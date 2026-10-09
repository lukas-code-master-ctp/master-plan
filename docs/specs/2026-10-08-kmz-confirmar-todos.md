# Confirmar todos los números sugeridos en Numerar

## El problema

En el paso Numerar de Crea tu KMZ, las partes del tamaño de un lote en las que el lector
leyó un número con poco apoyo salen en rojo como `¿N?` y en la lista "Números por
confirmar", una pastilla por número. Con Constitución son más de 40 y hay que hacer clic una
por una. Mientras no se confirman siguen siendo lotes sin número: Crear avisa "Quedan N lotes
sin número" y "Crear sin ellos" los deja fuera del KMZ (`consola/plano.py`, `crear_kmz`).

Lukas (2026-10-08): "me tinca el 2 para confirmar todos, y así solo quedan los que realmente
no tienen número".

## Lo que se hace

- Un botón **"Confirmar todos (N)"** junto al título "Números por confirmar". Se ve solo con
  2 sugerencias o más (con una basta su pastilla).
- Al apretarlo pide una confirmación del navegador: "¿Confirmar los N números sugeridos? Cada
  uno queda como número de su lote." Son muchos lotes de una vez y no hay deshacer para los
  números; si uno estaba mal se corrige como cualquier otro, con un clic en el lote.
- Cada sugerencia queda como si se hubiera confirmado su pastilla: el número en la forma del
  cuadro (`formaDelCuadro`), una semilla en el rótulo de la parte, el lote verde al tiro.
- Todo en un solo cambio de entradas y **una sola relectura** (no 40).
- **Las que chocan no se confirman.** Si el número ya está en otra semilla o se repite entre
  las sugerencias, esa sugerencia queda en la lista para resolverla a mano con su pastilla
  (que pregunta si pasar el número). Si hubo alguna, un aviso lo dice: "Se confirmaron 38. 2
  quedan por confirmar porque su número ya está en otro lote."
- Después solo quedan en rojo las partes que de verdad no tienen número.

## Fuera del alcance

- Cambiar el texto del diálogo de Crear ("lotes sin número" → "números por confirmar"): fue la
  propuesta 1 y Lukas eligió la 2.
- Deshacer la confirmación masiva.
- Cambios en el servidor: las sugerencias ya llegan en `lotes` y las semillas se guardan como
  hoy.
