"""La planilla puede salir directo del export del CRM (ctp_parcelas_latest.csv)."""
import pytest

from pipeline.crm import leer_crm

ENCABEZADO = ("ID,Parcela,SUPERFICIE_CRM,SERVIDUMBRE,PROVEEDOR_PREDIO,Parcelación,"
              "VALOR_CONTADO,RESERVA_CONTADO,VALOR_CREDITO,RESERVA_CREDITO,ESTADO_CRM_PARCELA")


def csv_crm(tmp_path, filas):
    ruta = tmp_path / "ctp_parcelas_latest.csv"
    ruta.write_text("﻿" + "\n".join([ENCABEZADO, *filas]) + "\n", encoding="utf-8")
    return ruta


def test_arma_las_fichas_de_una_parcelacion_con_sus_etapas(tmp_path):
    ruta = csv_crm(tmp_path, [
        "PRADERAS DE CAUQUENES7,7,5002,940.53,X,PRADERAS DE CAUQUENES,8990000,500000,0,0,DISPONIBLE",
        "PRADERAS DE CAUQUENES ET27,7,5436,0,X,PRADERAS DE CAUQUENES ET2,8990000,500000,0,0,ESCRITURA",
        "PRADERAS DE CAUQUENES ET31,1,5025,0,X,PRADERAS DE CAUQUENES ET3,0,0,0,0,AGENDA",
        "VIÑAS DE CAUQUENES1,1,5000,0,X,VIÑAS DE CAUQUENES,8990000,0,0,0,DISPONIBLE",
    ])

    fichas = leer_crm(ruta, "PRADERAS DE CAUQUENES")

    assert set(fichas) == {"1-7", "2-7", "3-1"}
    assert fichas["1-7"].estado == "disponible"
    assert fichas["2-7"].estado == "vendido"
    assert fichas["3-1"].estado == "reservado"
    assert fichas["1-7"].superficie_m2 == 5002
    assert fichas["1-7"].precio == 8990000
    assert fichas["1-7"].moneda == "CLP"


def test_la_servidumbre_del_crm_es_superficie_no_ancho(tmp_path):
    ruta = csv_crm(tmp_path, [
        "P1,1,5002,940.53,X,PRADERAS,8990000,0,0,0,DISPONIBLE",
    ])

    ficha = leer_crm(ruta, "PRADERAS")["1"]

    assert ficha.servidumbre_m2 == pytest.approx(940.53)
    assert ficha.servidumbre_m is None


def test_un_valor_contado_en_cero_es_precio_a_consultar(tmp_path):
    ruta = csv_crm(tmp_path, ["P1,1,5002,0,X,PRADERAS,0,0,0,0,DISPONIBLE"])

    assert leer_crm(ruta, "PRADERAS")["1"].precio is None


def test_avisa_si_la_parcelacion_no_esta_en_el_csv(tmp_path):
    ruta = csv_crm(tmp_path, ["P1,1,5002,0,X,OTRO LOTEO,0,0,0,0,DISPONIBLE"])

    with pytest.raises(ValueError, match="PRADERAS"):
        leer_crm(ruta, "PRADERAS")


def test_un_loteo_que_no_esta_en_el_csv_avisa_con_su_nombre(tmp_path):
    """El mensaje tiene que decir qué buscó: casi siempre es el nombre mal escrito."""
    ruta = csv_crm(tmp_path, ["P1,1,5002,0,X,OTRO LOTEO,0,0,0,0,DISPONIBLE"])

    with pytest.raises(ValueError, match="LAS ARAUCARIAS"):
        leer_crm(ruta, "LAS ARAUCARIAS")
