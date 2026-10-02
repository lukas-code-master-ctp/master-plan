# Crea tu KMZ: del plano aprobado al KMZ de la subdivisión

## Problema

Para armar un master hace falta el KMZ de la subdivisión, y muchas loteadoras no lo
tienen. Lo que sí tienen siempre es el **plano aprobado por el SAG y archivado en el CBR**:
un PDF escaneado (o una foto del papel), sin vectores ni coordenadas de vértices. Pedirle
el DWG al topógrafo no es una opción.

## Lo que ya sabemos (pruebas de concepto, oct-2026)

Cinco planos reales, cuatro de ellos a ciegas, medidos contra sus KMZ reales:

| Plano | Tinta / fuente | Ubicación | IoU por lote, tal cual → con ubicación ideal | Centroide, tal cual → ideal |
|---|---|---|---|---|
| El Arrayán | roja, escaneo | 2 anclas de Google Earth | 0,70 → 0,97 | 9,9 → 0,7 m |
| Puente Negro | negra, escaneo | 3 anclas | 0,85 → 0,98 | 5,3 → 0,55 m |
| Algarrobo | negra, escaneo | cuadrícula UTM impresa | **0,98** → 0,98 | **1,7** → 1,5 m |
| Curicó | negra, **foto** | foto rectificada + 3 anclas | 0,76 → 0,92 | 8,1 → 1,8 m |

Conclusiones que fijan el diseño:

1. **La forma sale bien** con una "red de deslindes": líneas compartidas entre vecinos,
   rectas donde el plano es recto, sin traslapes ni huecos por construcción.
2. **La ubicación es lo que mete error.** Con cuadrícula impresa queda perfecta. Con
   anclas, cada una se desvía 1–19 m, y en un caso el punto se marcó sobre la línea
   equivocada del plano. Dos anclas no permiten detectar una mala.
3. **El deslinde va por el eje del camino:** los lotes cubren todo el predio, sin
   polígonos de camino.
4. **El cuadro de superficies del plano es el mejor control:** el área de cada lote
   contra la oficial marca los lotes mal separados.
5. Una foto del papel se endereza con las 4 esquinas del marco impreso, sin anclas extra.

## Solución

Una herramienta en la consola, para cada loteadora, que convierte el plano en el KMZ del
master. Vive en el detalle de un master (`#/planos/<slug>/kmz`) y también se ofrece desde
"Nuevo master" como alternativa a subir un KMZ ("No tengo el KMZ: créalo desde el plano").

### Flujo

1. **Subir el plano** (PDF). El servidor extrae la imagen de cada página **sin
   rerasterizar** (el JPEG embebido; si no hay, renderiza a 200 dpi) y muestra
   miniaturas. La loteadora elige la página y la rotación.
2. **Marcar el dibujo**: un rectángulo alrededor de la "situación propuesta" y
   rectángulos sobre lo que no es dibujo (cuadros, cajetín, timbres, croquis). Si la
   fuente es una foto, marca (o confirma) las 4 esquinas del marco impreso para
   rectificar la perspectiva.
3. **Digitalizar** (trabajo de fondo, con avance en vivo):
   máscara de tinta (roja o negra; descarta verde, azul, achurados y cuadrícula) →
   regiones cerradas, separadas con las semillas de los rótulos → red plana de deslindes
   → aristas enderezadas (recta si cabe en ~2 px, si no Douglas-Peucker) → polígonos
   desde las caras.
4. **Numerar**: lectura automática de los rótulos ("LOTE 12", "12") que da número y
   posición (semilla). La loteadora corrige o completa con un clic sobre el lote. Si se
   puede leer el cuadro de superficies, cada lote queda con su área oficial.
5. **Ubicar en el mapa**:
   - **Cuadrícula impresa**: si el plano trae marcas UTM (E-…, N-…), se ajusta con
     ellas (WGS84/SIRGAS UTM 19S por defecto, PSAD56 como alternativa si las anclas lo
     indican).
   - **Anclas**: plano a la izquierda, mapa Esri (Leaflet, el del visor) a la derecha.
     Se marcan **3 o 4 pares de puntos** con zoom grande sobre el plano. La herramienta
     sugiere marcar esquinas del predio y cruces de caminos. Ajuste por mínimos
     cuadrados (similitud) con residuo por punto: un ancla con residuo alto se marca y
     se puede quitar o volver a marcar.
   - **Ajuste fino**: los lotes sobre la imagen satelital y un arrastre (traslación) para
     calzar los caminos con los deslindes.
