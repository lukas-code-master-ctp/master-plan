# Crea tu KMZ para un usuario promedio, sprint 2

## Problema

El sprint 1 (`docs/specs/2026-10-06-kmz-prueba-usuario-sprint1.md`) dejó Marcar, Leer el
plano y Numerar sin trabas. Lo que sigue frenando al parcelero de la prueba de usuario
(informe en `/mnt/project-files/prueba-usuario-kmz/`) es **Ubicar**:

- Tiene una coordenada, pero la consola le pide marcar 4 puntos en el plano y en el mapa.
  Pegar la coordenada mueve el mapa sin dejar un alfiler, y no se sabe a qué punto del plano
  corresponde.
- El plano de Rapel tiene el norte a la izquierda: hay que girarlo mentalmente para encontrar
  las esquinas en la foto.
- Los lotes recién se ven en el mapa con el plano ya ubicado.
- Al acercar a zoom 19 el satélite dice "Map data not yet available".
- Si los puntos quedan un poco corridos, todos los lotes salen parejo más chicos (−4,9 % en
  el QA del sprint 1) y no hay cómo arreglarlo sin volver a marcar.
- Son 7 pasos visibles, aunque Leer el plano corre solo y Numerar muchas veces no hace falta.

Del QA del sprint 1 quedaron dos fallas de la lectura: **8-09 sale cortado** (3.532 m²
contra ~4.750) según dónde se encierre el dibujo, y lotes de tamaño normal salen como
**"partes chicas"** en la primera lectura si sus vecinos aún no tienen número.

## Decisiones de Lukas (2026-10-07)

1. Ubicar por defecto: la coordenada y un clic en el plano. El tamaño sale del cuadro de
   superficies y el norte lo ajusta ella girando, mientras ve los lotes sobre el satélite.
2. Marcar puntos queda como "Afinar con puntos", opcional.
3. Cuatro pasos visibles: Subir → Marcar → Ubicar → Revisar y descargar. Leer el plano corre
   solo al salir de Marcar; Numerar aparece solo si hace falta.
4. Sin cuadro de superficies, se pide la escala impresa (1:5.000); si no la tiene, puntos.
5. Si se ubicó con puntos y los lotes salen parejo más chicos o más grandes, botón "Ajustar
   el tamaño con el cuadro" en Revisar y en el semáforo.
6. 8-09 cortado y las "partes chicas" entran en este sprint.

## Solución

### 1. Ubicar con un punto (servidor)

Nuevo método en `pipeline/plano/georreferencia.py`, `por_punto`: una similitud con

- **traslación**: el punto del plano (x, y en px de página) va a la coordenada (lon, lat);
- **escala** en m/px: del cuadro de superficies, `sqrt(mediana(area_oficial / area_px))`
  con los lotes que tienen área oficial (mínimo `ESCALA_CUADRO_LOTES`), o de la escala
  impresa (`1:N` → `N / 1000 / ppmm` m/px, con el `ppmm` de la imagen de trabajo); si no
  hay ninguna de las dos, error claro;
- **giro**: los grados que eligió la loteadora (0 = el arriba del plano es el norte).

Va en `entradas.ubicacion = {x, y, lon, lat, giro, escala_impresa?}`, validado en
`leer_entradas` y en la huella de Ubicar. Prioridad al ubicar: la cuadrícula elegida, luego
los puntos (2 o más), luego `ubicacion`. El resultado es una `Transformacion` con
`metodo="punto"`, sin control de calce; su aviso dice que el tamaño salió del cuadro (o de
la escala) y que puede afinar con puntos. La escala contra el cuadro no aplica (sería
circular) cuando la escala salió del cuadro.

### 2. Ubicar con un punto (pantalla)

El panel de Ubicar arranca con una sola tarea:

1. "Pega la coordenada que tienes" (el campo de hoy). Al apretar Ir, el mapa queda con un
   **alfiler** en la coordenada.
