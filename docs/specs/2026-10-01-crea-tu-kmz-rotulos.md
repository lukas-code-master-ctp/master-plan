# Crea tu KMZ: lectura de rótulos (tarea 1)

Decide cómo se leen los números de lote, las marcas de la cuadrícula y el cuadro de
superficies. Por ahora se midió solo **Tesseract**. El modelo de visión queda pendiente.

## Método

Todo corre en un contenedor `python:3.13-slim` con `tesseract-ocr` 5.5.0 y
`tesseract-ocr-spa`, más `pytesseract`, `opencv-python-headless` y `numpy`. Tesseract corre
con `OMP_THREAD_LIMIT=1` (una hebra por pasada; sin eso, las pasadas en paralelo se
estorban y El Arrayán tarda más de 10 min en vez de ~1). Los scripts
están en `trabajo_crea_kmz/rotulos/`; los recortes y resultados, en `datos/` (fuera de git).

**Lector de rótulos.** Los parámetros son **globales**: los mismos en los 5 planos.
1. Se recorta el rectángulo del dibujo y las máscaras van en blanco (son las entradas de la
   ronda 3; en El Arrayán, el inset 1:5000).
2. La luminancia se divide por el fondo (mediana grande), lo que quita las sombras de la
   foto y el tono del escaneo pálido.
3. Se estima el alto típico de carácter (la moda de los componentes "tipo letra"). Se usan
   2 escalas: el texto modal a 24 px y otra 2,5× más chica para los rótulos grandes.
4. La imagen se rota cada **15°** (24 ángulos), en gris y binarizada con Otsu: 96 pasadas
   de Tesseract `--psm 11` con la lista blanca `LOTE0123456789-,.`.
5. Una palabra vale como rótulo si es `LOTE-12`, `LOTE12`, `12` precedido de "LOTE" en la
   misma línea, o un prefijo como `10-6` (Hidango), del que se toma el último número. Se
   descartan las que tienen `,` o `.` (cotas y áreas).
6. Selección (`seleccion.py`):
   - Si hay ≥ 10 lecturas con "LOTE", cuentan solo esas. Si no, cuentan los números sueltos
     de alto ≥ 1,4× el texto modal.
   - Las lecturas del mismo número a menos de R se agrupan, y el apoyo es el número de
     pasadas que lo leyeron.
   - Queda un número por lugar y un lugar por número; en ambos casos gana el de más apoyo.

**Medición.** La verdad son las semillas leídas a ojo en la ronda 3 (`entradas.py`, en px
de la imagen cruda sin rotar) y en El Arrayán v2 (`etiquetas_leidas.py`, en px del inset).
- Un **acierto** es un lote cuyo número aparece a menos de R de su rótulo real.
- R es ~0,45 × la distancia mediana entre rótulos vecinos de la verdad: El Arrayán 30 px,
  Puente Negro 150, Algarrobo 70, Hidango 190 y Curicó 22. La selección usa el mismo R como
  radio de agrupación, así que ese radio es por plano, no global (en el producto saldría del
  alto del rótulo).
- Sensibilidad: con la mitad de R (en la medición y en la selección) el recall casi no se
  mueve: El Arrayán 36 → 37 %, Puente Negro 97 → 97 %, Algarrobo 80 → 84 %, Hidango
  98 → 97 % y Curicó 11 → 8 %. Los aciertos están cerca: el error de posición máximo es de
  49 px en Puente Negro, 62 en Hidango y ≤ 8 en el resto.
- Una lectura **errada** cae a menos de R de un rótulo pero con otro número.
- El **ruido** cae lejos de todo rótulo real.
- En Curicó la verdad tiene 87 de los 137 lotes, así que una parte del ruido pueden ser
  lotes sin verdad.

## Resultados: números de lote

Apoyo ≥ 1. Tiempo de reloj con 16 núcleos y 96 pasadas en paralelo. El tiempo varía entre corridas
(en una revisión, El Arrayán tardó 46 s y Puente Negro 125 s, con las mismas lecturas).

| Plano | Rótulo | Lotes | Aciertos | Recall | Lecturas | Precisión | Erradas | Ruido | Error pos. mediano | Tiempo |
|---|---|---|---|---|---|---|---|---|---|---|
| El Arrayán | `LOTE-N` rojo, cursiva, ~10 px | 183 | 66 | **36 %** | 92 | 72 % | 26 | 0 | 2 px | 82 s |
| Puente Negro | `LOTE N` grande, rotado | 65 | 63 | **97 %** | 64 | 98 % | 1 | 0 | 10 px | 130 s |
| Algarrobo | `N` suelto + área | 76 | 61 | **80 %** | 294 | 21 % | 48 | 185 | 2 px | 117 s |
| Hidango | `LOTE 10-N` diagonal, pálido | 58 | 57 | **98 %** | 57 | 100 % | 0 | 0 | 12 px | 122 s |
| Curicó | `N` suelto, foto | 87 | 10 | **11 %** | 42 | 24 % | 11 | 21 | 3 px | 68 s |

