from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any, Optional

from core.parser import ParsedQuestion


@dataclass(frozen=True)
class AIAnswer:
    answer: str
    confidence: float
    reason: str
    think_time_ms: int
    raw_response: str


class OllamaClient:
    def __init__(
        self,
        model: str = "deepseek-r1:8b",
        host: str = "http://localhost:11434",
        timeout: int = 620,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def choose_answer(
        self, parsed: ParsedQuestion, context: str = "", log_reasoning: bool = False
    ) -> AIAnswer:
        import requests

        prompt = build_prompt(parsed, context=context)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": 0.1,
                "num_ctx": 4096,
            },
        }
        
        start_time = time.perf_counter()
        response = requests.post(
            f"{self.host}/api/generate",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        end_time = time.perf_counter()
        
        raw = response.json().get("response", "").strip()
        think_time_ms = int((end_time - start_time) * 1000)

        return parse_ai_answer(raw, think_time_ms=think_time_ms, log_reasoning=log_reasoning)

    def is_available(self) -> bool:
        import requests

        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            return response.ok
        except requests.RequestException:
            return False


def build_prompt(parsed: ParsedQuestion, context: str = "") -> str:
    options = "\n".join(f"{idx + 1}. {option}" for idx, option in enumerate(parsed.options))
    context_block = f"\nInformación visual extraída (formato JSON):\n{context}\n" if context else ""

    return f"""
Eres un asistente de razonamiento lógico. Tu objetivo es resolver la siguiente pregunta seleccionando la mejor opción disponible.
Debes analizar la pregunta, realizar los cálculos necesarios, aplicar razonamiento lógico y comparar con las opciones.
Si existe información visual extraída, úsala para complementar tu razonamiento.

Responde exclusivamente en formato JSON con la siguiente estructura:
{{
  "answer": "texto exacto de la opción elegida",
  "confidence": 0.0,
  "reasoning": "explicación o justificación del razonamiento utilizado"
}}

Pregunta:
{parsed.question}

Opciones:
{options if options else "No se detectaron opciones. Responde con una respuesta breve."}
{context_block}
Reglas:
- El campo 'answer' debe coincidir exactamente (carácter por carácter) con una de las opciones listadas.
- Si no estás seguro o la información es insuficiente, reduce el valor de 'confidence' (entre 0.0 y 1.0).
- No inventes opciones que no estén en la lista.
""".strip()


def parse_ai_answer(
    raw: str, think_time_ms: int = 0, log_reasoning: bool = False
) -> AIAnswer:
    # Extraer bloque <think> si está presente
    think_content = ""
    clean_raw = raw
    if "<think>" in raw and "</think>" in raw:
        start_think = raw.find("<think>") + len("<think>")
        end_think = raw.find("</think>")
        think_content = raw[start_think:end_think].strip()
        clean_raw = raw[end_think + len("</think>") :].strip()

    if log_reasoning and think_content:
        print(f"\n=== PENSAMIENTO DEEPSEEK ===\n{think_content}\n=============================\n")

    data = _loads_json(clean_raw)
    answer = str(data.get("answer", "")).strip()
    reason = str(data.get("reasoning", data.get("reason", ""))).strip()
    confidence = _as_float(data.get("confidence"), default=0.0)
    confidence = max(0.0, min(1.0, confidence))

    return AIAnswer(
        answer=answer,
        confidence=confidence,
        reason=reason,
        think_time_ms=think_time_ms,
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
