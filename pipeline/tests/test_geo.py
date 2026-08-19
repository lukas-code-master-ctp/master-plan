import math

import pytest

from pipeline import geo

# Un cuadrado de 100 m de lado cerca del loteo, para tener números verificables a mano.
LAT = -34.79
GRADO_LON = geo.metros_por_grado_lon(LAT)
LADO = 100.0
CUADRADO = [
    (-72.0, LAT),
    (-72.0 + LADO / GRADO_LON, LAT),
    (-72.0 + LADO / GRADO_LON, LAT + LADO / geo.METROS_POR_GRADO_LAT),
    (-72.0, LAT + LADO / geo.METROS_POR_GRADO_LAT),
]


def test_el_area_de_un_cuadrado_de_100m_es_una_hectarea():
    assert geo.area_m2(CUADRADO) == pytest.approx(10000.0, rel=1e-3)


def test_el_area_no_depende_del_sentido_de_giro():
    assert geo.area_m2(CUADRADO[::-1]) == pytest.approx(geo.area_m2(CUADRADO))


def test_el_area_de_un_anillo_degenerado_es_cero():
    assert geo.area_m2([(-72.0, LAT), (-72.0, LAT)]) == 0.0


def test_el_centroide_de_un_cuadrado_es_su_centro():
    lon, lat = geo.centroide(CUADRADO)
    assert lon == pytest.approx(-72.0 + LADO / 2 / GRADO_LON, abs=1e-9)
    assert lat == pytest.approx(LAT + LADO / 2 / geo.METROS_POR_GRADO_LAT, abs=1e-9)


def test_el_centroide_es_el_del_area_y_no_el_de_los_vertices():
    # En una ele el centroide del área cae fuera de la figura, y eso es correcto:
    # (1.1, 1.1) es el resultado exacto de componer los dos rectángulos.
    ele = [(0, 0), (3, 0), (3, 1), (1, 1), (1, 3), (0, 3)]
    lon, lat = geo.centroide(ele)
    assert (lon, lat) == (pytest.approx(1.1, abs=1e-6), pytest.approx(1.1, abs=1e-6))
    assert not geo.contiene(ele, (lon, lat))


def test_el_centroide_no_depende_del_vertice_inicial_ni_del_sentido():
    referencia = geo.centroide(CUADRADO)
    rotado = geo.centroide(CUADRADO[2:] + CUADRADO[:2])
    invertido = geo.centroide(CUADRADO[::-1])
    assert rotado == pytest.approx(referencia, abs=1e-12)
    assert invertido == pytest.approx(referencia, abs=1e-12)


def test_contiene_distingue_dentro_de_fuera():
    centro = geo.centroide(CUADRADO)
    assert geo.contiene(CUADRADO, centro)
    assert not geo.contiene(CUADRADO, (-72.01, LAT))
    assert not geo.contiene(CUADRADO, (-72.0, LAT - 0.01))


def test_la_distancia_es_simetrica_y_conocida():
    a = (-72.0, LAT)
    b = (-72.0 + LADO / GRADO_LON, LAT)
    assert geo.distancia(a, b) == pytest.approx(LADO, rel=1e-6)
    assert geo.distancia(b, a) == pytest.approx(geo.distancia(a, b))


def test_un_grado_de_latitud_son_unos_111_km():
    assert geo.distancia((0, 0), (0, 1)) == pytest.approx(111320, rel=1e-6)


def test_la_caja_envolvente_cubre_todos_los_vertices():
    lon_min, lat_min, lon_max, lat_max = geo.caja(CUADRADO)
    for lon, lat in CUADRADO:
        assert lon_min <= lon <= lon_max
        assert lat_min <= lat <= lat_max