Variantes (con los mismos datos):
- **Apoyo ≥ 2** sube la precisión y baja poco el recall:
  - El Arrayán: 26 % de recall y 87 % de precisión.
  - Algarrobo: 80 % y 51 %.
  - Curicó: 10 % y 56 %.
  - Hidango: 97 % y 100 %. Puente Negro no cambia.
- **Sin la depuración final** (ni "un número por lugar" ni "un lugar por número"), Algarrobo
  llega a 96 % de recall: los candidatos están, pero los lotes 1–9 los gana ruido de un
  dígito. El Arrayán llega a 41 %, Puente Negro a 100 % y Hidango a 98 %.
- **Con un paso de 30° en vez de 15°** (medido con una selección anterior, sin la variante Otsu),
  Hidango cae a 24 % y Puente Negro a 85 %. Los rótulos diagonales piden un paso fino.
- **Puntaje = apoyo × alto del texto**: no mejora.

## Resultados: cuadrícula y cuadro

- **Cuadrícula de Algarrobo** (página completa, 0/90/180/270°, 57 s): de 15 valores, se leyeron
  bien y en su línea **los 5 N y los 10 E**. Hubo 7 lecturas malas, todas fuera de la
  progresión de 750 m o fuera de su línea. Alcanza de sobra para ajustar la cuadrícula; un
  ajuste robusto valor-vs-píxel las descarta.
- **Cuadro de superficies de Algarrobo** (76 filas, 15 s): la rotación se elige sola (la que da
  más valores `d,dd`). Primero se borran las líneas de la grilla con aperturas morfológicas.
  - **71/76 filas correctas** (lote y TOTAL, el último número de la fila, igual al área
    oficial). Con el área en cualquier columna de la fila son 73/76.
  - Sin borrar las líneas (misma rotación) se leen 5 filas y solo 1 está bien: el borrado es
    imprescindible.

## Modos de falla

1. **Texto chico en cursiva sobre JPEG (El Arrayán, Curicó).** Con ~10 px de alto y sin
   detalle para reescalar, Tesseract confunde el "1" cursivo con serifa con un 4 o un 7
   (`LOTE-1` → `LOTE-4`, `121` → `421`/`427`). En Curicó, foto con números de ~12 px,
   inclinados y negritos, casi no lee nada a ningún ángulo ni escala. El problema es de
   resolución y tipografía, no de rotación.
2. **Números sueltos sin prefijo (Algarrobo).** Sin "LOTE" no hay cómo separar el número de lote
   de las cotas y los fragmentos de área. Filtrar por alto resuelve los de 2 dígitos, pero los
   lotes 1–9 compiten con dígitos sueltos del ruido y se pierden en la selección.

## Costo e infraestructura

- `apt-get install tesseract-ocr tesseract-ocr-spa`: **+106 MB** sin comprimir en la imagen
  (capa medida). Los datos de idioma ocupan 17 MB. `pytesseract` pesa poco; opencv y numpy
  ya los pide la tarea 2.
- Sin costo por plano. La CPU sí pesa: 96 pasadas tardan 1–2 min de reloj con 16 núcleos. Con
  2 vCPU de Cloud Run serían del orden de 10–15 min por plano. Esta cifra es una
  **extrapolación**, no una medición; cabe en un trabajo de fondo con avance.
- Para bajar el costo se puede reducir a 1 escala o solo a gris, o acotar los ángulos tras una
  primera pasada (en la mayoría de los planos los rótulos se agrupan en pocas orientaciones).

## Recomendación (Tesseract solo)

- **Sirve como "semilla + corrección"** en planos con rótulos grandes (Puente Negro, Hidango:
  97–98 % de recall y precisión ≥ 98 %): la loteadora corrige 1–3 lotes a clic.
- **Algarrobo queda a medias**: 80 % de recall, pero aun con apoyo ≥ 2 la precisión es 52 %
  (56 lecturas sobrantes). Sirve solo si la interfaz muestra primero las de más apoyo.
- **No sirve en El Arrayán ni en Curicó** (36 % y 11 %): habría que numerar a mano 117 y ~77
  lotes, y además corregir los errados (26 y 12).
- **Umbral de UX propuesto:**
  - Recall ≥ 80 % con precisión ≥ 90 % (entregando apoyo ≥ 2): el lector ayuda.
  - Bajo 50 %: conviene ofrecer directo "numerar a clic", con las lecturas como sugerencias
    de baja confianza. Un número errado cuesta más que uno faltante: hay que verlo antes de
    corregirlo.
- La interfaz debe mostrar la **confianza (apoyo)** y destacar los lotes sin número o con
  número duplicado.
- **La cuadrícula y el cuadro de superficies sí se pueden leer con Tesseract** (15/15 y 71/76),
  siempre que se borren las líneas del cuadro y se valide la progresión de la cuadrícula.
- Si el modelo de visión no se mide, la decisión sería Tesseract para la cuadrícula, el cuadro
  y la semilla de rótulos, con corrección manual como camino normal.

## Modelo de visión: pendiente (requiere API key)

No se midió porque tiene costo por plano y no hay API key. Cuando esté, hay que correr la
misma medición (`evaluar.py`, mismos R y misma verdad) sobre los 5 planos, con prioridad en El
Arrayán y Curicó, que es donde Tesseract falla. Se registra el costo por plano.
