"""Puntos de referencia en el horizonte: pueblos cercanos para orientarse."""
import json
import math

import pytest

from pipeline.proyeccion import Vista
from pipeline.referencias import RADIO_TIERRA_EFECTIVO_M, Referencia, proyectar, resolver

LOTEO = (-72.273, -35.863)

CANDIDATOS = {
    "Cauquenes": [
        {"name": "Cauquenes Airport", "latitude": -35.971, "longitude": -72.225, "elevation": 164.0},
        {"name": "Cauquenes", "latitude": -35.967, "longitude": -72.322, "elevation": 172.0},
    ],
    "Chanco": [
        {"name": "Chanco", "latitude": -36.286, "longitude": -72.711, "elevation": 450.0},   # el de Itata
        {"name": "Chanco", "latitude": -35.737, "longitude": -72.533, "elevation": 39.0},    # el de Cauquenes
    ],
}


def geocodificador_falso(nombre, pais):
    assert pais == "CL"
    return CANDIDATOS[nombre]


def test_resuelve_nombres_eligiendo_el_candidato_mas_cercano(tmp_path):
    referencias = resolver(["Cauquenes", "Chanco"], LOTEO, tmp_path / "ref.json",
                           geocodificar=geocodificador_falso)

    assert [r.nombre for r in referencias] == ["Cauquenes", "Chanco"]
    assert referencias[0].lon == pytest.approx(-72.322)
    assert referencias[0].cota == 172.0
    assert referencias[1].lat == pytest.approx(-35.737)


def test_una_referencia_con_coordenadas_pasa_tal_cual(tmp_path):
    referencias = resolver([{"nombre": "Fundo El Peumo", "lon": -72.30, "lat": -35.90}], LOTEO,
                           tmp_path / "ref.json", geocodificar=geocodificador_falso)

    assert referencias == [Referencia(nombre="Fundo El Peumo", lon=-72.30, lat=-35.90, cota=None)]


def test_lo_geocodificado_queda_en_cache(tmp_path):
    cache = tmp_path / "ref.json"
    resolver(["Cauquenes"], LOTEO, cache, geocodificar=geocodificador_falso)

    def sin_red(nombre, pais):
        raise AssertionError("no debería volver a preguntar")

    de_nuevo = resolver(["Cauquenes"], LOTEO, cache, geocodificar=sin_red)

    assert de_nuevo[0].lat == pytest.approx(-35.967)
    assert "cauquenes" in json.loads(cache.read_text(encoding="utf-8"))["CL|cauquenes"]["nombre"].lower()


def test_un_nombre_que_no_existe_se_salta_con_aviso(tmp_path):
    def geocodificador_vacio(nombre, pais):
        return []

    referencias = resolver(["Villa Inexistente"], LOTEO, tmp_path / "ref.json",
                           geocodificar=geocodificador_vacio)

    assert referencias == []


def test_proyecta_al_horizonte_con_la_curvatura_de_la_tierra():
    vista = Vista(id="p01-200", posicion=1, lon=-72.0, lat=-35.0,
                  altura_relativa=200.0, altura_absoluta=480.0, rumbo0=0.0)
    al_norte = Referencia(nombre="Norte", lon=-72.0, lat=-35.0 + 10000 / 111320.0, cota=None)

    punto = proyectar(vista, al_norte, vista.terreno_plano())

    esperado = -math.degrees(math.atan2(200.0, 10000.0)) - math.degrees(10000.0 / (2 * RADIO_TIERRA_EFECTIVO_M))
    assert punto["nombre"] == "Norte"
    assert punto["az"] == pytest.approx(0.0, abs=0.01)
    assert punto["el"] == pytest.approx(esperado, abs=0.01)
    assert punto["distancia_km"] == pytest.approx(10.0, abs=0.05)
