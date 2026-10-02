# Plan: animación al digitalizar

Spec: `docs/specs/2026-10-02-animacion-digitalizar.md`. Rama: `cc/animacion-digitalizar`.

## Tarea 1 (única): la tarjeta del escáner

- `vuelo.js`: el avance dentro de un paso. Un patrón opcional con `(\d+) de (\d+)` que
  reparte el tramo del paso. Para el paso de lectura usa `Rótulos: X de Y pasadas`. Sigue
  siendo una función pura.
- Escena SVG en la sección del paso 3 (`index.html`), estilos en `consola.css` con las
  mismas variables y el mismo tono que la tarjeta del dron, y `prefers-reduced-motion`.
- `kmz.js`: pintar la tarjeta con cada tanda de líneas (el oyente que ya existe) y al
  terminar. El registro técnico queda plegado.
- Pruebas node del avance con líneas reales. Las pruebas de ids y `data-accion` siguen al
  día.
- Verificación en el navegador.
