"""Números de lote: se guardan como vienen y se comparan normalizados.

El número va tal como está en el plano o como lo escribió la loteadora ("8-01",
"10-6", "12"): así sale en el KMZ ("LOTE 8-01"). Para comparar (repetidos, emparejar
con el KMZ real, con el cuadro de superficies) se usa la clave de
`pipeline.kmz.normalizar_id`, la misma con que el pipeline del master lee los KMZ:
"8-01", "8-1" y "LOTE 8-01" son el mismo lote.
"""
from __future__ import annotations

import re
from collections import Counter

from ..kmz import normalizar_id


def clave(numero) -> str:
    """"8-01", "8-1", "LOTE 8-01" → "8-1"; "012" → "12". Lo que `normalizar_id` no
    reconoce se compara en mayúsculas y sin espacios."""
    # "LOTE12" pegado: sin esto `normalizar_id` toma la E de LOTE como letra de sector.
    texto = re.sub(r"^LOTES?(?=\d)", "", str(numero).strip().upper())
    return normalizar_id(f"LOTE {texto}") or re.sub(r"\s+", "", texto)


def ultimo(numero) -> int | None:
    """El número del lote dentro de su sector: "8-01" → 1, "12" → 12; None si no es
    un número."""
    m = re.search(r"(\d+)\s*$", clave(numero))
    return int(m.group(1)) if m else None


def mismo_lote(a, b) -> bool:
    """Mismo número normalizado, o uno trae el sector y el otro no ("10-6" y "6"): en
    Hidango los rótulos dicen "LOTE 10-6" y la loteadora puede marcar solo el 6."""
    ca, cb = clave(a), clave(b)
    if ca == cb:
        return True
    if ("-" in ca) == ("-" in cb):
        return False
    return ultimo(ca) is not None and ultimo(ca) == ultimo(cb)


def buscar(por_numero: dict, numero):
    """El valor de `numero` en `por_numero` (claves de cualquier forma): primero por
    clave igual y, si no, el único que es `mismo_lote`. None si no hay o es ambiguo."""
    c = clave(numero)
    iguales = [v for k, v in por_numero.items() if clave(k) == c]
    if iguales:
        return iguales[0]
    parecidos = [v for k, v in por_numero.items() if mismo_lote(k, numero)]
    return parecidos[0] if len(parecidos) == 1 else None


def repetidos(numeros) -> list[str]:
    """Los números (como vienen) cuya clave aparece más de una vez."""
    numeros = [str(n) for n in numeros]
    claves = [clave(n) for n in numeros]
    cuenta = Counter(claves)
    return sorted({n for n, c in zip(numeros, claves) if cuenta[c] > 1})
