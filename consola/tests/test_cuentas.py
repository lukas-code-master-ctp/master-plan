"""Cuentas que se crea la propia gente: Regístrate, olvidé mi contraseña y Google."""
import re
import sys
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from consola.acceso import Acceso
from consola.app import crear_app
from consola.cuentas import Cuentas, Google, Limitador
from consola.datos import Base
from consola.disenos import Disenos
from consola.proyectos import Registro
from consola.trabajos import Trabajos

CLAVE = "una-clave-larga-de-prueba"


class CorreoDePrueba:
    def __init__(self):
        self.enviados = []

    def enviar(self, para, asunto, texto):
        self.enviados.append((para, asunto, texto))

    def enlace(self, para, ruta):
        for destino, _, texto in reversed(self.enviados):
            if destino == para:
                encontrado = re.search(rf"http://testserver{ruta}\?t=([\w-]+)", texto)
                if encontrado:
                    return f"{ruta}?t={encontrado.group(1)}"
        raise AssertionError(f"no llegó un enlace {ruta} a {para}")


class HttpDeGoogle:
    """Lo que contestaría Google, sin salir a internet."""

    def __init__(self, sub="g-123", email="pia@bosques.cl", verificado=True, nombre="Pía Soto"):
        self.datos = {"sub": sub, "email": email, "email_verified": verificado, "name": nombre}
        self.canjes = []

    def __call__(self, metodo, url, formulario=None, token=None):
        if url == Google.CANJEAR:
            self.canjes.append(formulario)
            return {"access_token": "acceso"} if formulario["code"] == "bueno" else {}
        assert token == "acceso"
        return self.datos


class ComandosDePrueba:
    def construir(self, proyecto, sin_imagenes=False):
        return [sys.executable, "-c", "print('ok')"]

    def control_de_calce(self, proyecto):
        return [sys.executable, "-c", "print('ok')"]


def montar(tmp_path, http=None, local=True):
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    base.crear_cliente("CompraTuParcela", "ctp@ctp.cl", "CTP")
    base.cambiar_clave("ctp@ctp.cl", CLAVE)
    base.ascender_a_plataforma("ctp@ctp.cl")
    correo = CorreoDePrueba()
    acceso = Acceso(base=base, secreto="un-secreto", local=local)
    app = crear_app(
        registro=Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas"),
        trabajos=Trabajos(), comandos=ComandosDePrueba(), acceso=acceso, base=base,
        disenos=Disenos(base=base, carpeta=tmp_path / "disenos"),
        cuentas=Cuentas(base=base, correo=correo),
        google=Google("cliente", "secreto", http=http) if http else None)
    web = TestClient(app, follow_redirects=False)
    return web, base, correo


@pytest.fixture
def entorno(tmp_path):
    return montar(tmp_path)


def registrarse(web, email="pia@bosques.cl", loteadora="Bosques del Sur", clave=CLAVE, **extra):
    return web.post("/registro", data={"loteadora": loteadora, "nombre": "Pía Soto",
                                       "email": email, "clave": clave, **extra})


# --- Regístrate ---------------------------------------------------------------------

def test_la_pagina_de_entrada_ofrece_registrarse_y_recuperar(entorno):
    web, _, _ = entorno

    pagina = web.get("/entrar").text

    assert 'href="/registro"' in pagina
    assert 'href="/olvide"' in pagina
    # Sin Google configurado, no se ofrece.
    assert "/entrar/google" not in pagina


def test_registrarse_crea_la_cuenta_sin_verificar_y_manda_el_enlace(entorno):
    web, base, correo = entorno

    respuesta = registrarse(web)

    assert respuesta.status_code == 200
    assert "Revisa tu correo" in respuesta.text
    usuario = base.usuario_por_email("pia@bosques.cl")
    assert usuario.email_verificado is False
    assert usuario.rol == "dueño"
    assert base.cliente(usuario.cliente_id).nombre == "Bosques del Sur"
    assert correo.enlace("pia@bosques.cl", "/verificar")


def token_de(correo, para, ruta):
    return correo.enlace(para, ruta).split("t=")[1]


