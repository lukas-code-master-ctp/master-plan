"""Los avisos que llevan a una loteadora nueva hasta su primera publicación:
cuenta nueva y pedido de habilitación a CTP, loteo habilitado a la loteadora."""
import pytest

from fastapi.testclient import TestClient

from consola.tests.test_cuentas import CLAVE, HttpDeGoogle, confirmar, ir_y_volver, montar, registrarse

CTP = "ctp@ctp.cl"


def a(correo, para):
    return [(asunto, texto) for destino, asunto, texto in correo.enviados if destino == para]


def entrar(web, email):
    respuesta = web.post("/entrar", data={"email": email, "clave": CLAVE})
    assert respuesta.status_code == 303, respuesta.text


# --- cuenta nueva --------------------------------------------------------------------

def test_al_confirmar_una_cuenta_nueva_se_avisa_a_ctp(tmp_path):
    web, _, correo = montar(tmp_path)
    registrarse(web)
    assert a(correo, CTP) == []          # sin confirmar todavía no es una cuenta

    confirmar(web, correo)

    [(asunto, texto)] = a(correo, CTP)
    assert asunto == "Cuenta nueva: Bosques del Sur"
    assert "pia@bosques.cl" in texto
    assert "http://testserver/" in texto


def test_un_segundo_enlace_de_confirmacion_no_vuelve_a_avisar(tmp_path):
    web, _, correo = montar(tmp_path)
    registrarse(web)
    registrarse(web)                     # sin confirmar: le reenvía el enlace
    primero, segundo = [t for d, _, t in correo.enviados if d == "pia@bosques.cl"]

    for texto in (primero, segundo):
        web.post("/verificar", data={"t": texto.split("t=")[1].split()[0]})

    assert len(a(correo, CTP)) == 1


def test_una_cuenta_nueva_con_google_tambien_avisa(tmp_path):
    web, _, correo = montar(tmp_path, http=HttpDeGoogle())
    ir_y_volver(web)

    web.post("/registro/google", data={"loteadora": "Bosques del Sur"})

    [(asunto, _)] = a(correo, CTP)
    assert asunto == "Cuenta nueva: Bosques del Sur"


# --- pedir habilitación y anotar el pago ------------------------------------------------

@pytest.fixture
def con_loteo(tmp_path):
    """Pía se registró, confirmó y se creó un master; CTP entra aparte."""
    web, base, correo = montar(tmp_path)
    registrarse(web)
    confirmar(web, correo)
    slug = web.post("/api/proyectos", json={"nombre": "Mi Loteo"}).json()["slug"]
    correo.enviados.clear()
    return web, base, correo, slug


def test_pedir_habilitacion_avisa_a_ctp_una_sola_vez(con_loteo):
    web, _, correo, slug = con_loteo

    primera = web.post(f"/api/proyectos/{slug}/habilitacion")
    segunda = web.post(f"/api/proyectos/{slug}/habilitacion")

    assert primera.status_code == segunda.status_code == 200
    assert primera.json()["habilitacion_pedida"]
    assert segunda.json()["habilitacion_pedida"] == primera.json()["habilitacion_pedida"]
    [(asunto, texto)] = a(correo, CTP)
    assert asunto == "Pide habilitar un loteo: Mi Loteo (Bosques del Sur)"
    assert f"http://testserver/#/planos/{slug}" in texto
    assert "pia@bosques.cl" in texto


def test_pedirlo_no_habilita_nada(con_loteo):
    web, _, _, slug = con_loteo

    loteo = web.post(f"/api/proyectos/{slug}/habilitacion").json()

    assert loteo["pagado"] is False


def test_anotar_el_pago_le_avisa_a_la_loteadora(con_loteo):
    web, _, correo, slug = con_loteo
    ctp = TestClient(web.app, follow_redirects=False)
    entrar(ctp, CTP)

    respuesta = ctp.post(f"/api/plataforma/proyectos/{slug}/pago", json={"nota_cobro": "transf. 1"})

    assert respuesta.status_code == 200, respuesta.text
    [(asunto, texto)] = a(correo, "pia@bosques.cl")
    assert asunto == "Ya puedes publicar Mi Loteo"
    assert f"http://testserver/#/planos/{slug}" in texto


def test_ya_pagado_pedirlo_no_avisa(con_loteo):
    web, base, correo, slug = con_loteo
    base.anotar_pago(slug, "transf. 1")

    respuesta = web.post(f"/api/proyectos/{slug}/habilitacion")

    assert respuesta.status_code == 200
    assert respuesta.json()["habilitacion_pedida"] is None
    assert a(correo, CTP) == []


def test_pedir_la_habilitacion_de_un_loteo_ajeno_da_404(con_loteo):
    web, base, correo, slug = con_loteo
    otra = TestClient(web.app, follow_redirects=False)
    base.crear_cliente("Otra", "otra@otra.cl", "Otra")
    base.cambiar_clave("otra@otra.cl", CLAVE)
    entrar(otra, "otra@otra.cl")

    assert otra.post(f"/api/proyectos/{slug}/habilitacion").status_code == 404
    assert a(correo, CTP) == []
