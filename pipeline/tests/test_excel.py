import openpyxl
import pytest

from pipeline.excel import leer_excel, normalizar_estado


def planilla(tmp_path, filas, nombre="datos.xlsx"):
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "disponibles"
    for fila in filas:
        hoja.append(fila)
    ruta = tmp_path / nombre
    libro.save(ruta)
    return ruta


ENCABEZADO = ["Parcela", "Parcelación", "Estado", "Servidumbre", "Superficie", "Link de pago"]


def test_lee_las_columnas_del_formato_actual(tmp_path):
    ruta = planilla(tmp_path, [
        ENCABEZADO,
        ["Lote A 420", "HACIENDA VICHUQUEN ETAPA 1", "DISPONIBLE", "167", "5000", "https://pago/1"],
        ["A214", "HACIENDA VICHUQUEN ETAPA 1", "DISPONIBLE", 174, 5000, "https://pago/1"],
    ])

    fichas = leer_excel(ruta)

    assert set(fichas) == {"A420", "A214"}
    assert fichas["A420"].superficie_m2 == 5000
    assert fichas["A420"].servidumbre_m == 167
    assert fichas["A420"].estado == "disponible"
    assert fichas["A420"].link_pago == "https://pago/1"


def test_reconoce_columnas_opcionales_de_precio_y_moneda(tmp_path):
    ruta = planilla(tmp_path, [
        ENCABEZADO + ["Precio", "Moneda"],
        ["A1", "ETAPA 1", "DISPONIBLE", 10, 5000, "https://pago/1", "1.250", "UF"],
    ])

    ficha = leer_excel(ruta)["A1"]

    assert ficha.precio == 1250
    assert ficha.moneda == "UF"


def test_sin_columna_de_precio_el_precio_queda_vacio(tmp_path):
    ruta = planilla(tmp_path, [ENCABEZADO, ["A1", "E1", "DISPONIBLE", 10, 5000, ""]])

    assert leer_excel(ruta)["A1"].precio is None


def test_entiende_los_encabezados_sin_tildes_y_en_cualquier_caja(tmp_path):
    ruta = planilla(tmp_path, [
        ["PARCELA", "parcelacion", "  Estado  ", "SUPERFICIE M2"],
        ["A9", "E1", "vendido", 5200],
    ])

    ficha = leer_excel(ruta)["A9"]

    assert ficha.estado == "vendido"
    assert ficha.superficie_m2 == 5200


def test_interpreta_numeros_en_formato_chileno(tmp_path):
    ruta = planilla(tmp_path, [
        ENCABEZADO + ["Precio"],
        ["A1", "E1", "DISPONIBLE", 10, "13.124", "", "45.900.000"],
    ])

    ficha = leer_excel(ruta)["A1"]

    assert ficha.superficie_m2 == 13124
    assert ficha.precio == 45900000


def test_salta_las_filas_sin_parcela(tmp_path):
    ruta = planilla(tmp_path, [
        ENCABEZADO,
        [None, "E1", "DISPONIBLE", 10, 5000, ""],
        ["", "E1", "DISPONIBLE", 10, 5000, ""],
        ["A3", "E1", "DISPONIBLE", 10, 5000, ""],
    ])

    assert set(leer_excel(ruta)) == {"A3"}


def test_una_planilla_sin_columna_de_parcela_avisa_claramente(tmp_path):
    ruta = planilla(tmp_path, [["Cosa", "Otra"], ["x", "y"]])

    with pytest.raises(ValueError, match="columna de parcela"):
        leer_excel(ruta)


def test_una_planilla_vacia_devuelve_nada(tmp_path):
    assert leer_excel(planilla(tmp_path, [])) == {}


@pytest.mark.parametrize("entrada,esperado", [
    ("DISPONIBLE", "disponible"),
    ("Disponible", "disponible"),
    ("reservado", "reservado"),
    ("RESERVA", "reservado"),
    ("Vendida", "vendido"),
    ("No disponible", "no_disponible"),
    ("NO EN VENTA", "no_en_venta"),
    ("cualquier cosa", "no_disponible"),
    (None, "no_disponible"),
])
def test_normaliza_los_estados(entrada, esperado):
    assert normalizar_estado(entrada) == esperado


