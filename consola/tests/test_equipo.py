"""Configuración → Tu cuenta y Equipo: el perfil propio y quién más entra a la loteadora."""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import update

from consola.datos import invitaciones

from .test_cuentas import (  # noqa: F401  (sin_correo es fixture)
    CLAVE,
    HttpDeGoogle,
    ir_y_volver,
    montar,
    sin_correo,
)


def entrar(web, email, clave=CLAVE):
    respuesta = web.post("/entrar", data={"email": email, "clave": clave})
    assert respuesta.status_code == 303, respuesta.text
    return respuesta


@pytest.fixture
def loteadora(tmp_path):
    """Pía es dueña de Bosques del Sur y Tomás es de su equipo. Otra loteadora aparte."""
    web, base, correo = montar(tmp_path)
    pia = base.crear_cuenta_propia("Bosques del Sur", "pia@bosques.cl", "Pía Soto", CLAVE, verificado=True)
    tomas, _ = base.crear_usuario(pia.cliente_id, "tomas@bosques.cl", "Tomás")
    base.cambiar_clave("tomas@bosques.cl", CLAVE)
    base.crear_cuenta_propia("Otra", "ana@otra.cl", "Ana", CLAVE, verificado=True)
    return web, base, correo, pia, tomas


# --- Tu cuenta ---------------------------------------------------------------------

def test_la_cuenta_dice_quien_eres_y_quien_mas_entra(loteadora):
    web, _, _, _, tomas = loteadora
    entrar(web, "pia@bosques.cl")

    cuenta = web.get("/api/cuenta").json()

    assert cuenta["email"] == "pia@bosques.cl"
    assert cuenta["nombre"] == "Pía Soto"
    assert cuenta["rol"] == "dueño"
    assert cuenta["loteadora"] == "Bosques del Sur"
    assert cuenta["administra"] is True
    assert cuenta["google"] is False
    correos = {m["email"]: m for m in cuenta["equipo"]}
    assert set(correos) == {"pia@bosques.cl", "tomas@bosques.cl"}
    assert correos["pia@bosques.cl"]["yo"] is True
    assert correos["tomas@bosques.cl"]["id"] == tomas.id


def test_el_equipo_ve_la_lista_pero_no_la_administra(loteadora):
    web, *_ = loteadora
    entrar(web, "tomas@bosques.cl")

    cuenta = web.get("/api/cuenta").json()

    assert cuenta["administra"] is False
    assert len(cuenta["equipo"]) == 2


def test_cambiar_el_propio_nombre(loteadora):
    web, base, _, pia, _ = loteadora
    entrar(web, "pia@bosques.cl")

    respuesta = web.patch("/api/cuenta", json={"nombre": "  Pía Soto R.  "})

    assert respuesta.status_code == 200
    assert base.usuario(pia.id).nombre == "Pía Soto R."


def test_un_nombre_vacio_no_se_guarda(loteadora):
    web, *_ = loteadora
    entrar(web, "pia@bosques.cl")

    assert web.patch("/api/cuenta", json={"nombre": "   "}).status_code == 400


def test_la_duena_renombra_la_loteadora_y_el_equipo_no(loteadora):
    web, base, _, pia, _ = loteadora
    entrar(web, "tomas@bosques.cl")
    assert web.patch("/api/cuenta", json={"loteadora": "Otro nombre"}).status_code == 403

    entrar(web, "pia@bosques.cl")
    assert web.patch("/api/cuenta", json={"loteadora": "Bosques del Sur SpA"}).status_code == 200
    assert base.cliente(pia.cliente_id).nombre == "Bosques del Sur SpA"


def test_cerrar_todas_las_sesiones_corta_tambien_esta(loteadora):
    web, *_ = loteadora
    entrar(web, "pia@bosques.cl")

    respuesta = web.post("/api/cuenta/sesiones/cerrar")

    assert respuesta.status_code == 200
    web.cookies.clear()
    entrar(web, "pia@bosques.cl")      # con la clave se vuelve a entrar sin problema
    assert web.get("/api/cuenta").status_code == 200


def test_una_sesion_vieja_no_sirve_despues_de_cerrarlas(loteadora):
    web, base, _, pia, _ = loteadora
    galleta = entrar(web, "pia@bosques.cl").cookies

    base.cortar_sesiones(pia.id)

    web.cookies.clear()
    web.cookies.update(galleta)
    assert web.get("/api/cuenta").status_code == 401


# --- Invitar -----------------------------------------------------------------------

def invitar_a_rosa(web, email="Rosa@Bosques.cl"):
    entrar(web, "pia@bosques.cl")
    respuesta = web.post("/api/equipo", json={"nombre": "Rosa", "email": email})
    assert respuesta.status_code == 201, respuesta.text
    web.cookies.clear()
    return respuesta


