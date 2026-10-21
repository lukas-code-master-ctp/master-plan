# Plan: unir dos partes de un mismo lote en Numerar

Spec: `docs/specs/2026-10-20-kmz-unir-partes.md`. Un commit por tarea, con `(tarea N)` al
final. Cada tarea la revisa otro agente antes de pasar a la siguiente.

## Tarea 1: el digitalizador aplica las uniones

- `pipeline/plano/digitalizar.py`:
  - `leer_entradas`: valida `uniones` como `fuera`: lista de `{numero, x, y}` (número no
    vacío, pasado a str; x, y con `numeros`). Sin la clave o vacía, `salida["uniones"] = []`.
  - `unir_partes(lotes, sin_numero, sin_numero_lote, origen, uniones, ppmm)` pura, sobre
    polígonos en px de página: por cada unión, en orden, la cara que contiene su punto (una
    de `sin_numero`, o un lote distinto de `numero` cuyo `origen` es `"lector"`; nunca un
    lote de la loteadora). Se une si el lote `numero` existe y comparten un borde de al menos
    1 mm de papel (`lote.buffer(tol).intersection(cara.boundary).length`, tol ≈ 0,25 mm). El
    resultado es `unary_union`; si sale MultiPolygon por diferencias de coma flotante, se
    cierra con un buffer chico (+tol/−tol) y, si sigue partido, no se une. Devuelve las
    estructuras nuevas, las uniones aplicadas por número y los números descartados.
  - En `digitalizar`, justo después de `digitalizar_imagen` y antes de `_sugerencias` y de los
    huecos, aplica `unir_partes` sobre `r.lotes` / `r.sin_numero` / `r.sin_numero_lote` (y
    mantiene coherente `r.lotes_trabajo` si algo lo usa después). Cada lote lleva
    `partes: [[x, y], ...]` (los puntos de las uniones aplicadas; `[]` si ninguna) y
    `digitalizado.json` lleva `uniones_descartadas: ["17"]`. Una línea de avance cuando se
    une algo o se descarta.
  - El docstring del módulo documenta `uniones`, `lotes[].partes` y `uniones_descartadas`.
- Pruebas en `pipeline/tests/` (con polígonos a mano, sin imagen): une una cara sin número
  que comparte borde; no une si solo toca un vértice o no toca; absorbe un lote del lector
  y no uno de la loteadora; dos partes encadenadas al mismo lote; descarta si el lote no
  existe o el punto no cae en nada; `leer_entradas` valida y normaliza `uniones`.

## Tarea 2: la consola guarda y muestra las uniones

- `consola/plano.py`:
  - `uniones` entra en `CLAVES_DIGITALIZAR`, pero en `huella_digitalizar` solo cuenta si no
    está vacía (como `union`): las entradas de antes conservan su huella.
  - `TOPES` con `uniones=200`.
  - `lotes()`: cada lote lleva `unidas` = cuántas partes se le unieron (`len(partes)`).
  - El resumen `digitalizado` lleva `uniones_descartadas`.
- Pruebas en `consola/tests/test_plano.py` (o `test_kmz.py`, donde vivan las de huellas y
  topes): unas entradas sin `uniones` tienen la misma huella que antes; agregar una unión
  deja atrasada la digitalización; el tope; `unidas` y `uniones_descartadas` llegan.

## Tarea 3: las funciones puras de la pantalla

- `consola/web/js/kmz_geometria.js`:
  - `seTocan(anillosA, anillosB, tol)`: al menos dos vértices de A a menos de `tol` del
    borde de B (o al revés).
  - `loteConNumero(rasgos, numero, salvo)`: el rasgo con ese número (`claveLote`), que no
    sea `salvo`.
  - `unirParte(entradas, numero, punto, anillos)`: agrega `{numero, x, y}` a
    `entradas.uniones`, quita la semilla de la loteadora dentro de `anillos` y las uniones
    que ya hubiera dentro de esa parte (a otro número). No toca lo que recibe.
  - `separarPartes(entradas, numero)`: quita las uniones de ese número.
  - `aplicarUnion(rasgos, numero, punto)`: la parte que contiene `punto` pasa a verde con el
    número (`origen: 'usuario'`, sin banderas, `parte_de: numero`) y no cuenta como
    duplicado del lote, hasta que llegue la relectura.
  - `girarEntradas` gira también `uniones` (como las semillas).
- `consola/web/js/kmz.js`: `VACIAS()` con `uniones: []`.
- `consola/web/kmz.test.js`: pruebas de todo lo anterior.

## Tarea 4: el diálogo, "Separar las partes" y el aviso

- `consola/web/index.html`:
  - `<dialog id="kmz-unir-dialogo" class="modal">` con título, texto y los tres botones
    (`kmz-unir-si`, `kmz-unir-pasar`, Cancelar con `data-cerrar`), como
    `kmz-sin-numero-dialogo`.
  - En el cuadro del número (`#kmz-numero`), un botón `data-accion="kmz-separar"`
    ("Separar las partes", `boton--texto boton--chico`), oculto por defecto.
- `consola/web/js/kmz.js`:
  - `escribirNumero` y `confirmarSugerencia`: si el número ya lo tiene otro lote
    (`loteConNumero`) que `seTocan` con la parte (tol = 0,5 mm en px de página, con el
    `ppmm` de `plano.digitalizado.pagina`), abren el diálogo en vez del `confirm`. "Unirlas"
    → `unirParte`, `aplicarUnion`, `cambiar` y `programarRelectura`; "Pasar" → lo de hoy.
    Si no se tocan, el `confirm` de hoy.
  - `abrirNumero`: con `lote.properties.unidas > 0`, muestra "Separar las partes";
    `kmz-separar` → `separarPartes`, cierra el cuadro, `cambiar` y `programarRelectura`.
  - El aviso de Numerar (`mensajeNumerar` o junto a él) dice las uniones descartadas con el
    texto del spec.
- Prueba de que las acciones nuevas existen en el HTML si las pruebas del front ya lo
  comprueban para otras acciones.
