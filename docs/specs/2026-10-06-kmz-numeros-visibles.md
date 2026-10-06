# Números de lote visibles en el KMZ de Crea tu KMZ

## Problema

Al abrir en Google Earth el KMZ que escribe Crea tu KMZ se ven los polígonos rojos,
pero no el número de cada lote. Cada lote es un Placemark con nombre `LOTE <n>` y solo
un `Polygon`, y Google Earth no rotula polígonos en el mapa: el nombre aparece solo en
la lista de lugares. Para que el rótulo se vea en el mapa el Placemark necesita un
`Point`.

## Solución

- Cada Placemark pasa a ser un `MultiGeometry` con un `Point` dentro del lote (el
  `representative_point` de shapely, que siempre cae dentro, también con huecos o en
  forma de L) y el `Polygon` de siempre.
- El estilo `#lote` suma un `IconStyle` con escala 0 (sin chincheta encima de cada
  lote) y un `LabelStyle` blanco, legible sobre el satélite.
- El rótulo es el nombre del Placemark, `LOTE <n>`, igual que en la lista. No se
  cambia el nombre: `pipeline/kmz.py` saca el id de ahí.

## Compatibilidad

- `pipeline/kmz.py` sigue leyendo el KMZ en modo polígonos (el modo líneas lo decide
  solo la presencia de `LineString`). El `Point` se lee como etiqueta, pero los
  polígonos ya traen su id del nombre y la etiqueta no se asigna a nada.
- Los KMZ creados antes no cambian solos: se rehacen con "Crear el KMZ de nuevo".
  Los masters que ya usan uno tampoco cambian; el visor no usa los rótulos del KMZ.

## Fuera de alcance

- Rotular solo el número (sin "LOTE"), tamaño del rótulo según el zoom.
- Que "Crear el KMZ de nuevo" se desactive cuando no hay cambios.
