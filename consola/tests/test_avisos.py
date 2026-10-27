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


# --- planes ---------------------------------------------------------------------------

def test_pedir_un_plan_le_dice_a_ctp_cual(con_loteo):
    web, base, correo, slug = con_loteo

    respuesta = web.post(f"/api/proyectos/{slug}/habilitacion", json={"plan": "pro"})

    assert respuesta.status_code == 200
    [(asunto, texto)] = a(correo, CTP)
    assert asunto == "Pide el plan Pro: Bosques del Sur"
    assert "eligió el plan Pro" in texto
    assert base.cliente(base.proyecto(slug).cliente_id).plan_pedido == "pro"


def test_cambiar_el_plan_pedido_vuelve_a_avisar(con_loteo):
    web, _, correo, slug = con_loteo

    web.post(f"/api/proyectos/{slug}/habilitacion", json={"plan": "fly"})
    web.post(f"/api/proyectos/{slug}/habilitacion", json={"plan": "fly"})
    web.post(f"/api/proyectos/{slug}/habilitacion", json={"plan": "master"})

    assert [asunto for asunto, _ in a(correo, CTP)] == [
        "Pide el plan Fly: Bosques del Sur", "Pide el plan Master: Bosques del Sur"]


def test_pedir_un_plan_que_no_existe_da_400(con_loteo):
    web, _, correo, slug = con_loteo

    assert web.post(f"/api/proyectos/{slug}/habilitacion", json={"plan": "gratis"}).status_code == 400
    assert a(correo, CTP) == []


def test_asignar_un_plan_le_avisa_a_la_loteadora(con_loteo):
    web, base, correo, slug = con_loteo
    ctp = TestClient(web.app, follow_redirects=False)
    entrar(ctp, CTP)
    cliente_id = base.proyecto(slug).cliente_id

    respuesta = ctp.post(f"/api/plataforma/clientes/{cliente_id}/plan",
                         json={"plan": "pro", "nota_cobro": "factura 77"})
    # Corregir la nota del mismo plan no manda otro correo.
    ctp.post(f"/api/plataforma/clientes/{cliente_id}/plan",
             json={"plan": "pro", "nota_cobro": "factura 77, pagada"})

    assert respuesta.status_code == 200, respuesta.text
    [(asunto, texto)] = a(correo, "pia@bosques.cl")
    assert asunto == "Tu plan Pro está activo"
    assert "3 loteos en línea a la vez" in texto


# --- el plan de la landing y los vencimientos -----------------------------------------

def test_la_cuenta_nueva_cuenta_que_plan_le_intereso_en_la_landing(tmp_path):
    web, _, correo = montar(tmp_path)
    registrarse(web, plan="master")

    confirmar(web, correo)

    [(_, texto)] = a(correo, CTP)
    assert "Llegó desde la landing eligiendo el plan Master." in texto


def plan_que_vence(tmp_path):
    from datetime import date

    from consola.avisos import Avisos

    web, base, correo = montar(tmp_path)
    registrarse(web)
    confirmar(web, correo)
    cliente_id = base.usuario_por_email("pia@bosques.cl").cliente_id
    correo.enviados.clear()
    return Avisos(base=base, correo=correo, en_segundo_plano=False), cliente_id, correo, date


def test_el_recordatorio_dice_hasta_cuando_y_a_quien_escribir(tmp_path):
    avisos, cliente_id, correo, date = plan_que_vence(tmp_path)

    avisos.plan_por_vencer(cliente_id=cliente_id, plan="Pro", hasta=date(2026, 11, 30))

    [(asunto, texto)] = a(correo, "pia@bosques.cl")
    assert asunto == "Tu plan Pro vence el 30/11/2026"
    assert "escríbenos a" in texto and "7 días después" in texto
    [(asunto, _)] = a(correo, CTP)
    assert asunto == "Vence el plan Pro: Bosques del Sur"


def test_al_vencer_dice_el_dia_en_que_se_bajan(tmp_path):
    avisos, cliente_id, correo, date = plan_que_vence(tmp_path)

    avisos.plan_vencido(cliente_id=cliente_id, plan="Pro", hasta=date(2026, 11, 30),
                        bajada=date(2026, 12, 8))

    [(asunto, texto)] = a(correo, "pia@bosques.cl")
    assert asunto == "Venció tu plan Pro"
    assert "hasta el 08/12/2026" in texto
    assert len(a(correo, CTP)) == 1


def test_al_bajarlos_dice_que_los_masters_siguen(tmp_path):
    avisos, cliente_id, correo, _ = plan_que_vence(tmp_path)

    avisos.plan_bajado(cliente_id=cliente_id, plan="Pro")

    [(asunto, texto)] = a(correo, "pia@bosques.cl")
    assert asunto == "Tus loteos se bajaron del aire"
    assert "masters siguen guardados" in texto
    [(asunto, _)] = a(correo, CTP)
    assert asunto == "Sitios bajados: Bosques del Sur"
