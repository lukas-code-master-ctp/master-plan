# Crea tu KMZ para un usuario promedio, sprint 1

## Problema

En una prueba de usuario con el plano de Caminos de Rapel (Lote 8, 16 lotes de 5.000 m²) y
una sola coordenada, un parcelero sin experiencia se queda atascado en Crea tu KMZ
(informe en `/mnt/project-files/prueba-usuario-kmz/informe.md`). Lo que lo frena en este
sprint:

- **Numerar parece roto.** "¿8-16? Confirmar" deja un punto negro, pero el lote sigue rojo y
  los contadores no cambian hasta volver a digitalizar. "Seguir" se deshabilita, y el motivo
  ("Cambiaste el dibujo o los números…") queda al pie del plano, fuera de la pantalla. Hay
  tres avisos que dicen lo mismo. Escribir "8-8" deja "LOTE 8-8" en el KMZ, aunque el cuadro
  dice "8-08".
- **La cuadrícula impresa engaña.** El botón verde ("lo más preciso") aparece aunque solo se
  leyó un eje. Al usarla no pasa nada visible, "Seguir: revisar" sigue deshabilitado sin
  explicación, y usarla o quitarla deja la digitalización atrasada y devuelve a Numerar.
- **El resto de la propiedad** (Lote 8, 76 há) queda rojo como "lote sin número", sin saber
  si va al KMZ.
- **Marcar:** el modo activo es "Mover", así que el primer arrastre mueve la imagen en vez de
  encerrar el dibujo. "Seguir" se va bajo el borde a medida que se agregan tapados.
- **Digitalizar pide dos clics:** "Seguir: digitalizar" lleva a otra pantalla con otro botón
  "Digitalizar".
- **Se crea el KMZ sin advertir** aunque 14 de 16 lotes midan más de un 5 % distinto al cuadro.
- **Vocabulario técnico:** anclas, residuo, atípica, datum, UTM 19S · WGS84, lecturas, mediana.
- **Zigzag en 8-01 y 8-10.** El borde poniente sigue las letras de "Servidumbre de Tránsito
  8m", que está pegado al deslinde exterior.

Ubicar con la coordenada, el norte y la escala, y bajar a 4 pasos visibles quedan para el
sprint 2, en otro hilo.

## Decisiones de Lukas (2026-10-06)

