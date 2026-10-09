"""Configuración → Reservas y contacto: lo que la loteadora deja fijado para sus masters."""
import pytest

from .test_reservas import consola, solicitar  # noqa: F401  (consola es fixture)


def preferencias(c, quien="ana"):
    return c[quien].get("/api/preferencias")


def cambiar(c, quien="ana", **campos):
    return c[quien].patch("/api/preferencias", json=campos)


def test_sin_cambiar_nada_son_dos_horas_sin_whatsapp_ni_diseno(consola):  # noqa: F811
    assert preferencias(consola).json() == {"whatsapp": "", "diseno_id": None, "horas_apartado": 2,
                                            "administra": True}


def test_el_whatsapp_se_guarda_como_lo_pide_wa_me(consola):  # noqa: F811
    respuesta = cambiar(consola, whatsapp="+56 9 1234 5678", horas_apartado=24)

    assert respuesta.status_code == 200
    assert respuesta.json()["whatsapp"] == "56912345678"
    assert preferencias(consola).json()["horas_apartado"] == 24


@pytest.mark.parametrize("campos", [{"horas_apartado": 0}, {"horas_apartado": 49},
                                    {"horas_apartado": "dos"}, {"whatsapp": "123"}])
def test_lo_que_no_sirve_no_se_guarda(consola, campos):  # noqa: F811
    assert cambiar(consola, **campos).status_code == 400
    assert preferencias(consola).json()["horas_apartado"] == 2


def test_un_whatsapp_vacio_lo_quita(consola):  # noqa: F811
    cambiar(consola, whatsapp="56912345678")

    assert cambiar(consola, whatsapp="").json()["whatsapp"] == ""


def test_el_diseno_por_defecto_es_uno_propio(consola):  # noqa: F811
    propio = consola["ana"].post("/api/disenos", json={"nombre": "Marca", "color": "#166534"}).json()["id"]
    ajeno = consola["luis"].post("/api/disenos", json={"nombre": "Otra", "color": "#1d4ed8"}).json()["id"]

    assert cambiar(consola, diseno_id=ajeno).status_code == 404
    assert cambiar(consola, diseno_id=propio).json()["diseno_id"] == propio


def test_borrar_el_diseno_por_defecto_lo_deja_sin_diseno(consola):  # noqa: F811
    propio = consola["ana"].post("/api/disenos", json={"nombre": "Marca", "color": "#166534"}).json()["id"]
    cambiar(consola, diseno_id=propio)

    consola["ana"].delete(f"/api/disenos/{propio}")

    assert preferencias(consola).json()["diseno_id"] is None


def test_solo_el_dueno_las_cambia(consola):  # noqa: F811
    base = consola["base"]
    ana = base.usuario_por_email("ana@losrobles.cl")
    base.crear_usuario(ana.cliente_id, "pepe@losrobles.cl", "Pepe")
    base.cambiar_clave("pepe@losrobles.cl", "una-clave-larga-1")
    pepe = consola["publico"].__class__(consola["app"], follow_redirects=False)
    pepe.post("/entrar", data={"email": "pepe@losrobles.cl", "clave": "una-clave-larga-1"})

    assert pepe.get("/api/preferencias").json()["administra"] is False
    assert pepe.patch("/api/preferencias", json={"horas_apartado": 12}).status_code == 403


def test_la_sesion_trae_las_preferencias(consola):  # noqa: F811
    cambiar(consola, horas_apartado=6)

    assert consola["ana"].get("/api/sesion").json()["preferencias"]["horas_apartado"] == 6


# --- dónde se usan ---------------------------------------------------------------------

def test_un_master_nuevo_nace_con_el_whatsapp_de_la_loteadora(consola):  # noqa: F811
    cambiar(consola, whatsapp="56912345678")

    nuevo = consola["ana"].post("/api/proyectos", json={"nombre": "Los Olmos"}).json()

    assert nuevo["whatsapp"] == "56912345678"


def test_la_reserva_queda_apartada_las_horas_que_eligio_la_loteadora(consola):  # noqa: F811
    cambiar(consola, horas_apartado=24)

    respuesta = solicitar(consola)

    assert respuesta.json()["apartada_hasta"] == "2026-10-07T15:00:00+00:00"
    (correo,) = consola["correo"].enviados
    assert "24 horas" in correo["texto"]
