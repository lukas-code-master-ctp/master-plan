# Plan: confirmar todos los números sugeridos en Numerar

Spec: `docs/specs/2026-10-08-kmz-confirmar-todos.md`. Un commit por tarea, con `(tarea N)` al
final. Cada tarea la revisa otro agente antes de pasar a la siguiente.

## Tarea 1: la función que confirma todas las sugerencias

- `consola/web/js/kmz_geometria.js`: `confirmarSugerencias(entradas, rasgos, cuadro)` pura.
  Recorre `sugerencias(rasgos)`; por cada una, `formaDelCuadro(numero, cuadro)`. Se salta las
  que chocan (el número ya está en `entradas.semillas` o ya lo tomó otra sugerencia de esta
  misma pasada, comparando con `claveLote`). Para las demás usa `ponerNumero`,
  `devolverAlKmz` y `aplicarNumero`, como `ponerEnLote`. Devuelve
  `{ entradas, rasgos, confirmadas, omitidas }`. No toca lo que recibe.
- `consola/web/kmz.test.js`: confirma varias de una vez (semillas, lotes verdes, sin
  sugerencias); se salta la que choca con una semilla existente y la repetida; con el cuadro
  "8-8" queda "8-08"; sin sugerencias no cambia nada.

## Tarea 2: el botón en Numerar

- `consola/web/index.html`: el título "Números por confirmar" en una fila con el botón
  `data-accion="kmz-confirmar-todos"` (`boton boton--contorno boton--chico`), que en celular
  se envuelve.
- `consola/web/js/kmz.js`: en `pintarNumerar` el botón se ve con 2 sugerencias o más y dice
  "Confirmar todos (N)". `confirmarTodos()`: `confirm(...)`, `confirmarSugerencias`, un
  `cambiar` y un `programarRelectura`; si hubo omitidas, `avisar` con cuántas y por qué.
- Prueba de que la acción existe en el HTML si las pruebas del front ya lo comprueban para
  otras acciones.