def token_de(enlace):
    return enlace.split("t=")[1]


def test_invitar_no_crea_la_cuenta_y_manda_el_enlace_para_aceptar(loteadora):
    web, base, correo, *_ = loteadora

    respuesta = invitar_a_rosa(web)

    assert respuesta.json() == {"email": "rosa@bosques.cl", "invitacion": "correo"}
    # La invitación sola no ata ese correo a la loteadora.
    assert base.usuario_por_email("rosa@bosques.cl") is None
    para, _, texto = correo.enviados[-1]
    assert para == "rosa@bosques.cl"
    assert "Pía Soto" in texto and "Bosques del Sur" in texto
    assert correo.enlace("rosa@bosques.cl", "/invitacion")


def test_la_pagina_de_la_invitacion_dice_quien_invita_y_no_acepta_sola(loteadora):
    web, base, correo, *_ = loteadora
    invitar_a_rosa(web)

    pagina = web.get(correo.enlace("rosa@bosques.cl", "/invitacion"))

    assert pagina.status_code == 200
    assert "Pía Soto" in pagina.text and "Bosques del Sur" in pagina.text
    assert "rosa@bosques.cl" in pagina.text
    # Abrir el enlace (o que lo abra el antivirus del correo) no acepta nada.
    assert base.usuario_por_email("rosa@bosques.cl") is None


def test_aceptar_crea_la_cuenta_en_la_loteadora_y_entra(loteadora):
    web, base, correo, pia, _ = loteadora
    invitar_a_rosa(web)
    token = token_de(correo.enlace("rosa@bosques.cl", "/invitacion"))

    respuesta = web.post("/invitacion", data={"t": token, "clave": "una-clave-de-rosa"})

    assert respuesta.status_code == 303
    rosa = base.usuario_por_email("rosa@bosques.cl")
    assert rosa.cliente_id == pia.cliente_id
    assert rosa.rol == "equipo"
    assert rosa.nombre == "Rosa"
    assert web.get("/api/cuenta").json()["email"] == "rosa@bosques.cl"
    web.cookies.clear()
    entrar(web, "rosa@bosques.cl", "una-clave-de-rosa")
    assert web.get("/api/sesion").json()["debe_cambiar_clave"] is False


def test_una_invitacion_se_acepta_una_sola_vez(loteadora):
    web, _, correo, *_ = loteadora
    invitar_a_rosa(web)
    token = token_de(correo.enlace("rosa@bosques.cl", "/invitacion"))
    web.post("/invitacion", data={"t": token, "clave": "una-clave-de-rosa"})
    web.cookies.clear()

    assert web.post("/invitacion", data={"t": token, "clave": "otra-clave-de-rosa"}).status_code == 400
    assert web.get(f"/invitacion?t={token}").status_code == 400


def test_una_clave_corta_no_acepta_la_invitacion(loteadora):
    web, base, correo, *_ = loteadora
    invitar_a_rosa(web)
    token = token_de(correo.enlace("rosa@bosques.cl", "/invitacion"))

    respuesta = web.post("/invitacion", data={"t": token, "clave": "corta"})

    assert respuesta.status_code == 400
    assert base.usuario_por_email("rosa@bosques.cl") is None
    # Y el enlace sigue sirviendo.
    assert web.post("/invitacion", data={"t": token, "clave": "una-clave-de-rosa"}).status_code == 303


def test_una_invitacion_vencida_no_sirve(loteadora):
    web, base, correo, *_ = loteadora
    invitar_a_rosa(web)
    token = token_de(correo.enlace("rosa@bosques.cl", "/invitacion"))
    with base.motor.begin() as con:
        con.execute(update(invitaciones).values(vence_en=datetime.now(timezone.utc) - timedelta(minutes=1)))

    assert web.get(f"/invitacion?t={token}").status_code == 400
    assert web.post("/invitacion", data={"t": token, "clave": "una-clave-de-rosa"}).status_code == 400
    assert base.usuario_por_email("rosa@bosques.cl") is None


def test_quien_fue_invitado_puede_crear_su_propia_loteadora(loteadora):
    """El problema de antes: la invitación tomaba el correo y no lo dejaba registrarse."""
    web, base, correo, pia, _ = loteadora
    invitar_a_rosa(web)
    token = token_de(correo.enlace("rosa@bosques.cl", "/invitacion"))

    rosa = base.crear_cuenta_propia("Rosales", "rosa@bosques.cl", "Rosa", CLAVE, verificado=True)

    assert rosa.cliente_id != pia.cliente_id
    # La invitación ya no la puede mover de loteadora.
    respuesta = web.post("/invitacion", data={"t": token, "clave": "una-clave-de-rosa"})
    assert respuesta.status_code == 409
    assert base.usuario_por_email("rosa@bosques.cl").cliente_id == rosa.cliente_id


