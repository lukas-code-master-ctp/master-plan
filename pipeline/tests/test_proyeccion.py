import math

import pytest

from pipeline import geo
from pipeline.proyeccion import (
    ParcelaProyectada,
    Vista,
    area_angular,
    direccion,
    es_visible,
    proyectar_parcela,
    proyectar_punto,
    proyectar_vista,
    separacion_angular,
)

LAT, LON = -34.79, -72.0
GRADO_LON = geo.metros_por_grado_lon(LAT)

VISTA = Vista(id="prueba", posicion=1, lon=LON, lat=LAT,
              altura_relativa=100.0, altura_absoluta=200.0, rumbo0=0.0)


def desplazar(este_m, norte_m):
    return (LON + este_m / GRADO_LON, LAT + norte_m / geo.METROS_POR_GRADO_LAT)


def cuadrado(este_m, norte_m, lado):
    return [
        desplazar(este_m, norte_m),
        desplazar(este_m + lado, norte_m),
        desplazar(este_m + lado, norte_m + lado),
        desplazar(este_m, norte_m + lado),
    ]


# --- proyectar_punto ---------------------------------------------------------

@pytest.mark.parametrize("este,norte,azimut_esperado", [
    (0, 100, 0.0),      # norte
    (100, 0, 90.0),     # este
    (0, -100, 180.0),   # sur
    (-100, 0, 270.0),   # oeste
])
def test_el_azimut_apunta_al_rumbo_correcto(este, norte, azimut_esperado):
    azimut, _, _ = proyectar_punto(VISTA, desplazar(este, norte))
    assert azimut == pytest.approx(azimut_esperado, abs=0.01)


def test_a_45_grados_de_depresion_la_distancia_iguala_la_altura():
    _, elevacion, distancia = proyectar_punto(VISTA, desplazar(100, 0))
    assert distancia == pytest.approx(100.0, rel=1e-6)
    assert elevacion == pytest.approx(-45.0, abs=0.01)


def test_lo_que_esta_bajo_el_dron_cae_al_nadir():
    _, elevacion, _ = proyectar_punto(VISTA, (LON, LAT))
    assert elevacion == pytest.approx(-90.0)


def test_todo_el_suelo_queda_bajo_el_horizonte():
    for distancia in (10, 100, 1000, 5000):
        _, elevacion, _ = proyectar_punto(VISTA, desplazar(distancia, 0))
        assert elevacion < 0


def test_mientras_mas_lejos_menos_depresion():
    _, cerca, _ = proyectar_punto(VISTA, desplazar(50, 0))
    _, lejos, _ = proyectar_punto(VISTA, desplazar(500, 0))
    assert cerca < lejos < 0


def test_un_terreno_mas_alto_sube_la_elevacion_del_punto():
    punto = desplazar(300, 0)
    _, al_nivel, _ = proyectar_punto(VISTA, punto)
    _, en_alto, _ = proyectar_punto(VISTA, punto, cota_terreno=VISTA.terreno_plano() + 40)
    assert en_alto > al_nivel


# --- separación angular ------------------------------------------------------

def test_la_separacion_angular_cruza_bien_el_norte():
    assert separacion_angular((359.0, 0.0), (1.0, 0.0)) == pytest.approx(2.0, abs=1e-6)


def test_la_separacion_angular_entre_polos_es_180():
    assert separacion_angular((0.0, 90.0), (0.0, -90.0)) == pytest.approx(180.0, abs=1e-6)


def test_el_area_angular_de_un_parche_pequeno_es_base_por_altura():
    # Un cuadrado de 2° × 2° centrado en el horizonte mide 4 grados².
    anillo = [(-1.0, -1.0), (1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)]
    assert area_angular(anillo, (0.0, 0.0)) == pytest.approx(4.0, rel=0.01)


def test_el_area_angular_no_depende_de_donde_este_el_parche():
    anillo = lambda az, el: [(az - 1, el - 1), (az + 1, el - 1), (az + 1, el + 1), (az - 1, el + 1)]
    # Cerca del nadir el azimut se comprime, así que hay que comparar figuras
    # equivalentes: un parche de 2°x2° en elevación pero corregido en azimut.
    referencia = area_angular(anillo(0, 0), (0.0, 0.0))
    assert area_angular(anillo(200, 0), (200.0, 0.0)) == pytest.approx(referencia, rel=0.01)


def test_el_area_angular_cruza_bien_el_norte():
    anillo = [(359.0, -1.0), (1.0, -1.0), (1.0, 1.0), (359.0, 1.0)]
    assert area_angular(anillo, (0.0, 0.0)) == pytest.approx(4.0, rel=0.02)


def test_el_area_angular_funciona_mirando_al_nadir():
    anillo = [(0.0, -89.0), (90.0, -89.0), (180.0, -89.0), (270.0, -89.0)]
    assert area_angular(anillo, (0.0, -90.0)) > 0


def test_el_area_angular_de_un_anillo_degenerado_es_cero():
    assert area_angular([(0.0, 0.0), (1.0, 0.0)], (0.5, 0.0)) == 0.0


