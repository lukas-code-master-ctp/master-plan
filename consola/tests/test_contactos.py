"""El formulario de contacto de la landing: llega a la consola y lo ve el equipo de CTP."""
from datetime import datetime, timezone
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from consola.acceso import Acceso
from consola.app import crear_app
from consola.contactos import Contactos, ContactoInvalido, leer_contacto
from consola.datos import Base
from consola.disenos import Disenos
from consola.kmzs import RegistroKmz
from consola.proyectos import Registro
from consola.tests.test_app import CLAVE, ComandosDePrueba, entrar
from consola.tests.test_reservas import CorreoDePrueba
from consola.trabajos import Trabajos

LANDING = "https://www.tumasterplan.cl"
FORMULARIO = {"nombre": "Marta Soto", "email": "marta@loteos.cl", "telefono": "9 8765 4321",
              "loteadora": "Loteos del Sur", "plan": "pro", "parcelas": "120", "vuelo": "si",
              "mensaje": "Tenemos dos loteos en Chillán.\nQueremos partir con uno."}


def montar(tmp_path, *, local=False):
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    for nombre, email in (("CompraTuParcela", "ctp@ctp.cl"), ("Los Robles", "ana@losrobles.cl")):
        base.crear_cliente(nombre, email, nombre)
        base.cambiar_clave(email, CLAVE)
    base.ascender_a_plataforma("ctp@ctp.cl")
    registro = Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas")
    correo = CorreoDePrueba()
    contactos = Contactos(base=base, correo=correo, en_segundo_plano=False,
                          ahora=lambda: datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc))
    app = crear_app(registro=registro, trabajos=Trabajos(), comandos=ComandosDePrueba(),
                    acceso=Acceso(base=base, secreto="un-secreto", local=local), base=base,
                    disenos=Disenos(base=base, carpeta=tmp_path / "disenos"), google=None, cierra=None,
                    kmzs=RegistroKmz(base=base, carpeta=tmp_path / "kmz", limites=registro.limites),
                    contactos=contactos)
    return app, contactos, correo


@pytest.fixture
def consola(tmp_path):
    app, contactos, correo = montar(tmp_path)
    return {"app": app, "contactos": contactos, "correo": correo,
            "publico": TestClient(app, headers={"origin": LANDING}, follow_redirects=False)}


def enviar(cliente, **cambios):
    """Como lo manda el navegador: un formulario HTML, sin JavaScript."""
    campos = {**FORMULARIO, **cambios}
    return cliente.post("/api/publico/contacto", content=urlencode(campos),
                        headers={"content-type": "application/x-www-form-urlencoded"})


# --- desde la landing -------------------------------------------------------------------

def test_un_mensaje_valido_queda_guardado_y_vuelve_a_la_landing_con_las_gracias(consola):
    respuesta = enviar(consola["publico"])

    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == f"{LANDING}/#contacto-enviado"
    [guardado] = consola["contactos"].listar()
    assert (guardado.nombre, guardado.email, guardado.plan, guardado.vuelo, guardado.parcelas) == (
        "Marta Soto", "marta@loteos.cl", "pro", True, 120)
    assert guardado.telefono == "56987654321"
    assert guardado.estado == "nuevo"


def test_el_equipo_de_ctp_recibe_un_correo_y_la_loteadora_no(consola):
    enviar(consola["publico"])

    assert [c["para"] for c in consola["correo"].enviados] == ["ctp@ctp.cl"]
    assert "Marta Soto" in consola["correo"].enviados[0]["texto"]


def test_el_campo_trampa_contesta_como_si_nada_pero_no_guarda(consola):
    respuesta = enviar(consola["publico"], sitio="https://spam.example")

    assert respuesta.headers["location"] == f"{LANDING}/#contacto-enviado"
    assert consola["contactos"].listar() == []
    assert consola["correo"].enviados == []


def test_un_correo_que_no_sirve_vuelve_con_el_error_y_no_guarda(consola):
    respuesta = enviar(consola["publico"], email="no-es-correo")

    assert respuesta.status_code == 303
    assert respuesta.headers["location"] == f"{LANDING}/#contacto-error"
    assert consola["contactos"].listar() == []


def test_desde_otro_sitio_no_se_acepta(consola):
    ajeno = TestClient(consola["app"], headers={"origin": "https://otro.cl"}, follow_redirects=False)

    respuesta = enviar(ajeno)

    assert respuesta.status_code == 403
    assert consola["contactos"].listar() == []


