"""Playwright browser automation module for DOM-based reading and interaction."""
from __future__ import annotations
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page


class BotBrowser:
    def __init__(self, headless: bool = False) -> None:
        self.headless = headless
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def open(self, url: str, timeout_ms: int = 30000) -> None:
        """Launch browser and open the target URL."""
        if not self._playwright:
            self._playwright = sync_playwright().start()

        if not self._browser:
            self._browser = self._playwright.chromium.launch(headless=self.headless)
            self._context = self._browser.new_context(
                viewport={"width": 1280, "height": 800}
            )
            self.page = self._context.new_page()

        assert self.page is not None
        self.page.set_default_timeout(timeout_ms)
        self.page.goto(url, timeout=timeout_ms, wait_until="load")
        self.page.wait_for_load_state("load", timeout=timeout_ms)
        time.sleep(1.0)

    def read_page(self, skip_questions: Optional[set[str] | list[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Extract the current unanswered question, options, and their CSS selectors.
        Returns a dict: {"question": str, "options": List[str], "selectors": List[str]}
        or None if no question is found or all questions on page are answered.
        """
        if not self.page:
            return None

        # Execute extraction script in the DOM context
        js_extractor = r"""
        (skipQuestionsArg) => {
            const skipQuestions = new Set((skipQuestionsArg || []).map(q => (q || "").replace(/\s+/g, " ").trim()));

            // Find all question containers
            const containers = Array.from(document.querySelectorAll('ul.form-items > li, .form-items > li, li[data-type="OM"]'));
            
            let targetContainer = null;
            let isFallback = false;

            const getQuestionData = (container) => {
                const qEl = container.querySelector('.question, .pregunta');
                if (qEl) {
                    const clone = qEl.cloneNode(true);
                    return {
                        text: (clone.innerText || "").replace(/\s+/g, " ").trim(),
                        html: qEl.outerHTML
                    };
                }
                const pEl = container.querySelector('p, h2, h3, h4');
                const source = pEl || container;
                return {
                    text: (source.innerText || "").replace(/\s+/g, " ").trim(),
                    html: source.outerHTML
                };
            };
            
            if (containers.length > 0) {
                for (const container of containers) {
                    // Check if this container has radio/checkbox inputs, and if any is checked
                    const inputs = Array.from(container.querySelectorAll('input[type="radio"], input[type="checkbox"]'));
                    if (inputs.length > 0) {
                        const hasChecked = inputs.some(input => input.checked);
                        if (!hasChecked) {
                            const qData = getQuestionData(container);
                            if (skipQuestions.has(qData.text)) continue;
                            targetContainer = container;
                            break;
                        }
                    } else {
                        // Check for text inputs or textareas
                        const textInputs = Array.from(container.querySelectorAll('input[type="text"], textarea'));
                        if (textInputs.length > 0) {
                            const hasFilled = textInputs.some(input => input.value.trim() !== "");
                            if (!hasFilled) {
                                const qData = getQuestionData(container);
                                if (skipQuestions.has(qData.text)) continue;
                                targetContainer = container;
                                break;
                            }
                        }
                    }
                }
            }
            
            // If all containers are answered
            if (!targetContainer && containers.length > 0) {
                return null;
            }
            
            // Fallback: look for general question elements
            if (!targetContainer) {
                const questionEl = document.querySelector('.question, .pregunta, h1, h2, h3');
                if (questionEl) {
                    const questionText = (questionEl.innerText || "").replace(/\s+/g, " ").trim();
                    if (skipQuestions.has(questionText)) return null;
                    targetContainer = document.body;
                    isFallback = true;
                } else {
                    return null;
                }
            }
            
            // Extract question text and html
            let questionText = "";
            let questionHtml = "";
            if (isFallback) {
                const qEl = document.querySelector('.question, .pregunta');
                questionText = qEl ? qEl.innerText : document.body.innerText;
                questionHtml = qEl ? qEl.outerHTML : document.body.innerHTML;
            } else {
                const qData = getQuestionData(targetContainer);
                questionText = qData.text;
                questionHtml = qData.html;
            }
            questionText = questionText.trim();
            
            // Clean up question text (remove image alt text or extra whitespace)
            questionText = questionText.replace(/\\s+/g, ' ');
            
            const options = [];
            const optionsHtml = [];
            const selectors = [];
            const optionSelectors = [];
            
            // Find all input radio/checkbox elements in the target container
            const optionInputs = Array.from(targetContainer.querySelectorAll('input[type="radio"], input[type="checkbox"]'));
            
            // Helper function to generate unique CSS selector for an element
            const getUniqueSelector = (el) => {
                if (el.id) {
                    return `#${el.id}`;
                }
                if (el.getAttribute('data-op')) {
                    return `input[data-op="${el.getAttribute('data-op').replace(/"/g, '\\"')}"]`;
                }
                if (el.name && el.value) {
                    return `input[name="${el.name.replace(/"/g, '\\"')}"][value="${el.value.replace(/"/g, '\\"')}"]`;
                }
                // Fallback to absolute/nth-child path
                const path = [];
                let curr = el;
                while (curr && curr.nodeType === Node.ELEMENT_NODE) {
                    let selector = curr.nodeName.toLowerCase();
                    if (curr.parentNode) {
                        const siblings = Array.from(curr.parentNode.children);
                        const index = siblings.indexOf(curr) + 1;
                        selector += `:nth-child(${index})`;
                    }
                    path.unshift(selector);
                    curr = curr.parentNode;
                }
                return path.join(' > ');
            };

            const questionSelector = (() => {
                if (isFallback) {
                    return getUniqueSelector(document.querySelector('.question, .pregunta') || document.body);
                }
                const qEl = targetContainer.querySelector('.question, .pregunta, p, h2, h3, h4');
                return getUniqueSelector(qEl || targetContainer);
            })();
            
            for (const input of optionInputs) {
                let labelText = "";
                let labelHtml = "";
                let optionElement = null;
                let parent = input.parentElement;
                while (parent && parent !== targetContainer) {
                    if (parent.tagName === 'LABEL') {
                        labelText = parent.innerText;
                        labelHtml = parent.outerHTML;
                        optionElement = parent;
                        break;
                    }
                    parent = parent.parentElement;
                }
                
                if (!labelText && input.id) {
                    const label = document.querySelector(`label[for="${input.id}"]`);
                    if (label) {
                        labelText = label.innerText;
                        labelHtml = label.outerHTML;
                        optionElement = label;
                    }
                }
                
                if (!labelText) {
                    labelText = input.parentElement ? input.parentElement.innerText : "";
                    labelHtml = input.parentElement ? input.parentElement.outerHTML : "";
                    optionElement = input.parentElement || input;
                }
                
                labelText = labelText.trim();
                options.push(labelText);
                optionsHtml.push(labelHtml);
                selectors.push(getUniqueSelector(input));
                optionSelectors.push(getUniqueSelector(optionElement || input));
            }
            
            const mediaSelectors = [];
            const mediaElementsData = [];
            if (targetContainer) {
                const mediaElements = Array.from(targetContainer.querySelectorAll('img, svg, canvas, table, iframe'));
                for (const media of mediaElements) {
                    const sel = getUniqueSelector(media);
                    mediaSelectors.push(sel);
                    mediaElementsData.push({
                        selector: sel,
                        tagName: media.tagName.toLowerCase(),
                        src: media.getAttribute('src') || media.src || "",
                        width: media.clientWidth || media.width || 0,
                        height: media.clientHeight || media.height || 0
                    });
                }
            }
            
            return {
                question: questionText,
                question_html: questionHtml,
                question_selector: questionSelector,
                options: options,
                options_html: optionsHtml,
                selectors: selectors,
                option_selectors: optionSelectors,
                media_selectors: mediaSelectors,
                media_elements: mediaElementsData
            };
        }
        """
        try:
            return self.page.evaluate(js_extractor, list(skip_questions or []))
        except Exception as e:
            print(f"[BROWSER ERROR] Failed to evaluate page: {e}")
            return None

    def click_option(self, selector: str) -> None:
        """Click the element matching the selector."""
        if not self.page:
            raise RuntimeError("Browser not initialized.")
        self.page.click(selector)

    def fill_text(self, selector: str, text: str) -> None:
        """Fill input field with text."""
        if not self.page:
            raise RuntimeError("Browser not initialized.")
        self.page.fill(selector, text)

    def next_page(self, selector: str, timeout_ms: int = 30000) -> bool:
        """Click the next/submit button and return True if successful."""
        if not self.page:
            return False
        try:
            # Scroll to make sure it's visible/clickable
            self.page.locator(selector).scroll_into_view_if_needed()
            self.page.click(selector, timeout=timeout_ms)
            # Wait for either load state or longer timeout
            self.page.wait_for_load_state("load", timeout=timeout_ms)
            time.sleep(1.0)
            return True
        except Exception as e:
            print(f"[BROWSER WARNING] Click next page failed: {e}")
            return False

    def screenshot_element(self, selector: str, output_path: str | Path) -> bool:
        """Capture a screenshot of a specific element and save to output_path."""
        if not self.page:
            return False
        try:
            loc = self.page.locator(selector)
            if loc.count() > 0:
                loc.first.screenshot(path=str(output_path))
                return True
            return False
        except Exception as e:
            print(f"[BROWSER WARNING] Failed to screenshot element {selector}: {e}")
            return False

    def close(self) -> None:
        """Close page, context, browser, and stop Playwright."""
        try:
            if self.page:
                self.page.close()
                self.page = None
            if self._context:
                self._context.close()
                self._context = None
            if self._browser:
                self._browser.close()
                self._browser = None
            if self._playwright:
                self._playwright.stop()
                self._playwright = None
        except Exception as e:
            print(f"[BROWSER ERROR] Error closing browser: {e}")
