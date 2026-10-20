"""Puntos de referencia en el horizonte: pueblos cercanos para orientarse."""
import json
import math

import pytest

from pipeline.proyeccion import Vista
from pipeline.referencias import RADIO_TIERRA_EFECTIVO_M, Referencia, leer_entrada, proyectar, resolver

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


# --- Tiempos de viaje y coordenadas escritas en la consola -----------------------

@pytest.mark.parametrize("texto, esperado", [
    ("Quillón 10 minutos", {"nombre": "Quillón", "tiempo": "10 min"}),
    ("Playa Laguna Avendaño 14 minutos", {"nombre": "Playa Laguna Avendaño", "tiempo": "14 min"}),
    ("Los Ángeles 1 hora 20 minutos", {"nombre": "Los Ángeles", "tiempo": "1 h 20 min"}),
    ("Los Ángeles 1 h y 20 min", {"nombre": "Los Ángeles", "tiempo": "1 h 20 min"}),
    ("Concepción 90 min", {"nombre": "Concepción", "tiempo": "1 h 30 min"}),
    ("Chillán 2 horas", {"nombre": "Chillán", "tiempo": "2 h"}),
    ("Ruta 5 20 minutos", {"nombre": "Ruta 5", "tiempo": "20 min"}),
    ("Ruta 5", {"nombre": "Ruta 5"}),
    ("Cauquenes", {"nombre": "Cauquenes"}),
    ("Ruta 5 (-36.7465, -72.3378) 20 min",
     {"nombre": "Ruta 5", "tiempo": "20 min", "lat": -36.7465, "lon": -72.3378}),
    ("Parque Acuático Antu 22 minutos (-36.80, -72.40)",
     {"nombre": "Parque Acuático Antu", "tiempo": "22 min", "lat": -36.80, "lon": -72.40}),
])
def test_lee_el_tiempo_y_las_coordenadas_del_texto(texto, esperado):
    assert leer_entrada(texto) == esperado


def test_el_tiempo_se_rotula_y_no_queda_en_el_cache(tmp_path):
    cache = tmp_path / "ref.json"
    con_tiempo = resolver(["Cauquenes 15 minutos"], LOTEO, cache, geocodificar=geocodificador_falso)

    assert con_tiempo[0].nombre == "Cauquenes"
    assert con_tiempo[0].tiempo == "15 min"
    assert "tiempo" not in json.loads(cache.read_text(encoding="utf-8"))["CL|cauquenes"] or \
        json.loads(cache.read_text(encoding="utf-8"))["CL|cauquenes"]["tiempo"] is None
    # Otro loteo que pide el mismo pueblo sin tiempo no hereda el del primero.
    sin_tiempo = resolver(["Cauquenes"], LOTEO, cache, geocodificar=geocodificador_falso)
    assert sin_tiempo[0].tiempo is None


def test_con_coordenadas_no_se_pregunta_al_geocodificador(tmp_path):
    def sin_red(nombre, pais):
        raise AssertionError("no debería preguntar")

    referencias = resolver(["Ruta 5 (-36.7465, -72.3378) 20 min"], LOTEO, tmp_path / "ref.json",
                           geocodificar=sin_red)

    assert referencias == [Referencia(nombre="Ruta 5", lon=-72.3378, lat=-36.7465, tiempo="20 min")]


def test_la_proyeccion_lleva_el_tiempo_si_lo_hay():
    vista = Vista(id="p01-200", posicion=1, lon=-72.0, lat=-35.0,
                  altura_relativa=200.0, altura_absoluta=480.0, rumbo0=0.0)
    hito = Referencia(nombre="Quillón", lon=-72.0, lat=-34.95, tiempo="10 min")

    assert proyectar(vista, hito, vista.terreno_plano())["tiempo"] == "10 min"
    assert "tiempo" not in proyectar(vista, Referencia("Norte", -72.0, -34.95), vista.terreno_plano())


def _plano(cota):
    from pipeline.tests.test_terreno import png_terrarium
    tesela = png_terrarium(cota)
    return lambda url: tesela


def test_un_pueblo_en_el_llano_se_ve_desde_el_dron(tmp_path):
    from pipeline.referencias import cresta
    pueblo = Referencia(nombre="Quillón", lon=-72.40, lat=-36.74, cota=100.0)
    assert cresta((-72.47, -36.73), 600.0, pueblo, tmp_path, descarga=_plano(100.0)) is None


def test_un_pueblo_detras_de_los_cerros_da_la_cumbre_que_lo_tapa(tmp_path):
    from pipeline.referencias import cresta
    # El dron vuela a 600 m sobre un terreno de 900 m: todo lo que está más allá queda tapado.
    pueblo = Referencia(nombre="Chillán", lon=-72.10, lat=-36.61, cota=120.0)
    cumbre = cresta((-72.47, -36.73), 600.0, pueblo, tmp_path, descarga=_plano(900.0))
    assert cumbre is not None and cumbre.nombre == "Chillán"
    assert cumbre.cota == pytest.approx(900.0, abs=1.0)
    # La cumbre está en el camino hacia el pueblo, no más allá.
    assert -72.47 < cumbre.lon < -72.10


def test_sin_cota_no_se_puede_saber_y_se_da_por_visible(tmp_path):
    from pipeline.referencias import cresta
    pueblo = Referencia(nombre="Bulnes", lon=-72.30, lat=-36.74)
    assert cresta((-72.47, -36.73), 600.0, pueblo, tmp_path, descarga=_plano(900.0)) is None
