"""Nivelación de cada panorámica contra el horizonte.

El sol fija el rumbo, pero no dice si la panorámica quedó horizontal. DJI la cose
con la actitud que reporta el dron y a veces queda inclinada uno o dos grados. Desde
500 m eso corre los lotes decenas de metros: en Lomas de Quillón (octubre de 2026)
la foto venía 1,5° caída y el camino del KMZ quedaba 30–40 m al sur del camino real
en el lado más lejano del dron.

El remedio sale del mismo DEM que ya se usa para las cotas: desde la posición del
dron se calcula dónde debería estar la línea del horizonte (cerros cercanos,
cordilleras lejanas), se busca en la foto el borde entre cielo y tierra cerca de
esa línea, y se ajustan las dos inclinaciones que mejor la superponen. No depende
del KMZ ni de que se vean caminos, así que corre antes de la calibración fina y la
deja empezando cerca del óptimo: esa búsqueda tiene topes chicos a propósito y un
desnivel de 1,5° la mandaba al tope y se descartaba.

No toca el giro: el sol lo resuelve mejor que un perfil de cerros.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from . import geo, terreno
from .calibracion import _proyectar

Image.MAX_IMAGE_PIXELS = None

ANCHO_ANALISIS = 7200
PASO_AZIMUT = 0.25

# (zoom, desde m, hasta m, paso m). Cerca hace falta detalle; a 200 km basta una
# tesela de zoom 8, y así el perfil completo son unas 75 teselas.
ANILLOS = ((12, 150.0, 15000.0, 30.0), (10, 15000.0, 60000.0, 150.0),
           (8, 60000.0, 250000.0, 500.0))
RADIO_TERRESTRE_M = 6371000.0
REFRACCION = 0.13

# Un horizonte a menos de esto suele ser bosque o casas, no el suelo del DEM: 25 m de
# árboles a 2 km ya son 0,7°.
DISTANCIA_MINIMA_M = 2500.0

# El borde: el brillo cae al pasar del cielo a la tierra, y sobre el borde hay cielo
# (más azul que rojo). Una nube blanca sobre el cerro no pasa el segundo filtro.
SALTO_MINIMO = 10.0
CIELO_AZUL_MINIMO = 12.0
VENTANAS_GRADOS = (0.5, 0.3)
PASO_GRUESO = 0.1
PASOS_GRUESOS = 30

PUNTOS_MINIMOS = 40
INCLINACION_MAXIMA = 4.0
RESIDUO_MAXIMO = 0.3
# Regularización hacia cero: con el horizonte visible en un solo sector, la inclinación
# perpendicular a ese sector no queda determinada y debe quedarse donde estaba.
REGULARIZACION = 0.01


@dataclass(frozen=True)
class Perfil:
    """La línea del horizonte según el DEM, vista desde el dron (sin corregir)."""
    azimut: np.ndarray       # grados
    elevacion: np.ndarray    # grados
    distancia: np.ndarray    # metros hasta el punto que forma el horizonte


@dataclass(frozen=True)
class Nivelacion:
    inclinacion_este: float = 0.0
    inclinacion_norte: float = 0.0
    puntos: int = 0
    residuo: float = 0.0     # mediana del error que queda, en grados
    motivo: str = ""         # por qué no se aplicó, si no se aplicó

    @property
    def aplicada(self) -> bool:
        return bool(self.inclinacion_este or self.inclinacion_norte)


SIN_NIVELAR = Nivelacion()


def perfil(lon: float, lat: float, altura: float, cache: Path,
           descarga: terreno.Descarga = None, anillos=ANILLOS) -> Perfil:
    """El horizonte que ve un observador a `altura` m (en el datum del DEM)."""
    azimutes = np.arange(0.0, 360.0, PASO_AZIMUT)
    seno, coseno = np.sin(np.radians(azimutes)), np.cos(np.radians(azimutes))
    grado_lon = geo.metros_por_grado_lon(lat)
    mejor_el = np.full(len(azimutes), -90.0)
    mejor_d = np.zeros(len(azimutes))
    for zoom, desde, hasta, paso in anillos:
        lon_r, lat_r = hasta / grado_lon, hasta / geo.METROS_POR_GRADO_LAT
        modelo = terreno.cargar((lon - lon_r, lat - lat_r, lon + lon_r, lat + lat_r), cache,
                                margen_m=2 * paso, zoom=zoom, descarga=descarga)
        distancias = np.arange(desde, hasta, paso)
        este = seno[:, None] * distancias[None, :]
        norte = coseno[:, None] * distancias[None, :]
        cotas = modelo.cotas_en(lon + este / grado_lon, lat + norte / geo.METROS_POR_GRADO_LAT)
        # La Tierra se curva y el aire dobla un poco la luz hacia abajo.
        caida = distancias ** 2 / (2 * RADIO_TERRESTRE_M) * (1 - REFRACCION)
        elevaciones = np.degrees(np.arctan2(cotas - caida[None, :] - altura, distancias[None, :]))
        indice = elevaciones.argmax(axis=1)
        maximo = elevaciones[np.arange(len(azimutes)), indice]
        mas_alto = maximo > mejor_el
        mejor_el = np.where(mas_alto, maximo, mejor_el)
        mejor_d = np.where(mas_alto, distancias[indice], mejor_d)
    return Perfil(azimut=azimutes, elevacion=mejor_el, distancia=mejor_d)


def cargar_imagen(ruta: Path, ancho: int = ANCHO_ANALISIS) -> np.ndarray:
    with Image.open(ruta) as imagen:
        imagen.draft("RGB", (ancho, ancho // 2))
        return np.asarray(imagen.convert("RGB").resize((ancho, ancho // 2), Image.BILINEAR))


def nivelar(rgb: np.ndarray, horizonte: Perfil, rumbo0: float, giro: float = 0.0) -> Nivelacion:
    """Las inclinaciones que ponen el horizonte del DEM sobre el de la foto."""
    lejos = horizonte.distancia >= DISTANCIA_MINIMA_M
    if lejos.sum() < PUNTOS_MINIMOS:
        return Nivelacion(motivo="no hay horizonte lejano a la vista")
    azimut = np.radians(horizonte.azimut[lejos])
    tangente = np.tan(np.radians(horizonte.elevacion[lejos]))
    gris = rgb.mean(axis=2)
    azul = rgb[..., 2].astype(np.float64) - rgb[..., 0]

    def predecir(x):
        return _proyectar(azimut, -tangente, np.ones_like(tangente), giro, x[0], x[1])

    # Primero una búsqueda gruesa sobre todo el rango: el ajuste fino solo mira cerca de
    # donde ya está, y partiendo de cero se queda con bordes de nubes o de bruma.
    x = _busqueda_gruesa(_mapa_de_bordes(gris, azul), predecir, rumbo0)
    medidas = validos = None
    for ventana in VENTANAS_GRADOS:
        az, el = predecir(x)
        medidas, validos = _medir(gris, azul, az, el, rumbo0, ventana)
        if validos.sum() < PUNTOS_MINIMOS:
            return Nivelacion(puntos=int(validos.sum()),
                              motivo="no se distingue el horizonte (nubes o bruma)")
        x = _ajustar(x, predecir, medidas, validos)
        if np.hypot(*x) > INCLINACION_MAXIMA:
            return Nivelacion(motivo=f"la inclinación daba {np.hypot(*x):.1f}°, demasiado para ser real")

    residuo = float(np.median(np.abs(predecir(x)[1] - medidas)[validos]))
    if residuo > RESIDUO_MAXIMO:
        return Nivelacion(puntos=int(validos.sum()), residuo=round(residuo, 3),
                          motivo=f"el horizonte no calza ni nivelado (queda a {residuo:.2f}°)")
    return Nivelacion(inclinacion_este=round(float(x[0]), 3),
                      inclinacion_norte=round(float(x[1]), 3),
                      puntos=int(validos.sum()), residuo=round(residuo, 3))


def _mapa_de_bordes(gris: np.ndarray, azul: np.ndarray) -> np.ndarray:
    """Cuánto cae el brillo de cada píxel al siguiente hacia abajo, solo bajo cielo azul."""
    caida = np.zeros_like(gris)
    caida[:-1] = np.maximum(gris[:-1] - gris[1:], 0.0)
    cielo = np.zeros(gris.shape, dtype=bool)
    cielo[4:] = azul[:-4] >= CIELO_AZUL_MINIMO
    caida[~cielo] = 0.0
    # Unos píxeles de tolerancia vertical para que el puntaje tenga pendiente.
    suave = caida.copy()
    for d in (1, 2, 3):
        suave[d:] += caida[:-d] * (1 - d / 4)
        suave[:-d] += caida[d:] * (1 - d / 4)
    return suave


def _busqueda_gruesa(bordes: np.ndarray, predecir, rumbo0: float) -> np.ndarray:
    alto, ancho = bordes.shape
    mejor, x = -1.0, np.zeros(2)
    for este in np.arange(-PASO_GRUESO * PASOS_GRUESOS, PASO_GRUESO * PASOS_GRUESOS + 1e-9, PASO_GRUESO):
        for norte in np.arange(-PASO_GRUESO * PASOS_GRUESOS, PASO_GRUESO * PASOS_GRUESOS + 1e-9, PASO_GRUESO):
            if math.hypot(este, norte) > INCLINACION_MAXIMA:
                continue
            az, el = predecir(np.array([este, norte]))
            columnas = (((az - rumbo0) % 360.0) / 360.0 * ancho).astype(int) % ancho
            filas = np.clip(np.round((90.0 - el) / 180.0 * alto).astype(int), 0, alto - 1)
            puntaje = float(bordes[filas, columnas].mean())
            if puntaje > mejor:
                mejor, x = puntaje, np.array([este, norte])
    return x


def _medir(gris: np.ndarray, azul: np.ndarray, azimut: np.ndarray, elevacion: np.ndarray,
           rumbo0: float, ventana: float) -> tuple[np.ndarray, np.ndarray]:
    """La elevación del borde cielo-tierra en la foto, en cada columna, cerca de la esperada."""
    alto, ancho = gris.shape
    por_grado = alto / 180.0
    medio = int(math.ceil(ventana * por_grado))
    columnas = (((azimut - rumbo0) % 360.0) / 360.0 * ancho).astype(int) % ancho
    filas = np.round((90.0 - elevacion) * por_grado).astype(int)
    medidas = np.full(len(columnas), np.nan)
    for k, (columna, fila) in enumerate(zip(columnas, filas)):
        arriba, abajo = fila - medio, fila + medio
        if arriba < 6 or abajo >= alto - 1:
            continue
        salto = np.diff(gris[arriba:abajo, columna])
        i = int(np.argmin(salto))
        if -salto[i] < SALTO_MINIMO or azul[arriba + i - 5:arriba + i, columna].mean() < CIELO_AZUL_MINIMO:
            continue
        # Interpolación parabólica: el borde cae entre píxeles.
        fino = 0.0
        if 0 < i < len(salto) - 1:
            a, b, c = salto[i - 1], salto[i], salto[i + 1]
            if a - 2 * b + c:
                fino = 0.5 * (a - c) / (a - 2 * b + c)
        medidas[k] = 90.0 - (arriba + i + 1 + fino) / por_grado
    return medidas, ~np.isnan(medidas)


def _ajustar(x: np.ndarray, predecir, medidas: np.ndarray, validos: np.ndarray) -> np.ndarray:
    """Gauss-Newton con pesos de Huber: unas columnas con nube o árbol no lo arrastran."""
    for _ in range(8):
        residuo = (predecir(x)[1] - medidas)[validos]
        jacobiano = np.empty((len(residuo), 2))
        for j in range(2):
            paso = np.zeros(2)
            paso[j] = 1e-3
            jacobiano[:, j] = ((predecir(x + paso)[1] - medidas)[validos] - residuo) / 1e-3
        escala = max(1.4826 * float(np.median(np.abs(residuo))), 0.05)
        pesos = np.minimum(1.0, 1.5 * escala / np.maximum(np.abs(residuo), 1e-9))
        a = jacobiano.T @ (jacobiano * pesos[:, None]) + REGULARIZACION * len(residuo) * np.eye(2)
        b = jacobiano.T @ (pesos * residuo) + REGULARIZACION * len(residuo) * x
        delta = np.linalg.solve(a, b)
        x = x - delta
        if np.abs(delta).max() < 1e-4:
            break
    return x
