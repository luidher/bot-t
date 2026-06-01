from __future__ import annotations

import argparse
import sys
import time

from core.actions import execute_click, plan_click_for_answer
from core.ai import OllamaClient
from core.capture import Region, capture_screen
from core.ocr import run_ocr
from core.parser import parse_question


def main() -> int:
    args = parse_args()
    region = parse_region(args.region)
    client = OllamaClient(model=args.model, host=args.ollama_host)

    if not client.is_available():
        print("[ERROR] Ollama no responde. Inicia Ollama y verifica el modelo.")
        print(f"        Host: {args.ollama_host}")
        print(f"        Modelo esperado: {args.model}")
        return 2

    while True:
        run_once(args=args, client=client, region=region)
        if not args.loop:
            break
        time.sleep(args.interval)

    return 0


def run_once(args: argparse.Namespace, client: OllamaClient, region: Region | None) -> None:
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

    answer = client.choose_answer(parsed)
    print("\n=== RESPUESTA IA LOCAL ===")
    print(f"Respuesta: {answer.answer}")
    print(f"Confianza: {answer.confidence:.2f}")
    print(f"Razon: {answer.reason}")

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
        description="Bot local de vision + OCR + Ollama para demos autorizadas.",
    )
    parser.add_argument("--model", default="llama3.1", help="Modelo local de Ollama.")
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
    return parser.parse_args()


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
