# Mis KMZ: ajustes del QA en producción (Caminos de Rapel, 2026-10-05)

## Problemas

1. **Bordes exteriores ondulados.** En Google Earth, el borde junto al camino, el lado
   izquierdo y el borde de abajo siguen el trazo "a pulso" (escalones, ondas). Las líneas
   interiores salen rectas. El KMZ real tiene polígonos de pocos vértices y lados rectos.
2. **Un número sin prefijo se toma como otro lote.** Un clic viejo "9" quedó como lote "9",
   distinto del "8-09" de la serie, y "8-09" aparecía como faltante.
3. **La sugerencia confirmada sigue visible.** "¿8-05? Confirmar" sigue en la lista después
   de confirmarla; parece que no pasó nada.
4. **Revisar culpa a los lotes cuando es la escala.** Con 13 lotes en rojo por la escala de
   las anclas (−5,5 % de área parejo), el texto dice "suelen ser lotes mal separados".
5. **Barra horizontal en el panel de Ubicar.** El panel izquierdo muestra una barra de
   desplazamiento horizontal que no debería aparecer.

## Solución

1. **Enderezado de bordes.** Una arista que en el plano es recta pero viene con ruido (texto
   o achurado pegado, el borde de un camino dibujado, el escaneo) se ajusta a una recta, o a
   una poligonal de pocos tramos, con una tolerancia en mm de papel, robusta a valores
   atípicos (RANSAC o recorte de residuos) y no solo "cabe en 2 px". Las curvas de verdad
   (esteros, caminos curvos) siguen curvas pero simplificadas. Con Rapel en el set de
   regresión se mide el número de vértices por lote y el Hausdorff contra el real. Los
   demás planos no pueden empeorar más que la tolerancia.
2. **Prefijo de sector.** Si un número escrito o leído no tiene sector y casi toda la serie
   lo tiene (por ejemplo, ≥ 80 % de los lotes son "8-NN"), se interpreta como "8-NN"
   (mostrándolo así: "9 → 8-09") y no como otro lote. Lo que la loteadora escriba con su
   sector se respeta tal cual.
3. Al confirmar una sugerencia, su botón desaparece de la lista o queda como "✓ 8-05"
   hasta digitalizar de nuevo.
4. Revisar: si existe el aviso de escala de Ubicar o el error de área es parejo (la mayoría
   de los lotes con el mismo signo y una dispersión chica), decir que probablemente son las
   anclas y enlazar a Ubicar, en vez de culpar a la separación de lotes.
5. Sin desborde horizontal en el panel de Ubicar.

## Aceptación

- Rapel en la regresión: la mediana de vértices por lote cerca de la del real (6) y bordes
  exteriores rectos en el KMZ (revisión visual con una captura); los 6 planos dentro de la
  tolerancia.
- Pruebas para cada punto; `pytest` (en Docker) y `node --test` en verde.
