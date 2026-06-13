from __future__ import annotations

import json
import requests
from typing import Any


class QwenVisionClient:
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
        self, question: str, options: list[str], media_base64: list[str]
    ) -> dict[str, Any]:
        """Analiza la imagen o imágenes adjuntas usando Qwen2.5-VL.

        Retorna un diccionario JSON con la descripción visual estructurada.
        """
        if not media_base64:
            return {
                "content_type": "ninguno",
                "description": "No se proporcionaron imágenes para análisis visual.",
                "extracted_data": {},
            }

        prompt = f"""
Analiza la imagen adjunta y extrae la información visual relevante para la siguiente pregunta y opciones.
Tu única tarea es describir detalladamente lo que se observa en la imagen (gráficos, tablas, diagramas, fórmulas, objetos, textos o diagramas).

Pregunta: {question}
Opciones: {", ".join(options)}

REGLAS CRÍTICAS:
1. Responde EXCLUSIVAMENTE en formato JSON con la siguiente estructura:
{{
  "content_type": "tabla | gráfico | diagrama | fórmula | imagen | texto | otro",
  "description": "descripción detallada de los elementos visuales relevantes",
  "extracted_data": {{
     "clave": "valor"
  }}
}}
2. NO respondas la pregunta.
3. NO sugieras respuestas ni elijas ninguna opción.
4. NO uses lenguaje de decisión. Solo describe de forma objetiva la información visual contenida en la imagen.
""".strip()

        payload = {
            "model": self.model,
            "prompt": prompt,
            "images": media_base64,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
            },
        }

        try:
            response = requests.post(
                f"{self.host}/api/generate",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            raw_response = response.json().get("response", "").strip()

            # Intentar decodificar la respuesta JSON
            return self._parse_json(raw_response)
        except Exception as e:
            print(f"[VISION WARNING] Falló la consulta con Qwen2.5-VL: {e}")
            return {
                "content_type": "error",
                "description": f"Error al procesar la imagen con Qwen: {str(e)}",
                "extracted_data": {},
            }

    def _parse_json(self, raw: str) -> dict[str, Any]:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            start = raw.find("{")
            end = raw.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return {
                    "content_type": "otro",
                    "description": raw,
                    "extracted_data": {},
                }
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                return {
                    "content_type": "otro",
                    "description": raw,
                    "extracted_data": {},
                }