def test_la_lista_del_equipo_muestra_las_invitaciones_pendientes(loteadora):
    web, *_ = loteadora
    invitar_a_rosa(web)
    entrar(web, "tomas@bosques.cl")

    cuenta = web.get("/api/cuenta").json()

    assert {m["email"] for m in cuenta["equipo"]} == {"pia@bosques.cl", "tomas@bosques.cl"}
    assert [(i["nombre"], i["email"], i["vencida"]) for i in cuenta["invitaciones"]] == [
        ("Rosa", "rosa@bosques.cl", False)]


def test_volver_a_invitar_reemplaza_el_enlace_anterior(loteadora):
    web, base, correo, *_ = loteadora
    invitar_a_rosa(web)
    primero = token_de(correo.enlace("rosa@bosques.cl", "/invitacion"))
    invitar_a_rosa(web)
    segundo = token_de(correo.enlace("rosa@bosques.cl", "/invitacion"))

    assert primero != segundo
    assert web.get(f"/invitacion?t={primero}").status_code == 400
    assert web.get(f"/invitacion?t={segundo}").status_code == 200
    entrar(web, "pia@bosques.cl")
    assert len(web.get("/api/cuenta").json()["invitaciones"]) == 1


def test_la_duena_anula_una_invitacion_y_el_enlace_deja_de_servir(loteadora):
    web, base, correo, *_ = loteadora
    invitar_a_rosa(web)
    token = token_de(correo.enlace("rosa@bosques.cl", "/invitacion"))
    entrar(web, "pia@bosques.cl")
    invitacion = web.get("/api/cuenta").json()["invitaciones"][0]

    assert web.delete(f"/api/equipo/invitaciones/{invitacion['id']}").status_code == 200

    assert web.get("/api/cuenta").json()["invitaciones"] == []
    web.cookies.clear()
    assert web.post("/invitacion", data={"t": token, "clave": "una-clave-de-rosa"}).status_code == 400


def test_el_equipo_no_anula_invitaciones(loteadora):
    web, *_ = loteadora
    invitar_a_rosa(web)
    entrar(web, "tomas@bosques.cl")
    invitacion = web.get("/api/cuenta").json()["invitaciones"][0]

    assert web.delete(f"/api/equipo/invitaciones/{invitacion['id']}").status_code == 403


def test_una_invitacion_de_otra_loteadora_es_404(loteadora):
    web, *_ = loteadora
    invitar_a_rosa(web)
    entrar(web, "pia@bosques.cl")
    invitacion = web.get("/api/cuenta").json()["invitaciones"][0]
    entrar(web, "ana@otra.cl")

    assert web.delete(f"/api/equipo/invitaciones/{invitacion['id']}").status_code == 404
    assert web.get("/api/cuenta").json()["invitaciones"] == []
    entrar(web, "pia@bosques.cl")
    assert len(web.get("/api/cuenta").json()["invitaciones"]) == 1


def test_sin_correo_la_invitacion_trae_el_enlace_para_entregar(sin_correo):  # noqa: F811
    web, base, _ = sin_correo
    base.crear_cuenta_propia("Bosques del Sur", "pia@bosques.cl", "Pía Soto", CLAVE, verificado=True)
    entrar(web, "pia@bosques.cl")

    respuesta = web.post("/api/equipo", json={"nombre": "Rosa", "email": "rosa@bosques.cl"})

    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert datos["invitacion"] == "enlace"
    assert "clave_provisional" not in datos
    assert base.usuario_por_email("rosa@bosques.cl") is None
    web.cookies.clear()
    aceptada = web.post("/invitacion", data={"t": token_de(datos["enlace"]), "clave": "una-clave-de-rosa"})
    assert aceptada.status_code == 303
    assert web.get("/api/cuenta").json()["loteadora"] == "Bosques del Sur"


def test_solo_la_duena_invita(loteadora):
    web, base, correo, *_ = loteadora
    entrar(web, "tomas@bosques.cl")

    respuesta = web.post("/api/equipo", json={"nombre": "Rosa", "email": "rosa@bosques.cl"})

    assert respuesta.status_code == 403
    assert correo.enviados == []


@pytest.mark.parametrize("campos", [{"nombre": "Rosa", "email": "no-es-correo"},
                                    {"nombre": "", "email": "rosa@bosques.cl"}])
def test_una_invitacion_incompleta_no_crea_nada(loteadora, campos):
    web, base, correo, *_ = loteadora
    entrar(web, "pia@bosques.cl")

    assert web.post("/api/equipo", json=campos).status_code == 400
    assert web.get("/api/cuenta").json()["invitaciones"] == []
    assert correo.enviados == []


