from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.actions import execute_click, plan_click_for_answer, execute_playwright_click
from core.ai import OllamaClient
from core.pipeline import AIPipeline
from core.config import BotConfig, BotConfigUpdate, default_config_dict, merge_config
from core.parser import parse_question, ParsedQuestion
from core.browser import BotBrowser
from core.page_manager import PageManager

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

    def get_system_status(self) -> dict[str, Any]:
        import requests

        ollama_ok = False
        models = []
        host = ensure_http(self.config["ollama_host"])

        try:
            response = requests.get(f"{host.rstrip('/')}/api/tags", timeout=1.5)
            if response.ok:
                ollama_ok = True
                models = [m["name"] for m in response.json().get("models", [])]
        except Exception:
            pass

        tess_path = self.config.get("tesseract_cmd")
        tess_ok = Path(tess_path).exists() if tess_path else False

        return {
            "ollama_available": ollama_ok,
            "ollama_models": models,
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

        if self.config.get("mode") == "playwright":
            return self.run_once_playwright()
        else:
            return self.run_once_vision()

    def run_once_playwright(self) -> dict[str, Any]:
        self.log("Iniciando ciclo de resolución (Playwright)...", "INFO")
        
        url = self.config.get("url")
        if not url:
            self.log("URL no configurada para el modo Playwright.", "ERROR")
            raise ValueError("Configura la URL antes de iniciar.")

        if not self.browser:
            self.log("Abriendo navegador con Playwright...", "INFO")
            self.browser = BotBrowser(headless=self.config.get("pw_headless", False))
            self.browser.open(url, timeout_ms=self.config.get("pw_timeout_ms", 10000))
            self.log(f"Navegando a {url}...", "INFO")

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
                    },
                    "click_plan": None,
                    "think_time_ms": 0,
                    "qwen_activated": False,
                    "model_used": "ninguno",
                }
                self.last_run_info = run_data
                self.broadcast({"type": "result", "data": run_data})
                return run_data

        parsed = ParsedQuestion.from_dom(page_data)
        self.log(f"Pregunta: {parsed.question or '[No detectada]'}", "INFO")
        if parsed.options:
            self.log(f"Opciones: {', '.join(parsed.options)}", "INFO")
        else:
            self.log("No se detectaron opciones.", "INFO")

        bot_config = BotConfig.model_validate(self.config)
        pipeline = AIPipeline(bot_config)

        if not pipeline.reason_client.is_available():
            self.log(f"Ollama no disponible en {self.config['ollama_host']}", "ERROR")
            raise Exception(f"Ollama no responde en {self.config['ollama_host']}. Abre Ollama e instala el modelo.")

        self.log(f"Consultando sistema híbrido de IA...", "INFO")
        try:
            pipeline_result = pipeline.run(parsed, is_ocr_mode=False)
        except Exception as e:
            self.log(f"Error en consulta con Ollama: {str(e)}", "ERROR")
            raise

        self.log(f"Respuesta elegida: '{pipeline_result['answer']}' (Confianza: {pipeline_result['confidence']:.2f})", "SUCCESS")
        self.log(f"Explicacion: {pipeline_result['reasoning']}", "INFO")

        # Fase 5: Validación
        confidence = pipeline_result["confidence"]
        if confidence < bot_config.confidence_threshold:
            self.log(f"[WARNING] Confianza {confidence:.2f} por debajo del umbral ({bot_config.confidence_threshold:.2f}).", "WARNING")

        click_plan_info = None
        best_idx = -1
        
        # Verificar que coincida exactamente con una opción
        for idx, opt in enumerate(parsed.options):
            if opt == pipeline_result["answer"]:
                best_idx = idx
                break

        if best_idx == -1 and parsed.options:
            self.log(f"Error de validación: La respuesta de la IA '{pipeline_result['answer']}' no coincide exactamente con ninguna de las opciones disponibles.", "ERROR")
            # Continuar de forma segura sin hacer clic
        elif best_idx != -1:
            selector = parsed.selectors[best_idx]
            click_plan_info = {
                "target_text": parsed.options[best_idx],
                "score": 1.0,
                "selector": selector,
                "dry_run": not self.config["i_am_authorized"],
            }
            self.log(
                f"Plan de interacción: hacer clic en '{parsed.options[best_idx]}' [Selector: {selector}]",
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

        run_data = {
            "timestamp": time.strftime("%H:%M:%S"),
            "question": parsed.question,
            "options": parsed.options,
            "answer": {
                "answer": pipeline_result["answer"],
                "confidence": pipeline_result["confidence"],
                "reason": pipeline_result["reasoning"],
            },
            "click_plan": click_plan_info,
            "think_time_ms": pipeline_result["think_time_ms"],
            "qwen_activated": pipeline_result["qwen_activated"],
            "model_used": f"{bot_config.vision_model} + {bot_config.reason_model}" if pipeline_result["qwen_activated"] else bot_config.reason_model
        }

        self.last_run_info = run_data
        self.broadcast({"type": "result", "data": run_data})
        return run_data

    def run_once_vision(self) -> dict[str, Any]:
        from core.capture import capture_screen
        from core.ocr import run_ocr
        import io
        import base64

        self.log("Iniciando ciclo de resolucion (Vision)...", "INFO")
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

        # Convert image to base64
        buffered = io.BytesIO()
        capture.image.save(buffered, format="PNG")
        img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")

        parsed = parse_question(ocr.text, media=[img_str])

        self.log(f"Pregunta: {parsed.question or '[No detectada]'}", "INFO")
        if parsed.options:
            self.log(f"Opciones: {', '.join(parsed.options)}", "INFO")
        else:
            self.log("No se detectaron opciones.", "INFO")

        bot_config = BotConfig.model_validate(self.config)
        pipeline = AIPipeline(bot_config)

        if not pipeline.reason_client.is_available():
            self.log(f"Ollama no disponible en {self.config['ollama_host']}", "ERROR")
            raise Exception(f"Ollama no responde en {self.config['ollama_host']}. Abre Ollama e instala el modelo.")

        self.log(f"Consultando sistema híbrido de IA...", "INFO")
        try:
            pipeline_result = pipeline.run(parsed, is_ocr_mode=True)
        except Exception as e:
            self.log(f"Error en consulta con Ollama: {str(e)}", "ERROR")
            raise

        self.log(f"Respuesta elegida: '{pipeline_result['answer']}' (Confianza: {pipeline_result['confidence']:.2f})", "SUCCESS")
        self.log(f"Explicacion: {pipeline_result['reasoning']}", "INFO")

        # Fase 5: Validación
        confidence = pipeline_result["confidence"]
        if confidence < bot_config.confidence_threshold:
            self.log(f"[WARNING] Confianza {confidence:.2f} por debajo del umbral ({bot_config.confidence_threshold:.2f}).", "WARNING")

        click_plan_info = None
        clicked_successfully = False
        best_idx = -1
        
        # Verificar que coincida exactamente con una opción
        for idx, opt in enumerate(parsed.options):
            if opt == pipeline_result["answer"]:
                best_idx = idx
                break

        if best_idx == -1 and parsed.options:
            self.log(f"Error de validación: La respuesta de la IA '{pipeline_result['answer']}' no coincide exactamente con ninguna de las opciones disponibles.", "ERROR")
            # Continuar de forma segura sin hacer clic
        elif self.config["click"] and best_idx != -1:
            offset = (region_tuple[0], region_tuple[1]) if region_tuple else (0, 0)
            dry_run = not self.config["i_am_authorized"]

            self.log("Calculando coordenadas para el clic...", "INFO")
            plan = plan_click_for_answer(
                pipeline_result["answer"],
                ocr.boxes,
                region_offset=offset,
                min_score=self.config["min_click_score"],
                dry_run=dry_run,
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

                    self.page_manager.record(parsed.question, pipeline_result["answer"])

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
                "answer": pipeline_result["answer"],
                "confidence": pipeline_result["confidence"],
                "reason": pipeline_result["reasoning"],
            },
            "click_plan": click_plan_info,
            "think_time_ms": pipeline_result["think_time_ms"],
            "qwen_activated": pipeline_result["qwen_activated"],
            "model_used": f"{bot_config.vision_model} + {bot_config.reason_model}" if pipeline_result["qwen_activated"] else bot_config.reason_model
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
