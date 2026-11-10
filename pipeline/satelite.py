"""Calzar una vista contra la imagen satelital cuando los caminos no alcanzan.

La calibración con los caminos (calibracion.py) necesita caminos claros en la foto, y
deja la inclinación atada al horizonte (horizonte.py). En Parque Algarrobo fallaron
las dos cosas juntas: cerros, bruma de costa y el sol bajo hicieron que el horizonte
diera inclinaciones de 1 a 3° que la foto no tenía, la búsqueda con los caminos se fue
al tope en las tres vistas, y el dibujo quedó 20 a 40 m corrido, distinto en cada foto.

Lo que sí se ve en cualquier foto es dónde hay vegetación y dónde no. Sentinel-2
publica cada pocos días una imagen de todo el planeta a 10 m, bien georreferenciada,
y de ella sale el verdor del suelo (NDVI). Se proyecta la foto del dron sobre el suelo
con la pose que se está probando y se busca la pose con que el verdor de la foto más
se parece al del satélite: bosque sobre bosque, pradera sobre pradera, camino sobre
camino. En Parque Algarrobo deja las servidumbres del KMZ sobre los caminos de las
tres fotos.

Las imágenes se leen del bucket público de Sentinel-2 en AWS, trozo por trozo: son
GeoTIFF en teselas, y de un archivo de 200 MB basta bajar la tesela que cubre el loteo.
"""
from __future__ import annotations

import json
import math
import re
import struct
import urllib.request
import zlib
from dataclasses import dataclass, replace
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, map_coordinates
from scipy.optimize import minimize

from . import geo
from .calibracion import SIN_AJUSTE, Ajuste, _proyectar
from .proyeccion import Vista

BUCKET = "https://sentinel-cogs.s3.us-west-2.amazonaws.com"
PREFIJO = "sentinel-s2-l2a-cogs"
# Cuántos meses hacia atrás se busca una imagen despejada, y cuántas se miran.
MESES_ATRAS = 6
ESCENAS_PROBADAS = 12
NUBES_MAXIMAS_ESCENA = 40.0     # % de la escena entera (100 x 100 km)
NUBES_MAXIMAS_ZONA = 0.03       # fracción del recorte con nube, sombra o nieve
# Clases de la capa de escena de Sentinel (SCL) que tapan el suelo: sin dato, defecto,
# sombra de nube, nube media y alta, cirro y nieve.
CLASES_TAPADAS = (0, 1, 3, 8, 9, 10, 11)

ANCHO_FOTO = 3600
# El suelo que se compara: hasta dónde desde el dron y cada cuántos metros. Sentinel
# tiene 10 m por píxel; más fino no agrega nada.
ALCANCE_M = 1600.0
PASO_GRUESO_M = 20.0
PASO_FINO_M = 8.0
MARGEN_RECORTE_M = ALCANCE_M + 200.0

# Lo que se prueba. El desnivel, como en calibrar_altura; el giro y la inclinación, más
# sueltos que con los caminos: acá no hay cosas claras que arrastren la búsqueda.
DESNIVELES_DE_PARTIDA = tuple(float(d) for d in range(-80, 81, 20))
GIROS_DE_PARTIDA = (-2.0, 0.0, 2.0)
LIMITE_DESNIVEL = 80.0
LIMITE_GIRO = 3.0
LIMITE_INCLINACION = 4.0
# Con menos parecido que esto, o si mejora menos que esto, no se cree: una foto sobre
# puro bosque o puro potrero no tiene manchas que comparar.
PARECIDO_MINIMO = 0.40
MEJORA_MINIMA = 0.10
PUNTOS_MINIMOS = 2000

Descarga = Callable[[str, tuple[int, int] | None], bytes]


