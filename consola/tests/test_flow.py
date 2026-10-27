"""El pago con tarjeta en Flow, contra el Flow falso de QA (que revisa la firma)."""
import hashlib
import hmac
import time

import pytest
from fastapi.testclient import TestClient

from consola.cobros import Cobros, activa
from consola.flow import Flow, FlowNoResponde, crear_planes, firmar
from consola.tests.test_app import construir_a_mano, crear, entrar, id_de, montar
from qa.flow_falsa import CLAVE, SECRETO, Falsa, levantar


@pytest.fixture
def falsa():
    falsa = Falsa()
    servidor = levantar(falsa)
    yield falsa
    servidor.shutdown()


@pytest.fixture
def consola(tmp_path, falsa, monkeypatch):
    """La consola con pago con tarjeta, Ana (dueña de Los Robles) y CTP."""
    import consola.app as app_mod
    flow = Flow(f"{falsa.base_url}/api", CLAVE, SECRETO)
    original = app_mod.crear_app

    def con_flow(**argumentos):
        return original(cobros=Cobros(base=argumentos["base"], flow=flow), **argumentos)
    monkeypatch.setattr("consola.tests.test_app.crear_app", con_flow)
    app, base, registro, comandos = montar(tmp_path)
    return {"app": app, "base": base, "registro": registro, "flow": flow, "falsa": falsa,
            "ana": entrar(app, "ana@losrobles.cl"), "ctp": entrar(app, "ctp@ctp.cl"),
            "cliente_id": id_de(registro, "ana@losrobles.cl")}


def pagar(c, plan="fly", aprobada=True):
    """Elegir el plan, registrar la tarjeta en Flow y volver a la consola."""
    respuesta = c["ana"].post("/api/plan/flow", json={"plan": plan})
    assert respuesta.status_code == 200, respuesta.text
    url = respuesta.json()["url"]
    token = url.split("token=")[1]
    vuelta = c["falsa"].registrar(token, aprobada)
    assert vuelta.endswith("/api/flow/tarjeta")
    # El navegador vuelve desde flow.cl: sin la galleta de sesión.
    anonimo = TestClient(c["app"], follow_redirects=False)
    return anonimo.post("/api/flow/tarjeta", data={"token": token})


def cliente(c):
    return c["base"].cliente(c["cliente_id"])


# --- la firma ---------------------------------------------------------------------

def test_la_firma_es_la_de_la_documentacion_de_flow():
    parametros = {"apiKey": "XXXX-XXXX-XXXX", "currency": "CLP", "amount": 5000}

    esperada = hmac.new(b"secreto", b"amount5000apiKeyXXXX-XXXX-XXXXcurrencyCLP",
                        hashlib.sha256).hexdigest()

    assert firmar(parametros, "secreto") == esperada


def test_con_otra_clave_flow_contesta_error(falsa):
    flow = Flow(f"{falsa.base_url}/api", CLAVE, "otro-secreto")

    with pytest.raises(FlowNoResponde):
        flow.crear_cliente(nombre="X", email="x@x.cl", externo="x")


# --- pagar con tarjeta --------------------------------------------------------------

def test_sin_flow_configurado_pagar_con_tarjeta_da_503(tmp_path):
    app, _, _, _ = montar(tmp_path)
    ana = entrar(app, "ana@losrobles.cl")

    assert ana.get("/api/sesion").json()["pago_con_tarjeta"] is False
    assert ana.post("/api/plan/flow", json={"plan": "fly"}).status_code == 503


def test_registrar_la_tarjeta_activa_el_plan(consola):
    vuelta = pagar(consola, "pro")

    assert vuelta.status_code == 303
    assert vuelta.headers["location"].endswith("/?plan=listo#/configuracion")
    ana = cliente(consola)
    assert ana.plan == "pro"
    assert ana.flow_tarjeta == "Visa ···· 4242"
    assert ana.flow_suscripcion
    assert ana.plan_nota.startswith("Flow")
    plan = consola["ana"].get("/api/sesion").json()["plan"]
    assert (plan["nombre"], plan["con_tarjeta"], plan["tarjeta"]) == ("Pro", True, "Visa ···· 4242")


def test_con_el_plan_pagado_se_publica(consola):
    slug = crear(consola["ana"])["slug"]
    construir_a_mano(consola["registro"], consola["registro"].salidas, slug)
    pagar(consola, "fly")

    respuesta = consola["ana"].post(f"/api/proyectos/{slug}/publicar", json={"confirmado": True})

    assert respuesta.status_code == 202


def test_una_tarjeta_rechazada_no_activa_nada(consola):
    vuelta = pagar(consola, "fly", aprobada=False)

    assert vuelta.headers["location"].endswith("/?plan=sin-tarjeta#/configuracion")
    assert cliente(consola).plan is None
    assert cliente(consola).flow_suscripcion is None


def test_un_token_inventado_no_activa_nada(consola):
    anonimo = TestClient(consola["app"], follow_redirects=False)

    vuelta = anonimo.post("/api/flow/tarjeta", data={"token": "INVENTADO"})
    pago = anonimo.post("/api/flow/pago", data={"token": "INVENTADO"})

    assert vuelta.headers["location"].endswith("/?plan=error#/configuracion")
    assert pago.status_code == 400
    assert cliente(consola).plan is None


def test_solo_el_duenio_elige_el_plan(consola):
    base = consola["base"]
    base.crear_usuario(consola["cliente_id"], "pia@losrobles.cl", "Pía")
    from consola.tests.test_app import CLAVE as CLAVE_CONSOLA
    base.cambiar_clave("pia@losrobles.cl", CLAVE_CONSOLA)
    pia = entrar(consola["app"], "pia@losrobles.cl")

    assert pia.post("/api/plan/flow", json={"plan": "fly"}).status_code == 403