def test_invitar_un_correo_que_ya_tiene_cuenta_avisa(loteadora):
    web, *_ = loteadora
    entrar(web, "pia@bosques.cl")

    assert web.post("/api/equipo", json={"nombre": "Ana", "email": "ana@otra.cl"}).status_code == 409


# --- Aceptar con Google ----------------------------------------------------------------

@pytest.fixture
def con_google(tmp_path):
    """Como `loteadora`, con Google configurado. Rosa entra a Google con su correo."""
    google = HttpDeGoogle(sub="g-rosa", email="rosa@bosques.cl", nombre="Rosa Díaz")
    web, base, correo = montar(tmp_path, http=google)
    base.crear_cuenta_propia("Bosques del Sur", "pia@bosques.cl", "Pía Soto", CLAVE, verificado=True)
    return web, base, correo, google


def aceptar_con_google(web, token):
    ida = web.get(f"/entrar/google?invitacion={token}")
    estado = parse_qs(urlparse(ida.headers["location"]).query)["state"][0]
    return web.get(f"/entrar/google/vuelta?code=bueno&state={estado}")


def test_entrar_con_google_sin_aceptar_no_suma_al_equipo(con_google):
    web, base, *_ = con_google
    invitar_a_rosa(web)

    vuelta = ir_y_volver(web)

    # Le ofrece crear su propia loteadora, no la deja en la que la invitó.
    assert vuelta.headers["location"] == "/registro/google"
    assert base.usuario_por_email("rosa@bosques.cl") is None


def test_aceptar_con_google_crea_la_cuenta_y_la_enlaza(con_google):
    web, base, correo, _ = con_google
    invitar_a_rosa(web)
    token = token_de(correo.enlace("rosa@bosques.cl", "/invitacion"))

    vuelta = aceptar_con_google(web, token)

    assert vuelta.status_code == 303 and vuelta.headers["location"] == "/#/planos"
    rosa = base.usuario_por_email("rosa@bosques.cl")
    assert base.cliente(rosa.cliente_id).nombre == "Bosques del Sur"
    assert base.usuario_por_identidad("google", "g-rosa").id == rosa.id
    assert web.get("/api/cuenta").json()["email"] == "rosa@bosques.cl"


def test_aceptar_con_google_pide_el_mismo_correo_invitado(con_google):
    web, base, correo, google = con_google
    invitar_a_rosa(web)
    token = token_de(correo.enlace("rosa@bosques.cl", "/invitacion"))
    google.datos["email"] = "otra.persona@gmail.com"

    vuelta = aceptar_con_google(web, token)

    assert vuelta.status_code == 400
    assert "otra.persona@gmail.com" in vuelta.text
    assert base.usuario_por_email("rosa@bosques.cl") is None
    assert base.usuario_por_email("otra.persona@gmail.com") is None


# --- Desactivar y reactivar ---------------------------------------------------------

def test_la_duena_desactiva_a_alguien_y_le_corta_la_sesion(loteadora):
    web, base, _, _, tomas = loteadora
    galleta_de_tomas = entrar(web, "tomas@bosques.cl").cookies
    entrar(web, "pia@bosques.cl")

    respuesta = web.post(f"/api/equipo/{tomas.id}/estado", json={"activo": False})

    assert respuesta.status_code == 200
    assert base.usuario(tomas.id).activo is False
    web.cookies.clear()
    web.cookies.update(galleta_de_tomas)
    assert web.get("/api/cuenta").status_code == 401


def test_reactivar_devuelve_la_entrada(loteadora):
    web, base, _, _, tomas = loteadora
    entrar(web, "pia@bosques.cl")
    web.post(f"/api/equipo/{tomas.id}/estado", json={"activo": False})

    web.post(f"/api/equipo/{tomas.id}/estado", json={"activo": True})

    assert base.usuario(tomas.id).activo is True
    web.cookies.clear()
    entrar(web, "tomas@bosques.cl")


def test_nadie_se_desactiva_a_si_misma(loteadora):
    web, _, _, pia, _ = loteadora
    entrar(web, "pia@bosques.cl")

    assert web.post(f"/api/equipo/{pia.id}/estado", json={"activo": False}).status_code == 400


def test_el_equipo_no_desactiva_a_nadie(loteadora):
    web, _, _, pia, _ = loteadora
    entrar(web, "tomas@bosques.cl")

    assert web.post(f"/api/equipo/{pia.id}/estado", json={"activo": False}).status_code == 403


def test_alguien_de_otra_loteadora_es_404(loteadora):
    web, base, *_ = loteadora
    ana = base.usuario_por_email("ana@otra.cl")
    entrar(web, "pia@bosques.cl")

    assert web.post(f"/api/equipo/{ana.id}/estado", json={"activo": False}).status_code == 404
    assert base.usuario(ana.id).activo is True
