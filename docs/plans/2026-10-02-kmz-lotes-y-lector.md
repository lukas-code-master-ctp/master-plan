# Plan: lotes que no se pierden, números como en el plano y lector robusto

Spec: `docs/specs/2026-10-02-kmz-lotes-y-lector.md`. Rama: `cc/kmz-lotes-y-lector`.
Pruebas: pytest, `node --test`, `python -m pipeline.plano.regresion`.

## Tarea 1: Caminos de Rapel en el set y números como en el plano
- `regresion/planos/caminos_de_rapel/entradas.json` sale de `entradas_produccion.json`.
  Las capas del real se configuran si hace falta (los rótulos del real son puntos "Lote 8-NN").
- `pipeline/plano/metricas.py`: empareja por `normalizar_id`, así "8-01" calza con
  "Lote 8-01". Se registra la línea base actual de Rapel, que mostrará los 4 lotes perdidos.
- `rotulos.py`: el rótulo completo ("LOTE 8-01" → "8-01", "LOTE 10-6" → "10-6"), sin quedarse
  con el último número. Las pruebas existentes se actualizan.
- `salida.py`: el nombre del lote como vino (`LOTE 8-01`), con la normalización solo para
  comparar o repetir.

## Tarea 2: lotes sin número que no se pierden y huecos en la numeración
- `particion.py`: las regiones sin número de tamaño de lote no se fusionan; quedan como
  "sin número". El umbral es relativo a la mediana de los lotes con número y está documentado.
- `digitalizar.py`: `huecos` por sector a partir de la serie leída, o de los esperados del
  cuadro si existe.
- Consola: se muestran los huecos y los lotes sin número.
- Rapel en la regresión: 16 caras de lote (las sin número cuentan); los demás planos dentro de
  la tolerancia.

## Tarea 3: marcar el cuadro de superficies
- Pantalla Marcar: herramienta "Cuadro de superficies" (un rectángulo, que puede estar fuera
  del dibujo), guardada en `entradas.cuadro`, que el backend ya entiende.
- El lector lee ese recuadro aunque esté fuera del rectángulo del dibujo.
- Los esperados y las áreas oficiales alimentan los faltantes y el color del paso Revisar.
- Pruebas node y python.

## Tarea 4: lector robusto y pantalla que no se queda pegada
- Reproducir la caída con el plano grande (lo entrega el usuario) en Docker con
  `--memory=4g --cpus=2`.
- Lectura por trozos con solapamiento; presupuesto de hebras con agrandado y giro;
  orientaciones primero.
- Medir memoria y tiempo antes y después en los planos del set con el lector, y la calidad con
  `--con-lector`.
- Consola: un trabajo que desaparece (404) se muestra como interrumpido, con reintentar.

## Tarea 5: el área de menos
- Con Rapel en el set, separar escala de anclas contra forma con el what-if. Revisar si el
  deslinde va por el eje de la franja de servidumbre.
- Corregir si es del método; documentar si es de las anclas.

## Tarea 6: documentación y verificación
- README al día y verificación completa (pytest, node, regresión, Docker con lector).
