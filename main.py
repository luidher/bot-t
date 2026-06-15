from __future__ import annotations

import argparse
import sys
import time

from core.actions import execute_click, plan_click_for_answer
from core.ai import is_model_available
from core.capture import Region, capture_screen
from core.config import BotConfig
from core.media_extractor import MediaItem
from core.ocr import run_ocr
from core.parser import parse_question
from core.pipeline import DecisionPipeline


def main() -> int:
    args = parse_args()
    region = parse_region(args.region)

    # Build config from CLI args
    cfg = BotConfig(
        reason_model=args.reason_model,
        vision_model=args.vision_model,
        ollama_host=args.ollama_host,
        vision_enabled=args.vision_enabled,
        confidence_threshold=args.confidence_threshold,
        log_reasoning=args.log_reasoning,
    )

    # Verify models are available
    import requests
    host = cfg.ensure_http()
    try:
        resp = requests.get(f"{host}/api/tags", timeout=5)
        if not resp.ok:
            print("[ERROR] Ollama no responde. Inicia Ollama y verifica los modelos.")
            return 2
        models = [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        print("[ERROR] Ollama no responde. Inicia Ollama y verifica los modelos.")
        print(f"        Host: {args.ollama_host}")
        return 2

    if not is_model_available(models, cfg.reason_model):
        print(f"[ERROR] Modelo de razonamiento '{cfg.reason_model}' no encontrado en Ollama.")
        print(f"        Modelos disponibles: {', '.join(models)}")
        return 2

    if cfg.vision_enabled and not is_model_available(models, cfg.vision_model):
        print(f"[WARNING] Modelo de visión '{cfg.vision_model}' no encontrado en Ollama.")
        print(f"          Se desactivará el análisis visual.")
        cfg.vision_enabled = False

    print(f"[INFO] Modelo de razonamiento: {cfg.reason_model}")
    print(f"[INFO] Modelo de visión: {cfg.vision_model} ({'activado' if cfg.vision_enabled else 'desactivado'})")
    print(f"[INFO] Umbral de confianza: {cfg.confidence_threshold}")

    pipeline = DecisionPipeline(cfg)

    while True:
        run_once(args=args, pipeline=pipeline, config=cfg, region=region)
        if not args.loop:
            break
        time.sleep(args.interval)

    return 0


def run_once(
    args: argparse.Namespace,
    pipeline: DecisionPipeline,
    config: BotConfig,
    region: Region | None,
) -> None:
    capture = capture_screen(region=region)
    ocr = run_ocr(capture.image, lang=args.lang, psm=args.psm, preprocess=not args.no_preprocess)
    parsed = parse_question(ocr.text)

    print("\n=== CAPTURA ===")
    print(capture.path)

    print("\n=== TEXTO OCR ===")
    print(ocr.text or "[sin texto detectado]")

    print("\n=== PREGUNTA ===")
    print(parsed.question or "[no detectada]")

    print("\n=== OPCIONES ===")
    if parsed.options:
        for index, option in enumerate(parsed.options, start=1):
            print(f"{index}. {option}")
    else:
        print("[sin opciones detectadas]")

    # Execute pipeline (the screenshot is the visual resource for OCR mode)
    media_items = [MediaItem(path=str(capture.path), role="question", selector="screen_capture")]

    try:
        answer, qwen_activated, visual_descs = pipeline.run(
            question=parsed.question,
            options=parsed.options,
            media_items=media_items,
            is_dom_mode=False,
        )
    except Exception as e:
        print(f"\n[ERROR] Error en pipeline: {e}")
        return

    model_used = config.reason_model
    if qwen_activated:
        model_used = f"{config.vision_model} + {config.reason_model}"

    print("\n=== RESPUESTA IA LOCAL ===")
    print(f"Modelo: {model_used}")
    print(f"Qwen activado: {'Sí' if qwen_activated else 'No'}")
    print(f"Respuesta: {answer.answer}")
    print(f"Confianza: {answer.confidence:.2f}")
    print(f"Razonamiento: {answer.reasoning}")
    print(f"Tiempo de razonamiento: {answer.think_time_ms} ms")

    # Confidence warning
    if answer.confidence < config.confidence_threshold:
        print(f"\n⚠ ADVERTENCIA: Confianza ({answer.confidence:.2f}) por debajo del umbral ({config.confidence_threshold:.2f}).")

    # Log visual descriptions if present
    if qwen_activated and visual_descs:
        print("\n=== ANÁLISIS VISUAL (Qwen) ===")
        import json
        print(json.dumps(visual_descs, indent=2, ensure_ascii=False))

    if not args.click:
        return

    offset = (region[0], region[1]) if region else (0, 0)
    plan = plan_click_for_answer(
        answer.answer,
        ocr.boxes,
        region_offset=offset,
        min_score=args.min_click_score,
        dry_run=not args.i_am_authorized,
    )

    print("\n=== PLAN DE INTERACCION ===")
    if plan is None:
        print("No se encontro una zona fiable para hacer clic.")
        return

    print(f"Texto objetivo: {plan.target_text}")
    print(f"Score OCR: {plan.score:.2f}")
    print(f"Coordenadas: ({plan.x}, {plan.y})")

    if args.confirm and not confirm("Ejecutar clic? [s/N]: "):
        print("Clic cancelado por el usuario.")
        return

    execute_click(plan)
    if plan.dry_run:
        print("Modo seguro: no se hizo clic. Usa --i-am-authorized para habilitarlo.")
    else:
        print("Clic ejecutado.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Bot local de vision + OCR + Ollama (Híbrido: Qwen2.5-VL + DeepSeek-R1).",
    )
    parser.add_argument("--reason-model", default="deepseek-r1:8b", help="Modelo de razonamiento (DeepSeek).")
    parser.add_argument("--vision-model", default="qwen2.5-vl", help="Modelo de visión (Qwen2.5-VL).")
    parser.add_argument("--ollama-host", default="http://localhost:11434")
    parser.add_argument("--lang", default="spa+eng", help="Idiomas de Tesseract.")
    parser.add_argument("--psm", type=int, default=6, help="Page segmentation mode de Tesseract.")
    parser.add_argument("--region", help="Region x,y,w,h. Ejemplo: 100,200,900,500")
    parser.add_argument("--loop", action="store_true", help="Analiza en ciclo.")
    parser.add_argument("--interval", type=float, default=3.0, help="Segundos entre ciclos.")
    parser.add_argument("--no-preprocess", action="store_true", help="Desactiva mejora de imagen.")
    parser.add_argument("--click", action="store_true", help="Calcula y prepara clic sobre la respuesta.")
    parser.add_argument("--confirm", action="store_true", help="Pide confirmacion antes de hacer clic.")
    parser.add_argument(
        "--i-am-authorized",
        action="store_true",
        help="Habilita clic real en un entorno propio/autorizado.",
    )
    parser.add_argument("--min-click-score", type=float, default=0.58)
    parser.add_argument("--no-vision", action="store_true", help="Desactiva el análisis visual con Qwen.")
    parser.add_argument("--confidence-threshold", type=float, default=0.70, help="Umbral mínimo de confianza.")
    parser.add_argument("--log-reasoning", action="store_true", help="Registra el razonamiento completo.")
    args = parser.parse_args()
    args.vision_enabled = not args.no_vision
    return args


def parse_region(value: str | None) -> Region | None:
    if not value:
        return None

    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise SystemExit("--region debe tener formato x,y,w,h")

    try:
        x, y, width, height = [int(part) for part in parts]
    except ValueError as exc:
        raise SystemExit("--region solo acepta numeros enteros") from exc

    if width <= 0 or height <= 0:
        raise SystemExit("El ancho y alto de --region deben ser mayores que cero")

    return (x, y, width, height)


def confirm(prompt: str) -> bool:
    return input(prompt).strip().lower() in {"s", "si", "y", "yes"}


if __name__ == "__main__":
    sys.exit(main())
