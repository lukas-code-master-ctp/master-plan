# normalizar_id: qué salidas cambian

Acompaña a `2026-10-03-normalizar-id.md`. Lista, para revisar antes de mergear, cada
forma de nombre cuya salida cambia entre la versión anterior de `normalizar_id` y la
nueva. Sale de la prueba `pipeline/tests/test_normalizar_id_cambios.py`, que exige que
**todo** cambio caiga en uno de estos cinco casos (si aparece otro, la prueba falla).

## Regla final

- La **letra de sector** cuenta si está suelta (no es la cola ni la cabeza de una
  palabra) y no hay ningún número antes de ella, salvo el de "ETAPA n": `A214`, `A 214`,
  `LOTE A 420`, `SECTOR B 12`, `ETAPA 2 LOTE A 5` → `A214`, `A214`, `A420`, `B12`, `A5`.
  Tras un número la letra es una unidad o un sufijo: `1.342 m2`, `1342 M2`, `12 A 5` →
  None (`12 A` ya daba None).
- **LOTE, LOTES, PARCELA, PARCELAS, SITIO, SITIOS** se quitan sueltas, pegadas al número
  o con guion o # (`LOTE12`, `LOTES12`, `LOTES 12`, `Parcela 4`, `PARCELA-12`, `Sitio 5`
  → `12`, `12`, `12`, `4`, `12`, `5`), y también pegadas a **una sola letra que va pegada al número**: `LOTEA12`,
  `LOTESA12`, `PARCELAB3` → `A12`, `A12`, `B3`, como antes. Con espacio entre la letra y el
  número es otra palabra: `LOTEO 12`, `LOTEA 12`, `LOTEADORA 12` → None.
- Cualquier otra palabra delante del número da None: `ROL 273-15`, `MANZANA 3`, `Mz 3`.
- Sin cambios: pares `7-1`, `LOTE 8-01` → `8-1`; `LOTE-12`, `LOTE #12` → `12`; floats
  `12.0` → `12`; fechas y `5,00hás` → None.

## Corpus

30.575 entradas: 10.575 armadas a mano y combinando LOTE/Lote/lote, PARCELA, SITIO,
letras de sector, separadores " ", "-", "#", ceros a la izquierda, pares "8-01", floats,
ROL, MZ, MANZANA, ETAPA, SECTOR, MICROSITIO, fechas, áreas ("1.342 m2", "5,00 ha") y
número + letra + número; más 20.000 combinaciones al azar con semilla fija. Cambian 9.156
(8.132 distintas). No hay datos de clientes. "Distintos" cuenta entradas distintas en
todo el corpus; "Del corpus armado", solo en la parte armada a mano.

## Por caso

| Caso | Distintos | Del corpus armado | Ejemplos (entrada: antes → ahora) |
|---|---:|---:|---|
| `lote_pegado`: LOTE o LOTES pegado al número | 259 | 104 | `LOTE1`: E1 → 1; `LOTES1`: S1 → 1; `LOTE7-1`: E7 → 7-1 |
| `parcela_como_lote`: PARCELA(S) y SITIO(S) se leen como LOTE | 1.867 | 1.456 | `PARCELA1`: A1 → 1; `Parcela 4`: A4 → 4; `Sitio 5`: O5 → 5; `PARCELA#1`: None → 1 |
| `palabra_de_lote_con_otras_palabras`: la letra era la cola de LOTE/PARCELA/SITIO, pero hay más texto pegado | 84 | 0 | `_Lote7`: E7 → None; `_LOTES12`: S12 → None; `Lote042E11`: E42 → None |
| `numero_antes_de_la_letra`: la letra venía después de un número | 1.387 | 597 | `1.342 m2`: M2 → None; `5.000 M2`: M2 → None; `12 A 5`: A5 → None |
| `cola_de_otra_palabra`: la letra era la cola de otra palabra | 4.535 | 2.120 | `ROL 273-15`: L273 → None; `MZ1`: Z1 → None; `ETAPA 2 LOTE A 5`: A2 → A5 |

En `lote_pegado` y `parcela_como_lote`, la salida nueva es exactamente la que la versión
anterior daba con LOTE escrito aparte ("LOTE 12"). En `numero_antes_de_la_letra` la
salida nueva es siempre None. En los demás, None o la letra suelta que viene después de
la palabra.

