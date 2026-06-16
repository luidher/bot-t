from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
import uuid


MediaRole = Literal["question", "option"]


@dataclass(frozen=True)
class MediaItem:
    path: str
    role: MediaRole
    option_index: int | None = None
    option_label: str | None = None
    selector: str = ""


def extract_media(page: Any, question_selector: str, option_selectors: list[str]) -> list[MediaItem]:
    """Extract visual media from a DOM question and save element screenshots."""
    session_dir = Path("tmp") / uuid.uuid4().hex[:12]
    session_dir.mkdir(parents=True, exist_ok=True)

    items: list[MediaItem] = []

    question_root = _query_element(page, question_selector)
    if question_root:
        question_images = _query_all(question_root, "img")
        if not question_images and _matches(question_root, "img"):
            question_images = [question_root]

        for index, image in enumerate(question_images, start=1):
            selector = _unique_selector(image)
            path = session_dir / f"question_{index}.png"
            if _screenshot_element(page, image, path):
                items.append(
                    MediaItem(
                        path=str(path),
                        role="question",
                        selector=selector,
                    )
                )

    for option_index, option_selector in enumerate(option_selectors):
        option_root = _option_root(page, option_selector)
        if not option_root:
            continue

        target = _find_option_visual_target(option_root)
        if not target:
            continue

        label = _option_label(option_index)
        selector = _unique_selector(target)
        path = session_dir / f"option_{label}.png"
        if _screenshot_element(page, target, path):
            items.append(
                MediaItem(
                    path=str(path),
                    role="option",
                    option_index=option_index,
                    option_label=label,
                    selector=selector,
                )
            )

    return items


def _query_element(page: Any, selector: str) -> Any | None:
    if not selector:
        return None
    try:
        return page.query_selector(selector)
    except Exception:
        return None


def _query_all(element: Any, selector: str) -> list[Any]:
    try:
        return list(element.query_selector_all(selector))
    except Exception:
        return []


def _matches(element: Any, selector: str) -> bool:
    try:
        return bool(element.evaluate("(el, selector) => el.matches(selector)", selector))
    except Exception:
        return False


def _option_root(page: Any, selector: str) -> Any | None:
    if not selector:
        return None
    try:
        handle = page.evaluate_handle(
            """
            (selector) => {
                const el = document.querySelector(selector);
                if (!el) return null;
                if (!el.matches('input[type="radio"], input[type="checkbox"]')) return el;
                if (el.closest('label')) return el.closest('label');
                if (el.id) {
                    const label = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                    if (label) return label;
                }
                return el.parentElement || el;
            }
            """,
            selector,
        )
        return handle.as_element()
    except Exception:
        return None


def _find_option_visual_target(option_root: Any) -> Any | None:
    try:
        handle = option_root.evaluate_handle(
            """
            (root) => {
                if (root.matches('img, canvas')) return root;

                const media = root.querySelector('img, canvas');
                if (media) return media;

                const candidates = [root, ...root.querySelectorAll('*')];
                return candidates.find((el) => {
                    const bg = getComputedStyle(el).backgroundImage;
                    return bg && bg !== 'none';
                }) || null;
            }
            """
        )
        return handle.as_element()
    except Exception:
        return None


def _screenshot_element(page: Any, element: Any, path: Path) -> bool:
    try:
        _wait_for_lazy_load(page, element)
        element.screenshot(path=str(path))
        return True
    except Exception as e:
        print(f"[MEDIA WARNING] No se pudo capturar media DOM: {e}")
        return False


def _wait_for_lazy_load(page: Any, element: Any) -> None:
    try:
        element.scroll_into_view_if_needed()
    except Exception:
        pass

    try:
        page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        pass

    try:
        tag_name = str(element.evaluate("(el) => el.tagName.toLowerCase()"))
    except Exception:
        tag_name = ""

    if tag_name == "img":
        try:
            element.evaluate(
                """
                (img) => new Promise((resolve) => {
                    if (img.complete && img.naturalWidth > 0) {
                        resolve(true);
                        return;
                    }
                    const done = () => resolve(img.complete && img.naturalWidth > 0);
                    img.addEventListener('load', done, { once: true });
                    img.addEventListener('error', () => resolve(false), { once: true });
                    setTimeout(done, 4000);
                })
                """
            )
        except Exception:
            pass
    else:
        try:
            page.wait_for_timeout(250)
        except Exception:
            pass


def _unique_selector(element: Any) -> str:
    try:
        return str(
            element.evaluate(
                """
                (el) => {
                    if (el.id) return `#${CSS.escape(el.id)}`;
                    const path = [];
                    let curr = el;
                    while (curr && curr.nodeType === Node.ELEMENT_NODE) {
                        let selector = curr.nodeName.toLowerCase();
                        if (curr.classList.length) {
                            selector += Array.from(curr.classList)
                                .slice(0, 2)
                                .map((name) => `.${CSS.escape(name)}`)
                                .join('');
                        }
                        if (curr.parentNode) {
                            const siblings = Array.from(curr.parentNode.children)
                                .filter((child) => child.nodeName === curr.nodeName);
                            if (siblings.length > 1) {
                                selector += `:nth-of-type(${siblings.indexOf(curr) + 1})`;
                            }
                        }
                        path.unshift(selector);
                        curr = curr.parentElement;
                    }
                    return path.join(' > ');
                }
                """
            )
        )
    except Exception:
        return ""


def _option_label(index: int) -> str:
    label = ""
    value = index
    while True:
        label = chr(ord("A") + (value % 26)) + label
        value = (value // 26) - 1
        if value < 0:
            return label
