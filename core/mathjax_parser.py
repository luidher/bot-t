import logging
import bs4
from bs4 import BeautifulSoup, Tag, NavigableString

logger = logging.getLogger("MathJaxParser")

class MathJaxParser:
    def __init__(self) -> None:
        self.contains_mathjax = False

    def parse_mathml(self, html: str) -> str:
        """Convierte MathML en texto plano/LaTeX"""
        if not html:
            return ""
        
        try:
            soup = BeautifulSoup(html, "html.parser")
            # Find root math element in order of priority
            math_root = soup.find("mjx-assistive-mml")
            if not math_root:
                math_root = soup.find("math")
            if not math_root:
                math_root = soup.find("mjx-math")
            if not math_root:
                # Try to find any tag that looks like a math root
                math_root = soup.find()

            if not math_root:
                return ""

            return self._parse_element(math_root).strip()
        except Exception as e:
            logger.warning(f"[MathJaxParser] Error al parsear MathML: {e}")
            print(f"[MathJaxParser] Warning: Error al parsear MathML: {e}")
            # Maintain original text on error
            return html

    def replace_mathjax(self, html: str) -> str:
        """Reemplaza expresiones MathJax en el HTML por texto reconstruido"""
        self.contains_mathjax = False
        if not html:
            return ""

        try:
            soup = BeautifulSoup(html, "html.parser")

            # Detección automática de contenido MathJax
            # Buscar nodos: mjx-assistive-mml, math
            has_assistive = soup.find("mjx-assistive-mml") is not None
            has_math = soup.find("math") is not None
            has_mjx_math = soup.find("mjx-math") is not None

            if has_assistive or has_math or has_mjx_math:
                self.contains_mathjax = True
                logger.info("[MathJaxParser] MathML detectado")
                print("[MathJaxParser] MathML detectado")

            replaced_elements = set()

            # We'll search for root math nodes in order of priority:
            # 1. mjx-assistive-mml
            # 2. math
            # 3. mjx-math
            root_selectors = ["mjx-assistive-mml", "math", "mjx-math"]
            any_replaced = False
            for selector in root_selectors:
                nodes = soup.find_all(selector)
                for node in nodes:
                    # Check if this node or any of its parents has already been replaced
                    is_already_replaced = False
                    parent = node
                    while parent:
                        if parent in replaced_elements:
                            is_already_replaced = True
                            break
                        parent = parent.parent
                    
                    if is_already_replaced:
                        continue

                    # Parse the math root node
                    try:
                        parsed_text = self._parse_element(node)
                        # Add spacing around converted math expressions to prevent word merging
                        parsed_text = f" {parsed_text.strip()} "
                    except Exception as e:
                        logger.warning(f"[MathJaxParser] Error al convertir MathML: {e}")
                        print(f"[MathJaxParser] Warning: Error al convertir MathML: {e}")
                        # Keep original text if conversion fails
                        parsed_text = node.get_text()

                    # Find the MathJax container wrapper to replace the visual representation too
                    container = self._find_mathjax_container(node)
                    if container:
                        # Clean up preview or script tags next to the container
                        prev_sib = container.find_previous_sibling()
                        if prev_sib and self._is_mathjax_preview(prev_sib):
                            prev_sib.decompose()
                        
                        next_sib = container.find_next_sibling()
                        if next_sib and self._is_mathjax_script(next_sib):
                            next_sib.decompose()

                        new_tag = soup.new_string(parsed_text)
                        container.replace_with(new_tag)
                        replaced_elements.add(container)
                        any_replaced = True
                    else:
                        new_tag = soup.new_string(parsed_text)
                        node.replace_with(new_tag)
                        replaced_elements.add(node)
                        any_replaced = True

            # Check for any stray script tags or preview elements that weren't inside a container
            for script in soup.find_all("script", type=lambda t: t and "math/tex" in t):
                script_math = script.string or ""
                script_math = script_math.strip()
                if script_math:
                    script.replace_with(soup.new_string(f" {script_math} "))
                    any_replaced = True
                else:
                    script.decompose()

            for preview in soup.find_all(class_=lambda c: c and "MathJax_Preview" in c):
                preview.decompose()

            if any_replaced:
                logger.info("[MathJaxParser] Expresión reconstruida correctamente")
                print("[MathJaxParser] Expresión reconstruida correctamente")

            return str(soup)
        except Exception as e:
            logger.warning(f"[MathJaxParser] Error general en replace_mathjax: {e}")
            print(f"[MathJaxParser] Warning: Error general en replace_mathjax: {e}")
            return html

    def _normalize_tag(self, tag_name: str) -> str:
        if not tag_name:
            return ""
        tag_name = tag_name.lower()
        if tag_name.startswith("mjx-"):
            return tag_name[4:]
        return tag_name

    def _is_simple(self, text: str) -> bool:
        """Determines if a parsed expression is a simple identifier or number."""
        text = text.strip()
        if not text:
            return True
        return len(text) == 1 and text.isalnum()

    def _parse_element(self, element) -> str:
        if isinstance(element, NavigableString):
            return str(element)
        if not isinstance(element, Tag):
            return ""

        tag = self._normalize_tag(element.name)
        
        # Get children that are Tags
        children = [c for c in element.children if isinstance(c, Tag)]
        
        if tag in ("mi", "mn", "mo", "mtext"):
            text = element.get_text().strip()
            # Handle special invisible mathematical characters
            if text in ("\u2062", "\u2061", "\u2063", "\u2064"):
                return ""
            return text
            
        elif tag == "mfrac":
            if len(children) >= 2:
                num = self._parse_element(children[0]).strip()
                den = self._parse_element(children[1]).strip()
                
                # Check for simple format (like 2/4) or LaTeX format (\frac{2}{4})
                # We log the plain text version: num/den
                logger.info(f"[MathJaxParser] Fracción convertida: {num}/{den}")
                print(f"[MathJaxParser] Fracción convertida: {num}/{den}")
                
                # Return standard LaTeX format for robustness in LLMs,
                # but if both are simple, we can return num/den
                if self._is_simple(num) and self._is_simple(den):
                    return f"{num}/{den}"
                return f"\\frac{{{num}}}{{{den}}}"
            elif len(children) == 1:
                return self._parse_element(children[0])
            return ""
            
        elif tag == "msup":
            if len(children) >= 2:
                base = self._parse_element(children[0]).strip()
                exp = self._parse_element(children[1]).strip()
                
                logger.info(f"[MathJaxParser] Potencia convertida: {base}^{exp}")
                print(f"[MathJaxParser] Potencia convertida: {base}^{exp}")
                
                if self._is_simple(base) and self._is_simple(exp):
                    return f"{base}^{exp}"
                return f"{{{base}}}^{{{exp}}}"
            elif len(children) == 1:
                return self._parse_element(children[0])
            return ""
            
        elif tag == "msub":
            if len(children) >= 2:
                base = self._parse_element(children[0]).strip()
                sub = self._parse_element(children[1]).strip()
                if self._is_simple(base) and self._is_simple(sub):
                    return f"{base}_{sub}"
                return f"{{{base}}}_{{{sub}}}"
            elif len(children) == 1:
                return self._parse_element(children[0])
            return ""
            
        elif tag == "msubsup":
            if len(children) >= 3:
                base = self._parse_element(children[0]).strip()
                sub = self._parse_element(children[1]).strip()
                sup = self._parse_element(children[2]).strip()
                return f"{{{base}}}_{{{sub}}}^{{{sup}}}"
            elif len(children) == 2:
                base = self._parse_element(children[0]).strip()
                sub = self._parse_element(children[1]).strip()
                if self._is_simple(base) and self._is_simple(sub):
                    return f"{base}_{sub}"
                return f"{{{base}}}_{{{sub}}}"
            elif len(children) == 1:
                return self._parse_element(children[0])
            return ""

        elif tag == "msqrt":
            content = "".join(self._parse_element(c) for c in children).strip()
            if not children:
                content = element.get_text().strip()
            
            if self._is_simple(content):
                return f"sqrt({content})"
            return f"\\sqrt{{{content}}}"
            
        elif tag == "mroot":
            if len(children) >= 2:
                base = self._parse_element(children[0]).strip()
                index = self._parse_element(children[1]).strip()
                return f"\\sqrt[{index}]{{{base}}}"
            elif len(children) == 1:
                base = self._parse_element(children[0]).strip()
                if self._is_simple(base):
                    return f"sqrt({base})"
                return f"\\sqrt{{{base}}}"
            return ""
            
        elif tag == "mfenced":
            open_delim = element.get("open", "(")
            close_delim = element.get("close", ")")
            separators = element.get("separators", ",")
            
            parts = [self._parse_element(c).strip() for c in children]
            sep = f"{separators} " if separators else ""
            content = sep.join(parts)
            return f"{open_delim}{content}{close_delim}"
            
        elif tag == "mover":
            if len(children) >= 2:
                base = self._parse_element(children[0]).strip()
                over = self._parse_element(children[1]).strip()
                if over in ("¯", "―", "\u0304", "\u0305", "_"):
                    return f"\\overline{{{base}}}"
                elif over in ("^", "\u0302", "˜", "\u0303"):
                    return f"\\hat{{{base}}}"
                return f"\\overset{{{over}}}{{{base}}}"
            elif len(children) == 1:
                return self._parse_element(children[0])
            return ""

        elif tag == "munder":
            if len(children) >= 2:
                base = self._parse_element(children[0]).strip()
                under = self._parse_element(children[1]).strip()
                if under in ("_", "\u0331", "\u0332"):
                    return f"\\underline{{{base}}}"
                return f"\\underset{{{under}}}{{{base}}}"
            elif len(children) == 1:
                return self._parse_element(children[0])
            return ""

        elif tag == "munderover":
            if len(children) >= 3:
                base = self._parse_element(children[0]).strip()
                under = self._parse_element(children[1]).strip()
                over = self._parse_element(children[2]).strip()
                if base in ("\\sum", "sum", "\\int", "int", "\\prod", "prod", "∑", "∫", "∏"):
                    # Canonical sum/integral format
                    return f"{base}_{{{under}}}^{{{over}}}"
                return f"\\munderover_{{{under}}}^{{{over}}}{{{base}}}"
            elif len(children) == 2:
                base = self._parse_element(children[0]).strip()
                under = self._parse_element(children[1]).strip()
                return f"\\underset{{{under}}}{{{base}}}"
            elif len(children) == 1:
                return self._parse_element(children[0])
            return ""

        elif tag in ("math", "mrow", "semantics", "mstyle", "mpadded", "mphantom"):
            return "".join(self._parse_element(c) for c in children)

        elif tag == "annotation":
            encoding = element.get("encoding", "")
            if "tex" in encoding.lower() or "latex" in encoding.lower():
                return element.get_text().strip()
            return ""

        elif tag == "mtable":
            # Tabla/Matriz: cada fila separada por "; "
            rows = [self._parse_element(c) for c in children]
            return "(" + "; ".join(r for r in rows if r.strip()) + ")"

        elif tag == "mtr":
            # Fila de tabla: celdas separadas por ", "
            cells = [self._parse_element(c) for c in children]
            return ", ".join(c for c in cells if c.strip())

        elif tag == "mtd":
            # Celda de tabla: contenido normal
            return "".join(self._parse_element(c) for c in children)

        elif tag == "mspace":
            # Espacio matemático
            return " "

        elif tag == "menclose":
            # Notación envolvente (cuadro, círculo, etc.)
            content = "".join(self._parse_element(c) for c in children)
            notation = element.get("notation", "")
            if "radical" in notation:
                return f"sqrt({content})" if self._is_simple(content) else f"\\sqrt{{{content}}}"
            return content

        # Default fallback: parse children if any, otherwise return text
        if children:
            return "".join(self._parse_element(c) for c in children)
        return element.get_text().strip()

    def _find_mathjax_container(self, node) -> Tag | None:
        curr = node.parent
        while curr:
            if curr.name == "mjx-container":
                return curr
            classes = curr.get("class", [])
            if isinstance(classes, str):
                classes = [classes]
            if any("mathjax" in c.lower() for c in classes):
                return curr
            curr = curr.parent
        return None

    def _is_mathjax_preview(self, node) -> bool:
        if not isinstance(node, Tag):
            return False
        classes = node.get("class", [])
        if isinstance(classes, str):
            classes = [classes]
        return any("MathJax_Preview" in c for c in classes)

    def _is_mathjax_script(self, node) -> bool:
        if not isinstance(node, Tag):
            return False
        if node.name != "script":
            return False
        script_type = node.get("type", "")
        return "math/tex" in script_type
