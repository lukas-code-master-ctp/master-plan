"""Configuración → Tu cuenta y Equipo: el perfil propio y quién más entra a la loteadora."""
import pytest

from .test_cuentas import (  # noqa: F401  (sin_correo es fixture)
    CLAVE,
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

def test_invitar_crea_la_cuenta_y_manda_el_enlace_para_elegir_contrasena(loteadora):
    web, base, correo, pia, _ = loteadora
    entrar(web, "pia@bosques.cl")

    respuesta = web.post("/api/equipo", json={"nombre": "Rosa", "email": "Rosa@Bosques.cl"})

    assert respuesta.status_code == 201
    assert respuesta.json() == {"email": "rosa@bosques.cl", "invitacion": "correo"}
    rosa = base.usuario_por_email("rosa@bosques.cl")
    assert rosa.cliente_id == pia.cliente_id
    assert rosa.rol == "equipo"
    para, _, texto = correo.enviados[-1]
    assert para == "rosa@bosques.cl"
    assert "Pía Soto" in texto and "Bosques del Sur" in texto
    # Con el enlace elige su contraseña y queda adentro.
    enlace = correo.enlace("rosa@bosques.cl", "/restablecer")
    respuesta = web.post("/restablecer", data={"t": enlace.split("t=")[1], "clave": "una-clave-de-rosa"})
    assert respuesta.status_code == 303
    assert web.get("/api/cuenta").json()["email"] == "rosa@bosques.cl"


def test_sin_correo_la_invitacion_trae_una_contrasena_provisional(sin_correo):  # noqa: F811
    web, base, _ = sin_correo
    base.crear_cuenta_propia("Bosques del Sur", "pia@bosques.cl", "Pía Soto", CLAVE, verificado=True)
    entrar(web, "pia@bosques.cl")

    respuesta = web.post("/api/equipo", json={"nombre": "Rosa", "email": "rosa@bosques.cl"})

    assert respuesta.status_code == 201
    datos = respuesta.json()
    assert datos["invitacion"] == "clave"
    web.cookies.clear()
    entrar(web, "rosa@bosques.cl", datos["clave_provisional"])
    assert web.get("/api/sesion").json()["debe_cambiar_clave"] is True


def test_solo_la_duena_invita(loteadora):
    web, base, *_ = loteadora
    entrar(web, "tomas@bosques.cl")

    respuesta = web.post("/api/equipo", json={"nombre": "Rosa", "email": "rosa@bosques.cl"})

    assert respuesta.status_code == 403
    assert base.usuario_por_email("rosa@bosques.cl") is None


@pytest.mark.parametrize("campos", [{"nombre": "Rosa", "email": "no-es-correo"},
                                    {"nombre": "", "email": "rosa@bosques.cl"}])
def test_una_invitacion_incompleta_no_crea_nada(loteadora, campos):
    web, base, *_ = loteadora
    entrar(web, "pia@bosques.cl")

    assert web.post("/api/equipo", json=campos).status_code == 400
    assert base.usuario_por_email("rosa@bosques.cl") is None


def test_invitar_un_correo_que_ya_tiene_cuenta_avisa(loteadora):
    web, *_ = loteadora
    entrar(web, "pia@bosques.cl")

    assert web.post("/api/equipo", json={"nombre": "Ana", "email": "ana@otra.cl"}).status_code == 409


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
