# Plan: Crea tu KMZ para un usuario promedio, sprint 2

Spec: `docs/specs/2026-10-07-kmz-prueba-usuario-sprint2.md`. Un commit por tarea, con
`(tarea N)` al final; cada tarea la revisa otro agente antes de la siguiente. Banco: el KMZ
`parcelas-coipue-lote-8` del QA local (Rapel) y las entradas de
`/mnt/project-files/prueba-usuario-kmz/sprint1/entradas-rapel-sprint1.json`.

## Tarea 1: ubicar con un punto en el servidor

- `pipeline/plano/georreferencia.py`: `escala_del_cuadro(digitalizado)` (m/px por la mediana
  de `area_oficial / area_px`), `por_punto(ubicacion, escala_m_px, homografia)` y el orden
  cuadrícula → puntos (≥2) → `ubicacion` en `georreferenciar`. `metodo="punto"`, aviso sin
  jerga.
- `pipeline/plano/digitalizar.py` (`leer_entradas`): validar `ubicacion` (números finitos,
  giro en −180..180, `escala_impresa` entero positivo opcional).
- `consola/plano.py`: `ubicacion` en `CLAVES_UBICAR`, el estado expone `escala_m_px` del
  cuadro (o `null`) para la vista previa del navegador, y "Ubicar" habilitado con
  `ubicacion` completa.
- Pruebas: `pipeline/tests/test_plano_georref.py` (un loteo sintético girado 90° y ubicado
  con un punto calza con su posición real; escala impresa; sin cuadro ni escala da error) y
  `consola/tests/test_plano.py`.

## Tarea 2: Ubicar con un punto en pantalla

- `kmz_geometria.js`: `similitudPorPunto({x, y, lon, lat, giro}, escala_m_px)` y la
  proyección local metros ↔ lon/lat alrededor del punto para la vista previa; pruebas.
- `kmz.js`, `mapa_kmz.js`, `index.html`, `consola.css`: alfiler en la coordenada, clic en el
  plano para el punto, plano girado con el giro, lotes en vista previa, control de giro
  (±1°, ±15°, deslizador), arrastre de los lotes (ajuste fino), campo de escala impresa sin
  cuadro, guardado en `entradas.ubicacion` y `georreferenciar` al soltar.
- `mapa_kmz.js`: `maxNativeZoom` 18.

## Tarea 3: afinar con puntos

- La tabla de puntos plegada bajo "Afinar con puntos" (abierta si ya hay puntos).
- Vista previa de los lotes desde el segundo punto (similitud de mínimos cuadrados en el
  navegador, la misma de `por_anclas`); pruebas de la similitud en `kmz.test.js`.

## Tarea 4: ajustar el tamaño con el cuadro

- `georreferencia.py`: con `entradas.escala_cuadro` y método puntos, reescalar la similitud
  al tamaño del cuadro en torno al centroide de los puntos; validación y huella.
- `kmz.js`: botón "Ajustar el tamaño con el cuadro" en Revisar y en el semáforo cuando hay
  sesgo; "Deshacer el ajuste" si está puesto.
- Pruebas en `pipeline/tests/` y `consola/tests/`.

## Tarea 5: cuatro pasos visibles

- `index.html`, `kmz.js`, `consola.css`: pastillas Subir · Marcar · Ubicar · Revisar y
  descargar; Numerar intermedio sin pastilla; Revisar y Crear en un panel; rutas viejas como
  alias; "Seguir" de Marcar va a Numerar solo si hace falta (`hayQueNumerar(plano, rasgos)`
  en `kmz_geometria.js`, con prueba).
- Celular: los 4 pasos en una fila.

## Tarea 6: lectura de 8-09 y "partes chicas"

- `pipeline/plano/particion.py`: causa del corte de 8-09 con las entradas del QA y arreglo,
  con prueba; `de_lote` para caras ≥ 0,4 × la mediana.
- Banco de Rapel: 8-09 y 8-16 como lotes en la primera lectura, áreas parejas.

## Cierre

`npm test`, QA local recorriendo los 4 pasos con la coordenada de la prueba
(34°10'37.52"S 71°32'53.89"W) en escritorio y celular, capturas en
`/mnt/project-files/prueba-usuario-kmz/sprint2/`, PR a `main` e informe.
