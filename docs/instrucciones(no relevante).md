Después de obtener la respuesta del modelo:
- Llamar `_extraer_letra(respuesta_raw, len(opciones))`
- Si retorna un índice: `AIAnswer(answer=opciones[indice], index=indice, raw=respuesta_raw)`
- Si retorna `None` (fallback): `AIAnswer(answer=respuesta_raw, index=None, raw=respuesta_raw)`

El campo `answer` debe contener siempre el texto exacto de la opción, no la respuesta
raw del modelo.

---

## Archivo: `core/actions.py`

### 3. Agregar `answer_index` a `plan_click_for_answer()`
Agregar el parámetro opcional `answer_index: int | None = None` a la firma de la función.

Cuando `answer_index` no es `None`, el comportamiento no cambia pero el índice queda
disponible para uso futuro (por ejemplo, filtrar boxes por posición vertical esperada
en casos de opciones duplicadas).

No modificar la lógica de `SequenceMatcher` existente. Con el fix de `ai.py`, el campo
`answer` ya llega con el texto exacto de la opción, por lo que el score será alto
naturalmente.

---

## Archivo: `core/pipeline.py`

### 4. Pasar el texto exacto de la opción al click
Al llamar `plan_click_for_answer()`, usar `answer.answer` (texto exacto de la opción)
en vez de la respuesta raw del modelo.

Pasar también `answer_index=answer.index` si está disponible.

---

## Casos que quedan resueltos

- Respuesta numérica vs texto: "1/3" → la IA elige "C" → se pasa "Una tercera parte"
- Sinónimos o redacción diferente: irrelevante, el texto viene de las propias opciones
- Opciones duplicadas: `answer_index` permite desambiguar por posición
- Opciones con imágenes: la descripción visual queda en el contexto, la elección sigue
  siendo por letra