"""Posición del sol y detección del disco solar en una panorámica.

De aquí sale el rumbo de cada panorámica: se calcula dónde estaba el sol y se busca
dónde aparece en la imagen. La diferencia es el azimut de la columna x=0.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)


@dataclass(frozen=True)
class PosicionSolar:
    azimut: float      # grados desde el norte, sentido horario
    elevacion: float   # grados sobre el horizonte, con refracción aplicada


def posicion_solar(momento: datetime, lat: float, lon: float) -> PosicionSolar:
    """Algoritmo NOAA. `momento` debe traer zona horaria."""
    if momento.tzinfo is None:
        raise ValueError("el momento debe traer zona horaria")
    utc = momento.astimezone(timezone.utc)

    siglos = (utc - J2000).total_seconds() / 86400.0 / 36525.0

    long_media = (280.46646 + siglos * (36000.76983 + siglos * 0.0003032)) % 360
    anomalia = 357.52911 + siglos * (35999.05029 - 0.0001537 * siglos)
    excentricidad = 0.016708634 - siglos * (0.000042037 + 0.0000001267 * siglos)

    anom_rad = math.radians(anomalia)
    centro = (
        math.sin(anom_rad) * (1.914602 - siglos * (0.004817 + 0.000014 * siglos))
        + math.sin(2 * anom_rad) * (0.019993 - 0.000101 * siglos)
        + math.sin(3 * anom_rad) * 0.000289
    )

    omega = 125.04 - 1934.136 * siglos
    long_aparente = long_media + centro - 0.00569 - 0.00478 * math.sin(math.radians(omega))

    oblicuidad_media = 23 + (26 + (21.448 - siglos * (46.815 + siglos * (0.00059 - siglos * 0.001813))) / 60) / 60
    oblicuidad = oblicuidad_media + 0.00256 * math.cos(math.radians(omega))

    declinacion = math.degrees(math.asin(
        math.sin(math.radians(oblicuidad)) * math.sin(math.radians(long_aparente))
    ))

    # Ecuación del tiempo, en minutos
    y = math.tan(math.radians(oblicuidad / 2)) ** 2
    lm_rad = math.radians(long_media)
    ecuacion_tiempo = 4 * math.degrees(
        y * math.sin(2 * lm_rad)
        - 2 * excentricidad * math.sin(anom_rad)
        + 4 * excentricidad * y * math.sin(anom_rad) * math.cos(2 * lm_rad)
        - 0.5 * y * y * math.sin(4 * lm_rad)
        - 1.25 * excentricidad * excentricidad * math.sin(2 * anom_rad)
    )

    minutos_utc = utc.hour * 60 + utc.minute + utc.second / 60.0 + utc.microsecond / 6e7
    tiempo_solar = (minutos_utc + ecuacion_tiempo + 4 * lon) % 1440
    angulo_horario = tiempo_solar / 4 - 180
    if angulo_horario < -180:
        angulo_horario += 360

    lat_rad = math.radians(lat)
    dec_rad = math.radians(declinacion)
    ah_rad = math.radians(angulo_horario)

    cos_cenit = (math.sin(lat_rad) * math.sin(dec_rad)
                 + math.cos(lat_rad) * math.cos(dec_rad) * math.cos(ah_rad))
    cenit = math.acos(max(-1.0, min(1.0, cos_cenit)))
    elevacion = 90 - math.degrees(cenit)

    denominador = math.cos(lat_rad) * math.sin(cenit)
    if abs(denominador) < 1e-9:
        azimut = 180.0
    else:
        coseno = (math.sin(lat_rad) * math.cos(cenit) - math.sin(dec_rad)) / denominador
        angulo = math.degrees(math.acos(max(-1.0, min(1.0, coseno))))
        azimut = (angulo + 180) % 360 if angulo_horario > 0 else (540 - angulo) % 360

    return PosicionSolar(azimut, elevacion + refraccion(elevacion))


def refraccion(elevacion: float) -> float:
    """Refracción atmosférica en grados. Despreciable en altura, ~0.5° en el horizonte."""
    if elevacion > 85 or elevacion < -1:
        return 0.0
    tan_e = math.tan(math.radians(elevacion))
    if elevacion > 5:
        correccion = 58.1 / tan_e - 0.07 / tan_e**3 + 0.000086 / tan_e**5
    elif elevacion > -0.575:
        correccion = 1735 + elevacion * (-518.2 + elevacion * (103.4 + elevacion * (-12.79 + elevacion * 0.711)))
    else:
        correccion = -20.774 / tan_e
    return correccion / 3600.0


@dataclass(frozen=True)
class DiscoSolar:
    x_normalizado: float   # posición horizontal del centro del disco, en [0, 1)
    elevacion_medida: float
    metodo: str            # "disco" (píxeles saturados) o "brillo" (respaldo)
    pixeles: int


def detectar_disco(
    gris: np.ndarray,
    elevacion_esperada: float,
    banda_grados: float = 12.0,
    umbral: int = 250,
) -> DiscoSolar:
    """Ubica el sol en una panorámica equirectangular en escala de grises.

    Busca píxeles saturados en una banda alrededor de la elevación esperada. Si no
    hay ninguno (sol tapado por nubes o por un cerro), cae al máximo de brillo.
    """
    alto, ancho = gris.shape
    centro = (90.0 - elevacion_esperada) / 180.0 * alto
    media_banda = banda_grados / 180.0 * alto
    y0 = max(0, int(centro - media_banda))
    y1 = min(alto, int(centro + media_banda))
    if y1 <= y0:
        raise ValueError("la banda de búsqueda quedó vacía")
    banda = gris[y0:y1]

    ys, xs = np.nonzero(banda >= umbral)
    if len(xs) >= 20:
        x_norm = _centro_circular(xs / ancho)
        y_centro = _centro_ponderado_y(ys, xs, x_norm, ancho)
        elevacion = 90.0 - (y0 + y_centro) / alto * 180.0
        return DiscoSolar(x_norm, elevacion, "disco", len(xs))

    perfil = banda.mean(axis=0)
    x = int(perfil.argmax())
    elevacion = 90.0 - (y0 + banda.shape[0] / 2) / alto * 180.0
    return DiscoSolar(x / ancho, elevacion, "brillo", 0)


def _centro_circular(valores: np.ndarray) -> float:
    """Media circular de posiciones en [0,1). Maneja el corte en el borde de la imagen."""
    angulos = valores * 2 * math.pi
    x = float(np.cos(angulos).mean())
    y = float(np.sin(angulos).mean())
    return (math.atan2(y, x) / (2 * math.pi)) % 1.0


def _centro_ponderado_y(ys: np.ndarray, xs: np.ndarray, x_norm: float, ancho: int) -> float:
    """Promedio de y usando solo los píxeles cercanos al centro horizontal hallado."""
    distancia = np.abs(((xs / ancho - x_norm + 0.5) % 1.0) - 0.5)
    cercanos = distancia < 0.02
    return float(ys[cercanos].mean()) if cercanos.any() else float(ys.mean())


def rumbo_desde_sol(azimut_solar: float, x_normalizado: float) -> float:
    """Azimut de la columna x=0 de la panorámica."""
    return (azimut_solar - x_normalizado * 360.0) % 360.0
