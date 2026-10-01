# Plan: Crea tu KMZ

Spec: `docs/specs/2026-10-01-crea-tu-kmz.md`. Rama: `cc/crea-tu-kmz`.
Pruebas: `python -m pytest -q` y `node --test web/js/*.test.js consola/web/*.test.js`.

Referencias de las pruebas de concepto. Viven fuera del repo, en el scratchpad de la
sesión que las hizo, y se citan para portarlas, no para importarlas:
- `scratchpad/poc_kmz/`: El Arrayán.
  - `p2_segmentar.py`: segmentación.
  - `p5_red_v2.py`: red de deslindes.
  - `medir.py`: métricas.
  - `resultados.md`.
- `scratchpad/ronda3_ciega/`: el método generalizado a tinta negra, foto y cuadrícula.
  - `pipeline_ciego.py`, `cuadricula.py`, `entradas.py` (entradas por plano).
  - `congelado.md` (parámetros globales).
- `scratchpad/ronda3_evaluacion/`: cómo se arman los lotes reales a partir de KMZ de
  líneas.
  - `reales.py`, `medir_r3.py`, `evaluacion.md`.

## Tarea 1: prueba de lectura de rótulos (decisión)

- En `trabajo_crea_kmz/rotulos/` (carpeta de trabajo; los datos de los planos no van a
  git), medir sobre los 5 planos del set cuántos números de lote se leen bien y con qué
  error de posición:
  - Tesseract, si se puede correr localmente, por ejemplo en un contenedor Docker con
    tesseract-ocr.
  - Un modelo de visión (Claude), **solo si el usuario entrega una API key**: se le
    pregunta antes, porque tiene costo.
- Medir también la lectura de las marcas de cuadrícula de Algarrobo y del cuadro de
  superficies de un plano.
- Entregable: `docs/specs/2026-10-01-crea-tu-kmz-rotulos.md` con la tabla de aciertos y la
  decisión. La interfaz del lector queda fija: `leer(imagen) -> [Rotulo(numero, x, y,
  confianza)]`.

## Tarea 2: el núcleo de digitalización (`pipeline/plano/`)

- `pagina.py`: extraer la imagen embebida de cada página (pymupdf), rotar, recortar y
  rectificar la perspectiva a partir de 4 esquinas.
- `tinta.py`: máscara de deslindes para tinta roja y negra. Descarta verde, azul,
  achurados y la cuadrícula. Aplica los rectángulos de máscara.
- `particion.py`: regiones cerradas con semillas (rótulos), red plana de deslindes,
  aristas enderezadas, polígonos desde las caras (shapely), sin traslapes ni huecos.
- `__main__`/CLI `python -m pipeline.plano digitalizar <carpeta-plano>`: lee
  `entradas.json`, escribe `digitalizado.json` e imprime el avance por línea (lo muestra
  la consola).
- Dependencias: `pymupdf` y `opencv-python-headless` en `requirements.txt`.
- Pruebas con imágenes sintéticas: una grilla de lotes dibujada con huecos, texto encima y
  líneas dobles de camino. La salida tiene el número de lotes esperado, comparte aristas y
  no tiene traslapes ni huecos.
- Los parámetros globales salen de `congelado.md` de la ronda 3, sin ajuste por plano.

## Tarea 3: georreferencia y KMZ (`pipeline/plano/`)

- `georreferencia.py`:
  - Similitud por mínimos cuadrados con residuo por ancla y marca de las anclas atípicas.
  - Ajuste a cuadrícula a partir de las marcas leídas: WGS84 UTM 19S, con PSAD56 como
    alternativa.
  - Traslación de ajuste fino.
  - El huso se elige desde las anclas o la cuadrícula; no queda fijo en 19.
- `salida.py`: escribe el KMZ como dice el spec (un Polygon por lote, `LOTE <n>`, KML
  2.2) y calcula las áreas.
- CLI `python -m pipeline.plano georreferenciar <carpeta>` y `... kmz <carpeta>
  <destino.kmz>`.
- Pruebas:
  - Transformaciones conocidas: se recuperan escala, rotación y traslación, y un ancla
    perturbada queda marcada.
  - El KMZ generado lo lee `pipeline.kmz.leer_kmz` con ids únicos.

## Tarea 4: set de regresión (`pipeline/plano/regresion.py`)

- Portar `medir.py`/`medir_r3.py`, incluido armar los lotes reales desde KMZ de líneas
  (polygonize más rótulos).
