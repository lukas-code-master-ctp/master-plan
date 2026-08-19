"""El modelo solar se valida contra invariantes astronómicas conocidas, no contra
sus propios resultados."""
import math
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from pipeline.solar import (
    detectar_disco,
    posicion_solar,
    refraccion,
    rumbo_desde_sol,
)

UTC = timezone.utc


def elevacion_maxima_del_dia(fecha, lat, lon):
    """Barre el día y devuelve (elevacion, azimut) del mediodía solar."""
    mejor = None
    for minuto in range(0, 1440, 2):
        momento = fecha + timedelta(minutes=minuto)
        p = posicion_solar(momento, lat, lon)
        if mejor is None or p.elevacion > mejor.elevacion:
            mejor = p
    return mejor


def test_equinoccio_en_el_ecuador_el_sol_pasa_por_el_cenit():
    p = elevacion_maxima_del_dia(datetime(2026, 3, 20, tzinfo=UTC), 0.0, 0.0)
    assert p.elevacion == pytest.approx(90.0, abs=0.6)


def test_solsticio_de_junio_en_el_ecuador():
    # La declinación solar llega a +23.44°, así que al mediodía el sol queda a 66.56°.
    p = elevacion_maxima_del_dia(datetime(2026, 6, 21, tzinfo=UTC), 0.0, 0.0)
    assert p.elevacion == pytest.approx(66.56, abs=0.4)


def test_solsticio_de_junio_sobre_el_tropico_de_cancer():
    p = elevacion_maxima_del_dia(datetime(2026, 6, 21, tzinfo=UTC), 23.44, 0.0)
    assert p.elevacion == pytest.approx(90.0, abs=0.5)


def test_sol_de_medianoche_en_el_polo_norte():
    fecha = datetime(2026, 6, 21, tzinfo=UTC)
    elevaciones = [posicion_solar(fecha + timedelta(hours=h), 89.9, 0.0).elevacion
                   for h in range(24)]
    assert min(elevaciones) > 22.0   # nunca se pone
    assert max(elevaciones) < 25.0   # y nunca sube más que la declinación


def test_en_el_hemisferio_sur_el_mediodia_solar_apunta_al_norte():
    p = elevacion_maxima_del_dia(datetime(2026, 6, 21, tzinfo=UTC), -34.79, -72.0)
    assert min(p.azimut, 360 - p.azimut) < 1.5


def test_en_el_hemisferio_norte_el_mediodia_solar_apunta_al_sur():
    p = elevacion_maxima_del_dia(datetime(2026, 6, 21, tzinfo=UTC), 45.0, 0.0)
    assert p.azimut == pytest.approx(180.0, abs=1.5)


def test_en_el_equinoccio_el_sol_se_pone_por_el_oeste():
    fecha = datetime(2026, 3, 20, tzinfo=UTC)
    anterior = None
    for minuto in range(0, 1440):
        p = posicion_solar(fecha + timedelta(minutes=minuto), -34.79, -72.0)
        if anterior and anterior.elevacion > 0 >= p.elevacion:
            assert p.azimut == pytest.approx(270.0, abs=2.0)
            return
        anterior = p
    pytest.fail("no se encontró el ocaso")


def test_la_refraccion_es_maxima_en_el_horizonte_y_nula_en_el_cenit():
    assert refraccion(0.0) == pytest.approx(0.48, abs=0.05)
    assert refraccion(45.0) < 0.02
    assert refraccion(90.0) == 0.0


def test_el_momento_debe_traer_zona_horaria():
    with pytest.raises(ValueError):
        posicion_solar(datetime(2026, 3, 5, 19, 5), -34.79, -72.0)


# --- Detección del disco solar ----------------------------------------------

def imagen_con_sol(ancho, alto, x_centro, y_centro, radio=8):
    img = np.full((alto, ancho), 120, dtype=np.uint8)
    ys, xs = np.mgrid[0:alto, 0:ancho]
    dx = np.minimum(np.abs(xs - x_centro), ancho - np.abs(xs - x_centro))
    img[(dx**2 + (ys - y_centro)**2) < radio**2] = 255
    return img


def test_detecta_el_disco_solar():
    alto, ancho = 400, 800
    elevacion = 20.0
    y = int((90 - elevacion) / 180 * alto)
    img = imagen_con_sol(ancho, alto, 600, y)

    disco = detectar_disco(img, elevacion)

    assert disco.metodo == "disco"
    assert disco.x_normalizado == pytest.approx(600 / ancho, abs=0.005)
    assert disco.elevacion_medida == pytest.approx(elevacion, abs=1.0)


def test_detecta_el_disco_aunque_quede_partido_por_el_borde():
    alto, ancho = 400, 800
    elevacion = 20.0
    y = int((90 - elevacion) / 180 * alto)
    img = imagen_con_sol(ancho, alto, 0, y)

    disco = detectar_disco(img, elevacion)

    assert disco.metodo == "disco"
    assert min(disco.x_normalizado, 1 - disco.x_normalizado) < 0.005


def test_sin_pixeles_saturados_cae_al_metodo_de_brillo():
    img = np.full((400, 800), 100, dtype=np.uint8)
    img[:, 300:320] = 180

    disco = detectar_disco(img, 20.0)

    assert disco.metodo == "brillo"
    assert disco.x_normalizado == pytest.approx(310 / 800, abs=0.02)


def test_ignora_lo_saturado_fuera_de_la_banda_de_elevacion():
    alto, ancho = 400, 800
    img = imagen_con_sol(ancho, alto, 600, int((90 - 20) / 180 * alto))
    img[0:20, 100:140] = 255   # cielo quemado muy arriba

    disco = detectar_disco(img, 20.0, banda_grados=10.0)

    assert disco.x_normalizado == pytest.approx(600 / ancho, abs=0.01)


# --- Rumbo -------------------------------------------------------------------

def test_el_rumbo_ubica_el_sol_donde_corresponde():
    azimut_solar = 279.3
    x = 0.378
    rumbo = rumbo_desde_sol(azimut_solar, x)
    assert (rumbo + x * 360) % 360 == pytest.approx(azimut_solar, abs=1e-9)


def test_el_rumbo_siempre_queda_en_el_rango_valido():
    for x in (0.0, 0.25, 0.5, 0.99):
        for az in (0.0, 90.0, 359.9):
            assert 0 <= rumbo_desde_sol(az, x) < 360
