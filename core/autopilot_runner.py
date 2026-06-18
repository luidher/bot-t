"""
autopilot_runner.py — Motor de bucle para el Modo Autopilot DB.

Módulo completamente independiente: no requiere PyQt5, widget ni config externo.

Implementa:
  - Extracción DOM de preguntas y opciones (incluyendo data-op).
  - Clic por selector en Playwright con fallbacks.
  - Validación de acierto leyendo clases CSS del DOM.
  - Recarga de hoja (botón Reintentar o page.reload()).
  - Avance de hoja (botón Siguiente) solo cuando todas las respuestas son correctas.
  - Bucle principal: Paso A (extraer) → B (responder) → C (avanzar).
  - Guardado en BD por data-op (selector estable) + texto visible.
  - Thread Qt (AutopilotRunnerThread) opcional, compatible con el widget existente.
"""
from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from core.db_manager import DBManager

if TYPE_CHECKING:
    from core.browser import BotBrowser

AUTOPILOT_CONFIG_FILE = Path("autopilot_config.json")


# ---------------------------------------------------------------------------
# Helpers de configuración
# ---------------------------------------------------------------------------

def _load_autopilot_config() -> dict[str, Any]:
    """Carga autopilot_config.json; si falta, devuelve valores razonables."""
    defaults: dict[str, Any] = {
        "selectors": {
            "question_container": "ul.form-items > li, .form-items > li, li[data-type='OM']",
            "question_text": ".question, .pregunta, p, h2, h3, h4",
            "option_input": "input[type='radio'], input[type='checkbox']",
            "option_label": "label",
            "correct_markers": [".correct", "[class*='correct']", "[class*='success']"],
            "incorrect_markers": [".incorrect", "[class*='incorrect']", "[class*='wrong']", "[class*='error']"],
            "next_button": [
                "button.next", "a.next", ".btn-next", ".next-page",
                "button[class*='siguiente']", "input[type='submit'][value*='iguiente']",
                "button[class*='next']",
            ],
            "retry_button": [
                "button.retry", ".reintentar", "button[class*='retry']",
                "button[class*='reintentar']", ".btn-retry", "button[onclick*='reload']",
            ],
        },
        "timings": {
            "feedback_wait_ms": 900,
            "after_click_wait_ms": 600,
            "reload_wait_ms": 2000,
            "next_wait_ms": 2500,
            "dom_stable_wait_ms": 500,
        },
        "auth": {
            "wait_for_manual_auth": True,
            "manual_auth_timeout_sec": 300,
            "manual_auth_poll_sec": 1.0,
        },
        "browser": {
            "keep_open": False,
            "pw_timeout_ms": 120000
        },
        "limits": {
            "max_sheets": 10000,
            "max_intentos_por_pregunta": 8,
        },
    }
    if not AUTOPILOT_CONFIG_FILE.exists():
        return defaults
    try:
        with open(AUTOPILOT_CONFIG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for section, values in defaults.items():
            if section not in data:
                data[section] = values
            elif isinstance(values, dict):
                for k, v in values.items():
                    data[section].setdefault(k, v)
        return data
    except Exception as exc:
        print(f"[AUTOPILOT] Error cargando autopilot_config.json: {exc}. Usando defaults.")
        return defaults


# ---------------------------------------------------------------------------
# JavaScript de validación y navegación
# ---------------------------------------------------------------------------

_JS_VALIDATE = r"""
(selector) => {
    try {
        const el = document.querySelector(selector);
        if (!el) return "unknown";

        const correctKeywords   = ["correct", "success", "right", "acert", "verdad", "correcto"];
        const incorrectKeywords = ["incorrect", "wrong", "error", "fail", "incorrecto", "erroneo"];

        const checkEl = (node) => {
            const cls = (node.className || "").toLowerCase();
            const html = node.outerHTML.toLowerCase().substring(0, 500);
            if (correctKeywords.some(k => cls.includes(k) || html.includes(k))) return "correct";
            if (incorrectKeywords.some(k => cls.includes(k) || html.includes(k))) return "incorrect";
            return null;
        };

        // Checar el propio elemento y hasta 5 ancestros
        let node = el;
        for (let i = 0; i < 6; i++) {
            const r = checkEl(node);
            if (r) return r;
            if (!node.parentElement || node === document.body) break;
            node = node.parentElement;
        }

        // Checar el <li> ancestro (contenedor de opción)
        let ancestor = el;
        for (let i = 0; i < 4; i++) {
            if (!ancestor.parentElement) break;
            ancestor = ancestor.parentElement;
        }
        const r = checkEl(ancestor);
        if (r) return r;

        return "unknown";
    } catch(e) {
        return "unknown";
    }
}
"""

_JS_FIND_BUTTON = r"""
(selectorList) => {
    const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === "none" || style.visibility === "hidden" || parseFloat(style.opacity) === 0) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };

    const previousTargets = document.querySelectorAll('[data-ap-temp-target="true"]');
    previousTargets.forEach((node) => node.removeAttribute('data-ap-temp-target'));

    for (const sel of selectorList) {
        try {
            const elements = Array.from(document.querySelectorAll(sel));
            for (const el of elements) {
                if (!isVisible(el)) continue;
                el.setAttribute('data-ap-temp-target', 'true');
                return '[data-ap-temp-target="true"]';
            }
        } catch (_) {}
    }
    return null;
}
"""


# ---------------------------------------------------------------------------
# AutopilotRunner — Motor independiente
# ---------------------------------------------------------------------------

class AutopilotRunner:
    """
    Motor del Modo Autopilot DB. Completamente independiente de PyQt5/widget.

    Flujo por hoja:
      A. Extraer preguntas y opciones (incluyendo data-op).
      B. Por cada pregunta: consultar DB por hash → responder desde DB
         (usando data-op si disponible) o probar al azar hasta acertar
         y guardar en DB.
      C. Cuando no quedan preguntas sin responder → ir a la siguiente hoja.

    Parámetros:
      url             — URL del cuestionario a resolver.
      log_callback    — fn(msg: str, level: str) para recibir logs.
      stats_callback  — fn(stats: dict) para recibir estadísticas en tiempo real.
      keep_browser_open — mantener el navegador abierto tras terminar.
      browser         — instancia BotBrowser preexistente (opcional).
                        Si se pasa, NO se abre una URL nueva; se usa la página actual.
    """

    def __init__(
        self,
        url: str = "",
        log_callback: Callable[[str, str], None] | None = None,
        stats_callback: Callable[[dict], None] | None = None,
        keep_browser_open: bool = False,
        browser: Optional["BotBrowser"] = None,
        bot_config: dict[str, Any] | None = None,  # compat con widget
    ) -> None:
        self.url = url
        self.log_cb = log_callback or (lambda msg, lvl: print(f"[{lvl}] {msg}"))
        self.stats_cb = stats_callback or (lambda _: None)
        self.keep_browser_open = keep_browser_open

        # bot_config es opcional; solo se usa pw_timeout_ms y pw_headless
        _cfg = bot_config or {}
        if hasattr(_cfg, "dict") and callable(getattr(_cfg, "dict")):
            _cfg = _cfg.dict()
        self._pw_timeout_ms: int = int(_cfg.get("pw_timeout_ms", 120000))
        self._pw_headless: bool = bool(_cfg.get("pw_headless", False))

        self.ap_cfg = _load_autopilot_config()
        self.timings = self.ap_cfg["timings"]
        self.limits = self.ap_cfg["limits"]
        self.auth_cfg = self.ap_cfg["auth"]

        self.db = DBManager()
        self.browser: Optional["BotBrowser"] = browser
        self._owned_browser = browser is None  # solo cerramos el browser si lo creamos nosotros
        self.failed_questions_in_sheet: set[str] = set()

        # Estadísticas de sesión
        self.stats = {
            "total_registros_db": self.db.contar_registros(),
            "respondidas_desde_db": 0,
            "respondidas_al_azar": 0,
            "nuevas_guardadas": 0,
            "hojas_completadas": 0,
        }

        self._running = False
        self._paused = False

    # ------------------------------------------------------------------
    # Control externo
    # ------------------------------------------------------------------

    def stop(self) -> None:
        self._running = False

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str, level: str = "INFO") -> None:
        self.log_cb(msg, level)

    def _emit_stats(self) -> None:
        self.stats["total_registros_db"] = self.db.contar_registros()
        self.stats_cb(dict(self.stats))

    # ------------------------------------------------------------------
    # Normalización de datos de página
    # ------------------------------------------------------------------

    def _normalize_page_question(self, page_data: dict[str, Any] | None) -> dict[str, Any] | None:
        """Convierte BotBrowser.read_page al formato usado internamente por Autopilot."""
        if not page_data:
            return None

        question = str(page_data.get("question") or "").strip()
        raw_options = list(page_data.get("options") or [])
        selectors = list(page_data.get("selectors") or [])
        click_selectors = list(page_data.get("option_selectors") or selectors)
        data_ops = list(page_data.get("data_ops") or [])

        options: list[dict[str, str | None]] = []
        for idx, text in enumerate(raw_options):
            option_text = str(text or "").strip()
            selector = selectors[idx] if idx < len(selectors) else ""
            click_selector = click_selectors[idx] if idx < len(click_selectors) else selector
            data_op = data_ops[idx] if idx < len(data_ops) else ""
            if not option_text or not selector:
                continue
            options.append({
                "texto": option_text,
                "selector": selector,
                "clickSelector": click_selector or selector,
                "data_op": data_op,
            })

        if not question:
            return None

        return {
            "question": question,
            "options": options,
            "data_item": str(page_data.get("question_data_item") or ""),
        }

    def extraer_preguntas_y_opciones(self) -> list[dict] | None:
        """
        Extrae la pregunta actual (sin responder) y sus opciones desde el DOM.
        Retorna None si todas las preguntas de la hoja ya están respondidas.
        """
        if not self.browser or not self.browser.page:
            return None
        try:
            result = self.browser.read_page(skip_questions=self.failed_questions_in_sheet)
            question = self._normalize_page_question(result)
            if not question:
                return None
            return [question]
        except Exception as exc:
            self._log(f"Error al extraer preguntas del DOM: {exc}", "ERROR")
            return None

    # ------------------------------------------------------------------
    # Espera de autenticación manual
    # ------------------------------------------------------------------

    def _wait_for_manual_auth_and_questions(self) -> bool:
        """
        Deja el navegador abierto para login manual y comienza cuando detecta preguntas.
        """
        if not self.auth_cfg.get("wait_for_manual_auth", True):
            return True
        if not self.browser or not self.browser.page:
            return False

        timeout_sec = float(self.auth_cfg.get("manual_auth_timeout_sec", 300))
        poll_sec = max(float(self.auth_cfg.get("manual_auth_poll_sec", 1.0)), 0.2)
        started_at = time.monotonic()
        notified_wait = False

        self._log(
            "Navegador abierto. Autentícate manualmente y navega hasta la hoja de preguntas; "
            "el Autopilot iniciará cuando detecte una pregunta con opciones.",
            "INFO",
        )

        while self._running:
            self._check_pause()
            page_data = self.browser.read_page()
            question = self._normalize_page_question(page_data)
            if question and question.get("options"):
                self._log("Pregunta detectada. Iniciando flujo Autopilot DB.", "SUCCESS")
                return True
            if self._page_has_next_button():
                self._log("Botón Siguiente detectado. Iniciando flujo Autopilot DB.", "SUCCESS")
                return True

            if not notified_wait:
                self._log("Esperando autenticación manual o aparición de preguntas...", "INFO")
                notified_wait = True

            if timeout_sec > 0 and time.monotonic() - started_at >= timeout_sec:
                self._log(
                    f"No se detectaron preguntas después de {timeout_sec:.0f}s de espera.",
                    "ERROR",
                )
                return False

            time.sleep(poll_sec)

        return False

    def _page_has_next_button(self) -> bool:
        if not self.browser or not self.browser.page:
            return False
        try:
            next_selectors = self.ap_cfg["selectors"]["next_button"]
            return bool(self.browser.page.evaluate(_JS_FIND_BUTTON, next_selectors))
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Clic en opciones
    # ------------------------------------------------------------------

    def hacer_clic_en_opcion(self, selector: str, click_selector: str | None = None) -> bool:
        """Hace clic en la opción dada por selector."""
        if not self.browser or not self.browser.page:
            return False
        target = click_selector or selector
        if self._click_selector_with_fallback(target):
            return True
        if selector != target and self._click_selector_with_fallback(selector):
            return True
        self._log(f"Error al hacer clic en '{selector}' con todos los fallbacks.", "WARNING")
        return False

    def _js_click_selector(self, selector: str) -> bool:
        if not self.browser or not self.browser.page:
            return False
        try:
            clicked = self.browser.page.evaluate(
                r"""(sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return false;
                    el.click();
                    return true;
                }""",
                selector,
            )
            time.sleep(self.timings["after_click_wait_ms"] / 1000)
            return bool(clicked)
        except Exception as exc:
            self._log(f"Error al hacer clic vía JS en '{selector}': {exc}", "DEBUG")
            return False

    def _click_selector_with_fallback(self, selector: str) -> bool:
        if not selector or not self.browser or not self.browser.page:
            return False
        for click_kwargs in ({}, {"force": True}):
            try:
                self.browser.page.click(selector, timeout=5000, **click_kwargs)
                time.sleep(self.timings["after_click_wait_ms"] / 1000)
                return True
            except Exception:
                continue
        return self._js_click_selector(selector)

    # ------------------------------------------------------------------
    # Validación de acierto
    # ------------------------------------------------------------------

    def validar_acierto(self, selector: str) -> str:
        """
        Evalúa el DOM para determinar si el clic fue correcto.
        Retorna: 'correct' | 'incorrect' | 'unknown'
        """
        if not self.browser or not self.browser.page:
            return "unknown"
        try:
            time.sleep(self.timings["feedback_wait_ms"] / 1000)
            result = self.browser.page.evaluate(_JS_VALIDATE, selector)
            return str(result)
        except Exception as exc:
            self._log(f"Error al validar acierto: {exc}", "WARNING")
            return "unknown"

    # ------------------------------------------------------------------
    # Navegación entre hojas
    # ------------------------------------------------------------------

    def recargar_hoja_actual(self) -> bool:
        """Recarga la hoja actual sin avanzar a la siguiente."""
        if not self.browser or not self.browser.page:
            return False

        retry_selectors = self.ap_cfg["selectors"]["retry_button"]
        try:
            found_sel = self.browser.page.evaluate(_JS_FIND_BUTTON, retry_selectors)
            if found_sel:
                self._log("Botón 'Reintentar' encontrado. Haciendo clic...", "INFO")
                if self._click_selector_with_fallback(found_sel):
                    self.browser.page.wait_for_load_state("load", timeout=self._pw_timeout_ms)
                    return True
                self._log("Clic en 'Reintentar' falló. Intentando recarga manual...", "WARNING")
        except Exception:
            pass

        self._log("Recargando la URL actual para reiniciar la hoja...", "INFO")
        try:
            self.browser.page.reload(timeout=self._pw_timeout_ms, wait_until="load")
            time.sleep(self.timings["reload_wait_ms"] / 1000)
            return True
        except Exception as exc:
            self._log(f"Error al recargar la hoja: {exc}", "ERROR")
            return False

    def ir_a_siguiente_hoja(self) -> bool:
        """Hace clic en el botón 'Siguiente' y espera la carga de la nueva hoja."""
        if not self.browser or not self.browser.page:
            return False

        next_selectors = self.ap_cfg["selectors"]["next_button"]
        try:
            found_sel = self.browser.page.evaluate(_JS_FIND_BUTTON, next_selectors)
            if found_sel:
                self._log(f"Botón 'Siguiente' encontrado. Avanzando...", "INFO")
                if self._click_selector_with_fallback(found_sel):
                    time.sleep(self.timings["next_wait_ms"] / 1000)
                    self.browser.page.wait_for_load_state("load", timeout=self._pw_timeout_ms)
                    return True
                self._log("Clic en 'Siguiente' falló. Intentando otro selector...", "WARNING")
        except Exception:
            pass

        for text_hint in ["Siguiente", "Next", "Continuar", "Submit", "Enviar"]:
            try:
                selector = f"button:has-text('{text_hint}'), a:has-text('{text_hint}')"
                if self._click_selector_with_fallback(selector):
                    time.sleep(self.timings["next_wait_ms"] / 1000)
                    self.browser.page.wait_for_load_state("load", timeout=self._pw_timeout_ms)
                    self._log(f"Avanzado con botón '{text_hint}'.", "SUCCESS")
                    return True
            except Exception:
                continue

        self._log("No se encontró botón 'Siguiente'. ¿Fin del formulario?", "WARNING")
        return False

    # ------------------------------------------------------------------
    # Pausa interactiva
    # ------------------------------------------------------------------

    def _check_pause(self) -> None:
        while self._paused and self._running:
            time.sleep(0.3)

    # ------------------------------------------------------------------
    # Bucle principal
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Bucle principal: Paso A → B → C para cada hoja.
        Termina cuando no hay botón 'Siguiente' o se alcanza max_sheets.
        """
        self._running = True
        self._log("=== Modo Autopilot DB INICIADO ===", "SUCCESS")
        self._log(f"Registros en BD al inicio: {self.db.contar_registros()}", "INFO")

        # Abrir navegador si no se proporcionó uno externo
        opened_browser = False
        if not self.browser:
            from core.browser import BotBrowser
            self.browser = BotBrowser(headless=self._pw_headless)
            self._owned_browser = True
            if self.url:
                try:
                    self.browser.open(self.url, timeout_ms=self._pw_timeout_ms)
                    opened_browser = True
                    self._log(f"Navegador abierto en: {self.url}", "INFO")
                except Exception as exc:
                    self._log(f"Error al abrir el navegador: {exc}", "ERROR")
                    self._shutdown()
                    return
            else:
                self._log("No se proporcionó URL; asumiendo navegador ya en posición.", "WARNING")

        if opened_browser and not self._wait_for_manual_auth_and_questions():
            self._shutdown()
            return

        max_hojas = self.limits.get("max_sheets", 10000)
        hojas_procesadas = 0

        # ── Paso A: Inicio de hoja ──────────────────────────────────────────
        while self._running and hojas_procesadas < max_hojas:
            self._check_pause()
            if not self._running:
                break

            self.failed_questions_in_sheet.clear()
            hojas_procesadas += 1
            self._log(f"── Procesando hoja {hojas_procesadas} ──", "INFO")

            pregunta_actual_idx = 0
            max_preguntas_hoja = 200

            while self._running and pregunta_actual_idx < max_preguntas_hoja:
                self._check_pause()
                if not self._running:
                    break

                # Obtener la primera pregunta sin responder
                pagina_data = self.extraer_preguntas_y_opciones()

                if not pagina_data:
                    # Todas respondidas → fin de hoja
                    self._log(
                        f"Hoja {hojas_procesadas} completada "
                        f"({pregunta_actual_idx} preguntas respondidas).",
                        "SUCCESS",
                    )
                    self.stats["hojas_completadas"] += 1
                    self._emit_stats()
                    break

                pregunta_obj = pagina_data[0]
                texto_pregunta = pregunta_obj["question"]
                opciones: list[dict] = pregunta_obj["options"]

                if not opciones:
                    self._log(
                        f"Pregunta #{pregunta_actual_idx + 1} sin opciones detectadas. Saltando...",
                        "WARNING",
                    )
                    self.failed_questions_in_sheet.add(texto_pregunta)
                    pregunta_actual_idx += 1
                    continue

                self._log(
                    f"[P{pregunta_actual_idx + 1}] {texto_pregunta[:80]}...",
                    "INFO",
                )

                # ── Paso B: Consultar DB o probar al azar ──────────────────
                hash_p = self.db.calcular_hash(texto_pregunta)
                respuesta_db = self.db.consultar_db(hash_p)

                if respuesta_db is not None:
                    self._responder_desde_db(respuesta_db, opciones, texto_pregunta)
                    pregunta_actual_idx += 1
                    self._emit_stats()
                    time.sleep(self.timings["dom_stable_wait_ms"] / 1000)
                    continue

                # No está en DB → probar al azar con descarte
                acertada = self._buscar_al_azar(hash_p, texto_pregunta, opciones)
                if not acertada and self._running:
                    self._log(
                        f"  [ERROR] No se pudo acertar la pregunta tras "
                        f"{self.limits.get('max_intentos_por_pregunta', 8)} intentos. Continuando...",
                        "ERROR",
                    )
                    self.failed_questions_in_sheet.add(texto_pregunta)
                pregunta_actual_idx += 1

            # ── Paso C: Avanzar hoja ────────────────────────────────────────
            if not self._running:
                break

            self._log("Intentando avanzar a la siguiente hoja...", "INFO")
            if not self.ir_a_siguiente_hoja():
                self._log(
                    "No se pudo avanzar. Fin del formulario o error de navegación.", "SUCCESS"
                )
                break

        self._log(
            f"=== Autopilot DB FINALIZADO. Hojas: {hojas_procesadas}. "
            f"Desde DB: {self.stats['respondidas_desde_db']}. "
            f"Al azar: {self.stats['respondidas_al_azar']}. "
            f"Nuevas guardadas: {self.stats['nuevas_guardadas']}. ===",
            "SUCCESS",
        )
        self._shutdown()

    # ------------------------------------------------------------------
    # Lógica de respuesta desde BD
    # ------------------------------------------------------------------

    def _responder_desde_db(
        self,
        respuesta_db: dict,
        opciones: list[dict],
        texto_pregunta: str,
    ) -> None:
        texto_correcto = respuesta_db.get("texto", "")
        selector_correcto = respuesta_db.get("selector", "")

        self._log(f"  [DB] Respondiendo desde BD: '{texto_correcto}'", "SUCCESS")

        # 1. Intentar por data-op (selector más estable)
        if selector_correcto:
            opcion_por_selector = next(
                (o for o in opciones if o.get("data_op") == selector_correcto),
                None,
            )
            if opcion_por_selector:
                self.hacer_clic_en_opcion(
                    opcion_por_selector["selector"],
                    opcion_por_selector.get("clickSelector"),
                )
                self.stats["respondidas_desde_db"] += 1
                return

        # 2. Intentar por texto exacto
        opcion_por_texto = next(
            (o for o in opciones if o["texto"].strip() == texto_correcto.strip()),
            None,
        )
        if opcion_por_texto:
            self.hacer_clic_en_opcion(
                opcion_por_texto["selector"],
                opcion_por_texto.get("clickSelector"),
            )
            self.stats["respondidas_desde_db"] += 1
            return

        # 3. Búsqueda por similitud (fallback)
        self._log("  [DB] Texto exacto no encontrado. Buscando similitud...", "WARNING")
        mejor = max(opciones, key=lambda o: _similarity(o["texto"], texto_correcto))
        self._log(f"  [DB] Mejor coincidencia: '{mejor['texto']}'", "INFO")
        self.hacer_clic_en_opcion(mejor["selector"], mejor.get("clickSelector"))
        self.stats["respondidas_desde_db"] += 1

    # ------------------------------------------------------------------
    # Lógica de búsqueda aleatoria con descarte
    # ------------------------------------------------------------------

    def _buscar_al_azar(
        self,
        hash_p: str,
        texto_pregunta: str,
        opciones: list[dict],
    ) -> bool:
        """
        Prueba opciones al azar, descartando las incorrectas.
        Guarda la correcta en la BD con su data-op.
        Retorna True si encontró la respuesta correcta.
        """
        self._log("  [AZAR] Pregunta desconocida. Iniciando búsqueda aleatoria...", "WARNING")

        # Descarte por data-op si disponible, sino por texto
        descartadas_ops: set[str] = set()    # data-op descartados
        descartadas_txt: set[str] = set()    # textos descartados (cuando no hay data-op)

        max_intentos = min(
            self.limits.get("max_intentos_por_pregunta", 8),
            len(opciones),
        )
        acertada = False

        for intento in range(max_intentos):
            if not self._running:
                break
            self._check_pause()

            # Filtrar opciones disponibles
            disponibles = [
                o for o in opciones
                if (o.get("data_op") not in descartadas_ops if o.get("data_op") else True)
                and o["texto"] not in descartadas_txt
            ]
            if not disponibles:
                self._log(
                    f"  [AZAR] Sin opciones disponibles tras {intento} intentos.", "ERROR"
                )
                break

            elegida = random.choice(disponibles)
            self._log(
                f"  [AZAR] Intento {intento + 1}/{max_intentos}: '{elegida['texto']}'",
                "INFO",
            )

            clic_ok = self.hacer_clic_en_opcion(
                elegida["selector"], elegida.get("clickSelector")
            )
            if not clic_ok:
                self._log("  [AZAR] Clic fallido. Descartando opción.", "WARNING")
                if elegida.get("data_op"):
                    descartadas_ops.add(elegida["data_op"])
                descartadas_txt.add(elegida["texto"])
                continue

            resultado = self.validar_acierto(elegida["selector"])
            self._log(f"  [AZAR] Feedback DOM: {resultado}", "INFO")

            if resultado == "correct":
                selector_a_guardar = elegida.get("data_op") or elegida["selector"]
                self._log(
                    f"  [AZAR] ¡CORRECTO! Guardando en BD: '{elegida['texto']}' "
                    f"[op={selector_a_guardar[:30]}...]",
                    "SUCCESS",
                )
                self.db.guardar_en_db(
                    hash_p,
                    texto_pregunta,
                    elegida["texto"],
                    selector_correcto=selector_a_guardar,
                    inmediato=True,
                )
                self.stats["respondidas_al_azar"] += 1
                self.stats["nuevas_guardadas"] += 1
                self._emit_stats()
                acertada = True
                break

            elif resultado == "incorrect":
                self._log(
                    f"  [AZAR] Incorrecto. Descartando '{elegida['texto']}' y recargando hoja.",
                    "WARNING",
                )
                if elegida.get("data_op"):
                    descartadas_ops.add(elegida["data_op"])
                descartadas_txt.add(elegida["texto"])
                self.recargar_hoja_actual()

                # Re-extraer opciones tras recarga
                nuevas_pagina = self.extraer_preguntas_y_opciones()
                if nuevas_pagina:
                    nuevas_opciones = nuevas_pagina[0].get("options", opciones)
                    # Mantener descarte: actualizar lista
                    opciones = [
                        o for o in nuevas_opciones
                        if o["texto"] not in descartadas_txt
                        and (not o.get("data_op") or o.get("data_op") not in descartadas_ops)
                    ] + [
                        o for o in nuevas_opciones
                        if o["texto"] in descartadas_txt
                        or (o.get("data_op") and o.get("data_op") in descartadas_ops)
                    ]
                    # Dejamos opciones en orden completo pero el filtro está en disponibles
                    opciones = nuevas_opciones

            else:
                # "unknown" → asumir avance de pregunta para no bloquearse
                self._log(
                    "  [AZAR] Feedback desconocido. Asumiendo avance de pregunta.",
                    "WARNING",
                )
                acertada = True
                break

        return acertada

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        """Cierra BD y navegador de forma limpia."""
        self._running = False
        flushed = self.db.flush_buffer()
        if flushed:
            self._log(f"Buffer final: {flushed} registros escritos en BD.", "INFO")
        self.db.close()

        if self.browser and self._owned_browser:
            if self.keep_browser_open or self.ap_cfg.get("browser", {}).get("keep_open", False):
                self._log("Manteniendo navegador abierto según configuración.", "INFO")
            else:
                self._log("Cerrando navegador Playwright...", "INFO")
                try:
                    self.browser.close()
                except Exception:
                    pass
                self.browser = None


# ---------------------------------------------------------------------------
# Utilidad de similitud
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    """Similitud de Jaccard entre dos strings (tokenizados por palabras)."""
    if not a or not b:
        return 0.0
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


# ---------------------------------------------------------------------------
# Thread Qt — compatible con el widget existente (opcional)
# ---------------------------------------------------------------------------

try:
    from PyQt5.QtCore import QThread, pyqtSignal
    _HAS_PYQT = True
except ImportError:
    _HAS_PYQT = False

if _HAS_PYQT:
    class AutopilotRunnerThread(QThread):
        """
        Thread Qt que envuelve AutopilotRunner y emite señales compatibles
        con las del widget existente.
        """
        log_signal    = pyqtSignal(str, str)
        status_signal = pyqtSignal(str)
        db_stats_signal = pyqtSignal(dict)

        def __init__(
            self,
            url: str,
            bot_config: dict,
            keep_browser_open: bool = False,
            parent: object = None,
        ) -> None:
            super().__init__(parent)
            self._url = url
            self._bot_config = bot_config
            self._keep_browser_open = keep_browser_open
            self._runner: Optional[AutopilotRunner] = None

        def run(self) -> None:
            self.status_signal.emit("running")
            self._runner = AutopilotRunner(
                url=self._url,
                bot_config=self._bot_config,
                log_callback=lambda msg, lvl: self.log_signal.emit(msg, lvl),
                stats_callback=lambda stats: self.db_stats_signal.emit(stats),
                keep_browser_open=self._keep_browser_open,
            )
            try:
                self._runner.run()
            except Exception as exc:
                self.log_signal.emit(f"Error crítico en Autopilot: {exc}", "ERROR")
            finally:
                self.status_signal.emit("idle")

        def pause(self) -> None:
            if self._runner:
                self._runner.pause()
            self.status_signal.emit("paused")

        def resume(self) -> None:
            if self._runner:
                self._runner.resume()
            self.status_signal.emit("running")

        def stop(self) -> None:
            if self._runner:
                self._runner.stop()
