"""Proyección de parcelas del suelo a coordenadas angulares de la panorámica.

El resultado son anillos de (azimut, elevación) en grados. Se guardan así y no en
píxeles a propósito: el overlay queda independiente del tamaño de imagen que se
sirva, y el visor convierte a dirección 3D directamente.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable

from . import geo
from .config import (
    ANCHO_ANGULAR_MINIMO_GRADOS,
    AREA_ANGULAR_MINIMA_GRADOS2,
    DECIMALES_ANGULO,
    DEPRESION_MINIMA_GRADOS,
    DISTANCIA_MAXIMA_M,
    SEGMENTO_MAXIMO_GRADOS,
)

ModeloTerreno = Callable[[geo.Punto], float]


@dataclass(frozen=True)
class Vista:
    """Una panorámica: dónde estaba el dron y hacia dónde mira la columna x=0."""
    id: str
    posicion: int
    lon: float
    lat: float
    altura_relativa: float   # metros sobre el punto de despegue
    altura_absoluta: float   # metros sobre el nivel del mar
    rumbo0: float            # azimut de la columna x=0, en grados

    @property
    def origen(self) -> geo.Punto:
        return (self.lon, self.lat)

    def terreno_plano(self) -> float:
        """Cota del suelo asumiendo terreno plano a la altura del despegue."""
        return self.altura_absoluta - self.altura_relativa


@dataclass
class ParcelaProyectada:
    id: str
    anillo: list[tuple[float, float]]   # (azimut, elevación) en grados
    centro: tuple[float, float]
    distancia_m: float
    ancho_angular: float                # diámetro angular, en grados
    area_angular: float                 # superficie en el campo visual, en grados²


def proyectar_punto(vista: Vista, punto: geo.Punto,
                    cota_terreno: float | None = None) -> tuple[float, float, float]:
    """(lon, lat) → (azimut, elevación, distancia horizontal).

    La elevación es negativa cuando el punto está bajo el horizonte, que es el caso
    de todo el suelo visto desde el dron.
    """
    este, norte = geo.a_metros(punto, vista.origen)
    distancia = math.hypot(este, norte)
    if distancia < 1e-6:
        return 0.0, -90.0, 0.0

    cota = vista.terreno_plano() if cota_terreno is None else cota_terreno
    caida = vista.altura_absoluta - cota

    azimut = math.degrees(math.atan2(este, norte)) % 360.0
    elevacion = -math.degrees(math.atan2(caida, distancia))
    return azimut, elevacion, distancia


def direccion(azimut: float, elevacion: float) -> tuple[float, float, float]:
    """Vector unitario. X este, Y norte, Z arriba."""
    az = math.radians(azimut)
    el = math.radians(elevacion)
    coseno = math.cos(el)
    return (coseno * math.sin(az), coseno * math.cos(az), math.sin(el))


def separacion_angular(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Ángulo en grados entre dos direcciones dadas como (azimut, elevación)."""
    ax, ay, az = direccion(*a)
    bx, by, bz = direccion(*b)
    producto = max(-1.0, min(1.0, ax * bx + ay * by + az * bz))
    return math.degrees(math.acos(producto))


def area_angular(anillo: list[tuple[float, float]], centro: tuple[float, float]) -> float:
    """Cuánto ocupa el polígono en el campo visual, en grados cuadrados.

    Es la medida que importa para decidir si vale la pena mostrarlo: una parcela
    lejana puede ser ancha y aun así ser una astilla imposible de clickear, porque
    la profundidad se aplasta contra el horizonte.

    Se proyecta al plano tangente a la dirección del centro (proyección gnomónica) y
    se aplica el cordón de zapato. Para polígonos de pocos grados el error es ínfimo.
    """
    if len(anillo) < 3:
        return 0.0

    normal = direccion(*centro)
    este = _normalizar(_producto_cruz(normal, (0.0, 0.0, 1.0)))
    if este is None:                       # el centro apunta al cenit o al nadir
        este = _normalizar(_producto_cruz(normal, (0.0, 1.0, 0.0)))
    norte = _producto_cruz(normal, este)

    planos = []
    for vertice in anillo:
        d = direccion(*vertice)
        profundidad = _producto_punto(d, normal)
        if profundidad <= 1e-6:            # a más de 90° del centro: no es una parcela
            return 0.0
        t = tuple(componente / profundidad for componente in d)
        planos.append((_producto_punto(t, este), _producto_punto(t, norte)))

    suma = sum(x1 * y2 - x2 * y1
               for (x1, y1), (x2, y2) in zip(planos, planos[1:] + planos[:1]))
    return abs(suma) / 2.0 * (180.0 / math.pi) ** 2