# --- etapas y planillas en CSV ------------------------------------------------

from pipeline.excel import leer_planilla


def test_califica_los_ids_por_etapa_cuando_la_planilla_trae_varias(tmp_path):
    """Un loteo por etapas numera cada etapa desde 1. La parcelación lleva el sufijo."""
    ruta = planilla(tmp_path, [
        ENCABEZADO,
        ["7", "PRADERAS DE CAUQUENES", "DISPONIBLE", 3, 5002, ""],
        ["7", "PRADERAS DE CAUQUENES ET2", "VENDIDO", 3, 5436, ""],
        ["1", "PRADERAS DE CAUQUENES ETAPA 3", "DISPONIBLE", 3, 5025, ""],
    ])

    fichas = leer_excel(ruta)

    assert set(fichas) == {"1-7", "2-7", "3-1"}
    assert fichas["2-7"].etapa == 2 and fichas["2-7"].numero == "7"
    assert fichas["1-7"].superficie_m2 == 5002


def test_con_una_sola_etapa_los_ids_no_cambian(tmp_path):
    ruta = planilla(tmp_path, [
        ENCABEZADO,
        ["A1", "HACIENDA VICHUQUEN ETAPA 1", "DISPONIBLE", 10, 5000, ""],
        ["A2", "HACIENDA VICHUQUEN ETAPA 1", "DISPONIBLE", 10, 5000, ""],
    ])

    fichas = leer_excel(ruta)

    assert set(fichas) == {"A1", "A2"}
    assert fichas["A1"].etapa == 1


def test_filtra_por_parcelacion_incluyendo_sus_etapas(tmp_path):
    ruta = planilla(tmp_path, [
        ENCABEZADO,
        ["1", "PRADERAS DE CAUQUENES", "DISPONIBLE", 3, 5002, ""],
        ["1", "PRADERAS DE CAUQUENES ET2", "DISPONIBLE", 3, 5002, ""],
        ["1", "VIÑAS DE CAUQUENES", "DISPONIBLE", 3, 5002, ""],
        ["1", "PRADERAS DE CAUQUENES NORTE", "DISPONIBLE", 3, 5002, ""],
    ])

    fichas = leer_planilla(ruta, parcelacion="Praderas de Cauquenes")

    assert set(fichas) == {"1-1", "2-1"}


def test_lee_la_misma_planilla_en_csv(tmp_path):
    ruta = tmp_path / "parcelas.csv"
    ruta.write_text("﻿Parcela,Estado,Superficie,Precio\nA5,RESERVADO,5.170,45.900.000\n",
                    encoding="utf-8")

    fichas = leer_planilla(ruta)

    assert fichas["A5"].estado == "reservado"
    assert fichas["A5"].superficie_m2 == 5170
    assert fichas["A5"].precio == 45900000


def test_reconoce_la_servidumbre_en_metros_cuadrados(tmp_path):
    ruta = planilla(tmp_path, [["Parcela", "Servidumbre m2"], ["A1", "940.53"]])

    ficha = leer_excel(ruta)["A1"]

    assert ficha.servidumbre_m2 == pytest.approx(940.53)
    assert ficha.servidumbre_m is None


@pytest.mark.parametrize("entrada,esperado", [
    ("AGENDA", "reservado"),
    ("PRE-RESERVA", "reservado"),
    ("BORRADOR", "reservado"),
    ("ESCRITURA", "vendido"),
    ("ENTRADA CBR", "vendido"),
])
def test_normaliza_los_estados_del_crm(entrada, esperado):
    assert normalizar_estado(entrada) == esperado


def test_una_servidumbre_en_cero_es_dato_ausente(tmp_path):
    """El CRM guarda 0 cuando no tiene el dato; mostrar "0 m²" sería afirmar algo."""
    ruta = planilla(tmp_path, [["Parcela", "Servidumbre", "Servidumbre m2"], ["A1", 0, "0"]])

    ficha = leer_excel(ruta)["A1"]

    assert ficha.servidumbre_m is None and ficha.servidumbre_m2 is None