def test_el_plan_a_la_medida_no_se_paga_con_tarjeta(consola):
    respuesta = consola["ana"].post("/api/plan/flow", json={"plan": "enterprise"})

    assert respuesta.status_code == 409


def test_cambiar_de_plan_con_la_tarjeta_registrada_no_vuelve_a_pedirla(consola):
    pagar(consola, "fly")
    anterior = cliente(consola).flow_suscripcion

    respuesta = consola["ana"].post("/api/plan/flow", json={"plan": "master"})

    assert respuesta.json() == {"cambiado": True}
    assert cliente(consola).plan == "master"
    assert cliente(consola).flow_suscripcion != anterior
    # La anterior queda cancelada en Flow: no se cobran dos planes.
    assert consola["falsa"].estado.suscripciones[anterior]["status"] == 4


def test_un_aviso_sobre_la_suscripcion_anterior_no_quita_el_plan_nuevo(consola):
    pagar(consola, "fly")
    cobros = Cobros(consola["base"], consola["flow"])
    vieja = cliente(consola)
    consola["ana"].post("/api/plan/flow", json={"plan": "pro"})

    # La revisión que empezó antes del cambio contesta con la anterior, ya cancelada.
    cobros._aplicar(vieja, consola["flow"].suscripcion(vieja.flow_suscripcion))

    assert cliente(consola).plan == "pro"
    assert cliente(consola).flow_suscripcion


def test_pedir_el_mismo_plan_que_tiene_da_409(consola):
    pagar(consola, "pro")

    assert consola["ana"].post("/api/plan/flow", json={"plan": "pro"}).status_code == 409


# --- lo que dice Flow después -----------------------------------------------------

def test_cancelar_deja_el_plan_hasta_fin_de_mes(consola):
    pagar(consola, "fly")

    respuesta = consola["ana"].post("/api/plan/flow/cancelar")

    assert respuesta.status_code == 200
    assert respuesta.json()["hasta"]
    assert cliente(consola).plan == "fly"
    assert cliente(consola).flow_hasta == respuesta.json()["hasta"]


def test_cuando_flow_cancela_la_suscripcion_se_quita_el_plan(consola):
    pagar(consola, "fly")
    sid = cliente(consola).flow_suscripcion
    consola["flow"].cancelar(sid, al_final=False)      # p. ej. desde el panel de Flow

    Cobros(consola["base"], consola["flow"]).sincronizar_todas()

    assert cliente(consola).plan is None
    assert cliente(consola).flow_suscripcion is None


def test_una_suscripcion_morosa_quita_el_plan(consola):
    pagar(consola, "pro")
    consola["falsa"].vencer(cliente(consola).flow_suscripcion)

    Cobros(consola["base"], consola["flow"]).sincronizar_todas()

    assert cliente(consola).plan is None
    assert any(e.que == "plan quitado" for e in consola["base"].historial())


def test_un_plan_anotado_a_mano_no_lo_quita_flow(consola):
    pagar(consola, "fly")
    consola["falsa"].vencer(cliente(consola).flow_suscripcion)
    consola["ctp"].post(f"/api/plataforma/clientes/{consola['cliente_id']}/plan",
                        json={"plan": "enterprise", "loteos": 10, "nota_cobro": "factura 9"})

    Cobros(consola["base"], consola["flow"]).sincronizar_todas()

    assert cliente(consola).plan == "enterprise"


def test_el_aviso_de_pago_de_flow_llega_a_la_consola(consola):
    pagar(consola, "fly")
    falsa = consola["falsa"]
    # El primer cobro ya avisó (a nadie: la consola de prueba no tiene puerto). El
    # aviso se manda acá a mano, con un token que Flow sí conoce.
    token = next(iter(falsa.estado.pagos))
    anonimo = TestClient(consola["app"], follow_redirects=False)

    respuesta = anonimo.post("/api/flow/pago", data={"token": token})

    assert respuesta.status_code == 200
    assert respuesta.json() == {"revisadas": 1}


def test_la_tarea_diaria_pide_su_clave(consola, monkeypatch):
    monkeypatch.setenv("CONSOLA_TAREAS_CLAVE", "clave-de-tareas")
    pagar(consola, "fly")
    anonimo = TestClient(consola["app"])

    assert anonimo.post("/api/tareas/flow").status_code == 401
    respuesta = anonimo.post("/api/tareas/flow", headers={"x-tarea-clave": "clave-de-tareas"})
    assert respuesta.json() == {"revisadas": 1}


def test_activa_pide_un_mes_pagado():
    assert activa({"status": 1, "morose": 0, "invoices": [{"status": 1}]})
    assert not activa({"status": 1, "morose": 2, "invoices": [{"status": 0}]})
    assert not activa({"status": 1, "morose": 1, "invoices": [{"status": 1}]})
    assert not activa({"status": 4, "morose": 0, "invoices": [{"status": 1}]})
    assert activa({"status": 2, "morose": 0, "invoices": []})


# --- crear los planes en Flow -------------------------------------------------------

def test_crear_los_planes_no_pisa_los_que_existen(falsa):
    flow = Flow(f"{falsa.base_url}/api", CLAVE, SECRETO)
    del falsa.estado.planes["tumasterplan-master"]
    lineas = []

    crear_planes(flow, "https://consola.tumasterplan.cl", avisar=lineas.append)

    assert [l[0] for l in lineas] == ["=", "=", "+"]
    plan = falsa.estado.planes["tumasterplan-master"]
    assert plan["amount"] == 150000
    assert plan["urlCallback"] == "https://consola.tumasterplan.cl/api/flow/pago"
