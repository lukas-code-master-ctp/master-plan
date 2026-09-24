"""Calibración fina de la pose de cada vista contra la propia foto.

Después del sol (que fija el rumbo) y del terreno (que fija las cotas) queda un
residuo de ~0,5–1°: el nivelado de la panorámica no es perfecto, el GPS del dron
tiene unos metros de error y el DEM también. Como el KMZ trae los caminos y los
caminos de tierra se ven claros en la foto, se ajusta por vista un giro, dos
inclinaciones y un desnivel para que las líneas del KMZ caigan sobre píxeles claros
y poco saturados.

Es una búsqueda por coordenadas, de gruesa a fina, sobre un mapa suavizado de
"camino". Un ajuste que no mejora el puntaje al menos un 3 % se descarta: en una
foto sin caminos visibles no hay con qué calibrar, y peor que no ajustar es ajustar
contra ruido.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from . import geo
from .proyeccion import ModeloTerreno, Vista

ANCHO_MAPA = 4096
PASO_MUESTRA_M = 3.0
DISTANCIA_MINIMA_M = 30.0
DISTANCIA_MAXIMA_M = 1500.0

# Un camino de tierra: claro y casi gris. El pasto es oscuro o verde; el bosque, oscuro.
BRILLO_MINIMO = 0.55
SATURACION_MAXIMA = 0.30
DESENFOQUE_PX = 6

# Pasos de la búsqueda (giro°, inclinación este°, inclinación norte°, desnivel m).
PASOS = ((0.6, 0.6, 0.6, 12.0), (0.2, 0.2, 0.2, 4.0), (0.05, 0.05, 0.05, 1.0))
LIMITE_GIRO = 1.5
LIMITE_INCLINACION = 2.0
LIMITE_DESNIVEL = 15.0
MEJORA_MINIMA = 0.03


@dataclass(frozen=True)
class Ajuste:
    giro: float = 0.0
    inclinacion_este: float = 0.0
    inclinacion_norte: float = 0.0
    desnivel: float = 0.0
    puntaje_antes: float = 0.0
    puntaje_despues: float = 0.0

    @property
    def mejora(self) -> float:
        if self.puntaje_antes <= 0:
            return 0.0
        return self.puntaje_despues / self.puntaje_antes - 1.0

    @property
    def aplicado(self) -> bool:
        return any((self.giro, self.inclinacion_este, self.inclinacion_norte, self.desnivel))


SIN_AJUSTE = Ajuste()


def mapa_de_caminos(ruta: Path, ancho: int = ANCHO_MAPA) -> np.ndarray:
    """Qué tan "camino" es cada píxel de la panorámica, entre 0 y 1, suavizado."""
    alto = ancho // 2
    with Image.open(ruta) as imagen:
        imagen.draft("RGB", (ancho, alto))
        rgb = imagen.convert("RGB").resize((ancho, alto), Image.BILINEAR)
    canales = np.asarray(rgb, dtype=np.float64) / 255.0
    brillo = canales.max(axis=2)
    saturacion = (brillo - canales.min(axis=2)) / np.maximum(brillo, 1e-6)
    camino = ((brillo > BRILLO_MINIMO) & (saturacion < SATURACION_MAXIMA)).astype(np.uint8) * 255
    suave = Image.fromarray(camino).filter(ImageFilter.GaussianBlur(DESENFOQUE_PX * ancho / ANCHO_MAPA))
    return np.asarray(suave, dtype=np.float64) / 255.0


def calibrar(vista: Vista, lineas: list[geo.Anillo], cota: ModeloTerreno | None,
             mapa: np.ndarray) -> Ajuste:
    """El ajuste que mejor pone las líneas del KMZ sobre los caminos de la foto."""
    muestras = _muestras(lineas, vista, cota)
    if len(muestras) < 50:
        return SIN_AJUSTE
    este, norte, cotas = muestras.T
    distancia = np.hypot(este, norte)
    caida = vista.altura_absoluta - cotas
    azimut = np.arctan2(este, norte)
    alto, ancho = mapa.shape

    def puntaje(parametros: np.ndarray) -> float:
        giro, este_i, norte_i, desnivel = parametros
        az, el = _proyectar(azimut, caida - desnivel, distancia, giro, este_i, norte_i)
        px = ((az - vista.rumbo0) % 360.0) / 360.0 * ancho
        py = (90.0 - el) / 180.0 * alto
        return _muestrear(mapa, px, py)

    actual = np.zeros(4)
    antes = mejor = puntaje(actual)
    if antes <= 0:
        return SIN_AJUSTE

    for pasos in PASOS:
        mejoro = True
        while mejoro:
            mejoro = False
            for indice, paso in enumerate(pasos):
                for signo in (1.0, -1.0):
                    candidato = actual.copy()
                    candidato[indice] += signo * paso
                    if not _dentro_de_limites(candidato):
                        continue
                    valor = puntaje(candidato)
                    if valor > mejor + 1e-9:
                        actual, mejor, mejoro = candidato, valor, True

    ajuste = Ajuste(giro=round(float(actual[0]), 3),
                    inclinacion_este=round(float(actual[1]), 3),
                    inclinacion_norte=round(float(actual[2]), 3),
                    desnivel=round(float(actual[3]), 1),
                    puntaje_antes=antes, puntaje_despues=mejor)
    if ajuste.mejora < MEJORA_MINIMA:
        return replace(SIN_AJUSTE, puntaje_antes=antes, puntaje_despues=mejor)
    return ajuste


def aplicar(vista: Vista, ajuste: Ajuste) -> Vista:
    return replace(vista, giro=ajuste.giro, inclinacion_este=ajuste.inclinacion_este,
                   inclinacion_norte=ajuste.inclinacion_norte, desnivel=ajuste.desnivel)


def _muestras(lineas: list[geo.Anillo], vista: Vista, cota: ModeloTerreno | None) -> np.ndarray:
    """Puntos cada pocos metros sobre las líneas, en metros respecto del dron, con su cota."""
    filas = []
    for linea in lineas:
        for inicio, fin in zip(linea, linea[1:]):
            pasos = max(1, int(geo.distancia(inicio, fin) / PASO_MUESTRA_M))
            for k in range(pasos + 1):
                fraccion = k / pasos
                punto = (inicio[0] + (fin[0] - inicio[0]) * fraccion,
                         inicio[1] + (fin[1] - inicio[1]) * fraccion)
                este, norte = geo.a_metros(punto, vista.origen)
                if not DISTANCIA_MINIMA_M < math.hypot(este, norte) < DISTANCIA_MAXIMA_M:
                    continue
                filas.append((este, norte, cota(punto) if cota else vista.terreno_plano()))
    return np.array(filas, dtype=np.float64).reshape(-1, 3)


def _proyectar(azimut, caida, distancia, giro, inclinacion_este, inclinacion_norte):
    """La misma corrección que `proyeccion.corregir`, vectorizada. Si cambia una,
    cambia la otra."""
    elevacion = -np.arctan2(caida, distancia)
    x, y, z = np.cos(elevacion) * np.sin(azimut), np.cos(elevacion) * np.cos(azimut), np.sin(elevacion)
    tx, ty, g = (math.radians(v) for v in (inclinacion_este, inclinacion_norte, giro))
    y, z = y * math.cos(tx) - z * math.sin(tx), y * math.sin(tx) + z * math.cos(tx)
    x, z = x * math.cos(ty) + z * math.sin(ty), -x * math.sin(ty) + z * math.cos(ty)
    x, y = x * math.cos(g) - y * math.sin(g), x * math.sin(g) + y * math.cos(g)
    return np.degrees(np.arctan2(x, y)) % 360.0, np.degrees(np.arcsin(np.clip(z, -1.0, 1.0)))


def _muestrear(mapa: np.ndarray, px: np.ndarray, py: np.ndarray) -> float:
    """Promedio del mapa en posiciones fraccionarias, interpolando: así el puntaje
    cambia suavemente y la búsqueda fina tiene pendiente que seguir."""
    alto, ancho = mapa.shape
    px = px - 0.5
    py = np.clip(py - 0.5, 0.0, alto - 1.0)
    j = np.floor(px).astype(int)
    i = np.floor(py).astype(int)
    fj, fi = px - j, py - i
    j0, j1 = j % ancho, (j + 1) % ancho          # el azimut da la vuelta
    i0, i1 = i, np.minimum(i + 1, alto - 1)
    valores = (mapa[i0, j0] * (1 - fi) * (1 - fj) + mapa[i0, j1] * (1 - fi) * fj
               + mapa[i1, j0] * fi * (1 - fj) + mapa[i1, j1] * fi * fj)
    return float(valores.mean())


def _dentro_de_limites(parametros: np.ndarray) -> bool:
    giro, este, norte, desnivel = parametros
    return (abs(giro) <= LIMITE_GIRO and abs(este) <= LIMITE_INCLINACION
            and abs(norte) <= LIMITE_INCLINACION and abs(desnivel) <= LIMITE_DESNIVEL)
