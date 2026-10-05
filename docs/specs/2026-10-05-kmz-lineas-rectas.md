# Crea tu KMZ: deslindes rectos

## Problema

El KMZ de Caminos de Rapel (`test.kmz`, comparado con el KMZ del topógrafo) sale con los
bordes torcidos:

- **Dientes donde hay texto pegado a la línea.** El borde norte de los lotes 8-03 a 8-05,
  el oeste de 8-01 y 8-10 y el sur de 8-12 a 8-15 van en escalones de 3 a 20 m, hasta
  10 m fuera del deslinde real (que es recto). El texto en negrita pegado al deslinde es
  tinta (desde `RELLENO_MIN_MM2`), y el watershed reparte el bloque línea + letras por su
  eje: la grieta pasa por dentro de las letras. Douglas-Peucker, con 0,34 mm de
  tolerancia, conserva cada diente.
- **Quiebres de 2 a 4° en los nodos en T.** El deslinde del medio y el perímetro pasan
  por los nodos donde llegan las divisorias. Cada trozo entre dos nodos es una arista con
  su propia recta, y las rectas de trozos vecinos no coinciden: la línea se quiebra en
  cada nodo.

## Solución (`pipeline/plano/particion.py`, `red_de_deslindes`)

1. **Cadenas.** En cada nodo se unen, de a pares, las aristas que siguen derecho (menos
   de 20° y la recta de una pasa cerca de la otra). Los nodos unidos por una arista de un
   par de píxeles cuentan como uno. Cada cadena se endereza entera: un tramo recto que
   cruza un nodo tiene una sola recta. Un anillo se parte al medio de su tramo más largo.
2. **Dientes.** Un tramo de al menos `ANCLA_MM` (8 mm) es un apoyo. Se endereza lo que
   queda entre dos apoyos seguidos de la misma recta (entre medio, solo tramos cortos),
   entre dos apoyos que se cortan en una esquina (con al menos dos tramos entre medio) o
   entre un apoyo y la punta de la cadena, si se aparta a lo más `EXCURSION_MM` (6 mm),
   menos de `EXCURSION_FRAC` (0,15) de su largo y en zigzag (gira a los dos lados, como
   las letras; una curva gira siempre al mismo).
3. **Puntas en un diente.** Si el nodo de una punta quedó dentro de un tramo enderezado de
   otra línea (la divisoria que llega al borde por dentro del texto), en una segunda
   pasada basta con que lo que va del último apoyo al nodo mida a lo más `EXCURSION_MM`.
4. **Nodos.** Van a la intersección de sus rectas como antes; uno sobre un tramo
   enderezado puede moverse hasta `EXCURSION_MM`.
5. Un tramo corto en una esquina de al menos 20°, cuyas rectas vecinas se cruzan a menos
   de 3 tolerancias de él (el codo de una línea gruesa), se quita.

## Lo que se respeta y lo que no

- Un ochavo (se aparta ≥ 0,35 de su largo, y no zigzaguea), un lado corto en la punta
  (gira una sola vez), un escalón (su tramo largo es un apoyo) y una curva quedan.
- Un entrante de verdad queda si alto / (2·alto + ancho) ≥ 0,15.
- Se pierde un entrante de menos de 6 mm de hondo y casi cinco veces más ancho que hondo
  entre dos tramos de la misma recta. En un plano de loteo no se ve.

## Pruebas

- `dibujar_girado` (`pipeline/tests/plano_sintetico.py`): loteo girado 14°, divisorias en
  T y texto en negrita pegado al borde norte. Antes: hasta 2,6 mm del lote ideal y giros
  de 135°; ahora 0,1 mm y ningún quiebre.
- `_enderezar`: los dientes se van; un entrante de 4 × 8 mm, un ochavo de 6 mm, una
  esquina a 5 mm de la punta y un arco quedan (y un arco de 6.000 px se endereza en
  milisegundos).
- Fuera de git: el set de regresión (`python -m pipeline.plano.regresion`) con los planos
  reales.
