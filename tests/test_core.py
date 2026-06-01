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


if __name__ == "__main__":
    unittest.main()
