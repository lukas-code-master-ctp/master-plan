"""Unir dos partes de un mismo lote en Numerar: ver docs/specs/2026-10-20-kmz-unir-partes.md."""
import json

import pytest
from shapely.geometry import Point, Polygon, box

from pipeline.plano.digitalizar import digitalizar, leer_entradas, unir_partes
from pipeline.tests.plano_sintetico import iou
from pipeline.tests.test_plano_cli import _carpeta

PPMM = 10.0          # 1 mm de papel = 10 px: el borde mínimo es de 10 px


def _unir(lotes, sin_numero, uniones, origen=None, de_lote=None):
    origen = origen or {n: "usuario" for n in lotes}
    de_lote = de_lote if de_lote is not None else [True] * len(sin_numero)
    return unir_partes(lotes, sin_numero, de_lote, origen,
                       [dict(numero=n, x=float(x), y=float(y)) for n, x, y in uniones], PPMM)


def test_une_la_cara_sin_numero_que_comparte_un_borde():
    """El Lote 17 en "L" partido por una cota: la pata sin número se suma al 17, sin la
    línea del medio."""
    lotes = {"17": box(0, 0, 100, 100), "18": box(100, 0, 200, 100)}
    pata = box(0, 100, 100, 300)
    otra = box(300, 300, 400, 400)

    nuevos, sin_numero, de_lote, partes, descartadas = _unir(lotes, [pata, otra], [("17", 50, 200)])

    assert nuevos["17"].geom_type == "Polygon"
    assert nuevos["17"].equals(box(0, 0, 100, 300))
    assert nuevos["18"] is lotes["18"]
    assert sin_numero == [otra] and de_lote == [True]
    assert partes == {"17": [[50.0, 200.0]]} and descartadas == []
    # No toca lo que recibe.
    assert lotes["17"].equals(box(0, 0, 100, 100))


@pytest.mark.parametrize("cara", [
    box(100, 100, 200, 200),          # solo un vértice en común
    box(0, 105, 100, 300),            # a medio mm: no se tocan
    box(98, 100, 200, 200),           # 0,2 mm de borde: menos del mínimo
])
def test_no_une_si_no_comparten_un_borde(cara):
    lotes = {"17": box(0, 0, 100, 100)}
    x, y = cara.representative_point().coords[0]

    nuevos, sin_numero, _, partes, descartadas = _unir(lotes, [cara], [("17", x, y)])

    assert nuevos["17"].equals(lotes["17"]) and sin_numero == [cara]
    assert partes == {} and descartadas == ["17"]


def test_absorbe_un_lote_del_lector_y_no_uno_de_la_loteadora():
    """El lector leyó "18" en la mitad del 17: unirla se lleva el 18. Un número que
    marcó ella manda: su lote no se absorbe."""
    lotes = {"17": box(0, 0, 100, 100), "18": box(0, 100, 100, 200), "19": box(100, 0, 200, 100)}
    origen = {"17": "usuario", "18": "lector", "19": "usuario"}

    nuevos, _, _, partes, descartadas = _unir(lotes, [], [("17", 50, 150), ("17", 150, 50)], origen)

    assert set(nuevos) == {"17", "19"}
    assert nuevos["17"].equals(box(0, 0, 100, 200)) and nuevos["19"].equals(lotes["19"])
    assert partes == {"17": [[50.0, 150.0]]} and descartadas == ["17"]


def test_dos_partes_encadenadas_al_mismo_lote():
    """La segunda parte solo toca a la primera: entra porque se compara con el lote
    como va quedando."""
    lotes = {"17": box(0, 0, 100, 100)}
    caras = [box(0, 100, 100, 200), box(0, 200, 100, 300)]

    nuevos, sin_numero, de_lote, partes, descartadas = _unir(lotes, caras, [("17", 50, 150), ("17", 50, 250)])

    assert nuevos["17"].equals(box(0, 0, 100, 300))
    assert sin_numero == [] and de_lote == []
    assert partes == {"17": [[50.0, 150.0], [50.0, 250.0]]} and descartadas == []


def test_en_otro_orden_la_parte_lejana_se_descarta():
    lotes = {"17": box(0, 0, 100, 100)}
    caras = [box(0, 100, 100, 200), box(0, 200, 100, 300)]

    nuevos, sin_numero, _, partes, descartadas = _unir(lotes, caras, [("17", 50, 250), ("17", 50, 150)])

    assert nuevos["17"].equals(box(0, 0, 100, 200)) and sin_numero == [caras[1]]
    assert partes == {"17": [[50.0, 150.0]]} and descartadas == ["17"]


def test_cierra_la_rendija_de_coma_flotante():
    """Dos caras de la misma red pueden quedar a una fracción de px al pasarlas a la
    página: igual salen como un polígono."""
    lotes = {"17": box(0, 0, 100, 100)}
    cara = box(0, 100.3, 100, 200)

    nuevos, _, _, partes, _ = _unir(lotes, [cara], [("17", 50, 150)])

    assert nuevos["17"].geom_type == "Polygon"
    assert nuevos["17"].area == pytest.approx(100 * 200, rel=0.01)
    assert partes == {"17": [[50.0, 150.0]]}


