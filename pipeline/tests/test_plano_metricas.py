import json
import math
import zipfile
from pathlib import Path

import numpy as np
import pytest
from shapely.affinity import rotate, scale, translate
from shapely.geometry import box

from pipeline.plano import regresion
from pipeline.plano.georreferencia import _transformador
from pipeline.plano.metricas import comparar, lotes_kmz, numero, topologia, umeyama

EPSG = 32719
ORIGEN = (280000.0, 6290000.0)       # Chile central, huso 19S


def _grilla(columnas=4, filas=3, lado=50.0):
    x0, y0 = ORIGEN
    return {str(f * columnas + c + 1): box(x0 + c * lado, y0 + f * lado, x0 + (c + 1) * lado, y0 + (f + 1) * lado)
            for f in range(filas) for c in range(columnas)}


def test_numero_de_lote():
    assert numero("LOTE 12") == "12"
    assert numero("LOTE-07") == "7"
    assert numero(" 12.") == "12"
    assert numero("LOTES 3") == "3"
    assert numero("ANCLA") is None
    assert numero(None) is None
    # Par sector-lote (Caminos de Rapel), normalizado como en el master.
    assert numero("Lote 8-01") == numero("8-01") == numero("8-1") == "8-1"
    assert numero("ROL 409-37 ETAPA 1") is None and numero("A12") is None


def test_iguales():
    real = _grilla()
    m = comparar(dict(real), real)
    assert m["pareados"] == 12 and not m["solo_candidato"] and not m["solo_real"]
    assert m["tal_cual"]["iou_mediana"] == pytest.approx(1.0)
    assert m["tal_cual"]["centroide_mediana_m"] == pytest.approx(0.0, abs=1e-6)
    assert m["what_if"]["hausdorff_p90_m"] == pytest.approx(0.0, abs=1e-6)
    assert m["topologia"] == pytest.approx(dict(traslapes_m2=0, huecos_m2=0, partes=1, area_m2=12 * 2500))


def test_similitud_optima_recupera_la_georreferencia():
    # El candidato es el real girado 0,5°, escalado +1 % y corrido (dE, dN) = (-4, +3) m:
    # tal cual empeora; con la similitud óptima vuelve a calzar.
    real = _grilla()
    centro = (ORIGEN[0] + 100, ORIGEN[1] + 75)
    cand = {n: translate(scale(rotate(p, 0.5, origin=centro), 1.01, 1.01, origin=centro), -4, 3)
            for n, p in real.items()}
    m = comparar(cand, real)
    assert m["tal_cual"]["iou_mediana"] < 0.9
    assert m["tal_cual"]["centroide_mediana_m"] > 4
    assert m["what_if"]["iou_mediana"] == pytest.approx(1.0, abs=1e-6)
    assert m["what_if"]["centroide_mediana_m"] == pytest.approx(0.0, abs=1e-6)
    s = m["similitud"]
    assert s["rotacion_grados"] == pytest.approx(-0.5, abs=1e-6)
    assert s["escala_pct"] == pytest.approx(100 * (1 / 1.01 - 1), abs=1e-6)
    assert (s["de_m"], s["dn_m"]) == pytest.approx((4.0, -3.0), abs=1e-6)
    # El error de área tal cual es el de la escala: 1,01² − 1.
    assert m["tal_cual"]["error_area_mediana_pct"] == pytest.approx(2.01, abs=1e-6)


def test_umeyama():
    rng = np.random.default_rng(1)
    origen = rng.uniform(-100, 100, (20, 2))
    a = math.radians(30)
    R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    destino = 2.0 * origen @ R.T + [5, -7]
    s, R2, t = umeyama(origen, destino)
    assert s == pytest.approx(2.0) and np.allclose(R2, R) and np.allclose(t, [5, -7])


def test_lote_que_falta_y_hausdorff():
    real = _grilla()
    cand = dict(real)
    del cand["5"]
    cand["1"] = box(*real["1"].bounds[:3], real["1"].bounds[3] + 2)   # 2 m más alto
    m = comparar(cand, real)
    assert m["pareados"] == 11 and m["solo_real"] == ["5"]
    assert m["tal_cual"]["hausdorff_max_m"] == pytest.approx(2.0)


