import unittest
from core.mathjax_parser import MathJaxParser
from core.parser import ParsedQuestion

class TestMathJaxParser(unittest.TestCase):
    def setUp(self):
        self.parser = MathJaxParser()

    def test_parse_fraction(self):
        html = "<mfrac><mn>2</mn><mn>4</mn></mfrac>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "2/4")

    def test_parse_power(self):
        html = "<msup><mi>x</mi><mn>2</mn></msup>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "x^2")

    def test_parse_subscript(self):
        html = "<msub><mi>x</mi><mn>1</mn></msub>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "x_1")

    def test_parse_sqrt(self):
        html = "<msqrt><mi>x</mi></msqrt>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "sqrt(x)")

    def test_operator_normalization(self):
        # Unicode minus: \u2212 -> -
        html_minus = "<mo>\u2212</mo>"
        self.assertEqual(self.parser.parse_mathml(html_minus), "-")

        # Unicode times: \u00d7 -> *
        html_times = "<mo>\u00d7</mo>"
        self.assertEqual(self.parser.parse_mathml(html_times), "*")

    def test_priority_3_manual_reconstruction(self):
        html = (
            "<mjx-math>"
            "<mjx-mfrac>"
            "<mjx-num><mjx-mn>4</mjx-mn></mjx-num>"
            "<mjx-den><mjx-mn>8</mjx-mn></mjx-den>"
            "</mjx-mfrac>"
            "</mjx-math>"
        )
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "4/8")

    def test_error_handling_malformed_xml(self):
        # Malformed XML should log warning and return original string without crashing
        html = "<mfrac><mn>2</mn>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, html)

    def test_html_entities(self):
        # &times; is HTML-only entity and should be parsed to *
        # &alpha; is HTML-only entity and should be parsed to α
        html = "<math><mi>&alpha;</mi><mo>&times;</mo><mn>2</mn></math>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "α*2")

    def test_replace_mathjax_integration(self):
        html = "¿Qué número es mayor <mjx-assistive-mml><math><mfrac><mn>2</mn><mn>4</mn></mfrac></math></mjx-assistive-mml> o <mjx-assistive-mml><math><mfrac><mn>2</mn><mn>8</mn></mfrac></math></mjx-assistive-mml>?"
        clean_html = self.parser.replace_mathjax(html)
        self.assertEqual(clean_html, "¿Qué número es mayor 2/4 o 2/8?")

    def test_parsed_question_from_dom_fallback(self):
        # Backwards compatibility: without html, uses plain question/options
        data = {
            "question": "Standard question",
            "options": ["Opt A", "Opt B"]
        }
        pq = ParsedQuestion.from_dom(data)
        self.assertEqual(pq.question, "Standard question")
        self.assertEqual(pq.options, ["Opt A", "Opt B"])
        self.assertFalse(pq.contains_mathjax)

    def test_parsed_question_from_dom_with_html(self):
        # Integrated MathJax conversion inside ParsedQuestion
        data = {
            "question_html": "<div>¿Qué número es mayor <math><mfrac><mn>2</mn><mn>4</mn></mfrac></math>?</div>",
            "options_html": [
                "<div><math><mfrac><mn>2</mn><mn>4</mn></mfrac></math>, porque se compone de partes más grandes.</div>",
                "<div><math><mfrac><mn>2</mn><mn>8</mn></mfrac></math></div>"
            ],
            "contains_mathjax": True
        }
        pq = ParsedQuestion.from_dom(data)
        self.assertEqual(pq.question, "¿Qué número es mayor 2/4?")
        self.assertEqual(pq.options, [
            "2/4, porque se compone de partes más grandes.",
            "2/8"
        ])
        self.assertTrue(pq.contains_mathjax)

if __name__ == "__main__":
    unittest.main()
