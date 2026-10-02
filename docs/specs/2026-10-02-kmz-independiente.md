# Crea tu KMZ como herramienta propia: "Mis KMZ"

## Problema

"Crea tu KMZ" nació dentro de un master: el KMZ se armaba en las fuentes de un master y
solo servía para ese master. Pero una loteadora puede querer el KMZ de su subdivisión sin
armar un masterplan: para su topógrafo, para Google Earth, para otro sistema, o para
usarlo más adelante. Hoy no puede.

## Decisiones (con el usuario, 2026-10-02)

| Tema | Decisión |
|---|---|
| Qué es | Una herramienta aparte. Un **KMZ** es su propia entidad, con nombre, de una loteadora. |
| Entrada | Botón **"Nuevo KMZ"** a la derecha de "Nuevo master" en *Mis planos*, y también en *Mis KMZ*. |
| Listado | Pantalla propia **"Mis KMZ"**: en curso y terminados. |
| Resultado | **Descargarlo** y **usarlo en un master**. |
| Cobro | Gratis y sin tope de cantidad. Se mantiene "una digitalización a la vez por loteadora" (cada una usa hasta ~5 min de CPU). |
| Lo de hoy | **Se reemplaza.** Se quita "No tengo el KMZ: créalo desde el plano" de Nuevo master y del detalle. En su lugar, un master **elige uno de Mis KMZ** o sube un archivo. |

En producción no hay ningún plano a medias dentro de un master (se revisó el bucket), así
que no hay nada que migrar.

## Diseño

**La entidad.** Tabla nueva `kmzs`: `id`, `cliente_id`, `slug` (único en todo el
sistema), `nombre` (único por cliente), `creado_en`. Que esté terminado se deduce del
disco: existe el `.kmz`. Se borra con su carpeta.

**Dónde vive.** `DATOS/kmz/<slug>/`, con lo mismo que hoy guarda `plano/`: `plano.pdf`,
`paginas/`, `entradas.json`, `digitalizado.json`, `georreferencia.json`, `lotes.geojson`
y `huellas.json`, más el resultado `<slug>.kmz`. La clase `Plano` de `consola/plano.py`
ya trabaja sobre una carpeta: se reusa entera y solo cambia el destino del KMZ.

**Quién ve qué.** Igual que los masters y los diseños: cada loteadora ve los suyos
(`VistaKmz`, filtrada por cliente) y el equipo los ve todos. Uno ajeno da 404.

**Rutas** (todas declaradas en el inventario de `test_app.py`):
- `GET /api/kmz` lista y `POST /api/kmz {nombre}` crea.
- `GET /api/kmz/{slug}` da el estado (el mismo resumen de hoy).
- `PATCH /api/kmz/{slug} {nombre}` renombra y `DELETE /api/kmz/{slug}` borra con su
  carpeta.
- Las mismas acciones de hoy, bajo `/api/kmz/{slug}/...`:
  - `plano` (subir el PDF)
  - `paginas/{n}`
  - `entradas`
  - `digitalizar` (trabajo de fondo)
  - `georreferenciar`
  - `lotes`
  - `crear` (escribe el KMZ)
- `GET /api/kmz/{slug}/descargar` entrega el `.kmz` con un `Content-Disposition` que lleva
  el nombre.
- `POST /api/proyectos/{slug}/kmz {kmz: <slug del KMZ>, confirmar_reemplazo}` copia un KMZ
  de la loteadora a las fuentes del master como `subdivision.kmz`. Usa el mismo flujo de
  reemplazo de hoy: 409 con `existentes` y, al confirmar, el anterior queda como
  `.kmz.anterior`. Solo se pueden usar KMZ propios y terminados.

**Trabajos.** La clave de un trabajo de digitalizar es `kmz:<slug>`, para no chocar con el
slug de un master. La regla de una a la vez por loteadora cuenta construcciones y
digitalizaciones juntas.

**Lo que se retira.**
- Las 8 rutas `/api/proyectos/{slug}/plano/*`.
- El relajo de `Vista.subir` para masters sin KMZ "porque van por el plano".
- `plano` en el JSON del master.
- El botón y la pastilla del detalle, y la opción de Nuevo master.

Construir sin KMZ sigue dando 409, ahora con "falta el KMZ: súbelo o elige uno de Mis KMZ".
La exclusión de la carpeta `plano/` en `pipeline/config.py` se mantiene: es inofensiva y
protege una carpeta vieja si apareciera.

**Pantallas.**
- *Mis planos*: botón "Nuevo KMZ" a la derecha de "Nuevo master".
- *Mis KMZ* (`#/kmz`): tarjetas con nombre, paso en que va (subir, marcar, digitalizar,
  ubicar, crear, listo), cantidad de lotes y fecha. "Nuevo KMZ" pide un nombre y lleva al
  KMZ.
- El KMZ (`#/kmz/<slug>`): la pantalla de 7 pasos de hoy, apuntando a `/api/kmz/{slug}`.
  Al terminar ofrece **Descargar** y **Usar en un master**, que permite elegir un master
  existente o "Nuevo master con este KMZ".
- *Nuevo master*: el KMZ se sube o se **elige de Mis KMZ**, una lista de los terminados.
- *Detalle del master*: "Usar un KMZ de Mis KMZ" junto a subir archivos.
- La navegación gana la pestaña "Mis KMZ".

## Fuera del alcance

- Cobro o topes de cantidad.
- Compartir un KMZ entre loteadoras.
- Editar el KMZ resultante fuera del flujo de 7 pasos.

## Criterios de aceptación

1. Una loteadora crea un KMZ desde *Mis planos* o *Mis KMZ* sin crear un master, lo
   termina y lo descarga. El archivo lo lee `pipeline.kmz.leer_kmz`.
2. Lo usa en un master existente y en uno nuevo. El master se construye con él.
3. No ve ni puede usar los KMZ de otra loteadora (404). El equipo los ve todos.
4. Ya no existen las rutas ni las opciones del flujo dentro del master.
5. `pytest`, `node --test` y la regresión de `pipeline.plano` pasan, y el inventario de
   rutas está declarado.
