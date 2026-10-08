# Plan: la lectura del plano se retoma si se cae la instancia

Spec: `docs/specs/2026-10-08-lectura-retomable.md`. Un commit por tarea, con `(tarea N)` al
final. Cada tarea la revisa otro agente antes de pasar a la siguiente.

## Tarea 1: el lector guarda y retoma su avance por pasada

- `pipeline/plano/rotulos.py`:
  - `_correr` acepta `al_completar(pasada, lecturas)`, que se llama cuando una pasada
    termina entera y sin teselas malas.
  - `leer(…, avance_en=None)`: carga las pasadas guardadas (nombre estable por escala
    0/1, variante y ángulo), las salta en el sondeo y en el resto, y escribe cada pasada
    nueva con una escritura atómica. Avisa "Rótulos: se retoman N pasadas ya leídas".
    Las lecturas se guardan como JSON (floats y str de Python).
- `pipeline/plano/digitalizar.py` (`_leer_rotulos`): `avance_en=carpeta/"lector-avance"/huella`.
  Las otras huellas se borran al empezar y `lector-avance/` entera después de escribir
  `digitalizado.json`.
- Pruebas (`pipeline/tests/`): con un Tesseract falso, una lectura cortada a mitad y
  retomada da los mismos rótulos que una de corrido y no repite pasadas; un archivo roto se
  vuelve a leer; una pasada con una tesela mala no se guarda; digitalizar borra el avance
  al terminar.

## Tarea 2: la consola retoma la lectura al arrancar

- `consola/app.py`: sacar el lanzamiento de `digitalizar_kmz` a una función que escribe
  `lectura.json` (`intento`) y lo borra al terminar, encadenada con `anotar`. Un lifespan que
  siempre corre `retomar_lecturas` (y además republica si `republicar_al_arrancar`).
- `retomar_lecturas`: recorre los KMZ de la base. Con `lectura.json` e `intento < 3`,
  relanza con la línea "Se retoma la lectura del plano donde quedó (intento N de 3)."; si no,
  o si el plano ya no se puede digitalizar, borra el archivo. Nunca bota el arranque.
- `Trabajos.lanzar` acepta líneas iniciales.
- Pruebas (`consola/tests/`): lanzar escribe y terminar borra `lectura.json`; al arrancar
  con un `lectura.json` se relanza con intento 2 y la línea; con intento 3 no se relanza y
  se borra; un KMZ sin PDF se salta; el inventario de rutas no cambia.

## Tarea 3: la pantalla sigue al trabajo retomado

- `consola/web/js/sondeo.js`: aguantar ~1 minuto de errores pasajeros (más intentos, espera
  con tope).
- `consola/web/js/plano.js` (`seguir`): ante 'interrumpido' de una clave `kmz:`, pedir
  `GET /api/kmz/<slug>`. Si trae otro trabajo corriendo, seguirlo con `desde = 0` y las
  líneas ya mostradas. `seguir` recibe `desde` explícito.
- Pruebas en `consola/web/sondeo.test.js` (la decisión de relevo, pura).

## Verificación y QA

- `npm test` completo.
- QA local con `npm run qa:levantar`: lanzar una lectura en un KMZ sembrado y matar la
  consola a mitad (`npm run qa:bajar` o un kill). Levantarla con `--conservar` y ver que la
  pantalla, sin recargar, sigue con "Se retoma…" desde la pasada en que iba y termina.
  Repetirlo con la pestaña cerrada y volviendo después. Capturas en escritorio y celular.
