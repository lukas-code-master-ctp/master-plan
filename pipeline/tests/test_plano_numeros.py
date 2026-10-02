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
