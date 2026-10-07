# Plan: Crea tu KMZ para un usuario promedio, sprint 1

Spec: `docs/specs/2026-10-06-kmz-prueba-usuario-sprint1.md`. Un commit por tarea, con
`(tarea N)` al final. Cada tarea termina con sus pruebas pasando; la suite completa
(`npm test`) corre al final de cada tarea que toca Python y al cierre.

Banco de prueba de Rapel (fuera de git, en el scratchpad del hilo): una carpeta de plano
con `plano.pdf`, `entradas.json` (dibujo, tapado, cuadro, números, 4 puntos) y lo derivado.
`python -m pipeline.plano digitalizar <carpeta>` y luego `georreferenciar` y `kmz` la
rehacen. Tesseract está instalado en el hilo.

## Tarea 1: borde exterior recto

- `pipeline/plano/particion.py` (o donde se arman los polígonos finales): enderezar los
  tramos del borde exterior del loteo, entre vértices compartidos con otro lote o esquinas
  del contorno, cuando la desviación máxima a la recta entre extremos es ≤ ~2,5 mm del
  plano (en px con `ppmm`). Las aristas compartidas no se tocan. Constante con nombre y su
  porqué.
- Prueba en `pipeline/tests/`: un loteo sintético con dientes de "texto" en el borde
  exterior sale recto, y un borde curvo de verdad (más desviación) queda curvo; la red no
  pierde área entre lotes.
- Verificación: en el banco de Rapel, 8-01 y 8-10 sin dientes en el borde poniente (captura
  del plano con los polígonos), y áreas de los demás lotes con cambio ≤ 0,5 %.

## Tarea 2: la cuadrícula solo si sirve, y sin atrasar nada

- `consola/plano.py`: `huella_digitalizar` no cambia por elegir o quitar la cuadrícula que
  propuso el lector (lo que importa a digitalizar es lo que se leyó). Revisar qué usa
  digitalizar de `entradas.cuadricula` antes de cambiarlo, y dejar el porqué en un
  comentario.
- `consola/plano.py` (estado) o `kmz.js`: la propuesta se ofrece solo si tiene al menos dos
  líneas con valor en cada eje (lo que pide `por_cuadricula`).
- `kmz.js`: si `georreferenciar` falla con la cuadrícula, se quita sola y el panel dice
  "No se pudo ubicar con la cuadrícula del plano. Marca los puntos a mano."
- Pruebas: `consola/tests/` (huella estable al usar/quitar la cuadrícula; propuesta incompleta
  no se ofrece) y `consola/web/kmz.test.js` si hay lógica pura nueva.

## Tarea 3: Numerar se entiende y no se traba

- `kmz_geometria.js`: funciones puras para (a) aplicar al tiro una semilla nueva sobre los
  rasgos en px (el lote queda con número, origen usuario, sin bandera `sin_numero`), (b) la
  forma del cuadro de un número escrito (`claveLote` igual → la del cuadro), (c) el mensaje
  único de Numerar.
- El servidor expone los números del cuadro (lo que ya lee el lector) en el estado del KMZ
  para que el cliente normalice y ofrezca la lista de faltantes (`<datalist>` en el campo).
- `kmz.js`: confirmar/escribir aplica (a) y repinta; un temporizador (≈1,5 s tras el último
  cambio) relanza la lectura en segundo plano si el digitalizado quedó atrasado y no hay
  trabajo corriendo, sin cambiar de paso al terminar; "Actualizando los lotes…" en el panel
  y "Seguir" esperando. En Numerar no se muestra el aviso de atrasado; se quita la nota
  "Cuando cambias números…".
- Todos los pasos: motivo en una línea bajo el "Seguir" deshabilitado
  (`#kmz-panel-<paso> .kmz-por-que`).
- Pruebas: `consola/web/kmz.test.js` para (a), (b), (c); prueba de servidor para los
  números del cuadro en el estado.

## Tarea 4: el resto de la propiedad

- Detección (servidor o `kmz_geometria.js`): fila de resto en el cuadro, o parte sin número
  más de 5 veces la mediana de los lotes.
- Numerar: tarjeta con la pregunta y los dos botones; centra el plano en el polígono.
  "Incluirlo" pone la semilla con el número del cuadro (o "Resto"); "Dejarlo fuera" lo anota
  en `entradas` (p. ej. `fuera: [[x, y]]`, un punto dentro) y esa parte deja de contar como
  lote sin número en Numerar, Revisar y al crear (el 409 de "sin número" no la cuenta).
  `_migrar` no aplica (son JSON del plano); `guardar_entradas` valida el campo nuevo.
- Pruebas: servidor (crear no pide confirmación por una parte dejada fuera) y JS
  (detección y conteos).

## Tarea 5: Marcar guiado

- `kmz.js`: al pintar Marcar sin `rectangulo`, herramienta "dibujo"; tras el primer
  rectángulo de dibujo, "mascara". "Seguir" de Marcar llama a `digitalizar()` y abre el
  paso 3 con el escáner.
- `consola.css`: `.kmz-panel__pie` fijo abajo del panel (sticky), también en celular.
- Pruebas: las que existan de pasos/herramientas en `kmz.test.js`; QA con capturas.

## Tarea 6: semáforo antes de crear

- `kmz_geometria.js`: `semaforo(rasgosGeo)` → `{tono: 'verde'|'ambar'|null, dentro, total}`
  (ámbar si la mitad o más de los lotes con área oficial se aparta más de un 5 %).
- `index.html` + `kmz.js`: caja `#kmz-semaforo` en el panel Crear, con "Volver a Ubicar";
  el botón dice "Crear el KMZ igual" en ámbar. Necesita los lotes en lon/lat cargados al
  entrar a Crear.
- Pruebas: `kmz.test.js` para `semaforo`.

## Tarea 7: vocabulario

- `index.html`, `kmz.js`, `kmz_geometria.js` (`nombreDelSistema` deja de mostrarse en el
  resumen), y los avisos del servidor (`pipeline/plano/georreferencia.py`, `consola/plano.py`)
  según la tabla del spec. El paso 3 pasa a "Leer el plano".
- Pruebas: actualizar las que comparan textos (`kmz.test.js`, `consola/tests/`, pruebas del
  pipeline que miran avisos).

## Cierre

`npm test` completo, QA local (`npm run qa:levantar`) con el plano de Rapel recorriendo los
7 pasos en escritorio y celular, arreglo de lo que se encuentre, PR a `main` con el informe.
