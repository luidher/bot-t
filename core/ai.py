from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any, Optional

from core.parser import ParsedQuestion


@dataclass(frozen=True)
class AIAnswer:
    answer: str
    confidence: float
    reasoning: str
    raw_response: str
    think_time_ms: int = 0
    index: Optional[int] = None
    raw: Optional[str] = None

    @property
    def reason(self) -> str:
        return self.reasoning


def is_model_available(available_models: list[str], target_model: str) -> bool:
    """Verifica si un modelo específico está disponible en la lista de Ollama."""
    def normalize(name: str) -> str:
        return name.lower().replace("-", "").replace("_", "").replace(":", "")
    
    target_norm = normalize(target_model)
    for m in available_models:
        m_norm = normalize(m)
        if target_norm in m_norm or m_norm in target_norm:
            return True
    return False


class OllamaClient:
    def __init__(
        self,
        model: str = "deepseek-r1:8b",
        host: str = "http://localhost:11434",
        timeout: int = 220,
    ) -> None:
        self.model = model
        self.host = host.rstrip("/")
        self.timeout = timeout

    def choose_answer(self, parsed: ParsedQuestion, context: str = "", ocr_context: str = "") -> AIAnswer:
        import requests

        prompt = build_prompt(parsed, context=context, ocr_context=ocr_context)
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
        elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        
        raw = response.json().get("response", "").strip()
        
        return parse_ai_answer(raw, elapsed_ms=elapsed_ms, options=parsed.options)

    def is_available(self) -> bool:
        import requests

        try:
            response = requests.get(f"{self.host}/api/tags", timeout=5)
            if not response.ok:
                return False
            models_data = response.json().get("models", [])
            models = [m["name"] for m in models_data]
            return is_model_available(models, self.model)
        except requests.RequestException:
            return False


def build_prompt(parsed: ParsedQuestion, context: str = "", ocr_context: str = "") -> str:
    options = "\n".join(f"{idx + 1}. {option}" for idx, option in enumerate(parsed.options))
    context_block = f"\nInformación visual estructurada en texto plano:\n{context}\n" if context else ""
    ocr_block = f"\nTexto adicional extraído por OCR desde elementos inaccesibles/canvas/svg/iframe:\n{ocr_context}\n" if ocr_context else ""

    return f"""
Eres un asistente local basado en inteligencia artificial para la selección de respuestas.
Analiza la pregunta y las opciones disponibles. Utiliza la información visual provista cuando exista.
Resuelve la pregunta y proporciona una justificación breve.
Debes elegir exactamente una opción que sea la correcta.

Responde exclusivamente como un objeto JSON válido con esta forma exacta:
{{
  "answer": "copia exacta de la opción elegida",
  "confidence": 0.95,
  "reasoning": "justificación breve de por que esta opción es correcta"
}}

Pregunta:
{parsed.question}

Opciones:
{options if options else "No se detectaron opciones. Responde brevemente."}

{context_block}
{ocr_block}

Reglas:
- Si hay opciones, el campo "answer" debe copiar EXACTAMENTE una de ellas.
- No inventes opciones que no estén en la lista.
- Responde ÚNICAMENTE con el objeto JSON, sin formato markdown u otros comentarios.
""".strip()


def _extraer_letra(respuesta_raw: str, num_opciones: int) -> int | None:
    if not respuesta_raw or num_opciones <= 0:
        return None

    raw_cleaned = respuesta_raw.strip()
    if not raw_cleaned:
        return None

    valid_letters = [chr(ord('A') + i) for i in range(num_opciones)]

    # 1. Direct check of the fully stripped/normalized string
    # Strips common markdown and punctuation around the letters
    cleaned_exact = raw_cleaned.strip("*_()[].,-:\t ").upper()
    if cleaned_exact in valid_letters:
        return valid_letters.index(cleaned_exact)

    # 2. Check if it's a number corresponding to an option index (1-based)
    if cleaned_exact.isdigit():
        idx = int(cleaned_exact) - 1
        if 0 <= idx < num_opciones:
            return idx

    # 3. Check for patterns like "opción A", "option B", "opcion 3"
    match_opt = re.match(r'^(?:opci[oó]n|option)\s+([a-zA-Z0-9]+)\b', raw_cleaned, re.IGNORECASE)
    if match_opt:
        val = match_opt.group(1).upper()
        if val in valid_letters:
            return valid_letters.index(val)
        if val.isdigit():
            idx = int(val) - 1
            if 0 <= idx < num_opciones:
                return idx

    # 4. Check if it starts with a letter or digit followed by standard option delimiters
    # E.g. "A) Una tercera parte", "1. Un medio"
    match_start = re.match(r'^([a-zA-Z0-9]+)\s*[\)\.\-\:]\s*', raw_cleaned)
    if match_start:
        val = match_start.group(1).upper()
        if val in valid_letters:
            return valid_letters.index(val)
        if val.isdigit():
            idx = int(val) - 1
            if 0 <= idx < num_opciones:
                return idx

    return None


def parse_ai_answer(raw: str, elapsed_ms: int = 0, options: list[str] | None = None) -> AIAnswer:
    # 1. Clean think tag if it is outside of the JSON
    cleaned_raw = raw
    think_content = ""
    if "<think>" in raw:
        start_idx = raw.find("<think>")
        end_idx = raw.find("</think>")
        if end_idx != -1 and end_idx > start_idx:
            think_content = raw[start_idx + 7 : end_idx].strip()
            cleaned_raw = (raw[:start_idx] + raw[end_idx + 8 :]).strip()

    data = _loads_json(cleaned_raw)
    
    # Extract answer and reasoning
    respuesta_raw = str(data.get("answer", "")).strip()
    reasoning = str(data.get("reasoning", data.get("reason", ""))).strip()
    
    # If reasoning is empty but we extracted think content, use it!
    if not reasoning and think_content:
        reasoning = think_content
    elif think_content and think_content not in reasoning:
        # Combine if appropriate
        reasoning = f"{think_content}\n\n{reasoning}".strip()
        
    # Clean think tags inside reasoning if any
    if "<think>" in reasoning:
        reasoning = reasoning.replace("<think>", "").replace("</think>", "").strip()

    confidence = _as_float(data.get("confidence"), default=0.0)
    confidence = max(0.0, min(1.0, confidence))

    index = None
    answer = respuesta_raw

    if options:
        idx = _extraer_letra(respuesta_raw, len(options))
        if idx is not None:
            answer = options[idx]
            index = idx
        else:
            # Fallback exact/case-insensitive match with the option list
            for i, opt in enumerate(options):
                if opt.strip().lower() == respuesta_raw.lower():
                    answer = opt
                    index = i
                    break

    return AIAnswer(
        answer=answer,
        confidence=confidence,
        reasoning=reasoning,
        raw_response=raw,
        think_time_ms=elapsed_ms,
        index=index,
        raw=respuesta_raw,
    )


def _loads_json(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {"answer": raw, "confidence": 0.0, "reasoning": "Respuesta no JSON de Ollama."}
        try:
            value = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {"answer": raw, "confidence": 0.0, "reasoning": "Respuesta no JSON de Ollama."}

    return value if isinstance(value, dict) else {}


def _as_float(value: Optional[Any], default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
