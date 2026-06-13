from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from core.actions import plan_click_for_answer
from core.ai import parse_ai_answer
from core.config import BotConfig, BotConfigUpdate, default_config_dict, merge_config
from core.parser import parse_question
from core.runner import BotRunner


class ParserTests(unittest.TestCase):
    def test_question_starting_with_c_is_not_option(self) -> None:
        parsed = parse_question("Capital de Francia?\nA) Madrid\nB) Paris\nC) Roma")

        self.assertEqual(parsed.question, "Capital de Francia?")
        self.assertEqual(parsed.options, ["Madrid", "Paris", "Roma"])


class AITests(unittest.TestCase):
    def test_parse_json_answer(self) -> None:
        answer = parse_ai_answer(
            '{"answer":"Paris","confidence":0.91,"reason":"capital correcta"}'
        )

        self.assertEqual(answer.answer, "Paris")
        self.assertEqual(answer.confidence, 0.91)
        self.assertEqual(answer.reason, "capital correcta")


class ActionTests(unittest.TestCase):
    def test_plan_click_matches_answer_line(self) -> None:
        boxes = [
            SimpleNamespace(text="A)", left=10, top=10, width=10, height=10),
            SimpleNamespace(text="Madrid", left=25, top=10, width=60, height=10),
            SimpleNamespace(text="B)", left=10, top=40, width=10, height=10),
            SimpleNamespace(text="Paris", left=25, top=40, width=50, height=10),
        ]

        plan = plan_click_for_answer("Paris", boxes)

        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.target_text, "B) Paris")
        self.assertEqual((plan.x, plan.y), (42, 45))


class ConfigTests(unittest.TestCase):
    def test_update_normalizes_host_and_region(self) -> None:
        config = merge_config(
            default_config_dict(),
            BotConfigUpdate(ollama_host="localhost:11434", region=[10, 20, 300, 120]),
        )

        self.assertEqual(config["ollama_host"], "http://localhost:11434")
        self.assertEqual(config["region"], [10, 20, 300, 120])

    def test_update_can_clear_region(self) -> None:
        current = BotConfig(region=[10, 20, 300, 120]).model_dump(mode="json")

        config = merge_config(current, BotConfigUpdate(region=None))

        self.assertIsNone(config["region"])

    def test_invalid_region_size_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BotConfigUpdate(region=[10, 20, 0, 120])


class RunnerTests(unittest.TestCase):
    def test_update_config_persists_and_emits_event(self) -> None:
        events = []

        with TemporaryDirectory() as tmp:
            runner = BotRunner(
                config_file=Path(tmp) / "web_config.json",
                event_callback=events.append,
            )

            config = runner.update_config(BotConfigUpdate(model="mistral"))

            self.assertEqual(config["model"], "mistral")
            self.assertTrue((Path(tmp) / "web_config.json").exists())
            self.assertEqual(events[-1]["type"], "config")


class PipelineTests(unittest.TestCase):
    def test_has_visual_content_keywords(self) -> None:
        from core.pipeline import has_visual_content
        from core.parser import ParsedQuestion

        # Visual keyword in question
        parsed = ParsedQuestion(question="¿Qué se observa en la tabla siguiente?", options=["Op1", "Op2"], raw_lines=[])
        self.assertTrue(has_visual_content(parsed, is_ocr_mode=True))

        # Visual keyword in option
        parsed = ParsedQuestion(question="Seleccione la opción", options=["La gráfica muestra crecimiento", "Op2"], raw_lines=[])
        self.assertTrue(has_visual_content(parsed, is_ocr_mode=True))

        # No visual keywords
        parsed = ParsedQuestion(question="¿Cuál es la capital de Italia?", options=["Roma", "Milán"], raw_lines=[])
        self.assertFalse(has_visual_content(parsed, is_ocr_mode=True))

    def test_has_visual_content_media_in_dom(self) -> None:
        from core.pipeline import has_visual_content
        from core.parser import ParsedQuestion

        # Media present, DOM mode -> True
        parsed = ParsedQuestion(question="Pregunta", options=["Op1"], raw_lines=[], media=["base64img"])
        self.assertTrue(has_visual_content(parsed, is_ocr_mode=False))


if __name__ == "__main__":
    unittest.main()