def test_topologia_traslapes_y_huecos():
    real = _grilla()
    real["1"] = box(*real["1"].bounds[:2], real["1"].bounds[2] + 1, real["1"].bounds[3])  # pisa 1 m al 2
    del real["6"]                                                                         # deja un hueco
    t = topologia(real.values())
    assert t["traslapes_m2"] == pytest.approx(50.0)
    assert t["huecos_m2"] == pytest.approx(2500.0)
    assert t["partes"] == 1


# --- lectura de KMZ ----------------------------------------------------------

def _kmz(ruta: Path, marcas: list[str]) -> Path:
    kml = ('<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           + "".join(marcas) + "</Document></kml>")
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("doc.kml", kml)
    return ruta


def _ll(coords):
    lon, lat = _transformador(EPSG, 4326).transform(*np.asarray(coords, float).T)
    return " ".join(f"{a:.10f},{b:.10f},0" for a, b in zip(lon, lat))


def _marca(nombre, capa, tipo, coords):
    geom = {"P": f"<Point><coordinates>{_ll(coords)}</coordinates></Point>",
            "L": f"<LineString><coordinates>{_ll(coords)}</coordinates></LineString>",
            "A": f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{_ll(coords)}</coordinates>"
                 "</LinearRing></outerBoundaryIs></Polygon>"}[tipo]
    return (f"<Placemark>{f'<name>{nombre}</name>' if nombre else ''}"
            f"{f'<description>{capa}</description>' if capa else ''}{geom}</Placemark>")


def test_kmz_de_poligonos_con_nombre_o_con_punto_adentro(tmp_path):
    g = _grilla(2, 1)
    marcas = [_marca("LOTE 1", None, "A", g["1"].exterior.coords),
              _marca(None, None, "A", g["2"].exterior.coords),
              _marca("LOTE 2", None, "P", [g["2"].centroid.coords[0]]),
              _marca(None, "CAMINOS", "A", box(ORIGEN[0], ORIGEN[1] - 10, ORIGEN[0] + 100, ORIGEN[1]).exterior.coords)]
    lotes, informe = lotes_kmz(_kmz(tmp_path / "a.kmz", marcas), EPSG, capas_excluidas=["CAMINOS"])
    assert informe["modo"] == "poligonos" and informe["capas_excluidas"] == [("CAMINOS", 1)]
    assert sorted(lotes) == ["1", "2"]
    assert lotes["2"].symmetric_difference(g["2"]).area < 0.01


def test_kmz_de_poligonos_sin_nombre_y_puntos_sector_lote(tmp_path):
    # El real de Caminos de Rapel: polígonos sin nombre, puntos "Lote 8-NN" y las líneas
    # de los caminos. Se rotula por punto en polígono y el número va normalizado.
    g = _grilla(2, 1)
    marcas = [_marca(None, "0", "A", g[n].exterior.coords) for n in g]
    marcas += [_marca(f"Lote 8-0{n}", "C-PROP-TEXT", "P", [g[n].centroid.coords[0]]) for n in g]
    marcas.append(_marca(None, "0 - CAMINOS", "L", [ORIGEN, (ORIGEN[0] + 100, ORIGEN[1])]))
    lotes, informe = lotes_kmz(_kmz(tmp_path / "r.kmz", marcas), EPSG)
    assert informe["modo"] == "poligonos" and sorted(lotes) == ["8-1", "8-2"]
    assert lotes["8-2"].symmetric_difference(g["2"]).area < 0.01


def test_comparar_empareja_por_numero_normalizado():
    g = _grilla(2, 1)
    candidato = {"8-1": g["1"], "8-2": g["2"]}          # lotes_kmz del candidato "LOTE 8-01"
    m = comparar(candidato, {"8-1": g["1"], "8-2": g["2"]})
    assert m["pareados"] == 2 and m["what_if"]["iou_mediana"] > 0.999


def test_kmz_de_lineas_se_cierra_y_se_rotula(tmp_path):
    # Un CAD: el perímetro como polígono, las divisorias como líneas sueltas (una
    # queda a 0,5 m del perímetro), los bordes de camino en otra capa y un punto por lote.
    g = _grilla(3, 1)
    x0, y0 = ORIGEN
    perimetro = box(x0, y0, x0 + 150, y0 + 50)
    marcas = [_marca("EJE", "PERIMETRO", "A", perimetro.exterior.coords),
              _marca(None, "LOTES", "L", [(x0 + 50, y0), (x0 + 50, y0 + 50)]),
              _marca(None, "LOTES", "L", [(x0 + 100, y0 + 0.5), (x0 + 100, y0 + 50)]),
              _marca(None, "SERVIDUMBRE", "L", [(x0, y0 + 25), (x0 + 150, y0 + 25)])]
    marcas += [_marca(f"LOTE {n}", "ROTULOS", "P", [p.centroid.coords[0]]) for n, p in g.items()]
    ruta = _kmz(tmp_path / "b.kmz", marcas)

    lotes, informe = lotes_kmz(ruta, EPSG, capas_excluidas=["SERVIDUMBRE"])
    assert informe["modo"] == "lineas" and informe["conectores"] >= 1
    assert sorted(lotes) == ["1", "2", "3"]
    for n, p in g.items():
        assert lotes[n].symmetric_difference(p).area < 0.5
    # Con los bordes de camino, cada lote queda partido en dos y ninguna cara tiene rótulo único… salvo
    # las que tienen el punto: se pierde la mitad del lote.
    con_camino, _ = lotes_kmz(ruta, EPSG)
    assert all(con_camino[n].area < 0.6 * g[n].area for n in con_camino)


# --- comparación con la línea base -------------------------------------------

def _fila(iou, d, pareados=50, lotes=60):
    return dict(lotes=lotes, pareados=pareados, what_if=dict(n=pareados, iou_mediana=iou, centroide_mediana_m=d,
                                                            hausdorff_mediana_m=1.0),
                tal_cual=dict(iou_mediana=0.8, centroide_mediana_m=5.0))


def test_tolerancias_de_la_linea_base():
    base = regresion.resumen_base(_fila(0.95, 1.0))
    assert regresion.regresiones(_fila(0.945, 1.2), base) == []
    assert regresion.regresiones(_fila(0.96, 0.5, pareados=51, lotes=61), base) == []
    assert any("IoU" in m for m in regresion.regresiones(_fila(0.939, 1.0), base))
    assert any("centroide" in m for m in regresion.regresiones(_fila(0.95, 1.26), base))
    assert any("pareados" in m for m in regresion.regresiones(_fila(0.95, 1.0, pareados=49), base))
    assert any("lotes" in m for m in regresion.regresiones(_fila(0.95, 1.0, lotes=59), base))
    # Sin real (Hidango): solo cuenta que no se pierdan lotes.
    assert regresion.regresiones(dict(lotes=58), dict(lotes=58)) == []
    assert regresion.regresiones(dict(lotes=57), dict(lotes=58))


def test_sin_carpeta_de_regresion_sale_con_2(tmp_path, capsys):
    assert regresion.main(["--carpeta", str(tmp_path / "no")]) == 2


# --- el set real (fuera de git) ----------------------------------------------

SET = Path(__file__).resolve().parents[2] / "regresion" / "planos"


@pytest.mark.skipif(not SET.is_dir(), reason="el set de regresión vive fuera de git")
def test_los_kmz_reales_del_set_dan_sus_lotes():
    esperados = {"el_arrayan": 183, "puente_negro": 58, "algarrobo": 76, "curico": 49, "caminos_de_rapel": 16}
    for plano, n in esperados.items():
        carpeta = SET / plano
        if not (carpeta / "real.kmz").is_file():
            continue
        e = json.loads((carpeta / "entradas.json").read_text(encoding="utf-8"))
        lotes, informe = lotes_kmz(carpeta / "real.kmz", None, (e.get("regresion") or {}).get("capas_excluidas") or [])
        assert len(lotes) == n, (plano, informe)
        assert not informe["repetidos"]
