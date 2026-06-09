"""Multi-page manager for tracking progress across form pages."""
from __future__ import annotations

import time
from typing import Any, List, Optional, Tuple
from core.capture import capture_screen
from core.ocr import run_ocr
from core.actions import plan_click_for_answer, execute_click


class PageManager:
    def __init__(self, max_pages: int = 50) -> None:
        self.max_pages = max_pages
        self.current_page: int = 1
        self.total_pages: Optional[int] = None
        self.history: List[dict] = []  # [{"question": str, "answer": str, "page": int}]
        self.completed: bool = False

    def record(self, question: str, answer: str) -> None:
        """Record a question and answer for the current page."""
        self.history.append({
            "question": question,
            "answer": answer,
            "page": self.current_page
        })

    def try_next(self, browser: Any = None, region: Optional[Tuple[int, int, int, int]] = None, config: Any = None) -> bool:
        """
        Attempts to click the 'Next' / 'Submit' button.
        - If browser is provided, uses Playwright DOM logic.
        - If browser is None, captures screen and uses OCR + pyautogui coordinates.
        Returns True if a button was found and clicked, False otherwise.
        """
        if self.current_page >= self.max_pages:
            self.completed = True
            return False

        # 1. Playwright Mode
        if browser is not None:
            next_selectors = [
                'button[type="submit"]',
                'input[type="submit"]',
                '.btn-submit',
                'button:has-text("Siguiente")',
                'button:has-text("Next")',
                'button:has-text("Continuar")',
                'button:has-text("Calificar")',
                'input[value="Siguiente"]',
                'input[value="Next"]',
                'input[value="Continuar"]',
                'input[value="Calificar"]',
                'a:has-text("Siguiente")',
                'a:has-text("Next")',
                'a:has-text("Continuar")',
                'a.next',
                '.next'
            ]
            for selector in next_selectors:
                # Check if visible/enabled
                try:
                    loc = browser.page.locator(selector)
                    if loc.count() > 0 and loc.first.is_visible() and loc.first.is_enabled():
                        # Click the button
                        success = browser.next_page(selector)
                        if success:
                            self.current_page += 1
                            return True
                except Exception:
                    continue
            return False

        # 2. Vision Mode
        else:
            try:
                lang = config.lang if config else "spa+eng"
                psm = config.psm if config else 6
                no_preprocess = config.no_preprocess if config else False
                tess_cmd = config.tesseract_cmd if config else None
                
                if tess_cmd:
                    try:
                        import pytesseract
                        pytesseract.pytesseract.tesseract_cmd = tess_cmd
                    except ImportError:
                        pass

                capture = capture_screen(region=region, filename="latest_web_capture.png")
                ocr = run_ocr(
                    capture.image,
                    lang=lang,
                    psm=psm,
                    preprocess=not no_preprocess
                )

                targets = ["Siguiente", "Next", "Continuar", "Calificar", "Enviar", "Terminar"]
                offset = (region[0], region[1]) if region else (0, 0)

                for target in targets:
                    plan = plan_click_for_answer(
                        target,
                        ocr.boxes,
                        region_offset=offset,
                        min_score=0.5,
                        dry_run=False  # Execute real clicks for page transition
                    )
                    if plan:
                        execute_click(plan)
                        self.current_page += 1
                        time.sleep(2.0)  # Wait for page load
                        return True
            except Exception as e:
                print(f"[PAGE MANAGER WARNING] Error in vision next page click: {e}")
            
            return False

    def is_done(self) -> bool:
        """Returns True if the maximum pages limit or completion state is reached."""
        return self.completed or (self.current_page > self.max_pages)
