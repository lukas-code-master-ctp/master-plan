"""El contorno de cada etapa, para encerrar sus parcelas en el visor.

Con varias etapas, la pastilla dice solo el número ("28") y la etapa tiene que
leerse de otra forma: como en el plano, una línea que rodea todas sus parcelas.
Las parcelas de una etapa no se tocan entre sí (las separan caminos internos), así
que se unen cerrando esos huecos: se engordan y se vuelven a adelgazar lo mismo,
y el borde queda sobre el contorno de afuera de las parcelas.
"""
from __future__ import annotations

from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from . import geo

# Lo que se cierra entre parcelas de la misma etapa: el doble de esto. Un camino
# interno tiene de 8 a 20 m; un estero o una quebrada que parten la etapa, más.
CIERRE_M = 15.0
# Sin esto el contorno lleva cada quiebre de cada parcela y pesa más que ellas.
SIMPLIFICACION_M = 1.5


def contornos(parcelas: list[tuple[int | None, geo.Anillo]]) -> list[tuple[int, list[geo.Anillo]]]:
    """(etapa, anillo) de cada parcela → (etapa, anillos exteriores) de cada etapa.

    Sin al menos dos etapas no hay nada que separar y no devuelve nada.
    """
    por_etapa: dict[int, list[geo.Anillo]] = {}
    for etapa, anillo in parcelas:
        if etapa is not None and len(anillo) >= 3:
            por_etapa.setdefault(etapa, []).append(anillo)
    if len(por_etapa) < 2:
        return []

    todos = [p for anillos in por_etapa.values() for anillo in anillos for p in anillo]
    origen = (sum(p[0] for p in todos) / len(todos), sum(p[1] for p in todos) / len(todos))
    resultado = []
    for etapa in sorted(por_etapa):
        poligonos = [Polygon([geo.a_metros(p, origen) for p in anillo]).buffer(0)
                     for anillo in por_etapa[etapa]]
        union = (unary_union(poligonos).buffer(CIERRE_M, join_style="mitre")
                 .buffer(-CIERRE_M, join_style="mitre").simplify(SIMPLIFICACION_M))
        partes = union.geoms if isinstance(union, MultiPolygon) else [union]
        anillos = [[geo.desde_metros(xy, origen) for xy in list(parte.exterior.coords)[:-1]]
                   for parte in partes if not parte.is_empty]
        if anillos:
            resultado.append((etapa, anillos))
    return resultado
