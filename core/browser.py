"""Playwright browser automation module for DOM-based reading and interaction.

This module adds an option to reuse a single Playwright browser process
in-process and create a fresh context/page per `BotBrowser` instance. Reusing
the browser process reduces memory consumption when multiple runner instances
exist within the same Python process.
"""
from __future__ import annotations
from pathlib import Path
import time
from threading import Lock
from typing import Any, Dict, List, Optional
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page


class BotBrowser:
    # Shared (process-wide) Playwright/browser instances and simple refcount
    # to allow multiple BotBrowser instances to create lightweight contexts
    # while sharing the underlying Chromium process.
    _shared_playwright = None
    _shared_browser: Optional[Browser] = None
    _shared_refcount: int = 0
    _shared_lock = Lock()

    def __init__(self, headless: bool = False, use_shared_browser: bool = True, browser_type: str = "chromium") -> None:
        """Create a BotBrowser.

        Args:
            headless: launch browser headless when creating a new browser.
            use_shared_browser: if True, reuse a process-wide browser and
                create a new context/page for this instance. If False, the
                instance manages its own playwright/browser lifecycle.
            browser_type: type of browser to launch ("chromium", "chrome", "firefox", "msedge").
        """
        self.headless = headless
        self.browser_type = browser_type
        if browser_type != "chromium":
            self.use_shared_browser = False
        else:
            self.use_shared_browser = bool(use_shared_browser)
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def open(self, url: str, timeout_ms: int = 120000) -> None:
        """Launch browser and open the target URL."""
        if self.use_shared_browser:
            # Ensure shared playwright/browser exist and increment refcount.
            with BotBrowser._shared_lock:
                if BotBrowser._shared_playwright is None:
                    BotBrowser._shared_playwright = sync_playwright().start()
                if BotBrowser._shared_browser is None:
                    BotBrowser._shared_browser = BotBrowser._shared_playwright.chromium.launch(
                        headless=self.headless
                    )
                BotBrowser._shared_refcount += 1

            # Reference the shared objects
            self._playwright = BotBrowser._shared_playwright
            self._browser = BotBrowser._shared_browser
            # Create an isolated context + page for this instance
            self._context = self._browser.new_context(viewport={"width": 1280, "height": 800})
            self.page = self._context.new_page()

        else:
            if not self._playwright:
                self._playwright = sync_playwright().start()
            if not self._browser:
                if self.browser_type == "firefox":
                    self._browser = self._playwright.firefox.launch(headless=self.headless)
                elif self.browser_type == "chrome":
                    self._browser = self._playwright.chromium.launch(headless=self.headless, channel="chrome")
                elif self.browser_type == "msedge":
                    self._browser = self._playwright.chromium.launch(headless=self.headless, channel="msedge")
                else:
                    self._browser = self._playwright.chromium.launch(headless=self.headless)
                self._context = self._browser.new_context(viewport={"width": 1280, "height": 800})
                self.page = self._context.new_page()

        assert self.page is not None
        self.page.set_default_timeout(timeout_ms)
        self.page.goto(url, timeout=timeout_ms, wait_until="load")
        try:
            self.page.wait_for_load_state("load", timeout=timeout_ms)
        except Exception:
            # best-effort wait
            pass
        time.sleep(1.0)

    def read_page(self, skip_questions: Optional[set[str] | list[str]] = None) -> Optional[Dict[str, Any]]:
        """
        Extract the current unanswered question, options, and their CSS selectors.

        Returns a dict with keys:
          - question: str — texto visible de la pregunta
          - question_html: str
          - question_selector: str
          - question_data_item: str — atributo data-item del <li> contenedor (ID de pregunta en el DOM)
          - options: List[str] — textos visibles de cada opción
          - options_html: List[str]
          - selectors: List[str] — selector único del <input>
          - option_selectors: List[str] — selector del elemento clickable (label o input)
          - data_ops: List[str] — valor data-op de cada input ('' si no tiene)
          - media_selectors: List[str]
          - media_elements: List[dict]

        Returns None if no question is found or all questions on page are answered.
        """
        if not self.page:
            return None

        js_extractor = r"""
        (skipQuestionsArg) => {
            const skipQuestions = new Set((skipQuestionsArg || []).map(q => (q || "").replace(/\s+/g, " ").trim()));

            // ── Selector de contenedores de preguntas ──────────────────────
            const containers = Array.from(document.querySelectorAll(
                'ul.form-items > li[data-type="OM"], ul.form-items > li[data-item], .form-items > li[data-type="OM"]'
            ));

            let targetContainer = null;
            let isFallback = false;

            const getQuestionData = (container) => {
                const qEl = container.querySelector('.question, .pregunta');
                if (qEl) {
                    // Clonar y eliminar la lista de opciones para no incluir su texto
                    const clone = qEl.cloneNode(true);
                    clone.querySelectorAll('.form-list, .options-list, ul').forEach(el => el.remove());
                    return {
                        text: (clone.innerText || "").replace(/\s+/g, " ").trim(),
                        html: qEl.outerHTML
                    };
                }
                const pEl = container.querySelector('p, h2, h3, h4');
                if (pEl) {
                    return {
                        text: (pEl.innerText || "").replace(/\s+/g, " ").trim(),
                        html: pEl.outerHTML
                    };
                }
                // Fallback: container sin opciones
                const clone = container.cloneNode(true);
                clone.querySelectorAll('.form-list, .options-list, ul').forEach(el => el.remove());
                return {
                    text: (clone.innerText || "").replace(/\s+/g, " ").trim(),
                    html: container.outerHTML
                };
            };

            // ── Buscar primer contenedor sin responder ──────────────────────
            if (containers.length > 0) {
                for (const container of containers) {
                    const inputs = Array.from(container.querySelectorAll(
                        'input[type="radio"], input[type="checkbox"]'
                    ));
                    if (inputs.length > 0) {
                        const hasChecked = inputs.some(input => input.checked);
                        if (!hasChecked) {
                            const qData = getQuestionData(container);
                            if (skipQuestions.has(qData.text)) continue;
                            targetContainer = container;
                            break;
                        }
                    } else {
                        const textInputs = Array.from(container.querySelectorAll(
                            'input[type="text"], textarea'
                        ));
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

            // Si todos los contenedores están contestados → null para avanzar hoja
            if (!targetContainer && containers.length > 0) {
                return null;
            }

            // Fallback: buscar elementos de pregunta directamente
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

            // ── Extraer data-item del contenedor (ID de pregunta en el DOM) ──
            const questionDataItem = targetContainer.getAttribute
                ? (targetContainer.getAttribute('data-item') || "")
                : "";

            // ── Texto e HTML de la pregunta ────────────────────────────────
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

            // ── Helper para generar selector único de un elemento ──────────
            const getUniqueSelector = (el) => {
                if (el.id) {
                    return `#${el.id}`;
                }
                if (el.getAttribute && el.getAttribute('data-op')) {
                    const dataOp = el.getAttribute('data-op').replace(/"/g, '\\"');
                    return `input[data-op="${dataOp}"]`;
                }
                if (el.name && el.value) {
                    return `input[name="${el.name.replace(/"/g, '\\"')}"][value="${el.value.replace(/"/g, '\\"')}"]`;
                }
                // Fallback a nth-child path
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
                    return getUniqueSelector(
                        document.querySelector('.question, .pregunta') || document.body
                    );
                }
                const qEl = targetContainer.querySelector('.question, .pregunta, p, h2, h3, h4');
                return getUniqueSelector(qEl || targetContainer);
            })();

            // ── Opciones ───────────────────────────────────────────────────
            const options = [];
            const optionsHtml = [];
            const selectors = [];
            const optionSelectors = [];
            const dataOps = [];

            const optionInputs = Array.from(
                targetContainer.querySelectorAll('input[type="radio"], input[type="checkbox"]')
            );

            for (const input of optionInputs) {
                // Capturar data-op (identificador único de la opción)
                const dataOp = input.getAttribute('data-op') || "";
                dataOps.push(dataOp);

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

            // ── Elementos multimedia ───────────────────────────────────────
            const mediaSelectors = [];
            const mediaElementsData = [];
            if (targetContainer) {
                const mediaElements = Array.from(
                    targetContainer.querySelectorAll('img, svg, canvas, table, iframe')
                );
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
                question_data_item: questionDataItem,
                options: options,
                options_html: optionsHtml,
                selectors: selectors,
                option_selectors: optionSelectors,
                data_ops: dataOps,
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
            self.page.locator(selector).scroll_into_view_if_needed()
            self.page.click(selector, timeout=timeout_ms)
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
        """Close this instance's page/context and shutdown shared browser when
        it is the last user.
        """
        try:
            if self.page:
                try:
                    self.page.close()
                except Exception:
                    pass
                self.page = None

            if self._context:
                try:
                    self._context.close()
                except Exception:
                    pass
                self._context = None

            if self.use_shared_browser:
                # Decrement shared refcount and shutdown shared browser when
                # no more users remain.
                with BotBrowser._shared_lock:
                    if BotBrowser._shared_refcount > 0:
                        BotBrowser._shared_refcount -= 1
                    # If this was the last reference, close shared browser/playwright
                    if BotBrowser._shared_refcount == 0 and BotBrowser._shared_browser:
                        try:
                            BotBrowser._shared_browser.close()
                        except Exception:
                            pass
                        BotBrowser._shared_browser = None
                        try:
                            if BotBrowser._shared_playwright:
                                BotBrowser._shared_playwright.stop()
                        except Exception:
                            pass
                        BotBrowser._shared_playwright = None
            else:
                # Instance-owned browser: close browser + stop playwright
                if self._browser:
                    try:
                        self._browser.close()
                    except Exception:
                        pass
                    self._browser = None
                if self._playwright:
                    try:
                        self._playwright.stop()
                    except Exception:
                        pass
                    self._playwright = None
        except Exception as e:
            print(f"[BROWSER ERROR] Error closing browser: {e}")
