# Crea tu KMZ: unir las hojas de un plano

## El problema

Hay planos que el CBR entrega partidos en varias hojas del PDF. El de Constitución
("Planos CBR Constitucion - fusionado.pdf") trae 3 láminas a 1:1.000, escaneadas a
150 dpi (5,9 px/mm), que se traslapan bastante: los lotes 44 a 49 y 105 a 125 salen
en dos hojas. Cada lámina trae además su cuadro de superficies, su viñeta, el croquis,
la "situación actual" y timbres.

Hoy Crea tu KMZ trabaja sobre **una** página: con un plano así solo se puede
digitalizar una lámina a la vez, y el KMZ queda incompleto.

## La solución

Un editor "Unir hojas" en el paso **Sube el plano**: la loteadora pone las hojas en un
lienzo, las arrastra para dejarlas cerca, pide **Afinar** y el sistema las calza solo en
la zona traslapada. Recorta cada hoja a su dibujo; donde se traslapan manda la de
arriba. La unión pasa a ser una página más (la "página 0") y todo lo que sigue
(marcar, digitalizar, numerar, ubicar, revisar, crear) trabaja sobre ella sin cambios.

Decisiones de Lukas (2026-10-06), todas las recomendadas:

| # | Tema | Decisión |
| --- | --- | --- |
| 1 | Alineación | Se arrastra cerca y el sistema afina en el traslape |
| 2 | Traslape | Cada hoja recortada a su dibujo; manda la de arriba (orden editable) |
| 3 | Cuadros, viñeta, etc. | Quedan fuera con el recorte; el cuadro de superficies se lee de la hoja original |
| 4 | Giro | Botones de 90° más ajuste fino de unos pocos grados |
| 5 | Escala | La del PDF, no se toca |
| 6 | Dónde | En "Sube el plano", si el PDF tiene más de una página |
| 7 | Celular | Se puede ver y mover; el texto recomienda computador |
| 8 | Cambios | Cambiar la unión reinicia los pasos siguientes, como cambiar de página |

## Quién y dónde

- **Loteadora** (dueño o equipo), en Mis KMZ → un KMZ → paso 1 "Sube el plano".
- No lo ven los compradores ni cambia nada para el equipo CTP.

## Cómo se usa

1. Sube el PDF. Si tiene más de una página, bajo las miniaturas aparece
   **"El loteo está en varias hojas: unirlas"**.
2. Se abre el editor sobre el lienzo de la derecha. Arriba del panel, una nota: "Es más
   cómodo en un computador" (solo en pantallas angostas).
3. El panel lista las hojas, cada una con:
   - una casilla **Usar** (todas marcadas al entrar; mínimo 2);
   - **↺ 90° / ↻ 90°** y un control de **giro fino** (−5° a +5°, de a 0,05°);
   - **Recortar**: en el lienzo aparece el rectángulo de recorte de esa hoja con
     manillas; por defecto, la hoja entera;
   - **Subir / Bajar** para el orden (la de más arriba en la lista es la que se ve
     encima).
4. En el lienzo: tocar una hoja la elige; arrastrarla la mueve (mientras se arrastra se
   ve semitransparente para calzar el dibujo de abajo). Rueda y pellizco acercan,
   como en el resto de Crea tu KMZ.
5. **Afinar la alineación**: el servidor calza cada hoja con las que ya están puestas
   (la de más abajo queda fija y las demás se calzan de abajo hacia arriba). Si una hoja no traslapa o
   no se encuentra, queda donde estaba y el panel dice "No se pudo calzar la hoja 3:
   acércala a su lugar y vuelve a afinar".
6. **Usar la unión** guarda y lleva al paso Marcar. **Volver a una sola página** quita
   la unión.
7. Al entrar de nuevo al paso 1 con una unión guardada, la miniatura "Hojas unidas"
   aparece primera y elegida; **Editar la unión** reabre el editor.

En **Marcar**, con una unión, la herramienta del cuadro de superficies pide primero
"¿En qué hoja está el cuadro?" con un botón por hoja usada; el lienzo muestra esa hoja
original (con su giro de 90°) para encerrarlo, y vuelve a la unión al terminar. La
lista de lo marcado dice "Cuadro de superficies (hoja 2)".

## Funcionalidad

### Geometría

Cada hoja usada lleva, en `entradas.union.hojas[]` (en orden de abajo hacia arriba):

```json
{"n": 2, "rotacion": 90, "angulo": 0.35, "x": 6120.5, "y": 2210.0, "recorte": [x0, y0, x1, y1]}
```

- `rotacion`: 0, 90, 180 o 270, como hoy. Los "px de hoja" son los de la imagen de la
  página ya girada.
- `recorte`: en px de hoja; `null` es la hoja entera.
- `angulo`: giro fino en grados, horario en pantalla, entre −10 y 10 (la pantalla deja
  ±5; el margen es para lo que proponga Afinar).
- `x`, `y`: dónde cae el **centro de la hoja girada** en el lienzo de la unión, en px
  de unión.
- Escala: la unión tiene `ppmm_union = min(max(ppmm de las hojas), PPMM_TRABAJO_MAXIMO)`
  y cada hoja se lleva a ella con `k = ppmm_union / ppmm_hoja` (1 en Constitución).
  Nadie la edita.