@pytest.mark.parametrize("union", [
    ("20", 50, 150),                  # el lote no existe
    ("17", 500, 500),                 # el punto no cae en ninguna parte
])
def test_descarta_si_el_lote_no_existe_o_el_punto_no_cae_en_nada(union):
    lotes = {"17": box(0, 0, 100, 100)}
    cara = box(0, 100, 100, 200)

    nuevos, sin_numero, _, partes, descartadas = _unir(lotes, [cara], [union, union])

    assert nuevos["17"].equals(lotes["17"]) and sin_numero == [cara]
    assert partes == {} and descartadas == [union[0]]     # una vez por número


def test_el_numero_se_compara_normalizado_y_un_punto_ya_dentro_no_hace_nada():
    lotes = {"8-01": box(0, 0, 100, 100)}
    cara = box(0, 100, 100, 200)

    nuevos, _, _, partes, descartadas = _unir(lotes, [cara], [("8-1", 50, 50), ("8-1", 50, 150)])

    assert nuevos["8-01"].equals(box(0, 0, 100, 200))
    assert partes == {"8-01": [[50.0, 150.0]]} and descartadas == []


def _escribir(tmp_path, **cambios):
    entradas = dict(pdf="plano.pdf", semillas=[], anclas=[], **cambios)
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")


def test_leer_entradas_normaliza_las_uniones(tmp_path):
    _escribir(tmp_path)
    assert leer_entradas(tmp_path)["uniones"] == []
    _escribir(tmp_path, uniones=[dict(numero=17, x=5, y=6.5)])
    assert leer_entradas(tmp_path)["uniones"] == [dict(numero="17", x=5.0, y=6.5)]


@pytest.mark.parametrize("uniones, mensaje", [
    ({"numero": "17"}, "«uniones» es una lista"),
    ([dict(x=1, y=2)], "cada unión lleva «numero»"),
    ([dict(numero="", x=1, y=2)], "cada unión lleva «numero»"),
    ([dict(numero="17", x="a", y=2)], "unión al lote 17: x, y"),
    ([[1, 2]], "cada unión lleva «numero»"),
])
def test_leer_entradas_rechaza_uniones_malas(tmp_path, uniones, mensaje):
    _escribir(tmp_path, uniones=uniones)
    with pytest.raises(ValueError, match=mensaje):
        leer_entradas(tmp_path)


def test_digitalizar_une_la_parte_y_lo_dice_en_el_digitalizado(tmp_path):
    """De punta a punta: un lote sin semilla se suma a su vecino y sale como un solo
    lote, con sus partes; uno que no toca queda en `uniones_descartadas`."""
    plano = _carpeta(tmp_path)
    entradas = json.loads((tmp_path / "entradas.json").read_text(encoding="utf-8"))
    celdas = plano.celdas
    # Un par de lotes vecinos (comparten un lado) y uno que no toca al primero.
    a, b = next((a, b) for a in celdas for b in celdas
                if a != b and celdas[a].intersection(celdas[b]).length > 10)
    lejos = next(n for n in celdas if celdas[n].distance(celdas[a].union(celdas[b])) > 20)
    pb, pl = celdas[b].representative_point(), celdas[lejos].representative_point()
    entradas["semillas"] = [s for s in entradas["semillas"] if s["numero"] not in (b, lejos)]
    entradas["lector"] = False
    entradas["uniones"] = [dict(numero=a, x=pb.x, y=pb.y), dict(numero=a, x=pl.x, y=pl.y)]
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    avance = []

    datos = digitalizar(tmp_path, avance=avance.append)

    lote = next(l for l in datos["lotes"] if l["numero"] == a)
    assert iou(Polygon(lote["poligono"], lote["huecos"]), celdas[a].union(celdas[b])) > 0.95
    assert lote["partes"] == [[pb.x, pb.y]]
    assert all(l["partes"] == [] for l in datos["lotes"] if l["numero"] != a)
    assert not any(Polygon(c["poligono"]).contains(Point(pb.x, pb.y)) for c in datos["sin_numero"])
    assert any(Polygon(c["poligono"]).contains(Point(pl.x, pl.y)) for c in datos["sin_numero"])
    assert datos["uniones_descartadas"] == [a]
    assert any(linea.startswith("Partes unidas: 1 al lote") for linea in avance)


def test_sin_uniones_el_digitalizado_no_cambia_de_forma(tmp_path):
    _carpeta(tmp_path)
    entradas = json.loads((tmp_path / "entradas.json").read_text(encoding="utf-8"))
    entradas["lector"] = False
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    avance = []

    datos = digitalizar(tmp_path, avance=avance.append)

    assert datos["uniones_descartadas"] == []
    assert all(l["partes"] == [] for l in datos["lotes"])
    assert not any(linea.startswith("Partes unidas") for linea in avance)
