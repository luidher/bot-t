from __future__ import annotations

from dataclasses import dataclass, field
import re


OPTION_RE = re.compile(r"^\s*(?:[A-Da-d][\).:-]|\d+[\).:-]|[-*])\s*(.+?)\s*$")


@dataclass(frozen=True)
class ParsedQuestion:
    question: str
    options: list[str]
    raw_lines: list[str]
    question_selector: str = ""
    selectors: list[str] = field(default_factory=list)
    option_selectors: list[str] = field(default_factory=list)
    media_selectors: list[str] = field(default_factory=list)
    media_elements: list[dict] = field(default_factory=list)

    @property
    def has_options(self) -> bool:
        return len(self.options) > 0

    @classmethod
    def from_dom(cls, data: dict) -> "ParsedQuestion":
        """Construye un ParsedQuestion desde los datos extraídos del DOM.

        data = {
            "question": str,
            "options": list[str],
            "question_selector": str,
            "selectors": list[str],
            "option_selectors": list[str],
            "media_selectors": list[str],
            "media_elements": list[dict],
        }
        """
        from core.mathjax_parser import MathJaxParser
        from bs4 import BeautifulSoup
        
        math_parser = MathJaxParser()

        question_html = data.get("question_html")
        # Texto ya extraído por JS (puede contener [img: ...] tags)
        question_js = str(data.get("question", "")).strip()
        if question_html:
            cleaned_html = math_parser.replace_mathjax(question_html)
            question = BeautifulSoup(cleaned_html, "html.parser").get_text().strip()
            question = re.sub(r"\s+", " ", question)
            # Si HTML queda vacío (ej. solo imágenes), usar el texto extraído por JS
            if not question:
                question = question_js
            else:
                # Recuperar etiquetas [img: ...] del texto JS que BeautifulSoup no extrae
                js_imgs = re.findall(r"\[img:\s*[^\]]+\]", question_js)
                if js_imgs:
                    question = f"{question} {' '.join(js_imgs)}".strip()
        else:
            question = question_js

        options_html = data.get("options_html")
        # Textos de opciones ya extraídos por JS
        options_js = [str(o).strip() for o in data.get("options", [])]
        if options_html:
            options = []
            for i, opt_html in enumerate(options_html):
                cleaned_opt_html = math_parser.replace_mathjax(opt_html)
                opt_text = BeautifulSoup(cleaned_opt_html, "html.parser").get_text().strip()
                opt_text = re.sub(r"\s+", " ", opt_text)
                # Si HTML queda vacío (ej. solo imagen), usar el texto JS de la opción
                if not opt_text and i < len(options_js):
                    opt_text = options_js[i]
                elif i < len(options_js):
                    # Recuperar etiquetas [img: ...] del texto JS que BeautifulSoup no extrae
                    js_opt_imgs = re.findall(r"\[img:\s*[^\]]+\]", options_js[i])
                    if js_opt_imgs:
                        opt_text = f"{opt_text} {' '.join(js_opt_imgs)}".strip()
                if opt_text:
                    options.append(opt_text)
        else:
            options = [o for o in options_js if o]

        selectors = [str(s).strip() for s in data.get("selectors", []) if str(s).strip()]
        question_selector = str(data.get("question_selector", "")).strip()
        option_selectors = [str(s).strip() for s in data.get("option_selectors", []) if str(s).strip()]
        media_selectors = [str(m).strip() for m in data.get("media_selectors", []) if str(m).strip()]
        media_elements = data.get("media_elements", [])
        raw_lines = [question] + options
        return cls(
            question=question,
            options=options,
            raw_lines=raw_lines,
            question_selector=question_selector,
            selectors=selectors,
            option_selectors=option_selectors,
            media_selectors=media_selectors,
            media_elements=media_elements,
        )


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
