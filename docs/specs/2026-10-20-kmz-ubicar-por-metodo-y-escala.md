# Crea tu KMZ: Ubicar por método y marcar la escala

Fecha: 2026-10-20. Pedido de Lukas tras usar el paso Ubicar del sprint 2: sigue siendo poco
intuitivo tener la coordenada + giro arriba y "Afinar con puntos" plegado abajo, con reglas de
quién manda que no se ven.

## Problema

1. En Ubicar conviven tres formas de ubicar (coordenada + giro, puntos, cuadrícula) en un mismo
   panel, y la que manda la decide el servidor por reglas ocultas (2 puntos ganan a la
   coordenada, la cuadrícula gana a todo). La loteadora no sabe qué está usando.
2. El tamaño con un punto sale del cuadro de superficies o de la escala 1:N escrita en Ubicar.
   No se puede usar la barra de escala dibujada en el plano, que casi todos traen.

## Solución

### Ubicar: primero el método

Al entrar a Ubicar sin método elegido se ven tarjetas para elegir:

- **Varios puntos** (A, B, C, D): "Pega la coordenada de puntos que veas en el plano y en el
  mapa. El más preciso."
- **Un punto y girar**: "Una coordenada, su punto en el plano, y giras hasta que calce."
- **Cuadrícula impresa**: solo si el lector encontró una cuadrícula con coordenadas en el plano.

Elegir guarda `entradas.metodo` (`"puntos"`, `"punto"`, `"cuadricula"`). Un enlace "Cambiar de
método" vuelve a las tarjetas sin borrar nada: lo de cada método queda guardado y solo se usa
el elegido.

**Varios puntos.** Parte con una sola fila, A: campo de coordenada + "Ir". Al apretar Ir el
mapa va allá con el alfiler, y la fila pide "Haz clic en el plano donde está A". El clic en el
plano completa el punto. Entonces aparece "Añadir B" bajo la fila A, con el mismo flujo, y así
hasta D (4 puntos como máximo desde esta pantalla). También sirve hacer clic en el mapa en vez
de pegar la coordenada mientras la fila la espera. Cada punto hecho muestra su distancia y
estado (como la tabla de hoy) con "Rehacer" y "Quitar". Con 2 puntos ya se ubica; C y D son
para afinar. Los KMZ viejos con más de 4 puntos o con otros nombres los muestran todos; solo
"Añadir" se detiene en D (o al haber 4).

**Un punto y girar.** 1) Pega la coordenada + Ir; al apretar Ir queda esperando el clic en el
plano (sin otro botón). 2) Con el punto puesto aparece el giro (deslizador y botones de 1° y
15°) en el mismo panel, más el giro chico que ya hay sobre el mapa. Si falta la escala (sin
cuadro de superficies y sin escala marcada) se dice "Falta la escala del plano: márcala en el
paso Marcar" con un botón que lleva allá.

**Cuadrícula impresa.** Lo de hoy (usar/dejar de usar) y, abajo, los puntos opcionales para
comprobarla, con las mismas filas del método de varios puntos.

Las flechas del ajuste fino y "Arrastrar los lotes" siguen abajo en todos los métodos.
Desaparece "Afinar con puntos" y el campo 1:N de Ubicar.

**KMZ que ya existen** (sin `metodo`): con 2 puntos o más, entran en "varios puntos"; con la
cuadrícula elegida, en "cuadrícula"; con la coordenada y su punto, en "un punto"; sin nada,
ven las tarjetas. En el servidor, sin `metodo` se mantiene la precedencia de hoy, así lo ya
ubicado sigue al día (misma huella).

### Marcar: la escala

Herramienta nueva **Escala** en la barra de Marcar, junto a "Cuadro de superficies". Con ella
se hacen dos clics en los extremos de la barra de escala del plano y, en el panel, se escribe
cuántos metros mide ("200"). Se dibuja como una línea con sus extremos y la etiqueta "200 m".
En el mismo panel, como alternativa, "o escribe la escala del plano 1: ___". La lista de lo
marcado muestra "Escala: 200 m" o "Escala 1:1.000" con "Quitar".

Se guarda en `entradas.escala`: `{"p": [x, y], "q": [x, y], "metros": 200}` (px de página) o
`{"impresa": 1000}`. No cambia los lotes: no vuelve a leer el plano. Girar la página gira sus
extremos como al resto de lo marcado. La escala 1:N que algunos KMZ tienen en
`ubicacion.escala_impresa` se sigue leyendo si no hay `entradas.escala`.

**Qué escala manda** con un punto: la marcada (línea o 1:N) > la del cuadro de superficies >
`ubicacion.escala_impresa` vieja. El semáforo de Revisar sigue comparando con el cuadro, y el
aviso de escala distinta al cuadro ahora sí aparece con la escala marcada (deja de ser
circular). Con varios puntos o la cuadrícula la escala marcada no se usa (el "Ajustar el
tamaño con el cuadro" de Revisar queda igual).

## Datos

`entradas.json` suma, opcionales y sin cambiar la huella de lo que ya existe si no vienen:

- `metodo`: `"puntos" | "punto" | "cuadricula" | null`. Con valor, `georreferenciar` usa solo
  ese método (y falla con un mensaje claro si le falta algo); sin valor, la precedencia de hoy.
- `escala`: `{"p", "q", "metros"}` o `{"impresa"}`, o null. Validación: metros > 0, extremos
  distintos (al menos 10 px), impresa entre 1:100 y 1:1.000.000.

Ambas son claves de ubicar (`CLAVES_UBICAR`): cambiarlas deja atrasada la ubicación, no lo
digitalizado. En la huella de ubicar cuentan solo cuando las usa el método vigente.

La escala de la línea se lleva a px de trabajo pasando sus extremos por la homografía página →
trabajo y midiendo ahí: m/px de trabajo = metros / largo.

## Fuera del alcance

- Leer la barra de escala sola (OCR).
- Usar la escala marcada para fijar el tamaño con varios puntos.
- Cambios en Numerar (los está haciendo otro hilo) y en Revisar.
