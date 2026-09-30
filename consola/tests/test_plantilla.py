"""La plantilla del inventario se lee de vuelta tal cual con el pipeline."""
from io import BytesIO

import openpyxl

from consola.plantilla import COLUMNAS, plantilla
from pipeline.excel import leer_planilla


def guardar(tmp_path, contenido):
    ruta = tmp_path / "inventario.xlsx"
    ruta.write_bytes(contenido)
    return ruta


def test_la_plantilla_en_blanco_trae_las_columnas_y_se_lee(tmp_path):
    fichas = leer_planilla(guardar(tmp_path, plantilla()))

    assert set(fichas) == {"1", "2", "3"}
    assert fichas["1"].estado == "disponible"
    assert fichas["3"].moneda == "UF"


def test_la_plantilla_del_loteo_trae_sus_parcelas_con_lo_que_muestran_hoy(tmp_path):
    parcelas = [
        {"id": "1-7", "estado": "disponible", "precio": 9_990_000.0, "moneda": "CLP",
         "superficie_m2": 5002, "link_pago": "https://pago.cl/7", "en_planilla": True},
        {"id": "2-7", "estado": "vendido", "precio": 395.5, "moneda": "UF",
         "superficie_m2": 5100, "link_pago": None, "en_planilla": True},
        # Fuera de la planilla: la superficie es la del dibujo, no se prellena.
        {"id": "2-8", "estado": "no_disponible", "precio": None, "moneda": "CLP",
         "superficie_m2": 4066, "link_pago": None, "en_planilla": False},
    ]

    fichas = leer_planilla(guardar(tmp_path, plantilla(parcelas)))

    assert set(fichas) == {"1-7", "2-7", "2-8"}
    assert fichas["1-7"].precio == 9_990_000
    assert fichas["1-7"].link_pago == "https://pago.cl/7"
    assert (fichas["2-7"].estado, fichas["2-7"].precio, fichas["2-7"].moneda) == ("vendido", 395.5, "UF")
    assert fichas["2-8"].superficie_m2 is None


def test_la_columna_parcela_es_texto_para_que_excel_no_la_vuelva_fecha():
    hoja = openpyxl.load_workbook(BytesIO(plantilla([{"id": "2-7", "estado": "disponible"}]))).active

    assert [c.value for c in hoja[1]] == list(COLUMNAS)
    assert hoja["A2"].value == "2-7"
    assert hoja["A2"].number_format == "@"
    assert hoja["A500"].number_format == "@"
    listas = {str(v.sqref): v.formula1 for v in hoja.data_validations.dataValidation}
    assert "Disponible" in listas["B2:B2000"]
    assert listas["D2:D2000"] == '"CLP,UF"'
