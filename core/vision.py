from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Optional


class VisionAnalyzer:
    def __init__(
        self,
        model: str = "qwen2.5-vl",
        host: str = "http://localhost:11434",
        timeout: int = 120,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def analyze_image(
        self,
        image_path: str | Path,
        question: str,
        options: list[str],
        ocr_text: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        import requests

        try:
            image_path = Path(image_path)
            if not image_path.exists():
                print(f"[VISION ERROR] La ruta de la imagen no existe: {image_path}")
                return None

            # Read image and convert to base64
            with open(image_path, "rb") as f:
                img_data = f.read()
            b64_str = base64.b64encode(img_data).decode("utf-8")

            prompt = build_vision_prompt(question, options, ocr_text=ocr_text)
            payload = {
                "model": self.model,
                "prompt": prompt,
                "images": [b64_str],
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.1,
                    "num_ctx": 4096,
                },
            }

            response = requests.post(
                f"{self.host}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            raw = response.json().get("response", "").strip()

            return parse_vision_response(raw)
        except Exception as e:
            print(f"[VISION ERROR] Error al analizar imagen con Qwen: {e}")
            return None


def build_vision_prompt(question: str, options: list[str], ocr_text: Optional[str] = None) -> str:
    options_str = "\n".join(f"- {o}" for o in options)
    ocr_block = f"\nTexto extraído por OCR de la imagen:\n{ocr_text}\n" if ocr_text else ""
    return f"""
Eres un asistente de análisis visual especializado en la descripción estructurada de imágenes.
Analiza la imagen proporcionada en el contexto de la siguiente pregunta y opciones.
Tu tarea es exclusivamente extraer y describir la información visual relevante de la imagen (por ejemplo: contenido de tablas, datos de gráficos, diagramas, fórmulas, conteo de objetos o elementos visuales clave).

Pregunta:
{question}

Opciones:
{options_str if options else "No provistas"}
{ocr_block}

REGLAS ABSOLUTAS:
1. Responde ÚNICAMENTE con un objeto JSON descriptivo.
2. NO intentes responder la pregunta.
3. NO sugieras qué opción es la correcta ni descartes opciones.
4. NO selecciones ninguna respuesta.
5. Limítate a describir detalladamente lo que ves de forma objetiva y estructurada.

Formato de salida esperado:
{{
  "tipo_contenido": "tabla | grafico | diagrama | formula | objetos | otro",
  "descripcion_visual": "Descripción detallada y objetiva de los elementos visuales...",
  "datos_extraidos": {{
     // Estructura libre con datos numéricos, etiquetas u objetos detectados en la imagen
  }}
}}
""".strip()


def parse_vision_response(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {"tipo_contenido": "otro", "descripcion_visual": raw, "datos_extraidos": {}}
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {"tipo_contenido": "otro", "descripcion_visual": raw, "datos_extraidos": {}}

    return data if isinstance(data, dict) else {}
