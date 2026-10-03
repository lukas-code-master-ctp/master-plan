# normalizar_id: una letra de sector solo cuenta si está suelta

## Problema

`pipeline/kmz.py:normalizar_id` nombra los lotes al construir un master (ids del KMZ) y
cruza el inventario (Excel, CRM). Su rama "con letra de sector" busca **cualquier letra
seguida de un número**, también la última letra de una palabra:

| Entrada | Hoy | Debería |
|---|---|---|
| `LOTE12` | `E12` | `12` |
| `Parcela 4` | `A4` | `4` |
| `ROL 273-15` | `L273` | `None` (un rol no es un lote) |

Hoy ningún plano ni inventario real del set lo gatilla (revisado el 2026-10-02 en 7 KMZ
reales y 2 planillas), pero un inventario con "LOTE12" o "Parcela 4" se cruzaría mal sin
aviso.

## Regla nueva

- **Letra de sector**: solo una letra **suelta**, que no sea la cola de una palabra:
  `A214`, `A 214`, `LOTE A 420`, `SECTOR B 12`, `E12`.
- **Palabras de lote**: `LOTE`, `LOTES` y `PARCELA`, `PARCELAS` se quitan, también pegadas
  al número (`LOTE12`, `PARCELA4`).
- Cualquier otra palabra delante del número (`ROL`, `MANZANA`, `ETAPA`, fechas, áreas) da
  `None`, como ya pasaba con los números sueltos.
- Lo demás no cambia: el par sector-lote `7-1`, `LOTE 8-01` → `8-1`, `LOTE-12` → `12`, los
  floats `12.0` → `12`.

## Seguridad

Este cambio sí altera salidas que hoy no son `None`, a diferencia del ajuste anterior.
Para eso:

- Una prueba de propiedad compara la versión anterior y la nueva sobre un corpus grande y
  realista, y **lista cada salida que cambia**. La lista va en el PR para que el usuario la
  revise antes de mergear.
- Se verifica contra los KMZ reales y las planillas que hay en el repo y en el set de
  regresión (fuera de git): ningún id real debe cambiar.
- pytest (en Docker) y la regresión de `pipeline.plano` pasan.
