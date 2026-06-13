from __future__ import annotations

import json
from typing import Any

from core.ai import AIAnswer, OllamaClient
from core.config import BotConfig
from core.parser import ParsedQuestion
from core.vision import QwenVisionClient

VISUAL_KEYWORDS = [
    "imagen",
    "gráfico",
    "grafica",
    "tabla",
    "diagrama",
    "figura",
    "dibujo",
    "esquema",
    "mapa",
    "chart",
    "table",
    "image",
    "figure",
    "diagram",
    "plot",
    "ilustracion",
    "ilustración",
    "fórmula",
    "formula",
]


def has_visual_content(parsed: ParsedQuestion, is_ocr_mode: bool) -> bool:
    """Evalúa si la pregunta posee imágenes, diagramas, tablas o gráficas por heurística."""
    # Si estamos en modo DOM y extrajimos elementos de imagen/svg/canvas
    if not is_ocr_mode and parsed.media:
        return True

    # Buscar palabras clave en el texto de la pregunta y opciones
    text_to_check = (parsed.question + " " + " ".join(parsed.options)).lower()
    for kw in VISUAL_KEYWORDS:
        if kw in text_to_check:
            return True

    return False


class AIPipeline:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.vision_client = QwenVisionClient(
            model=config.vision_model,
            host=config.ensure_http(),
        )
        self.reason_client = OllamaClient(
            model=config.reason_model,
            host=config.ensure_http(),
        )

    def run(self, parsed: ParsedQuestion, is_ocr_mode: bool) -> dict[str, Any]:
        """Orquesta la ejecución de Qwen2.5-VL y DeepSeek-R1:8b."""
        qwen_activated = False
        visual_json = ""
        visual_info = {}

        # Determinar si activamos Qwen
        if self.config.vision_enabled and has_visual_content(parsed, is_ocr_mode):
            if parsed.media:
                qwen_activated = True
                print(
                    f"[PIPELINE] Activando Qwen2.5-VL para análisis visual ({len(parsed.media)} recursos)..."
                )
                visual_info = self.vision_client.analyze_image(
                    question=parsed.question,
                    options=parsed.options,
                    media_base64=parsed.media,
                )
                visual_json = json.dumps(visual_info, ensure_ascii=False, indent=2)
            else:
                print(
                    "[PIPELINE] Detectado posible contenido visual por palabras clave, pero sin recursos de imagen adjuntos."
                )

        # Ejecutar DeepSeek-R1:8b
        print(f"[PIPELINE] Consultando modelo de razonamiento: {self.config.reason_model}...")
        answer: AIAnswer = self.reason_client.choose_answer(
            parsed=parsed,
            context=visual_json,
            log_reasoning=self.config.log_reasoning,
        )

        return {
            "answer": answer.answer,
            "confidence": answer.confidence,
            "reasoning": answer.reason,
            "think_time_ms": answer.think_time_ms,
            "qwen_activated": qwen_activated,
            "visual_info": visual_info,
            "raw_response": answer.raw_response,
        }