6. **Revisar**: lotes sobre el mapa, coloreados por error de área contra el cuadro (si lo
   hay): verde ±2 %, ámbar ±5 %, rojo más. También se marcan los lotes sin número.
7. **Crear el KMZ**: un Polygon por lote, con nombre `LOTE <n>`, KML 2.2, sin
   LineStrings (así `pipeline/kmz.py` lo lee en modo polígonos). Se guarda en las
   fuentes del master como `subdivision.kmz`. Si ya había un KMZ, se pide confirmar el
   reemplazo y el anterior se renombra a `.kmz.anterior`.

### Lo que se guarda

`fuentes/<slug>/plano/`:
- `plano.pdf`
- `paginas/<n>.jpg`
- `entradas.json`: página, rotación, rectángulos, esquinas del marco, anclas, números
  corregidos y ajuste fino
- `digitalizado.json`: lotes en píxeles del plano, rótulos, cuadrícula detectada, áreas
  oficiales
- `georreferencia.json`: transformación, residuos y datum

Todo se puede retomar y rehacer: cambiar una entrada vuelve a calcular solo lo que depende
de ella.

### Set de regresión

Los planos de prueba con sus KMZ reales quedan **fuera de git** (traen nombres y RUT de
propietarios) en `regresion/planos/<plano>/` (`plano.pdf`, `real.kmz`, `entradas.json`).
`python -m pipeline.plano.regresion` corre el método completo sobre cada uno y mide contra
el real: IoU, centroide, Hausdorff, el "what-if" con la similitud óptima, la descomposición
de la georreferencia, y traslapes y huecos. Escribe una tabla y falla si un plano empeora
más allá de una tolerancia contra la línea base guardada. La línea base inicial son los
números de las pruebas de concepto.

## Decisión abierta: cómo leer los rótulos

Las pruebas numeraron leyendo a ojo. El producto necesita leer números de lote, las marcas
de la cuadrícula y, si se puede, el cuadro de superficies. Hay dos caminos:

- **OCR clásico (Tesseract)**: gratis por plano; se instala en la imagen con apt. Rinde
  mal con texto chico, rotado y escaneado.
- **Modelo de visión (Claude)**: probablemente mucho mejor con rótulos rotados y tablas.
  Cuesta por plano y necesita una API key en Secret Manager.

La **tarea 1 del plan** mide los dos sobre los planos de prueba (aciertos de número y de
posición) y deja la decisión escrita. El resto del diseño no cambia: el lector entrega
`[(numero, x, y, confianza)]` y la loteadora corrige.

## Fuera del alcance

- Leer DWG o DXF.
- Corregir el plano (errores del topógrafo) o validar deslindes legalmente.
- Reconstruir lotes que la lámina no dibuja.
- Unir varias láminas de detalle: se usa la vista que muestra el predio completo. La
  primera versión trabaja con una página.
- Edición libre de geometría (mover vértices a mano). Si un lote sale mal, se corrige
  ajustando las entradas (máscaras, semillas).
- Precisión mejor que la del plano escaneado más las anclas.

## Criterios de aceptación

1. Con las entradas guardadas de cada plano del set, el método completo reproduce (con
   tolerancia) los números de las pruebas de concepto: IoU what-if mediano ≥ 0,92 en
   todos y centroide what-if mediano ≤ 2 m.
2. Algarrobo se ubica solo con su cuadrícula: centroide tal cual ≤ 3 m.
3. Con 3+ anclas, un ancla con error grosero (> 3× el residuo mediano) queda marcada.
4. El KMZ generado lo lee `pipeline.kmz.leer_kmz`, con un polígono por lote e ids únicos,
   y un master se construye con él.
5. Una loteadora completa el flujo desde la consola sin tocar archivos. Se valida en QA
   con un plano nuevo.
6. `pytest` y `node --test` pasan, y el inventario de rutas está declarado.
