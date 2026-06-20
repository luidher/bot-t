"""
autopilot_runner.py — Motor de bucle para el Modo Autopilot DB.

Módulo completamente independiente: no requiere PyQt5, widget ni config externo.

Flujo correcto para plataformas con múltiples preguntas por hoja:
  A. Extraer TODAS las preguntas y opciones de la hoja actual.
  B. Para cada pregunta: consultar DB → responder desde DB o al azar.
  C. Hacer clic en "Calificar" (btn-submit) para enviar todas las respuestas.
  D. Leer feedback del DOM:
     - Preguntas con feedback "correct" → guardar en DB (si no estaban ya).
     - Preguntas con feedback "incorrect" → descartar esa opción.
  E. Si hay incorrectas → clic "Intenta de nuevo" (btn-reload) → volver a B
     solo con las preguntas incorrectas (las correctas ya quedaron fijas).
  F. Cuando todas correctas → clic "Siguiente" → nueva hoja → volver a A.
"""
from __future__ import annotations

import json
import random
import re
import time
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from core.db_manager import DBManager

if TYPE_CHECKING:
    from core.browser import BotBrowser

AUTOPILOT_CONFIG_FILE = Path("autopilot_config.json")


# ---------------------------------------------------------------------------
# Helpers de configuración
# ---------------------------------------------------------------------------

