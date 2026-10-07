"""Números de lote: se guardan como vienen y se comparan normalizados."""
import json

import pytest
from shapely.geometry import box

from pipeline.plano import numeros, regresion
from pipeline.plano.digitalizar import leer_entradas


@pytest.mark.parametrize("a, b", [("8-01", "8-1"), ("LOTE 8-01", "8-01"), ("012", "12"), (12, "12"),
                                  ("10-6", "6"), ("8-01", "1")])
def test_mismo_lote(a, b):
    assert numeros.mismo_lote(a, b) and numeros.mismo_lote(b, a)


@pytest.mark.parametrize("a, b", [("8-01", "8-11"), ("8-01", "9-01"), ("12", "21"), ("10-6", "16")])
def test_distinto_lote(a, b):
    assert not numeros.mismo_lote(a, b)


def test_clave_y_repetidos():
    assert numeros.clave("8-01") == numeros.clave("LOTE 8-1") == "8-1"
    assert numeros.clave("A-3?") == "A-3?"                     # lo que no se reconoce, tal cual
    # "LOTE12" pegado: la E de LOTE no es letra de sector (como `claveLote` en la consola).
    assert numeros.clave("LOTE12") == numeros.clave("lote 012") == "12"
    assert numeros.clave("A03") == "A3"
    assert numeros.repetidos(["8-01", "8-1", "8-02", "3", "03"]) == ["03", "3", "8-01", "8-1"]
    assert numeros.repetidos(["8-01", "8-02"]) == []


def test_buscar_prefiere_la_clave_igual():
    assert numeros.buscar({"1": 5000.0, "8-01": 4900.0}, "8-1") == 4900.0
    assert numeros.buscar({"1": 5000.0}, "8-01") == 5000.0       # el cuadro sin sector
    assert numeros.buscar({"8-01": 1.0, "9-01": 2.0}, "1") is None   # ambiguo
    assert numeros.buscar({}, "1") is None


def test_semillas_repetidas_normalizadas_fallan(tmp_path):
    (tmp_path / "plano.pdf").write_bytes(b"%PDF-1.4")
    entradas = dict(pdf="plano.pdf", pagina=1, rotacion=0, semillas=[dict(numero="8-01", x=1, y=1),
                                                                      dict(numero="8-1", x=5, y=5)])
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    with pytest.raises(ValueError, match="repetidos en las semillas: 8-01, 8-1"):
        leer_entradas(tmp_path)
    entradas["semillas"][1]["numero"] = "8-02"
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    assert [s["numero"] for s in leer_entradas(tmp_path)["semillas"]] == ["8-01", "8-02"]    # tal cual


def test_numeracion_de_la_regresion_compara_normalizado():
    # Hidango: la verdad dice "6" y el lector lee "LOTE 10-6"; Rapel: "8-01" contra "8-1".
    digitalizado = dict(lotes=[dict(numero="10-6", poligono=list(box(0, 0, 10, 10).exterior.coords)),
                               dict(numero="8-1", poligono=list(box(10, 0, 20, 10).exterior.coords)),
                               dict(numero="7", poligono=list(box(20, 0, 30, 10).exterior.coords))])
    verdad = [dict(numero="6", x=5, y=5), dict(numero="8-01", x=15, y=5), dict(numero="9", x=25, y=5)]
    u = regresion.numeracion(digitalizado, verdad)
    assert (u["correctos"], u["errados"], u["lotes_numero_ajeno"]) == (2, 1, 1)


RAPEL_LEIDOS = ["8-01", "8-02", "8-04", "8-06", "8-07", "8-08", "8-09", "8-10", "8-12", "8-13", "8-14", "8-15"]


def test_huecos_de_una_serie_con_ceros_como_en_el_plano():
    assert numeros.huecos(RAPEL_LEIDOS) == ["8-03", "8-05", "8-11"]
    assert numeros.huecos(["1", "2", "4", "7"]) == ["3", "5", "6"]
    assert numeros.huecos(["01", "02", "05"]) == ["03", "04"]
    assert numeros.huecos(["1", "2", "3"]) == [] and numeros.huecos([]) == []


def test_huecos_por_sector_y_letra():
    # Cada sector es su propia serie: el 9-01 no tapa el 8-01, ni el 10-6 al 9-6.
    assert numeros.huecos(["8-01", "8-03", "9-1", "9-3", "10-6", "10-8"]) == ["10-7", "8-02", "9-2"]
    assert numeros.huecos(["A01", "A03", "B1", "B3"]) == ["A02", "B2"]
    # Lo que no es número no cuenta; "8-1" y "8-01" son el mismo.
    assert numeros.huecos(["8-01", "8-1", "8-03", "??"]) == ["8-02"]