def confirmar(web, correo, para="pia@bosques.cl"):
    return web.post("/verificar", data={"t": token_de(correo, para, "/verificar")})


def test_sin_confirmar_el_correo_no_se_entra_y_se_reenvia_el_enlace(entorno):
    """Si no, cualquiera registra el correo de otro con su clave y espera a que el
    dueño lo confirme para quedar adentro de esa cuenta."""
    web, _, correo = entorno
    registrarse(web)
    antes = len(correo.enviados)

    respuesta = web.post("/entrar", data={"email": "pia@bosques.cl", "clave": CLAVE})

    assert respuesta.status_code == 403
    assert "confirmar tu correo" in respuesta.text
    assert "consola" not in respuesta.cookies
    assert len(correo.enviados) == antes + 1


def test_una_clave_mala_de_una_cuenta_sin_confirmar_no_cuenta_nada(entorno):
    web, _, _ = entorno
    registrarse(web)

    respuesta = web.post("/entrar", data={"email": "pia@bosques.cl", "clave": "no-es-esta-clave"})

    assert respuesta.status_code == 401
    assert "confirmar" not in respuesta.text


def test_el_enlace_pide_un_boton_y_despues_deja_adentro(entorno):
    web, base, correo = entorno
    registrarse(web)

    pagina = web.get(correo.enlace("pia@bosques.cl", "/verificar"))
    respuesta = confirmar(web, correo)

    # Abrir el enlace (o que lo abra el antivirus del correo) no gasta nada.
    assert pagina.status_code == 200
    assert "Confirmar y entrar" in pagina.text
    assert respuesta.status_code == 303
    assert "consola" in respuesta.cookies
    assert base.usuario_por_email("pia@bosques.cl").email_verificado is True
    assert web.get("/api/sesion").json()["quien"] == "pia@bosques.cl"
    assert web.post("/entrar", data={"email": "pia@bosques.cl", "clave": CLAVE}).status_code == 303


def test_el_enlace_de_verificacion_sirve_una_vez(entorno):
    web, _, correo = entorno
    registrarse(web)
    confirmar(web, correo)

    assert confirmar(web, correo).status_code == 400


def test_registrarse_de_nuevo_sin_haber_confirmado_reenvia_el_enlace(entorno):
    web, _, correo = entorno
    registrarse(web)

    registrarse(web)

    assert [asunto for _, asunto, _ in correo.enviados] == ["Confirma tu correo en Tu Masterplan"] * 2


def test_registrarse_con_un_correo_que_ya_existe_no_lo_cuenta(entorno):
    """La pantalla es la misma; la diferencia llega solo al buzón del dueño."""
    web, base, correo = entorno

    respuesta = registrarse(web, email="ctp@ctp.cl")

    assert respuesta.status_code == 200
    assert "Revisa tu correo" in respuesta.text
    assert base.usuario_por_email("ctp@ctp.cl").rol == "plataforma"
    assert "Ya tienes una cuenta" in correo.enviados[-1][1]


def test_dos_loteadoras_pueden_llamarse_igual(entorno):
    web, base, _ = entorno
    registrarse(web, email="a@a.cl", loteadora="Los Robles")

    registrarse(web, email="b@b.cl", loteadora="Los Robles")

    slugs = {base.cliente(base.usuario_por_email(e).cliente_id).slug for e in ("a@a.cl", "b@b.cl")}
    assert slugs == {"los-robles", "los-robles-2"}


@pytest.mark.parametrize("campos,mensaje", [
    ({"loteadora": ""}, "loteadora"),
    ({"email": "no-es-correo"}, "correo"),
    ({"clave": "corta"}, "10 caracteres"),
])
def test_un_registro_invalido_explica_por_que_y_conserva_lo_escrito(entorno, campos, mensaje):
    web, _, correo = entorno

    respuesta = registrarse(web, **campos)

    assert respuesta.status_code == 400
    assert mensaje in respuesta.text
    assert "Pía Soto" in respuesta.text
    assert correo.enviados == []


def test_lo_escrito_se_devuelve_escapado(entorno):
    web, _, _ = entorno

    respuesta = registrarse(web, loteadora='"><script>alert(1)</script>', clave="corta")

    assert "<script>alert(1)" not in respuesta.text
    assert "&lt;script&gt;" in respuesta.text


