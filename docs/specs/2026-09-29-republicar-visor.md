# Despliegue continuo: la consola con cada merge, y los loteos con el visor nuevo

## Problema

Hoy, mergear a `main` no cambia nada en línea:

1. La consola en Cloud Run (proyecto GCP `tumasterplan`) solo se actualiza si alguien
   corre `gcloud builds submit` a mano.
2. Cada loteo publicado en Vercel lleva **su propia copia del visor** (`web/`), hecha
   al construirlo. Un arreglo del visor mergeado no llega a ningún loteo ya publicado
   hasta que alguien lo reconstruya y lo republique, uno por uno.

Los datos de los loteos (vuelos, sitios construidos) viven en el bucket montado en la
consola, no en el repo: lo segundo no puede correr en GitHub, tiene que correr en la
consola.

## Decisiones

| Tema | Decisión | Descartado y por qué |
|---|---|---|
| Deploy de la consola | Trigger de Cloud Build sobre `main` que corre el `cloudbuild.yaml` existente (igual que el CRM) | GitHub Actions: pide una llave de servicio de GCP en GitHub |
| Qué se hace con cada loteo | **Actualizar el visor**: copiar `web/` sobre el sitio ya construido, reescribir el diseño y republicar | Reconstruir completo: minutos de CPU por loteo, una instancia, y lo que cambia con un merge es casi siempre el visor |
| Cuándo | **Automático al arrancar la consola**, comparando una huella del visor | Botón manual: el usuario prefiere automático |
| Cuáles | **Solo los ya publicados** (con `url_publicada`) | Todos los pagados: pondría en línea loteos que hoy no lo están |

## Diseño

**Huella del visor.** Un SHA-256 del contenido de `web/` (rutas + bytes), con los
mismos archivos que ignora la copia al construir (`datos`, `panoramas`, `*.test.js`,
`.DS_Store`). Un deploy que no toca `web/` deja la misma huella y no republica nada.

**Lo que se guarda.** Columna nueva `proyectos.visor_publicado` (texto, nulo): la huella
del visor con que quedó publicado cada loteo. Se agrega en `_migrar`, idempotente. La
escribe tanto la publicación normal como la actualización automática.

**El gancho al arrancar.** Con `CONSOLA_REPUBLICAR_AL_ARRANCAR=1` (solo lo pone el
`cloudbuild.yaml`; en el computador y en las pruebas no está), la consola, al arrancar,
lanza en un hilo de fondo el recorrido:

- Pendientes = loteos con `url_publicada`, pagados, construidos, y con
  `visor_publicado` distinto de la huella actual (incluye nulo).
- Uno a la vez, en orden por slug. Para cada uno:
  1. Si ya hay un trabajo corriendo en ese loteo, se salta (se retoma en el próximo
     arranque).
  2. Escribe el diseño en el sitio (`disenos.escribir_en_sitio`).
  3. Lanza un trabajo `actualizar-visor` por `Trabajos` (así queda el bloqueo por
     loteo y el registro de líneas): `python -m pipeline.visor --sitio <sitio>` y
     `publicar.sh <sitio> <vercel_proyecto>` **sin `--crear`**, encadenados.
  4. Espera a que termine. Si salió bien, anota la URL real (de `publicacion.json`) y
     la huella. Si falló, lo deja sin anotar y sigue con el siguiente.
- Cada paso se escribe en el log del proceso (`print` con prefijo `[republicar]`),
  que en Cloud Run va a Cloud Logging.

**Por qué es seguro con arranques en frío.** Cloud Run tiene `min-instances=0`: la
consola arranca muchas veces sin que haya deploy. En esos arranques la huella coincide
con la guardada y no hay pendientes: el costo es hashear `web/` (menos de 1 MB). Si la
instancia se recicla a mitad de camino, los loteos ya hechos quedaron anotados y el
próximo arranque sigue con los que faltan.

**Lo que no hace.** No reconstruye datos ni imágenes, no publica loteos nunca
publicados, no crea proyectos en Vercel (sin `--crear`: si el proyecto no existe, el
loteo falla y se ve en el log), y no tiene pantalla: el estado se ve en los logs.

## Fuera de alcance

- Botón o pantalla de estado en el back office.
- Reconstrucción completa automática cuando cambia el pipeline.
- Borrar del sitio archivos del visor que ya no existen en `web/` (la copia es
  `dirs_exist_ok`, igual que hoy al construir).

## Criterios de aceptación

1. `python -m pytest -q` y `node --test web/js/*.test.js consola/web/*.test.js` pasan.
2. Con la variable apagada, arrancar la consola no lanza nada.
3. Con la variable encendida, un loteo publicado con huella vieja se actualiza y queda
   con la huella nueva; uno con la huella al día, uno sin publicar, uno sin pagar y uno
   con trabajo en curso no se tocan.
4. Publicar a mano anota la huella.
5. Un fallo en un loteo no detiene a los demás.
6. El inventario de rutas no cambia (no hay rutas nuevas).
