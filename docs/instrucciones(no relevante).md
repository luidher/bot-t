INSTRUCCIONES PARA IMPLEMENTAR MÓDULO DE EXTRACCIÓN, RESPUESTA INTELIGENTE Y PERSISTENCIA (10K+ REGISTROS)
1. REQUISITOS PREVIOS (INSTALACIÓN Y CONFIGURACIÓN)
Lenguaje y entorno: Determina el lenguaje de tu sistema base (JavaScript/Node.js, Python, etc.).

Dependencias mínimas:

Motor de base de datos ligero: SQLite.

Librería oficial para SQLite (ej: better-sqlite3 en Node, sqlite3 en Python).

Librería para generar hashes (ej: crypto nativo en Node, hashlib en Python).

Archivo de configuración: Crea un objeto JSON con los selectores CSS de la plataforma objetivo. Debes tener claro:

Contenedor de pregunta.

Texto de la pregunta.

Contenedor de cada opción (y su texto).

Clase/atributo que indica respuesta correcta (ej: class="correct").

Clase/atributo que indica respuesta incorrecta (ej: class="incorrect").

Botón o enlace para ir a la siguiente hoja/página.

Botón o enlace para reiniciar/intentar de nuevo la hoja actual (si existe). Si no existe, deberás simularlo recargando la URL actual.

2. ESTRUCTURA DE LA BASE DE DATOS
Crea una tabla llamada respuestas con los siguientes campos:

id (INTEGER, PRIMARY KEY, AUTOINCREMENT).

hash_pregunta (TEXT, UNIQUE, NOT NULL). → Almacena el SHA-256 o MD5 del texto limpio de la pregunta.

texto_pregunta (TEXT, NOT NULL).

opcion_correcta (TEXT, NOT NULL). → Guarda el texto exacto de la opción ganadora.

fecha_guardado (DATETIME, DEFAULT CURRENT_TIMESTAMP).

Indexa el campo hash_pregunta para búsquedas ultrarrápidas: CREATE INDEX idx_hash ON respuestas(hash_pregunta);.

3. FUNCIONES AUXILIARES OBLIGATORIAS (IMPLEMENTAR ANTES DEL BUCLE PRINCIPAL)
Debes crear las siguientes funciones en tu código, independientes del flujo principal:

calcularHash(texto): Recibe un string, elimina espacios múltiples y mayúsculas/minúsculas (normaliza) y devuelve el hash hexadecimal.

consultarDB(hash): Ejecuta SELECT opcion_correcta FROM respuestas WHERE hash_pregunta = ?. Devuelve el texto de la opción si existe, o null si no.

guardarEnDB(hash, pregunta, opcion): Ejecuta INSERT OR REPLACE INTO respuestas (hash_pregunta, texto_pregunta, opcion_correcta) VALUES (?, ?, ?).

extraerPreguntasYOpciones(): Función que captura el DOM actual y devuelve un array de objetos con la estructura:

json
[
  {
    "texto": "¿Capital de Francia?",
    "opciones": ["París", "Londres", "Madrid", "Berlín"],
    "indicePregunta": 0  // (opcional, para referencia)
  }
]
hacerClicEnOpcion(indicePregunta, indiceOpcion): Función que, dado el índice de la pregunta y el índice de la opción, realiza el clic en el elemento del DOM.

validarAcierto(indicePregunta, indiceOpcion): Función que verifica en el DOM si esa opción específica tiene la clase de "correcto" o si apareció un mensaje de éxito. Devuelve true o false.

recargarHojaActual(): Función que reinicia el estado de la hoja sin avanzar a la siguiente. Debe:

Si existe botón "Reintentar", hacer clic en él.

Si no existe, recargar la URL actual (window.location.reload() en contexto de navegador o page.reload() en Puppeteer).

Esperar a que el DOM se estabilice nuevamente.

irASiguienteHoja(): Función que hace clic en el botón de "Siguiente" y espera la carga de la nueva hoja.

4. LÓGICA DEL BUCLE PRINCIPAL (POR HOJA Y POR PREGUNTA)
El algoritmo debe manejar una sola hoja a la vez. Dentro de ella, itera pregunta por pregunta.

Paso A – Inicio de hoja:

Extrae todas las preguntas y opciones usando extraerPreguntasYOpciones().

Inicializa un contador preguntaActual = 0.

Paso B – Procesar una pregunta (bucle interno):

Toma el objeto de preguntas[preguntaActual].

Calcula el hash de pregunta.texto.

Consulta la DB con ese hash.

Si existe en DB:

Obtén el texto de opcion_correcta.