def test_sin_origen_vuelve_a_la_landing_y_no_a_donde_diga_la_peticion(consola):
    sin_origen = TestClient(consola["app"], follow_redirects=False)

    respuesta = enviar(sin_origen)

    assert respuesta.headers["location"] == f"{LANDING}/#contacto-enviado"


def test_un_cuerpo_enorme_no_se_lee_entero(consola):
    respuesta = enviar(consola["publico"], mensaje="a" * 40_000)

    assert respuesta.headers["location"] == f"{LANDING}/#contacto-error"
    assert consola["contactos"].listar() == []


def test_tope_por_ip(consola):
    respuestas = [enviar(consola["publico"], email=f"m{i}@loteos.cl") for i in range(6)]

    assert [r.headers["location"].rsplit("-", 1)[1] for r in respuestas] == ["enviado"] * 5 + ["error"]
    assert len(consola["contactos"].listar()) == 5


def test_en_local_acepta_la_landing_servida_en_localhost(tmp_path):
    app, contactos, _ = montar(tmp_path, local=True)
    local = TestClient(app, headers={"origin": "http://127.0.0.1:8770"}, follow_redirects=False)

    respuesta = enviar(local)

    assert respuesta.headers["location"] == "http://127.0.0.1:8770/#contacto-enviado"
    assert len(contactos.listar()) == 1


# --- lo que se revisa de cada campo -----------------------------------------------------

def test_solo_nombre_y_correo_son_obligatorios():
    datos = leer_contacto({"nombre": "Marta", "email": "marta@loteos.cl"})

    assert (datos["telefono"], datos["loteadora"], datos["plan"], datos["vuelo"], datos["parcelas"],
            datos["mensaje"]) == ("", "", "no-se", False, None, "")


@pytest.mark.parametrize("cambios", [{"nombre": "M"}, {"email": "marta@"}, {"telefono": "123"},
                                     {"parcelas": "muchas"}, {"parcelas": "0"}])
def test_lo_que_no_sirve_se_rechaza(cambios):
    with pytest.raises(ContactoInvalido):
        leer_contacto({**FORMULARIO, **cambios})


def test_un_plan_que_no_existe_queda_como_aun_no_se():
    assert leer_contacto({**FORMULARIO, "plan": "gratis-para-siempre"})["plan"] == "no-se"


def test_el_mensaje_guarda_sus_parrafos_pero_no_caracteres_de_control():
    mensaje = leer_contacto({**FORMULARIO, "mensaje": "Hola\r\n\r\n\r\n\r\nChao\x00\x1b[31m"})["mensaje"]

    assert mensaje == "Hola\n\nChao[31m"


def test_los_textos_de_una_linea_no_cuelan_saltos(consola):
    datos = leer_contacto({**FORMULARIO, "nombre": "Marta\nAsunto: falso", "loteadora": "A\r\nB"})

    assert "\n" not in datos["nombre"] and "\n" not in datos["loteadora"]


# --- en la consola, solo el equipo de CTP -----------------------------------------------

def test_ctp_ve_los_mensajes_y_los_marca_atendidos(consola):
    enviar(consola["publico"])
    ctp = entrar(consola["app"], "ctp@ctp.cl")

    [mensaje] = ctp.get("/api/plataforma/contactos").json()
    respuesta = ctp.post(f"/api/plataforma/contactos/{mensaje['id']}/estado", json={"estado": "atendido"})

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "atendido"
    assert ctp.get("/api/plataforma/contactos").json()[0]["estado"] == "atendido"


def test_un_estado_que_no_existe_se_rechaza(consola):
    enviar(consola["publico"])
    ctp = entrar(consola["app"], "ctp@ctp.cl")
    [mensaje] = ctp.get("/api/plataforma/contactos").json()

    assert ctp.post(f"/api/plataforma/contactos/{mensaje['id']}/estado",
                    json={"estado": "borrado"}).status_code == 400


def test_un_mensaje_que_no_existe_da_404(consola):
    ctp = entrar(consola["app"], "ctp@ctp.cl")

    assert ctp.post("/api/plataforma/contactos/999/estado", json={"estado": "atendido"}).status_code == 404


def test_una_loteadora_no_ve_los_mensajes(consola):
    enviar(consola["publico"])
    ana = entrar(consola["app"], "ana@losrobles.cl")

    assert ana.get("/api/plataforma/contactos").status_code == 403