## `cola_de_otra_palabra`, por palabra (corpus armado)

| Palabra | Distintos | Ejemplos |
|---|---:|---|
| ROL | 344 | `ROL1`: L1 → None |
| MZ, MANZANA | 402 | `MZ1`: Z1 → None; `MANZANA1`: A1 → None |
| ETAPA | 100 | `ETAPA1`: A1 → None; `ETAPA 2 LOTE A 1`: A2 → A1 |
| SECTOR, MICROSITIO, CASA, CAMINO | 400 | `SECTOR1`: R1 → None; `CASA1`: A1 → None; `MICROSITIO 1`: O1 → None |
| SUBLOTE, LOTEO, LOTEADORA | 171 | `SUBLOTE1`: E1 → None; `LOTEO 1`: O1 → None; `LOTEADORA 12`: A12 → None |
| AÑO, No | 200 | `AÑO1`: O1 → None; `No1`: O1 → None |
| LOTE/PARCELA/SITIO + letra, con espacio antes del número | 502 | `LOTEA 1`: A1 → None; `LOTESB 1`: B1 → None; `PARCELAA 1`: A1 → None; `SITIOA 1`: A1 → None |
| ARRAYÁN (palabra con tilde) | 1 | `ARRAYÁN 12`: N12 → None |

`LOTEA12` y `SITIOA12` (sin espacio) no cambian: dan `A12` antes y ahora.

## Datos reales

Ningún id real cambia: 1.731 valores revisados (697 nombres de placemark de los 6 KMZ —
Talhuenes y los 5 `real.kmz` del set de regresión—, 62 ids de
`trabajo_talhuenes/planilla_talhuenes.xlsx` y 486 números de las `entradas*.json` del set
de regresión, cada uno tal cual y como "LOTE n", más su `numeros.clave`).

Revisado de nuevo el 2026-10-03 (revisión adversarial), de punta a punta con
`leer_kmz` y `leer_excel` (versión anterior contra la nueva): los mismos ids en los 7 KMZ
—los de arriba más `KMZ HACIENDA VICHUQUEN  SOLO LOTES A ALZARSE.kmz`— y en las 2
planillas —`planilla_talhuenes.xlsx` y `datos_masterplan.xlsx` (202 fichas)—. Solo cambian
celdas que no son ids (la columna de parcelación "HACIENDA VICHUQUEN ETAPA 1", un link de
pago), que `normalizar_id` no lee.

## Formatos fuera del spec (revisión adversarial)

`SITIO` se agregó a las palabras de lote: con la regla del spec, "Sitio 5" pasaba de `O5`
a None y un loteo que nombra sus lotes "Sitio n" (común en Chile) se quedaba sin ids en
el KMZ y sin fichas en la planilla. Ahora da `5`, como "Parcela 5".

Estos pasan de un id con una letra sacada de la palabra a None. Se aceptan: el id
anterior era incorrecto (nunca cruzaba con una planilla que dijera "12" o "A12"), y el
build lo muestra ("0 parcelas con nombre, n polígonos sin identificar"):

| Entrada | Antes | Ahora |
|---|---|---|
| `LT 12`, `Lte 12`, `Parc 12`, `Pc 12` | T12, E12, C12, C12 | None |
| `Nro 12`, `Lote Nro 12`, `Lote No 12` | O12 | None |
| `Hijuela 3`, `Casa 3`, `Macrolote 3`, `Sublote 3-1` | A3, A3, E3, E3 | None |
| `Polygon 12`, `Polígono 12`, `VENDIDO Lote 12` | N12, O12, O12 | None |
| `Lote 3 Etapa 2`, `LOTE 5 - ETAPA 1` | A2, A1 (todos los lotes de la etapa chocaban) | None |
| `Lote 12 (1.342 m2)`, `Parcela 4A`, `Parcela 12-B`, `Lote 12 y 13` | M2, A4, A12, Y13 | None |

Sin cambio (None antes y ahora; no los reconoce ninguna de las dos): `Lote N°12`,
`Lote Nº 12`, `N° 12`, `L-12`, `A-12`, `12-B`, `Lote 12 B`, `12A`, `Lote A-1`.