def _load_autopilot_config() -> dict[str, Any]:
    """Carga autopilot_config.json; si falta, devuelve valores razonables."""
    defaults: dict[str, Any] = {
        "selectors": {
            "question_container": "ul.form-items > li[data-type='OM'], ul.form-items > li[data-item], .form-items > li[data-type='OM']",
            "question_text": ".question, .pregunta, p, h2, h3, h4",
            "option_input": "input[type='radio'], input[type='checkbox']",
            "option_label": "label",
            "correct_markers": [".correct", "[class*='correct']", "[class*='success']"],
            "incorrect_markers": [".incorrect", "[class*='incorrect']", "[class*='wrong']", "[class*='error']"],
            "submit_button": [
                "button.btn-submit",
                "button[type='submit'].btn-form",
                "button.btn-form.btn-submit",
                "button[type='submit']:not(.btn-reload)",
            ],
            "reload_button": [
                "button.btn-reload",
                "button.btn-form.btn-reload",
                ".reintentar",
                "button[class*='reload']",
                "button[class*='reintentar']",
            ],
            "next_button": [
                ".wrap-footer a",
                "a.btnAccede",
                "a[href*='/MiClase/inicia/']",
                "button.next",
                "a.next",
                ".btn-next",
                ".next-page",
                "button[class*='siguiente']",
                "input[type='submit'][value*='iguiente']",
                "button[class*='next']",
            ],
            "retry_button": [
                "button.btn-reload",
                "button.btn-form.btn-reload",
                "button.retry",
                ".reintentar",
                "button[class*='retry']",
                "button[class*='reintentar']",
                ".btn-retry",
            ],
        },
        "timings": {
            "feedback_wait_ms": 1500,
            "after_click_wait_ms": 600,
            "reload_wait_ms": 2500,
            "next_wait_ms": 3000,
            "dom_stable_wait_ms": 700,
            "after_submit_wait_ms": 2000,
        },
        "auth": {
            "wait_for_manual_auth": True,
            "manual_auth_timeout_sec": 300,
            "manual_auth_poll_sec": 1.0,
        },
        "browser": {
            "keep_open": False,
            "pw_timeout_ms": 120000,
        },
        "network": {
            "feedback_url_hints": ["registrar", "unidad", "registrar unidad"],
        },
        "limits": {
            "max_sheets": 10000,
            "max_intentos_por_pregunta": 8,
            "max_rondas_por_hoja": 20,
        },
    }
    if not AUTOPILOT_CONFIG_FILE.exists():
        return defaults
    try:
        with open(AUTOPILOT_CONFIG_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        for section, values in defaults.items():
            if section not in data:
                data[section] = values
            elif isinstance(values, dict):
                for k, v in values.items():
                    data[section].setdefault(k, v)
        return data
    except Exception as exc:
        print(f"[AUTOPILOT] Error cargando autopilot_config.json: {exc}. Usando defaults.")
        return defaults


def _default_log_callback(msg: str, level: str) -> None:
    text = f"[{level}] {msg}"
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


# ---------------------------------------------------------------------------
# JavaScript helpers
# ---------------------------------------------------------------------------

# Extrae TODAS las preguntas y opciones de la hoja actual (incluyendo las ya respondidas)
_JS_EXTRACT_ALL = r"""
() => {
    const containers = Array.from(document.querySelectorAll(
        'ul.form-items > li[data-type="OM"], ul.form-items > li[data-item], .form-items > li[data-type="OM"]'
    ));

    if (!containers.length) return null;

    const getUniqueSelector = (el) => {
        if (el.id) return `#${el.id}`;
        const dataOp = el.getAttribute && el.getAttribute('data-op');
        if (dataOp) return `input[data-op="${dataOp.replace(/"/g, '\\\"')}"]`;
        if (el.name && el.value)
            return `input[name="${el.name.replace(/"/g, '\\\"')}"][value="${el.value.replace(/"/g, '\\\"')}"]`;
        const path = [];
        let curr = el;
        while (curr && curr.nodeType === Node.ELEMENT_NODE) {
            let sel = curr.nodeName.toLowerCase();
            if (curr.parentNode) {
                const siblings = Array.from(curr.parentNode.children);
                sel += `:nth-child(${siblings.indexOf(curr) + 1})`;
            }
            path.unshift(sel);
            curr = curr.parentNode;
        }
        return path.join(' > ');
    };

    const getQuestionHtml = (container) => {
        const qEl = container.querySelector('.question, .pregunta');
        if (qEl) return qEl.outerHTML;
        const pEl = container.querySelector('p, h2, h3, h4');
        if (pEl) return pEl.outerHTML;
        return container.outerHTML;
    };

    const getQuestionText = (container) => {
        const qEl = container.querySelector('.question, .pregunta');
        let text = '';
        if (qEl) {
            const clone = qEl.cloneNode(true);
            clone.querySelectorAll('.form-list, .options-list, ul').forEach(el => el.remove());
            text = (clone.innerText || '').replace(/\s+/g, ' ').trim();
        } else {
            const pEl = container.querySelector('p, h2, h3, h4');
            const src = pEl || container;
            text = (src.innerText || '').replace(/\s+/g, ' ').trim();
        }

        // Append image tags if any (excluding ones inside options)
        try {
            const media = Array.from(container.querySelectorAll('img, svg, canvas'));
            const imgTexts = [];
            for (const m of media) {
                let isInsideOption = false;
                let parent = m.parentElement;
                while (parent && parent !== container) {
                    if (parent.tagName === 'LABEL' || parent.querySelector('input[type="radio"], input[type="checkbox"]')) {
                        isInsideOption = true;
                        break;
                    }
                    parent = parent.parentElement;
                }
                if (isInsideOption) continue;

                const alt = (m.getAttribute && (m.getAttribute('alt') || m.getAttribute('title') || m.getAttribute('aria-label'))) || '';
                if (alt.trim()) {
                    imgTexts.push(`[img: ${alt.trim()}]`);
                } else if (m.tagName && m.tagName.toLowerCase() === 'img') {
                    const srcAttr = m.getAttribute('src') || '';
                    if (srcAttr) {
                        const parts = srcAttr.split('?')[0].split('/');
                        const name = parts[parts.length - 1] || srcAttr;
                        imgTexts.push(`[img: ${name}]`);
                    }
                }
            }
            if (imgTexts.length > 0) {
                text = text ? `${text} ${imgTexts.join(' ')}` : imgTexts.join(' ');
            }
        } catch (_) {}

        return text;
    };

    const questions = [];
    for (const container of containers) {
        const dataItem = container.getAttribute('data-item') || '';
        let questionText = getQuestionText(container);
        const questionHtml = getQuestionHtml(container);

        if (!questionText) {
            if (dataItem) {
                questionText = dataItem;
            } else if (container.id) {
                questionText = `container#${container.id}`;
            } else {
                try {
                    const img = container.querySelector('img, svg, canvas');
                    if (img) {
                        const alt = (img.getAttribute && (img.getAttribute('alt') || img.getAttribute('title') || img.getAttribute('aria-label'))) || '';
                        const altNorm = (alt || '').replace(/\s+/g, ' ').trim();
                        if (altNorm) questionText = altNorm;
                        else if (img.tagName && img.tagName.toLowerCase() === 'img') {
                            const srcAttr = img.getAttribute('src') || '';
                            if (srcAttr) {
                                const parts = srcAttr.split('?')[0].split('/');
                                questionText = parts[parts.length - 1] || srcAttr;
                            }
                        }
                    }
                } catch (_) {}
            }
            if (!questionText) questionText = `pregunta-${questions.length + 1}`;
        }

        const inputs = Array.from(container.querySelectorAll('input[type="radio"], input[type="checkbox"]'));
        const options = [];
        for (const input of inputs) {
            const dataOp = input.getAttribute('data-op') || '';
            let labelText = '';
            let optionElement = null;

            // Buscar label padre
            let parent = input.parentElement;
            while (parent && parent !== container) {
                if (parent.tagName === 'LABEL') {
                    labelText = (parent.innerText || '').trim();
                    optionElement = parent;
                    break;
                }
                parent = parent.parentElement;
            }
            // Buscar label por for=id
            if (!labelText && input.id) {
                const label = document.querySelector(`label[for="${input.id}"]`);
                if (label) {
                    labelText = (label.innerText || '').trim();
                    optionElement = label;
                }
            }
            // Fallback: parent inmediato
            if (!labelText) {
                labelText = (input.parentElement ? input.parentElement.innerText : '').trim();
                optionElement = input.parentElement || input;
            }

            labelText = (labelText || '').replace(/\s+/g, ' ').trim();

            const optionRoot = optionElement || input.parentElement || input;
            const optionHtml = optionRoot.outerHTML;

            // Find images inside this option
            try {
                const images = Array.from(optionRoot.querySelectorAll('img, svg, canvas'));
                const imageTexts = [];
                for (const img of images) {
                    const alt = img.getAttribute('alt') || img.getAttribute('title') || img.getAttribute('aria-label') || '';
                    if (alt.trim()) {
                        imageTexts.push(`[img: ${alt.trim()}]`);
                    } else if (img.tagName.toLowerCase() === 'img') {
                        const src = img.getAttribute('src') || '';
                        if (src) {
                            const parts = src.split('?')[0].split('/');
                            const name = parts[parts.length - 1] || src;
                            imageTexts.push(`[img: ${name}]`);
                        }
                    }
                }
                if (imageTexts.length > 0) {
                    labelText = labelText ? `${labelText} ${imageTexts.join(' ')}` : imageTexts.join(' ');
                }
            } catch (_) {}

            if (!labelText) {
                labelText = `Opción ${options.length + 1}`;
            }

            options.push({
                texto: labelText,
                html: optionHtml,
                selector: getUniqueSelector(input),
                clickSelector: getUniqueSelector(optionElement || input),
                data_op: dataOp,
                checked: input.checked,
            });
        }

        questions.push({
            question: questionText,
            question_html: questionHtml,
            data_item: dataItem,
            options: options,
            answered: inputs.some(i => i.checked),
        });
    }

    return questions.length ? questions : null;
}
"""

# Valida si una pregunta (por su data-item del li contenedor) fue correcta o incorrecta
# después de hacer clic en "Calificar"
_JS_VALIDATE_QUESTION = r"""
(payload) => {
    try {
        const dataItem = (payload && payload.data_item) || '';
        const selector = (payload && payload.selector) || '';
        const dataOp = (payload && payload.data_op) || '';
        // Buscar el li contenedor por data-item
        let container = null;
        if (dataItem) {
            container = document.querySelector(`li[data-item="${dataItem}"]`);
        }
        if (!container) return 'unknown';

        const correctKeywords = [
            'correct', 'success', 'right', 'ok', 'good', 'acert', 'verdad',
            'correcto', 'bien', 'aprob', 'valid', 'check', 'fa-check'
        ];
        const incorrectKeywords = [
            'incorrect', 'wrong', 'error', 'fail', 'bad', 'ko', 'danger',
            'incorrecto', 'erroneo', 'mal', 'inval', 'times', 'close',
            'fa-times', 'fa-close', 'xmark'
        ];

        const checkEl = (node) => {
            if (!node || node.nodeType !== Node.ELEMENT_NODE) return null;
            const cls = (node.className || '').toString().toLowerCase();
            const aria = (node.getAttribute('aria-label') || '').toLowerCase();
            const title = (node.getAttribute('title') || '').toLowerCase();
            const dataAttrs = Array.from(node.attributes || [])
                .filter(a => a.name.startsWith('data-'))
                .map(a => `${a.name}=${a.value}`)
                .join(' ')
                .toLowerCase();
            const style = window.getComputedStyle(node);
            const inlineStyle = (node.getAttribute('style') || '').toLowerCase();
            const hay = `${cls} ${aria} ${title} ${dataAttrs} ${inlineStyle}`;

            if (incorrectKeywords.some(k => hay.includes(k))) return 'incorrect';
            if (correctKeywords.some(k => hay.includes(k))) return 'correct';

            const colorBits = `${style.color} ${style.backgroundColor} ${style.borderColor}`.toLowerCase();
            if (colorBits.includes('255, 0, 0') || colorBits.includes('220, 53, 69') || colorBits.includes('dc3545')) return 'incorrect';
            if (colorBits.includes('0, 128, 0') || colorBits.includes('40, 167, 69') || colorBits.includes('28a745')) return 'correct';
            return null;
        };

        // Primero validar la opción marcada; evita que la respuesta correcta
        // mostrada en otra opción oculte que la elegida fue incorrecta.
        let checkedInput = container.querySelector('input:checked');
        if (!checkedInput && dataOp) {
            checkedInput = container.querySelector(`input[data-op="${CSS.escape(dataOp)}"]`);
        }
        if (!checkedInput && selector) {
            try {
                const candidate = document.querySelector(selector);
                if (candidate && container.contains(candidate)) checkedInput = candidate;
            } catch (_) {}
        }
        if (checkedInput) {
            let inp = checkedInput;
            for (let i = 0; i < 5; i++) {
                const r = checkEl(inp);
                if (r) return r;
                if (!inp.parentElement || inp === container) break;
                inp = inp.parentElement;
            }
        }

        // Después revisar el contenedor de la pregunta.
        let node = container;
        for (let i = 0; i < 4; i++) {
            const r = checkEl(node);
            if (r) return r;
            if (!node.parentElement || node === document.body) break;
            node = node.parentElement;
        }

        const feedbackNodes = Array.from(container.querySelectorAll(
            '.feedback, .message, .mensaje, .alert, .resultado, .result, .validation, .validacion, i, svg, span'
        ));
        for (const fb of feedbackNodes) {
            const r = checkEl(fb);
            if (r) return r;
        }

        return 'unknown';
    } catch(e) {
        return 'unknown';
    }
}
"""

# Busca un botón visible de una lista de selectores y lo marca para hacer clic
_JS_FIND_BUTTON = r"""
(selectorList) => {
    const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };
    document.querySelectorAll('[data-ap-temp-target="true"]').forEach(n => n.removeAttribute('data-ap-temp-target'));
    // Primera pasada: preferir elementos visibles y fuera del header/buscador
    for (const sel of selectorList) {
        try {
            const elements = Array.from(document.querySelectorAll(sel));
            const buttons = [];
            const anchors = [];
            const others = [];
            for (const el of elements) {
                if (!isVisible(el)) continue;
                const tag = (el.tagName || '').toLowerCase();
                let href = '';
                try {
                    href = (el.getAttribute && el.getAttribute('href')) || (el.href || '') || '';
                } catch (_) {
                    href = '';
                }

                // Evitar elementos dentro del header o formularios de búsqueda
                try {
                    if (el.closest) {
                        const hasSearchAncestor = el.closest('header')
                            || el.closest('.search-container')
                            || el.closest('.search-container-mobile')
                            || el.closest('#navContainer')
                            || el.closest('#formSearch')
                            || el.closest('form[action*="Buscador"]');
                        if (hasSearchAncestor) continue;
                    }
                } catch (_) {}

                // Evitar enlaces que claramente llevan al buscador/resultados
                if (tag === 'a' && href && /buscador|\/buscador|buscador=|buscador\/resultados/i.test(href)) {
                    continue;
                }

                // Evitar botones explícitos de búsqueda
                try {
                    if (el.classList && el.classList.contains('search-button')) continue;
                } catch (_) {}

                if (tag === 'button' || (tag === 'input' && (el.type === 'submit' || el.type === 'button'))) {
                    buttons.push(el);
                } else if (tag === 'a') {
                    anchors.push(el);
                } else {
                    others.push(el);
                }
            }

            const pick = (buttons.length && buttons[0]) || (anchors.length && anchors[0]) || (others.length && others[0]);
            if (pick) {
                pick.setAttribute('data-ap-temp-target', 'true');
                return '[data-ap-temp-target="true"]';
            }
        } catch (_) {}
    }

    // Segunda pasada: aceptar elementos ocultos si no se encontró ninguno visible
    for (const sel of selectorList) {
        try {
            const elements = Array.from(document.querySelectorAll(sel));
            for (const el of elements) {
                const tag = (el.tagName || '').toLowerCase();
                let href = '';
                try {
                    href = (el.getAttribute && el.getAttribute('href')) || (el.href || '') || '';
                } catch (_) {
                    href = '';
                }
                // Evitar enlaces que claramente llevan al buscador/resultados
                if (tag === 'a' && href && /buscador|\/buscador|buscador=|buscador\/resultados/i.test(href)) continue;
                try { if (el.classList && el.classList.contains('search-button')) continue; } catch(_) {}
                el.setAttribute('data-ap-temp-target', 'true');
                return '[data-ap-temp-target="true"]';
            }
        } catch (_) {}
    }
    return null;
}
"""

_JS_CLICK_BY_TEXT = r"""
(textHint) => {
    const wanted = (textHint || '').toLowerCase().trim();
    if (!wanted) return false;
    const isVisible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };
    const candidates = Array.from(document.querySelectorAll(
        'button, a, input[type="submit"], input[type="button"]'
    ));
    for (const el of candidates) {
        if (!isVisible(el)) continue;
        const text = ((el.innerText || el.textContent || el.value || '') + '').replace(/\s+/g, ' ').trim().toLowerCase();
        if (!text.includes(wanted)) continue;
        el.click();
        return true;
    }
    return false;
}
"""

_JS_FEEDBACK_SNAPSHOT = r"""
(payload) => {
    try {
        const dataItem = (payload && payload.data_item) || '';
        const dataOp = (payload && payload.data_op) || '';
        const selector = (payload && payload.selector) || '';
        let container = dataItem ? document.querySelector(`li[data-item="${dataItem}"]`) : null;
        if (!container) return null;

        let input = container.querySelector('input:checked');
        if (!input && dataOp) input = container.querySelector(`input[data-op="${CSS.escape(dataOp)}"]`);
        if (!input && selector) {
            try {
                const candidate = document.querySelector(selector);
                if (candidate && container.contains(candidate)) input = candidate;
            } catch (_) {}
        }

        const summarize = (node) => {
            if (!node || node.nodeType !== Node.ELEMENT_NODE) return null;
            const style = window.getComputedStyle(node);
            return {
                tag: node.tagName.toLowerCase(),
                className: (node.className || '').toString(),
                dataResult: node.getAttribute('data-result') || node.getAttribute('data-status') || '',
                style: node.getAttribute('style') || '',
                color: style.color,
                backgroundColor: style.backgroundColor,
                text: (node.innerText || node.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 180),
            };
        };

        const path = [];
        let node = input || container;
        for (let i = 0; node && i < 5; i++) {
            path.push(summarize(node));
            if (node === container) break;
            node = node.parentElement;
        }

        return {
            container: summarize(container),
            selectedPath: path.filter(Boolean),
        };
    } catch (_) {
        return null;
    }
}
"""

_PY_CORRECT_WORDS = (
    "correct", "success", "right", "ok", "good", "acert", "verdad",
    "correcto", "correcta", "bien", "aprob", "valid", "check",
)
_PY_INCORRECT_WORDS = (
    "incorrect", "wrong", "error", "fail", "bad", "ko", "danger",
    "incorrecto", "incorrecta", "erroneo", "erronea", "mal", "inval",
    "times", "close", "xmark",
)
_PY_CORRECT_KEYS = (
    "correct", "correcta", "correcto", "answer", "respuesta", "acierto",
    "success", "valid", "right",
)
_PY_INCORRECT_KEYS = (
    "incorrect", "incorrecta", "incorrecto", "wrong", "error", "fail",
    "invalid", "errone", "mal",
)


def _normalize_math_symbols(text: str) -> str:
    if not text:
        return ""
    replacements = {
        "−": "-",
        "–": "-",
        "—": "-",
        "×": "*",
        "•": "*",
        "·": "*",
        "÷": "/",
        "≠": "!=",
        "≤": "<=",
        "≥": ">=",
        "≈": "=",
    }
    for orig, repl in replacements.items():
        text = text.replace(orig, repl)
    return text


def _normalize_feedback_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = _normalize_math_symbols(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.lower()).strip()


def _math_normalized_contains(container_text: str, search_text: str) -> bool:
    if not search_text:
        return False
    def clean(t: str) -> str:
        t = _normalize_feedback_text(t)
        for cmd in ("frac", "sqrt", "overline", "underline", "hat", "overset", "underset"):
            t = t.replace(cmd, "")
        t = re.sub(r"[\\_{}\(\)\-\+=\*\/\s]", "", t)
        return t
    clean_search = clean(search_text)
    if len(clean_search) < 2:
        return False
    return clean_search in clean(container_text)


def _math_normalized_equals(a: str, b: str) -> bool:
    if not a or not b:
        return False
    def clean(t: str) -> str:
        t = _normalize_feedback_text(t)
        for cmd in ("frac", "sqrt", "overline", "underline", "hat", "overset", "underset"):
            t = t.replace(cmd, "")
        t = re.sub(r"[\\_{}\(\)\-\+=\*\/\s]", "", t)
        return t
    return clean(a) == clean(b)


def _compact_json_text(value: Any, limit: int = 12000) -> str:
    try:
        return _normalize_feedback_text(json.dumps(value, ensure_ascii=False, default=str))[:limit]
    except Exception:
        return _normalize_feedback_text(value)[:limit]


def _classify_feedback_words(text: str) -> str:
    norm = _normalize_feedback_text(text)
    if any(word in norm for word in _PY_INCORRECT_WORDS):
        return "incorrect"
    if any(word in norm for word in _PY_CORRECT_WORDS):
        return "correct"
    return "unknown"


def _classify_server_front_item(class_name: Any) -> str:
    class_norm = _normalize_feedback_text(class_name)
    if not class_norm:
        return "unknown"
    if "wrong" in class_norm or "incorrect" in class_norm or "error" in class_norm:
        return "incorrect"
    if "success" in class_norm or "correct" in class_norm or "acert" in class_norm:
        return "correct"
    return _classify_feedback_words(class_norm)


def _classify_feedback_front(node: Any, data_item: str) -> str:
    """Lee el formato de servidor: front: [{id_item, class}, ...]."""
    wanted = _normalize_feedback_text(data_item)
    if not wanted:
        return "unknown"

    if isinstance(node, dict):
        front = node.get("front")
        if isinstance(front, list):
            for item in front:
                if not isinstance(item, dict):
                    continue
                item_id = _normalize_feedback_text(
                    item.get("id_item")
                    or item.get("data_item")
                    or item.get("item")
                    or item.get("id")
                )
                if item_id == wanted:
                    return _classify_server_front_item(item.get("class") or item.get("status"))

        for value in node.values():
            result = _classify_feedback_front(value, data_item)
            if result != "unknown":
                return result

    elif isinstance(node, list):
        for item in node:
            result = _classify_feedback_front(item, data_item)
            if result != "unknown":
                return result

    return "unknown"


def _classify_feedback_front_text(text: str, data_item: str) -> str:
    """Fallback para respuestas tipo texto con id_item/class cerca."""
    if not text or not data_item:
        return "unknown"

    positions = [match.start() for match in re.finditer(re.escape(data_item), text)]
    if not positions:
        norm_text = _normalize_feedback_text(text)
        norm_item = _normalize_feedback_text(data_item)
        positions = [match.start() for match in re.finditer(re.escape(norm_item), norm_text)]
        text = norm_text

    for pos in positions:
        after = text[pos:pos + 500]
        before = text[max(0, pos - 300):pos]
        for window in (after, before):
            class_match = re.search(
                r"""["']?class["']?\s*[:=]\s*["']?([a-zA-Z_-]+)""",
                window,
                flags=re.IGNORECASE,
            )
            if class_match:
                result = _classify_server_front_item(class_match.group(1))
                if result != "unknown":
                    return result

    return "unknown"


def _has_selected_value(value_text: str, data_op: str, option_text: str) -> bool:
    data_op_norm = _normalize_feedback_text(data_op)
    option_norm = _normalize_feedback_text(option_text)
    if bool(
        (data_op_norm and data_op_norm in value_text)
        or (option_norm and len(option_norm) >= 3 and option_norm in value_text)
    ):
        return True
    if option_text and _math_normalized_contains(value_text, option_text):
        return True
    return False
        or (option_norm and len(option_norm) >= 3 and option_norm in value_text)
    )


