# Funcionamiento del bot y conexion con formularios propios

Esta guia explica como funciona el bot y como usarlo con un formulario propio,
tanto en local para pruebas como en una pagina web ya hosteada.

## Resumen corto

El bot no se conecta al formulario por HTML, JavaScript, DOM, base de datos ni
API. Funciona como un bot de vision local:

```text
Formulario visible en el navegador
-> captura de pantalla o region
-> OCR con Tesseract
-> extraccion de pregunta y opciones
-> decision con Ollama local
-> plan de clic sobre la opcion detectada
-> clic real solo si el usuario lo autoriza
```

Por eso sirve igual para un formulario local (`localhost`) y para una pagina
publicada en internet: mientras el formulario se vea en pantalla, el bot puede
analizarlo.

## Componentes principales

- `main.py`: entrada por consola. Lee argumentos, captura pantalla, ejecuta OCR,
  consulta Ollama y muestra el resultado.
- `core/capture.py`: toma screenshot de pantalla completa o de una region.
- `core/ocr.py`: mejora la imagen y extrae texto/cajas con Tesseract.
- `core/parser.py`: separa la pregunta y las opciones detectadas.
- `core/ai.py`: envia la pregunta a Ollama y fuerza una respuesta JSON.
- `core/actions.py`: busca la linea visual que coincide con la respuesta y
  calcula el centro para hacer clic.
- `core/config.py`: valida y normaliza la configuracion usada por la consola web.
- `core/runner.py`: coordina captura, OCR, decision, clic, scroll, loop y estado.
- `web_app.py`: mantiene la API HTTP, los WebSockets y los archivos estaticos.

## Requisitos

- Python 3.11 o 3.12.
- Tesseract OCR instalado en:

```text
C:\Program Files\Tesseract-OCR\tesseract.exe
```

- Ollama instalado y en ejecucion.
- Un modelo local descargado, por ejemplo:

