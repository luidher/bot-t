from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Optional

from core.parser import ParsedQuestion


@dataclass(frozen=True)
class AIAnswer:
    answer: str
    confidence: float
    reason: str
    raw_response: str


class OllamaClient:
    def __init__(
        self,
        model: str = "llama3.1",
        host: str = "http://localhost:11434",
        timeout: int = 620,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def choose_answer(self, parsed: ParsedQuestion, context: str = "") -> AIAnswer:
        import requests

        prompt = build_prompt(parsed, context=context)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
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
        
        return parse_ai_answer(raw)

    def is_available(self) -> bool:
        import requests

        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            return response.ok
        except requests.RequestException:
            return False


def build_prompt(parsed: ParsedQuestion, context: str = "") -> str:
    options = "\n".join(f"{idx + 1}. {option}" for idx, option in enumerate(parsed.options))
    context_block = f"\nContexto adicional:\n{context}\n" if context else ""

    return f"""
Eres un asistente local para una demo autorizada de vision computacional.
Analiza la pregunta extraida por OCR y elige la mejor opcion disponible.
Responde exclusivamente como JSON valido con esta forma:
{{"answer":"texto exacto de la opcion elegida","confidence":0.0,"reason":"explicacion breve"}}

Pregunta:
{parsed.question}

Opciones:
{options if options else "No se detectaron opciones. Responde con una respuesta breve."}
{context_block}
Reglas:
- Si hay opciones, el campo answer debe copiar exactamente una de ellas.
- Si el OCR parece dudoso, baja confidence y explica la duda.
- No inventes una opcion que no este en la lista.
""".strip()


def parse_ai_answer(raw: str) -> AIAnswer:
    data = _loads_json(raw)
    answer = str(data.get("answer", "")).strip()
    reason = str(data.get("reason", "")).strip()
    confidence = _as_float(data.get("confidence"), default=0.0)
    confidence = max(0.0, min(1.0, confidence))

    return AIAnswer(
        answer=answer,
        confidence=confidence,
        reason=reason,
        raw_response=raw,
    )


def _loads_json(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {"answer": raw, "confidence": 0.0, "reason": "Respuesta no JSON de Ollama."}
        try:
            value = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {"answer": raw, "confidence": 0.0, "reason": "Respuesta no JSON de Ollama."}

    return value if isinstance(value, dict) else {}


def _as_float(value: Optional[Any], default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