@dataclass(frozen=True)
class Verdor:
    """El verdor (NDVI) del suelo en una grilla UTM, norte arriba."""
    ndvi: np.ndarray
    este0: float          # borde oeste del primer píxel
    norte0: float         # borde norte del primer píxel
    paso: float           # metros por píxel
    huso: int
    sur: bool
    escena: str = ""

    def en(self, lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        este, norte = a_utm(np.asarray(lon, dtype=np.float64), np.asarray(lat, dtype=np.float64),
                            self.huso, self.sur)
        columna = (este - self.este0) / self.paso - 0.5
        fila = (self.norte0 - norte) / self.paso - 0.5
        return map_coordinates(self.ndvi, [fila, columna], order=1, mode="nearest")


# --- La búsqueda de la pose -----------------------------------------------------

def cargar_foto(ruta: Path, ancho: int = ANCHO_FOTO) -> np.ndarray:
    """El verdor de la panorámica: cuánto le gana el verde al rojo, suavizado."""
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(ruta) as imagen:
        rgb = np.asarray(imagen.convert("RGB").resize((ancho, ancho // 2), Image.BILINEAR),
                         dtype=np.float32)
    return verdor_de_foto(rgb)


def verdor_de_foto(rgb: np.ndarray) -> np.ndarray:
    rojo, verde = rgb[..., 0].astype(np.float32), rgb[..., 1].astype(np.float32)
    return gaussian_filter((verde - rojo) / (verde + rojo + 1.0), 2.0)


def calibrar(vista: Vista, foto: np.ndarray, altura: float, cotas_en, verdor: Verdor) -> Ajuste:
    """Lo que hay que sumarle a la pose de la vista para que el verdor de la foto,
    puesto sobre el suelo, calce con el del satélite.

    `foto` es el verdor de la panorámica (ver `cargar_foto`), `altura` la del dron en el
    datum de `cotas_en` (la cota del despegue más la altura sobre él) y `cotas_en` da la
    cota de muchos puntos (lon, lat) a la vez. `puntaje_antes` y `puntaje_despues` son
    el parecido (correlación) antes y después.
    """
    alto, ancho = foto.shape
    base = np.array([vista.desnivel, vista.giro, vista.inclinacion_este, vista.inclinacion_norte])

    def grilla(paso: float):
        ejes = np.arange(-ALCANCE_M, ALCANCE_M + 1, paso)
        este, norte = np.meshgrid(ejes, ejes)
        distancia = np.hypot(este, norte)
        dentro = (distancia < ALCANCE_M) & (distancia > paso)
        este, norte, distancia = este[dentro], norte[dentro], distancia[dentro]
        lon = vista.lon + este / geo.metros_por_grado_lon(vista.lat)
        lat = vista.lat + norte / geo.METROS_POR_GRADO_LAT
        return np.arctan2(este, norte), distancia, altura - cotas_en(lon, lat), verdor.en(lon, lat)

    def parecido(pose: np.ndarray, puntos) -> float:
        azimut, distancia, caida, suelo = puntos
        desnivel, giro, este_i, norte_i = pose
        az, el = _proyectar(azimut, caida - desnivel, distancia, giro, este_i, norte_i)
        px = ((az - vista.rumbo0) % 360.0) / 360.0 * ancho - 0.5
        py = (90.0 - el) / 180.0 * alto - 0.5
        visto = map_coordinates(foto, [py, px], order=1, mode="grid-wrap")
        if visto.std() < 1e-9:
            return 0.0
        return float(np.corrcoef(visto, suelo)[0, 1])

    gruesa = grilla(PASO_GRUESO_M)
    if len(gruesa[0]) < PUNTOS_MINIMOS or gruesa[3].std() < 1e-6:
        return SIN_AJUSTE
    antes = parecido(base, gruesa)

    def buscar(partida: np.ndarray, puntos, fino: bool):
        pasos = np.diag([2.0, 0.15, 0.15, 0.15] if fino else [8.0, 0.5, 0.5, 0.5])
        return minimize(lambda p: -parecido(p, puntos), partida, method="Nelder-Mead",
                        options={"xatol": 0.01 if fino else 0.05, "fatol": 1e-5,
                                 "maxiter": 400, "initial_simplex": np.vstack([partida, partida + pasos])})

    candidatos = []
    for desnivel in DESNIVELES_DE_PARTIDA:
        for giro in GIROS_DE_PARTIDA:
            partida = np.array([base[0] + desnivel, base[1] + giro, base[2], base[3]])
            candidatos.append(buscar(partida, gruesa, fino=False))
    mejor = min(candidatos, key=lambda r: r.fun)
    fina = grilla(PASO_FINO_M)
    antes = parecido(base, fina)
    mejor = buscar(mejor.x, fina, fino=True)
    despues = float(-mejor.fun)
    desnivel, giro, este_i, norte_i = (float(v) for v in mejor.x)

    sin_cambio = replace(SIN_AJUSTE, puntaje_antes=antes, puntaje_despues=antes)
    topes = []
    if abs(desnivel) >= LIMITE_DESNIVEL:
        topes.append(f"desnivel {desnivel:+.0f} m")
    if abs(giro) >= LIMITE_GIRO:
        topes.append(f"giro {giro:+.1f}°")
    if max(abs(este_i), abs(norte_i)) >= LIMITE_INCLINACION:
        topes.append(f"inclinación {este_i:+.1f}° / {norte_i:+.1f}°")
    if topes:
        return replace(sin_cambio, tope=", ".join(topes))
    if despues < PARECIDO_MINIMO or despues - antes < MEJORA_MINIMA:
        return replace(sin_cambio, puntaje_despues=despues)
    return Ajuste(giro=round(giro - float(base[1]), 3),
                  inclinacion_este=round(este_i - float(base[2]), 3),
                  inclinacion_norte=round(norte_i - float(base[3]), 3),
                  desnivel=round(desnivel - float(base[0]), 1),
                  puntaje_antes=antes, puntaje_despues=despues)


# --- La imagen ------------------------------------------------------------------

def cargar(caja: tuple[float, float, float, float], dia: date, cache: Path,
           margen_m: float = MARGEN_RECORTE_M, descarga: Descarga | None = None) -> Verdor:
    """El verdor del suelo en la caja (lon_min, lat_min, lon_max, lat_max) más un margen,
    de la imagen despejada más cercana a `dia`. Sin ninguna que sirva, ValueError; sin
    red, OSError."""
    descarga = descarga or descargar
    lon_min, lat_min, lon_max, lat_max = caja
    centro = ((lon_min + lon_max) / 2, (lat_min + lat_max) / 2)
    cuadro = cuadro_mgrs(*centro)
    huso, sur = int(cuadro[:2]), centro[1] < 0
    estes, nortes = a_utm(np.array([lon_min, lon_max, lon_min, lon_max]),
                          np.array([lat_min, lat_min, lat_max, lat_max]), huso, sur)
    limites = (float(estes.min()) - margen_m, float(nortes.min()) - margen_m,
               float(estes.max()) + margen_m, float(nortes.max()) + margen_m)

    cache.mkdir(parents=True, exist_ok=True)
    clave = f"{cuadro}_{dia:%Y%m%d}_" + "_".join(f"{v:.0f}" for v in limites)
    guardado = cache / f"{clave}.npz"
    if guardado.exists():
        with np.load(guardado) as datos:
            return Verdor(datos["ndvi"], float(datos["este0"]), float(datos["norte0"]),
                          float(datos["paso"]), huso, sur, str(datos["escena"]))

    for escena in _escenas(cuadro, dia, descarga)[:ESCENAS_PROBADAS]:
        ficha = json.loads(descarga(f"{escena}/{escena.rsplit('/', 1)[1]}.json", None))
        if ficha["properties"].get("eo:cloud_cover", 100.0) > NUBES_MAXIMAS_ESCENA:
            continue
        clases, *_ = _recorte(f"{escena}/SCL.tif", ficha["assets"]["scl"]["proj:transform"],
                              limites, descarga)
        if clases.size == 0 or np.isin(clases, CLASES_TAPADAS).mean() > NUBES_MAXIMAS_ZONA:
            continue
        rojo, este0, norte0, paso = _recorte(f"{escena}/B04.tif", ficha["assets"]["red"]["proj:transform"],
                                             limites, descarga)
        infrarrojo, *_ = _recorte(f"{escena}/B08.tif", ficha["assets"]["nir"]["proj:transform"],
                                  limites, descarga)
        rojo, infrarrojo = rojo.astype(np.float32), infrarrojo.astype(np.float32)
        ndvi = (infrarrojo - rojo) / (infrarrojo + rojo + 1.0)
        nombre = escena.rsplit("/", 1)[1]
        np.savez_compressed(guardado, ndvi=ndvi, este0=este0, norte0=norte0, paso=paso, escena=nombre)
        return Verdor(ndvi, este0, norte0, paso, huso, sur, nombre)
    raise ValueError(f"no hay imagen satelital despejada del cuadro {cuadro} cerca del {dia:%d/%m/%Y}")


def descargar(ruta: str, rango: tuple[int, int] | None) -> bytes:
    """Un archivo del bucket, o los bytes [desde, hasta] de él. Una ruta que empieza
    con `?` es un listado."""
    pedido = urllib.request.Request(f"{BUCKET}/{ruta}")
    if rango:
        pedido.add_header("Range", f"bytes={rango[0]}-{rango[1]}")
    with urllib.request.urlopen(pedido, timeout=60) as respuesta:
        return respuesta.read()


def _escenas(cuadro: str, dia: date, descarga: Descarga) -> list[str]:
    """Las rutas de las escenas del cuadro, de la más cercana a `dia` a la más lejana."""
    huso, banda, cien = int(cuadro[:2]), cuadro[2], cuadro[3:]
    meses, mes = [], date(dia.year, dia.month, 1)
    for _ in range(MESES_ATRAS + 1):
        meses.append(mes)
        mes = (mes - timedelta(days=1)).replace(day=1)
    siguiente = (date(dia.year, dia.month, 28) + timedelta(days=7)).replace(day=1)
    meses.append(siguiente)
    encontradas = []
    for mes in meses:
        prefijo = f"{PREFIJO}/{huso}/{banda}/{cien}/{mes.year}/{mes.month}/"
        listado = descarga(f"?list-type=2&delimiter=/&prefix={prefijo}", None).decode()
        for ruta in re.findall(r"<Prefix>([^<]+_L2A)/</Prefix>", listado):
            fecha = re.search(r"_(\d{4})(\d{2})(\d{2})_", ruta)
            if fecha:
                encontradas.append((abs((date(*map(int, fecha.groups())) - dia).days), ruta))
    return [ruta for _, ruta in sorted(encontradas)]


def _recorte(ruta: str, transformacion: list[float], limites: tuple[float, float, float, float],
             descarga: Descarga) -> tuple[np.ndarray, float, float, float]:
    """El trozo de un GeoTIFF en teselas que cubre `limites` (este_min, norte_min,
    este_max, norte_max), con el borde (este, norte) de su primer píxel y su paso."""
    paso, este_tif, norte_tif = float(transformacion[0]), float(transformacion[2]), float(transformacion[5])
    tif = _Tif(ruta, descarga)
    j0 = max(0, int(math.floor((limites[0] - este_tif) / paso)))
    j1 = min(tif.ancho, int(math.ceil((limites[2] - este_tif) / paso)))
    i0 = max(0, int(math.floor((norte_tif - limites[3]) / paso)))
    i1 = min(tif.alto, int(math.ceil((norte_tif - limites[1]) / paso)))
    if j1 <= j0 or i1 <= i0:
        return np.zeros((0, 0), dtype=tif.tipo), 0.0, 0.0, paso
    return tif.leer(i0, i1, j0, j1), este_tif + j0 * paso, norte_tif - i0 * paso, paso


class _Tif:
    """Lo justo de un GeoTIFF en teselas (COG) para leer un trozo con pedidos parciales:
    TIFF clásico, una banda, enteros sin signo, comprimido con deflate."""
    CABECERA = 65536

    def __init__(self, ruta: str, descarga: Descarga):
        self.ruta, self.descarga = ruta, descarga
        inicio = descarga(ruta, (0, self.CABECERA - 1))
        if inicio[:4] != b"II*\x00":
            raise ValueError(f"{ruta}: no es un TIFF que sepa leer")
        (directorio,) = struct.unpack_from("<I", inicio, 4)
        (cantidad,) = struct.unpack_from("<H", inicio, directorio)
        etiquetas = {}
        for k in range(cantidad):
            etiqueta, tipo, cuenta = struct.unpack_from("<HHI", inicio, directorio + 2 + 12 * k)
            etiquetas[etiqueta] = (tipo, cuenta, directorio + 2 + 12 * k + 8)

        def valores(etiqueta: int) -> np.ndarray:
            tipo, cuenta, donde = etiquetas[etiqueta]
            formato = {3: "<u2", 4: "<u4", 16: "<u8"}[tipo]
            largo = np.dtype(formato).itemsize * cuenta
            if largo > 4:
                (donde,) = struct.unpack_from("<I", inicio, donde)
            datos = (inicio[donde:donde + largo] if donde + largo <= len(inicio)
                     else descarga(ruta, (donde, donde + largo - 1)))
            return np.frombuffer(datos, dtype=formato, count=cuenta).astype(np.int64)

        self.ancho, self.alto = int(valores(256)[0]), int(valores(257)[0])
        self.lado_x, self.lado_y = int(valores(322)[0]), int(valores(323)[0])
        self.predictor = int(valores(317)[0]) if 317 in etiquetas else 1
        bits = int(valores(258)[0])
        if int(valores(259)[0]) not in (8, 32946) or bits not in (8, 16) or self.predictor not in (1, 2):
            raise ValueError(f"{ruta}: no es un TIFF que sepa leer")
        self.tipo = np.dtype("<u2" if bits == 16 else "u1")
        self.desde, self.largos = valores(324), valores(325)

    def leer(self, i0: int, i1: int, j0: int, j1: int) -> np.ndarray:
        salida = np.zeros((i1 - i0, j1 - j0), dtype=self.tipo)
        por_fila = -(-self.ancho // self.lado_x)
        for fila in range(i0 // self.lado_y, (i1 - 1) // self.lado_y + 1):
            for columna in range(j0 // self.lado_x, (j1 - 1) // self.lado_x + 1):
                indice = fila * por_fila + columna
                if self.largos[indice] == 0:
                    continue
                desde = int(self.desde[indice])
                crudo = zlib.decompress(self.descarga(self.ruta, (desde, desde + int(self.largos[indice]) - 1)))
                tesela = np.frombuffer(crudo, dtype=self.tipo).reshape(self.lado_y, self.lado_x)
                if self.predictor == 2:
                    tesela = np.cumsum(tesela, axis=1, dtype=self.tipo)
                y, x = fila * self.lado_y, columna * self.lado_x
                a, b = max(i0, y), min(i1, y + self.lado_y)
                c, d = max(j0, x), min(j1, x + self.lado_x)
                salida[a - i0:b - i0, c - j0:d - j0] = tesela[a - y:b - y, c - x:d - x]
        return salida


# --- UTM y la grilla de Sentinel -------------------------------------------------

_A, _F, _K0 = 6378137.0, 1 / 298.257223563, 0.9996
_BANDAS = "CDEFGHJKLMNPQRSTUVWX"
_COLUMNAS = ("STUVWXYZ", "ABCDEFGH", "JKLMNPQR")      # según huso % 3
_FILAS = "ABCDEFGHJKLMNPQRSTUV"


def a_utm(lon: np.ndarray, lat: np.ndarray, huso: int, sur: bool) -> tuple[np.ndarray, np.ndarray]:
    """(lon, lat) WGS84 → (este, norte) UTM del huso, con las series de Krüger."""
    n = _F / (2 - _F)
    radio = _A / (1 + n) * (1 + n ** 2 / 4 + n ** 4 / 64)
    alfa = (n / 2 - 2 * n ** 2 / 3 + 5 * n ** 3 / 16,
            13 * n ** 2 / 48 - 3 * n ** 3 / 5,
            61 * n ** 3 / 240)
    fi = np.radians(lat)
    lam = np.radians(lon - (huso * 6 - 183))
    e = math.sqrt(_F * (2 - _F))
    t = np.sinh(np.arctanh(np.sin(fi)) - e * np.arctanh(e * np.sin(fi)))
    xi = np.arctan2(t, np.cos(lam))
    eta = np.arctanh(np.sin(lam) / np.sqrt(1 + t ** 2))
    este = eta + sum(a * np.cos(2 * k * xi) * np.sinh(2 * k * eta) for k, a in enumerate(alfa, 1))
    norte = xi + sum(a * np.sin(2 * k * xi) * np.cosh(2 * k * eta) for k, a in enumerate(alfa, 1))
    return 500000.0 + _K0 * radio * este, (10000000.0 if sur else 0.0) + _K0 * radio * norte


def cuadro_mgrs(lon: float, lat: float) -> str:
    """El cuadro de 100 km de la grilla militar donde cae el punto, como lo nombra
    Sentinel: "19HBD"."""
    huso = int((lon + 180.0) // 6) + 1
    este, norte = a_utm(np.array([lon]), np.array([lat]), huso, lat < 0)
    banda = _BANDAS[min(int((lat + 80.0) // 8), len(_BANDAS) - 1)]
    columna = _COLUMNAS[huso % 3][int(este[0] // 100000) - 1]
    fila = _FILAS[(int(norte[0] // 100000) + (0 if huso % 2 else 5)) % 20]
    return f"{huso:02d}{banda}{columna}{fila}"
