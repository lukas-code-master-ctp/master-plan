"""Entrar a la consola: quién es cada quien, y hasta cuándo."""
import json

import pytest
from fastapi.testclient import TestClient

from consola.acceso import Acceso, _de_base64
from consola.datos import Base


@pytest.fixture
def base(tmp_path):
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    base.cambiar_clave("ana@losrobles.cl", "la-clave-de-ana")
    return base


@pytest.fixture
def acceso(base):
    return Acceso(base=base, secreto="un-secreto-largo", horas=12)


# --- entrar ---------------------------------------------------------------------

def test_entrar_con_la_clave_correcta_dice_quien_es(acceso, base):
    sesion = acceso.entrar("ana@losrobles.cl", "la-clave-de-ana")

    assert sesion.quien == "ana@losrobles.cl"
    assert sesion.cliente_id == base.usuario_por_email("ana@losrobles.cl").cliente_id
    assert sesion.rol == "dueño"
    assert sesion.es_plataforma is False


@pytest.mark.parametrize("email,clave", [
    ("ana@losrobles.cl", "otra-clave"),
    ("ana@losrobles.cl", ""),
    ("nadie@ninguna.cl", "la-clave-de-ana"),
    ("", "la-clave-de-ana"),
])
def test_entrar_con_cualquier_cosa_mal_no_abre_nada(acceso, email, clave):
    assert acceso.entrar(email, clave) is None


def test_el_correo_no_distingue_mayusculas(acceso):
    assert acceso.entrar("Ana@LosRobles.CL", "la-clave-de-ana") is not None


def test_una_cuenta_desactivada_no_entra(acceso, base):
    base.desactivar_usuario("ana@losrobles.cl")

    assert acceso.entrar("ana@losrobles.cl", "la-clave-de-ana") is None


def test_la_gente_de_un_cliente_suspendido_no_entra(acceso, base):
    base.suspender(base.usuario_por_email("ana@losrobles.cl").cliente_id)

    assert acceso.entrar("ana@losrobles.cl", "la-clave-de-ana") is None


# --- la galleta -----------------------------------------------------------------

def test_una_sesion_firmada_se_puede_volver_a_leer(acceso):
    galleta = acceso.firmar(acceso.entrar("ana@losrobles.cl", "la-clave-de-ana"))

    assert acceso.leer(galleta).quien == "ana@losrobles.cl"


def test_la_galleta_no_lleva_el_rol_ni_de_quien_es(acceso):
    """Solo el id y la hora. Todo lo demás se relee de la base en cada petición,
    para que un cambio de rol o una baja valgan en la petición siguiente."""
    galleta = acceso.firmar(acceso.entrar("ana@losrobles.cl", "la-clave-de-ana"))

    cuerpo = json.loads(_de_base64(galleta.rpartition(".")[0]))

    assert sorted(cuerpo) == ["d", "u"]


def test_una_sesion_alterada_no_vale(acceso, base):
    base.crear_usuario(base.usuario_por_email("ana@losrobles.cl").cliente_id,
                       "luis@losrobles.cl", "Luis")
    galleta = acceso.firmar(acceso.entrar("ana@losrobles.cl", "la-clave-de-ana"))
    cuerpo, _, firma = galleta.rpartition(".")

    # Cambiar el contenido, aunque vaya en base64 y no se lea a simple vista.
    otro = acceso.firmar(acceso.entrar("ana@losrobles.cl", "la-clave-de-ana")
                         ).rpartition(".")[0]
    assert acceso.leer(f"{otro}.{firma}") is None
    # Cambiar la firma.
    assert acceso.leer(f"{cuerpo}.{firma[:-4]}aaaa") is None
    assert acceso.leer("cualquier cosa") is None
    assert acceso.leer(None) is None


def test_una_sesion_intacta_si_vale(acceso):
    """La contracara del test de arriba: que no esté rechazando todo."""
    assert acceso.leer(acceso.firmar(acceso.entrar("ana@losrobles.cl", "la-clave-de-ana")))


def test_una_sesion_firmada_con_otro_secreto_no_vale(acceso, base):
    ajena = Acceso(base=base, secreto="otro-secreto", horas=12)

    galleta = ajena.firmar(ajena.entrar("ana@losrobles.cl", "la-clave-de-ana"))

    assert acceso.leer(galleta) is None


