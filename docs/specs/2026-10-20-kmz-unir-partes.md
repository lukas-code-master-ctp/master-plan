# Unir dos partes de un mismo lote en Numerar

## El problema

En el paso Numerar de Crea tu KMZ, a veces el lector parte un lote en dos: un texto, una cota
o una flecha cruza el lote y la red de deslindes la toma como límite. En el plano de Lukas
(2026-10-20) el Lote 17, un lote largo en "L", quedó partido. Hoy las salidas son malas:

- Ponerle el mismo número a la segunda parte **mueve** el número: "¿Lo pasas a este?" y la
  primera parte queda sin número (`ponerNumero` quita la otra semilla).
- Dos números distintos (17 y 17-B) salen como dos parcelas en el KMZ.
- Dejar una parte sin número y "Crear sin ellos" deja el lote más chico de lo que es.
- Tapar la tinta que lo corta y volver a leer funciona, pero hay que adivinar qué tapar.

Lukas (2026-10-20): "me parece tu cambio propuesto", y eligió las recomendaciones en todas
las preguntas.

## Lo que se hace

- **Solo partes que se tocan.** Si la loteadora le escribe a una parte un número que ya tiene
  otra parte que comparte un borde con ella, se le ofrece unirlas. Si no se tocan, no se
  unen: el KMZ y el visor usan un polígono por parcela.
- **Solo en Numerar.** Revisar no cambia.
- **La pregunta.** En vez del "¿Lo pasas a este?" del navegador, un diálogo:
  - Título: "El 17 ya está en la parte de al lado".
  - Texto: "Si son el mismo lote, únelas y quedan como un solo polígono."
  - Botones: **"Unirlas en el lote 17"** (principal), **"Pasar el 17 a esta parte"** (lo de
    hoy) y **Cancelar**.
  Vale igual al escribir el número en el cuadro del lote y al confirmar una sugerencia del
  lector (`¿N? Confirmar`). Si el otro lote con ese número no toca esta parte, sigue el
  `confirm` de hoy.
  "Confirmar todos" no cambia: las sugerencias que chocan con un número ya puesto se siguen
  saltando y quedan para resolverlas una por una, que es donde aparece esta pregunta.
- **Qué se guarda.** Una unión es `{numero, x, y}` en `entradas.uniones`: un punto dentro de la
  parte que se suma al lote `numero`, en px de página (como las semillas). Al unir, la
  semilla de la loteadora que hubiera dentro de esa parte se quita (la parte ya no tiene
  número propio).
- **Se ve al tiro.** La parte pasa a verde con el número del lote mientras se vuelve a leer
  el plano (una relectura, como al poner un número). Al terminar, el lote llega como un solo
  polígono, sin la línea del medio y con un solo número.
- **Lo hace el servidor.** Al digitalizar, después de partir el dibujo, cada unión busca la
  cara que contiene su punto (una cara sin número o un lote cuyo número leyó el lector) y,
  si comparte un borde con el lote `numero`, la suma a él. El resultado se guarda como un
  lote más en `digitalizado.json`: Ubicar, Revisar, el semáforo de áreas y el KMZ lo ven
  como un solo lote sin cambios.
- **Separar.** Al tocar un lote que tiene partes unidas, el cuadro del número muestra
  **"Separar las partes"**. Quita las uniones de ese lote y vuelve a leer el plano: las
  partes vuelven a salir como antes (la otra parte, sin número o con lo que lea el lector).
- **Al volver a leer el plano** la unión se vuelve a aplicar. Si después de leer las partes
  ya no se tocan, o el punto ya no cae en ninguna parte, o el lote `numero` ya no existe, la
  unión no se aplica y Numerar lo dice en su aviso: "No se pudo unir la parte del lote 17:
  después de leer el plano ya no se toca con él." La unión queda guardada (no molesta) y
  "Separar" no aplica porque no hay nada unido.
- **Celular.** El mismo diálogo y el mismo cuadro del número.

## Detalles

- "Se tocan" en el servidor: comparten un borde de al menos 1 mm de papel (no basta un
  vértice). En la pantalla, para decidir si se ofrece unir, una prueba aproximada con los
  polígonos que ya tiene (al menos dos vértices de la parte a menos de 0,5 mm del borde del
  otro lote); la palabra final la tiene el servidor.
- Unir una parte que el lector numeró (por ejemplo leyó "18" en la mitad del 17): la parte se
  suma al 17 y el 18 desaparece de ahí.
- Varias partes al mismo lote: cada una es una unión. Se aplican en orden; una parte que
  solo toca a otra parte ya unida también entra (se compara con el lote como va quedando).
- Un número que se pasa a otro lote ("Pasar el 17 a esta parte") se lleva sus uniones solo
  si siguen tocando; si no, quedan como descartadas en el aviso.
- Al girar la página, las uniones giran como las semillas. Al rehacer la unión de hojas,
  se borran como todo lo marcado.
- Las entradas sin uniones quedan iguales, y su huella también: ningún plano existente se
  ve atrasado por este cambio.
- Tope: 200 uniones por plano.

## Fuera del alcance

- Unir partes que no se tocan (lotes de varios polígonos).
- Unir en el mapa de Revisar.
- Detectar solo que un lote quedó partido, sin que la loteadora lo diga.
