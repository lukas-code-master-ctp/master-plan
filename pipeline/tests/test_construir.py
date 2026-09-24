import pytest

from pipeline.construir import _revisar_ids_de_vista
from pipeline.panoramas import buscar_panoramas, leer_panorama
from pipeline.tests.test_panoramas import escribir_panorama


def test_acepta_vistas_con_ids_distintos(tmp_path):
    escribir_panorama(tmp_path / "a.JPG", lon=-72.0025, relativa=118.0,
                      momento="2026-03-05T19:05:00-03:00")
    escribir_panorama(tmp_path / "b.JPG", lon=-71.9970, relativa=118.0,
                      momento="2026-03-05T19:07:00-03:00")

    _revisar_ids_de_vista(buscar_panoramas(tmp_path))   # no levanta


def test_corta_si_dos_panoramicas_comparten_id(tmp_path):
    """El mismo archivo duplicado en dos carpetas: una vista pisaría a la otra."""
    original = leer_panorama(escribir_panorama(tmp_path / "POSICION 01" / "foto.JPG"))
    copia = leer_panorama(escribir_panorama(tmp_path / "respaldo" / "foto.JPG"))
    copia.posicion = original.posicion

    with pytest.raises(ValueError, match="comparten el id de vista"):
        _revisar_ids_de_vista([original, copia])


def test_el_aviso_nombra_los_archivos_en_conflicto(tmp_path):
    uno = leer_panorama(escribir_panorama(tmp_path / "POSICION 01" / "uno.JPG"))
    otro = leer_panorama(escribir_panorama(tmp_path / "POSICION 01" / "otro.JPG"))

    with pytest.raises(ValueError) as error:
        _revisar_ids_de_vista([uno, otro])

    assert "uno.JPG" in str(error.value) and "otro.JPG" in str(error.value)
    assert uno.id in str(error.value)


# --- orden, número y rótulo de cada parcela ------------------------------------

from pipeline.construir import _armar_parcelas, _orden_lote
from pipeline.kmz import ParcelaGeometrica

ANILLO = [(-72.0, -35.0), (-71.999, -35.0), (-71.999, -34.999), (-72.0, -34.999)]


@pytest.mark.parametrize("identificador,esperado", [
    ("42", (0, 42)),
    ("A214", (0, 214)),
    ("2-7", (2, 7)),
    ("2-15", (2, 15)),
])
def test_ordena_por_etapa_y_despues_por_numero(identificador, esperado):
    assert _orden_lote(identificador) == esperado


def test_las_etapas_quedan_juntas_al_ordenar():
    ids = sorted(["2-1", "1-15", "1-7", "2-7"], key=_orden_lote)

    assert ids == ["1-7", "1-15", "2-1", "2-7"]


def test_cada_parcela_lleva_numero_etapa_y_rotulo():
    geometrias = {
        "2-7": ParcelaGeometrica(id="2-7", anillo=ANILLO, etapa=2),
        "A214": ParcelaGeometrica(id="A214", anillo=ANILLO),
        "7-1": ParcelaGeometrica(id="7-1", anillo=ANILLO),   # sector-lote, sin etapas
    }

    parcelas = {p["id"]: p for p in _armar_parcelas({}, geometrias, {})}

    assert (parcelas["2-7"]["numero"], parcelas["2-7"]["etapa"], parcelas["2-7"]["rotulo"]) == (7, 2, "7")
    assert (parcelas["A214"]["numero"], parcelas["A214"]["etapa"], parcelas["A214"]["rotulo"]) == (214, None, "214")
    assert (parcelas["7-1"]["numero"], parcelas["7-1"]["etapa"], parcelas["7-1"]["rotulo"]) == (1, None, "7-1")


def test_si_el_loteo_no_esta_en_el_crm_avisa_y_sigue(tmp_path, capsys):
    """Que el loteo no figure en el export no puede tumbar la construcción: se
    avisa y las parcelas salen como no disponibles, que es lo honesto."""
    from pipeline.construir import Avisos, _leer_fichas
    from pipeline import config

    csv = tmp_path / "crm.csv"
    csv.write_text("﻿Parcela,Parcelación,ESTADO_CRM_PARCELA\n1,OTRO LOTEO,DISPONIBLE\n",
                   encoding="utf-8")
    fuentes = config.Fuentes(kmz=tmp_path / "x.kmz", panoramas=tmp_path, crm=csv)
    avisos = Avisos([])

    fichas = _leer_fichas(fuentes, config.Proyecto(nombre="Las Araucarias"), avisos)

    assert fichas == {}
    assert any("LAS ARAUCARIAS" in linea for linea in avisos.lineas)
