from __future__ import annotations

import unittest
from unittest.mock import patch
import io
import sys
import logging
from bs4 import BeautifulSoup
from core.mathjax_parser import MathJaxParser
from core.parser import ParsedQuestion

class TestMathJaxParser(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = MathJaxParser()

    def test_detect_mathjax(self) -> None:
        # Check contains_mathjax detection on math tag
        html_math = "<div>Some text <math><mn>2</mn></math> end.</div>"
        self.parser.replace_mathjax(html_math)
        self.assertTrue(self.parser.contains_mathjax)

        # Check contains_mathjax detection on mjx-assistive-mml
        self.parser.contains_mathjax = False
        html_assistive = "<div>Some text <mjx-assistive-mml>content</mjx-assistive-mml> end.</div>"
        self.parser.replace_mathjax(html_assistive)
        self.assertTrue(self.parser.contains_mathjax)

        # Check contains_mathjax is False when no math elements
        self.parser.contains_mathjax = False
        html_none = "<div>Some normal text.</div>"
        self.parser.replace_mathjax(html_none)
        self.assertFalse(self.parser.contains_mathjax)

    def test_parse_mfrac(self) -> None:
        # Simple fraction: 2/4
        html = "<mfrac><mn>2</mn><mn>4</mn></mfrac>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "2/4")

        # Complex fraction: \frac{x+1}{y-2}
        html_complex = "<mfrac><mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow><mrow><mi>y</mi><mo>-</mo><mn>2</mn></mrow></mfrac>"
        result_complex = self.parser.parse_mathml(html_complex)
        self.assertEqual(result_complex, "\\frac{x+1}{y-2}")

    def test_parse_msup(self) -> None:
        # Simple power: x^2
        html = "<msup><mi>x</mi><mn>2</mn></msup>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "x^2")

        # Complex power: {x+y}^{2}
        html_complex = "<msup><mrow><mi>x</mi><mo>+</mo><mi>y</mi></mrow><mn>2</mn></msup>"
        result_complex = self.parser.parse_mathml(html_complex)
        self.assertEqual(result_complex, "{x+y}^{2}")

    def test_parse_msub(self) -> None:
        # Simple subscript: x_1
        html = "<msub><mi>x</mi><mn>1</mn></msub>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "x_1")

        # Complex subscript: {x}_{i+1}
        html_complex = "<msub><mi>x</mi><mrow><mi>i</mi><mo>+</mo><mn>1</mn></mrow></msub>"
        result_complex = self.parser.parse_mathml(html_complex)
        self.assertEqual(result_complex, "{x}_{i+1}")

    def test_parse_msubsup(self) -> None:
        # Subscript + Superscript
        html = "<msubsup><mi>x</mi><mn>1</mn><mn>2</mn></msubsup>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "{x}_{1}^{2}")

    def test_parse_msqrt_and_mroot(self) -> None:
        # Square root of simple variable: sqrt(x)
        html_simple = "<msqrt><mi>x</mi></msqrt>"
        result_simple = self.parser.parse_mathml(html_simple)
        self.assertEqual(result_simple, "sqrt(x)")

        # Square root of expression: \sqrt{x+2}
        html_sqrt = "<msqrt><mi>x</mi><mo>+</mo><mn>2</mn></msqrt>"
        result_sqrt = self.parser.parse_mathml(html_sqrt)
        self.assertEqual(result_sqrt, "\\sqrt{x+2}")

        # Cube root: \sqrt[3]{y}
        html_mroot = "<mroot><mi>y</mi><mn>3</mn></mroot>"
        result_mroot = self.parser.parse_mathml(html_mroot)
        self.assertEqual(result_mroot, "\\sqrt[3]{y}")

    def test_parse_mo_and_mi_and_mn(self) -> None:
        # Variables, numbers, and operators
        html = "<mrow><mi>a</mi><mo>+</mo><mn>25</mn><mo>=</mo><mi>b</mi></mrow>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "a+25=b")

    def test_parse_mfenced(self) -> None:
        # Fenced expression: (a, b)
        html = "<mfenced><mi>a</mi><mi>b</mi></mfenced>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "(a, b)")

    def test_parse_limits(self) -> None:
        # Limits: sum over i from 1 to n
        html = "<munderover><mo>&sum;</mo><mrow><mi>i</mi><mo>=</mo><mn>1</mn></mrow><mi>n</mi></munderover>"
        result = self.parser.parse_mathml(html)
        # &sum; parses as symbol ∑, which is in our list of sum symbols
        self.assertEqual(result, "∑_{i=1}^{n}")

    def test_replace_mathjax_v3(self) -> None:
        # MathJax v3 visual container with assistive mml structure
        html = """
        <div class="content">
            Resolve:
            <mjx-container class="MathJax" jax="SVG">
                <svg>...Visual representation graphics...</svg>
                <mjx-assistive-mml>
                    <math>
                        <mfrac>
                            <mn>2</mn>
                            <mn>4</mn>
                        </mfrac>
                    </math>
                </mjx-assistive-mml>
            </mjx-container>
            correctly.
        </div>
        """
        cleaned_html = self.parser.replace_mathjax(html)
        text = BeautifulSoup(cleaned_html, "html.parser").get_text()
        normalized_text = " ".join(text.split())
        self.assertEqual(normalized_text, "Resolve: 2/4 correctly.")
        self.assertNotIn("svg", cleaned_html)
        self.assertNotIn("mjx-container", cleaned_html)

    def test_replace_mathjax_v2(self) -> None:
        # MathJax v2 pattern
        html = """
        <div>
            Calculate 
            <span class="MathJax_Preview">[math]</span>
            <span class="MathJax" id="MathJax-Element-1-Frame">
                <span>Visual rendering spans...</span>
                <span class="MJX_Assistive_MathML">
                    <math>
                        <msup>
                            <mi>x</mi>
                            <mn>2</mn>
                        </msup>
                    </math>
                </span>
            </span>
            <script type="math/tex" id="MathJax-Element-1">x^2</script>
            now.
        </div>
        """
        cleaned_html = self.parser.replace_mathjax(html)
        text = BeautifulSoup(cleaned_html, "html.parser").get_text()
        normalized_text = " ".join(text.split())
        self.assertEqual(normalized_text, "Calculate x^2 now.")
        self.assertNotIn("MathJax_Preview", cleaned_html)
        self.assertNotIn("MJX_Assistive_MathML", cleaned_html)

    def test_fallback_reconstruction_mjx_tags(self) -> None:
        # Direct replacement using manual fallback reconstruction tags (without assistive mml wrapper)
        html = "<mjx-math><mjx-mfrac><mjx-mn>2</mjx-mn><mjx-mn>4</mjx-mn></mjx-mfrac></mjx-math>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "2/4")

    def test_error_handling(self) -> None:
        # Graceful fallback: when exception is raised inside parser, keep original content
        with patch.object(self.parser, "_parse_element", side_effect=Exception("Parsing failed")):
            html = "<math><mn>2</mn></math>"
            result = self.parser.replace_mathjax(html)
            self.assertIn("2", result)

    def test_log_messages(self) -> None:
        # Test logs print to stdout/logger correctly matching templates
        # We redirect stdout to catch prints
        captured_output = io.StringIO()
        sys.stdout = captured_output
        
        try:
            html = """
            <mjx-container class="MathJax">
                <mjx-assistive-mml>
                    <math>
                        <mfrac>
                            <mn>2</mn>
                            <mn>4</mn>
                        </mfrac>
                        <mo>+</mo>
                        <msup>
                            <mi>x</mi>
                            <mn>2</mn>
                        </msup>
                    </math>
                </mjx-assistive-mml>
            </mjx-container>
            """
            self.parser.replace_mathjax(html)
            
            output = captured_output.getvalue()
            self.assertIn("[MathJaxParser] MathML detectado", output)
            self.assertIn("[MathJaxParser] Fracción convertida: 2/4", output)
            self.assertIn("[MathJaxParser] Potencia convertida: x^2", output)
            self.assertIn("[MathJaxParser] Expresión reconstruida correctamente", output)
        finally:
            sys.stdout = sys.__stdout__

    def test_parser_integration_from_dom(self) -> None:
        # Check that ParsedQuestion.from_dom processes question_html and options_html
        data = {
            "question_html": '<div>Check <math><mfrac><mn>2</mn><mn>4</mn></mfrac></math> here.</div>',
            "options_html": [
                '<span>Option <math><msup><mi>x</mi><mn>2</mn></msup></math></span>',
                '<span>Option B</span>'
            ],
            "selectors": ["#opt1", "#opt2"]
        }
        
        parsed = ParsedQuestion.from_dom(data)
        self.assertEqual(parsed.question, "Check 2/4 here.")
        self.assertEqual(parsed.options, ["Option x^2", "Option B"])

    def test_parse_mtable(self) -> None:
        # 2x2 matrix: (a, b; c, d)
        html = "<mtable><mtr><mtd><mi>a</mi></mtd><mtd><mi>b</mi></mtd></mtr><mtr><mtd><mi>c</mi></mtd><mtd><mi>d</mi></mtd></mtr></mtable>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "(a, b; c, d)")

    def test_parse_mspace(self) -> None:
        # mspace should produce a space between terms
        html = "<mrow><mn>3</mn><mspace width='5px'/><mn>4</mn></mrow>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "3 4")

    def test_parse_menclose(self) -> None:
        # menclose without radical notation should return inner content
        html = "<menclose notation='box'><mn>42</mn></menclose>"
        result = self.parser.parse_mathml(html)
        self.assertEqual(result, "42")

        # menclose with radical notation should return sqrt form
        html_rad = "<menclose notation='radical'><mn>9</mn></menclose>"
        result_rad = self.parser.parse_mathml(html_rad)
        self.assertEqual(result_rad, "sqrt(9)")

    def test_from_dom_image_only_question(self) -> None:
        """Pregunta cuyo HTML no tiene texto (solo imagen) usa el texto JS con [img: ...]."""
        data = {
            "question": "[img: BP3.png]",
            "question_html": '<div class="material"><img src="https://cdn.pruebat.org/recursos/BP3.png" alt="Pregunta"></div>',
            "options": ["[img: P3O1.png]", "[img: P3O2.png]"],
            "options_html": [
                '<label><input type="radio"><img src="https://cdn.pruebat.org/recursos/P3O1.png"></label>',
                '<label><input type="radio"><img src="https://cdn.pruebat.org/recursos/P3O2.png"></label>',
            ],
            "selectors": ["#i1", "#i2"],
        }
        parsed = ParsedQuestion.from_dom(data)
        # Texto de la pregunta debe contener el identificador de imagen
        self.assertIn("[img:", parsed.question)
        # Opciones tampoco deben quedar vacías
        self.assertTrue(all("[img:" in o for o in parsed.options))

    def test_from_dom_img_tag_preserved_alongside_text(self) -> None:
        """Cuando la pregunta tiene texto + imagen, la etiqueta [img: ...] se conserva."""
        data = {
            "question": "¿Cuál es la figura? [img: tangram.png]",
            "question_html": '<div><p>¿Cuál es la figura?</p><img src="tangram.png" alt="figura"></div>',
            "options": [],
            "options_html": [],
        }
        parsed = ParsedQuestion.from_dom(data)
        self.assertIn("¿Cuál es la figura?", parsed.question)
        self.assertIn("[img:", parsed.question)

if __name__ == "__main__":
    unittest.main()
