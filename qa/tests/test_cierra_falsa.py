"""La Cierra falsa contra el cliente de verdad: si `consola.cierra` la entiende, la
consola levantada en este computador también."""
import csv
import urllib.error
import urllib.request

import pytest

from consola.cierra import (
    Cierra,
    CierraNoResponde,
    ClaveRechazada,
    ConexionDelLoteo,
    Eleccion,
    sincronizar,
)
from pipeline.excel import leer_planilla
from qa import cierra_falsa
from qa.cierra_falsa import CLAVE


@pytest.fixture(scope="module")
def url():
    servidor, direccion = cierra_falsa.servir(puerto=0)
    yield direccion
    servidor.shutdown()
    servidor.server_close()


def test_lista_los_dos_proyectos_con_totales_que_calzan(url):
    proyectos = Cierra(url).proyectos(CLAVE)

    assert [(p.id, p.nombre) for p in proyectos] == [(1, "Praderas Demo Etapa 1"),
                                                     (2, "Praderas Demo Etapa 2")]
    for proyecto in proyectos:
        suyas = [p for p in cierra_falsa.PARCELAS if p["proyecto_id"] == proyecto.id]
        assert proyecto.parcelas_total == len(suyas) == 6
        assert proyecto.parcelas_disponibles == sum(p["estado"] == "disponible" for p in suyas)


def test_trae_las_parcelas_de_ambas_etapas_en_los_cuatro_estados(url):
    parcelas = Cierra(url).parcelas(CLAVE, [1, 2])

    assert len(parcelas) == 12
    assert {(p["proyecto_id"], p["numero"]) for p in parcelas} == {
        (e, str(n)) for e in (1, 2) for n in range(1, 7)}
    assert {p["estado"] for p in parcelas} == {"disponible", "reservado", "vendido", "no_disponible"}
    assert {p["moneda"] for p in parcelas} == {"CLP", "UF"}
    assert [p["proyecto_id"] for p in Cierra(url).parcelas(CLAVE, [2])] == [2] * 6


@pytest.mark.parametrize("clave", ["otra-clave-que-no-es-0001", ""])
def test_una_clave_mala_es_clave_rechazada(url, clave):
    with pytest.raises(ClaveRechazada):
        Cierra(url).proyectos(clave)
    with pytest.raises(ClaveRechazada):
        Cierra(url).parcelas(clave, [1])


def test_un_proyecto_que_no_existe_es_cierra_no_responde(url):
    with pytest.raises(CierraNoResponde, match="no encontró"):
        Cierra(url).parcelas(CLAVE, [1, 99])


def test_una_ruta_que_no_existe_contesta_404(url):
    peticion = urllib.request.Request(f"{url}/integrations/otra", headers={"X-API-Key": CLAVE})
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(peticion, timeout=5)
    assert error.value.code == 404


def test_sincronizar_escribe_el_inventario_con_una_parcelacion_por_etapa(url, tmp_path):
    conexion = ConexionDelLoteo(elecciones=(Eleccion(1, "Praderas Demo Etapa 1", 1),
                                            Eleccion(2, "Praderas Demo Etapa 2", 2)),
                                sincronizado_en=None)

    assert sincronizar(Cierra(url), CLAVE, conexion, tmp_path) == 12

    with open(tmp_path / "inventario.csv", encoding="utf-8", newline="") as archivo:
        filas = list(csv.DictReader(archivo))
    assert len(filas) == 12
    assert {f["Parcelación"] for f in filas} == {"CIERRA ET1", "CIERRA ET2"}
    # Los lotes quedan como los del KMZ sintético: "1-1" a "1-6" y "2-1" a "2-6".
    fichas = leer_planilla(tmp_path / "inventario.csv")
    assert set(fichas) == {f"{e}-{n}" for e in (1, 2) for n in range(1, 7)}
    assert {f.estado for f in fichas.values()} == {"disponible", "reservado", "vendido",
                                                    "no_disponible"}