```powershell
ollama pull llama3.1

- Dependencias del proyecto instaladas:

```powershell
cd C:\Users\luidh\Desktop\proyectos\BOT\vision-bot
python -m pip install --upgrade pip
```
## Como debe verse el formulario
El bot esta preparado principalmente para preguntas con opciones. Para que OCR y
clic funcionen bien, el formulario deberia mostrar algo parecido a esto:

```text
A) Madrid
B) Paris
C) Roma
D) Berlin
```

Recomendaciones para tu formulario:

- Usar texto visible, nitido y con buen contraste.
- Mantener la pregunta y las opciones dentro de la misma zona de pantalla.
- Usar opciones con prefijos claros: `A)`, `B)`, `C)`, `D)` o `1.`, `2.`, `3.`.
- Evitar textos muy pequenos, fondos con mucho ruido, animaciones o overlays.
- Mostrar una pregunta a la vez si quieres automatizar el clic con mayor
  confiabilidad.

## Conexion con un formulario local

En local, el formulario puede estar servido por cualquier tecnologia: HTML
estatico, React, Next, Flask, Django, etc. El bot no necesita importar codigo de
esa aplicacion. Solo necesita que el navegador muestre el formulario.

### 1. Levantar el formulario local

Si es una pagina HTML simple:

```powershell
cd ruta\de\tu\formulario
python -m http.server 8000
```

Luego abre:

```text
http://localhost:8000
```

Si es una app web con servidor propio, usa el comando normal del proyecto. Por
ejemplo:

```powershell
npm run dev
```

Luego abre la URL local que indique tu app, por ejemplo:

```text
http://localhost:3000
```

### 2. Abrir el formulario en pantalla

Coloca el navegador de forma que la pregunta y las opciones queden visibles. Es
mejor usar zoom 100% y evitar que la barra del navegador tape contenido.

### 3. Probar lectura sin clic

Ejecuta el bot una vez:

```powershell
cd C:\Users\luidh\Desktop\proyectos\BOT\vision-bot
.\venv\Scripts\python.exe main.py --model llama3.1
```

El bot imprimira:

- ruta de la captura guardada en `screenshots/`;
- texto detectado por OCR;
- pregunta detectada;
- opciones detectadas;
- respuesta elegida por Ollama.

### 4. Usar una region de pantalla

Para mejorar precision y evitar que OCR lea menus, pestanas o texto externo,
usa `--region`:

```powershell
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --model llama3.1
```

El formato es:

```text
x,y,ancho,alto
```

Donde `x,y` son las coordenadas de la esquina superior izquierda de la region y
`ancho,alto` son el tamano del area a capturar.

### 5. Preparar clic sin ejecutarlo

Antes de habilitar clic real, prueba el plan:

```powershell
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --click --model llama3.1
```

Sin `--i-am-authorized`, el bot calcula la coordenada pero no hace clic. Esto
sirve para validar si esta apuntando a la opcion correcta.

### 6. Ejecutar clic real en entorno propio/autorizado

Cuando ya validaste que OCR detecta bien y que el plan apunta a la opcion
correcta:

```powershell
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --click --confirm --i-am-authorized --model llama3.1
```

`--confirm` pide confirmacion antes de hacer clic. `--i-am-authorized` habilita
el clic real.

## Conexion con una pagina web hosteada

Para la pagina ya desplegada, el flujo es el mismo que en local. No hay que
agregar un endpoint especial ni modificar CORS, porque el bot no hace peticiones
al sitio: solo ve lo que aparece en pantalla.

### 1. Abrir la URL publicada

Abre en el navegador la pagina que acabas de desplegar, por ejemplo:

```text
https://tu-dominio.com/formulario
```

### 2. Verificar que el formulario sea visible

Asegurate de que la pregunta y las opciones esten visibles. Si hay login,
cookies, banners o pasos previos, completalos manualmente antes de ejecutar el
bot.

### 3. Ejecutar el bot sobre la pagina publicada

Primero sin clic:

```powershell
cd C:\Users\luidh\Desktop\proyectos\BOT\vision-bot
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --model llama3.1
```

Luego con plan de clic:

```powershell
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --click --model llama3.1
```

Y finalmente con clic real, solo si es tu pagina o tienes permiso explicito:

```powershell
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --click --confirm --i-am-authorized --model llama3.1
```

## Modo continuo

Si quieres que el bot revise el formulario cada ciertos segundos:

```powershell
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --loop --interval 3 --model llama3.1
```

Si combinas `--loop` con `--click`, ten cuidado: cada ciclo puede volver a
preparar o ejecutar una accion.

## Que datos viajan y que datos no viajan

- La captura se procesa en tu maquina.
- OCR se ejecuta con Tesseract local.
- La decision se envia a Ollama local en `http://localhost:11434`.
- No se envia la captura ni el texto a servicios externos desde este codigo.
- El sitio hosteado no recibe nada especial del bot, salvo el clic normal del
  navegador si habilitas la accion real.

## Limitaciones actuales

- El bot esta orientado a preguntas con opciones visibles.
- No llena campos de texto complejos de forma directa.
- No lee el DOM ni valida respuestas desde el backend del formulario.
- Si la opcion correcta queda fuera de pantalla, el bot no podra hacer clic.
- Si OCR lee mal una opcion, la decision de Ollama tambien puede degradarse.

Si necesitas integracion directa con un formulario mediante DOM, API o
automatizacion de navegador, eso seria una mejora distinta: habria que agregar
un modulo que use Playwright/Selenium o consumir un endpoint propio del sitio.

## Solucion de problemas

### Ollama no responde

Verifica que Ollama este abierto y que el modelo exista:

```powershell
ollama list
ollama pull llama3.1
```

### OCR no detecta texto

- Revisa la captura generada en `screenshots/`.
- Aumenta el zoom del navegador.
- Usa una region mas pequena con `--region`.
- Prueba otro modo de segmentacion:

```powershell
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --psm 4 --model llama3.1
```

### Detecta texto de otras partes de la pagina

Usa `--region` para capturar solo el area del formulario.

### El clic apunta a un lugar incorrecto

- Ejecuta primero con `--click` sin `--i-am-authorized`.
- Revisa `Texto objetivo`, `Score OCR` y `Coordenadas`.
- Sube el umbral si quieres que haga clic solo con coincidencias mas fuertes:

```powershell
.\venv\Scripts\python.exe main.py --region 100,200,900,500 --click --min-click-score 0.75 --model llama3.1
```

## Uso responsable

El clic automatico debe usarse solo en formularios propios, demos, entornos de
prueba o escenarios donde exista permiso explicito. Para produccion, lo mas
seguro es empezar con lectura sin clic, luego plan de clic, y al final habilitar
clic real solo cuando ya este validado.
