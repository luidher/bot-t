from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from core.actions import plan_click_for_answer
from core.ai import AIAnswer, parse_ai_answer
from core.config import BotConfig, BotConfigUpdate, default_config_dict, merge_config
from core.media_extractor import MediaItem
from core.pipeline import DecisionPipeline
from core.parser import parse_question


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

    def test_legacy_llama3_alias_is_normalized(self) -> None:
        config = merge_config(
            default_config_dict(),
            BotConfigUpdate(model="llama3.1", reason_model="llama3.1"),
        )

        self.assertEqual(config["model"], "deepseek-r1:8b")
        self.assertEqual(config["reason_model"], "deepseek-r1:8b")

    def test_invalid_region_size_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BotConfigUpdate(region=[10, 20, 0, 120])


class PipelineTests(unittest.TestCase):
    def test_dom_mode_uses_qwen_when_media_is_present(self) -> None:
        pipeline = DecisionPipeline(BotConfig(vision_enabled=True))
        captured_context = {}

        def fake_analyze_image(item: MediaItem, question: str, options: list[str], *args, **kwargs) -> dict:
            return {
                "tipo_contenido": "grafico",
                "descripcion_visual": f"media={item.path}",
                "datos_extraidos": {"opciones": len(options)},
            }

        def fake_choose_answer(parsed, context: str = "", *args, **kwargs) -> AIAnswer:
            captured_context["context"] = context
            return AIAnswer("A", 0.88, "usa contexto visual", "{}", 12)

        pipeline.vision_analyzer.analyze_image = fake_analyze_image
        pipeline.ai_client.choose_answer = fake_choose_answer

        answer, qwen_activated, descriptions = pipeline.run(
            question="Que muestra la imagen?",
            options=["A", "B"],
            media_items=[MediaItem(path="chart.png", role="question", selector="#chart")],
            is_dom_mode=True,
        )

        self.assertEqual(answer.answer, "A")
        self.assertTrue(qwen_activated)
        self.assertIsNotNone(descriptions)
        self.assertIn("chart.png", captured_context["context"])

    def test_visual_context_is_plain_text_ordered_by_media_role(self) -> None:
        pipeline = DecisionPipeline(BotConfig(vision_enabled=True))
        captured_context = {}

        def fake_analyze_image(item: MediaItem, question: str, options: list[str], *args, **kwargs) -> dict:
            return {
                "tipo_contenido": "otro",
                "descripcion_visual": f"descripcion de {item.role} {item.option_label or ''}".strip(),
                "datos_extraidos": {"valor": item.option_label or "pregunta"},
            }

        def fake_choose_answer(parsed, context: str = "", *args, **kwargs) -> AIAnswer:
            captured_context["context"] = context
            return AIAnswer("B", 0.9, "usa contexto visual", "{}", 9)

        pipeline.vision_analyzer.analyze_image = fake_analyze_image
        pipeline.ai_client.choose_answer = fake_choose_answer

        pipeline.run(
            question="Observa la imagen y elige.",
            options=["A", "B"],
            media_items=[
                MediaItem(path="question.png", role="question", selector="#question-img"),
                MediaItem(path="option_b.png", role="option", option_index=1, option_label="B", selector="#option-b-img"),
            ],
            is_dom_mode=True,
        )

        self.assertIn("[Enunciado]:", captured_context["context"])
        self.assertIn("[Opción B]:", captured_context["context"])
        self.assertNotIn('"descripcion_visual"', captured_context["context"])

    def test_ocr_mode_skips_qwen_without_visual_signal(self) -> None:
        pipeline = DecisionPipeline(BotConfig(vision_enabled=True))

        def fail_analyze_image(item: MediaItem, question: str, options: list[str], *args, **kwargs) -> dict:
            raise AssertionError("Qwen should not be called")

        pipeline.vision_analyzer.analyze_image = fail_analyze_image
        pipeline.ai_client.choose_answer = lambda parsed, context="", *args, **kwargs: AIAnswer("Paris", 0.9, "texto simple", "{}", 4)

        answer, qwen_activated, descriptions = pipeline.run(
            question="Capital de Francia?",
            options=["Madrid", "Paris"],
            media_items=[],
            is_dom_mode=False,
        )

        self.assertEqual(answer.answer, "Paris")
        self.assertFalse(qwen_activated)
        self.assertIsNone(descriptions)

    def test_ocr_mode_uses_qwen_for_unaccented_visual_keywords(self) -> None:
        pipeline = DecisionPipeline(BotConfig(vision_enabled=True))
        pipeline.vision_analyzer.analyze_image = lambda path, question, options, *args, **kwargs: {
            "tipo_contenido": "grafico",
            "descripcion_visual": "grafica detectada",
            "datos_extraidos": {},
        }
        pipeline.ai_client.choose_answer = lambda parsed, context="", *args, **kwargs: AIAnswer("B", 0.82, context, "{}", 5)

        _answer, qwen_activated, descriptions = pipeline.run(
            question="Segun la grafica, cual opcion es correcta?",
            options=["A", "B"],
            media_items=[MediaItem(path="capture.png", role="question", selector="screen_capture")],
            is_dom_mode=False,
        )

        self.assertTrue(qwen_activated)
        self.assertIsNotNone(descriptions)

    def test_dom_sufficiency_skips_qwen(self) -> None:
        pipeline = DecisionPipeline(BotConfig(vision_enabled=True))
        
        def fail_analyze_image(*args, **kwargs) -> dict:
            raise AssertionError("Qwen should not be called when DOM is sufficient")
            
        pipeline.vision_analyzer.analyze_image = fail_analyze_image
        pipeline.ai_client.choose_answer = lambda parsed, context="", *args, **kwargs: AIAnswer("Yes", 0.95, "DOM is sufficient", "{}", 8)
        
        # media_items is empty and is_dom_mode=True, meaning DOM is sufficient.
        answer, qwen_activated, descriptions = pipeline.run(
            question="Is this a simple text question?",
            options=["Yes", "No"],
            media_items=[],
            is_dom_mode=True,
        )
        self.assertEqual(answer.answer, "Yes")
        self.assertFalse(qwen_activated)
        self.assertIsNone(descriptions)


class ConsoleTests(unittest.TestCase):
    def test_parse_args_derives_vision_enabled(self) -> None:
        try:
            import main as cli_main
        except ModuleNotFoundError as exc:
            if exc.name == "pyautogui":
                self.skipTest("pyautogui is not installed")
            raise

        with patch("sys.argv", ["main.py", "--no-vision"]):
            args = cli_main.parse_args()

        self.assertFalse(args.vision_enabled)


class RunnerTests(unittest.TestCase):
    def test_update_config_persists_and_emits_event(self) -> None:
        try:
            from core.runner import BotRunner
        except ModuleNotFoundError as exc:
            if exc.name == "playwright":
                self.skipTest("playwright is not installed")
            raise

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