def test_un_robot_que_llena_la_trampa_no_crea_nada(entorno):
    web, base, correo = entorno

    respuesta = registrarse(web, sitio="https://spam.example")

    assert "Revisa tu correo" in respuesta.text
    assert base.usuario_por_email("pia@bosques.cl") is None
    assert correo.enviados == []


def test_el_tope_cuenta_por_conexion():
    limitador = Limitador(maximo=2, segundos=3600)
    assert limitador.permitir("1.2.3.4") and limitador.permitir("1.2.3.4")
    assert not limitador.permitir("1.2.3.4")
    assert limitador.permitir("5.6.7.8")


def test_el_tope_no_crece_sin_limite():
    limitador = Limitador(maximo=1, segundos=3600)
    limitador.TOPE_DE_CLAVES = 10

    for i in range(50):
        limitador.permitir(f"10.0.0.{i}")

    assert len(limitador._marcas) <= 10


def test_los_correos_a_un_mismo_buzon_tienen_tope(entorno):
    """Cambiar de IP no deja llenar de correos el buzón de alguien."""
    web, _, correo = entorno

    for _ in range(5):
        web.post("/olvide", data={"email": "ctp@ctp.cl"})

    assert len(correo.enviados) == 3


def test_desplegada_la_ip_es_la_que_agrega_el_balanceador(tmp_path):
    from starlette.requests import Request

    from consola.rutas_cuentas import ip_de
    peticion = Request({"type": "http", "headers": [(b"x-forwarded-for", b"6.6.6.6, 1.2.3.4")],
                        "client": ("10.0.0.1", 1234)})

    assert ip_de(peticion, local=False) == "1.2.3.4"
    assert ip_de(peticion, local=True) == "10.0.0.1"


def test_desplegada_sin_consola_url_no_arma_enlaces_con_la_peticion(tmp_path, monkeypatch):
    """Si no, cambiando la cabecera Host alguien haría llegar el enlace de
    restablecer de otro apuntando a su propio dominio."""
    monkeypatch.delenv("CONSOLA_URL", raising=False)
    web, _, correo = montar(tmp_path, local=False)

    respuesta = web.post("/olvide", data={"email": "ctp@ctp.cl"}, headers={"host": "malo.example"})

    assert respuesta.status_code == 503
    assert correo.enviados == []


def test_con_consola_url_los_enlaces_salen_de_ahi(tmp_path, monkeypatch):
    monkeypatch.setenv("CONSOLA_URL", "https://app.tumasterplan.cl/")
    web, _, correo = montar(tmp_path, local=False)

    web.post("/olvide", data={"email": "ctp@ctp.cl"}, headers={"host": "malo.example"})

    assert "https://app.tumasterplan.cl/restablecer?t=" in correo.enviados[-1][2]


def test_un_nombre_con_saltos_de_linea_queda_en_una_linea():
    from consola.cuentas import validar_registro

    datos = validar_registro({"loteadora": "Robles\n\nPaga en https://malo.cl", "nombre": "Ana\r\nX",
                              "email": "a@a.cl", "clave": CLAVE})

    assert datos.loteadora == "Robles Paga en https://malo.cl"
    assert datos.nombre == "Ana X"


def test_los_correos_no_llevan_el_nombre_que_escribio_quien_se_registro(entorno):
    web, _, correo = entorno

    registrarse(web, email="victima@x.cl", nombre="Tu cuenta fue suspendida")

    assert "suspendida" not in correo.enviados[-1][2]


def test_el_formulario_se_frena_despues_de_varios_intentos(entorno):
    web, _, _ = entorno

    estados = [registrarse(web, email=f"p{i}@x.cl").status_code for i in range(6)]

    assert estados[:5] == [200] * 5
    assert estados[5] == 429


# --- olvidé mi contraseña --------------------------------------------------------------

