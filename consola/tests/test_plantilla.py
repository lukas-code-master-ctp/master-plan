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

    # El ejemplo muestra cómo se escribe una segunda etapa.
    assert set(fichas) == {"1-1", "1-2", "2-1"}
    assert fichas["1-1"].estado == "disponible"
    assert fichas["2-1"].moneda == "UF"


def test_la_plantilla_del_loteo_trae_sus_parcelas_con_lo_que_muestran_hoy(tmp_path):
    parcelas = [
        {"id": "1-7", "numero": 7, "etapa": 1, "estado": "disponible", "precio": 9_990_000.0,
         "moneda": "CLP", "superficie_m2": 5002, "link_pago": "https://pago.cl/7", "en_planilla": True},
        {"id": "2-7", "numero": 7, "etapa": 2, "estado": "vendido", "precio": 395.5, "moneda": "UF",
         "superficie_m2": 5100, "link_pago": None, "en_planilla": True},
        # Fuera de la planilla: la superficie es la del dibujo, no se prellena.
        {"id": "2-8", "numero": 8, "etapa": 2, "estado": "no_disponible", "precio": None,
         "moneda": "CLP", "superficie_m2": 4066, "link_pago": None, "en_planilla": False},
    ]

    contenido = plantilla(parcelas, "Praderas de Cauquenes")
    fichas = leer_planilla(guardar(tmp_path, contenido))

    assert set(fichas) == {"1-7", "2-7", "2-8"}
    assert fichas["1-7"].precio == 9_990_000
    assert fichas["1-7"].link_pago == "https://pago.cl/7"
    assert (fichas["2-7"].estado, fichas["2-7"].precio, fichas["2-7"].moneda) == ("vendido", 395.5, "UF")
    assert fichas["2-8"].superficie_m2 is None
    # Como en Cierra: el proyecto dice la etapa y la parcela es solo el número.
    hoja = openpyxl.load_workbook(BytesIO(contenido)).active
    assert [c.value for c in hoja[3]][:2] == ["PRADERAS DE CAUQUENES ET2", "7"]
    assert [c.value for c in hoja[2]][:2] == ["PRADERAS DE CAUQUENES", "7"]


def test_la_columna_parcela_es_texto_para_que_excel_no_la_vuelva_fecha():
    hoja = openpyxl.load_workbook(BytesIO(plantilla([{"id": "2-7", "estado": "disponible"}]))).active

    assert [c.value for c in hoja[1]] == list(COLUMNAS)
    assert hoja["B2"].value == "2-7"
    assert hoja["B2"].number_format == "@"
    assert hoja["B500"].number_format == "@"
    listas = {str(v.sqref): v.formula1 for v in hoja.data_validations.dataValidation}
    assert "Disponible" in listas["C2:C2000"]
    assert listas["E2:E2000"] == '"CLP,UF"'


def test_lo_que_se_pega_desde_cierra_calza_con_el_plano(tmp_path):
    """El caso de Praderas: 4 etapas que numeran desde 1, estados escritos como en
    Cierra. Con la columna Proyecto, cada parcela cae en su etapa."""
    libro = openpyxl.load_workbook(BytesIO(plantilla()))
    hoja = libro.active
    hoja.delete_rows(2, 3)
    for proyecto, parcela, estado in (("PRADERAS DE CAUQUENES", "7", "DISPONIBLE"),
                                      ("PRADERAS DE CAUQUENES ET2", "7", "EN_PROCESO"),
                                      ("PRADERAS DE CAUQUENES ET3", "7", "INSCRITA"),
                                      ("PRADERAS DE CAUQUENES ET4", "7", "NO_DISPONIBLE")):
        hoja.append((proyecto, parcela, estado, 8_990_000, "CLP"))
    ruta = tmp_path / "inventario.xlsx"
    libro.save(ruta)

    fichas = leer_planilla(ruta)

    assert {i: f.estado for i, f in fichas.items()} == {
        "1-7": "disponible", "2-7": "reservado", "3-7": "vendido", "4-7": "no_disponible"}
