# Plan: Ubicar por método y marcar la escala

Spec: `docs/specs/2026-10-20-kmz-ubicar-por-metodo-y-escala.md`. Un commit por tarea, con
`(tarea N)` al final.

## Tarea 1: servidor, `metodo` y `escala`

- `pipeline/plano/digitalizar.py`: validar `metodo` y `escala` (doc del formato arriba del
  archivo). Sin la clave, no se agrega (la huella de entradas viejas no cambia).
- `pipeline/plano/georreferencia.py`: con `metodo` usar solo ese método; `_por_ubicacion` toma
  la escala marcada (línea → px de trabajo vía homografía, o 1:N con `ppmm`) antes que el
  cuadro, y luego `ubicacion.escala_impresa`. `origen_escala` = "marcada"/"impresa"/"cuadro";
  el aviso contra el cuadro solo es circular con "cuadro". Textos de error con el método.
- `consola/plano.py`: `metodo` y `escala` en `CLAVES_UBICAR`; `huella_ubicar` cuenta
  `ubicacion` y `escala` solo cuando el método vigente las usa, y `metodo` solo si viene.
  Revisar dónde se guardan y validan entradas desde la consola (que las claves pasen).
- Tests en `pipeline/tests` y `consola/tests`: validación, precedencia, huella igual sin las
  claves, escala de línea con homografía de recorte.

## Tarea 2: geometría del front

`consola/web/js/kmz_geometria.js` y su test:
- `metodoAlEntrar(entradas, hayPropuestaCuadricula)` → método vigente o null.
- `escalaDeUbicacion` con `entradas.escala` (línea o 1:N) y la misma precedencia.
- `usaUbicacion`, `puedeUbicar` y la vista previa respetan `metodo`.
- `girarEntradas` gira `escala.p/q`.
- `siguienteLetra(anclas)` para A..D (tope 4 desde la pantalla).

## Tarea 3: Marcar, herramienta Escala

`index.html`, `kmz.js`, `consola.css`, `kmz.test.js`:
- Botón "Escala" en la barra; dos clics (o arrastre) marcan la línea; el panel pide los metros
  o 1:N; se dibuja la línea con la etiqueta; fila "Escala: 200 m" con Quitar.
- Guardar sin releer el plano.

## Tarea 4: Ubicar, elegir método y "un punto y girar"

- Tarjetas de método, "Cambiar de método", `entradas.metodo`.
- Panel de un punto: coordenada + Ir → espera el clic en el plano → aparece el giro. Falta de
  escala con botón a Marcar. Se quitan el campo 1:N de Ubicar y "Afinar con puntos".

## Tarea 5: Ubicar, varios puntos A..D y cuadrícula

- Filas A..D: coordenada + Ir (o clic en el mapa) → clic en el plano; "Añadir B..D"; estado,
  Rehacer y Quitar por fila.
- Método cuadrícula con sus botones y los puntos opcionales para comprobar.

## Tarea 6: QA y documentación

- `README.md`/docs que mencionen "Afinar con puntos" o el 1:N en Ubicar.
- `npm test`, QA local con capturas en escritorio y celular.