- `regresion/` en `.gitignore`. Se copian ahí los 5 planos, sus KMZ reales (4: Hidango no
  tiene) y un `entradas.json` por plano, traducido de las entradas de la ronda 3: página,
  rotación, rectángulos, anclas, esquinas y las semillas leídas a ojo como "números
  corregidos".
- `python -m pipeline.plano.regresion [--plano X]` corre digitalizar, georreferenciar y
  kmz, y luego mide. Imprime la tabla, la compara con `regresion/linea_base.json` y sale
  con código distinto de 0 si un plano empeora más que la tolerancia.
- Cuando no está la carpeta, las pruebas de pytest la saltan.
- La línea base son los números de la ronda 3 y de El Arrayán v2. Si la versión portada da
  distinto, se investiga antes de aceptar la diferencia.

## Tarea 5: lector de rótulos (según la decisión de la tarea 1)

- `pipeline/plano/rotulos.py` con el lector elegido, detrás de la interfaz fija.
- Si es OCR: `tesseract-ocr` va en el Dockerfile.
- Si es el modelo de visión: la API key va en Secret Manager y el lector se activa solo si
  la key está.
- Si se pudo, leer las áreas oficiales y las marcas de la cuadrícula.
- Integrarlo a `digitalizar`: los rótulos leídos son las semillas y los números corregidos
  por la loteadora tienen prioridad.
- La regresión también se corre "con lector" y no solo con las semillas manuales, y se
  reporta cuánto empeora.

## Tarea 6: la consola, backend

- Rutas en `consola/app.py`, todas `AJENO_404` y declaradas en el inventario de
  `test_app.py`:
  - `POST /api/proyectos/{slug}/plano`: subir el PDF y extraer las páginas.
  - `GET .../plano`: estado y entradas.
  - `GET .../plano/paginas/{n}`: la imagen.
  - `PUT .../plano/entradas`: guardar las entradas.
  - `POST .../plano/digitalizar`: trabajo de fondo.
  - `GET .../plano/lotes`: GeoJSON en píxeles y, si está ubicado, en lat/lon, con el error
    de área.
  - `POST .../plano/georreferenciar`: devuelve los residuos por ancla.
  - `POST .../plano/kmz`: crea `subdivision.kmz` en las fuentes. Pide confirmar si ya
    había un KMZ y renombra el anterior a `.kmz.anterior`.
- `Comandos.digitalizar(...)` y los trabajos con `Trabajos.lanzar`, igual que construir
  (una a la vez por loteadora).
- Escrituras en `/datos` sin `copystat` (gcsfuse).
- Un master se puede crear sin KMZ cuando va por el plano. `Vista.subir` exige KMZ: se
  relaja solo para el flujo de plano y construir sigue exigiéndolo.
- Pruebas: de rutas, con `ComandosDePrueba` (que suma el método nuevo), y de permisos (un
  plano ajeno da 404).

## Tarea 7: la consola, pantalla

- Pantalla `#/planos/<slug>/kmz` (sección en `index.html`, entrada en `PANTALLAS`, rama
  en `ruta()`, módulos nuevos en `MODULOS`):
  1. Subir el PDF y elegir página y rotación.
  2. Marcar el rectángulo del dibujo, las máscaras y las esquinas si es foto (canvas con
     zoom y arrastre).
  3. Digitalizar, con avance en vivo.
  4. Numerar: clic en un lote para escribir su número.
  5. Ubicar: plano y mapa lado a lado, pares de puntos, tabla de residuos, quitar o
     rehacer, y arrastre del ajuste fino. Si hay cuadrícula, se ofrece usarla.
  6. Revisar: lotes coloreados por error de área sobre Esri.
  7. Crear el KMZ.
- Leaflet se sirve con `MODULOS_DEL_VISOR` o una ruta de vendor. Teselas de Esri.
- "Nuevo master" ofrece "No tengo el KMZ: créalo desde el plano", que crea el master y
  lleva a la pantalla.
- `consola.test.js`: los ids y `data-accion` nuevos existen en el HTML.

## Tarea 8: despliegue y documentación

- `requirements.txt` y Dockerfile con lo que haya decidido la tarea 5. La imagen se
  construye local (`docker build`) para verificar que importa `cv2` y `fitz`.
- README: sección "Crea tu KMZ" (el flujo, el set de regresión, cómo correrlo) y la
  estructura de `pipeline/plano/`.
- Correr completos `pytest`, `node --test` y la regresión.