2. "Haz clic en el plano en el punto de esa coordenada". El plano se muestra **girado** igual
   que lo que se ve en el mapa (el norte arriba, con el giro elegido).
3. Con los dos, los **lotes aparecen sobre el satélite** al tiro (calculados en el navegador
   con la misma similitud; el servidor la recalcula exacta al guardar).
4. "Gira hasta que los lotes calcen con los caminos": un control de giro (botones ±1° y
   ±15° y un deslizador de −180° a 180°), y un arrastre de los lotes en el mapa para
   moverlos (lo mismo que el ajuste fino de hoy, `entradas.ajuste`).
5. "Seguir: revisar" queda habilitado en cuanto hay coordenada, punto y escala.

Sin cuadro de superficies, debajo aparece "¿Qué escala dice el plano?" con un campo `1:` y
el aviso de que, si no la sabe, puede ubicar con puntos.

El mapa no acerca más allá de donde hay imagen (`maxNativeZoom` 18, con sobre-zoom).

### 3. Afinar con puntos

La tabla de puntos de hoy queda plegada bajo "Afinar con puntos" (se abre sola si el KMZ ya
tenía puntos). Con 2 o más puntos, ellos mandan. Los lotes se ven sobre el mapa desde el
segundo punto marcado (vista previa en el navegador), no solo al terminar.

### 4. Ajustar el tamaño con el cuadro

Cuando se ubicó con puntos y Revisar detecta el sesgo parejo (`sesgoDeEscala`), Revisar y el
semáforo muestran "Ajustar el tamaño con el cuadro". Guarda `entradas.escala_cuadro = true`
y la georreferencia reescala la similitud de los puntos al tamaño del cuadro, girando en
torno al centro de los puntos (la posición y el giro se mantienen). Se puede deshacer.

### 5. Cuatro pasos visibles

Las pastillas son: **1 Subir el plano · 2 Marcar · 3 Ubicar · 4 Revisar y descargar**.

- "Seguir" de Marcar lee el plano (como hoy) y, al terminar, va a Numerar solo si faltan
  números, hay lecturas por confirmar, números repetidos o la pregunta del resto; si no,
  directo a Ubicar.
- Numerar se muestra como un paso intermedio sin pastilla propia ("Antes de ubicar: revisa
  los números"), dentro de Marcar en la barra de pasos. Siempre se puede abrir con "Revisar
  los números" desde Ubicar y Revisar.
- Revisar y Crear quedan en un solo panel: el semáforo, el resumen y el botón de crear y
  descargar.
- Las rutas `#/kmz/<slug>/<paso>` viejas siguen funcionando (llevan al paso nuevo que las
  contiene).

### 6. Lectura: 8-09 cortado y "partes chicas"

- **8-09:** con las entradas de `/mnt/project-files/prueba-usuario-kmz/sprint1/entradas-rapel-sprint1.json`
  8-09 pierde su esquina norponiente. Se busca la causa en la red de deslindes
  (`particion.py`) y se arregla con una prueba que reproduce el caso (el rectángulo corrido
  unos píxeles no cambia la partición).
- **Partes chicas:** una cara sin número de al menos 0,4 veces la mediana de los lotes cuenta
  como lote (`de_lote`), aunque no toque un lote numerado.

Se mide con la regresión (`pipeline/plano/regresion.py`) donde esté disponible; en el hilo
no está `regresion/`, así que el criterio es el banco de Rapel y las pruebas.

## Fuera de alcance

Leer la flecha del norte o la escala impresa con OCR, Mis planos, y el visor (`web/`).

## Riesgos

- Un giro elegido a ojo puede quedar unos grados corrido: por eso los lotes se ven sobre el
  satélite mientras se gira y el semáforo sigue avisando.
- La escala del cuadro supone que el cuadro está bien leído; con pocas áreas oficiales se
  pide la escala impresa o puntos.
- Cambiar los pasos visibles toca rutas y textos de todo Crea tu KMZ: las rutas viejas
  se mantienen como alias.
