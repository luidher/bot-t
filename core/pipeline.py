from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from core.ai import OllamaClient, AIAnswer
from core.vision import VisionAnalyzer
from core.config import BotConfig
from core.parser import ParsedQuestion


class DecisionPipeline:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.ai_client = OllamaClient(
            model=config.reason_model,
            host=config.ensure_http(),
        )
        self.vision_analyzer = VisionAnalyzer(
            model=config.vision_model,
            host=config.ensure_http(),
        )

    def run(
        self,
        question: str,
        options: list[str],
        media_paths: list[str],
        is_dom_mode: bool,
        ocr_texts: Optional[list[str]] = None,
        ocr_context: str = "",
    ) -> tuple[AIAnswer, bool, Optional[list[dict[str, Any]]]]:
        """Ejecuta el flujo de decisión híbrido.

        Retorna:
            (answer_object, qwen_activated, visual_descriptions)
        """
        # Fase 2: Detección de contenido visual
        has_visual = self.detect_visual_content(question, options, media_paths, is_dom_mode)
        
        visual_json_list = None
        visual_context_str = ""
        qwen_activated = False

        if has_visual and self.config.vision_enabled:
            print("[PIPELINE] Contenido visual detectado. Activando Qwen2.5-VL...")
            descriptions = []
            for idx, path in enumerate(media_paths):
                elem_ocr = ocr_texts[idx] if (ocr_texts and idx < len(ocr_texts)) else None
                desc = self.vision_analyzer.analyze_image(path, question, options, ocr_text=elem_ocr)
                if desc:
                    descriptions.append(desc)
            if descriptions:
                visual_json_list = descriptions
                # Serializar a JSON para pasar como contexto a DeepSeek
                visual_context_str = json.dumps(descriptions, indent=2, ensure_ascii=False)
                qwen_activated = True
        else:
            print("[PIPELINE] Omitiendo Qwen2.5-VL (sin contenido visual o visión desactivada).")

        # Fase 4: Razonamiento
        parsed_q = ParsedQuestion(question=question, options=options, raw_lines=[question] + options)
        answer = self.ai_client.choose_answer(parsed_q, context=visual_context_str, ocr_context=ocr_context)
        
        return answer, qwen_activated, visual_json_list

    def detect_visual_content(
        self,
        question: str,
        options: list[str],
        media_paths: list[str],
        is_dom_mode: bool,
    ) -> bool:
        if is_dom_mode:
            # En modo DOM, si encontramos elementos multimedia en la pregunta, hay contenido visual.
            return len(media_paths) > 0

        # En modo OCR (o cuando solo tenemos la captura total):
        # 1. Búsqueda de palabras clave
        visual_keywords = [
            "gráfico", "grafico", "tabla", "imagen", "figura", "diagrama", "gráfica", "grafica", "esquema",
            "dibujo", "mapa", "chart", "table", "image", "graph", "diagram", "figure", "formula",
            "ecuación", "ecuacion", "resolución", "resolucion", "siguiente", "representa"
        ]
        text_to_check = (question + " " + " ".join(options)).lower()
        for kw in visual_keywords:
            if kw in text_to_check:
                return True

        # 2. Análisis de contornos con OpenCV
        if media_paths:
            try:
                import cv2
                import numpy as np

                image_path = media_paths[0]
                img = cv2.imread(str(image_path))
                if img is not None:
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    # Binarización invertida
                    _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
                    # Encontrar contornos
                    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

                    img_height, img_width = gray.shape
                    total_area = img_height * img_width

                    for c in contours:
                        x, y, w, h = cv2.boundingRect(c)
                        area = cv2.contourArea(c)
                        # Un contorno significativo mide al menos 80x80px (o área > 2%) y no es el borde completo
                        if (w > 80 and h > 80 and area > total_area * 0.02) or (w > 120 and h > 120):
                            if w < img_width * 0.98 or h < img_height * 0.98:
                                return True
            except Exception as e:
                print(f"[PIPELINE WARNING] Error en la detección visual basada en OpenCV: {e}")

        return False
