from __future__ import annotations

from dataclasses import dataclass
import re


OPTION_RE = re.compile(r"^\s*(?:[A-Da-d][\).:-]|\d+[\).:-]|[-*])\s*(.+?)\s*$")


@dataclass(frozen=True)
class ParsedQuestion:
    question: str
    options: list[str]
    raw_lines: list[str]

    @property
    def has_options(self) -> bool:
        return len(self.options) > 0


def parse_question(text: str) -> ParsedQuestion:
    lines = normalize_lines(text)
    if not lines:
        return ParsedQuestion(question="", options=[], raw_lines=[])

    option_start = _find_option_start(lines)
    if option_start is None:
        return ParsedQuestion(question=" ".join(lines), options=[], raw_lines=lines)

    question = " ".join(lines[:option_start]).strip()
    options = [_clean_option(line) for line in lines[option_start:]]
    options = [option for option in options if option]

    return ParsedQuestion(question=question, options=options, raw_lines=lines)


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