def _producto_cruz(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _producto_punto(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _normalizar(v):
    largo = math.sqrt(_producto_punto(v, v))
    if largo < 1e-9:
        return None
    return (v[0] / largo, v[1] / largo, v[2] / largo)


def proyectar_parcela(
    vista: Vista,
    identificador: str,
    anillo: geo.Anillo,
    terreno: ModeloTerreno | None = None,
    segmento_maximo: float = SEGMENTO_MAXIMO_GRADOS,
) -> ParcelaProyectada | None:
    """Proyecta un polígono, subdividiendo las aristas para conservar su curvatura.

    Una recta en el suelo no es una recta en la panorámica: es un arco. Subdividir
    cada arista hasta que ningún segmento supere `segmento_maximo` grados hace que
    el overlay siga el terreno en vez de cortarlo en diagonal.
    """
    if len(anillo) < 3:
        return None

    cota = (lambda p: terreno(p)) if terreno else (lambda p: vista.terreno_plano())

    proyectados: list[tuple[float, float]] = []
    for inicio, fin in zip(anillo, anillo[1:] + anillo[:1]):
        a = proyectar_punto(vista, inicio, cota(inicio))
        b = proyectar_punto(vista, fin, cota(fin))
        pasos = max(1, math.ceil(separacion_angular(a[:2], b[:2]) / segmento_maximo))
        for paso in range(pasos):
            fraccion = paso / pasos
            intermedio = (inicio[0] + (fin[0] - inicio[0]) * fraccion,
                          inicio[1] + (fin[1] - inicio[1]) * fraccion)
            azimut, elevacion, _ = proyectar_punto(vista, intermedio, cota(intermedio))
            proyectados.append((azimut, elevacion))

    centro_geo = geo.centroide(anillo)
    az_centro, el_centro, distancia = proyectar_punto(vista, centro_geo, cota(centro_geo))
    centro = (az_centro, el_centro)
    ancho = 2 * max(separacion_angular(centro, v) for v in proyectados)

    return ParcelaProyectada(
        id=identificador,
        anillo=[(round(a, DECIMALES_ANGULO), round(e, DECIMALES_ANGULO))
                for a, e in proyectados],
        centro=(round(az_centro, DECIMALES_ANGULO), round(el_centro, DECIMALES_ANGULO)),
        distancia_m=round(distancia, 1),
        ancho_angular=round(ancho, 3),
        area_angular=round(area_angular(proyectados, centro), 3),
    )


def es_visible(parcela: ParcelaProyectada,
               distancia_maxima: float = DISTANCIA_MAXIMA_M,
               ancho_minimo: float = ANCHO_ANGULAR_MINIMO_GRADOS,
               area_minima: float = AREA_ANGULAR_MINIMA_GRADOS2,
               depresion_minima: float = DEPRESION_MINIMA_GRADOS) -> bool:
    """Descarta lo que no sirve: demasiado lejos, demasiado chico, o al ras del horizonte.

    El área importa más que el ancho: a mucha distancia la profundidad de la parcela
    se aplasta contra el horizonte y queda una astilla ancha pero imposible de clickear.
    """
    if parcela.distancia_m > distancia_maxima:
        return False
    if parcela.ancho_angular < ancho_minimo:
        return False
    if parcela.area_angular < area_minima:
        return False
    if parcela.centro[1] > -depresion_minima:
        return False
    return True


def proyectar_vista(
    vista: Vista,
    parcelas: Iterable[tuple[str, geo.Anillo]],
    terreno: ModeloTerreno | None = None,
    **filtros,
) -> list[ParcelaProyectada]:
    """Proyecta todas las parcelas visibles desde una vista, de cerca a lejos."""
    resultado = []
    for identificador, anillo in parcelas:
        proyectada = proyectar_parcela(vista, identificador, anillo, terreno)
        if proyectada and es_visible(proyectada, **filtros):
            resultado.append(proyectada)
    resultado.sort(key=lambda p: p.distancia_m)
    return resultado
