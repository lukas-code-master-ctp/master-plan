# Plan: Mis KMZ, Crea tu KMZ como herramienta propia

Spec: `docs/specs/2026-10-02-kmz-independiente.md`. Rama: `cc/kmz-independiente`.
Pruebas: `python -m pytest -q`, `node --test web/js/*.test.js consola/web/*.test.js`,
`python -m pipeline.plano.regresion`.

## Tarea 1: la entidad KMZ en el backend

- `consola/datos.py`: tabla `kmzs` (create_all la crea en bases existentes) con sus
  métodos de alta, lista, renombre y baja. Slug único global (como el de los masters) y
  nombre único por cliente.
- `consola/kmzs.py`: `RegistroKmz`/`VistaKmz`, filtrados por cliente y con el equipo
  viendo todo. Carpeta `config.DATOS / "kmz" / <slug>`. `plano(slug)` devuelve un
  `Plano` sobre esa carpeta.
- `consola/plano.py`: el destino del KMZ pasa a ser un parámetro. Para un KMZ propio es
  `<carpeta>/<slug>.kmz`, sin flujo de reemplazo porque es su propio archivo.
- Rutas `/api/kmz…` en `app.py` según el spec, incluida `descargar`. Los trabajos de
  digitalizar van con la clave `kmz:<slug>`. La regla de una a la vez por loteadora
  cuenta construcciones y digitalizaciones.
- Pruebas en `consola/tests/test_kmz.py`, con las de `test_plano.py` como base:
  - crear, listar, renombrar y borrar;
  - todo el flujo con el plano sintético;
  - descargar;
  - un KMZ ajeno da 404;
  - el equipo ve todos;
  - un nombre repetido da 409.
- Inventario de rutas.

## Tarea 2: usar un KMZ en un master y retirar el flujo dentro del master

- `POST /api/proyectos/{slug}/kmz {kmz, confirmar_reemplazo}`: copia el KMZ terminado
  y propio a las fuentes como `subdivision.kmz`, con el mismo flujo de reemplazo
  (`.kmz.anterior`). Copia segura para gcsfuse: temporal más `os.replace`, sin copystat.
- Se retiran:
  - las 8 rutas `/api/proyectos/{slug}/plano/*`;
  - `Vista.plano` y el relajo de `Vista.subir`;
  - `plano` en el JSON del master;
  - el mensaje de construir, que pasa a "súbelo o elige uno de Mis KMZ".
- `test_plano.py` se convierte o se reparte en `test_kmz.py`. Se agregan pruebas de usar
  un KMZ (propio, ajeno → 404, sin terminar → 409, reemplazo).

## Tarea 3: las pantallas

- Pestaña "Mis KMZ" en la navegación y pantalla `#/kmz` con la lista.
- "Nuevo KMZ" en *Mis planos*, a la derecha de "Nuevo master", y en *Mis KMZ*: diálogo
  con el nombre, luego `#/kmz/<slug>`.
- `kmz.js` apunta a `/api/kmz/{slug}` en vez de `/api/proyectos/{slug}/plano`. Paso 7:
  Descargar y "Usar en un master", con un diálogo para elegir un master existente o "Nuevo
  master con este KMZ".
- *Nuevo master*: se quita "No tengo el KMZ". El campo KMZ ofrece subir o "Elegir de Mis
  KMZ", con la lista de terminados. Al crear, se llama a la ruta de la tarea 2.
- *Detalle*: "Usar un KMZ de Mis KMZ". Se quitan el botón y la pastilla del plano.
- `consola.test.js` y `kmz.test.js` al día (ids, `data-accion`, rutas hash).

## Tarea 4: documentación y verificación

- README: la sección "Crea tu KMZ" pasa a describir Mis KMZ (dónde vive, rutas, usar en
  un master). Se actualiza el árbol de archivos.
- Verificación completa: pytest, node, regresión y la consola local de punta a punta en
  el navegador (crear un KMZ, descargarlo, usarlo en un master nuevo).
