# Crea tu KMZ: set de regresión (tarea 4)

    python -m pipeline.plano.regresion [--plano X] [--carpeta regresion] [--actualizar-linea-base]

Corre digitalizar → georreferenciar → kmz sobre cada plano de `regresion/planos/` (fuera de
git: los planos traen nombres y RUT) y mide el KMZ contra el real con `pipeline/plano/metricas.py`,
portado de `medir.py`/`medir_r3.py`/`reales.py`. Sale con 1 si un plano empeora más que la
tolerancia contra `regresion/linea_base.json`:

- IoU what-if mediano: no puede bajar más de 0,01.
- Centroide what-if mediano: no puede subir más de 0,25 m.
- Lotes pareados y lotes digitalizados: no pueden bajar.

Cada corrida deja la tabla completa en `regresion/resultados.json`; `linea_base.json` solo
cambia con `--actualizar-linea-base`.

Hidango no tiene KMZ real ni anclas: solo se cuenta que salgan sus 58 lotes.

Los lotes reales salen del KMZ así: polígonos con nombre o con un punto numerado adentro; si
no hay, las líneas se cierran (`polygonize`, más el borde de los polígonos, con conectores de
≤ 1 m) y cada cara toma su punto. Capas excluidas por plano (`entradas.json` →
`regresion.capas_excluidas`), según `ronda3_evaluacion/evaluacion.md`: Puente Negro
`SERVIDUMBRE`; Algarrobo `SERVIDUMBRE` y `ROTULOS`; Curicó `CAMINOS_INTERIORES`. Salen
183, 58, 76 y 49 lotes reales, como en las pruebas.

## 1. El método portado reproduce las pruebas de concepto

Primera corrida, con el código de las tareas 2 y 3 sin cambios:

| Plano | Prueba de concepto: IoU tal cual → what-if / centroide (m) / Hausdorff what-if (m) | Portado |
|---|---|---|
| Puente Negro | 0,847 → 0,981 / 5,27 → 0,55 / 1,19 | 0,847 → 0,981 / 5,27 → 0,55 / 1,19 |
| Algarrobo (cuadrícula) | 0,977 → 0,979 / 1,72 → 1,53 / 10,95 | 0,977 → 0,979 / 1,72 → 1,53 / 10,95 |
| Curicó | 0,758 → 0,923 / 8,07 → 1,84 / 5,19 | 0,758 → 0,923 / 8,07 → 1,84 / 5,19 |
| El Arrayán | 0,699 → 0,970 / 9,95 → 0,74 / 1,59 (183 lotes) | 0,647 → 0,718 / 10,96 → 8,58 / 12,06 (180 lotes) |

- PN, Algarrobo y Curicó calzan en todos los números. Las únicas diferencias están en el
  segundo decimal del error de área: 2,09 % contra 2,08 % en PN y 2,36 % contra 2,35 % en
  Curicó. Vienen de que los polígonos portados no son idénticos bit a bit a los de la prueba:
  el IoU contra ella es ≥ 0,985 por lote (chequeo de la tarea 2).
- El Arrayán no reproduce. La prueba v2 usó un método propio de ese plano, solo con tinta
  roja, que el método general no tiene. Con las mismas métricas, el KMZ v2 de la prueba da
  0,699 / 0,970 / 0,74 m: el medidor portado está bien, y lo que cambia es el digitalizado.
- El KMZ real de El Arrayán cae en el huso 18 y se mide en EPSG:32718; la prueba midió en
  32719. Medido en 32719, el v2 da los mismos números.

## 2. El Arrayán: el arreglo global

Causas del 0,718, viendo los lotes peores sobre la imagen:

1. **El rosado tenue no contaba como tinta "firme".** El rojo del recuadro es pálido (el
   canal rojo también se oscurece), así que el margen de croma no llegaba a `CHROMA_FRAC`.
   Sin tinta firme, `_fusionar_sin_tinta` unía al lote regiones del otro lado de un deslinde
   verdadero.
2. **Los rótulos en negrita y subrayados pasan por línea** (miden más de 10 mm). En un lote
   angosto (7–14 mm a 1:5000) el texto toca los dos deslindes y parte el lote en dos: la
   mitad sin rótulo queda como cara sin número o se une al vecino. Además, el texto tapa el
   fondo alrededor del rótulo y 46 rótulos quedaban sin núcleo.
