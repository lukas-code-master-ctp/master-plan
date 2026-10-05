"""La siembra de QA: se niega a tocar algo que no sea de QA, deja las cuentas
entrando con la clave común y respeta el aislamiento entre loteadoras.

Siembra sin construir: construir de verdad es lo que prueba `python -m qa.sembrar`
a mano, y tarda lo que tarda el pipeline."""
import pytest

from consola.acceso import Acceso
from consola.datos import Base
from consola.disenos import Disenos
from consola.kmzs import RegistroKmz
from consola.proyectos import Registro
from pipeline.excel import leer_planilla
from pipeline.kmz import leer_kmz
from pipeline.panoramas import buscar_panoramas
from qa import ficticios
from qa.sembrar import (
    AJENO,
    CLAVE_QA,
    CUENTAS,
    PRADERAS,
    REPO,
    SIN_CONSTRUIR,
    VACIO,
    WHATSAPP_FICTICIO,
    motivo_para_no_sembrar,
    sembrar,
)

DATOS_QA = str(REPO / ".qa" / "datos")


# --- salvaguardas -----------------------------------------------------------------

def test_deja_sembrar_dentro_de_qa():
    assert motivo_para_no_sembrar({"MASTERPLAN_DATOS": DATOS_QA}) is None
    assert motivo_para_no_sembrar({"MASTERPLAN_DATOS": DATOS_QA, "CONSOLA_ENTORNO": ""}) is None
    assert motivo_para_no_sembrar({"MASTERPLAN_DATOS": DATOS_QA,
                                   "CONSOLA_ENTORNO": "local"}) is None


@pytest.mark.parametrize("datos", [None, "", str(REPO), str(REPO / "salidas"),
                                   str(REPO / ".qa-no"), str(REPO / ".qa" / ".." / "datos"),
                                   "/tmp/datos"])
def test_se_niega_fuera_de_qa(datos):
    entorno = {} if datos is None else {"MASTERPLAN_DATOS": datos}
    assert "MASTERPLAN_DATOS" in motivo_para_no_sembrar(entorno)


def test_se_niega_con_una_base_de_verdad():
    motivo = motivo_para_no_sembrar({"MASTERPLAN_DATOS": DATOS_QA,
                                     "MASTERPLAN_BD": "postgresql://algo/real"})
    assert "MASTERPLAN_BD" in motivo


@pytest.mark.parametrize("entorno", ["produccion", " local", "LOCAL"])
def test_se_niega_desplegada(entorno):
    # " local" o "LOCAL" la consola los toma por desplegada (`es_local`).
    motivo = motivo_para_no_sembrar({"MASTERPLAN_DATOS": DATOS_QA,
                                     "CONSOLA_ENTORNO": entorno})
    assert "CONSOLA_ENTORNO" in motivo


def test_el_comando_sale_con_2_y_sin_tocar_nada(tmp_path, monkeypatch, capsys):
    from qa.sembrar import main
    monkeypatch.setenv("MASTERPLAN_DATOS", str(tmp_path / "datos"))
    monkeypatch.delenv("MASTERPLAN_BD", raising=False)

    assert main([]) == 2
    assert "No siembro" in capsys.readouterr().err
    assert not (tmp_path / "datos").exists()


# --- la siembra ---------------------------------------------------------------------

@pytest.fixture
def sembrado(tmp_path):
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    registro = Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas")
    disenos = Disenos(base=base, carpeta=tmp_path / "disenos")
    kmzs = RegistroKmz(base=base, carpeta=tmp_path / "kmz")
    siembra = sembrar(base, registro, disenos, kmzs, construir=False, decir=lambda _: None)
    return base, registro, disenos, kmzs, siembra


def entrar(base, alias):
    return Acceso(base, secreto="x").entrar(CUENTAS[alias], CLAVE_QA)


def test_todas_las_cuentas_entran_con_la_clave_comun_menos_la_sin_confirmar(sembrado):
    base, *_ = sembrado
    for alias in ("plataforma", "duenio", "equipo", "otra"):
        sesion = entrar(base, alias)
        assert sesion is not None, alias
        assert not sesion.debe_cambiar_clave
    assert entrar(base, "sinconfirmar") is None
    usuario = base.usuario_por_email(CUENTAS["sinconfirmar"])
    assert usuario is not None and not usuario.email_verificado


def test_los_roles(sembrado):
    base, *_ = sembrado
    assert entrar(base, "plataforma").es_plataforma
    assert entrar(base, "duenio").rol == "dueño"
    assert entrar(base, "equipo").rol == "equipo"
    assert entrar(base, "equipo").cliente_id == entrar(base, "duenio").cliente_id


