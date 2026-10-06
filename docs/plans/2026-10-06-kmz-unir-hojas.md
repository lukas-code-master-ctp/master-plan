# Plan: unir las hojas de un plano en Crea tu KMZ

Spec: `docs/specs/2026-10-06-kmz-unir-hojas.md`.

Banco de prueba real: el PDF de Constitución (3 hojas, 5,906 px/mm) en el scratchpad
del hilo; no va a git. Los tests usan planos sintéticos.

## Tarea 1: geometría y composición de la unión

- `pipeline/plano/union.py` (nuevo):
  - `Hoja` (n, rotacion, angulo, x, y, recorte) y `leer(dic) -> Union` con las
    validaciones del spec (sin conocer el PDF: total de páginas y tamaños se pasan).
  - `geometria(hojas, tamanos, ppmms) -> Geometria`: por hoja la matriz 3×3 px de hoja
    girada → px de unión, `ancho`, `alto`, `ppmm`, y `huella(union)`.
  - `componer(imagenes, geometria, papel=None) -> np.ndarray`: pinta en orden, cada hoja
    solo en su recorte, warp por la caja de cada hoja.
  - `componer_desde_pdf(pdf, union) -> (imagen, ppmm)`.
  - Tope `MAX_MEGAPIXELES = 250`.
- `pipeline/tests/test_plano_union.py`: un plano sintético partido en 2 o 3 hojas
  traslapadas (con giros de 90° y un giro fino) se recompone igual al original
  (diferencia media baja en el dibujo); orden de capas; recorte; validaciones.
- Verificación: los tests nuevos y `pytest -q pipeline/tests`.

## Tarea 2: afinar la alineación

- `union.afinar(imagenes, ppmms, hojas) -> list[dict]`: ORB + RANSAC rígido a 2 px/mm
  en el traslape agrandado 40 mm, luego ECC euclídeo a 4 px/mm; topes de 30 puntos,
  60 mm y 5°; `calzada` y `residuo_mm` por hoja.
- Tests: hojas sintéticas desplazadas 10–40 mm y giradas 1–2° vuelven a su lugar con
  error bajo 1 px; una hoja sin traslape queda igual con `calzada: false`.
- Medición con Constitución (script en el scratchpad): residuo tras afinar.

## Tarea 3: digitalizar sobre la unión

- `pipeline/plano/digitalizar.py`: `leer_entradas` acepta `union` (pagina 0 ⇔ union,
  rotacion 0) y la valida con `union.leer`; `digitalizar` compone la página con
  `componer_desde_pdf` cuando `pagina == 0`; `digitalizado.pagina.union` lleva la
  huella; `_previo` la compara; `huella_lector` incluye `union`; el lector lee
  `union.cuadro` de su hoja original y no lo usa como máscara.
- `consola/plano.py`: `"union"` en `CLAVES_DIGITALIZAR`.
- Tests: digitalizar un PDF sintético de 2 hojas unido da los mismos lotes que la
  página entera; cambiar la unión deja atrasado lo digitalizado.

## Tarea 4: la consola sirve y guarda la unión

- `consola/plano.py`: miniatura media (`<n>_medio.jpg`, 2.400 px) al subir y a pedido;
  imagen de la unión en caché por huella (reducida si pasa de 60 MP); `estado.union`;
  `guardar_entradas` valida la unión contra las páginas y el tope de megapíxeles, y el
  cuadro de la unión dentro de su hoja; `afinar_union(hojas)`.
- `consola/app.py`: `?medio=1` en `GET /api/kmz/{slug}/paginas/{n}`, la página 0, y
  `POST /api/kmz/{slug}/union/afinar` (en el inventario de `test_app.py`, ajeno → 404).
- Tests en `consola/tests/test_plano.py` / `test_kmz.py`.

## Tarea 5: el editor de la unión

- `consola/web/js/kmz_union.js` (nuevo): funciones puras de geometría (las mismas
  fórmulas que `union.py`: hoja → unión, caja, origen, punto en hoja) y el editor:
  `LienzoUnion` sobre el canvas del paso 1 (elegir, arrastrar semitransparente, recortar
  con manillas, zoom y pellizco), panel con Usar / giro 90° / giro fino / Recortar /
  Subir-Bajar / Afinar / Usar la unión / Volver a una sola página.
- `consola/web/index.html` y `consola/web/consola.css`: el panel del editor y el botón
  "El loteo está en varias hojas: unirlas".
- `consola/web/kmz_union.test.js`: la geometría JS coincide con casos calculados en
  Python (los mismos números en los dos tests).

## Tarea 6: el resto del flujo con la unión

- `consola/web/js/kmz.js`: `paginaActual()` con la página 0 (miniatura "Hojas unidas",
  tamaño de `estado.union`); al guardar o quitar la unión, el mismo `confirm` y limpieza
  que al cambiar de página; en Marcar, el cuadro pide la hoja y muestra la hoja original;
  la lista dice "(hoja n)"; el aviso de "calzan" de Revisar compara también la unión.
- `consola/web/js/lienzo_plano.js`: dibujar una imagen más chica estirada a los px de
  página.
- Docs: README (Crea tu KMZ) con la unión de hojas.
- Verificación: `npm test` completo y QA local con el PDF de Constitución subido en la
  app (escritorio y celular).
