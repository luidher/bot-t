# Vision Bot local con OCR y Ollama

Proyecto demostrativo para entornos propios o autorizados. El bot no usa HTML:
observa la pantalla, extrae texto con OCR, interpreta la pregunta con Ollama y
puede preparar una interaccion de usuario sobre la opcion detectada.

## Flujo

```text
Pantalla o region
-> captura PNG
-> preprocesamiento de imagen
-> OCR con Tesseract
-> parser de pregunta/opciones
-> decision con Ollama local
-> plan de clic seguro
```

## Requisitos

- Python 3.11 o 3.12
- Tesseract OCR instalado en `C:\Program Files\Tesseract-OCR\tesseract.exe`
- Ollama instalado y ejecutandose
- Un modelo local descargado, por ejemplo:

```powershell
ollama pull llama3.1
```

## Instalacion

El proyecto usa `requirements.txt` como archivo bloqueado de dependencias.
`requirements.in` queda como lista corta de dependencias directas para futuras
actualizaciones.

Si el entorno virtual actual no arranca, recrealo:

```powershell
cd C:\Users\luidh\Desktop\proyectos\BOT\vision-bot
Remove-Item -Recurse -Force .\venv
py -3.12 -m venv venv
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Si `py` no existe, instala Python desde python.org y marca la opcion de agregarlo
al PATH.

Tambien puedes usar `iniciar_web.bat`; el script detecta si `venv` esta roto,
lo recrea y reinstala las dependencias bloqueadas.

## Pruebas

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Uso basico

Analizar toda la pantalla una vez:

```powershell
.\venv\Scripts\python.exe main.py --model llama3.1
```

Analizar solo una region:

```powershell
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --model llama3.1
```

Preparar clic sin ejecutarlo:

```powershell
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --click
```

Ejecutar clic real solo en una demo propia/autorizada:

```powershell
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --click --confirm --i-am-authorized
```

## Modulos

- `core/capture.py`: captura pantalla completa o region.
- `core/ocr.py`: preprocesa imagen y obtiene texto/cajas OCR.
- `core/parser.py`: separa pregunta y opciones.
- `core/ai.py`: llama a Ollama y fuerza respuesta JSON.
- `core/actions.py`: encuentra coordenadas de la opcion y ejecuta clic seguro.
- `core/config.py`: valida y normaliza la configuracion del bot.
- `core/runner.py`: orquesta captura, OCR, decision, clic, loop y estado.
- `web_app.py`: expone API, WebSocket y archivos estaticos de la consola web.

## Nota de uso

La automatizacion de clics debe usarse solamente en interfaces propias,
entornos de prueba o escenarios donde exista permiso explicito.

## Documentacion de formularios

Para entender como funciona el bot y como usarlo con un formulario propio en
local o con una pagina web hosteada, revisa:

- [`docs/funcionamiento-y-formularios.md`](docs/funcionamiento-y-formularios.md)
