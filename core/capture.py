from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image
import pyautogui

Region = Tuple[int, int, int, int]


@dataclass(frozen=True)
class CaptureResult:
    image: Image.Image
    path: Path
    region: Optional[Region]


def capture_screen(
    output_dir: str | Path = "screenshots",
    region: Optional[Region] = None,
    filename: str | None = None,
) -> CaptureResult:
    """Capture the full screen or a region as a PIL image.

    region uses the pyautogui convention: x, y, width, height.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    image = pyautogui.screenshot(region=region)
    if not isinstance(image, Image.Image):
        image = Image.frombytes("RGB", image.size, image.tobytes())

    if filename is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screen_{stamp}.png"

    path = output_path / filename
    image.save(path)

    return CaptureResult(image=image, path=path, region=region)


def tomar_screenshot() -> str:
    """Backward-compatible wrapper for the original script."""
    return str(capture_screen(filename="test.png").path)
