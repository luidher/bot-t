from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageFilter, ImageOps
import pytesseract

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - optional quality improvement
    cv2 = None
    np = None

DEFAULT_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

if Path(DEFAULT_TESSERACT_PATH).exists():
    pytesseract.pytesseract.tesseract_cmd = DEFAULT_TESSERACT_PATH


@dataclass(frozen=True)
class OCRBox:
    text: str
    left: int
    top: int
    width: int
    height: int
    confidence: float

    @property
    def center(self) -> tuple[int, int]:
        return (self.left + self.width // 2, self.top + self.height // 2)


@dataclass(frozen=True)
class OCRResult:
    text: str
    boxes: list[OCRBox]


def preprocess_image(image: Image.Image) -> Image.Image:
    """Improve OCR on screenshots with small or anti-aliased text."""
    gray = ImageOps.grayscale(image)
    enlarged = gray.resize((gray.width * 2, gray.height * 2))
    sharpened = enlarged.filter(ImageFilter.SHARPEN)

    if cv2 is None or np is None:
        return sharpened

    array = np.array(sharpened)
    thresholded = cv2.adaptiveThreshold(
        array,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11,
    )
    return Image.fromarray(thresholded)


def run_ocr(
    image_or_path: Image.Image | str | Path,
    lang: str = "spa+eng",
    psm: int = 6,
    preprocess: bool = True,
) -> OCRResult:
    image = _load_image(image_or_path)
    ocr_image = preprocess_image(image) if preprocess else image
    config = f"--oem 3 --psm {psm}"

    text = pytesseract.image_to_string(ocr_image, lang=lang, config=config).strip()
    data = pytesseract.image_to_data(
        ocr_image,
        lang=lang,
        config=config,
        output_type=pytesseract.Output.DICT,
    )

    scale = 2 if preprocess else 1
    boxes = list(_boxes_from_tesseract(data, scale=scale))
    return OCRResult(text=text, boxes=boxes)


def _load_image(image_or_path: Image.Image | str | Path) -> Image.Image:
    if isinstance(image_or_path, Image.Image):
        return image_or_path
    return Image.open(image_or_path)


def _boxes_from_tesseract(data: dict, scale: int) -> Iterable[OCRBox]:
    total = len(data.get("text", []))
    for index in range(total):
        raw_text = str(data["text"][index]).strip()
        if not raw_text:
            continue

        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            confidence = -1.0

        if confidence < 0:
            continue

        yield OCRBox(
            text=raw_text,
            left=int(data["left"][index] / scale),
            top=int(data["top"][index] / scale),
            width=max(1, int(data["width"][index] / scale)),
            height=max(1, int(data["height"][index] / scale)),
            confidence=confidence,
        )


def leer_texto(ruta: str | Path = "screenshots/test.png") -> str:
    """Backward-compatible wrapper for the original script."""
    result = run_ocr(ruta)
    return result.text
