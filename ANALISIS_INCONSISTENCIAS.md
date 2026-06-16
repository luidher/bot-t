# Análisis de Inconsistencias - Vision Bot

## 🔴 INCONSISTENCIAS CRÍTICAS

### 1. **Archivos de Configuración Idénticos (web_config.json y widget_config.json)**
**Severidad:** ALTA  
**Ubicación:** `web_config.json` y `widget_config.json`  
**Problema:** Ambos archivos contienen exactamente la misma configuración. El proyecto tiene dos modos de interfaz (web con FastAPI y widget PyQt5), pero ambos se cargan desde el mismo archivo.

**Impacto:**
- Cambios en la config web afectan al widget y viceversa
- Imposible tener configuraciones independientes
- Las características específicas de cada interfaz no se pueden personalizar por separado

**Recomendación:** Renombrar o separar las configuraciones según el modo de uso:
- `web_config.json` → para FastAPI web  
- `widget_config.json` → para PyQt5 widget (actualmente usado por `config.py`)

---

### 2. **Inconsistencia en Rutas de Configuración**
**Severidad:** ALTA  
**Ubicación:** `core/config.py` línea 6 y `core/runner.py` línea 19

```python
# config.py
CONFIG_FILE = Path("widget_config.json")  

# runner.py
CONFIG_FILE = Path("web_config.json")
```

**Problema:** Dos módulos cargan diferentes archivos de configuración, causando que cambios en uno no se reflejen en el otro.

**Impacto:** La configuración se vuelve inconsistente entre sesiones y modos de ejecución.

---

### 3. **Campo "model" Conflictivo en BotConfig**
**Severidad:** ALTA  
**Ubicación:** `core/config.py` línea 16-17

```python
model: str = Field(default="deepseek-r1:8b", min_length=1, max_length=120)
reason_model: str = Field(default="deepseek-r1:8b", min_length=1, max_length=120)
```

**Problema:** Se afirma que `model` es "alias de compatibilidad para `reason_model`", pero:
- No hay `field_validator` que sincronce automáticamente estos campos
- El `@model_validator` `_sync_reason_model` solo actualiza `reason_model` si son diferentes
- Pydantic no reconoce alias automáticamente sin configuración explícita

**Impacto:**
- Confusión sobre cuál campo usar
- Actualizaciones de `model` pueden no reflejarse en `reason_model`
- Modelos inconsistentes en el pipeline

**Recomendación:**
```python
# Usar alias explícito de Pydantic
model: str = Field(
    default="deepseek-r1:8b", 
    min_length=1, 
    max_length=120,
    validation_alias="reason_model"  # Para compatibilidad en JSON
)
```

---

### 4. **Región de Captura Confusa**
**Severidad:** MEDIA  
**Ubicación:** `core/capture.py` línea 16 y documentación README

```python
# En capture.py:
# "region uses the pyautogui convention: x, y, width, height."
```

**Problema:** Sin embargo, en `web_config.json`:
```json
"region": [693, 171, 1051, 592]
```

Esto parece ser `[x1, y1, x2, y2]` (coordenadas de esquina), no `[x, y, width, height]`.

**Verificación en actions.py línea ~26:**
```python
left = min(box.left for box in line_boxes)  # usa directamente como coordenada
```

**Impacto:** 
- La interpretación de región es ambigua
- Posibles capas de pantalla incorrectas

---

### 5. **Mode "auto" Ambiguo**
**Severidad:** MEDIA  
**Ubicación:** `core/runner.py` línea 218-224

```python
mode = self.config.get("mode", "auto")
if mode == "auto":
    if self.config.get("url"):
        return self.run_once_auto_playwright()
    else:
        return self.run_once_auto_vision()
```

**Problema:** 
- El modo "auto" decide basado en presencia de URL
- Pero la config también tiene `mode: "playwright"` y `mode: "vision"`
- El comportamiento no está documentado claramente

**Recomendación:** Documentar explícitamente en config:
```python
mode: str = Field(
    default="auto",
    description='Values: "auto" (URL → playwright, else → vision), "playwright", "vision"'
)
```

---

## 🟡 INCONSISTENCIAS MODERADAS

### 6. **Métodos Heredados sin Eliminar**
**Severidad:** MEDIA  
**Ubicación:** `core/runner.py` línea 205-211

```python
def run_once_playwright(self) -> dict[str, Any]:
    """Legacy wrapper for playwright execution."""
    return self.run_once_auto_playwright()

def run_once_vision(self) -> dict[str, Any]:
    """Legacy wrapper for vision execution."""
    return self.run_once_auto_vision()
```

**Problema:** Métodos redundantes que no añaden valor. Los nombres con "legacy" indican limpieza pendiente.

---

### 7. **Validador "model" que Cambia Valores**
**Severidad:** MEDIA  
**Ubicación:** `core/config.py` línea 67-72

```python
@field_validator("model", "vision_model", "reason_model", "ollama_host", "lang", "tesseract_cmd", "url", mode="before")
@classmethod
def _strip_text(cls, value: Any) -> Any:
    if isinstance(value, str):
        value = value.strip()
        if value == "llama3.1":
            return "deepseek-r1:8b"  # ⚠️ Silencia cambio de modelo
    return value
```

