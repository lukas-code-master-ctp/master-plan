"""Calibrar una vista contra otra: dos fotos del mismo suelo tienen que verlo en el mismo lugar."""
import math

import cv2
import numpy as np
import pytest

from pipeline import geo
from pipeline.cruce import calibrar_contra
from pipeline.proyeccion import Vista

LON, LAT = -72.0, -36.0
GRADO_LON = geo.metros_por_grado_lon(LAT)
LADO_M = 1600.0
RESOLUCION_SUELO = 0.5
SIN_INCLINACION = {float(d): (0.0, 0.0) for d in range(-80, 81, 10)}


def en_grados(este, norte):
    return (LON + este / GRADO_LON, LAT + norte / geo.METROS_POR_GRADO_LAT)


def suelo() -> np.ndarray:
    """Un suelo con manchas de 5 a 20 m, como potreros y árboles vistos de arriba."""
    lado = int(LADO_M / RESOLUCION_SUELO)
    capas = [cv2.resize(np.random.default_rng(semilla).random((lado // celda, lado // celda))
                        .astype(np.float32), (lado, lado), interpolation=cv2.INTER_CUBIC)
             for semilla, celda in ((7, 40), (8, 10))]
    return np.clip((0.6 * capas[0] + 0.4 * capas[1]) * 255, 0, 255).astype(np.uint8)


def panoramica(vista: Vista, textura: np.ndarray, ancho: int = 4096) -> np.ndarray:
    """La foto que sacaría el dron con esa pose sobre suelo plano (sin inclinaciones)."""
    alto = ancho // 2
    az_foto = vista.rumbo0 + (np.arange(ancho) + 0.5) / ancho * 360.0
    el = 90.0 - (np.arange(alto) + 0.5) / alto * 180.0
    az_foto, el = np.meshgrid(az_foto, el)
    # El giro corre la foto: lo que está al azimut az se ve en az - giro.
    az = np.radians(az_foto + vista.giro)
    caida = vista.altura_absoluta - vista.terreno_plano() - vista.desnivel
    debajo = el < -1.0
    distancia = np.where(debajo, caida / np.tan(np.radians(-np.minimum(el, -1.0))), 0.0)
    este0, norte0 = geo.a_metros(vista.origen, (LON, LAT))
    este = este0 + distancia * np.sin(az)
    norte = norte0 + distancia * np.cos(az)
    px = ((este + LADO_M / 2) / RESOLUCION_SUELO).astype(np.float32)
    py = ((LADO_M / 2 - norte) / RESOLUCION_SUELO).astype(np.float32)
    gris = cv2.remap(textura, px, py, cv2.INTER_LINEAR, borderValue=90)
    gris[~debajo] = 200   # cielo
    return np.repeat(gris[..., None], 3, axis=2)


def vista(este_m: float, norte_m: float, **pose) -> Vista:
    lon, lat = en_grados(este_m, norte_m)
    return Vista(id="p", posicion=1, lon=lon, lat=lat, altura_relativa=300.0,
                 altura_absoluta=400.0, rumbo0=20.0, **pose)


ZONA = (*en_grados(-350, -300), *en_grados(350, 300))


def test_encuentra_el_desnivel_y_el_giro_que_ve_la_referencia():
    """Punto II de Lomas de Quillón: los caminos no alcanzaban y la vista quedaba 60 m
    corrida; contra el punto I sale la altura que dice Google Earth."""
    textura = suelo()
    referencia = vista(-250, -200)
    real = vista(250, -250, giro=0.4, desnivel=35.0)
    supuesta = vista(250, -250)

    cruce = calibrar_contra(supuesta, panoramica(real, textura), None,
                            referencia, panoramica(referencia, textura), None,
                            ZONA, SIN_INCLINACION)

    assert cruce.ajuste is not None, cruce.motivo
    assert cruce.ajuste.desnivel == pytest.approx(35.0, abs=3.0)
    assert cruce.ajuste.giro == pytest.approx(0.4, abs=0.15)
    assert cruce.error_despues_m < cruce.error_antes_m


def test_dos_fotos_que_no_se_parecen_no_ajustan_nada():
    textura = suelo()
    referencia = vista(-250, -200)
    otra = np.random.default_rng(3).integers(0, 255, (2048, 4096, 3), dtype=np.uint8)

    cruce = calibrar_contra(vista(250, -250), otra, None, referencia,
                            panoramica(referencia, textura), None, ZONA, SIN_INCLINACION)

    assert cruce.ajuste is None
    assert cruce.motivo