Busca su índice en el array opciones de la pregunta.

Ejecuta hacerClicEnOpcion(preguntaActual, indiceEncontrado).

Espera 500ms para que el sistema valide (opcional, pero recomendado).

No necesitas verificar si es correcta (asumes que la DB es fiable). Incrementa preguntaActual en 1 y ve al Paso B (siguiente pregunta).

Si NO existe en DB:

Crea un Set llamado descartadas (vacío).

Inicia un contador intentos = 0.

Bucle while (intentos < 4 o hasta que queden opciones no descartadas):

Filtra las opciones cuyo índice no esté en descartadas.

Si el filtro está vacío, lanza un error (no hay más opciones que probar).

Elige un índice aleatorio de entre los disponibles.

Ejecuta hacerClicEnOpcion(preguntaActual, indiceElegido).

Espera el tiempo necesario para que el sistema muestre el feedback (ej: 800ms).

Ejecuta validarAcierto(preguntaActual, indiceElegido).

Si devuelve true:

Guarda en DB usando guardarEnDB(hash, pregunta.texto, opciones[indiceElegido]).

Rompe el bucle while, incrementa preguntaActual en 1 y ve al Paso B (siguiente pregunta).

Si devuelve false:

Agrega indiceElegido al Set descartadas.

Ejecuta recargarHojaActual() (esto limpia todas las selecciones de la hoja).

Vuelve a extraer preguntas y opciones (porque la recarga puede alterar el DOM). Actualiza el array preguntas y asegúrate de mantener el mismo preguntaActual.

Incrementa intentos en 1.

Paso C – Verificar fin de hoja:

Cuando preguntaActual sea igual al número total de preguntas de la hoja, significa que todas fueron respondidas correctamente.

Entonces ejecuta irASiguienteHoja().

Vuelve al Paso A para procesar la nueva hoja.

5. MANEJO DE RECARGAS DE HOJA (PUNTO CRÍTICO)
Tras ejecutar recargarHojaActual(), el DOM se destruye y reconstruye. Por lo tanto, debes re-ejecutar extraerPreguntasYOpciones() y actualizar el array con las nuevas referencias.

Al recargar, las opciones pueden aparecer en distinto orden. Para evitar confusiones, no uses índices fijos; usa el texto de la opción para identificar la que quieres probar. Pero como estás en un bucle de descarte, es más seguro trabajar con índices relativos al orden actual. La recomendación es: tras recargar, vuelve a extraer todas las opciones, pero mantén el Set de descartadas basado en el TEXTO de la opción (no en el índice), porque el orden puede cambiar. Convierte descartadas en un Set de strings (textos de opciones) en lugar de índices. Al elegir al azar, filtra por texto.

6. GUARDADO EN LOTE PARA RENDIMIENTO (10K+ REGISTROS)
Las inserciones individuales son lentas. Implementa un buffer en memoria:

Crea un array bufferInserciones = [].

En lugar de llamar a guardarEnDB inmediatamente tras un acierto, agrega el objeto {hash, pregunta, opcion} al buffer.

Cuando el buffer alcance 100 registros, ejecuta una inserción múltiple:

En SQLite: INSERT INTO respuestas (hash_pregunta, texto_pregunta, opcion_correcta) VALUES (?,?,?), (?,?,?), ...;.

Vacía el buffer tras la inserción.

Al finalizar toda la ejecución (o al cerrar el script), vacía el buffer restante.

7. CONTROL DE ERRORES Y SEGURIDAD
Límite de intentos por pregunta: Si intentos supera el número de opciones (ej: 4), detén el script y lanza una alerta (posible cambio en la interfaz o fallo en selectores).

Límite de hojas totales: Pon un contador maxHojas = 10000 o hasta que no haya botón "Siguiente" visible.

Timeouts: En cada espera (feedback, recarga), usa esperas inteligentes (waitForSelector o waitForFunction) en lugar de tiempos fijos, para que el script no se acelere ni se ralentice innecesariamente.

Duplicados: La base de datos con UNIQUE(hash_pregunta) evita duplicados automáticamente.

8. FLUJO DE "FUTURAS CONSULTAS" (REUTILIZACIÓN)
Cuando el script se ejecute en una nueva sesión, automáticamente consultará la DB antes de responder al azar.

No necesitas un modo especial. La lógica del Paso B (consultar primero) ya garantiza que las preguntas conocidas se respondan sin fallos y sin gastar intentos.

Para verificar que la DB se está usando, agrega logs: "🧠 Respondiendo desde DB: X" vs "🎲 Probando al azar: X".