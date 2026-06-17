"""
autopilot_runner.py — Motor de bucle para el Modo Autopilot DB.

Implementa:
  - Extracción DOM de preguntas y opciones.
  - Clic por índice/selector en Playwright.
  - Validación de acierto leyendo clases CSS del DOM.
  - Recarga de hoja (botón Reintentar o page.reload()).
  - Avance de hoja (botón Siguiente).
  - Bucle principal Paso A → B → C definido en las instrucciones.
  - Thread Qt (AutopilotRunnerThread) compatible con el widget existente.
"""
from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Optional

from core.browser import BotBrowser
from core.db_manager import DBManager

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
            "next_button": ["button.next", "a.next", ".btn-next", ".next-page", "button[class*='siguiente']"],
            "retry_button": ["button.retry", ".reintentar", "button[class*='retry']"],
        },
        "timings": {
            "feedback_wait_ms": 900,
            "after_click_wait_ms": 600,
            "reload_wait_ms": 2000,
            "next_wait_ms": 2500,
            "dom_stable_wait_ms": 500,
        },
        "browser": {
            "keep_open": False
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
        # Merge profundo para que falten claves no rompan nada
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
# JavaScript de extracción DOM
# ---------------------------------------------------------------------------

_JS_EXTRACT = r"""
() => {
    const cfg = {
        containerSel: "ul.form-items > li, .form-items > li, li[data-type='OM']",
        questionSel:  ".question, .pregunta, p, h2, h3, h4",
        inputSel:     "input[type='radio'], input[type='checkbox']"
    };

    // Buscar el primer contenedor con inputs SIN marcar
    const containers = Array.from(document.querySelectorAll(cfg.containerSel));
    let target = null;

    for (const c of containers) {
        const inputs = Array.from(c.querySelectorAll(cfg.inputSel));
        if (inputs.length > 0 && !inputs.some(i => i.checked)) {
            target = c;
            break;
        }
    }

    // Si todos están contestados, devolvemos null para avanzar hoja
    if (!target && containers.length > 0) return null;

    // Fallback: buscar pregunta directa en el body
    if (!target) {
        const qEl = document.querySelector(cfg.questionSel);
        if (!qEl) return null;
        target = document.body;
    }

    // Texto de la pregunta
    const qEl = target.querySelector(cfg.questionSel) || target;
    const questionText = (qEl.innerText || "").replace(/\s+/g, " ").trim();

    // Opciones
    const inputs = Array.from(target.querySelectorAll(cfg.inputSel));
    const options = [];

    const getSelector = (el) => {
        if (el.id) return "#" + el.id;
        if (el.getAttribute("data-op"))
            return `input[data-op="${el.getAttribute("data-op")}"]`;
        if (el.name && el.value)
            return `input[name="${el.name}"][value="${el.value}"]`;
        // nth-child fallback
        const parts = [];
        let cur = el;
        while (cur && cur !== document.body) {
            const tag = cur.nodeName.toLowerCase();
            let nth = 1;
            let sib = cur;
            while ((sib = sib.previousElementSibling)) nth++;
            parts.unshift(tag + ":nth-child(" + nth + ")");
            cur = cur.parentElement;
        }
        return parts.join(" > ");
    };

    for (const input of inputs) {
        // Buscar label asociado
        let labelText = "";
        let parent = input.parentElement;
        while (parent && parent !== target) {
            if (parent.tagName === "LABEL") { labelText = parent.innerText; break; }
            parent = parent.parentElement;
        }
        if (!labelText && input.id) {
            const lbl = document.querySelector(`label[for="${input.id}"]`);
            if (lbl) labelText = lbl.innerText;
        }
        if (!labelText) labelText = input.parentElement ? input.parentElement.innerText : "";

        // Buscar padre clickable (label o contenedor de opción)
        let clickEl = input;
        let p = input.parentElement;
        while (p && p !== target) {
            if (p.tagName === "LABEL") { clickEl = p; break; }
            p = p.parentElement;
        }

        options.push({
            texto:    labelText.replace(/\s+/g, " ").trim(),
            selector: getSelector(input),
            clickSelector: getSelector(clickEl),
        });
    }

    return { question: questionText, options };
}
"""

_JS_VALIDATE = r"""
(selector) => {
    // Verifica si el elemento (o sus ancestros/descendientes) tiene una clase de acierto/error
    try {
        const el = document.querySelector(selector);
        if (!el) return "unknown";

        const correctKeywords   = ["correct", "success", "right", "acert", "verdad"];
        const incorrectKeywords = ["incorrect", "wrong", "error", "fail", "incorrecto"];

        const checkEl = (node) => {
            const cls = (node.className || "").toLowerCase();
            const html = node.outerHTML.toLowerCase().substring(0, 500);
            if (correctKeywords.some(k => cls.includes(k) || html.includes(k))) return "correct";
            if (incorrectKeywords.some(k => cls.includes(k) || html.includes(k))) return "incorrect";
            return null;
        };

        // Checar el propio input y su label/parent
        let node = el;
        for (let i = 0; i < 5; i++) {
            const r = checkEl(node);
            if (r) return r;
            if (!node.parentElement || node === document.body) break;
            node = node.parentElement;
        }

        // Checar hijos del ancestro (li) por clases de resultado
        let ancestor = el;
        for (let i = 0; i < 3; i++) {
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
# AutopilotRunner
# ---------------------------------------------------------------------------

class AutopilotRunner:
    """
    Motor del Modo Autopilot DB.

    Flujo por hoja:
      A. Extraer preguntas y opciones.
      B. Por cada pregunta: consultar DB → responder desde DB
         o probar al azar hasta acertar y guardar en DB.
      C. Cuando no quedan preguntas sin responder → ir a la siguiente hoja.
    """

    def __init__(
        self,
        url: str,
        bot_config: dict[str, Any],
        log_callback: Callable[[str, str], None] | None = None,
        stats_callback: Callable[[dict], None] | None = None,
        keep_browser_open: bool = False,
    ) -> None:
        self.url = url
        self.bot_config = bot_config.dict() if hasattr(bot_config, "dict") and callable(getattr(bot_config, "dict")) else bot_config
        self.log_cb = log_callback or (lambda msg, lvl: print(f"[{lvl}] {msg}"))
        self.stats_cb = stats_callback or (lambda _: None)
        self.keep_browser_open = keep_browser_open

        self.ap_cfg = _load_autopilot_config()
        self.timings = self.ap_cfg["timings"]
        self.limits = self.ap_cfg["limits"]

        self.db = DBManager()
        self.browser: Optional[BotBrowser] = None

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
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass

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
    # Funciones auxiliares de DOM
    # ------------------------------------------------------------------

    def extraer_preguntas_y_opciones(self) -> list[dict] | None:
        """
        Extrae la pregunta actual (sin responder) y sus opciones desde el DOM.
        Retorna None si todas las preguntas de la hoja ya están respondidas.
        """
        if not self.browser or not self.browser.page:
            return None
        try:
            result = self.browser.page.evaluate(_JS_EXTRACT)
            if not result:
                return None
            # Devolvemos como lista de una pregunta (la primera sin responder)
            return [result]
        except Exception as exc:
            self._log(f"Error al extraer preguntas del DOM: {exc}", "ERROR")
            return None

    def hacer_clic_en_opcion(self, selector: str, click_selector: str | None = None) -> bool:
        """Hace clic en el input de la opción dada por selector."""
        if not self.browser or not self.browser.page:
            return False
        target = click_selector or selector
        if self._click_selector_with_fallback(target):
            return True
        if selector != target and self._click_selector_with_fallback(selector):
            return True
        self._log(f"Error al hacer clic en '{selector}' con todos los fallbacks.", "WARNING")
        return False

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

    def _js_click_selector(self, selector: str) -> bool:
        if not self.browser or not self.browser.page:
            return False
        try:
            clicked = self.browser.page.evaluate(
                """(sel) => {
                    const normalized = sel.trim();
                    const textMatch = normalized.match(/:has-text\(\s*["']([^"']+)["']\s*\)/);
                    if (textMatch) {
                        const expected = textMatch[1].trim();
                        const candidates = Array.from(document.querySelectorAll('button, a, input, label, span, div'));
                        for (const node of candidates) {
                            const value = ((node.innerText || node.value || "") + "").trim();
                            if (value.includes(expected)) {
                                node.click();
                                return true;
                            }
                        }
                        return false;
                    }
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

    def recargar_hoja_actual(self) -> bool:
        """
        Recarga la hoja actual sin avanzar a la siguiente.
        Intenta botón Reintentar → sino reload de la URL.
        """
        if not self.browser or not self.browser.page:
            return False

        retry_selectors = self.ap_cfg["selectors"]["retry_button"]

        # Buscar botón de reintento
        try:
            found_sel = self.browser.page.evaluate(_JS_FIND_BUTTON, retry_selectors)
            if found_sel:
                self._log("Botón 'Reintentar' encontrado. Haciendo clic...", "INFO")
                if self._click_selector_with_fallback(found_sel):
                    self.browser.page.wait_for_load_state("load", timeout=8000)
                    return True
                self._log("Clic en el botón 'Reintentar' falló. Intentando recarga manual...", "WARNING")
        except Exception:
            pass

        # Fallback: recargar la URL
        self._log("Recargando la URL actual para reiniciar la hoja...", "INFO")
        try:
            self.browser.page.reload(timeout=10000, wait_until="load")
            time.sleep(self.timings["reload_wait_ms"] / 1000)
            return True
        except Exception as exc:
            self._log(f"Error al recargar la hoja: {exc}", "ERROR")
            return False

    def ir_a_siguiente_hoja(self) -> bool:
        """
        Hace clic en el botón 'Siguiente' y espera la carga de la nueva hoja.
        """
        if not self.browser or not self.browser.page:
            return False

        next_selectors = self.ap_cfg["selectors"]["next_button"]

        try:
            found_sel = self.browser.page.evaluate(_JS_FIND_BUTTON, next_selectors)
            if found_sel:
                self._log(f"Botón 'Siguiente' encontrado ({found_sel}). Avanzando...", "INFO")
                if self._click_selector_with_fallback(found_sel):
                    time.sleep(self.timings["next_wait_ms"] / 1000)
                    self.browser.page.wait_for_load_state(
                        "load",
                        timeout=self.bot_config.get("pw_timeout_ms", 30000),
                    )
                    return True
                self._log("Clic en el botón 'Siguiente' falló. Intentando otro selector...", "WARNING")
        except Exception:
            pass

        # Fallback: buscar con Playwright locator con texto
        for text_hint in ["Siguiente", "Next", "Continuar", "Submit", "Enviar"]:
            try:
                selector = f"button:has-text('{text_hint}'), a:has-text('{text_hint}')"
                if self._click_selector_with_fallback(selector):
                    time.sleep(self.timings["next_wait_ms"] / 1000)
                    self.browser.page.wait_for_load_state(
                        "load",
                        timeout=self.bot_config.get("pw_timeout_ms", 30000),
                    )
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
        self._log(f"URL objetivo: {self.url}", "INFO")
        self._log(f"Registros en BD al inicio: {self.db.contar_registros()}", "INFO")

        # Abrir navegador
        self.browser = BotBrowser(headless=self.bot_config.get("pw_headless", False))
        try:
            self.browser.open(
                self.url,
                timeout_ms=self.bot_config.get("pw_timeout_ms", 10000),
            )
        except Exception as exc:
            self._log(f"Error al abrir el navegador: {exc}", "ERROR")
            self._shutdown()
            return

        max_hojas = self.limits.get("max_sheets", 10000)
        hojas_procesadas = 0

        # ── Paso A: Inicio de hoja ──────────────────────────────────────
        while self._running and hojas_procesadas < max_hojas:
            self._check_pause()
            if not self._running:
                break

            hojas_procesadas += 1
            self._log(f"── Procesando hoja {hojas_procesadas} ──", "INFO")

            # Extraer preguntas de esta hoja (iteramos pregunta a pregunta)
            pregunta_actual_idx = 0
            max_preguntas_hoja = 200   # salvaguarda

            while self._running and pregunta_actual_idx < max_preguntas_hoja:
                self._check_pause()
                if not self._running:
                    break

                # Obtener la pregunta actual (sin responder)
                pagina_data = self.extraer_preguntas_y_opciones()

                if not pagina_data:
                    # Ninguna pregunta sin responder → fin de hoja
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
                    pregunta_actual_idx += 1
                    continue

                self._log(
                    f"[P{pregunta_actual_idx + 1}] {texto_pregunta[:80]}...",
                    "INFO",
                )

                # ── Paso B: Consultar DB o probar al azar ──────────────
                hash_p = self.db.calcular_hash(texto_pregunta)
                respuesta_db = self.db.consultar_db(hash_p)

                if respuesta_db is not None:
                    # Responder desde DB
                    self._log(
                        f"  [DB] Respondiendo desde BD: '{respuesta_db}'", "SUCCESS"
                    )
                    # Buscar el índice en las opciones actuales por texto
                    opcion_encontrada = next(
                        (o for o in opciones if o["texto"].strip() == respuesta_db.strip()),
                        None,
                    )
                    if opcion_encontrada:
                        self.hacer_clic_en_opcion(
                            opcion_encontrada["selector"],
                            opcion_encontrada.get("clickSelector"),
                        )
                        self.stats["respondidas_desde_db"] += 1
                    else:
                        # Texto no coincide exactamente; intentar búsqueda difusa
                        self._log(
                            f"  [DB] Texto exacto no encontrado. Buscando similitud...",
                            "WARNING",
                        )
                        mejor = max(
                            opciones,
                            key=lambda o: _similarity(o["texto"], respuesta_db),
                        )
                        self._log(
                            f"  [DB] Mejor coincidencia: '{mejor['texto']}'", "INFO"
                        )
                        self.hacer_clic_en_opcion(
                            mejor["selector"], mejor.get("clickSelector")
                        )
                        self.stats["respondidas_desde_db"] += 1

                    pregunta_actual_idx += 1
                    self._emit_stats()
                    time.sleep(self.timings["dom_stable_wait_ms"] / 1000)
                    continue

                # No está en DB → probar al azar (con descarte)
                self._log(
                    f"  [AZAR] Pregunta desconocida. Iniciando búsqueda aleatoria...",
                    "WARNING",
                )
                descartadas: set[str] = set()   # textos de opciones descartadas
                max_intentos = min(
                    self.limits.get("max_intentos_por_pregunta", 8),
                    len(opciones),
                )
                acertada = False

                for intento in range(max_intentos):
                    if not self._running:
                        break
                    self._check_pause()

                    # Opciones disponibles (no descartadas)
                    disponibles = [o for o in opciones if o["texto"] not in descartadas]
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
                        descartadas.add(elegida["texto"])
                        continue

                    # Validar resultado
                    resultado = self.validar_acierto(elegida["selector"])
                    self._log(f"  [AZAR] Feedback DOM: {resultado}", "INFO")

                    if resultado == "correct":
                        self._log(
                            f"  [AZAR] ¡CORRECTO! Guardando en BD: '{elegida['texto']}'",
                            "SUCCESS",
                        )
                        self.db.guardar_en_db(hash_p, texto_pregunta, elegida["texto"])
                        self.stats["respondidas_al_azar"] += 1
                        self.stats["nuevas_guardadas"] += 1
                        acertada = True
                        pregunta_actual_idx += 1
                        self._emit_stats()
                        break

                    elif resultado == "incorrect":
                        self._log(
                            f"  [AZAR] Incorrecto. Descartando '{elegida['texto']}' y recargando hoja.",
                            "WARNING",
                        )
                        descartadas.add(elegida["texto"])
                        self.recargar_hoja_actual()

                        # Re-extraer opciones tras recarga (el DOM se destruyó)
                        nuevas_pagina = self.extraer_preguntas_y_opciones()
                        if nuevas_pagina:
                            opciones = nuevas_pagina[0].get("options", opciones)

                    else:
                        # "unknown" → asumir que es la última pregunta de la hoja
                        # o que la plataforma no da feedback inmediato.
                        # Avanzar pregunta de todas formas para no quedarse bloqueado.
                        self._log(
                            "  [AZAR] Feedback desconocido. Asumiendo avance de pregunta.",
                            "WARNING",
                        )
                        pregunta_actual_idx += 1
                        acertada = True   # evita log de error
                        break

                if not acertada and self._running:
                    self._log(
                        f"  [ERROR] No se pudo acertar la pregunta tras {max_intentos} intentos. "
                        "Posible cambio en la interfaz. Continuando...",
                        "ERROR",
                    )
                    pregunta_actual_idx += 1  # forzar avance para no bloquearse

            # ── Paso C: Avanzar hoja ────────────────────────────────────
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
    # Cierre
    # ------------------------------------------------------------------

    def _shutdown(self) -> None:
        """Cierra BD y navegador de forma limpia."""
        self._running = False
        # Flush pendientes en BD
        flushed = self.db.flush_buffer()
        if flushed:
            self._log(f"Buffer final: {flushed} registros escritos en BD.", "INFO")
        self.db.close()

        if self.browser:
            if self.keep_browser_open or self.ap_cfg.get("browser", {}).get("keep_open", False):
                self._log("Manteniendo navegador abierto según configuración de Autopilot.", "INFO")
            else:
                self._log("Cerrando navegador Playwright...", "INFO")
                try:
                    self.browser.close()
                except Exception:
                    pass
                self.browser = None


# ---------------------------------------------------------------------------
# Utilidad de similitud (adaptada de core/actions.py)
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
# Thread Qt — compatible con el widget existente
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
        con las del widget existente (log_signal, status_signal) más una
        nueva señal de estadísticas de BD.
        """
        log_signal    = pyqtSignal(str, str)   # (mensaje, nivel)
        status_signal = pyqtSignal(str)         # "running" | "paused" | "idle"
        db_stats_signal = pyqtSignal(dict)      # estadísticas de BD en tiempo real

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
