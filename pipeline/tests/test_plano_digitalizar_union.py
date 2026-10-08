"""Digitalizar sobre la unión de hojas (la "página 0"): ver
docs/specs/2026-10-06-kmz-unir-hojas.md."""
import io
import json
import re

import numpy as np
import pymupdf
import pytest
from PIL import Image
from shapely.geometry import Polygon

from pipeline.plano import pagina as pg
from pipeline.plano import rotulos
from pipeline.plano import union as un
from pipeline.plano.digitalizar import _mascaras, _previo, digitalizar, huella_lector, leer_entradas
from pipeline.tests.plano_sintetico import PPMM, dibujar

# El plano sintético (1560×1026 px) partido en dos láminas que se traslapan 200 px: la
# frontera de la unión (x = 800) cruza los lotes de la tercera columna.
CORTE_1, CORTE_2 = 900, 700          # la hoja 1 llega hasta x = 900; la 2 parte en x = 700
FRONTERA = 800


def _pdf(destino, imagenes):
    doc = pymupdf.open()
    for img in imagenes:
        buf = io.BytesIO()
        Image.fromarray(img).save(buf, "PNG")       # sin pérdida: la unión es el plano
        alto, ancho = img.shape[:2]
        hoja = doc.new_page(width=ancho / PPMM / pg.MM_POR_PUNTO, height=alto / PPMM / pg.MM_POR_PUNTO)
        hoja.insert_image(hoja.rect, stream=buf.getvalue())
    doc.save(destino)


def _entradas(plano, **cambios):
    alto, ancho = plano.imagen.shape[:2]
    return dict(pdf="plano.pdf", rectangulo=[100, 100, ancho - 20, alto - 5], mascaras=[],
                semillas=[dict(numero=n, x=x, y=y) for n, x, y in plano.semillas], lector=False,
                anclas=[], **cambios)


def _union(plano, cuadro=None):
    """Las dos hojas en su lugar exacto: la 1 tal cual, la 2 guardada de lado en el PDF
    (se lee con 90°). Cada una recortada hasta la frontera."""
    alto = plano.imagen.shape[0]
    ancho_2 = plano.imagen.shape[1] - CORTE_2
    return {"hojas": [
        {"n": 1, "rotacion": 0, "angulo": 0.0, "x": (CORTE_1 - 1) / 2, "y": (alto - 1) / 2,
         "recorte": [0, 0, FRONTERA, alto]},
        {"n": 2, "rotacion": 90, "angulo": 0.0, "x": CORTE_2 + (ancho_2 - 1) / 2, "y": (alto - 1) / 2,
         "recorte": [FRONTERA - CORTE_2, 0, ancho_2, alto]},
    ], "cuadro": cuadro}