def test_duenio_ve_sus_loteos_y_no_el_ajeno(sembrado):
    base, registro, *_ = sembrado
    nombres = {p.nombre for p in registro.para(entrar(base, "duenio")).listar()}
    assert nombres == {PRADERAS, SIN_CONSTRUIR, VACIO}
    assert {p.nombre for p in registro.para(entrar(base, "otra")).listar()} == {AJENO}


def test_plataforma_ve_todos(sembrado):
    base, registro, *_ = sembrado
    nombres = {p.nombre for p in registro.para(entrar(base, "plataforma")).listar()}
    assert nombres == {PRADERAS, SIN_CONSTRUIR, VACIO, AJENO}


def test_los_loteos_de_la_demo(sembrado):
    base, registro, disenos, kmzs, _ = sembrado
    duenio = entrar(base, "duenio")
    loteos = {p.nombre: p for p in registro.para(duenio).listar()}

    praderas = loteos[PRADERAS]
    assert praderas.pagado and praderas.whatsapp == WHATSAPP_FICTICIO
    assert disenos.base.diseno(praderas.diseno_id).nombre == "Marca Demo"
    assert praderas.fuentes_encontradas() == {
        "kmz": "subdivision.kmz", "panoramicas": 2,
        "megas": praderas.fuentes_encontradas()["megas"], "planilla": "inventario.csv"}
    assert not praderas.construido

    assert not loteos[SIN_CONSTRUIR].pagado
    assert loteos[SIN_CONSTRUIR].fuentes_encontradas()["kmz"] == "subdivision.kmz"
    vacio = loteos[VACIO].fuentes_encontradas()
    assert vacio["kmz"] is None and vacio["panoramicas"] == 0
    assert [k.nombre for k in kmzs.para(duenio).listar()] == ["Plano de prueba"]


def test_una_segunda_corrida_no_duplica(sembrado):
    base, registro, disenos, kmzs, siembra = sembrado
    antes = (len(base.clientes()), len(base.proyectos()), len(base.disenos()))

    otra_vez = sembrar(base, registro, disenos, kmzs, construir=False)

    assert siembra.hecha and not otra_vez.hecha
    assert (len(base.clientes()), len(base.proyectos()), len(base.disenos())) == antes


def test_sin_construir_no_corre_ningun_comando(tmp_path):
    corridos = []
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    sembrar(base, Registro(base=base, subidas=tmp_path / "p", salidas=tmp_path / "s"),
            Disenos(base=base, carpeta=tmp_path / "d"), RegistroKmz(base=base, carpeta=tmp_path / "k"),
            construir=False, correr=lambda c: corridos.append(c) or (True, ""))
    assert corridos == []


def test_si_construir_falla_avisa_y_deja_el_resto(tmp_path):
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    registro = Registro(base=base, subidas=tmp_path / "p", salidas=tmp_path / "s")
    siembra = sembrar(base, registro, Disenos(base=base, carpeta=tmp_path / "d"),
                      RegistroKmz(base=base, carpeta=tmp_path / "k"), construir=True,
                      correr=lambda c: (False, "se cayó el pipeline"), decir=lambda _: None)

    assert siembra.hecha
    assert any("no se pudo construir" in a and "se cayó" in a for a in siembra.avisos)
    assert len(base.proyectos()) == 4


# --- los ficticios ------------------------------------------------------------------

def test_el_kmz_trae_doce_lotes_en_dos_etapas(tmp_path):
    parcelas = leer_kmz(ficticios.escribir_kmz(tmp_path / "loteo.kmz"))

    assert sorted((p.id, p.etapa) for p in parcelas) == (
        [(f"1-{n}", 1) for n in range(1, 7)] + [(f"2-{n}", 2) for n in range(1, 7)])
    assert all(p.area_m2 == pytest.approx(4900, rel=0.01) for p in parcelas)


def test_la_planilla_calza_con_el_kmz_y_tiene_estados_variados(tmp_path):
    fichas = leer_planilla(ficticios.escribir_planilla(tmp_path / "inventario.csv"))

    assert set(fichas) == {f"{e}-{n}" for e in (1, 2) for n in range(1, 7)}
    assert {f.estado for f in fichas.values()} == {"disponible", "reservado", "vendido",
                                                   "no_disponible"}
    assert any(f.precio for f in fichas.values())


def test_las_panoramicas_quedan_sobre_el_loteo(tmp_path):
    ficticios.escribir_panoramas(tmp_path)

    panoramas = buscar_panoramas(tmp_path)

    assert [p.id for p in panoramas] == ["p01-100", "p02-100"]
    for panorama in panoramas:
        assert abs(panorama.lat - ficticios.LAT) < 0.002
        assert abs(panorama.lon - ficticios.LON) < 0.003
