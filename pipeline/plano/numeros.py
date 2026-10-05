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


def segun_cuadro(numero, oficiales) -> str:
    """`numero` corregido con el cuadro de superficies (`oficiales`: sus números). Si no
    está en el cuadro y el cuadro trae uno solo con el mismo número dentro del sector
    pero otro sector, es ese: el lector confunde el 8 con el 6 o el 3 (Caminos de Rapel:
    "6-09" por "8-09", y el lote quedaba sin área oficial). Si no, queda como viene."""
    oficiales = [str(n) for n in oficiales]
    if not oficiales or any(mismo_lote(numero, n) for n in oficiales) or "-" not in clave(numero):
        return str(numero)
    n = ultimo(numero)
    parecidos = [o for o in oficiales if "-" in clave(o) and ultimo(o) == n]
    return parecidos[0] if len(parecidos) == 1 else str(numero)


def repetidos(numeros) -> list[str]:
    """Los números (como vienen) cuya clave aparece más de una vez."""
    numeros = [str(n) for n in numeros]
    claves = [clave(n) for n in numeros]
    cuenta = Counter(claves)
    return sorted({n for n, c in zip(numeros, claves) if cuenta[c] > 1})


# Más números seguidos que esto sin ninguno no es un hueco: es otra serie, otra etapa o
# un número que no es de lote (una cota leída como rótulo). El lector pierde rótulos
# sueltos (Caminos de Rapel: 8-03, 8-05, 8-11); Curicó salta tramos de 4 a 9 números
# que no están en ese plano (5–9, 15–18, 42–48).
SALTO_MAX = 3


def _serie(numero) -> tuple[str, int] | None:
    """("8-", 1) para "8-01"; ("A", 3) para "A03"; ("", 12) para "12"."""
    m = re.fullmatch(r"(.*?)(\d+)", clave(numero))
    return (m.group(1), int(m.group(2))) if m else None


def _como(plantilla: str, n: int) -> str:
    """`n` escrito como `plantilla`, un número de su serie: ("8-01", 3) → "8-03"."""
    m = re.search(r"(\d+)\D*$", plantilla)
    if not m:
        return str(n)
    digitos = m.group(1)
    return plantilla[:m.start(1)] + (str(n).zfill(len(digitos)) if digitos.startswith("0") else str(n))


def esperados(cuadro) -> list[str]:
    """Los números del cuadro de superficies que deben ser lotes del dibujo: todos menos
    el resto de la propiedad. El resto es la fila cuyo número es el sector de las demás
    ("8 o resto de la propiedad, 760.000 m²" en un cuadro de "8-01" a "8-16"): es el
    predio que queda, no un lote de la situación propuesta, y no se avisa como faltante.
    Su área sigue en el cuadro: si una cara lleva ese número, la tiene."""
    numeros = [str(n) for n in cuadro]
    sectores = {s[0].rstrip("-") for s in map(_serie, numeros) if s and s[0]}
    return [n for n in numeros if "-" in clave(n) or clave(n) not in sectores]


def huecos(numeros, esperados=(), junto=None) -> list[str]:
    """Los números que faltan en la numeración, escritos como su serie.

    Por sector ("8-01" es el 1 del sector 8): los enteros que faltan entre el menor y el
    mayor de los leídos ("8-01", "8-02", "8-04" → "8-03"), sin contar saltos de más de
    SALTO_MAX. Con `esperados` (los números del cuadro de superficies) también los del
    cuadro que no están, si el cuadro calza con lo leído (la mitad o más de sus números
    está): así sale también el último ("8-16").

    `junto`: si se da, los números de los lotes que tocan una cara sin número del tamaño
    de un lote. Un hueco de la serie solo se dice si el lote anterior o el siguiente que
    sí está es uno de esos: el lote que falta suele ser esa cara (Caminos de Rapel). Sin
    una cara así al lado, el hueco suele ser un lote que esa lámina no dibuja (Curicó:
    11–13, 50–51, 120–122) y avisarlo es ruido. Los del cuadro se dicen siempre."""
    numeros = [str(n) for n in numeros]
    series: dict[str, dict[int, str]] = {}
    for texto in numeros:
        s = _serie(texto)
        if s:
            series.setdefault(s[0], {}).setdefault(s[1], texto)
    plantillas = {}
    for sector, vistos in series.items():
        # Si alguno trae ceros a la izquierda, la serie los usa.
        plantillas[sector] = next((v for v in vistos.values() if re.search(r"(?:^|\D)0\d+\D*$", v)),
                                  next(iter(vistos.values())))
    vecinos = None if junto is None else {clave(n) for n in junto}
    faltan: dict[tuple[str, int], str] = {}
    for sector, vistos in series.items():
        orden = sorted(vistos)
        for a, b in zip(orden, orden[1:]):
            if vecinos is not None and not {clave(vistos[a]), clave(vistos[b])} & vecinos:
                continue
            if b - a - 1 <= SALTO_MAX:
                for n in range(a + 1, b):
                    faltan[(sector, n)] = _como(plantillas[sector], n)
    esperados = [str(e) for e in esperados]
    if esperados and 2 * sum(any(mismo_lote(e, n) for n in numeros) for e in esperados) >= len(esperados):
        for e in esperados:
            s = _serie(e)
            if s is None or any(mismo_lote(e, n) for n in numeros):
                continue
            sector, n = s
            # El cuadro puede listar "16" en un loteo "8-16": va con la única serie que hay.
            if sector not in series and len(series) == 1:
                sector = next(iter(series))
            if (sector, n) not in faltan:
                faltan[(sector, n)] = _como(plantillas[sector], n) if sector in plantillas else e
    return [faltan[k] for k in sorted(faltan)]
