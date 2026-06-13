from __future__ import annotations

from dataclasses import dataclass, field
import re


OPTION_RE = re.compile(r"^\s*(?:[A-Da-d][\).:-]|\d+[\).:-]|[-*])\s*(.+?)\s*$")


@dataclass(frozen=True)
class ParsedQuestion:
    question: str
    options: list[str]
    raw_lines: list[str]
    selectors: list[str] = field(default_factory=list)
    media: list[str] = field(default_factory=list)

    @property
    def has_options(self) -> bool:
        return len(self.options) > 0

    @classmethod
    def from_dom(cls, data: dict) -> "ParsedQuestion":
        """Construye un ParsedQuestion desde los datos extraídos del DOM.

        data = {"question": str, "options": list[str], "selectors": list[str], "media": list[str]}
        """
        question = str(data.get("question", "")).strip()
        options = [str(o).strip() for o in data.get("options", []) if str(o).strip()]
        selectors = [str(s).strip() for s in data.get("selectors", []) if str(s).strip()]
        media = [str(m).strip() for m in data.get("media", []) if str(m).strip()]
        raw_lines = [question] + options
        return cls(question=question, options=options, raw_lines=raw_lines, selectors=selectors, media=media)


def parse_question(text: str, media: list[str] | None = None) -> ParsedQuestion:
    lines = normalize_lines(text)
    media_list = media if media is not None else []
    if not lines:
        return ParsedQuestion(question="", options=[], raw_lines=[], media=media_list)

    option_start = _find_option_start(lines)
    if option_start is None:
        return ParsedQuestion(question=" ".join(lines), options=[], raw_lines=lines, media=media_list)

    question = " ".join(lines[:option_start]).strip()
    options = [_clean_option(line) for line in lines[option_start:]]
    options = [option for option in options if option]

    return ParsedQuestion(question=question, options=options, raw_lines=lines, media=media_list)


def normalize_lines(text: str) -> list[str]:
    cleaned = []
    for line in text.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            cleaned.append(line)
    return cleaned


def _find_option_start(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if OPTION_RE.match(line):
            return index

    if len(lines) >= 3:
        return 1

    return None


def _clean_option(line: str) -> str:
    match = OPTION_RE.match(line)
    return (match.group(1) if match else line).strip()


def extraer_pregunta_y_opciones(texto: str):
    """Backward-compatible wrapper for the original script."""
    parsed = parse_question(texto)
    return parsed.question or None, parsed.options
