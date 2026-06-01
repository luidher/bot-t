from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from core.actions import execute_click, plan_click_for_answer
from core.ai import OllamaClient
from core.config import BotConfig, BotConfigUpdate, default_config_dict, merge_config
from core.parser import parse_question

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
        self.pending_click_plan = None
        self.config = default_config_dict()
        self.last_run_info: dict[str, Any] = {}
        self._thread: threading.Thread | None = None

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
            "pending_confirm": self.pending_click_plan is not None,
            "config": self.config,
            "last_run": self.last_run_info,
        }

    def execute_scroll_action(self, amount: int | None = None) -> None:
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
        from core.capture import capture_screen
        from core.ocr import run_ocr

        self.log("Iniciando ciclo de resolucion...", "INFO")
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

        self.log(f"Pregunta: {parsed.question or '[No detectada]'}", "INFO")
        if parsed.options:
            self.log(f"Opciones: {', '.join(parsed.options)}", "INFO")
        else:
            self.log("No se detectaron opciones.", "INFO")

        client = OllamaClient(
            model=self.config["model"],
            host=ensure_http(self.config["ollama_host"]),
        )

        if not client.is_available():
            self.log(f"Ollama no disponible en {self.config['ollama_host']}", "ERROR")
            raise Exception(f"Ollama no responde en {self.config['ollama_host']}. Abre Ollama e instala el modelo.")

        self.log(f"Consultando modelo '{self.config['model']}'...", "INFO")
        try:
            answer = client.choose_answer(parsed)
        except Exception as e:
            self.log(f"Error en consulta con Ollama: {str(e)}", "ERROR")
            raise

        self.log(f"Respuesta elegida: '{answer.answer}' (Confianza: {answer.confidence:.2f})", "SUCCESS")
        self.log(f"Explicacion: {answer.reason}", "INFO")

        click_plan_info = None
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

                    if self.config.get("auto_scroll", False):
                        self.execute_scroll_action()
            else:
                self.log("No se pudo mapear la respuesta seleccionada con ninguna coordenada confiable.", "WARNING")

        run_data = {
            "timestamp": time.strftime("%H:%M:%S"),
            "ocr_text": ocr.text,
            "question": parsed.question,
            "options": parsed.options,
            "answer": {
                "answer": answer.answer,
                "confidence": answer.confidence,
                "reason": answer.reason,
            },
            "click_plan": click_plan_info,
        }

        self.last_run_info = run_data
        self.broadcast({"type": "result", "data": run_data})
        return run_data

    def start_loop(self) -> None:
        if self.loop_active:
            return
        self.loop_active = True
        self.broadcast({"type": "status", "loop_running": True})
        self.log("Modo continuo (bucle automatico) INICIADO.", "INFO")
        self._thread = threading.Thread(target=self._loop_worker, daemon=True)
        self._thread.start()

    def stop_loop(self) -> None:
        if not self.loop_active:
            return
        self.loop_active = False
        self.pending_click_plan = None
        self.broadcast({"type": "status", "loop_running": False})
        self.log("Modo continuo (bucle automatico) DETENIDO.", "INFO")

    def handle_confirm(self, approved: bool) -> dict[str, bool]:
        if not self.pending_click_plan:
            raise RuntimeError("No hay ningun clic pendiente de confirmacion.")

        plan = self.pending_click_plan
        self.pending_click_plan = None

        if approved:
            self.log(f"Clic aprobado por el usuario en ({plan.x}, {plan.y})", "INFO")
            execute_click(plan)
            self.log("Clic ejecutado correctamente.", "SUCCESS")

            if self.config.get("auto_scroll", False):
                self.execute_scroll_action()

            return {"success": True, "executed": True}

        self.log("Clic rechazado por el usuario.", "WARNING")
        self.broadcast({"type": "cancel_confirm"})
        return {"success": True, "executed": False}

    def _loop_worker(self) -> None:
        self.pending_click_plan = None
        while self.loop_active:
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
                if self.pending_click_plan:
                    break
                time.sleep(0.1)
                elapsed += 0.1