def test_un_salto_largo_no_es_un_hueco():
    # Una cota leída como rótulo, u otra etapa: no se piden 200 números.
    assert numeros.huecos(["1", "2", "4", "250"]) == ["3"]
    assert numeros.huecos(["1", "2"] + [str(n) for n in range(3 + numeros.SALTO_MAX + 1, 20)]) == []


def test_un_hueco_se_dice_solo_junto_a_un_lote_sin_numero():
    # Con `junto` (los lotes que tocan una cara sin número del tamaño de un lote), un
    # hueco se dice si el anterior o el siguiente es uno de ellos (Curicó: los lotes que
    # esa lámina no dibuja no se avisan).
    assert numeros.huecos(RAPEL_LEIDOS, junto=["8-2", "8-12"]) == ["8-03", "8-11"]
    assert numeros.huecos(RAPEL_LEIDOS, junto=[]) == []
    assert numeros.huecos(["10", "14", "88", "89"], junto=["88"]) == []
    # Los del cuadro van igual.
    assert numeros.huecos(RAPEL_LEIDOS, [f"8-{n:02d}" for n in range(1, 17)], junto=[]) \
        == ["8-03", "8-05", "8-11", "8-16"]


def test_esperados_del_cuadro_sin_el_resto_de_la_propiedad():
    """En Caminos de Rapel el cuadro trae "8 o resto de la propiedad" (760.000 m²) junto a
    8-01…8-16: es el predio que queda, no un lote del dibujo."""
    cuadro = {f"8-{n:02d}": 5000.0 for n in range(1, 17)} | {"8": 760000.0}
    assert numeros.esperados(cuadro) == [f"8-{n:02d}" for n in range(1, 17)]
    # Sin sectores, un "8" es un lote más.
    assert numeros.esperados({"1": 5000.0, "8": 5000.0}) == ["1", "8"]
    assert numeros.esperados({}) == []
    # Con el resto fuera, falta el 8-16 (nunca leído) y el 8-08, no un "8-08" por el resto.
    leidos = [f"8-{n:02d}" for n in range(1, 16) if n != 8]
    assert numeros.huecos(leidos, numeros.esperados(cuadro), junto=[]) == ["8-08", "8-16"]
    sin_el_8 = [n for n in leidos if n != "8-07"]
    assert numeros.huecos(sin_el_8 + ["8-08"], numeros.esperados(cuadro), junto=[]) == ["8-07", "8-16"]


def test_el_resto_de_la_propiedad_en_el_cuadro():
    cuadro = {"8-01": 5000.0, "8-02": 5000.0, "8": 760000.0}
    assert numeros.resto(cuadro) == "8"
    assert numeros.resto({"8-01": 5000.0, "8-02": 5000.0}) is None
    assert numeros.resto({"1": 5000.0, "8": 5000.0}) is None             # sin sectores, el 8 es un lote
    # La fila que dice "resto" sin número.
    assert numeros.resto({"1": 5000.0, "2": 5000.0, "Resto": 90000.0}) == "Resto"
    assert numeros.esperados({"1": 5000.0, "Resto": 90000.0}) == ["1"]
    assert numeros.es_resto("Resto") and numeros.es_resto("RESTO DE LA PROPIEDAD")
    assert not numeros.es_resto("8") and not numeros.es_resto("8-08")


def test_el_resto_llamado_resto_tiene_el_area_de_la_fila_del_resto():
    from pipeline.plano.digitalizar import _area_oficial
    cuadro = {"8-01": 5000.0, "8": 760000.0}
    assert _area_oficial(cuadro, "Resto") == 760000.0
    assert _area_oficial(cuadro, "8") == 760000.0 and _area_oficial(cuadro, "8-1") == 5000.0
    assert _area_oficial({"8-01": 5000.0}, "Resto") is None


def test_el_resto_se_compara_solo_igual():
    """"8" y "8-08" son el mismo lote para quien marca solo el número dentro del sector,
    pero no si el 8 es el resto de la propiedad."""
    assert numeros.mismo_lote("8", "8-08")
    assert not numeros.mismo_lote("8", "8-08", restos=["8"])
    assert numeros.mismo_lote("8", "8", restos=["8"])
    assert numeros.mismo_lote("6", "10-6", restos=["8"])                 # lo demás, como siempre


def test_huecos_con_el_cuadro_de_superficies():
    # El cuadro trae el último (el 16), que la serie sola no ve; "16" sin sector va con la serie.
    cuadro = [str(n) for n in range(1, 17)]
    assert numeros.huecos(RAPEL_LEIDOS, cuadro) == ["8-03", "8-05", "8-11", "8-16"]
    assert numeros.huecos(RAPEL_LEIDOS, [f"8-{n:02d}" for n in range(1, 17)])[-1] == "8-16"
    # Un cuadro que no calza con lo leído (otro cuadro: vértices, roles) no se usa.
    assert numeros.huecos(RAPEL_LEIDOS, ["101", "102", "103"]) == ["8-03", "8-05", "8-11"]
