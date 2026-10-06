# Crea tu KMZ: corregir vértices a mano en Revisar

## El problema

Caminos de Rapel llega del CBR escaneado a 150 dpi y no hay otro archivo. A esa
resolución, el deslinde norte son tres líneas paralelas a unos 2 mm (borde del camino,
deslinde del lote y servidumbre punteada) con texto subrayado entre ellas. El resultado
de la partición depende de la fase de píxel del recorte: girar el plano o cambiar el
margen hace que cambie qué lote se queda con la franja. Se probaron otros pasos (marcar
los bolsillos, solo rectas, sin reescalar) y ninguno deja 8-01 y 8-05 bien en todas las
variantes. No hay un arreglo de algoritmo que valga para este escaneo.

Lo que queda es que la loteadora corrija a mano el par de vértices que salen mal, sobre
el satélite, en el paso Revisar, que es donde ya ve los lotes coloreados contra el cuadro.

## Lo que se arma

En Revisar, un botón "Corregir vértices a mano". Con el botón activo:

- Desde el zoom 17 se ven los vértices de los lotes como círculos que se pueden arrastrar.
  De más lejos son demasiados y se tapan entre sí; el panel dice "Acércate al mapa para
  ver los vértices". Solo se dibujan los de la vista, porque un loteo grande tiene miles.
- **Mover:** se arrastra el vértice. Si dos o más lotes lo comparten, se mueve en todos,
  así los vecinos siguen pegados.
- **Borrar:** se toca el vértice y su ventanita trae "Borrar este vértice". Se puede borrar
  un vértice de un solo lote (el diente de 8-05) o uno que está en medio de un lado
  compartido. Una esquina entre lotes (los vecinos de antes y después no son los mismos en
  todos los lotes) no se borra: se mueve.
- **Deshacer (n):** vuelve atrás la última corrección, hasta 20.
- Tras cada corrección se recalculan las áreas y los colores del panel, y el KMZ creado
  queda atrasado (hay que volver a crearlo).
- Las ventanitas de ficha de los lotes se apagan mientras se corrige, para que tocar un
  vértice no abra la del lote.

Volver a digitalizar descarta las correcciones: los lotes son otros.

## Cómo se guarda

- El punto viaja como `[lon, lat]`. La consola lo lleva a píxeles de página con la
  inversa de la homografía de la georreferencia, y busca el vértice más cercano dentro de
  0,5 px en todos los anillos de `digitalizado.json`. La topología es compartida (sale de
  `polygonize`), así que el mismo vértice tiene las mismas coordenadas en cada lote.
- `digitalizado.json` se reescribe con la corrección y se regenera `lotes.geojson`.
- `ediciones.json` guarda el historial para deshacer (`{lotes, sin_numero}` antes de cada
  corrección).
- Un lote que queda cruzado consigo mismo o con menos de tres vértices responde 400 y no
  cambia nada. Sin ubicar responde 409.

## Ruta

`POST /api/kmz/{slug}/corregir` con `{"accion": "mover"|"borrar"|"deshacer", "punto":
[lon, lat], "a": [lon, lat]}`. Responde `{"deshacer": n}`. Un KMZ de otra loteadora
responde 404, como el resto de las rutas de Crea tu KMZ.

## Lo que no hace

- No agrega vértices nuevos ni parte o une lotes.
- No corrige el plano en sí: si se digitaliza otra vez, hay que corregir de nuevo.
- No mueve las calles ni el contorno aparte de los lotes.