**Problema:**
- El validador convierte silenciosamente `llama3.1` a `deepseek-r1:8b`
- No hay advertencia al usuario
- Hace que las pruebas unitarias con "llama3.1" sean engañosas

**Recomendación:** Advertir explícitamente:
```python
if value == "llama3.1":
    print("[WARNING] Model alias 'llama3.1' is deprecated, using 'deepseek-r1:8b'")
    return "deepseek-r1:8b"
```

---

### 8. **Parser DOM Incompleto**
**Severidad:** MEDIA  
**Ubicación:** `core/browser.py` línea ~50-100

El extractor JavaScript:
```javascript
// Busca selectores genéricos: '.question', '.pregunta', 'h1', 'h2', 'h3'
// Pero los ejemplos HTML usan:
// - li[data-type="OM"]
// - div.question
// - ul.form-list.options-list.opm
```

**Problema:** El selector está parcialmente optimizado para `example.html/example2.html` pero tiene fallbacks genéricos que podrían no funcionar en todos los formularios objetivo.

---

### 9. **Inconsistencia en Rutas de Tesseract**
**Severidad:** BAJA  
**Ubicación:** `core/ocr.py` línea 14 vs `core/config.py` línea 47

```python
# ocr.py (línea 14)
DEFAULT_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# config.py (línea 47)
tesseract_cmd: str = Field(default=r"C:\Program Files\Tesseract-OCR\tesseract.exe", ...)

# Pero no hay sincronización entre ellos
```

**Problema:** La ruta se define en dos lugares. Si se cambia una, la otra no se actualiza automáticamente.

---

### 10. **Vision Analyzer Llama JSON Silenciosamente**
**Severidad:** MEDIA  
**Ubicación:** `core/vision.py` línea 31

```python
"format": "json",  # Solicita JSON a Qwen
```

Pero en `core/vision.py` línea 100:
```python
def parse_vision_response(raw: str) -> dict[str, Any]:
    # No hay validación de si es realmente JSON válido
```

**Problema:** Si Qwen no devuelve JSON válido, la función falla silenciosamente.

---

### 11. **Ausencia de Manejo de Errores en Pipeline**
**Severidad:** MEDIA  
**Ubicación:** `core/pipeline.py` línea ~50-60

Cuando `detect_visual_content()` falla con excepción en OpenCV, no hay catch explícito antes de retornar a `run_once_auto_playwright()`.

---

### 12. **Inconsistencia en Nombres de Métodos**
**Severidad:** BAJA  
**Ubicación:** Varios archivos

```python
# core/parser.py usa:
def parse_question(text: str) -> ParsedQuestion:
def extraer_pregunta_y_opciones(texto: str):  # nombre en español

# core/capture.py usa:
def capture_screen(...) -> CaptureResult:
def tomar_screenshot() -> str:  # nombre en español

# core/ocr.py no tiene wrapper en español
# core/actions.py no tiene wrapper en español
```

**Problema:** Inconsistencia entre nombres en inglés y español. Dificulta la mantenibilidad.

---

## 📋 RESUMEN DE RECOMENDACIONES

| Prioridad | Inconsistencia | Acción |
|-----------|---|---|
| 🔴 ALTA | Configs idénticas | Separar `web_config.json` y `widget_config.json` |
| 🔴 ALTA | CONFIG_FILE diferente en módulos | Centralizar en un archivo o módulo |
| 🔴 ALTA | Campo "model" confuso | Usar alias explícito de Pydantic |
| 🟡 MEDIA | Región ambigua | Documentar formato exacto |
| 🟡 MEDIA | Mode "auto" no documentado | Añadir docstring detallado |
| 🟡 MEDIA | Métodos "legacy" | Eliminar o deprecar formalmente |
| 🟡 MEDIA | Validador silencioso | Advertir cambios de modelo |
| 🟡 MEDIA | Parser DOM incompleto | Validar con ejemplos reales |
| 🟡 MEDIA | Rutas Tesseract duplicadas | Sincronizar con configuración |
| 🟡 MEDIA | Vision JSON sin validación | Añadir try/except en parse_vision_response |
| 🟡 MEDIA | Sin manejo de errores en Pipeline | Envolver en try/except |
| 🟡 BAJA | Nombres en inglés/español | Estandarizar nomenclatura |

---

## ✅ ASPECTOS BIEN IMPLEMENTADOS

1. ✅ **Separación de concerns:** browser.py, ocr.py, vision.py, ai.py bien organizados
2. ✅ **Validación con Pydantic:** BotConfig es sólida (excepto conflicto "model")
3. ✅ **Tests unitarios:** Cobertura de parser, config, actions
4. ✅ **Modo multi-interfaz:** Web + Widget bien separados (excepto config)
5. ✅ **Pipeline híbrido:** Buena arquitectura OCR + Vision + AI
6. ✅ **Documentación README:** Clara y completa
7. ✅ **Setup automation:** Scripts PowerShell y batch bien diseñados

