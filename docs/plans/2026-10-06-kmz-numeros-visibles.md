# Plan: números de lote visibles en el KMZ

Spec: `docs/specs/2026-10-06-kmz-numeros-visibles.md`.

## Tarea 1: rótulo por lote en el KML

- `pipeline/plano/salida.py`, `kml()`: cada Placemark lleva
  `<MultiGeometry><Point>` (en `representative_point()` del polígono lon/lat) `+ <Polygon>`.
  Estilo `#lote` con `IconStyle` escala 0 y `LabelStyle` blanco. Docstring del módulo al día.
- `pipeline/tests/test_plano_salida.py`: el test que exigía "sin Point" pasa a exigir un
  Point por Placemark, dentro de su polígono; `leer_kmz` sigue dando los mismos ids y
  áreas.
- Verificación: `python3 -m pytest -q pipeline/tests/test_plano_salida.py consola/tests/test_kmz.py`
  y la suite completa.

## Tarea 2: que se note al crear el KMZ

- `consola/web/js/kmz.js`: un estado `creandoKmz` (el slug que se está creando) que
  `crearKmz()` prende al empezar y apaga en `finally`; `pintarCrear()` lo usa para
  desactivar el botón, ponerle "Creando el KMZ…" y `aria-busy`. El texto de listo
  suma la hora (`HH:MM`, es-CL) y `#kmz-listo` reinicia una clase de destello.
- `consola/web/consola.css`: el destello de `.kmz-listo`, apagado con
  `prefers-reduced-motion`.
- Verificación: `npm test` y QA local de Crea tu KMZ (captura del botón trabajando y
  del aviso con la hora, en escritorio y celular).