def test_restablecer_la_clave_por_correo(entorno):
    web, _, correo = entorno

    web.post("/olvide", data={"email": "ctp@ctp.cl"})
    enlace = correo.enlace("ctp@ctp.cl", "/restablecer")
    formulario = web.get(enlace)
    token = enlace.split("t=")[1]
    cambio = web.post("/restablecer", data={"t": token, "clave": "otra-clave-nueva"})

    assert formulario.status_code == 200
    assert cambio.status_code == 303
    assert web.post("/entrar", data={"email": "ctp@ctp.cl", "clave": CLAVE}).status_code == 401
    assert web.post("/entrar", data={"email": "ctp@ctp.cl", "clave": "otra-clave-nueva"}).status_code == 303


def test_pedir_restablecer_un_correo_sin_cuenta_contesta_lo_mismo(entorno):
    web, _, correo = entorno

    con_cuenta = web.post("/olvide", data={"email": "ctp@ctp.cl"})
    sin_cuenta = web.post("/olvide", data={"email": "nadie@nada.cl"})

    assert con_cuenta.text == sin_cuenta.text
    assert [c[0] for c in correo.enviados] == ["ctp@ctp.cl"]


def test_el_enlace_de_restablecer_sirve_una_vez(entorno):
    web, _, correo = entorno
    web.post("/olvide", data={"email": "ctp@ctp.cl"})
    token = correo.enlace("ctp@ctp.cl", "/restablecer").split("t=")[1]
    web.post("/restablecer", data={"t": token, "clave": "otra-clave-nueva"})

    otra_vez = web.post("/restablecer", data={"t": token, "clave": "y-otra-mas-larga"})

    assert otra_vez.status_code == 400
    assert web.post("/entrar", data={"email": "ctp@ctp.cl", "clave": "otra-clave-nueva"}).status_code == 303


def test_restablecer_corta_las_sesiones_abiertas(entorno):
    web, _, correo = entorno
    otra = TestClient(web.app, follow_redirects=False)
    otra.post("/entrar", data={"email": "ctp@ctp.cl", "clave": CLAVE})
    assert otra.get("/api/sesion").status_code == 200

    web.post("/olvide", data={"email": "ctp@ctp.cl"})
    token = correo.enlace("ctp@ctp.cl", "/restablecer").split("t=")[1]
    web.post("/restablecer", data={"t": token, "clave": "otra-clave-nueva"})

    assert otra.get("/api/sesion").status_code == 401


def test_un_enlace_inventado_no_sirve(entorno):
    web, _, _ = entorno

    assert web.post("/restablecer", data={"t": "inventado", "clave": "otra-clave-nueva"}).status_code == 400
    assert web.post("/verificar", data={"t": "inventado"}).status_code == 400


def test_una_clave_corta_no_gasta_el_enlace(entorno):
    web, _, correo = entorno
    web.post("/olvide", data={"email": "ctp@ctp.cl"})
    token = correo.enlace("ctp@ctp.cl", "/restablecer").split("t=")[1]

    corta = web.post("/restablecer", data={"t": token, "clave": "corta"})
    buena = web.post("/restablecer", data={"t": token, "clave": "otra-clave-nueva"})

    assert corta.status_code == 400
    assert buena.status_code == 303


def test_la_base_guarda_el_hash_del_token_y_no_el_token(entorno):
    web, base, correo = entorno
    web.post("/olvide", data={"email": "ctp@ctp.cl"})
    token = correo.enlace("ctp@ctp.cl", "/restablecer").split("t=")[1]

    from sqlalchemy import text
    with base.motor.connect() as con:
        guardados = [f[0] for f in con.execute(text("SELECT hash FROM tokens"))]

    assert token not in guardados
    assert len(guardados) == 1


# --- Google ----------------------------------------------------------------------------

def ir_y_volver(web, codigo="bueno"):
    ida = web.get("/entrar/google")
    estado = parse_qs(urlparse(ida.headers["location"]).query)["state"][0]
    return web.get(f"/entrar/google/vuelta?code={codigo}&state={estado}")


def test_con_google_configurado_se_ofrece_en_la_entrada(tmp_path):
    web, _, _ = montar(tmp_path, http=HttpDeGoogle())

    assert 'href="/entrar/google"' in web.get("/entrar").text


