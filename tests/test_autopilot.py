from __future__ import annotations

import unittest
from pathlib import Path
import tempfile
import shutil
import sqlite3
import random
from unittest.mock import MagicMock

from core.db_manager import DBManager
from core.autopilot_runner import (
    AutopilotRunner,
    _classify_feedback_front,
    _classify_feedback_front_text,
    _similarity,
)

try:
    from core.browser import BotBrowser
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False


class TestDBManager(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_autopilot.db"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_db_initialization(self) -> None:
        db = DBManager(self.db_path)
        self.assertTrue(self.db_path.exists())
        
        # Verify connection and WAL mode
        conn = db._connect()
        cur = conn.execute("PRAGMA journal_mode")
        mode = cur.fetchone()[0]
        self.assertEqual(mode.lower(), "wal")
        db.close()

    def test_hashing_normalization(self) -> None:
        h1 = DBManager.calcular_hash("  ¿Qué hora   es?  ")
        h2 = DBManager.calcular_hash("¿qué hora es?")
        self.assertEqual(h1, h2)

    def test_save_and_query_immediate(self) -> None:
        db = DBManager(self.db_path)
        q_text = "Pregunta de prueba"
        h = DBManager.calcular_hash(q_text)
        
        db.guardar_en_db(h, q_text, "Opción A", inmediato=True)
        
        ans = db.consultar_db(h)
        self.assertIsNotNone(ans)
        assert ans is not None
        self.assertEqual(ans["texto"], "Opción A")
        self.assertEqual(db.contar_registros(), 1)
        db.close()

    def test_buffer_flush(self) -> None:
        db = DBManager(self.db_path)
        q_text = "Pregunta buffered"
        h = DBManager.calcular_hash(q_text)
        
        # Save without immediate flush
        db.guardar_en_db(h, q_text, "Opción B", inmediato=False)
        
        # Should not be in DB yet since buffer is small (BUFFER_SIZE=100)
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute("SELECT COUNT(*) FROM respuestas")
        self.assertEqual(cur.fetchone()[0], 0)
        conn.close()
        
        # Flush buffer
        db.flush_buffer()
        
        # Now should be there
        ans = db.consultar_db(h)
        self.assertIsNotNone(ans)
        assert ans is not None
        self.assertEqual(ans["texto"], "Opción B")
        self.assertEqual(db.contar_registros(), 1)
        db.close()

    def test_obtener_ultimos(self) -> None:
        db = DBManager(self.db_path)
        for i in range(5):
            db.guardar_en_db(f"hash_{i}", f"Pregunta {i}", f"Opción {i}", inmediato=True)
            
        ultimos = db.obtener_ultimos(3)
        self.assertEqual(len(ultimos), 3)
        # Should be most recent first
        self.assertEqual(ultimos[0]["pregunta"], "Pregunta 4")
        self.assertEqual(ultimos[0]["opcion"], "Opción 4")
        db.close()


class TestAutopilotRunnerHelpers(unittest.TestCase):
    def test_similarity(self) -> None:
        self.assertEqual(_similarity("la capital de francia", "Francia Capital de la"), 1.0)
        self.assertEqual(_similarity("capital de francia", "capital de españa"), 0.5)
        self.assertEqual(_similarity("", "algo"), 0.0)

    def test_classify_server_front_feedback(self) -> None:
        payload = {
            "success": True,
            "front": [
                {
                    "tipo": "OM",
                    "id_item": "V3Hqvu8AUVimMgLnTPv8yB0nGSXL5tq0yjpvdYbRLr8=",
                    "class": "success",
                },
                {
                    "tipo": "OM",
                    "id_item": "05wNHxSLFM8A13WCn0GV4PLGYfPKFqbxVWGx/bI19MM=",
                    "class": "wrong",
                },
            ],
        }

        self.assertEqual(
            _classify_feedback_front(payload, "V3Hqvu8AUVimMgLnTPv8yB0nGSXL5tq0yjpvdYbRLr8="),
            "correct",
        )
        self.assertEqual(
            _classify_feedback_front(payload, "05wNHxSLFM8A13WCn0GV4PLGYfPKFqbxVWGx/bI19MM="),
            "incorrect",
        )
        self.assertEqual(_classify_feedback_front(payload, "no-existe"), "unknown")

    def test_classify_server_front_feedback_from_text(self) -> None:
        text = """
        front:
        [{tipo: "OM", id_item: "V3Hqvu8AUVimMgLnTPv8yB0nGSXL5tq0yjpvdYbRLr8=", class: "success"},
        {tipo: "OM", id_item: "05wNHxSLFM8A13WCn0GV4PLGYfPKFqbxVWGx/bI19MM=", class: "wrong"}]
        """

        self.assertEqual(
            _classify_feedback_front_text(text, "V3Hqvu8AUVimMgLnTPv8yB0nGSXL5tq0yjpvdYbRLr8="),
            "correct",
        )
        self.assertEqual(
            _classify_feedback_front_text(text, "05wNHxSLFM8A13WCn0GV4PLGYfPKFqbxVWGx/bI19MM="),
            "incorrect",
        )

    def test_classify_submit_payloads_prefers_registrar_unidad_front_feedback(self) -> None:
        runner = AutopilotRunner(
            "http://test.com",
            bot_config={},
            keep_browser_open=False,
            browser=MagicMock(),
            log_callback=lambda msg, level: None,
        )
        try:
            runner._last_submit_payloads = [
                {
                    "content_type": "application/json",
                    "text": '{"success": true, "front": [{"id_item": "target-item", "class": "wrong"}]}',
                    "priority": 0,
                    "index": 2,
                },
                {
                    "content_type": "application/json",
                    "text": '{"success": true, "front": [{"id_item": "target-item", "class": "success"}]}',
                    "priority": 100,
                    "index": 1,
                },
            ]

            self.assertEqual(runner._classify_from_submit_payloads("target-item"), "correct")
        finally:
            runner.db.close()


class TestAutopilotRunnerMockFlows(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_autopilot.db"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_runner_flow_with_db(self) -> None:
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_browser.page = mock_page
        
        runner = AutopilotRunner("http://test.com", bot_config={}, keep_browser_open=False)
        runner.browser = mock_browser
        runner.db = DBManager(self.db_path)
        
        mock_question = {
            "question": "Cuál es la capital de España?",
            "options": [
                {"texto": "Madrid", "selector": "#opt1"},
                {"texto": "Barcelona", "selector": "#opt2"}
            ]
        }
        
        call_count = 0
        def mock_extract():
            nonlocal call_count
            if call_count == 0:
                call_count += 1
                return [mock_question]
            return None
            
        runner.extraer_preguntas_y_opciones = mock_extract
        runner._extraer_todas_las_preguntas = mock_extract
        
        h = DBManager.calcular_hash("Cuál es la capital de España?")
        runner.db.guardar_en_db(h, "Cuál es la capital de España?", "Madrid", inmediato=True)
        
        runner.hacer_clic_en_opcion = MagicMock(return_value=True)
        runner._hacer_clic_en_opcion = runner.hacer_clic_en_opcion
        runner._presionar_calificar = MagicMock(return_value=True)
        runner._validar_pregunta = MagicMock(return_value="correct")
        runner.ir_a_siguiente_hoja = MagicMock(return_value=False)
        
        runner.run()
        
        self.assertEqual(runner.stats["respondidas_desde_db"], 1)
        self.assertEqual(runner.stats["respondidas_al_azar"], 0)
        runner._hacer_clic_en_opcion.assert_called_once_with("#opt1", None)
        
        runner.db.close()

    def test_runner_flow_random_guess(self) -> None:
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_browser.page = mock_page
        
        runner = AutopilotRunner("http://test.com", bot_config={}, keep_browser_open=False)
        runner.browser = mock_browser
        runner.db = DBManager(self.db_path)
        
        mock_question = {
            "question": "Cuál es la capital de Italia?",
            "options": [
                {"texto": "Milán", "selector": "#opt1"},
                {"texto": "Roma", "selector": "#opt2"}
            ]
        }
        
        call_count = 0
        def mock_extract():
            nonlocal call_count
            if call_count == 0:
                call_count += 1
                return [mock_question]
            return None
            
        runner.extraer_preguntas_y_opciones = mock_extract
        runner._extraer_todas_las_preguntas = MagicMock(return_value=[mock_question])
        runner.hacer_clic_en_opcion = MagicMock(return_value=True)
        runner._hacer_clic_en_opcion = runner.hacer_clic_en_opcion
        runner._presionar_calificar = MagicMock(return_value=True)
        runner.recargar_hoja_actual = MagicMock(return_value=True)
        runner._presionar_reintentar = runner.recargar_hoja_actual
        runner.ir_a_siguiente_hoja = MagicMock(return_value=False)
        
        original_choice = random.choice
        choices = []
        def mock_choice(seq):
            milan = next((o for o in seq if o["texto"] == "Milán"), None)
            roma = next((o for o in seq if o["texto"] == "Roma"), None)
            if milan and milan["texto"] not in choices:
                choices.append("Milán")
                return milan
            if roma:
                choices.append("Roma")
                return roma
            return original_choice(seq)
            
        random.choice = mock_choice
        
        def mock_validate(selector):
            if selector == "#opt1":
                return "incorrect"
            if selector == "#opt2":
                return "correct"
            return "unknown"
            
        runner.validar_acierto = mock_validate
        runner._validar_pregunta = lambda data_item, opcion=None: mock_validate((opcion or {}).get("selector", ""))
        
        try:
            runner.run()
        finally:
            random.choice = original_choice
            
        self.assertEqual(runner.stats["respondidas_desde_db"], 1)
        self.assertEqual(runner.stats["respondidas_al_azar"], 1)
        self.assertEqual(runner.stats["nuevas_guardadas"], 1)
        
        h = DBManager.calcular_hash("Cuál es la capital de Italia?")
        ans = runner.db.consultar_db(h)
        self.assertIsNotNone(ans)
        assert ans is not None
        self.assertEqual(ans["texto"], "Roma")
        
        runner.db.close()

    def test_db_answer_discarded_after_server_wrong_is_not_reused(self) -> None:
        runner = AutopilotRunner("http://test.com", bot_config={}, keep_browser_open=False, browser=MagicMock())
        runner.db.close()
        runner.db = DBManager(self.db_path)

        question = "Capital de prueba?"
        hash_p = DBManager.calcular_hash(question)
        runner.db.guardar_en_db(
            hash_p,
            question,
            "Respuesta vieja",
            selector_correcto="old-op",
            inmediato=True,
        )

        chosen = runner._elegir_opcion_para_pregunta(
            {
                "question": question,
                "options": [
                    {"texto": "Respuesta vieja", "selector": "#old", "data_op": "old-op"},
                    {"texto": "Respuesta nueva", "selector": "#new", "data_op": "new-op"},
                ],
            },
            {hash_p: {"ops": {"old-op"}, "txt": {"Respuesta vieja"}}},
        )

        self.assertIsNotNone(chosen)
        assert chosen is not None
        self.assertEqual(chosen["texto"], "Respuesta nueva")
        runner.db.close()

    def test_runner_does_not_resave_correct_db_answer(self) -> None:
        mock_browser = MagicMock()
        mock_page = MagicMock()
        mock_browser.page = mock_page
        
        runner = AutopilotRunner("http://test.com", bot_config={}, keep_browser_open=False)
        runner.browser = mock_browser
        runner.db = DBManager(self.db_path)
        
        mock_question = {
            "question": "Cuál es la capital de España?",
            "options": [
                {"texto": "Madrid", "selector": "#opt1"},
                {"texto": "Barcelona", "selector": "#opt2"}
            ]
        }
        
        call_count = 0
        def mock_extract():
            nonlocal call_count
            if call_count == 0:
                call_count += 1
                return [mock_question]
            return None
            
        runner.extraer_preguntas_y_opciones = mock_extract
        runner._extraer_todas_las_preguntas = mock_extract
        
        h = DBManager.calcular_hash("Cuál es la capital de España?")
        runner.db.guardar_en_db(h, "Cuál es la capital de España?", "Madrid", inmediato=True)
        
        # Guardar espía del método guardar_en_db
        runner.db.guardar_en_db = MagicMock(side_effect=runner.db.guardar_en_db)
        
        runner.hacer_clic_en_opcion = MagicMock(return_value=True)
        runner._hacer_clic_en_opcion = runner.hacer_clic_en_opcion
        runner._presionar_calificar = MagicMock(return_value=True)
        runner._validar_pregunta = MagicMock(return_value="correct")
        runner.ir_a_siguiente_hoja = MagicMock(return_value=False)
        
        runner.run()
        
        # Verificar que no se llamó a guardar_en_db durante el flujo
        runner.db.guardar_en_db.assert_not_called()
        self.assertEqual(runner.stats["nuevas_guardadas"], 0)
        self.assertEqual(runner.stats["respondidas_desde_db"], 1)
        
        runner.db.close()

    def test_runner_retries_only_pending_before_next_sheet(self) -> None:
        mock_browser = MagicMock()
        mock_browser.page = MagicMock()

        runner = AutopilotRunner("http://test.com", bot_config={}, keep_browser_open=False, browser=mock_browser)
        runner.db.close()
        runner.db = DBManager(self.db_path)
        runner.timings.update({
            "dom_stable_wait_ms": 0,
            "feedback_wait_ms": 0,
            "after_click_wait_ms": 0,
            "after_submit_wait_ms": 0,
            "reload_wait_ms": 0,
            "next_wait_ms": 0,
        })
        runner.limits["max_sheets"] = 1
        runner.limits["max_rondas_por_hoja"] = 3

        q1 = {
            "question": "Pregunta 1",
            "data_item": "id-q1",
            "answered": False,
            "options": [
                {"texto": "Correcta 1", "selector": "#q1a", "data_op": "q1a"},
                {"texto": "Incorrecta 1", "selector": "#q1b", "data_op": "q1b"},
            ],
        }
        q2 = {
            "question": "Pregunta 2",
            "data_item": "id-q2",
            "answered": False,
            "options": [
                {"texto": "Incorrecta 2", "selector": "#q2a", "data_op": "q2a"},
                {"texto": "Correcta 2", "selector": "#q2b", "data_op": "q2b"},
            ],
        }

        runner._extraer_todas_las_preguntas = MagicMock(return_value=[q1, q2])
        runner._hacer_clic_en_opcion = MagicMock(return_value=True)
        runner._presionar_calificar = MagicMock(return_value=True)
        runner._presionar_reintentar = MagicMock(return_value=True)
        runner.ir_a_siguiente_hoja = MagicMock(return_value=False)

        def mock_validate(data_item: str, opcion: dict | None = None) -> str:
            data_op = (opcion or {}).get("data_op", "")
            if data_item == "id-q1" and data_op == "q1a":
                return "correct"
            if data_item == "id-q2" and data_op == "q2b":
                return "correct"
            return "incorrect"

        runner._validar_pregunta = mock_validate

        original_choice = random.choice

        def mock_choice(seq):
            by_text = {item["texto"]: item for item in seq}
            if "Correcta 1" in by_text:
                return by_text["Correcta 1"]
            if "Incorrecta 2" in by_text:
                return by_text["Incorrecta 2"]
            if "Correcta 2" in by_text:
                return by_text["Correcta 2"]
            return original_choice(seq)

        random.choice = mock_choice
        try:
            runner.run()
        finally:
            random.choice = original_choice

        clicked_selectors = [call.args[0] for call in runner._hacer_clic_en_opcion.call_args_list]
        self.assertEqual(clicked_selectors, ["#q1a", "#q2a", "#q1a", "#q2b"])
        runner._presionar_reintentar.assert_called_once()
        runner.ir_a_siguiente_hoja.assert_called_once()

        q1_hash = DBManager.calcular_hash("Pregunta 1")
        q2_hash = DBManager.calcular_hash("Pregunta 2")
        self.assertEqual(runner.db.consultar_db(q1_hash)["texto"], "Correcta 1")
        self.assertEqual(runner.db.consultar_db(q2_hash)["texto"], "Correcta 2")

        runner.db.close()


@unittest.skipIf(not _HAS_PLAYWRIGHT, "Playwright/BotBrowser is not installed")
class TestAutopilotRunnerDOM(unittest.TestCase):
    def setUp(self) -> None:
        self.example_html_path = Path(__file__).parent.parent / "docs" / "example.html"
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_autopilot.db"
        self.browser = None

    def tearDown(self) -> None:
        if self.browser:
            self.browser.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extract_questions_and_options(self) -> None:
        if not self.example_html_path.exists():
            self.skipTest("docs/example.html does not exist")

        self.browser = BotBrowser(headless=True)
        url = self.example_html_path.absolute().as_uri()
        self.browser.open(url, timeout_ms=5000)

        runner = AutopilotRunner(url, bot_config={}, keep_browser_open=False)
        runner.browser = self.browser
        runner.db = DBManager(self.db_path)

        data = runner.extraer_preguntas_y_opciones()
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(len(data), 1)
        
        q_obj = data[0]
        self.assertEqual(q_obj["question"], "Juan tiene _____ libros.")
        self.assertEqual(len(q_obj["options"]), 4)
        self.assertEqual(q_obj["options"][0]["texto"], "28 libros")
        self.assertTrue(q_obj["options"][0]["selector"].startswith("#") or "input" in q_obj["options"][0]["selector"])
        
        runner.db.close()

    def test_skipped_questions(self) -> None:
        if not self.example_html_path.exists():
            self.skipTest("docs/example.html does not exist")

        self.browser = BotBrowser(headless=True)
        url = self.example_html_path.absolute().as_uri()
        self.browser.open(url, timeout_ms=5000)

        runner = AutopilotRunner(url, bot_config={}, keep_browser_open=False)
        runner.browser = self.browser
        runner.db = DBManager(self.db_path)

        runner.failed_questions_in_sheet.add("Juan tiene _____ libros.")
        
        data = runner.extraer_preguntas_y_opciones()
        self.assertIsNotNone(data)
        assert data is not None
        self.assertEqual(data[0]["question"], "En el siguiente estanque hay ________ peces.")
        
        runner.db.close()


class TestAutopilotMathImageCrystals(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_autopilot.db"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_math_formula_normalization(self) -> None:
        # Test _normalize_feedback_text
        from core.autopilot_runner import (
            _normalize_feedback_text,
            _math_normalized_equals,
            _math_normalized_contains,
        )
        self.assertEqual(_normalize_feedback_text("13x−7y"), "13x-7y")
        self.assertEqual(_normalize_feedback_text("9x²"), "9x2")
        self.assertEqual(_normalize_feedback_text("a × b • c"), "a * b * c")

        # Test _math_normalized_equals
        self.assertTrue(_math_normalized_equals("\\frac{13x-7y}{9x^2-4y^2}", "13x-7y / 9x^2-4y^2"))
        self.assertTrue(_math_normalized_equals("x_1^2", "x12"))
        
        # Test _math_normalized_contains
        self.assertTrue(_math_normalized_contains("la respuesta es \\sqrt{25}", "sqrt(25)"))

    def test_extract_todas_las_preguntas_mathjax(self) -> None:
        # Test that _extraer_todas_las_preguntas processes MathJax HTML and preserves image tags
        runner = AutopilotRunner("http://test.com", bot_config={}, keep_browser_open=False)
        runner.db = DBManager(self.db_path)
        runner.browser = MagicMock()
        
        mock_eval_result = [
            {
                "question": "Resolver la ecuación [img: formula.png]",
                "question_html": "<div>Resolver la ecuación <math><mfrac><mi>x</mi><mn>2</mn></mfrac></math></div>",
                "options": [
                    {
                        "texto": "Opción 1 [img: opt.png]",
                        "html": "<label><math><msup><mi>x</mi><mn>2</mn></msup></math></label>",
                        "selector": "#opt1",
                    }
                ]
            }
        ]
        runner.browser.page.evaluate = MagicMock(return_value=mock_eval_result)
        
        res = runner._extraer_todas_las_preguntas()
        self.assertIsNotNone(res)
        self.assertEqual(res[0]["question"], "Resolver la ecuación x/2 [img: formula.png]")
        self.assertEqual(res[0]["options"][0]["texto"], "x^2 [img: opt.png]")
        
        runner.db.close()

    def test_image_extraction_unique_filenames(self) -> None:
        # Test that _extraer_todas_las_preguntas processes and keeps unique filenames mock results
        runner = AutopilotRunner("http://test.com", bot_config={}, keep_browser_open=False)
        runner.db = DBManager(self.db_path)
        runner.browser = MagicMock()
        
        mock_eval_result = [
            {
                "question": "¿Cuál de las figuras está hecha con el siguiente tangram? [img: BP3.png]",
                "question_html": "<div>¿Cuál de las figuras está hecha con el siguiente tangram? <img src=\"https://cdn.pruebat.org/.../BP3.png\" alt=\"Pregunta\"></div>",
                "options": [
                    {
                        "texto": "[img: P3O3.png]",
                        "html": "<label><img src=\"https://cdn.pruebat.org/.../P3O3.png\"></label>",
                        "selector": "#opt1",
                    }
                ]
            }
        ]
        runner.browser.page.evaluate = MagicMock(return_value=mock_eval_result)
        
        res = runner._extraer_todas_las_preguntas()
        self.assertIsNotNone(res)
        self.assertEqual(res[0]["question"], "¿Cuál de las figuras está hecha con el siguiente tangram? [img: BP3.png]")
        self.assertEqual(res[0]["options"][0]["texto"], "[img: P3O3.png]")
        
        runner.db.close()

    def test_crystals_detection_payloads(self) -> None:
        runner = AutopilotRunner("http://test.com", bot_config={}, keep_browser_open=False)
        runner.db = DBManager(self.db_path)
        
        # Test finding in structured payload
        runner._last_submit_payloads = [
            {
                "text": '{"response": {"resultados": {"cristales": 2, "porcentaje": 66}}, "success": true}',
                "content_type": "application/json"
            }
        ]
        self.assertEqual(runner._check_cristales_in_payloads(), 2)

        # Test recursive find
        runner._last_submit_payloads = [
            {
                "text": '{"nested": {"foo": {"cristales": 3}}}',
                "content_type": "application/json"
            }
        ]
        self.assertEqual(runner._check_cristales_in_payloads(), 3)
        
        runner.db.close()

    def test_crystals_detection_dom(self) -> None:
        runner = AutopilotRunner("http://test.com", bot_config={}, keep_browser_open=False)
        runner.db = DBManager(self.db_path)
        runner.browser = MagicMock()
        
        runner.browser.page.evaluate = MagicMock(return_value=3)
        self.assertEqual(runner._obtener_cristales_dom(), 3)
        
        runner.db.close()

    def test_crystals_retry_loop(self) -> None:
        # Verify that if cristales < 3, the run loop clears confirmadas_correctas and retries
        runner = AutopilotRunner("http://test.com", bot_config={}, keep_browser_open=False)
        runner.db = DBManager(self.db_path)
        runner.browser = MagicMock()
        
        runner.timings.update({
            "dom_stable_wait_ms": 0,
            "feedback_wait_ms": 0,
            "after_click_wait_ms": 0,
            "after_submit_wait_ms": 0,
            "reload_wait_ms": 0,
            "next_wait_ms": 0,
        })
        runner.limits["max_sheets"] = 1
        runner.limits["max_rondas_por_hoja"] = 2
        
        q1 = {
            "question": "Pregunta simple",
            "data_item": "id-q1",
            "answered": False,
            "options": [
                {"texto": "Opción A", "selector": "#a", "data_op": "a"},
                {"texto": "Opción B", "selector": "#b", "data_op": "b"},
            ],
        }
        
        # Mock DOM extraction: return the question on both rounds
        runner._extraer_todas_las_preguntas = MagicMock(return_value=[q1])
        runner._hacer_clic_en_opcion = MagicMock(return_value=True)
        runner._presionar_calificar = MagicMock(return_value=True)
        runner._presionar_reintentar = MagicMock(return_value=True)
        runner.ir_a_siguiente_hoja = MagicMock(return_value=False)
        
        # Correct classification
        runner._validar_pregunta = MagicMock(return_value="correct")
        
        # First round: 2 crystals (less than 3)
        # Second round: 3 crystals (success)
        crystal_values = [2, 3]
        def mock_obtener_cristales():
            if crystal_values:
                return crystal_values.pop(0)
            return 3
        runner._obtener_cristales = mock_obtener_cristales
        
        # Run
        runner.run()
        
        # Because cristales was < 3 on the first round, confirmadas_correctas should have been cleared,
        # forcing it to re-answer the questions in the second round.
        # This means _hacer_clic_en_opcion should have been called twice (once per round).
        self.assertEqual(runner._hacer_clic_en_opcion.call_count, 2)
        runner._presionar_reintentar.assert_called_once()
        
        runner.db.close()