def test_una_sesion_vencida_no_vale(base):
    acceso = Acceso(base=base, secreto="y", horas=0)

    assert acceso.leer(acceso.firmar(acceso.entrar("ana@losrobles.cl", "la-clave-de-ana"))) is None


def test_una_galleta_de_un_usuario_que_ya_no_esta_no_vale(acceso, base):
    galleta = acceso.firmar(acceso.entrar("ana@losrobles.cl", "la-clave-de-ana"))

    base.desactivar_usuario("ana@losrobles.cl")

    assert acceso.leer(galleta) is None


def test_cambiar_la_clave_corta_las_sesiones_abiertas(acceso, base):
    """Uno cambia la clave justamente porque sospecha de alguien: dejar viva la
    sesión de ese alguien haría inútil el cambio."""
    galleta = acceso.firmar(acceso.entrar("ana@losrobles.cl", "la-clave-de-ana"))
    assert acceso.leer(galleta) is not None

    base.cambiar_clave("ana@losrobles.cl", "otra-clave-nueva")

    assert acceso.leer(galleta) is None


def test_suspender_al_cliente_corta_las_sesiones_de_su_gente(acceso, base):
    galleta = acceso.firmar(acceso.entrar("ana@losrobles.cl", "la-clave-de-ana"))

    base.suspender(base.usuario_por_email("ana@losrobles.cl").cliente_id)

    assert acceso.leer(galleta) is None


def test_ascender_a_plataforma_vale_en_la_peticion_siguiente(acceso, base):
    galleta = acceso.firmar(acceso.entrar("ana@losrobles.cl", "la-clave-de-ana"))
    assert acceso.leer(galleta).es_plataforma is False

    base.ascender_a_plataforma("ana@losrobles.cl")

    assert acceso.leer(galleta).es_plataforma is True


# --- la puerta en la aplicación -------------------------------------------------

def web(base, tmp_path, monkeypatch, **entorno):
    for clave in ("CONSOLA_SECRETO", "CONSOLA_ENTORNO"):
        monkeypatch.delenv(clave, raising=False)
    for clave, valor in entorno.items():
        monkeypatch.setenv(clave, valor)
    monkeypatch.setattr("pipeline.config.DATOS", tmp_path)

    from consola.acceso import desde_el_entorno
    from consola.app import crear_app
    from consola.proyectos import Registro
    registro = Registro(base=base, subidas=tmp_path / "p", salidas=tmp_path / "s")
    return TestClient(crear_app(registro=registro, acceso=desde_el_entorno(base)),
                      follow_redirects=False)


def test_sin_secreto_de_firma_y_fuera_de_local_la_consola_se_cierra(base, tmp_path, monkeypatch):
    """Sin secreto cualquiera se fabrica una galleta: mejor que no funcione."""
    cliente = web(base, tmp_path, monkeypatch, CONSOLA_ENTORNO="produccion")

    respuesta = cliente.get("/api/proyectos")

    assert respuesta.status_code == 503
    assert "CONSOLA_SECRETO" in respuesta.json()["detail"]


def test_en_local_el_secreto_se_genera_solo_y_no_queda_a_la_vista(base, tmp_path, monkeypatch):
    web(base, tmp_path, monkeypatch)

    archivo = tmp_path / ".secreto-consola"
    assert len(archivo.read_text()) >= 32
    assert oct(archivo.stat().st_mode)[-3:] == "600"


def test_sin_sesion_la_api_pide_entrar(base, tmp_path, monkeypatch):
    cliente = web(base, tmp_path, monkeypatch)

    assert cliente.get("/api/proyectos").status_code == 401


def test_sin_sesion_la_pagina_manda_al_login(base, tmp_path, monkeypatch):
    cliente = web(base, tmp_path, monkeypatch)

    respuesta = cliente.get("/")

    assert respuesta.status_code == 307
    assert respuesta.headers["location"] == "/entrar"


def test_entrar_con_la_cuenta_correcta_abre_la_consola(base, tmp_path, monkeypatch):
    cliente = web(base, tmp_path, monkeypatch)

    respuesta = cliente.post("/entrar", data={"email": "ana@losrobles.cl",
                                              "clave": "la-clave-de-ana"})

    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == "/"
    assert cliente.get("/api/proyectos").status_code == 200