def _carpeta_partida(carpeta, plano=None):
    plano = plano or dibujar()
    img = plano.imagen
    hoja_2 = pg.rotar(img[:, CORTE_2:], 270)        # de lado en el PDF
    _pdf(carpeta / "plano.pdf", [np.ascontiguousarray(img[:, :CORTE_1]), hoja_2])
    entradas = _entradas(plano, pagina=0, rotacion=0, union=_union(plano))
    (carpeta / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    return plano, entradas


@pytest.fixture(scope="module")
def plano():
    return dibujar()


def test_la_union_digitaliza_los_mismos_lotes_que_la_pagina_entera(tmp_path, plano):
    entera, partida = tmp_path / "entera", tmp_path / "partida"
    entera.mkdir()
    partida.mkdir()
    _pdf(entera / "plano.pdf", [plano.imagen])
    (entera / "entradas.json").write_text(json.dumps(_entradas(plano, pagina=1, rotacion=0)), encoding="utf-8")
    _carpeta_partida(partida, plano)
    lineas = []

    una = digitalizar(entera, avance=lambda _: None)
    unida = digitalizar(partida, avance=lineas.append)

    assert re.match(r"Hojas unidas 1 y 2: 156\d×102\d px, 6\.00 px/mm$", lineas[0]), lineas[0]
    pagina = unida["pagina"]
    assert (pagina["numero"], pagina["rotacion"], pagina["fuente"]) == (0, 0, "union")
    assert pagina["union"] == un.huella(un.leer(_union(plano)))
    # El ppmm de cada hoja sale del tamaño de la hoja del PDF, redondeado en puntos: las
    # dos difieren en ~1e-8 y la unión puede ganar un píxel de papel en el borde.
    assert abs(pagina["ancho"] - plano.imagen.shape[1]) <= 2 and abs(pagina["alto"] - plano.imagen.shape[0]) <= 2
    assert una["pagina"]["union"] is None
    areas = {l["numero"]: Polygon(l["poligono"], l["huecos"]).area for l in una["lotes"]}
    areas_unida = {l["numero"]: Polygon(l["poligono"], l["huecos"]).area for l in unida["lotes"]}
    assert len(areas) == len(plano.semillas)
    assert sorted(areas_unida) == sorted(areas)
    for n, area in areas.items():
        assert areas_unida[n] == pytest.approx(area, rel=0.02), n


def test_otra_union_no_reusa_lo_digitalizado(tmp_path, plano):
    _, entradas = _carpeta_partida(tmp_path, plano)
    digitalizar(tmp_path, avance=lambda _: None)
    huella = un.huella(un.leer(entradas["union"]))

    assert _previo(tmp_path, 0, 0, huella) is not None
    otra = json.loads(json.dumps(entradas["union"]))
    otra["hojas"][1]["x"] += 3
    assert _previo(tmp_path, 0, 0, un.huella(un.leer(otra))) is None
    assert _previo(tmp_path, 0, 0, None) is None
    # Y lo de una página suelta no se confunde con lo de una unión.
    assert _previo(tmp_path, 1, 0) is None


@pytest.mark.parametrize("cambio, mensaje", [
    (dict(union=None), "«pagina» 0 es la unión de hojas, y no hay hojas unidas"),
    (dict(pagina=1), "con las hojas unidas, «pagina» es 0 (la unión), no 1"),
    (dict(rotacion=90), "con las hojas unidas, «rotacion» es 0"),
    (dict(cuadro=[10, 10, 50, 50]), "el cuadro de superficies va en «union.cuadro»"),
    (dict(union={"hojas": [{"n": 1, "x": 0, "y": 0}]}), "la unión lleva entre 2 y 12 hojas"),
])
def test_entradas_de_la_union_malas(tmp_path, plano, cambio, mensaje):
    entradas = _entradas(plano, pagina=0, rotacion=0, union=_union(plano))
    entradas.update(cambio)
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    with pytest.raises(ValueError, match=mensaje.replace("(", r"\(").replace(")", r"\)")):
        leer_entradas(tmp_path)


def test_leer_entradas_normaliza_la_union(tmp_path, plano):
    union = _union(plano, cuadro={"hoja": 2, "rect": [10.4, 20, 300, 400]})
    union["hojas"][0]["x"] = int(union["hojas"][0]["x"])
    entradas = _entradas(plano, union=union)               # sin «pagina»: con unión es 0
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")

    leidas = leer_entradas(tmp_path)

    assert leidas["pagina"] == 0 and leidas["rotacion"] == 0
    assert leidas["union"] == un.leer(union).a_dic()
    assert leidas["union"]["cuadro"] == {"hoja": 2, "rect": [10, 20, 300, 400]}
    (tmp_path / "entradas.json").write_text(json.dumps(_entradas(plano)), encoding="utf-8")
    assert leer_entradas(tmp_path)["union"] is None


def test_la_huella_del_lector_cambia_con_la_union_y_su_cuadro(tmp_path, plano):
    _, entradas = _carpeta_partida(tmp_path, plano)
    base = huella_lector(tmp_path, leer_entradas(tmp_path))
    corrida = json.loads(json.dumps(entradas))
    corrida["union"]["hojas"][1]["y"] += 1
    con_cuadro = json.loads(json.dumps(entradas))
    con_cuadro["union"]["cuadro"] = {"hoja": 1, "rect": [10, 10, 200, 200]}
    otro_cuadro = json.loads(json.dumps(con_cuadro))
    otro_cuadro["union"]["cuadro"]["rect"] = [10, 10, 210, 200]
    huellas = [base]
    for e in (corrida, con_cuadro, otro_cuadro):
        (tmp_path / "entradas.json").write_text(json.dumps(e), encoding="utf-8")
        huellas.append(huella_lector(tmp_path, leer_entradas(tmp_path)))
    assert len(set(huellas)) == 4
    # Sin unión, la huella es la de siempre (sin la clave): los KMZ que ya existen no
    # vuelven a leer.
    sola = _entradas(plano, pagina=1, rotacion=0)
    (tmp_path / "entradas.json").write_text(json.dumps(sola), encoding="utf-8")
    normalizadas = leer_entradas(tmp_path)
    assert huella_lector(tmp_path, normalizadas) == huella_lector(
        tmp_path, {k: v for k, v in normalizadas.items() if k != "union"})


def _lector_falso(monkeypatch):
    vistos = []
    monkeypatch.setattr(rotulos, "motivo_no_disponible", lambda: None)
    monkeypatch.setattr(rotulos, "leer", lambda imagen, ppmm, avance, avance_en=None: [])
    monkeypatch.setattr(rotulos, "leer_cuadricula", lambda imagen, ppmm, avance, rectangulo: None)
    monkeypatch.setattr(rotulos, "leer_cuadro", lambda imagen, rects, avance: vistos.append(
        dict(imagen=imagen.copy(), rects=[list(r) for r in rects])) or {})
    return vistos


def test_el_cuadro_de_la_union_se_lee_de_su_hoja_original(tmp_path, monkeypatch, plano):
    _, entradas = _carpeta_partida(tmp_path, plano)
    rect = [FRONTERA - CORTE_2 - 50, 20, FRONTERA - CORTE_2 + 150, 300]
    entradas["union"]["cuadro"] = {"hoja": 2, "rect": rect}
    entradas["mascaras"] = [[1200, 900, 1300, 1000]]
    entradas["lector"] = True
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    vistos = _lector_falso(monkeypatch)

    digitalizar(tmp_path, avance=lambda _: None)

    # El trozo del cuadro en la hoja 2 tal como la ve la loteadora (girada 90°), no en la
    # unión ni en la fuente de lado; solo el trozo, para no copiar la hoja entera.
    x0, y0, x1, y1 = rect
    assert len(vistos) == 1 and vistos[0]["rects"] == [[0, 0, x1 - x0, y1 - y0]]
    assert np.array_equal(vistos[0]["imagen"], plano.imagen[y0:y1, CORTE_2 + x0:CORTE_2 + x1])
    # Está en px de la hoja: no tapa nada de la unión.
    assert _mascaras(leer_entradas(tmp_path)) == [[1200.0, 900.0, 1300.0, 1000.0]]


def test_sin_cuadro_se_prueban_las_mascaras_sobre_la_union(tmp_path, monkeypatch, plano):
    _, entradas = _carpeta_partida(tmp_path, plano)
    entradas["mascaras"] = [[1200, 900, 1300, 1000]]
    entradas["lector"] = True
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    vistos = _lector_falso(monkeypatch)

    digitalizar(tmp_path, avance=lambda _: None)

    assert len(vistos) == 1 and vistos[0]["rects"] == [[1200.0, 900.0, 1300.0, 1000.0]]
    alto, ancho = vistos[0]["imagen"].shape[:2]
    assert abs(ancho - plano.imagen.shape[1]) <= 2 and abs(alto - plano.imagen.shape[0]) <= 2