3. **Error en `particionar`:** un rótulo sin núcleo (`c == 0`) se trataba como si estuviera
   en el exterior, porque el 0 también toca el margen. Eso borraba 12 mm de semillas
   vecinas. Solo pasa cuando un rótulo no tiene núcleo, así que en el resto del set no se
   notaba.

Arreglo, sin parámetros por plano:

- `tinta.ROJO_FIRME_FRAC = 0,15`: el margen de croma para que una tinta roja cuente como
  firme.
- En `particion`:
  - Se borra el texto de los rótulos: en ±10 mm del rótulo, lo que no sigue un tramo
    recto de 3 mm sobre el esqueleto, y los trazos que quedan enteros dentro de ese cuadrado.
  - Si un rótulo no tiene núcleo a 3 mm, toma el núcleo libre más cercano hasta 6 mm.
  - Al unir regiones sin número no cuenta la tinta a ±5 mm del rótulo del lote, y se
    prefiere ese lote. Esto solo aplica a regiones de hasta el doble del lote.
  - Se corrige el error del `c == 0`.
  - (Revisión) El borrado de trazos enteros dentro del cuadrado no toca los que encierran
    un rótulo con un hueco de al menos `CORE_MIN_MM2`: sin esto, un lote chico aislado (un
    enclave de 10–20 mm dibujado suelto dentro de otro lote) se borraba como si fuera el
    texto de su rótulo. No cambia ningún número del set.

**Ojo: desde aquí el set es de desarrollo, no de prueba.** El arreglo se buscó mirando
las métricas de El Arrayán contra su KMZ real, y los otros cuatro planos solo se usaron
para comprobar que no empeoraran. Los números de El Arrayán ya no miden cómo le irá al
método con un plano que no ha visto: eso lo dicen los planos nuevos. Conviene sumar al
set cada plano nuevo con KMZ real y anotar su primera corrida, antes de ajustar nada
con él.

Antes y después, en los 5 planos (IoU what-if mediano / centroide what-if mediano):

| Plano | Antes | Después | Cambio de forma (IoU por lote antes/después) |
|---|---|---|---|
| El Arrayán | 180 lotes; 0,718 / 8,58 m | **183 lotes; 0,947 / 1,22 m** | — |
| Puente Negro | 0,981 / 0,55 m | 0,981 / 0,55 m | mediana 1,000, mínimo 1,000 |
| Algarrobo | 0,979 / 1,53 m | 0,979 / 1,52 m | mediana 1,000, mínimo 0,994 (Hausdorff mediano 10,95 → 11,82 m) |
| Curicó | 0,923 / 1,84 m | 0,923 / 1,83 m | mediana 1,000, mínimo 0,993 |
| Hidango | 58 lotes | 58 lotes | idénticos (mínimo 1,000) |

Cuánto aporta cada pieza a El Arrayán, sacándola del arreglo completo (0,947 / 1,22 m):

| Sin esta pieza | IoU what-if | Centroide what-if |
|---|---|---|
| Borrar el texto de los rótulos | 0,923 | 1,79 m |
| Núcleo más cercano | 0,938 | 1,50 m |
| Unir sin contar la tinta del rótulo | 0,868 | 3,51 m |
| `ROJO_FIRME_FRAC` (queda en 0,35) | 0,804 | 5,81 m |

**Lo que queda.** El Arrayán sigue debajo de la v2 (0,970 / 0,74 m). La causa son los
rectángulos negros del índice de láminas, que cruzan el recuadro y cortan lotes (117, 50,
118, 149 y 106). Un deslinde negro y un marco negro no se distinguen sin saber de qué color
son los deslindes del plano. Se probó una regla "plano rojo" que usaba solo la tinta roja
cuando era una fracción grande de la tinta, y no sirve:
- Algarrobo tiene el perímetro en rojo (21 % de su tinta) y los deslindes en negro.
- El rojo de El Arrayán, solo, deja 62 rótulos en el exterior: parte de sus deslindes se
  lee negra donde cruza los segmentos de camino.

Se deja así. El criterio del spec (IoU what-if ≥ 0,92 y centroide ≤ 2 m) se cumple. Si hace
falta más, la loteadora tapa los marcos con máscaras.

## 3. Memoria: tope de 8 px/mm

