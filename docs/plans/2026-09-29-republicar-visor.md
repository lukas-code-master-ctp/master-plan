# Plan: republicar los loteos con el visor nuevo

Spec: `docs/specs/2026-09-29-republicar-visor.md`. Rama: `cc/republicar-visor`.
Pruebas: `python -m pytest -q` y `node --test web/js/*.test.js consola/web/*.test.js`.

## Tarea 1: el visor como pieza propia en el pipeline

- Nuevo `pipeline/visor.py`:
  - `IGNORAR` (los patrones de hoy), `copiar(sitio: Path)` (lo que hace hoy
    `_copiar_plantilla_web`) y `huella(origen: Path = config.PLANTILLA_WEB) -> str`
    (SHA-256 de rutas relativas ordenadas + bytes, saltando lo ignorado).
  - `python -m pipeline.visor --sitio <carpeta>`: exige `<sitio>/datos/parcelas.json`
    (si no, sale con código ≠ 0 y un mensaje), copia e imprime la huella.
- `pipeline/construir.py` usa `visor.copiar` en vez de `_copiar_plantilla_web`.
- Pruebas en `pipeline/tests/test_visor.py`: la huella cambia al cambiar un archivo,
  no cambia con `*.test.js` ni `datos/`; `copiar` no pisa `datos/`; el CLI falla en un
  sitio sin construir.

## Tarea 2: la base recuerda con qué visor se publicó

- `consola/datos.py`: columna `visor_publicado` (String(64), nula) en `proyectos`;
  `_migrar` la agrega si falta; `ProyectoGuardado.visor_publicado`;
  `Base.anotar_visor(slug, huella)`.
- `consola/proyectos.py`: `Proyecto` expone `visor_publicado`; `Vista.anotar_visor`;
  `Registro.todos()` devuelve una `Vista` sin filtro para uso interno (no ligada a
  sesión).
- Pruebas: migración sobre una base sin la columna; anotar y leer la huella.

## Tarea 3: el recorrido al arrancar

- `consola/comandos.py`: `Comandos.actualizar_visor(proyecto, vercel_proyecto)` =
  `encadenar(python -m pipeline.visor --sitio …, publicar.sh … sin --crear)`.
- `consola/trabajos.py`: `Trabajos.esperar(id, tope=None)` (bloquea hasta terminado).
- Nuevo `consola/republicar.py`: `pendientes(vista, huella)` y
  `republicar(vista, trabajos, comandos, disenos, huella, avisar=print)`, según el
  spec (uno a la vez, salta los que tienen trabajo corriendo, un fallo no detiene).
- `consola/app.py`:
  - `_anotar_publicacion` anota también la huella actual.
  - En `crear_app`, parámetro `republicar_al_arrancar: bool | None = None` (None = lee
    `CONSOLA_REPUBLICAR_AL_ARRANCAR == "1"`); si es verdadero, al arrancar la app
    (evento de inicio de FastAPI) lanza `republicar` en un hilo daemon.
- Pruebas en `consola/tests/test_republicar.py` con comandos falsos (como los de
  `test_app.py`): cubre los criterios 2–5 del spec. La prueba del inventario de rutas
  sigue pasando sin cambios.

## Tarea 4: despliegue y documentación

- `cloudbuild.yaml`: agregar `CONSOLA_REPUBLICAR_AL_ARRANCAR=1` a `--set-env-vars`.
- README: sección "Despliegue continuo": el trigger de Cloud Build sobre `main` y la
  actualización automática de los loteos (qué hace, qué no, cómo ver el log).

## Tarea 5 (infra, fuera del repo): trigger de Cloud Build

- El usuario conecta el repo de GitHub a Cloud Build en la consola web de GCP
  (instalar la app de GitHub; es OAuth en el navegador).
- Crear el trigger `consola-main`: rama `^main$`, config `cloudbuild.yaml`, región
  `southamerica-east1`, cuenta de servicio de compute (ya tiene los roles).
