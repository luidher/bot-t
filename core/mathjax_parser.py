import xml.etree.ElementTree as ET
import re
import html as html_lib

class MathJaxParser:
    def _parse_element(self, element: ET.Element) -> str:
        # Get tag name without namespace
        tag = element.tag
        if '}' in tag:
            tag = tag.split('}', 1)[1]

        # Check for aria-label first (on any element, e.g. mjx-char or others)
        aria_label = element.attrib.get("aria-label")
        if aria_label:
            return aria_label.strip()

        # Handle fractions (Priority 1/2: mfrac, Priority 3: mjx-mfrac)
        if tag in ("mfrac", "mjx-mfrac"):
            num_el = None
            den_el = None
            for child in element:
                child_tag = child.tag.split('}', 1)[1] if '}' in child.tag else child.tag
                if "num" in child_tag:
                    num_el = child
                elif "den" in child_tag:
                    den_el = child
            
            if num_el is not None and den_el is not None:
                num = self._parse_element(num_el)
                den = self._parse_element(den_el)
            elif len(element) >= 2:
                num = self._parse_element(element[0])
                den = self._parse_element(element[1])
            else:
                num = ""
                den = ""
            
            result = f"{num}/{den}"
            print(f"[MathJaxParser] Fracción convertida: {result}")
            return result

        # Handle powers/superscripts (Priority 1/2: msup, Priority 3: mjx-msup)
        if tag in ("msup", "mjx-msup"):
            if len(element) >= 2:
                base = self._parse_element(element[0])
                exp = self._parse_element(element[1])
                result = f"{base}^{exp}"
            else:
                result = "".join(self._parse_element(child) for child in element)
            print(f"[MathJaxParser] Potencia convertida: {result}")
            return result

        # Handle subscripts (Priority 1/2: msub, Priority 3: mjx-msub)
        if tag in ("msub", "mjx-msub"):
            if len(element) >= 2:
                base = self._parse_element(element[0])
                sub = self._parse_element(element[1])
                return f"{base}_{sub}"
            else:
                return "".join(self._parse_element(child) for child in element)

        # Handle square roots (Priority 1/2: msqrt, Priority 3: mjx-msqrt)
        if tag in ("msqrt", "mjx-msqrt"):
            content = "".join(self._parse_element(child) for child in element)
            if not content and element.text:
                content = element.text.strip()
            return f"sqrt({content})"

        # Handle general roots with index/degree
        if tag in ("mroot", "mjx-mroot") and len(element) >= 2:
            base = self._parse_element(element[0])
            index = self._parse_element(element[1])
            return f"root_{index}({base})"

        # Terminal/Leaf elements (mi, mn, mo, or custom mjx tags without children)
        if len(element) == 0:
            text = element.text or ""
            text = text.strip()
            if tag in ("mo", "mjx-mo"):
                # Normalize operator characters
                text = text.replace("\u2212", "-")  # Minus sign
                text = text.replace("\u22c5", "*")  # Dot operator
                text = text.replace("\u00d7", "*")  # Multiplication sign
                text = text.replace("\u2215", "/")  # Division slash
                text = text.replace("\u00f7", "/")  # Division sign
                text = text.replace("\u2264", "<=") # Less than or equal to
                text = text.replace("\u2265", ">=") # Greater than or equal to
                text = text.replace("\u2260", "!=") # Not equal to
            return text

        # Grouping elements (math, mrow, mstyle, mtable, mtr, mtd, mjx-math, etc.)
        # Recursively parse children and join
        return "".join(self._parse_element(child) for child in element)

    def parse_mathml(self, html_str: str) -> str:
        """
        Parses a single MathML string or element to plain text.
        """
        try:
            # Decode HTML-only entities to unicode, leaving XML standard entities intact
            def entity_replacer(match):
                entity = match.group(0)
                name = match.group(1)
                if name in ("amp", "lt", "gt", "apos", "quot"):
                    return entity
                decoded = html_lib.unescape(entity)
                # Escape standard characters so we don't produce invalid XML syntax
                return decoded.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            xml_str = re.sub(r"&([a-zA-Z0-9#]+);", entity_replacer, html_str)
            element = ET.fromstring(xml_str)
            return self._parse_element(element)
        except Exception as e:
            print(f"[MathJaxParser] [WARNING] Error al parsear MathML: {e}")
            return html_str

    def replace_mathjax(self, html_str: str) -> str:
        """
        Detects and replaces MathML/MathJax expressions in a block of HTML.
        Returns the modified HTML block.
        """
        if not html_str:
            return ""

        # Priority 1: <mjx-assistive-mml>
        pattern_mml = re.compile(r"<mjx-assistive-mml\b[^>]*>.*?</mjx-assistive-mml>", re.DOTALL | re.IGNORECASE)
        def replace_mml(match):
            mml_block = match.group(0)
            print("[MathJaxParser] MathML detectado.")
            parsed = self.parse_mathml(mml_block)
            if parsed != mml_block:
                print("[MathJaxParser] Expresión reconstruida correctamente.")
            return parsed

        result = pattern_mml.sub(replace_mml, html_str)

        # Priority 2: <math>
        pattern_math = re.compile(r"<math\b[^>]*>.*?</math>", re.DOTALL | re.IGNORECASE)
        def replace_math(match):
            math_block = match.group(0)
            print("[MathJaxParser] MathML detectado.")
            parsed = self.parse_mathml(math_block)
            if parsed != math_block:
                print("[MathJaxParser] Expresión reconstruida correctamente.")
            return parsed

        result = pattern_math.sub(replace_math, result)

        # Priority 3: <mjx-math>
        pattern_mjx_math = re.compile(r"<mjx-math\b[^>]*>.*?</mjx-math>", re.DOTALL | re.IGNORECASE)
        def replace_mjx_math(match):
            mjx_math_block = match.group(0)
            print("[MathJaxParser] MathML detectado.")
            parsed = self.parse_mathml(mjx_math_block)
            if parsed != mjx_math_block:
                print("[MathJaxParser] Expresión reconstruida correctamente.")
            return parsed

        result = pattern_mjx_math.sub(replace_mjx_math, result)

        return result
