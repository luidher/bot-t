from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.ocr import OCRBox


@dataclass(frozen=True)
class ClickPlan:
    target_text: str
    score: float
    x: int
    y: int
    dry_run: bool


def plan_click_for_answer(
    answer: str,
    boxes: list["OCRBox"],
    region_offset: tuple[int, int] = (0, 0),
    min_score: float = 0.58,
    dry_run: bool = True,
) -> ClickPlan | None:
    if not answer.strip() or not boxes:
        return None

    lines = _group_boxes_by_line(boxes)
    best: ClickPlan | None = None
    offset_x, offset_y = region_offset

    for line_text, line_boxes in lines:
        score = _similarity(answer, line_text)
        if score < min_score:
            continue

        left = min(box.left for box in line_boxes)
        top = min(box.top for box in line_boxes)
        right = max(box.left + box.width for box in line_boxes)
        bottom = max(box.top + box.height for box in line_boxes)
        plan = ClickPlan(
            target_text=line_text,
            score=score,
            x=offset_x + (left + right) // 2,
            y=offset_y + (top + bottom) // 2,
            dry_run=dry_run,
        )

        if best is None or plan.score > best.score:
            best = plan

    return best


def execute_click(plan: ClickPlan, pause_before_click: float = 0.2) -> None:
    if plan.dry_run:
        return

    import pyautogui

    time.sleep(pause_before_click)
    pyautogui.moveTo(plan.x, plan.y, duration=0.15)
    pyautogui.click()


def _group_boxes_by_line(boxes: list["OCRBox"]) -> list[tuple[str, list["OCRBox"]]]:
    sorted_boxes = sorted(boxes, key=lambda box: (box.top, box.left))
    lines: list[list["OCRBox"]] = []

    for box in sorted_boxes:
        placed = False
        for line in lines:
            avg_top = sum(item.top for item in line) / len(line)
            avg_height = sum(item.height for item in line) / len(line)
            if abs(box.top - avg_top) <= max(8, avg_height * 0.65):
                line.append(box)
                placed = True
                break

        if not placed:
            lines.append([box])

    grouped = []
    for line in lines:
        line.sort(key=lambda box: box.left)
        text = " ".join(box.text for box in line)
        grouped.append((text, line))
    return grouped


def _similarity(left: str, right: str) -> float:
    left_norm = _normalize(left)
    right_norm = _normalize(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm in right_norm or right_norm in left_norm:
        return 1.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _normalize(value: str) -> str:
    return " ".join(value.lower().strip().split())