Un punto `p` de la hoja va a `R(angulo)·k·(p − c) + (x, y) − origen`, con `c` el centro
de la hoja girada y `origen` la esquina superior izquierda (piso) de la caja que
encierra los recortes ya transformados. Así los "px de página" de la unión empiezan en
(0, 0) y todo lo demás de entradas (rectángulo, máscaras, semillas, anclas) se marca
en ellos como en cualquier página. `entradas.pagina` es `0` y `entradas.rotacion` es
`0`.

### Composición

- Fondo: color papel (mediana de las hojas). Se pintan en orden; cada una solo dentro
  de su recorte transformado. Interpolación lineal; la máscara del recorte, sin
  suavizar.
- Para digitalizar se compone desde las imágenes extraídas del PDF
  (`pagina.extraer`), no desde los JPEG de la pantalla.
- Tope: la unión no pasa de **250 megapíxeles** (Constitución da ~120). Más grande,
  "La unión es demasiado grande: recorta las hojas a su dibujo".

### Afinar

`POST /api/kmz/{slug}/union/afinar` con las hojas como están en pantalla; devuelve las
mismas hojas con `x`, `y` y `angulo` corregidos y, por hoja, `calzada: true/false` y
el residuo en mm. No guarda nada.

- Trabaja a 2 px/mm en gris. Para cada hoja (de la segunda en adelante), compara con lo
  ya compuesto debajo, solo en la zona donde se traslapan según la posición actual,
  agrandada 40 mm.
- Puntos ORB y RANSAC con un modelo rígido (giro y traslado; la escala no cambia), y un
  refinamiento ECC euclídeo a 4 px/mm en la misma zona.
- Se acepta si hay al menos 30 puntos que calzan y la corrección no pasa de 60 mm ni de
  5°. Si no, la hoja queda como estaba y `calzada: false`.
- Con Constitución, tras afinar, el residuo en el traslape debe quedar bajo 1 px de
  unión (medido en los puntos que calzan).

### El cuadro de superficies

`entradas.union.cuadro = {"hoja": n, "rect": [x0, y0, x1, y1]}` en px de esa hoja. El
lector lo lee de la hoja original (extraída y girada con su `rotacion`), igual que hoy
lee `entradas.cuadro`. Con unión, `entradas.cuadro` queda en `null`. Sin cuadro, se
sigue probando cada máscara como hoy.

### Lo que queda atrasado

- `union` entra en la huella de digitalizar y en la del lector: cambiar la unión deja
  atrasado lo digitalizado, y la pantalla avisa y borra lo marcado como hoy al cambiar
  de página (con el mismo `confirm`).
- La digitalización anterior se reusa (`_previo`) solo si es de la misma unión
  (`digitalizado.pagina.union` lleva la huella de la unión).
- Subir otro PDF borra la unión con todo lo demás.
- KMZ existentes: no cambian (sin `union`, todo sigue como hoy).

### Validaciones (400 con mensaje para la loteadora)

- Entre 2 y 12 hojas, sin repetir, todas páginas del PDF.
- `pagina` es 0 si y solo si hay `union`; con unión, `rotacion` 0.
- `recorte` dentro de la hoja y no vacío; `angulo` en [−10, 10]; `x`, `y` finitos.
- El cuadro, en una hoja usada y dentro de ella.

### Imágenes para la pantalla

- `GET /api/kmz/{slug}/paginas/{n}?medio=1`: la hoja a lo más 2.400 px de lado, para el
  editor (las tres hojas enteras serían ~150 MP en el navegador). Se genera al subir;
  para PDFs subidos antes, al primer pedido.
- `GET /api/kmz/{slug}/paginas/0`: la unión, compuesta desde los JPEG de las páginas y
  guardada en caché por su huella (`paginas/union-<huella>.jpg`). Si pasa de 60 MP se
  sirve reducida y el lienzo la dibuja estirada a los px de página.
- `estado.union`: `{ancho, alto, ppmm, hojas}` cuando hay unión, para que la pantalla
  sepa el tamaño de la página 0.

## Diseño

- El editor reemplaza el contenido del panel del paso 1 mientras está abierto (mismo
  ancho, mismo estilo de botones). Título "Une las hojas", y una línea: "Arrastra cada
  hoja cerca de su lugar y pulsa Afinar. Recorta cada una a su dibujo: lo que quede
  fuera (cuadros, viñeta, timbres) no entra."
- La hoja elegida lleva un borde violeta (el de la imagen de referencia de Lukas) y su
  número; las demás, borde gris.
- En celular, el panel va arriba y el lienzo abajo, como hoy; las filas de cada hoja
  se pliegan (solo se despliega la elegida).

## Fuera del alcance

- Escalar hojas a mano o hojas de distinta escala.
- Alinear marcando puntos a mano.
- Mezclar las hojas (oscurecer) en el traslape.
- Leer y juntar varios cuadros de superficies (se usa uno).
- Unir páginas de PDFs distintos.

## Riesgos

- Memoria: componer ~120 MP en RGB son ~360 MB en el servidor, además de lo que ya usa
  digitalizar. Se compone por hoja en su caja (no lienzos enteros por hoja) y se
  libera cada una al terminar.
- Choca en archivos con el sprint de la "Prueba de usuario Crea tu KMZ"
  (`consola/plano.py`, `digitalizar.py`, `kmz.js`). Lo nuevo va en archivos propios
  (`pipeline/plano/union.py`, `consola/web/js/kmz_union.js`) y lo que se toca en los
  compartidos es acotado.