def test_la_ida_a_google_lleva_estado_y_vuelta(tmp_path):
    web, _, _ = montar(tmp_path, http=HttpDeGoogle())

    ida = web.get("/entrar/google")

    destino = urlparse(ida.headers["location"])
    consulta = parse_qs(destino.query)
    assert destino.netloc == "accounts.google.com"
    assert consulta["redirect_uri"] == ["http://testserver/entrar/google/vuelta"]
    assert consulta["state"][0]


def test_alguien_nuevo_con_google_elige_su_loteadora_y_entra(tmp_path):
    web, base, _ = montar(tmp_path, http=HttpDeGoogle())

    vuelta = ir_y_volver(web)
    formulario = web.get("/registro/google")
    alta = web.post("/registro/google", data={"loteadora": "Bosques del Sur"})

    assert vuelta.headers["location"] == "/registro/google"
    assert "pia@bosques.cl" in formulario.text
    assert alta.status_code == 303
    usuario = base.usuario_por_email("pia@bosques.cl")
    assert usuario.email_verificado is True
    assert base.usuario_por_identidad("google", "g-123").id == usuario.id
    assert web.get("/api/sesion").json()["quien"] == "pia@bosques.cl"


def test_la_segunda_vez_con_google_entra_directo(tmp_path):
    web, _, _ = montar(tmp_path, http=HttpDeGoogle())
    ir_y_volver(web)
    web.post("/registro/google", data={"loteadora": "Bosques del Sur"})
    web.cookies.clear()

    vuelta = ir_y_volver(web)

    assert vuelta.status_code == 303
    assert vuelta.headers["location"] == "/#/planos"


def test_google_con_el_correo_de_una_cuenta_existente_la_enlaza(tmp_path):
    web, base, _ = montar(tmp_path, http=HttpDeGoogle(sub="g-ctp", email="ctp@ctp.cl"))

    vuelta = ir_y_volver(web)

    assert vuelta.headers["location"] == "/#/planos"
    assert base.usuario_por_identidad("google", "g-ctp").email == "ctp@ctp.cl"
    assert web.get("/api/sesion").json()["rol"] == "plataforma"


def test_google_le_quita_la_cuenta_a_quien_registro_un_correo_ajeno(tmp_path):
    """El atacante registra el correo de la víctima con su clave y no puede
    confirmarlo. Cuando la víctima entra con Google, esa clave deja de servir."""
    web, base, _ = montar(tmp_path, http=HttpDeGoogle(sub="g-victima", email="victima@x.cl"))
    atacante = TestClient(web.app, follow_redirects=False)
    registrarse(atacante, email="victima@x.cl")

    vuelta = ir_y_volver(web)

    assert vuelta.headers["location"] == "/#/planos"
    assert base.usuario_por_email("victima@x.cl").email_verificado is True
    assert atacante.post("/entrar", data={"email": "victima@x.cl", "clave": CLAVE}).status_code == 401


def test_un_correo_de_google_sin_verificar_no_enlaza_nada(tmp_path):
    web, base, _ = montar(tmp_path, http=HttpDeGoogle(email="ctp@ctp.cl", verificado=False))

    vuelta = ir_y_volver(web)

    assert vuelta.status_code == 400
    assert base.usuario_por_identidad("google", "g-123") is None


def test_una_vuelta_sin_la_ida_de_este_navegador_no_entra(tmp_path):
    web, _, _ = montar(tmp_path, http=HttpDeGoogle())

    respuesta = web.get("/entrar/google/vuelta?code=bueno&state=inventado")

    assert respuesta.status_code == 400
    assert "consola" not in web.cookies


def test_un_codigo_que_google_no_acepta_no_entra(tmp_path):
    web, _, _ = montar(tmp_path, http=HttpDeGoogle())

    respuesta = ir_y_volver(web, codigo="malo")

    assert respuesta.status_code == 400


def test_sin_google_configurado_la_ruta_no_existe(entorno):
    web, _, _ = entorno

    assert web.get("/entrar/google").status_code == 404


def test_el_alta_con_google_sin_pasar_por_google_no_crea_nada(entorno):
    web, base, _ = entorno

    respuesta = web.post("/registro/google", data={"loteadora": "Trucha"})

    assert respuesta.status_code == 400
    assert len(base.clientes()) == 1
