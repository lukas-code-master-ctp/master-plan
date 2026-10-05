import json
import math
import zipfile
from xml.etree import ElementTree as ET

import numpy as np
import pytest

from pipeline import geo
from pipeline.kmz import NS, leer_kmz
from pipeline.plano.__main__ import main
from pipeline.plano.georreferencia import Transformacion
from pipeline.plano.salida import escribir_kmz, geojson, kml, lotes_utm

# 0,5 m/px, girada 10°, en Chile central (19S).
ESCALA = 0.5
_a = ESCALA * complex(math.cos(math.radians(10)), math.sin(math.radians(10)))
MATRIZ = np.array([[_a.real, _a.imag, 280000.0], [_a.imag, -_a.real, 6290000.0], [0, 0, 1.0]])


def _transformacion():
    return Transformacion("anclas", "similitud", 32719, MATRIZ.copy())


def _cuadro(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def _digitalizado():
    lotes = [
        dict(numero="1", poligono=_cuadro(0, 0, 400, 300), huecos=[]),
        dict(numero="2", poligono=_cuadro(400, 0, 800, 300), huecos=[]),
        # El 3 rodea un bolsón que no es suyo (un lote ajeno, una laguna): un hueco.
        dict(numero="A3", poligono=_cuadro(0, 300, 800, 700), huecos=[_cuadro(300, 400, 500, 600)]),
    ]
    return dict(lotes=lotes, sin_numero=[dict(poligono=_cuadro(800, 0, 900, 100))])


AREAS_PX = {"1": 120000, "2": 120000, "A3": 320000 - 40000}


def test_las_areas_salen_en_metros_utm():
    areas = {n: p.area for n, p in lotes_utm(_digitalizado(), _transformacion())}
    for n, px in AREAS_PX.items():
        assert abs(areas[n] - px * ESCALA ** 2) < 1e-6


def test_el_kmz_lo_lee_pipeline_kmz(tmp_path):
    destino = tmp_path / "subdivision.kmz"

    assert escribir_kmz(destino, _digitalizado(), _transformacion()) == 3

    assert [p.name for p in tmp_path.iterdir()] == ["subdivision.kmz"]       # sin temporales
    parcelas = leer_kmz(destino)
    assert sorted(p.id for p in parcelas) == ["1", "2", "A3"]
    for p in parcelas:
        # pipeline.kmz lee solo el anillo exterior; el área local es ≈ la UTM.
        exterior = AREAS_PX[p.id] + (40000 if p.id == "A3" else 0)
        assert abs(p.area_m2 / (exterior * ESCALA ** 2) - 1) < 0.005


def test_el_kml_trae_poligonos_con_huecos_y_nada_mas():
    raiz = ET.fromstring(kml(_digitalizado(), _transformacion()))

    assert raiz.tag == NS + "kml"
    marcas = list(raiz.iter(NS + "Placemark"))
    assert [m.find(NS + "name").text for m in marcas] == ["LOTE 1", "LOTE 2", "LOTE A3"]
    assert not list(raiz.iter(NS + "LineString")) and not list(raiz.iter(NS + "Point"))
    assert len(list(raiz.iter(NS + "Polygon"))) == 3
    huecos = list(marcas[2].iter(NS + "innerBoundaryIs"))
    assert len(huecos) == 1
    datos = {d.get("name"): float(d.find(NS + "value").text) for d in marcas[2].iter(NS + "Data")}
    assert abs(datos["area_m2"] - AREAS_PX["A3"] * ESCALA ** 2) < 0.1
    assert "m²" in marcas[2].find(NS + "description").text


def test_area_oficial_va_en_extended_data():
    d = _digitalizado()
    d["lotes"][0]["area_oficial"] = 30000
    raiz = ET.fromstring(kml(d, _transformacion()))
    primera = next(raiz.iter(NS + "Placemark"))
    assert {x.get("name") for x in primera.iter(NS + "Data")} == {"area_m2", "area_oficial_m2"}


def test_numeros_repetidos_o_ilegibles_fallan():
    d = _digitalizado()
    d["lotes"][1]["numero"] = "01"           # "LOTE 01" y "LOTE 1" son el mismo id
    with pytest.raises(ValueError, match="repetidos"):
        kml(d, _transformacion())
    d["lotes"][1]["numero"] = "12b?"
    with pytest.raises(ValueError, match="no reconoce"):
        kml(d, _transformacion())


def test_el_nombre_va_como_en_el_plano_y_se_compara_normalizado(tmp_path):
    # Caminos de Rapel: "LOTE 8-01", con el cero; el master lo lee como "8-1".
    d = _digitalizado()
    for lote, n in zip(d["lotes"], ("8-01", "8-02", "10-6")):
        lote["numero"] = n
    raiz = ET.fromstring(kml(d, _transformacion()))
    assert [m.find(NS + "name").text for m in raiz.iter(NS + "Placemark")] == ["LOTE 8-01", "LOTE 8-02", "LOTE 10-6"]
    destino = tmp_path / "s.kmz"
    escribir_kmz(destino, d, _transformacion())
    assert sorted(p.id for p in leer_kmz(destino)) == ["10-6", "8-1", "8-2"]
    # "8-1" y "8-01" son el mismo lote: repetido, nombrado como vino.
    d["lotes"][1]["numero"] = "8-1"
    with pytest.raises(ValueError, match="repetidos: 8-01, 8-1"):
        kml(d, _transformacion())


def test_geojson_en_lon_lat_con_huecos():
    g = geojson(_digitalizado(), _transformacion())

    assert g["type"] == "FeatureCollection" and len(g["features"]) == 3
    tercero = g["features"][2]
    assert tercero["properties"]["numero"] == "A3"
    anillos = tercero["geometry"]["coordinates"]
    assert len(anillos) == 2
    lon, lat = np.array(anillos[0]).T
    assert -72 < lon.mean() < -66 and -40 < lat.mean() < -30
    assert abs(geo.area_m2([tuple(c) for c in anillos[0][:-1]]) / (320000 * ESCALA ** 2) - 1) < 0.005
    json.dumps(g)


def test_kmz_desde_la_carpeta(tmp_path, capsys):
    (tmp_path / "entradas.json").write_text("{}", encoding="utf-8")
    (tmp_path / "digitalizado.json").write_text(json.dumps(_digitalizado()), encoding="utf-8")
    destino = tmp_path / "salida.kmz"

    assert main(["kmz", str(tmp_path), str(destino)]) == 1
    assert "georreferencia.json" in capsys.readouterr().err

    (tmp_path / "georreferencia.json").write_text(json.dumps(_transformacion().a_dict()), encoding="utf-8")
    assert main(["kmz", str(tmp_path), str(destino)]) == 0
    assert "KMZ: 3 lotes" in capsys.readouterr().out
    with zipfile.ZipFile(destino) as z:
        assert z.namelist() == ["doc.kml"]
    assert len(leer_kmz(destino)) == 3