def _classify_feedback_json(node: Any, data_item: str, data_op: str, option_text: str) -> str:
    """Clasifica respuestas JSON comunes sin asumir un esquema exacto."""
    data_item_norm = _normalize_feedback_text(data_item)

    if isinstance(node, dict):
        node_text = _compact_json_text(node)
        node_has_question = not data_item_norm or data_item_norm in node_text
        node_has_selected = _has_selected_value(node_text, data_op, option_text)

        for key, value in node.items():
            key_norm = _normalize_feedback_text(key)
            value_text = _compact_json_text(value)
            value_has_selected = _has_selected_value(value_text, data_op, option_text)

            if any(marker in key_norm for marker in _PY_INCORRECT_KEYS):
                if value is True and node_has_selected and node_has_question:
                    return "incorrect"
                if value_has_selected and node_has_question:
                    return "incorrect"

            if any(marker in key_norm for marker in _PY_CORRECT_KEYS):
                if value is True and node_has_selected and node_has_question:
                    return "correct"
                if value is False and node_has_selected and node_has_question:
                    return "incorrect"
                if value_has_selected and node_has_question:
                    return "correct"

            result = _classify_feedback_json(value, data_item, data_op, option_text)
            if result != "unknown":
                return result

        if node_has_question and node_has_selected:
            return _classify_feedback_words(node_text)

    elif isinstance(node, list):
        for item in node:
            result = _classify_feedback_json(item, data_item, data_op, option_text)
            if result != "unknown":
                return result

    return "unknown"


