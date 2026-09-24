"""Modelo de elevación del terreno.

La proyección asume por defecto que el suelo es plano a la cota del despegue. En un
loteo con ladera eso corre los polígonos lejanos decenas de metros: un lote 24 m más
abajo que el despegue, a 600 m del dron, se dibuja 60 m más lejos de lo que está.

El DEM sale de las teselas Terrarium de AWS Open Data (Mapzen/Tilezen): PNG de
256 px donde cada píxel codifica la cota como R·256 + G + B/256 − 32768. A zoom 14
son ~7,7 m por píxel a esta latitud; el dato de origen es SRTM/Copernicus de 30 m.
No necesita llave ni librerías de GIS, y las teselas quedan en caché en disco.
"""
from __future__ import annotations

import io
import math
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from . import geo
from .proyeccion import ModeloTerreno, Vista

ZOOM = 14
LADO = 256
URL_TESELA = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
DESPLAZAMIENTO = 32768.0

# Alrededor de la caja del loteo, para que los bordes también interpolen bien.
MARGEN_M = 300.0

Descarga = Callable[[str], bytes]


@dataclass(frozen=True)
class Terreno:
    zoom: int
    x0: int                  # tesela de la esquina noroeste del mosaico
    y0: int
    cotas: np.ndarray        # mosaico de cotas en metros (filas, columnas)

    @property
    def metros_por_pixel(self) -> float:
        lat = a_coordenada((self.x0 * LADO + self.cotas.shape[1] / 2,
                            self.y0 * LADO + self.cotas.shape[0] / 2), self.zoom)[1]
        return 40075016.686 * math.cos(math.radians(lat)) / (LADO * 2 ** self.zoom)

    def cota(self, punto: geo.Punto) -> float:
        """Cota del terreno en un punto, interpolando entre los cuatro píxeles vecinos."""
        gx, gy = a_pixel_global(punto, self.zoom)
        alto, ancho = self.cotas.shape
        # El valor del píxel corresponde a su centro.
        px = min(max(gx - self.x0 * LADO - 0.5, 0.0), ancho - 1.0)
        py = min(max(gy - self.y0 * LADO - 0.5, 0.0), alto - 1.0)
        j, i = int(px), int(py)
        fj, fi = px - j, py - i
        j2, i2 = min(j + 1, ancho - 1), min(i + 1, alto - 1)
        c = self.cotas
        return float(c[i, j] * (1 - fi) * (1 - fj) + c[i, j2] * (1 - fi) * fj
                     + c[i2, j] * fi * (1 - fj) + c[i2, j2] * fi * fj)


def cargar(caja: tuple[float, float, float, float], cache: Path, margen_m: float = MARGEN_M,
           zoom: int = ZOOM, descarga: Descarga = None) -> Terreno:
    """El terreno que cubre una caja (lon_min, lat_min, lon_max, lat_max) más un margen."""
    descarga = descarga or descargar
    lon_min, lat_min, lon_max, lat_max = caja
    dlat = margen_m / geo.METROS_POR_GRADO_LAT
    dlon = margen_m / geo.metros_por_grado_lon((lat_min + lat_max) / 2)

    xa, ya = a_pixel_global((lon_min - dlon, lat_max + dlat), zoom)   # noroeste
    xb, yb = a_pixel_global((lon_max + dlon, lat_min - dlat), zoom)   # sureste
    tx0, ty0, tx1, ty1 = int(xa // LADO), int(ya // LADO), int(xb // LADO), int(yb // LADO)

    filas = []
    for ty in range(ty0, ty1 + 1):
        fila = [decodificar(_tesela(tx, ty, zoom, Path(cache), descarga))
                for tx in range(tx0, tx1 + 1)]
        filas.append(np.hstack(fila))
    return Terreno(zoom=zoom, x0=tx0, y0=ty0, cotas=np.vstack(filas))


def cota_en(punto: geo.Punto, cache: Path, zoom: int = ZOOM) -> float:
    """La cota de un punto suelto, lejos del loteo: baja solo la tesela que lo contiene."""
    return cargar((punto[0], punto[1], punto[0], punto[1]), cache, margen_m=50.0, zoom=zoom).cota(punto)


def modelo_para_vista(terreno: Terreno, vista: Vista, despegue: geo.Punto) -> ModeloTerreno:
    """Cota de cada punto en el datum del dron.

    El dron mide alturas respecto del punto de despegue, y su "altura absoluta" viene
    en un datum propio que no calza con el del DEM. Así que el DEM solo aporta los
    desniveles: la cota del despegue es la que dice el dron, y cada punto queda a
    tantos metros por sobre o por debajo de ella como diga el DEM.
    """
    base = vista.terreno_plano() - terreno.cota(despegue)
    return lambda punto: base + terreno.cota(punto)


def descargar(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as respuesta:
        return respuesta.read()


def decodificar(png: bytes) -> np.ndarray:
    canales = np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), dtype=np.float64)
    return canales[..., 0] * 256 + canales[..., 1] + canales[..., 2] / 256 - DESPLAZAMIENTO


def a_pixel_global(punto: geo.Punto, zoom: int = ZOOM) -> tuple[float, float]:
    """(lon, lat) → píxel en la cuadrícula Web Mercator del zoom dado."""
    lon, lat = punto
    n = LADO * 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y


def a_coordenada(pixel: tuple[float, float], zoom: int = ZOOM) -> geo.Punto:
    x, y = pixel
    n = LADO * 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return lon, lat


def _tesela(x: int, y: int, zoom: int, cache: Path, descarga: Descarga) -> bytes:
    ruta = cache / str(zoom) / f"{x}_{y}.png"
    if ruta.exists():
        return ruta.read_bytes()
    datos = descarga(URL_TESELA.format(z=zoom, x=x, y=y))
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(datos)
    return datos
