"""Entrar a la consola."""
import time

import pytest
from fastapi.testclient import TestClient

from consola.acceso import Acceso, Sesion


@pytest.fixture
def acceso():
    return Acceso(clave="abrete-sesamo", secreto="un-secreto-largo", horas=12)


# --- la sesión firmada ---------------------------------------------------------

def test_una_sesion_firmada_se_puede_volver_a_leer(acceso):
    galleta = acceso.firmar(Sesion(quien="mac"))

    assert acceso.leer(galleta).quien == "mac"


def test_una_sesion_alterada_no_vale(acceso):
    galleta = acceso.firmar(Sesion(quien="mac"))
    cuerpo, _, firma = galleta.rpartition(".")

    # Cambiar el contenido —aunque el cuerpo vaya en base64 y no se lea a simple vista.
    otro = acceso.firmar(Sesion(quien="intruso")).rpartition(".")[0]
    assert acceso.leer(f"{otro}.{firma}") is None
    # Cambiar la firma.
    assert acceso.leer(f"{cuerpo}.{firma[:-4]}aaaa") is None
    assert acceso.leer("cualquier cosa") is None
    assert acceso.leer(None) is None


def test_una_sesion_intacta_si_vale(acceso):
    """La contracara del test de arriba: que no esté rechazando todo."""
    assert acceso.leer(acceso.firmar(Sesion(quien="mac"))) is not None


def test_una_sesion_firmada_con_otro_secreto_no_vale(acceso):
    ajena = Acceso(clave="abrete-sesamo", secreto="otro-secreto", horas=12)

    assert acceso.leer(ajena.firmar(Sesion(quien="mac"))) is None


def test_una_sesion_vencida_no_vale():
    acceso = Acceso(clave="x", secreto="y", horas=0)

    galleta = acceso.firmar(Sesion(quien="mac", desde=time.time() - 60))

    assert acceso.leer(galleta) is None


@pytest.mark.parametrize("intento,vale", [("abrete-sesamo", True), ("otra", False), ("", False)])
def test_la_clave_se_compara_entera(acceso, intento, vale):
    assert acceso.es_valida(intento) is vale


# --- la puerta en la aplicación -------------------------------------------------

def cliente(monkeypatch, tmp_path, **entorno):
    for clave in ("CONSOLA_CLAVE", "CONSOLA_SECRETO", "CONSOLA_ENTORNO"):
        monkeypatch.delenv(clave, raising=False)
    for clave, valor in entorno.items():
        monkeypatch.setenv(clave, valor)
    from consola.app import crear_app
    from consola.proyectos import Registro
    registro = Registro(archivo=tmp_path / "p.json", subidas=tmp_path / "p", salidas=tmp_path / "s")
    return TestClient(crear_app(registro=registro), follow_redirects=False)


def test_sin_clave_configurada_y_fuera_de_local_la_consola_se_cierra(monkeypatch, tmp_path):
    """Desplegar sin contraseña dejaría la consola abierta: mejor que no funcione."""
    web = cliente(monkeypatch, tmp_path, CONSOLA_ENTORNO="produccion")

    respuesta = web.get("/api/proyectos")

    assert respuesta.status_code == 503
    assert "CONSOLA_CLAVE" in respuesta.json()["detail"]


def test_sin_clave_en_local_no_pide_nada(monkeypatch, tmp_path):
    web = cliente(monkeypatch, tmp_path)

    assert web.get("/api/proyectos").status_code == 200


def test_con_clave_la_api_pide_sesion(monkeypatch, tmp_path):
    web = cliente(monkeypatch, tmp_path, CONSOLA_CLAVE="abrete", CONSOLA_SECRETO="s")

    assert web.get("/api/proyectos").status_code == 401


def test_con_clave_la_pagina_manda_al_login(monkeypatch, tmp_path):
    web = cliente(monkeypatch, tmp_path, CONSOLA_CLAVE="abrete", CONSOLA_SECRETO="s")

    respuesta = web.get("/")

    assert respuesta.status_code == 307
    assert respuesta.headers["location"] == "/entrar"


def test_entrar_con_la_clave_correcta_abre_la_consola(monkeypatch, tmp_path):
    web = cliente(monkeypatch, tmp_path, CONSOLA_CLAVE="abrete", CONSOLA_SECRETO="s")

    respuesta = web.post("/entrar", data={"clave": "abrete"})

    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/"
    assert web.get("/api/proyectos").status_code == 200


def test_entrar_con_la_clave_equivocada_no_abre_nada(monkeypatch, tmp_path):
    web = cliente(monkeypatch, tmp_path, CONSOLA_CLAVE="abrete", CONSOLA_SECRETO="s")

    respuesta = web.post("/entrar", data={"clave": "otra"})

    assert respuesta.status_code == 401
    assert web.get("/api/proyectos").status_code == 401


def test_la_galleta_no_se_puede_leer_desde_javascript(monkeypatch, tmp_path):
    web = cliente(monkeypatch, tmp_path, CONSOLA_CLAVE="abrete", CONSOLA_SECRETO="s")

    respuesta = web.post("/entrar", data={"clave": "abrete"})

    galleta = respuesta.headers["set-cookie"].lower()
    assert "httponly" in galleta and "samesite=lax" in galleta


def test_salir_cierra_la_sesion(monkeypatch, tmp_path):
    web = cliente(monkeypatch, tmp_path, CONSOLA_CLAVE="abrete", CONSOLA_SECRETO="s")
    web.post("/entrar", data={"clave": "abrete"})

    web.post("/salir")

    assert web.get("/api/proyectos").status_code == 401


def test_la_pagina_de_entrar_siempre_se_puede_ver(monkeypatch, tmp_path):
    web = cliente(monkeypatch, tmp_path, CONSOLA_CLAVE="abrete", CONSOLA_SECRETO="s")

    respuesta = web.get("/entrar")

    assert respuesta.status_code == 200
    assert "contraseña" in respuesta.text.lower()


def test_la_consola_dice_si_pide_contrasena(monkeypatch, tmp_path):
    """La página usa esto para mostrar u ocultar el botón de salir."""
    con = cliente(monkeypatch, tmp_path, CONSOLA_CLAVE="abrete", CONSOLA_SECRETO="s")
    con.post("/entrar", data={"clave": "abrete"})

    assert con.get("/api/sesion").json() == {"exigida": True}
    assert cliente(monkeypatch, tmp_path).get("/api/sesion").json() == {"exigida": False}
