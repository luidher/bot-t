from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.actions import execute_click, plan_click_for_answer
from core.ai import is_model_available
from core.config import BotConfig, BotConfigUpdate, default_config_dict, merge_config
from core.media_extractor import MediaItem, extract_media
from core.parser import parse_question, ParsedQuestion
from core.browser import BotBrowser
from core.page_manager import PageManager
from core.pipeline import DecisionPipeline

CONFIG_FILE = Path("web_config.json")


def ensure_http(host: str) -> str:
    """Guarantee the host string has an http:// or https:// prefix."""
    host = host.strip()
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host.rstrip("/")


class BotRunner:
    def __init__(
        self,
        config_file: Path = CONFIG_FILE,
        event_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.config_file = config_file
        self.event_callback = event_callback
        self.loop_active = False
        self.paused = False
        self.pending_click_plan = None
        self.config = default_config_dict()
        self.last_run_info: dict[str, Any] = {}
        self._thread: threading.Thread | None = None

        self.browser: BotBrowser | None = None
        self.page_manager: PageManager | None = None

        self.load_config()
        self.apply_tesseract_path()

    def load_config(self) -> None:
        if self.config_file.exists():
            try:
                with open(self.config_file, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.config = BotConfig.model_validate(
                        {**default_config_dict(), **saved}
                    ).model_dump(mode="json")
                print("[INFO] Configuracion cargada desde web_config.json")
            except ValidationError as e:
                print(f"[WARNING] Configuracion invalida en web_config.json; usando valores por defecto: {e}")
            except Exception as e:
                print(f"[WARNING] No se pudo cargar configuracion: {e}")

    def save_config(self) -> None:
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[ERROR] No se pudo guardar la configuracion: {e}")

    def update_config(self, new_config: BotConfigUpdate) -> dict[str, Any]:
        self.config = merge_config(self.config, new_config)
        self.save_config()
        self.apply_tesseract_path()
        self.log("Configuracion actualizada y guardada.", "INFO")
        self.broadcast({"type": "config", "config": self.config})
        return self.config

    def apply_tesseract_path(self) -> None:
        cmd = self.config.get("tesseract_cmd")
        if cmd and Path(cmd).exists():
            try:
                import pytesseract
            except ImportError:
                return

            pytesseract.pytesseract.tesseract_cmd = cmd

    def _build_pipeline(self) -> DecisionPipeline:
        """Build a DecisionPipeline from the current config dict."""
        cfg = BotConfig.model_validate(self.config)
        return DecisionPipeline(cfg)

    def _wait_for_manual_auth_and_questions(self) -> bool:
        if not self.config.get("wait_for_manual_auth", True):
            return True

        if not self.browser:
            return False

        timeout_sec = int(self.config.get("manual_auth_timeout_sec", 300))
        poll_sec = float(self.config.get("manual_auth_poll_sec", 1.0))
        poll_sec = max(poll_sec, 0.2)

        if self.config.get("use_external_chrome_for_auth", True) and not self.browser.page:
            self.log(
                "Se abrió Chrome del sistema para autenticación manual. Completa el login y pulsa Enter para continuar.",
                "INFO",
            )
            try:
                input("Autenticación manual completada. Presiona Enter para continuar...")
            except EOFError:
                self.log("No se detectó entrada interactiva; se continuará con la conexión al navegador existente.", "WARNING")
            try:
                self.browser.connect_to_existing_browser(
                    url=self.config.get("url"),
                    timeout_ms=self.config.get("pw_timeout_ms", 60000),
                    cdp_endpoint=None,
                )
                self.log("Conectado a la sesión de Chrome existente por CDP.", "SUCCESS")
            except Exception as exc:
                self.log(f"No se pudo conectar a la sesión de Chrome existente: {exc}", "ERROR")
                return False

        if not self.browser.page:
            return False

        start_at = time.monotonic()
        notified_wait = False

        while self.browser and self.browser.page:
            if self.paused:
                time.sleep(0.2)
                continue

            page_data = self.browser.read_page()
            if page_data and page_data.get("question") and page_data.get("options"):
                self.log("Pregunta detectada después de la autenticación. Continuando ejecución.", "SUCCESS")
                return True

            if not notified_wait:
                self.log(
                    "Navegador abierto. Autentícate manualmente y espera a que aparezca el formulario.",
                    "INFO",
                )
                notified_wait = True

            if timeout_sec > 0 and time.monotonic() - start_at >= timeout_sec:
                self.log(
                    f"No se detectaron preguntas tras {timeout_sec} segundos de espera manual.",
                    "ERROR",
                )
                return False

            time.sleep(poll_sec)

        return False

    def _pipeline_model_used(self, qwen_activated: bool) -> str:
        reason_model = self.config.get("reason_model", "deepseek-r1:8b")
        if qwen_activated:
            return f"{self.config.get('vision_model', 'qwen2.5-vl')} + {reason_model}"
        return str(reason_model)

    def get_system_status(self) -> dict[str, Any]:
        import requests

        ollama_ok = False
        models = []
        host = ensure_http(self.config["ollama_host"])

        reason_model_ok = False
        vision_model_ok = False

        try:
            response = requests.get(f"{host.rstrip('/')}/api/tags", timeout=1.5)
            if response.ok:
                ollama_ok = True
                models = [m["name"] for m in response.json().get("models", [])]
                reason_model_ok = is_model_available(models, self.config.get("reason_model", "deepseek-r1:8b"))
                vision_model_ok = is_model_available(models, self.config.get("vision_model", "qwen2.5-vl"))
        except Exception:
            pass

        tess_path = self.config.get("tesseract_cmd")
        tess_ok = Path(tess_path).exists() if tess_path else False

        return {
            "ollama_available": ollama_ok,
            "ollama_models": models,
            "reason_model_available": reason_model_ok,
            "vision_model_available": vision_model_ok,
            "tesseract_available": tess_ok,
            "loop_running": self.loop_active,
            "paused": self.paused,
            "pending_confirm": self.pending_click_plan is not None,
            "config": self.config,
            "last_run": self.last_run_info,
        }

    def execute_scroll_action(self, amount: int | None = None) -> None:
        if self.config.get("mode") == "playwright" and self.browser and self.browser.page:
            scroll_val = amount if amount is not None else self.config.get("scroll_amount", 300)
            self.log(f"Simulando scroll de {scroll_val} px en Playwright...", "INFO")
            try:
                self.browser.page.evaluate(f"window.scrollBy(0, {scroll_val})")
                self.log("Scroll completado.", "SUCCESS")
            except Exception as e:
                self.log(f"Error al simular scroll en Playwright: {e}", "ERROR")
            return

        import pyautogui

        scroll_val = amount if amount is not None else self.config.get("scroll_amount", -300)
        delay = self.config.get("scroll_delay", 1.0)

        self.log(f"Simulando scroll de {scroll_val} unidades...", "INFO")

        try:
            reg = self.config["region"]
            if reg:
                rx, ry, rw, rh = reg
                cx = rx + rw // 2
                cy = ry + rh // 2
            else:
                screen_w, screen_h = pyautogui.size()
                cx = screen_w // 2
                cy = screen_h // 2

            pyautogui.moveTo(cx, cy, duration=0.15)
            pyautogui.scroll(scroll_val)
            time.sleep(delay)
            self.log("Scroll completado.", "SUCCESS")
        except Exception as e:
            self.log(f"Error al simular scroll: {e}", "ERROR")

    def broadcast(self, data: dict[str, Any]) -> None:
        if self.event_callback is not None:
            self.event_callback(data)

    def log(self, message: str, level: str = "INFO") -> None:
        print(f"[{level}] {message}")
        self.broadcast(
            {
                "type": "log",
                "message": message,
                "level": level,
                "timestamp": time.strftime("%H:%M:%S"),
            }
        )

    def capture_only(self) -> str:
        from core.capture import capture_screen

        self.apply_tesseract_path()
        reg = self.config["region"]
        region_tuple = tuple(reg) if reg else None

        Path("screenshots").mkdir(exist_ok=True)
        capture = capture_screen(region=region_tuple, filename="latest_web_capture.png")

        self.broadcast(
            {
                "type": "screenshot",
                "path": f"/api/screenshot/latest?t={int(time.time() * 1000)}",
            }
        )
        return str(capture.path)

    def run_once(self) -> dict[str, Any]:
        if not self.page_manager:
            self.page_manager = PageManager(max_pages=self.config.get("max_pages", 50))

        mode = self.config.get("mode", "auto")
        if mode == "auto":
            if self.config.get("url"):
                return self.run_once_auto_playwright()
            else:
                return self.run_once_auto_vision()
        elif mode == "playwright":
            return self.run_once_auto_playwright()
        else:
            return self.run_once_auto_vision()

    def run_once_playwright(self) -> dict[str, Any]:
        """Legacy wrapper for playwright execution."""
        return self.run_once_auto_playwright()

    def run_once_vision(self) -> dict[str, Any]:
        """Legacy wrapper for vision execution."""
        return self.run_once_auto_vision()

    def run_once_auto_playwright(self) -> dict[str, Any]:
        self.log("Iniciando ciclo de resolución inteligente (Playwright)...", "INFO")
        
        url = self.config.get("url")
        if not url:
            self.log("URL no configurada para el modo Playwright/Auto.", "ERROR")
            raise ValueError("Configura la URL antes de iniciar.")

        if not self.browser:
            self.log("Preparando flujo de navegador para autenticación manual y automatización posterior.", "INFO")
            self.browser = BotBrowser(
                headless=self.config.get("pw_headless", False),
                browser_type=self.config.get("browser_type", "chromium")
            )
            if self.config.get("use_external_chrome_for_auth", True):
                self.log("Abriendo Chrome del sistema para autenticación manual sin Playwright.", "INFO")
                self.browser.launch_external_browser(
                    url=url,
                    timeout_ms=self.config.get("pw_timeout_ms", 60000),
                    executable=self.config.get("chrome_executable"),
                )
            else:
                self.browser.open(url, timeout_ms=self.config.get("pw_timeout_ms", 60000))
                self.log(f"Navegando a {url}...", "INFO")

            if self.config.get("wait_for_manual_auth", True):
                if not self._wait_for_manual_auth_and_questions():
                    self.log("No hubo autenticación/manual input suficiente. Abortando ejecución.", "ERROR")
                    raise RuntimeError("Timeout esperando autenticación manual o formulario.")

        self.log("Buscando preguntas sin responder en el DOM...", "INFO")
        page_data = self.browser.read_page()

        if not page_data:
            self.log("No se detectaron preguntas sin responder en esta página.", "INFO")
            if self.config.get("auto_next", True):
                self.log("Intentando avanzar a la siguiente página...", "INFO")
                if self.page_manager.try_next(browser=self.browser, config=self):
                    self.log(f"Avanzado a página {self.page_manager.current_page}.", "SUCCESS")
                    time.sleep(self.config.get("next_wait_sec", 2.0))
                    # Read again after transition
                    page_data = self.browser.read_page()
                else:
                    self.log("No se pudo avanzar a la siguiente página o se alcanzó el límite.", "WARNING")
            
            if not page_data:
                self.log("Fin del formulario o sin preguntas.", "SUCCESS")
                run_data = {
                    "timestamp": time.strftime("%H:%M:%S"),
                    "question": "[No detectada / Fin de formulario]",
                    "options": [],
                    "answer": {
                        "answer": "[Ninguna]",
                        "confidence": 1.0,
                        "reason": "Todas las preguntas resueltas.",
                        "think_time_ms": 0,
                    },
                    "click_plan": None,
                    "qwen_activated": False,
                    "model_used": "ninguno",
                    "visual_descriptions": None,
                    "confidence_threshold": self.config.get("confidence_threshold", 0.70),
                }
                self.last_run_info = run_data
                self.broadcast({"type": "result", "data": run_data})
                return run_data

        parsed = ParsedQuestion.from_dom(page_data)
        media_items: list[MediaItem] = []
        if self.config.get("vision_enabled", True) and self.browser and self.browser.page:
            try:
                media_items = extract_media(
                    self.browser.page,
                    parsed.question_selector or "body",
                    parsed.option_selectors or parsed.selectors,
                )
            except Exception as e:
                self.log(f"[MEDIA WARNING] Error al extraer recursos visuales: {e}", "WARNING")
        
        # --- FASE 1: Detección de Pregunta ---
        visual_elements_detected = len(media_items) > 0
        phase1_result = {
            "question_detected": bool(parsed.question),
            "options_detected": len(parsed.options) > 0,
            "visual_elements_detected": visual_elements_detected
        }
        self.log(f"[FASE 1] Detección de Pregunta: {json.dumps(phase1_result, ensure_ascii=False)}", "INFO")
        self.log(f"Pregunta: {parsed.question or '[No detectada]'}", "INFO")
        if parsed.options:
            self.log(f"Opciones: {', '.join(parsed.options)}", "INFO")
        else:
            self.log("No se detectaron opciones.", "INFO")

        # --- Hybrid Pipeline ---
        pipeline = self._build_pipeline()

        # --- FASE 2: Evaluación de Suficiencia del DOM ---
        if not visual_elements_detected:
            self.log("[FASE 2] Suficiencia del DOM: El DOM es suficiente (pregunta textual). Omitiendo visión y OCR.", "SUCCESS")
            try:
                answer, qwen_activated, visual_descs = pipeline.run(
                    question=parsed.question,
                    options=parsed.options,
                    media_items=[],
                    is_dom_mode=True,
                    ocr_texts=None,
                    ocr_context="",
                )
            except Exception as e:
                self.log(f"Error en pipeline híbrida: {str(e)}", "ERROR")
                raise
        else:
            # Hay elementos visuales
            # --- FASE 3: Detección de Contenido Visual ---
            self.log(f"[FASE 3] Contenido Visual: Detectados {len(media_items)} elementos visuales.", "INFO")

            # --- FASES 7 & 8: Análisis Visual y Razonamiento/Validación ---
            self.log(f"Ejecutando pipeline híbrida (Reason: {self.config['reason_model']})...", "INFO")
            try:
                answer, qwen_activated, visual_descs = pipeline.run(
                    question=parsed.question,
                    options=parsed.options,
                    media_items=media_items,
                    is_dom_mode=True,
                    ocr_texts=None,
                    ocr_context="",
                )
            except Exception as e:
                self.log(f"Error en pipeline híbrida: {str(e)}", "ERROR")
                raise

        model_used = self._pipeline_model_used(qwen_activated)
        if qwen_activated:
            self.log(f"Qwen2.5-VL activado para análisis visual.", "INFO")

        self.log(f"Respuesta elegida: '{answer.answer}' (Confianza: {answer.confidence:.2f})", "SUCCESS")
        self.log(f"Razonamiento: {answer.reasoning}", "INFO")
        self.log(f"Tiempo de razonamiento: {answer.think_time_ms} ms", "INFO")

        # Confidence threshold warning
        confidence_threshold = self.config.get("confidence_threshold", 0.70)
        if answer.confidence < confidence_threshold:
            self.log(
                f"⚠ Confianza ({answer.confidence:.2f}) por debajo del umbral ({confidence_threshold:.2f}).",
                "WARNING",
            )

        if self.config.get("log_reasoning", False):
            self.log(f"[REASONING LOG] {answer.reasoning}", "INFO")

        click_plan_info = None
        if parsed.options:
            from core.actions import _similarity
            best_idx = -1
            best_score = 0.0
            for idx, opt in enumerate(parsed.options):
                score = _similarity(answer.answer, opt)
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if (
                best_idx != -1
                and best_idx < len(parsed.selectors)
                and best_score >= self.config.get("min_click_score", 0.58)
            ):
                selector = parsed.selectors[best_idx]
                click_plan_info = {
                    "target_text": parsed.options[best_idx],
                    "score": best_score,
                    "selector": selector,
                    "dry_run": not self.config["i_am_authorized"],
                }
                self.log(
                    f"Plan de interacción: hacer clic en '{parsed.options[best_idx]}' [Selector: {selector}, Score: {best_score:.2f}]",
                    "INFO",
                )

                if self.config.get("confirm", False):
                    self.log("Requiere confirmacion del usuario para proceder.", "WARNING")
                    self.pending_click_plan = click_plan_info
                    self.broadcast({"type": "pending_confirm", "plan": click_plan_info})
                else:
                    self.log("Ejecutando clic automático...", "INFO")
                    if not click_plan_info["dry_run"]:
                        self.browser.click_option(selector)
                        self.log("Clic enviado exitosamente.", "SUCCESS")
                    else:
                        self.log("Modo seguro activo: clic simulado (sin acción real).", "WARNING")

                    self.page_manager.record(parsed.question, parsed.options[best_idx])

                    if self.config.get("auto_scroll", False):
                        self.execute_scroll_action()
            else:
                self.log("No se pudo mapear la respuesta seleccionada con ninguna opción del DOM.", "WARNING")
        else:
            self.log("No hay opciones del DOM disponibles para ejecutar clic.", "WARNING")

        run_data = {
            "timestamp": time.strftime("%H:%M:%S"),
            "question": parsed.question,
            "options": parsed.options,
            "answer": {
                "answer": answer.answer,
                "confidence": answer.confidence,
                "reason": answer.reasoning,
                "think_time_ms": answer.think_time_ms,
            },
            "click_plan": click_plan_info,
            "qwen_activated": qwen_activated,
            "model_used": model_used,
            "visual_descriptions": visual_descs,
            "confidence_threshold": confidence_threshold,
        }

        self.last_run_info = run_data
        self.broadcast({"type": "result", "data": run_data})
        return run_data

    def run_once_auto_vision(self) -> dict[str, Any]:
        from core.capture import capture_screen
        from core.ocr import run_ocr

        self.log("Iniciando ciclo de resolución inteligente (Visión/OCR)...", "INFO")
        self.apply_tesseract_path()

        reg = self.config["region"]
        region_tuple = tuple(reg) if reg else None

        self.log(f"Capturando pantalla (Region: {region_tuple or 'Pantalla Completa'})...", "INFO")
        try:
            capture = capture_screen(region=region_tuple, filename="latest_web_capture.png")
        except Exception as e:
            self.log(f"Error en captura de pantalla: {str(e)}", "ERROR")
            raise

        self.broadcast(
            {
                "type": "screenshot",
                "path": f"/api/screenshot/latest?t={int(time.time() * 1000)}",
            }
        )

        self.log("Ejecutando OCR con Tesseract...", "INFO")
        try:
            ocr = run_ocr(
                capture.image,
                lang=self.config["lang"],
                psm=self.config["psm"],
                preprocess=not self.config["no_preprocess"],
            )
        except Exception as e:
            self.log(f"Error en OCR: {str(e)}", "ERROR")
            raise

        self.log(f"OCR completo. Detectados {len(ocr.text)} caracteres.", "INFO")
        parsed = parse_question(ocr.text)

        # --- FASE 1: Detección de Pregunta (OCR/Visión) ---
        self.log(f"Pregunta: {parsed.question or '[No detectada]'}", "INFO")
        if parsed.options:
            self.log(f"Opciones: {', '.join(parsed.options)}", "INFO")
        else:
            self.log("No se detectaron opciones.", "INFO")

        # --- Hybrid Pipeline ---
        pipeline = self._build_pipeline()

        # En modo Visión, la captura es el recurso visual para Qwen
        media_items = [MediaItem(path=str(capture.path), role="question", selector="screen_capture")]

        # --- FASE 2: Evaluación de Suficiencia ---
        has_visual = pipeline.detect_visual_content(parsed.question, parsed.options, media_items, is_dom_mode=False)
        
        qwen_activated = False
        visual_descs = None
        
        if not has_visual:
            self.log("[FASE 2] Suficiencia: La pregunta es completamente textual (según palabras clave y contornos). Omitiendo Qwen.", "SUCCESS")
            try:
                answer, qwen_activated, visual_descs = pipeline.run(
                    question=parsed.question,
                    options=parsed.options,
                    media_items=[],
                    is_dom_mode=False,
                    ocr_texts=None,
                    ocr_context="",
                )
            except Exception as e:
                self.log(f"Error en pipeline híbrida: {str(e)}", "ERROR")
                raise
        else:
            self.log("[FASE 3] Contenido visual relevante detectado en la captura de pantalla.", "INFO")
            ocr_context = ocr.text
            self.log(f"Ejecutando pipeline híbrida con visión (Reason: {self.config['reason_model']})...", "INFO")
            try:
                answer, qwen_activated, visual_descs = pipeline.run(
                    question=parsed.question,
                    options=parsed.options,
                    media_items=media_items,
                    is_dom_mode=False,
                    ocr_texts=[ocr.text],
                    ocr_context=ocr_context,
                )
            except Exception as e:
                self.log(f"Error en pipeline híbrida: {str(e)}", "ERROR")
                raise

        model_used = self._pipeline_model_used(qwen_activated)
        if qwen_activated:
            self.log(f"Qwen2.5-VL activado para análisis visual.", "INFO")

        self.log(f"Respuesta elegida: '{answer.answer}' (Confianza: {answer.confidence:.2f})", "SUCCESS")
        self.log(f"Razonamiento: {answer.reasoning}", "INFO")
        self.log(f"Tiempo de razonamiento: {answer.think_time_ms} ms", "INFO")

        # Confidence threshold warning
        confidence_threshold = self.config.get("confidence_threshold", 0.70)
        if answer.confidence < confidence_threshold:
            self.log(
                f"⚠ Confianza ({answer.confidence:.2f}) por debajo del umbral ({confidence_threshold:.2f}).",
                "WARNING",
            )

        if self.config.get("log_reasoning", False):
            self.log(f"[REASONING LOG] {answer.reasoning}", "INFO")

        click_plan_info = None
        clicked_successfully = False
        if self.config["click"]:
            offset = (region_tuple[0], region_tuple[1]) if region_tuple else (0, 0)
            dry_run = not self.config["i_am_authorized"]

            self.log("Calculando coordenadas para el clic...", "INFO")
            plan = plan_click_for_answer(
                answer.answer,
                ocr.boxes,
                region_offset=offset,
                min_score=self.config["min_click_score"],
                dry_run=dry_run,
                answer_index=answer.index,
            )

            if plan:
                click_plan_info = {
                    "target_text": plan.target_text,
                    "score": plan.score,
                    "x": plan.x,
                    "y": plan.y,
                    "dry_run": plan.dry_run,
                }
                self.log(
                    f"Plan de interaccion: hacer clic en '{plan.target_text}' ({plan.x}, {plan.y}) "
                    f"[Score: {plan.score:.2f}, Modo seguro: {plan.dry_run}]",
                    "INFO",
                )

                if self.config["confirm"]:
                    self.log("Requiere confirmacion del usuario para proceder.", "WARNING")
                    self.pending_click_plan = plan
                    self.broadcast({"type": "pending_confirm", "plan": click_plan_info})
                else:
                    self.log("Ejecutando clic automatico...", "INFO")
                    execute_click(plan)
                    if plan.dry_run:
                        self.log("Modo seguro activo: clic simulado (sin accion real).", "WARNING")
                    else:
                        self.log("Clic enviado exitosamente.", "SUCCESS")
                        clicked_successfully = True

                    self.page_manager.record(parsed.question, answer.answer)

                    if self.config.get("auto_scroll", False):
                        self.execute_scroll_action()
            else:
                self.log("No se pudo mapear la respuesta seleccionada con ninguna coordenada confiable.", "WARNING")

        # Handle page transition in Vision mode
        if clicked_successfully and self.config.get("auto_next", True):
            self.log("Esperando antes de avanzar de página...", "INFO")
            time.sleep(self.config.get("next_wait_sec", 2.0))
            self.log("Buscando botón 'Siguiente' en la pantalla...", "INFO")
            if self.page_manager.try_next(region=region_tuple, config=self):
                self.log(f"Avanzado a página {self.page_manager.current_page}.", "SUCCESS")

        run_data = {
            "timestamp": time.strftime("%H:%M:%S"),
            "ocr_text": ocr.text,
            "question": parsed.question,
            "options": parsed.options,
            "answer": {
                "answer": answer.answer,
                "confidence": answer.confidence,
                "reason": answer.reasoning,
                "think_time_ms": answer.think_time_ms,
            },
            "click_plan": click_plan_info,
            "qwen_activated": qwen_activated,
            "model_used": model_used,
            "visual_descriptions": visual_descs,
            "confidence_threshold": confidence_threshold,
        }

        self.last_run_info = run_data
        self.broadcast({"type": "result", "data": run_data})
        return run_data

    def start_loop(self) -> None:
        if self.loop_active:
            return
        self.loop_active = True
        self.paused = False
        self.broadcast({"type": "status", "loop_running": True})
        self.log("Modo continuo (bucle automatico) INICIADO.", "INFO")
        self._thread = threading.Thread(target=self._loop_worker, daemon=True)
        self._thread.start()

    def stop_loop(self) -> None:
        if not self.loop_active:
            return
        self.loop_active = False
        self.paused = False
        self.pending_click_plan = None
        self.broadcast({"type": "status", "loop_running": False})
        self.log("Modo continuo (bucle automatico) DETENIDO.", "INFO")

    def pause_loop(self) -> None:
        if not self.loop_active or self.paused:
            return
        self.paused = True
        self.broadcast({"type": "status", "loop_running": True, "paused": True})
        self.log("Modo continuo PAUSADO.", "WARNING")

    def resume_loop(self) -> None:
        if not self.loop_active or not self.paused:
            return
        self.paused = False
        self.broadcast({"type": "status", "loop_running": True, "paused": False})
        self.log("Modo continuo REANUDADO.", "INFO")

    def handle_confirm(self, approved: bool) -> dict[str, bool]:
        if not self.pending_click_plan:
            raise RuntimeError("No hay ningun clic pendiente de confirmacion.")

        plan = self.pending_click_plan
        self.pending_click_plan = None

        if approved:
            if self.config.get("mode") == "playwright":
                self.log(f"Clic aprobado por el usuario en selector: {plan['selector']}", "INFO")
                if not plan["dry_run"]:
                    self.browser.click_option(plan["selector"])
                    self.log("Clic ejecutado correctamente.", "SUCCESS")
                else:
                    self.log("Modo seguro activo: clic simulado (sin accion real).", "WARNING")
                
                # Record it
                self.page_manager.record(self.last_run_info.get("question", ""), plan["target_text"])
            else:
                self.log(f"Clic aprobado por el usuario en ({plan.x}, {plan.y})", "INFO")
                execute_click(plan)
                self.log("Clic ejecutado correctamente.", "SUCCESS")

                # Record it
                self.page_manager.record(self.last_run_info.get("question", ""), plan.target_text)

            if self.config.get("auto_scroll", False):
                self.execute_scroll_action()

            return {"success": True, "executed": True}

        self.log("Clic rechazado por el usuario.", "WARNING")
        self.broadcast({"type": "cancel_confirm"})
        return {"success": True, "executed": False}

    def _loop_worker(self) -> None:
        self.pending_click_plan = None
        self.page_manager = PageManager(max_pages=self.config.get("max_pages", 50))
        while self.loop_active:
            if self.paused:
                time.sleep(0.5)
                continue
            if self.pending_click_plan:
                time.sleep(0.5)
                continue

            try:
                self.run_once()
            except Exception as e:
                self.log(f"Error durante ejecucion en bucle: {str(e)}", "ERROR")

            interval = self.config["interval"]
            elapsed = 0.0
            while elapsed < interval and self.loop_active:
                if self.paused or self.pending_click_plan:
                    break
                time.sleep(0.1)
                elapsed += 0.1

        # Close playwright browser if it was open
        if self.browser:
            self.log("Cerrando navegador Playwright...", "INFO")
            try:
                self.browser.close()
            except Exception as e:
                print(f"[ERROR] Error al cerrar navegador: {e}")
            self.browser = None


# Qt integration if PyQt5 is installed
try:
    from PyQt5.QtCore import QThread, pyqtSignal
    HAS_PYQT = True
except ImportError:
    HAS_PYQT = False

if HAS_PYQT:
    class BotRunnerThread(QThread):
        log_signal = pyqtSignal(str, str)
        status_signal = pyqtSignal(str)
        result_signal = pyqtSignal(dict)
        screenshot_signal = pyqtSignal(str)

        def __init__(self, runner: BotRunner) -> None:
            super().__init__()
            self.runner = runner
            self.original_callback = self.runner.event_callback
            self.runner.event_callback = self._on_event

        def _on_event(self, event: dict[str, Any]) -> None:
            if self.original_callback:
                try:
                    self.original_callback(event)
                except Exception:
                    pass

            etype = event.get("type")
            if etype == "log":
                self.log_signal.emit(event.get("message", ""), event.get("level", "INFO"))
            elif etype == "status":
                loop_running = event.get("loop_running", False)
                paused = event.get("paused", False)
                if paused:
                    self.status_signal.emit("paused")
                elif loop_running:
                    self.status_signal.emit("running")
                else:
                    self.status_signal.emit("idle")
            elif etype == "result":
                self.result_signal.emit(event.get("data", {}))
            elif etype == "screenshot":
                self.screenshot_signal.emit(event.get("path", ""))

        def run(self) -> None:
            self.runner.start_loop()
            while self.runner.loop_active:
                time.sleep(0.5)