1. Dos sprints; este es el primero.
2. Mis planos queda como está (el #44 sacó de ahí "Nuevo KMZ").
3. El resto de la propiedad: se pregunta si se incluye.
4. Semáforo antes de crear: avisa y deja "Crear igual"; no bloquea.
5. Al escribir o confirmar números, se vuelve a leer el plano solo, en segundo plano.
6. El cambio de vocabulario se aplica tal como se propuso.

## Solución

### 1. Borde exterior recto (zigzag de 8-01 y 8-10)

En el pipeline (`pipeline/plano/`), después de partir en lotes, las aristas del **borde
exterior del loteo** (las que no comparte con otro lote) se enderezan: un tramo del borde
entre dos vértices que comparten otros lotes (o esquinas del contorno) cuya desviación de
la recta entre sus extremos es del tamaño de un rótulo (hasta ~2,5 mm en el plano) se
reemplaza por esa recta. Las aristas compartidas entre lotes no se tocan, así que la red
sigue cerrada y sin huecos. Un borde de verdad curvo (un estero, una curva de camino) se
desvía más que eso y queda como está.

Criterio de aceptación con el plano de Rapel: el borde poniente de 8-01 y 8-10 queda recto
(sin dientes) y las áreas de los demás lotes no cambian más de un 0,5 %. Crea tu KMZ está en
prueba: se aceptan cambios en otros planos si no empeoran la regresión (`pipeline/plano/regresion.py`).

### 2. La cuadrícula solo si sirve, y sin atrasar nada

- "Usar la cuadrícula impresa" se ofrece solo si lo leído alcanza para ubicar (al menos dos
  líneas con valor en cada eje, lo mismo que exige `por_cuadricula`). Si no alcanza, no se
  muestra.
- Si al usarla la ubicación falla, se dice en el panel: "No se pudo ubicar con la cuadrícula
  del plano. Marca los puntos a mano." y se quita sola.
- Usarla o quitarla no deja la digitalización atrasada: la huella de digitalizar no cambia
  cuando la cuadrícula elegida es la misma que se leyó al digitalizar (o cuando no hay
  ninguna elegida). Solo atrasa la ubicación, que es lo que cambia.

### 3. Numerar se entiende y no se traba

- **Se ve al tiro.** Al confirmar una lectura o escribir un número, el lote pasa a verde en
  el plano, su botón "Confirmar" desaparece y los contadores bajan, sin esperar al servidor.
- **Se vuelve a leer solo.** Si los números cambiaron, la consola relanza la lectura del
  plano en segundo plano un momento después del último cambio (sin salir de Numerar). Mientras
  corre, el panel dice "Actualizando los lotes…" y "Seguir" espera. Se quita la nota "Cuando
  cambias números, vuelve a digitalizar" y, en Numerar, el aviso de "desactualizados".
- **Un solo mensaje.** Arriba, una línea: "Faltan 7 números: haz clic en cada lote rojo y
  elige su número." (o "Todos los lotes tienen número."). Las lecturas por confirmar siguen
  como botones. La lista de "pocas lecturas" pasa a "Revisa estos números", con solo el
  número en cada botón (sin "lect." ni porcentaje).
- **El número como en el cuadro.** Lo escrito se guarda con la forma del cuadro de
  superficies cuando son el mismo lote (`claveLote` igual): "8-8" queda "8-08". Al hacer clic
  en un lote sin número, el campo ofrece la lista de números que faltan según el cuadro.
- **Por qué no se puede seguir.** Cuando un "Seguir" está deshabilitado en cualquier paso,
  debajo del botón va el motivo en una línea.

### 4. El resto de la propiedad

Cuando el cuadro trae una fila de resto ("resto de la propiedad", "resto", o un número sin
lote vendible como "8 o resto…") o hay una parte sin número mucho más grande que los lotes
(más de 5 veces la mediana), Numerar pregunta: "¿Este polígono grande es el resto de la
propiedad? **Incluirlo en el KMZ** / **Dejarlo fuera**", centrando el plano en él.

- Incluirlo: se numera con el número del cuadro (o "Resto" si no trae).
- Dejarlo fuera: queda como parte sin número que no cuenta como lote sin número, así que no
  aparece en los avisos ni en el diálogo de "Crear sin ellos".
- La decisión se guarda en las entradas y se puede cambiar.

### 5. Marcar guiado

- Al entrar a Marcar sin dibujo encerrado, la herramienta activa es "Encerrar el dibujo".
  Después de encerrarlo, pasa sola a "Tapar".
- El pie del panel ("Seguir") queda fijo abajo del panel, siempre a la vista.
- "Seguir" en Marcar lanza la lectura del plano directamente (paso 3 con el escáner
  corriendo). El botón del paso 3 queda solo para leer de nuevo.

### 6. Semáforo antes de crear

En el paso Crear, arriba del botón:

- Verde: "Los lotes calzan con el cuadro de superficies (X de Y dentro del 5 %)."
- Ámbar: cuando la mitad o más de los lotes con área oficial se aparta más de un 5 %:
  "14 de 16 lotes miden distinto al cuadro de superficies. Suele ser la ubicación: vuelve a
  Ubicar y marca los puntos de nuevo.", con un botón "Volver a Ubicar". El botón principal
  dice "Crear el KMZ igual".
- Sin cuadro: no se muestra.

### 7. Vocabulario

| Hoy | Queda |
| --- | --- |
| Paso "Digitalizar", "Digitaliza el plano", "Digitalizando…" | "Leer el plano", "Lee el plano", "Leyendo el plano…" |
| anclas | puntos |
| Tabla "Residuo" / "Atípica" / "ok" | "Distancia" / "No calza: márcalo de nuevo" / "Calza" |
| "Con 4 anclas · UTM 19S · WGS84 · error medio 5.4 m" | "Ubicado con 4 puntos · calzan con ±5 m" |
| "Las anclas sirven para confirmar el datum." | "Puedes sumar puntos para comprobar que calza." |
| "la escala de las anclas parece 2,9 % menor…" | "Los lotes salen un 2,9 % más chicos: revisa los puntos…" |
| "8-09 · 2 lect. · 8 %" | "8-09" |

Los textos que vienen del servidor (avisos de la georreferencia, detalle técnico) se
reescriben en su origen. El detalle técnico plegado ("Ver el detalle técnico") puede seguir
siendo técnico.

## Fuera de alcance (sprint 2)

Ubicar con la coordenada y un clic en el plano, girar el plano al norte, corregir la escala
con el cuadro, mostrar los lotes desde el segundo punto, limitar el zoom del mapa, y bajar a 4
pasos visibles. Mis planos no cambia.

## Riesgos

- Enderezar el borde puede mover el contorno de otros planos. Se mide con la regresión.
- Releer solo en segundo plano lanza más trabajos: se agrupan los cambios (uno por ráfaga) y
  no se lanza uno si ya hay uno corriendo para ese KMZ.
