"""Geometría plana local.

El loteo abarca ~2 km. A esa escala, proyectar a metros con un factor constante por
latitud tiene un error muy por debajo del ancho de una línea, y evita arrastrar una
librería de proyecciones.
"""
from __future__ import annotations

import math

Punto = tuple[float, float]   # (lon, lat) en grados
Anillo = list[Punto]

METROS_POR_GRADO_LAT = 111320.0


def metros_por_grado_lon(latitud: float) -> float:
    return METROS_POR_GRADO_LAT * math.cos(math.radians(latitud))


def a_metros(punto: Punto, origen: Punto) -> tuple[float, float]:
    """(lon, lat) → (este, norte) en metros respecto de `origen`."""
    escala_lon = metros_por_grado_lon(origen[1])
    return ((punto[0] - origen[0]) * escala_lon,
            (punto[1] - origen[1]) * METROS_POR_GRADO_LAT)


def distancia(a: Punto, b: Punto) -> float:
    """Simétrica: la escala se toma en la latitud media de los dos puntos."""
    escala_lon = metros_por_grado_lon((a[1] + b[1]) / 2)
    return math.hypot((a[0] - b[0]) * escala_lon,
                      (a[1] - b[1]) * METROS_POR_GRADO_LAT)


def _origen(anillo: Anillo) -> Punto:
    """Centro de referencia de un anillo.

    Se usa el promedio de los vértices y no el primero, para que el área y el
    centroide no cambien según por dónde empiece el anillo ni en qué sentido gire.
    """
    return (sum(p[0] for p in anillo) / len(anillo),
            sum(p[1] for p in anillo) / len(anillo))


def area_m2(anillo: Anillo) -> float:
    """Área por la fórmula del cordón de zapato, sobre la proyección local."""
    if len(anillo) < 3:
        return 0.0
    origen = _origen(anillo)
    puntos = [a_metros(p, origen) for p in anillo]
    if puntos[0] != puntos[-1]:
        puntos.append(puntos[0])
    suma = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(puntos, puntos[1:]))
    return abs(suma) / 2.0


def centroide(anillo: Anillo) -> Punto:
    """Centroide del área, no de los vértices."""
    if len(anillo) < 3:
        return anillo[0] if anillo else (0.0, 0.0)
    origen = _origen(anillo)
    puntos = [a_metros(p, origen) for p in anillo]
    if puntos[0] != puntos[-1]:
        puntos.append(puntos[0])

    doble_area = 0.0
    cx = cy = 0.0
    for (x1, y1), (x2, y2) in zip(puntos, puntos[1:]):
        cruz = x1 * y2 - x2 * y1
        doble_area += cruz
        cx += (x1 + x2) * cruz
        cy += (y1 + y2) * cruz

    if abs(doble_area) < 1e-9:
        media_x = sum(x for x, _ in puntos[:-1]) / (len(puntos) - 1)
        media_y = sum(y for _, y in puntos[:-1]) / (len(puntos) - 1)
        cx_m, cy_m = media_x, media_y
    else:
        cx_m, cy_m = cx / (3 * doble_area), cy / (3 * doble_area)

    escala_lon = metros_por_grado_lon(origen[1])
    return (origen[0] + cx_m / escala_lon, origen[1] + cy_m / METROS_POR_GRADO_LAT)


def contiene(anillo: Anillo, punto: Punto) -> bool:
    """Punto en polígono por conteo de cruces."""
    x, y = punto
    dentro = False
    n = len(anillo)
    for i in range(n):
        x1, y1 = anillo[i]
        x2, y2 = anillo[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            corte = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < corte:
                dentro = not dentro
    return dentro


def caja(anillo: Anillo) -> tuple[float, float, float, float]:
    """(lon_min, lat_min, lon_max, lat_max)."""
    lons = [p[0] for p in anillo]
    lats = [p[1] for p in anillo]
    return min(lons), min(lats), max(lons), max(lats)