def test_entrar_mal_no_dice_si_el_correo_existe(base, tmp_path, monkeypatch):
    cliente = web(base, tmp_path, monkeypatch)

    existe = cliente.post("/entrar", data={"email": "ana@losrobles.cl", "clave": "otra"})
    no_existe = cliente.post("/entrar", data={"email": "nadie@nada.cl", "clave": "otra"})

    assert existe.status_code == no_existe.status_code == 401
    assert existe.text == no_existe.text
    assert cliente.get("/api/proyectos").status_code == 401


def test_la_galleta_no_se_puede_leer_desde_javascript(base, tmp_path, monkeypatch):
    cliente = web(base, tmp_path, monkeypatch)

    respuesta = cliente.post("/entrar", data={"email": "ana@losrobles.cl",
                                              "clave": "la-clave-de-ana"})

    galleta = respuesta.headers["set-cookie"].lower()
    assert "httponly" in galleta and "samesite=lax" in galleta


def test_salir_cierra_la_sesion(base, tmp_path, monkeypatch):
    cliente = web(base, tmp_path, monkeypatch)
    cliente.post("/entrar", data={"email": "ana@losrobles.cl", "clave": "la-clave-de-ana"})

    cliente.post("/salir")

    assert cliente.get("/api/proyectos").status_code == 401


def test_la_pagina_de_entrar_siempre_se_puede_ver(base, tmp_path, monkeypatch):
    cliente = web(base, tmp_path, monkeypatch)

    respuesta = cliente.get("/entrar")

    assert respuesta.status_code == 200
    assert "contraseña" in respuesta.text.lower()


def test_la_consola_dice_quien_entro(base, tmp_path, monkeypatch):
    cliente = web(base, tmp_path, monkeypatch)
    cliente.post("/entrar", data={"email": "ana@losrobles.cl", "clave": "la-clave-de-ana"})

    cuerpo = cliente.get("/api/sesion").json()

    assert cuerpo["quien"] == "ana@losrobles.cl"
    assert cuerpo["cliente"] == "Los Robles"
    assert cuerpo["rol"] == "dueño"


# --- cambiar la propia clave ------------------------------------------------------

def test_cambiar_la_clave_desde_la_consola(base, tmp_path, monkeypatch):
    cliente = web(base, tmp_path, monkeypatch)
    cliente.post("/entrar", data={"email": "ana@losrobles.cl", "clave": "la-clave-de-ana"})

    respuesta = cliente.post("/api/clave", json={"actual": "la-clave-de-ana",
                                                 "nueva": "una-clave-bastante-larga"})

    assert respuesta.status_code == 200
    # Cambiarla cierra la sesión: hay que volver a entrar, ahora con la nueva.
    assert cliente.get("/api/proyectos").status_code == 401
    assert cliente.post("/entrar", data={"email": "ana@losrobles.cl",
                                         "clave": "una-clave-bastante-larga"}).status_code == 303


def test_no_se_puede_cambiar_la_clave_sin_saber_la_actual(base, tmp_path, monkeypatch):
    """Si no, basta con dejar una sesión abierta un minuto para quedarse la cuenta."""
    cliente = web(base, tmp_path, monkeypatch)
    cliente.post("/entrar", data={"email": "ana@losrobles.cl", "clave": "la-clave-de-ana"})

    respuesta = cliente.post("/api/clave", json={"actual": "no-es-esa",
                                                 "nueva": "una-clave-bastante-larga"})

    assert respuesta.status_code == 403
    assert base.clave_valida(base.usuario_por_email("ana@losrobles.cl"), "la-clave-de-ana")


def test_una_clave_nueva_muy_corta_no_se_acepta(base, tmp_path, monkeypatch):
    cliente = web(base, tmp_path, monkeypatch)
    cliente.post("/entrar", data={"email": "ana@losrobles.cl", "clave": "la-clave-de-ana"})

    respuesta = cliente.post("/api/clave", json={"actual": "la-clave-de-ana", "nueva": "corta"})

    assert respuesta.status_code == 400