# ---------------------------------------------------------------------------
# AutopilotRunner — Motor principal (flujo completo por hoja)
# ---------------------------------------------------------------------------

class AutopilotRunner:
    """
    Motor del Modo Autopilot DB.

    Flujo por hoja:
      1. Extraer TODAS las preguntas de la hoja.
      2. Para cada pregunta sin respuesta en DB: elegir al azar.
         Para las que están en DB: responder directamente.
      3. Hacer clic en "Calificar".
      4. Leer feedback del DOM por data-item.
      5. Guardar correctas en DB; descartar incorrectas.
      6. Si hay incorrectas → "Intenta de nuevo" → repetir desde 2 con las que faltan.
      7. Cuando todas correctas (o agotados intentos) → "Siguiente".
    """

    def __init__(
        self,
        url: str = "",
        log_callback: Callable[[str, str], None] | None = None,
        stats_callback: Callable[[dict], None] | None = None,
        keep_browser_open: bool = False,
        browser: Optional["BotBrowser"] = None,
        bot_config: dict[str, Any] | None = None,
    ) -> None:
        self.url = url
        self.log_cb = log_callback or _default_log_callback
        self.stats_cb = stats_callback or (lambda _: None)
        self.keep_browser_open = keep_browser_open

        _cfg = bot_config or {}
        if hasattr(_cfg, "dict") and callable(getattr(_cfg, "dict")):
            _cfg = _cfg.dict()
        self._pw_timeout_ms: int = int(_cfg.get("pw_timeout_ms", 120000))
        self._pw_headless: bool = bool(_cfg.get("pw_headless", False))

        self.ap_cfg = _load_autopilot_config()
        self.timings = self.ap_cfg["timings"]
        self.limits = self.ap_cfg["limits"]
        self.auth_cfg = self.ap_cfg["auth"]

        self.db = DBManager()
        self.browser: Optional["BotBrowser"] = browser
        self._owned_browser = browser is None

        # Estadísticas de sesión
        self.stats = {
            "total_registros_db": self.db.contar_registros(),
            "respondidas_desde_db": 0,
            "respondidas_al_azar": 0,
            "nuevas_guardadas": 0,
            "hojas_completadas": 0,
        }

        self._running = False
        self._paused = False
        self._last_submit_payloads: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Control externo
    # ------------------------------------------------------------------

    def stop(self) -> None:
        self._running = False

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    # ------------------------------------------------------------------
    # Log helpers
    # ------------------------------------------------------------------

    def _log(self, msg: str, level: str = "INFO") -> None:
        self.log_cb(msg, level)

    def _emit_stats(self) -> None:
        self.stats["total_registros_db"] = self.db.contar_registros()
        self.stats_cb(dict(self.stats))

    # ------------------------------------------------------------------
    # Extracción DOM
    # ------------------------------------------------------------------

    def _extraer_todas_las_preguntas(self) -> list[dict] | None:
        """
        Extrae TODAS las preguntas y opciones del DOM actual.
        Retorna lista de dicts con: question, data_item, options[], answered.
        """
        if not self.browser or not self.browser.page:
            return None
        try:
            result = self.browser.page.evaluate(_JS_EXTRACT_ALL)
            if not result:
                return None

            try:
                from core.mathjax_parser import MathJaxParser
                from bs4 import BeautifulSoup
                math_parser = MathJaxParser()
                for p in result:
                    q_html = p.get("question_html")
                    if q_html:
                        try:
                            cleaned_html = math_parser.replace_mathjax(q_html)
                            q_text = BeautifulSoup(cleaned_html, "html.parser").get_text().strip()
                            q_text = re.sub(r"\s+", " ", q_text)
                            
                            # Preservar las etiquetas [img: ...] del JS
                            js_imgs = re.findall(r"\[img:\s*[^\]]+\]", p.get("question", ""))
                            if js_imgs:
                                q_text = f"{q_text} {' '.join(js_imgs)}"
                            
                            if q_text:
                                p["question"] = q_text
                        except Exception as e:
                            self._log(f"Error al limpiar HTML de pregunta: {e}", "DEBUG")

                    for o in p.get("options", []):
                        o_html = o.get("html")
                        if o_html:
                            try:
                                cleaned_html = math_parser.replace_mathjax(o_html)
                                o_text = BeautifulSoup(cleaned_html, "html.parser").get_text().strip()
                                o_text = re.sub(r"\s+", " ", o_text)
                                
                                # Preservar las etiquetas [img: ...] del JS
                                js_opt_imgs = re.findall(r"\[img:\s*[^\]]+\]", o.get("texto", ""))
                                if js_opt_imgs:
                                    o_text = f"{o_text} {' '.join(js_opt_imgs)}"
                                
                                if o_text:
                                    o["texto"] = o_text
                            except Exception as e:
                                self._log(f"Error al limpiar HTML de opción: {e}", "DEBUG")
            except Exception as exc:
                self._log(f"Error en post-procesamiento MathJax: {exc}", "DEBUG")

            return result
        except Exception as exc:
            self._log(f"Error al extraer preguntas del DOM: {exc}", "ERROR")
            return None
        try:
            result = self.browser.page.evaluate(_JS_EXTRACT_ALL)
            if not result:
                return None
            return result
        except Exception as exc:
            self._log(f"Error al extraer preguntas del DOM: {exc}", "ERROR")
            return None

    # ------------------------------------------------------------------
    # Espera de autenticación manual
    # ------------------------------------------------------------------

    def _wait_for_manual_auth_and_questions(self) -> bool:
        if not self.auth_cfg.get("wait_for_manual_auth", True):
            return True
        if not self.browser or not self.browser.page:
            return False

        timeout_sec = float(self.auth_cfg.get("manual_auth_timeout_sec", 300))
        poll_sec = max(float(self.auth_cfg.get("manual_auth_poll_sec", 1.0)), 0.2)
        started_at = time.monotonic()

        self._log(
            "Navegador abierto. Autentícate manualmente y navega hasta la hoja de preguntas; "
            "el Autopilot iniciará cuando detecte preguntas con opciones.",
            "INFO",
        )

        while self._running:
            self._check_pause()
            preguntas = self._extraer_todas_las_preguntas()
            if preguntas and any(q.get("options") for q in preguntas):
                self._log("Preguntas detectadas. Iniciando flujo Autopilot DB.", "SUCCESS")
                return True
            if self._page_has_next_button():
                self._log("Botón Siguiente detectado. Iniciando flujo Autopilot DB.", "SUCCESS")
                return True
            if timeout_sec > 0 and time.monotonic() - started_at >= timeout_sec:
                self._log(
                    f"No se detectaron preguntas después de {timeout_sec:.0f}s de espera.",
                    "ERROR",
                )
                return False
            time.sleep(poll_sec)

        return False

    # ------------------------------------------------------------------
    # Detección de botones
    # ------------------------------------------------------------------

    def _page_has_next_button(self) -> bool:
        if not self.browser or not self.browser.page:
            return False
        try:
            next_selectors = self.ap_cfg["selectors"]["next_button"]
            return bool(self.browser.page.evaluate(_JS_FIND_BUTTON, next_selectors))
        except Exception:
            return False

    def _find_and_mark_button(self, selector_list: list[str]) -> str | None:
        """Encuentra el primer botón visible de la lista y retorna su selector temporal."""
        if not self.browser or not self.browser.page:
            return None
        try:
            return self.browser.page.evaluate(_JS_FIND_BUTTON, selector_list)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Clic en opciones
    # ------------------------------------------------------------------

    def _js_click_selector(self, selector: str) -> bool:
        if not self.browser or not self.browser.page:
            return False
        if ":has-text(" in selector:
            return False
        try:
            clicked = self.browser.page.evaluate(
                r"""(sel) => {
                    const el = document.querySelector(sel);
                    if (!el) return false;
                    el.click();
                    return true;
                }""",
                selector,
            )
            time.sleep(self.timings.get("after_click_wait_ms", 600) / 1000)
            return bool(clicked)
        except Exception as exc:
            self._log(f"Error JS click '{selector}': {exc}", "DEBUG")
            return False

    def _click_selector_with_fallback(self, selector: str) -> bool:
        if not selector or not self.browser or not self.browser.page:
            return False
        for click_kwargs in ({}, {"force": True}):
            try:
                self.browser.page.click(selector, timeout=5000, **click_kwargs)
                time.sleep(self.timings.get("after_click_wait_ms", 600) / 1000)
                return True
            except Exception:
                continue
        return self._js_click_selector(selector)

    def _click_by_visible_text(self, text_hint: str) -> bool:
        if not text_hint or not self.browser or not self.browser.page:
            return False
        try:
            clicked = self.browser.page.evaluate(_JS_CLICK_BY_TEXT, text_hint)
            if clicked:
                time.sleep(self.timings.get("after_click_wait_ms", 600) / 1000)
            return bool(clicked)
        except Exception as exc:
            self._log(f"Error JS click por texto '{text_hint}': {exc}", "DEBUG")
            return False

    def _hacer_clic_en_opcion(self, selector: str, click_selector: str | None = None) -> bool:
        target = click_selector or selector
        if self._click_selector_with_fallback(target):
            return True
        if selector != target and self._click_selector_with_fallback(selector):
            return True
        self._log(f"Error al hacer clic en '{selector}'.", "WARNING")
        return False

    # ------------------------------------------------------------------
    # Botones de submit / reload / siguiente
    # ------------------------------------------------------------------

    def _start_submit_response_capture(self) -> Callable[[Any], None] | None:
        """Registra respuestas de red recientes para leer feedback AJAX/HTML."""
        if not self.browser or not self.browser.page:
            return None

        self._last_submit_payloads = []
        responses: list[Any] = []

        def _handler(response: Any) -> None:
            try:
                resource_type = getattr(response.request, "resource_type", "")
                if resource_type not in {"xhr", "fetch", "document"}:
                    return
                responses.append(response)
            except Exception:
                return

        self._pending_submit_responses = responses
        try:
            self.browser.page.on("response", _handler)
            return _handler
        except Exception:
            return None

    def _submit_response_priority(self, response: Any, text: str, content_type: str) -> int:
        """Prioriza respuestas que parecen ser el XHR de feedback de la unidad."""
        score = 0
        request = getattr(response, "request", None)
        request_url = getattr(request, "url", "") if request is not None else ""
        response_url = getattr(response, "url", "")
        method = getattr(request, "method", "") if request is not None else ""
        post_data = ""
        if request is not None:
            try:
                raw_post_data = getattr(request, "post_data", "")
                post_data = raw_post_data() if callable(raw_post_data) else raw_post_data
            except Exception:
                post_data = ""

        location_text = _normalize_feedback_text(
            f"{response_url} {request_url} {method} {post_data or ''}"
        )
        compact_location = re.sub(r"[^a-z0-9]+", "", location_text)
        payload_text = _normalize_feedback_text(text[:20000])

        hints = self.ap_cfg.get("network", {}).get(
            "feedback_url_hints",
            ["registrar", "unidad", "registrar unidad"],
        )
        for hint in hints:
            hint_text = _normalize_feedback_text(hint)
            if not hint_text:
                continue
            compact_hint = re.sub(r"[^a-z0-9]+", "", hint_text)
            hint_words = [word for word in hint_text.split() if word]
            if hint_text in location_text or (compact_hint and compact_hint in compact_location):
                score += 35
            elif hint_words and all(
                word in location_text or word in compact_location
                for word in hint_words
            ):
                score += 25

        if "json" in content_type:
            score += 5
        if "front" in payload_text and "id_item" in payload_text and "class" in payload_text:
            score += 100
        if "success" in payload_text and ("wrong" in payload_text or "correct" in payload_text):
            score += 20

        return score

    def _finish_submit_response_capture(self, handler: Callable[[Any], None] | None) -> None:
        if not self.browser or not self.browser.page:
            return

        if handler:
            try:
                self.browser.page.remove_listener("response", handler)
            except Exception:
                try:
                    self.browser.page.off("response", handler)
                except Exception:
                    pass

        payloads: list[dict[str, Any]] = []
        responses = getattr(self, "_pending_submit_responses", [])
        for index, response in enumerate(list(responses)[-20:]):
            try:
                headers = getattr(response, "headers", {}) or {}
                content_type = headers.get("content-type", "").lower()
                if not any(part in content_type for part in ("json", "text", "html", "javascript")):
                    continue
                text = response.text()
                if not text:
                    continue
                priority = self._submit_response_priority(response, text, content_type)
                payloads.append({
                    "url": getattr(response, "url", ""),
                    "content_type": content_type,
                    "text": text[:200000],
                    "priority": priority,
                    "index": index,
                })
            except Exception:
                continue

        self._last_submit_payloads = payloads
        self._pending_submit_responses = []
        if payloads:
            likely_feedback = sum(1 for item in payloads if int(item.get("priority", 0)) >= 60)
            extra = f"; {likely_feedback} parecen feedback de Registrar unidad" if likely_feedback else ""
            self._log(
                f"Capturadas {len(payloads)} respuesta(s) del servidor tras 'Calificar'{extra}.",
                "DEBUG",
            )

    def _presionar_calificar(self) -> bool:
        """Hace clic en el botón 'Calificar' (btn-submit) para enviar la hoja."""
        submit_selectors = self.ap_cfg["selectors"]["submit_button"]
        found = self._find_and_mark_button(submit_selectors)
        if found:
            self._log("Botón 'Calificar' encontrado. Haciendo clic...", "INFO")
            response_handler = self._start_submit_response_capture()
            ok = self._click_selector_with_fallback(found)
            if ok:
                wait_ms = self.timings.get("after_submit_wait_ms", 2000)
                self._log(f"'Calificar' presionado. Esperando {wait_ms}ms para feedback...", "INFO")
                time.sleep(wait_ms / 1000)
                try:
                    self.browser.page.wait_for_load_state("networkidle", timeout=3000)
                except Exception:
                    pass
                self._finish_submit_response_capture(response_handler)
                return True
            self._finish_submit_response_capture(response_handler)
        self._log("No se encontró botón 'Calificar'. ¿Ya fue presionado o no está visible?", "WARNING")
        return False

    def _presionar_reintentar(self) -> bool:
        """Hace clic en 'Intenta de nuevo' (btn-reload) para reiniciar la hoja."""
        reload_selectors = (
            self.ap_cfg["selectors"].get("reload_button")
            or self.ap_cfg["selectors"].get("retry_button", [])
        )
        found = self._find_and_mark_button(reload_selectors)
        if found:
            self._log("Botón 'Intenta de nuevo' encontrado. Haciendo clic...", "INFO")
            ok = self._click_selector_with_fallback(found)
            if ok:
                wait_ms = self.timings.get("reload_wait_ms", 2500)
                time.sleep(wait_ms / 1000)
                try:
                    self.browser.page.wait_for_load_state("load", timeout=self._pw_timeout_ms)
                except Exception:
                    pass
                return True

        for text_hint in ["Intenta de nuevo", "Reintentar", "Intentar de nuevo", "Try again"]:
            if self._click_by_visible_text(text_hint):
                wait_ms = self.timings.get("reload_wait_ms", 2500)
                time.sleep(wait_ms / 1000)
                try:
                    self.browser.page.wait_for_load_state("load", timeout=self._pw_timeout_ms)
                except Exception:
                    pass
                self._log(f"Reintentando con botón '{text_hint}'.", "INFO")
                return True

        # Fallback: page.reload()
        self._log("Botón 'Intenta de nuevo' no encontrado. Recargando página...", "WARNING")
        try:
            self.browser.page.reload(timeout=self._pw_timeout_ms, wait_until="load")
            time.sleep(self.timings.get("reload_wait_ms", 2500) / 1000)
            return True
        except Exception as exc:
            self._log(f"Error al recargar: {exc}", "ERROR")
            return False

    def ir_a_siguiente_hoja(self) -> bool:
        """Hace clic en 'Siguiente' y espera la carga de la nueva hoja."""
        if not self.browser or not self.browser.page:
            return False

        next_selectors = self.ap_cfg["selectors"]["next_button"]
        found = self._find_and_mark_button(next_selectors)
        if found:
            self._log("Botón 'Siguiente' encontrado. Avanzando...", "INFO")
            ok = self._click_selector_with_fallback(found)
            if ok:
                wait_ms = self.timings.get("next_wait_ms", 3000)
                time.sleep(wait_ms / 1000)
                try:
                    self.browser.page.wait_for_load_state("load", timeout=self._pw_timeout_ms)
                except Exception:
                    pass

                # Comprobar si la navegación llevó inesperadamente al buscador
                try:
                    current_url = getattr(self.browser.page, "url", "") or ""
                    if isinstance(current_url, str) and "buscador" in current_url.lower():
                        self._log(
                            f"Click en 'Siguiente' redirigió a {current_url}. Revirtiendo y probando otra estrategia.",
                            "WARNING",
                        )
                        try:
                            self.browser.page.go_back(timeout=self._pw_timeout_ms)
                            try:
                                self.browser.page.wait_for_load_state("load", timeout=self._pw_timeout_ms)
                            except Exception:
                                pass
                        except Exception:
                            pass

                        for text_hint in ["Siguiente", "Next", "Continuar", "Submit", "Enviar"]:
                            if self._click_by_visible_text(text_hint):
                                wait_ms = self.timings.get("next_wait_ms", 3000)
                                time.sleep(wait_ms / 1000)
                                try:
                                    self.browser.page.wait_for_load_state("load", timeout=self._pw_timeout_ms)
                                except Exception:
                                    pass
                                self._log(f"Avanzado con botón '{text_hint}'.", "SUCCESS")
                                return True

                        return False
                except Exception:
                    pass

                return True

        for text_hint in ["Siguiente", "Next", "Continuar", "Submit", "Enviar"]:
            if self._click_by_visible_text(text_hint):
                wait_ms = self.timings.get("next_wait_ms", 3000)
                time.sleep(wait_ms / 1000)
                try:
                    self.browser.page.wait_for_load_state("load", timeout=self._pw_timeout_ms)
                except Exception:
                    pass
                self._log(f"Avanzado con botón '{text_hint}'.", "SUCCESS")
                return True

        self._log("No se encontró botón 'Siguiente'. ¿Fin del formulario?", "WARNING")
        return False

    # ------------------------------------------------------------------
    # Validación de feedback por pregunta
    # ------------------------------------------------------------------

    def _classify_from_submit_payloads(self, data_item: str, opcion: dict | None = None) -> str:
        """Busca feedback en las respuestas del servidor capturadas al calificar."""
        option_text = (opcion or {}).get("texto", "")
        data_op = (opcion or {}).get("data_op", "")

        payloads = sorted(
            self._last_submit_payloads,
            key=lambda item: (int(item.get("priority", 0)), int(item.get("index", 0))),
            reverse=True,
        )
        for payload in payloads:
            text = payload.get("text", "")
            if not text:
                continue

            parsed: Any | None = None
            content_type = payload.get("content_type", "")
            if "json" in content_type:
                try:
                    parsed = json.loads(text)
                except Exception:
                    parsed = None
            if parsed is None:
                stripped = text.strip()
                if stripped.startswith("{") or stripped.startswith("["):
                    try:
                        parsed = json.loads(stripped)
                    except Exception:
                        parsed = None

            if parsed is not None:
                front_feedback = _classify_feedback_front(parsed, data_item)
                if front_feedback != "unknown":
                    return front_feedback

                generic_feedback = _classify_feedback_json(parsed, data_item, data_op, option_text)
                if generic_feedback != "unknown":
                    return generic_feedback

            payload_text = _normalize_feedback_text(text)
            data_item_norm = _normalize_feedback_text(data_item)
            if data_item_norm and data_item_norm in payload_text:
                front_text_feedback = _classify_feedback_front_text(text, data_item)
                if front_text_feedback != "unknown":
                    return front_text_feedback

                feedback = _classify_feedback_words(payload_text)
                if feedback != "unknown":
                    return feedback

        return "unknown"

    def _feedback_snapshot(self, data_item: str, opcion: dict | None = None) -> dict | None:
        if not self.browser or not self.browser.page:
            return None
        payload = {
            "data_item": data_item,
            "selector": (opcion or {}).get("selector", ""),
            "data_op": (opcion or {}).get("data_op", ""),
        }
        try:
            snapshot = self.browser.page.evaluate(_JS_FEEDBACK_SNAPSHOT, payload)
            return snapshot if isinstance(snapshot, dict) else None
        except Exception:
            return None

    def _validar_pregunta(self, data_item: str, opcion: dict | None = None) -> str:
        """
        Evalúa la respuesta del servidor y luego el DOM para determinar si acertó.
        Retorna: 'correct' | 'incorrect' | 'unknown'
        """
        if not self.browser or not self.browser.page:
            return "unknown"

        server_feedback = self._classify_from_submit_payloads(data_item, opcion)
        if server_feedback != "unknown":
            self._log(f"  Feedback servidor id_item='{data_item[:24]}...' → {server_feedback}", "DEBUG")
            return server_feedback

        payload = {
            "data_item": data_item,
            "selector": (opcion or {}).get("selector", ""),
            "data_op": (opcion or {}).get("data_op", ""),
        }
        try:
            result = self.browser.page.evaluate(_JS_VALIDATE_QUESTION, payload)
            result = str(result)
            if result == "unknown":
                snapshot = self._feedback_snapshot(data_item, opcion)
                if snapshot:
                    self._log(f"  Diagnóstico feedback DOM id_item='{data_item[:24]}...': {snapshot}", "DEBUG")
            return result
        except Exception as exc:
            self._log(f"Error al validar pregunta '{data_item}': {exc}", "WARNING")
            return "unknown"

    def _check_cristales_in_payloads(self) -> int | None:
        """Busca el valor del campo 'cristales' en los payloads capturados del servidor."""
        for payload in self._last_submit_payloads:
            text = payload.get("text", "")
            if not text:
                continue
            match = re.search(r'"cristales"\s*:\s*(\d+)', text)
            if match:
                try:
                    return int(match.group(1))
                except Exception:
                    pass
            try:
                data = json.loads(text)
                if isinstance(data, dict):
                    val = self._find_key_recursive(data, "cristales")
                    if val is not None:
                        return int(val)
            except Exception:
                pass
        return None

    def _find_key_recursive(self, node: Any, target_key: str) -> Any:
        if isinstance(node, dict):
            if target_key in node:
                return node[target_key]
            for val in node.values():
                res = self._find_key_recursive(val, target_key)
                if res is not None:
                    return res
        elif isinstance(node, list):
            for item in node:
                res = self._find_key_recursive(item, target_key)
                if res is not None:
                    return res
        return None

    def _obtener_cristales_dom(self) -> int | None:
        if not self.browser or not self.browser.page:
            return None
        try:
            val = self.browser.page.evaluate(r"""() => {
                const elements = Array.from(document.querySelectorAll('*'));
                for (const el of elements) {
                    if (el.children.length === 0 && /cristal/i.test(el.innerText || '')) {
                        const text = el.innerText || '';
                        const match = text.match(/(\d+)/);
                        if (match) return parseInt(match[1], 10);
                    }
                }
                const dataEl = document.querySelector('[data-cristales], [id*="cristal"], [class*="cristal"]');
                if (dataEl) {
                    const val = dataEl.getAttribute('data-cristales') || dataEl.innerText || '';
                    const match = val.match(/(\d+)/);
                    if (match) return parseInt(match[1], 10);
                }
                return null;
            }""")
            return int(val) if val is not None else None
        except Exception:
            return None

    def _obtener_cristales(self) -> int | None:
        cristales_server = self._check_cristales_in_payloads()
        if cristales_server is not None:
            return cristales_server
        return self._obtener_cristales_dom()

    # ------------------------------------------------------------------
    # Pausa interactiva
    # ------------------------------------------------------------------

    def _check_pause(self) -> None:
        while self._paused and self._running:
            time.sleep(0.3)

    # ------------------------------------------------------------------
    # Lógica de respuesta para una pregunta individual
    # ------------------------------------------------------------------

    @staticmethod
    def _opcion_descartada(opcion: dict, desc_ops: set[str], desc_txt: set[str]) -> bool:
        data_op = opcion.get("data_op") or ""
        texto = opcion.get("texto") or ""
        return bool((data_op and data_op in desc_ops) or texto in desc_txt)

    def _elegir_opcion_para_pregunta(
        self,
        pregunta_obj: dict,
        opciones_descartadas: dict[str, dict[str, set]],
    ) -> dict | None:
        """
        Elige la opción a marcar para una pregunta dada.
        Primero consulta DB; si no está, elige al azar entre las no descartadas.
        Retorna el dict de la opción elegida, o None si no hay opciones disponibles.
        """
        texto_pregunta = pregunta_obj["question"]
        opciones: list[dict] = pregunta_obj["options"]
        hash_p = self.db.calcular_hash(texto_pregunta)

        # Conjunto de data_ops/textos descartados para esta pregunta
        desc_ops = opciones_descartadas.get(hash_p, {}).get("ops", set())
        desc_txt = opciones_descartadas.get(hash_p, {}).get("txt", set())

        # Inicializar el contador de intentos si no existe
        if not hasattr(self, "_attempt_counts"):
            self._attempt_counts = {}
        attempts_for_q = self._attempt_counts.setdefault(hash_p, {})

        # 1. Consultar DB — intentar por data_item (si existe), luego por hash,
        # y por último por selector/data_op entre las opciones actuales.
        respuesta_db = None
        data_item_val = pregunta_obj.get("data_item", "")
        if data_item_val:
            try:
                respuesta_db = self.db.consultar_por_data_item(data_item_val)
            except Exception:
                respuesta_db = None

        if respuesta_db is None:
            respuesta_db = self.db.consultar_db(hash_p)

        if respuesta_db is None:
            for o in opciones:
                for sel in (o.get("data_op") or "", o.get("selector") or ""):
                    if not sel:
                        continue
                    try:
                        db_row = self.db.consultar_por_selector(sel)
                    except Exception:
                        db_row = None
                    if db_row:
                        respuesta_db = {"texto": db_row.get("texto", ""), "selector": db_row.get("selector", "")}
                        break
                if respuesta_db is not None:
                    break

        if respuesta_db is not None:
            texto_correcto = respuesta_db.get("texto", "")
            selector_correcto = respuesta_db.get("selector", "")

            # 1.a Intentar emparejar por selector/data_op exacto
            opcion = None
            if selector_correcto:
                opcion = next(
                    (o for o in opciones if o.get("data_op") == selector_correcto or o.get("selector") == selector_correcto),
                    None,
                )

            # 1.b Intentar emparejar por texto normalizado
            if opcion is None and texto_correcto:
                target_norm = _normalize_feedback_text(texto_correcto)
                for o in opciones:
                    if _normalize_feedback_text(o.get("texto", "")) == target_norm:
                        opcion = o
                        break

            # 1.b-2 Fallback por comparación matemática flexible (agresiva)
            if opcion is None and texto_correcto:
                for o in opciones:
                    if _math_normalized_equals(o.get("texto", ""), texto_correcto):
                        opcion = o
                        break

            # 1.c Fallback por similitud sobre texto normalizado
            if opcion is None and texto_correcto:
                norm_target = _normalize_feedback_text(texto_correcto)
                cand_norms = [(_normalize_feedback_text(o.get("texto", "")), o) for o in opciones]
                if cand_norms:
                    mejor_norm, mejor_opt = max(cand_norms, key=lambda x: _similarity(x[0], norm_target))
                    if _similarity(mejor_norm, norm_target) >= 0.5:
                        opcion = mejor_opt

            if opcion:
                db_opcion_descartada = False
                if self._opcion_descartada(opcion, desc_ops, desc_txt):
                    db_opcion_descartada = True
                    self._log(
                        f"  [DB] Omitiendo opcion descartada para '{texto_pregunta[:50]}...' -> '{opcion['texto']}'",
                        "WARNING",
                    )
                else:
                    attempts_for_q[opcion["texto"]] = attempts_for_q.get(opcion["texto"], 0) + 1
                    self._log(f"  [DB] Respondiendo '{texto_pregunta[:50]}...' → '{opcion['texto']}'", "SUCCESS")
                    return opcion

                if db_opcion_descartada:
                    self._log(
                        f"  [DB] La respuesta guardada para '{texto_pregunta[:40]}...' "
                        "ya fue descartada en esta hoja; probando otra opcion.",
                        "WARNING",
                    )
            else:
                self._log("  [DB] Se encontró registro en BD pero no se pudo mapear a ninguna opción actual.", "WARNING")

        # 2. Elegir entre opciones no descartadas
        disponibles = [
            o for o in opciones
            if not self._opcion_descartada(o, desc_ops, desc_txt)
        ]

        max_attempts = int(self.limits.get("max_intentos_por_pregunta", 8))
        total_attempts = sum(attempts_for_q.values()) if attempts_for_q else 0

        if not disponibles:
            # Todas las opciones están marcadas como descartadas. Evitar forzar siempre
            # la misma opción: elegir la que tenga menos intentos entre todas.
            if total_attempts >= max_attempts:
                self._log(
                    f"  [AZAR] Límite de intentos alcanzado para '{texto_pregunta[:40]}...'; no habrá más reintentos.",
                    "WARNING",
                )
                return None

            # elegir opción descartada con menos intentos
            min_count = None
            candidates: list[dict] = []
            for o in opciones:
                c = attempts_for_q.get(o["texto"], 0)
                if min_count is None or c < min_count:
                    min_count = c
                    candidates = [o]
                elif c == min_count:
                    candidates.append(o)

            elegida = random.choice(candidates) if candidates else random.choice(opciones)
            attempts_for_q[elegida["texto"]] = attempts_for_q.get(elegida["texto"], 0) + 1
            self._log(
                f"  [AZAR] Todas las opciones fueron descartadas para '{texto_pregunta[:40]}...'; "
                f"seleccionando forzado '{elegida['texto']}' (intento #{attempts_for_q.get(elegida['texto'], 0)})",
                "WARNING",
            )
            return elegida

        # Elegir entre las disponibles la que tenga menos intentos (balancear exploración)
        min_count = None
        candidates = []
        for o in disponibles:
            c = attempts_for_q.get(o["texto"], 0)
            if min_count is None or c < min_count:
                min_count = c
                candidates = [o]
            elif c == min_count:
                candidates.append(o)

        elegida = random.choice(candidates) if candidates else random.choice(disponibles)
        attempts_for_q[elegida["texto"]] = attempts_for_q.get(elegida["texto"], 0) + 1
        self._log(f"  [AZAR] '{texto_pregunta[:50]}...' → '{elegida['texto']}'", "INFO")
        return elegida

    # ------------------------------------------------------------------
    # Bucle principal
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Bucle principal de hojas. Por cada hoja:
          - Extrae todas las preguntas.
          - Responde todas (DB o al azar).
          - Presiona 'Calificar'.
          - Lee feedback, guarda correctas, descarta incorrectas.
          - Reintenta si hay incorrectas; avanza cuando todas correctas.
        """
        self._running = True
        self._log("=== Modo Autopilot DB INICIADO ===", "SUCCESS")
        self._log(f"Registros en BD al inicio: {self.db.contar_registros()}", "INFO")

        # Abrir navegador si no se proporcionó uno externo
        opened_browser = False
        if not self.browser:
            from core.browser import BotBrowser
            self.browser = BotBrowser(headless=self._pw_headless)
            self._owned_browser = True
            if self.url:
                try:
                    self.browser.open(self.url, timeout_ms=self._pw_timeout_ms)
                    opened_browser = True
                    self._log(f"Navegador abierto en: {self.url}", "INFO")
                except Exception as exc:
                    self._log(f"Error al abrir el navegador: {exc}", "ERROR")
                    self._shutdown()
                    return
            else:
                self._log("No se proporcionó URL; asumiendo navegador ya en posición.", "WARNING")

        if opened_browser and not self._wait_for_manual_auth_and_questions():
            self._shutdown()
            return

        max_hojas = self.limits.get("max_sheets", 10000)
        max_rondas = self.limits.get("max_rondas_por_hoja", 20)
        hojas_procesadas = 0

        while self._running and hojas_procesadas < max_hojas:
            self._check_pause()
            if not self._running:
                break

            hojas_procesadas += 1
            self._log(f"── Procesando hoja {hojas_procesadas} ──", "INFO")

            # Estado de descarte por pregunta: hash → {ops: set, txt: set}
            opciones_descartadas: dict[str, dict[str, set]] = {}
            # Preguntas confirmadas correctas en esta hoja (por hash)
            confirmadas_correctas: set[str] = set()
            hoja_completada = False
            hoja_sin_preguntas = False

            for ronda in range(max_rondas):
                self._check_pause()
                if not self._running:
                    break

                # ── A. Extraer todas las preguntas ──────────────────────────
                time.sleep(self.timings.get("dom_stable_wait_ms", 700) / 1000)
                preguntas = self._extraer_todas_las_preguntas()

                if not preguntas:
                    self._log(
                        f"Hoja {hojas_procesadas}: no se detectaron preguntas. "
                        "Intentando avanzar...",
                        "WARNING",
                    )
                    hoja_sin_preguntas = True
                    break

                self._log(
                    f"  Ronda {ronda + 1}: {len(preguntas)} pregunta(s) detectada(s) en la hoja.",
                    "INFO",
                )

                # ── B. Responder preguntas (las no confirmadas aún) ─────────
                preguntas_a_responder = [
                    p for p in preguntas
                    if self.db.calcular_hash(p["question"]) not in confirmadas_correctas
                    or not p.get("answered")
                ]

                if not preguntas_a_responder:
                    self._log("Todas las preguntas de la hoja ya están confirmadas como correctas.", "SUCCESS")
                    hoja_completada = True
                    break

                elegidas: dict[str, dict] = {}  # hash_p → opción elegida

                for pregunta_obj in preguntas_a_responder:
                    if not self._running:
                        break
                    self._check_pause()

                    hash_p = self.db.calcular_hash(pregunta_obj["question"])
                    opcion = self._elegir_opcion_para_pregunta(pregunta_obj, opciones_descartadas)

                    if opcion is None:
                        self._log(
                            f"  Sin opciones disponibles para '{pregunta_obj['question'][:40]}...'. Saltando.",
                            "WARNING",
                        )
                        continue

                    ok = self._hacer_clic_en_opcion(opcion["selector"], opcion.get("clickSelector"))
                    if ok:
                        elegidas[hash_p] = opcion
                    else:
                        self._log(f"  Clic fallido en '{opcion['texto']}'. Descartando.", "WARNING")
                        self._registrar_descarte(opciones_descartadas, hash_p, opcion)

                if not elegidas:
                    self._log("No se pudo marcar ninguna opción. Abortando hoja.", "ERROR")
                    break

                # ── C. Presionar 'Calificar' ────────────────────────────────
                calificado = self._presionar_calificar()
                if not calificado:
                    self._log("No se pudo presionar 'Calificar'. Reintentando en la siguiente ronda.", "WARNING")
                    # Esperar y continuar (quizá el botón aparezca)
                    time.sleep(self.timings.get("feedback_wait_ms", 1500) / 1000)
                    continue

                # ── D. Leer feedback del DOM ────────────────────────────────
                time.sleep(self.timings.get("feedback_wait_ms", 1500) / 1000)

                preguntas_incorrectas_en_ronda: list[dict] = []

                for pregunta_obj in preguntas_a_responder:
                    if not self._running:
                        break

                    hash_p = self.db.calcular_hash(pregunta_obj["question"])
                    data_item = pregunta_obj.get("data_item", "")
                    opcion_elegida = elegidas.get(hash_p)

                    if opcion_elegida is None:
                        continue

                    feedback = self._validar_pregunta(data_item, opcion_elegida)
                    self._log(
                        f"  Feedback '{pregunta_obj['question'][:40]}...' → {feedback} "
                        f"(opción: '{opcion_elegida['texto']}')",
                        "INFO",
                    )

                    if feedback == "correct":
                        # Guardar en DB si no está ya
                        if hash_p not in confirmadas_correctas:
                            selector_a_guardar = (
                                opcion_elegida.get("data_op") or opcion_elegida["selector"]
                            )
                            self._log(
                                f"  ✔ CORRECTO → guardando en DB: '{opcion_elegida['texto']}'",
                                "SUCCESS",
                            )
                            self.db.guardar_en_db(
                                hash_p,
                                pregunta_obj["question"],
                                opcion_elegida["texto"],
                                selector_correcto=selector_a_guardar,
                                inmediato=True,
                            )
                            confirmadas_correctas.add(hash_p)
                            self.stats["nuevas_guardadas"] += 1
                        self.stats["respondidas_desde_db"] += 1

                    elif feedback == "incorrect":
                        self._log(
                            f"  ✘ INCORRECTO → descartando '{opcion_elegida['texto']}'",
                            "WARNING",
                        )
                        self._registrar_descarte(opciones_descartadas, hash_p, opcion_elegida)
                        preguntas_incorrectas_en_ronda.append(pregunta_obj)
                        self.stats["respondidas_al_azar"] += 1

                    else:
                        self._log(
                            f"  ? Feedback desconocido para '{pregunta_obj['question'][:40]}...'. "
                            "se mantendrá pendiente.",
                            "WARNING",
                        )
                        preguntas_incorrectas_en_ronda.append(pregunta_obj)

                self._emit_stats()

                # ── E. Evaluar si debemos reintentar ────────────────────────
                pendientes = [
                    p for p in preguntas
                    if self.db.calcular_hash(p["question"]) not in confirmadas_correctas
                ]

                # Comprobar cristales si está disponible
                cristales = self._obtener_cristales()
                if cristales is not None:
                    self._log(f"  [CRISTALES] Detectados {cristales} de 3 esperados.", "INFO")

                if not pendientes:
                    if cristales is not None and cristales < 3:
                        self._log("  [CRISTALES] < 3 cristales detectados a pesar de no haber preguntas pendientes en el bot.", "WARNING")
                        self._log("  [CRISTALES] Posible colisión de preguntas o error de mapeo. Forzando reintento.", "WARNING")
                        confirmadas_correctas.clear()
                        pendientes = preguntas
                    else:
                        self._log(
                            f"Hoja {hojas_procesadas} completada en {ronda + 1} ronda(s). "
                            f"Guardadas: {len(confirmadas_correctas)} preguntas.",
                            "SUCCESS",
                        )
                        self.stats["hojas_completadas"] += 1
                        self._emit_stats()
                        hoja_completada = True
                        break

                self._log(
                    f"  {len(pendientes)} pregunta(s) incorrectas/pendientes. "
                    "Presionando 'Intenta de nuevo'...",
                    "WARNING",
                )
                reintentado = self._presionar_reintentar()
                if not reintentado:
                    self._log("No se pudo reintentar la hoja. Abortando.", "ERROR")
                    break

            # ── F. Ir a la siguiente hoja ────────────────────────────────────
            if not self._running:
                break

            if not hoja_completada and not hoja_sin_preguntas:
                self._log(
                    f"Hoja {hojas_procesadas} no completada: no se avanzará hasta confirmar todas las preguntas.",
                    "ERROR",
                )
                break

            self._log("Intentando avanzar a la siguiente hoja...", "INFO")
            if not self.ir_a_siguiente_hoja():
                self._log("No se pudo avanzar. Fin del formulario o error.", "SUCCESS")
                break

        self._log(
            f"=== Autopilot DB FINALIZADO. Hojas: {hojas_procesadas}. "
            f"Desde DB: {self.stats['respondidas_desde_db']}. "
            f"Al azar: {self.stats['respondidas_al_azar']}. "
            f"Nuevas guardadas: {self.stats['nuevas_guardadas']}. ===",
            "SUCCESS",
        )
        self._shutdown()

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _registrar_descarte(
        self,
        opciones_descartadas: dict[str, dict[str, set]],
        hash_p: str,
        opcion: dict,
    ) -> None:
        """Registra una opción como descartada para una pregunta dada."""
        if hash_p not in opciones_descartadas:
            opciones_descartadas[hash_p] = {"ops": set(), "txt": set()}
        if opcion.get("data_op"):
            opciones_descartadas[hash_p]["ops"].add(opcion["data_op"])
        opciones_descartadas[hash_p]["txt"].add(opcion["texto"])

    def _shutdown(self) -> None:
        """Cierra BD y navegador de forma limpia."""
        self._running = False
        flushed = self.db.flush_buffer()
        if flushed:
            self._log(f"Buffer final: {flushed} registros escritos en BD.", "INFO")
        self.db.close()

        if self.browser and self._owned_browser:
            if self.keep_browser_open or self.ap_cfg.get("browser", {}).get("keep_open", False):
                self._log("Manteniendo navegador abierto según configuración.", "INFO")
            else:
                self._log("Cerrando navegador Playwright...", "INFO")
                try:
                    self.browser.close()
                except Exception:
                    pass
                self.browser = None

    # ------------------------------------------------------------------
    # Compatibilidad con la interfaz antigua (extraer_preguntas_y_opciones)
    # ------------------------------------------------------------------

    def extraer_preguntas_y_opciones(self) -> list[dict] | None:
        """
        Compatibilidad con código anterior. Retorna solo la primera pregunta sin responder.
        """
        preguntas = self._extraer_todas_las_preguntas()
        if not preguntas:
            return None
        # Filtrar las no respondidas
        sin_responder = [p for p in preguntas if not p.get("answered")]
        if not sin_responder:
            return None
        p = sin_responder[0]
        return [{
            "question": p["question"],
            "options": p["options"],
            "data_item": p.get("data_item", ""),
        }]

    def recargar_hoja_actual(self) -> bool:
        """Compatibilidad con código anterior."""
        return self._presionar_reintentar()


# ---------------------------------------------------------------------------
# Utilidad de similitud
# ---------------------------------------------------------------------------

def _similarity(a: str, b: str) -> float:
    """Similitud de Jaccard entre dos strings (tokenizados por palabras)."""
    if not a or not b:
        return 0.0
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


# ---------------------------------------------------------------------------
# Thread Qt — compatible con el widget existente (opcional)
# ---------------------------------------------------------------------------

try:
    from PyQt5.QtCore import QThread, pyqtSignal
    _HAS_PYQT = True
except ImportError:
    _HAS_PYQT = False

if _HAS_PYQT:
    class AutopilotRunnerThread(QThread):
        """
        Thread Qt que envuelve AutopilotRunner y emite señales compatibles
        con las del widget existente.
        """
        log_signal      = pyqtSignal(str, str)
        status_signal   = pyqtSignal(str)
        db_stats_signal = pyqtSignal(dict)

        def __init__(
            self,
            url: str,
            bot_config: dict,
            keep_browser_open: bool = False,
            parent: object = None,
        ) -> None:
            super().__init__(parent)
            self._url = url
            self._bot_config = bot_config
            self._keep_browser_open = keep_browser_open
            self._runner: Optional[AutopilotRunner] = None

        def run(self) -> None:
            self.status_signal.emit("running")
            self._runner = AutopilotRunner(
                url=self._url,
                bot_config=self._bot_config,
                log_callback=lambda msg, lvl: self.log_signal.emit(msg, lvl),
                stats_callback=lambda stats: self.db_stats_signal.emit(stats),
                keep_browser_open=self._keep_browser_open,
            )
            try:
                self._runner.run()
            except Exception as exc:
                self.log_signal.emit(f"Error crítico en Autopilot: {exc}", "ERROR")
            finally:
                self.status_signal.emit("idle")

        def pause(self) -> None:
            if self._runner:
                self._runner.pause()
            self.status_signal.emit("paused")

        def resume(self) -> None:
            if self._runner:
                self._runner.resume()
            self.status_signal.emit("running")

        def stop(self) -> None:
            if self._runner:
                self._runner.stop()