def test_el_area_angular_ignora_lo_que_queda_detras():
    anillo = [(0.0, 0.0), (100.0, 0.0), (200.0, 0.0)]
    assert area_angular(anillo, (0.0, 0.0)) == 0.0


def test_una_parcela_lejana_tiene_mucha_menos_area_que_una_cercana():
    cerca = proyectar_parcela(VISTA, "A1", cuadrado(100, 0, 70))
    lejos = proyectar_parcela(VISTA, "A2", cuadrado(1000, 0, 70))
    assert cerca.area_angular > 20 * lejos.area_angular


def test_las_direcciones_son_unitarias():
    for azimut, elevacion in [(0, 0), (37, -12), (270, -89)]:
        x, y, z = direccion(azimut, elevacion)
        assert math.sqrt(x * x + y * y + z * z) == pytest.approx(1.0)


# --- proyectar_parcela -------------------------------------------------------

def test_la_parcela_bajo_el_dron_queda_centrada_en_el_nadir():
    anillo = cuadrado(-35, -35, 70)
    p = proyectar_parcela(VISTA, "A1", anillo)
    assert p.centro[1] < -50   # bien abajo
    assert p.distancia_m < 1.0


def test_subdivide_las_aristas_largas():
    lejana = cuadrado(200, -35, 70)
    p = proyectar_parcela(VISTA, "A1", lejana)
    assert len(p.anillo) > 4, "una arista de 70 m a 200 m abarca varios grados"
    for a, b in zip(p.anillo, p.anillo[1:] + p.anillo[:1]):
        assert separacion_angular(a, b) <= 1.6


def test_no_subdivide_lo_que_ya_es_suficientemente_corto():
    p = proyectar_parcela(VISTA, "A1", cuadrado(1500, 0, 20), segmento_maximo=90.0)
    assert len(p.anillo) == 4


def test_una_parcela_mas_lejana_se_ve_mas_chica():
    cerca = proyectar_parcela(VISTA, "A1", cuadrado(100, 0, 70))
    lejos = proyectar_parcela(VISTA, "A2", cuadrado(1000, 0, 70))
    assert cerca.ancho_angular > lejos.ancho_angular


def test_un_anillo_sin_area_no_se_proyecta():
    assert proyectar_parcela(VISTA, "A1", [(LON, LAT), (LON, LAT)]) is None


def test_la_parcela_al_este_queda_en_azimut_90():
    p = proyectar_parcela(VISTA, "A1", cuadrado(300, -35, 70))
    assert p.centro[0] == pytest.approx(90.0, abs=1.0)


# --- visibilidad -------------------------------------------------------------

def parcela(distancia=100.0, ancho=5.0, area=8.0, elevacion=-30.0):
    return ParcelaProyectada("A1", [(0.0, elevacion)], (0.0, elevacion),
                             distancia, ancho, area)


def test_descarta_lo_que_esta_demasiado_lejos():
    assert not es_visible(parcela(distancia=5000.0))
    assert es_visible(parcela(distancia=500.0))


def test_descarta_lo_que_se_ve_demasiado_chico():
    assert not es_visible(parcela(ancho=0.2))
    assert es_visible(parcela(ancho=3.0))


def test_descarta_la_astilla_ancha_pero_sin_area():
    """Una parcela lejana puede medir 4° de ancho y aun así ser imposible de clickear."""
    assert not es_visible(parcela(ancho=4.0, area=0.1))


def test_descarta_lo_que_queda_al_ras_del_horizonte():
    assert not es_visible(parcela(elevacion=-0.3))
    assert es_visible(parcela(elevacion=-10.0))


# --- proyectar_vista ---------------------------------------------------------

def test_la_vista_ordena_las_parcelas_de_cerca_a_lejos():
    entrada = [
        ("A-lejos", cuadrado(800, 0, 70)),
        ("A-cerca", cuadrado(120, 0, 70)),
        ("A-medio", cuadrado(400, 0, 70)),
    ]
    resultado = proyectar_vista(VISTA, entrada)
    assert [p.id for p in resultado] == ["A-cerca", "A-medio", "A-lejos"]


def test_la_vista_filtra_lo_que_no_se_ve():
    entrada = [
        ("A-visible", cuadrado(200, 0, 70)),
        ("A-lejisimos", cuadrado(50000, 0, 70)),
    ]
    resultado = proyectar_vista(VISTA, entrada)
    assert [p.id for p in resultado] == ["A-visible"]


def test_el_modelo_de_terreno_se_aplica_a_toda_la_parcela():
    anillo = cuadrado(300, -35, 70)
    plano = proyectar_parcela(VISTA, "A1", anillo)
    elevado = proyectar_parcela(VISTA, "A1", anillo,
                                terreno=lambda p: VISTA.terreno_plano() + 30)
    assert elevado.centro[1] > plano.centro[1]
    assert all(e2 > e1 for (_, e1), (_, e2) in zip(plano.anillo, elevado.anillo))
