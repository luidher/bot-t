from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest import mock
from core.parser import ParsedQuestion

try:
    from core.page_manager import PageManager
except ModuleNotFoundError as exc:
    if exc.name != "pyautogui":
        raise
    PageManager = None

try:
    from core.browser import BotBrowser
except ModuleNotFoundError as exc:
    if exc.name != "playwright":
        raise
    BotBrowser = None


@unittest.skipIf(BotBrowser is None, "playwright is not installed")
class PlaywrightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.example_html_path = Path(__file__).parent.parent / "docs" / "example.html"
        self.browser = None

    def tearDown(self) -> None:
        if self.browser:
            self.browser.close()

    @unittest.skipIf(shutil.which("node") is None, "playwright runtime is not available")
    def test_dom_parsing_example_html(self) -> None:
        # Skip if example.html doesn't exist
        if not self.example_html_path.exists():
            self.skipTest("docs/example.html does not exist")

        self.browser = BotBrowser(headless=True)
        url = self.example_html_path.absolute().as_uri()
        self.browser.open(url, timeout_ms=5000)

        # Read the first unanswered question
        data = self.browser.read_page()
        self.assertIsNotNone(data)
        assert data is not None

        parsed = ParsedQuestion.from_dom(data)

        # Verify question and options
        self.assertEqual(parsed.question, "Juan tiene _____ libros.")
        self.assertEqual(len(parsed.options), 4)
        self.assertEqual(parsed.options[0], "28 libros")
        self.assertEqual(parsed.options[1], "25 libros")
        self.assertEqual(parsed.options[2], "20 libros")
        self.assertEqual(parsed.options[3], "30 libros")

        # Verify selectors
        self.assertEqual(len(parsed.selectors), 4)
        for selector in parsed.selectors:
            self.assertIn("input", selector)

    def test_click_and_answered_detection(self) -> None:
        if not self.example_html_path.exists():
            self.skipTest("docs/example.html does not exist")

        self.browser = BotBrowser(headless=True)
        url = self.example_html_path.absolute().as_uri()
        self.browser.open(url, timeout_ms=5000)

        # First read
        data = self.browser.read_page()
        self.assertIsNotNone(data)
        assert data is not None
        parsed = ParsedQuestion.from_dom(data)
        
        # Click the first option
        self.browser.click_option(parsed.selectors[0])

        # Second read should skip the first question because it's now checked,
        # and instead return the second question ("En el siguiente estanque hay ________ peces.")
        data2 = self.browser.read_page()
        self.assertIsNotNone(data2)
        assert data2 is not None
        parsed2 = ParsedQuestion.from_dom(data2)

        self.assertEqual(parsed2.question, "En el siguiente estanque hay ________ peces.")
        self.assertEqual(parsed2.options[0], "18")
        self.assertEqual(parsed2.options[1], "13")

    def test_connect_to_existing_browser_uses_cdp(self) -> None:
        browser = BotBrowser(headless=True)
        fake_process = mock.Mock()
        fake_process.poll.return_value = None

        fake_playwright = mock.Mock()
        fake_browser = mock.Mock()
        fake_context = mock.Mock()
        fake_page = mock.Mock()
        fake_context.new_page.return_value = fake_page
        fake_browser.new_context.return_value = fake_context
        fake_browser.contexts = []
        fake_playwright.chromium = mock.Mock()
        fake_playwright.chromium.connect_over_cdp.return_value = fake_browser

        fake_playwright_manager = mock.Mock()
        fake_playwright_manager.start.return_value = fake_playwright

        fake_response = mock.MagicMock()
        fake_response.__enter__.return_value = fake_response
        fake_response.status = 200

        with mock.patch("core.browser.shutil.which", return_value="/usr/bin/google-chrome"), \
             mock.patch("core.browser.subprocess.Popen", return_value=fake_process) as popen_mock, \
             mock.patch("core.browser.sync_playwright", return_value=fake_playwright_manager), \
             mock.patch("core.browser.urlopen", return_value=fake_response), \
             mock.patch("core.browser.time.sleep"):
            browser.connect_to_existing_browser(url="https://example.com", timeout_ms=1000)

        self.assertTrue(popen_mock.called)
        fake_playwright.chromium.connect_over_cdp.assert_called_once()
        self.assertEqual(browser.page, fake_page)


@unittest.skipIf(PageManager is None, "pyautogui is not installed")
class PageManagerTests(unittest.TestCase):
    def test_page_manager_tracking(self) -> None:
        pm = PageManager(max_pages=5)
        self.assertEqual(pm.current_page, 1)
        self.assertFalse(pm.is_done())

        pm.record("Question 1", "Answer A")
        self.assertEqual(len(pm.history), 1)
        self.assertEqual(pm.history[0]["page"], 1)

        # Simulate moving next
        pm.current_page += 1
        self.assertEqual(pm.current_page, 2)
        
        pm.record("Question 2", "Answer B")
        self.assertEqual(len(pm.history), 2)
        self.assertEqual(pm.history[1]["page"], 2)


if __name__ == "__main__":
    unittest.main()