Un A0 a 300 dpi (11,8 px/mm, ~140 Mpx) pasaba de 4 GiB. Se decidió reducir la imagen de
trabajo a `pagina.PPMM_TRABAJO_MAXIMO = 8` px/mm (`INTER_AREA`), en vez de poner un tope de
píxeles: un tope cortaría el plano o rechazaría el escaneo, y la reducción conserva todo el
dibujo. Ningún plano del set pasa de 7,87 px/mm, así que ninguno cambia.

Se midió con Puente Negro agrandado ×1,5 en un PDF de la misma hoja: 9.894 × 14.136 =
139,9 Mpx a 11,81 px/mm. El pico es el del proceso con `digitalizar(carpeta)` completo; solo
las bibliotecas ya reservan 1,05 GiB:

| Caso | Trabajo | Pico reservado / en RAM | Segundos | IoU what-if / centroide what-if / Hausdorff what-if |
|---|---|---|---|---|
| PN 140 Mpx sin tope | 11,81 px/mm, 85,8 Mpx | 4,84 / 3,89 GiB | 33 | 0,982 / 0,54 / 1,06 m |
| PN 140 Mpx con tope 8 | 8,00 px/mm, 39,4 Mpx | **3,04 / 2,08 GiB** | 16 | 0,981 / 0,57 / 1,30 m |
| Algarrobo ×2 (101 Mpx) sin tope | 11,81 px/mm, 80,0 Mpx | 4,51 / 3,55 GiB | 30 | — |
| Algarrobo ×2 con tope 8 | 8,00 px/mm, 36,7 Mpx | 2,81 / 1,86 GiB | 15 | — |
| PN original (62 Mpx) | 7,87 px/mm | 2,96 / 2,00 GiB | 14 | 0,981 / 0,55 / 1,19 m |

La exactitud casi no depende de la resolución en el set. Puente Negro a 6 y 7 px/mm da
0,980 / 0,58 m y 0,980 / 0,59 m, contra 0,981 / 0,55 m a 7,87 px/mm. El tope de 8 deja un
margen sobre esos valores y deja el pico de un A0 a 300 dpi en ~2 GiB de RAM.

## 4. Línea base (`regresion/linea_base.json`, escrita con `--actualizar-linea-base`)

| Plano | Lotes / semillas | Pareados / real | IoU tal cual → what-if (mediana) | IoU what-if p10 | Centroide tal cual → what-if (m) | Hausdorff what-if mediana / p10 / p90 (m) | Similitud: giro, escala, dE / dN | Error de área tal cual → what-if | Traslapes / huecos (m²) |
|---|---|---|---|---|---|---|---|---|---|
| Algarrobo | 76 / 76 | 76 / 76 | 0,977 → 0,979 | 0,965 | 1,72 → 1,52 | 11,82 / 3,64 / 25,59 | −0,005°, +0,005 %, −0,08 / +0,22 m | 0,50 % → 0,50 % | 0 / 24.894 |
| Curicó | 87 / 87 | 49 / 49 | 0,760 → 0,923 | 0,860 | 8,07 → 1,83 | 5,19 / 3,35 / 8,02 | +0,151°, +0,073 %, −5,62 / −4,80 m | 2,39 % → 2,50 % | 0 / 8.035 |
| El Arrayán | 183 / 183 | 183 / 183 | 0,674 → 0,947 | 0,692 | 10,59 → 1,22 | 4,46 / 1,30 / 48,25 | +0,290°, +0,219 %, −2,12 / −9,74 m | 1,17 % → 1,01 % | 0 / 4.511 |
| Hidango | 58 / 58 | sin anclas ni cuadrícula | | | | | | | |
| Puente Negro | 65 / 65 | 58 / 58 | 0,847 → 0,981 | 0,962 | 5,27 → 0,55 | 1,19 / 0,55 / 3,47 | +0,216°, +0,882 %, −4,07 / −2,99 m | 2,09 % → 0,40 % | 0 / 223 |

Notas:
- "Huecos" son las caras sin número dentro del contorno: caminos y sobrantes que el plano
  dibuja cerrados. No hay traslapes en ningún plano.
- El p90 de Hausdorff de El Arrayán (48 m) son los lotes cortados por los marcos de lámina.
- La corrida completa toma ~1,5 min.
