# Crea tu KMZ: el texto sobre el borde y la escala de los puntos

Segunda vuelta sobre Caminos de Rapel, después de `2026-10-05-kmz-lineas-rectas.md`.
Con el enderezado ya desplegado, en Revisar quedaban dos cosas:

- **Casi todos los lotes en rojo.** No era el dibujo: Lukas ubicó el plano con dos puntos,
  uno puesto a ojo. Con dos puntos no hay control, y la escala depende de dónde quedó el
  segundo; entre A y C hay ~500 m, así que 5 m de error son ~2 % de área en todos los
  lotes. A eso se suma que, con los puntos bien puestos, el dibujo da +1 a +3,3 %
  (ámbar). Juntos pasan del 5 %.
- **Un lote "raro" en el borde norte.** El deslinde de 8-04 iba en dientes de hasta 10 m
  hacia afuera, donde "Camino al Lago Rapel" y "Servidumbre de Tránsito 10m" van escritos
  encima del deslinde. El enderezado de la primera vuelta no lo tomaba: ese trozo de borde
  es una arista sola, de nodo a nodo (las divisorias de 8-03 y 8-05), hecha solo de
  dientes cortos, y no se unía en cadena con los lados vecinos.

## Cambios

1. **Cadenas a través de una arista de puros dientes** (`_encadenar.apoyo`): si ningún
   tramo de Douglas-Peucker de la arista llega a `ANCLA_MM` y tiene al menos tres, su
   dirección en el nodo es la de su cuerda (si la cuerda mide al menos `ANCLA_MM / 2`).
   Así sigue derecho por los nodos y el borde norte queda en una sola cadena.
2. **Puente entre apoyos casi paralelos** (`_enderezar`, paso 4): dos apoyos seguidos a
   menos de `PUENTE_GRADOS` (10°) que no son la misma recta ni se cortan cerca (el deslinde
   cambia unos grados de rumbo o se corre bajo el texto) se unen por la recta entre sus
   puntas, si lo de entre medio zigzaguea y se aparta poco (las mismas reglas que el paso
   1). Un escalón (los dos apoyos en la misma recta) o un puente que cruza el rumbo de los
   apoyos se respetan.
3. **Nodo en un diente** (`_enderezar_cadena`): la punta de una divisoria cuenta como
   "dentro de un diente" también si queda a menos de `EXCURSION_MM` de un tramo
   enderezado. El corte de Douglas-Peucker no siempre cae justo en el nodo, y sin esto la
   divisoria de 8-02/8-03 quedaba con un gancho de 2 mm.
4. **Aviso en Revisar** (`sesgoDeEscala`, `consola/web/js/kmz_geometria.js`): si la
   mediana del error de área pasa de ±3 % y al menos 4 de cada 5 lotes van hacia el mismo
   lado, el texto de Revisar dice que suele ser la escala de los puntos de Ubicar y pide
   marcar 3 o 4 esquinas con coordenadas exactas. Ubicar ya avisaba lo mismo (desde
   `ESCALA_CUADRO_MAX`), pero ese aviso queda atrás cuando se llega a Revisar.
5. Revisar ya no dice "los rojos…" cuando no hay ningún rojo.

## Resultado en Caminos de Rapel

Plano de Lukas, semillas en los rótulos y anclas ajustadas al KMZ del topógrafo (error
~1,5 m), contra ese KMZ:

| | Antes | Ahora |
|---|---|---|
| Rotación 0: IoU what-if mediano / mínimo | 0,971 / 0,947 | 0,975 / 0,948 |
| Rotación 0: área de los 16 lotes | +1,0 a +3,6 %, diente de ~10 m en 8-04 | +1,0 a +3,2 %, borde norte recto |
| Rotación 90: 8-02 | +29 % | +29 % (sin cambio, ver abajo) |

## Lo que queda

- **Con el plano girado 90°, 8-02 se escapa hasta la línea del camino.** Su deslinde norte
  es de trazos largos (~4 mm, huecos de ~1,5 mm) que se borran como texto
  (`MIN_COMP_MM`). Con rotación 0 el watershed igual llega bien; con 90° desempata hacia
  afuera. Se probó reconstruir los trazos que siguen a una recta dibujada: arregla 8-02
  (+29 % → −7 %), pero en este plano devuelve también la línea de la servidumbre, 2 mm
  por dentro, y deja a 8-02 y 8-03 cortos. Quedó fuera; el prototipo está en el hilo.
- **El sesgo de +2 % con los puntos bien puestos** no se investigó: puede ser del ajuste
  de las anclas (1,5 m) o del grosor de línea.
- **Sin el set de regresión** (fuera de git): los cambios 1 a 3 se probaron con Rapel y
  las pruebas sintéticas. Hay que correr `python -m pipeline.plano.regresion` antes de
  confiar en ellos para otros planos.

## Pruebas

- `test_enderezar_une_por_una_recta_dos_tramos_casi_paralelos_con_dientes_entre_medio`:
  dos tramos a 3° y 1,5 mm de distancia, con dientes entre medio, quedan unidos por el
  puente. Falla sin el paso 4.
- `test_enderezar_respeta_un_escalon_y_una_esquina_de_verdad` sigue pasando (un escalón
  entre dos tramos de la misma recta no es un puente).
- `el sesgo de escala` (`consola/web/kmz.test.js`): cuándo se avisa y cuándo no.
- QA local: el plano de Rapel subido en la consola, con dos puntos (escala +2 %, los 16 en
  rojo y el aviso) y con cuatro (6 verdes, 10 ámbar, ningún rojo).
