"""Solicitudes de reserva: el sitio publicado aparta una parcela y la loteadora se entera."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from consola.acceso import Acceso
from consola.app import crear_app
from consola.datos import Base
from consola.disenos import Disenos
from consola.kmzs import RegistroKmz
from consola.proyectos import Registro
from consola.reservas import Reservas
from consola.tests.test_app import CLAVE, ComandosDePrueba, entrar
from consola.trabajos import Trabajos

COMPRADOR = {"nombre": "Pedro Pérez", "telefono": "+56 9 8765 4321", "email": "pedro@correo.cl"}


class CorreoDePrueba:
    puede_enviar = True

    def __init__(self):
        self.enviados = []

    def enviar(self, para, asunto, texto):
        self.enviados.append({"para": para, "asunto": asunto, "texto": texto})


class Reloj:
    def __init__(self):
        self.ahora = datetime(2026, 10, 6, 15, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.ahora


@pytest.fixture
def consola(tmp_path):
    """Dos loteadoras; Ana tiene un loteo publicado con dos parcelas, una en venta."""
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    for nombre, email in (("CompraTuParcela", "ctp@ctp.cl"), ("Los Robles", "ana@losrobles.cl"),
                          ("Del Valle", "luis@delvalle.cl")):
        base.crear_cliente(nombre, email, nombre)
        base.cambiar_clave(email, CLAVE)
    base.ascender_a_plataforma("ctp@ctp.cl")
    registro = Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas")
    correo, reloj = CorreoDePrueba(), Reloj()
    reservas = Reservas(base=base, correo=correo, ahora=reloj, en_segundo_plano=False)
    app = crear_app(registro=registro, trabajos=Trabajos(), comandos=ComandosDePrueba(),
                    acceso=Acceso(base=base, secreto="un-secreto", local=False), base=base,
                    disenos=Disenos(base=base, carpeta=tmp_path / "disenos"), google=None, cierra=None,
                    kmzs=RegistroKmz(base=base, carpeta=tmp_path / "kmz", limites=registro.limites),
                    reservas=reservas)
    ana, luis = entrar(app, "ana@losrobles.cl"), entrar(app, "luis@delvalle.cl")
    slug = ana.post("/api/proyectos", json={"nombre": "Praderas"}).json()["slug"]
    ana.patch(f"/api/proyectos/{slug}", json={"link_reserva": "https://pago.cl/reserva"})
    datos = registro.salidas / slug / "sitio" / "datos"
    datos.mkdir(parents=True)
    (datos / "parcelas.json").write_text(json.dumps({"resumen": {"total": 2, "por_estado": {"disponible": 1, "vendido": 1}}, "parcelas": [
        {"id": "1-7", "estado": "disponible"}, {"id": "1-8", "estado": "vendido"}]}))
    (datos / "vistas.json").write_text(json.dumps({"vistas": []}))
    base.anotar_publicacion(slug, f"masterplan-{slug}", f"https://masterplan-{slug}.vercel.app")
    publico = TestClient(app, headers={"origin": f"https://masterplan-{slug}.vercel.app"})
    return {"publico": publico, "ana": ana, "luis": luis, "slug": slug, "correo": correo,
            "reloj": reloj, "registro": registro, "base": base, "app": app}


def entrar_como_ctp(consola):
    return entrar(consola["app"], "ctp@ctp.cl")


def solicitar(c, parcela="1-7", **cambios):
    # Como lo manda el visor: texto plano, para que el navegador no pida permiso antes.
    cuerpo = {"loteo": c["slug"], "parcela": parcela, **COMPRADOR, **cambios}
    return c["publico"].post("/api/publico/reservas", content=json.dumps(cuerpo),
                             headers={"content-type": "text/plain"})


def apartadas(c):
    return c["publico"].get("/api/publico/apartadas", params={"loteo": c["slug"]})


# --- pedir una reserva -------------------------------------------------------------

def test_una_solicitud_aparta_la_parcela_por_dos_horas_y_devuelve_el_link_de_pago(consola):
    respuesta = solicitar(consola)

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["link"] == "https://pago.cl/reserva?parcela=1-7"
    assert respuesta.json()["apartada_hasta"] == "2026-10-06T17:00:00+00:00"
    # El sitio publicado puede leer la respuesta.
    assert respuesta.headers["access-control-allow-origin"] == f"https://masterplan-{consola['slug']}.vercel.app"
    assert apartadas(consola).json() == {"1-7": "2026-10-06T17:00:00+00:00"}


def test_la_loteadora_recibe_un_correo_con_la_parcela_y_el_comprador(consola):
    solicitar(consola)

    (correo,) = consola["correo"].enviados
    assert correo["para"] == "ana@losrobles.cl"
    assert "Parcela 1-7" in correo["asunto"] and "Praderas" in correo["asunto"]
    for dato in ("Pedro Pérez", "56987654321", "pedro@correo.cl", "2 horas"):
        assert dato in correo["texto"]


def test_sin_link_de_pago_la_solicitud_igual_queda_y_no_hay_link(consola):
    consola["ana"].patch(f"/api/proyectos/{consola['slug']}", json={"link_reserva": ""})

    respuesta = solicitar(consola)

    assert respuesta.status_code == 201
    assert respuesta.json()["link"] is None


def test_una_parcela_apartada_no_se_puede_pedir_de_nuevo(consola):
    solicitar(consola)

    respuesta = solicitar(consola, nombre="Otra Persona", email="otra@correo.cl", telefono="912345678")

    assert respuesta.status_code == 409
    assert "apartada" in respuesta.json()["detail"]


def test_una_parcela_que_no_esta_en_venta_no_se_aparta(consola):
    assert solicitar(consola, parcela="1-8").status_code == 409


@pytest.mark.parametrize("cambio", [{"parcela": "9-99"}, {"loteo": "no-existe"}])
def test_una_parcela_o_un_loteo_que_no_existen_dan_404(consola, cambio):
    assert solicitar(consola, **cambio).status_code == 404


def test_un_loteo_sin_publicar_no_recibe_solicitudes(consola):
    sin_publicar = consola["ana"].post("/api/proyectos", json={"nombre": "Borrador"}).json()["slug"]

    assert solicitar(consola, loteo=sin_publicar).status_code == 404


@pytest.mark.parametrize("cambio", [
    {"nombre": "P"}, {"telefono": "123"}, {"email": "no-es-correo"}, {"nombre": ""},
], ids=["nombre-corto", "telefono-corto", "correo", "sin-nombre"])
def test_los_datos_que_no_sirven_se_rechazan_y_no_apartan_nada(consola, cambio):
    respuesta = solicitar(consola, **cambio)

    assert respuesta.status_code == 400
    assert apartadas(consola).json() == {}


def test_el_campo_trampa_lleno_parece_aceptado_pero_no_aparta_ni_avisa(consola):
    respuesta = solicitar(consola, sitio="https://spam.example")

    assert respuesta.status_code == 201
    assert apartadas(consola).json() == {}
    assert consola["correo"].enviados == []


def test_desde_otro_sitio_no_se_puede_pedir(consola):
    cuerpo = json.dumps({"loteo": consola["slug"], "parcela": "1-7", **COMPRADOR})

    respuesta = consola["publico"].post("/api/publico/reservas", content=cuerpo,
                                        headers={"origin": "https://otro-sitio.example"})

    assert respuesta.status_code == 403
    assert "access-control-allow-origin" not in respuesta.headers


def test_mas_de_cinco_solicitudes_por_hora_desde_la_misma_conexion_se_frenan(consola):
    codigos = [solicitar(consola, parcela="9-99").status_code for _ in range(6)]

    assert codigos[:5] == [404] * 5 and codigos[5] == 429


# --- el plazo -----------------------------------------------------------------------

def test_a_las_dos_horas_sin_confirmar_la_parcela_vuelve_a_estar_disponible(consola):
    solicitar(consola)
    consola["reloj"].ahora += timedelta(hours=2, seconds=1)

    assert apartadas(consola).json() == {}
    assert solicitar(consola, nombre="Otra Persona").status_code == 201


# --- en la consola ------------------------------------------------------------------

def test_la_loteadora_ve_sus_solicitudes_con_los_datos_del_comprador(consola):
    solicitar(consola)

    (solicitud,) = consola["ana"].get(f"/api/proyectos/{consola['slug']}/reservas").json()

    assert (solicitud["parcela"], solicitud["nombre"], solicitud["telefono"], solicitud["email"],
            solicitud["estado"]) == ("1-7", "Pedro Pérez", "56987654321", "pedro@correo.cl", "pendiente")


def test_otra_loteadora_no_ve_ni_resuelve_las_solicitudes_ajenas(consola):
    solicitar(consola)
    (solicitud,) = consola["ana"].get(f"/api/proyectos/{consola['slug']}/reservas").json()
    base = f"/api/proyectos/{consola['slug']}/reservas"

    assert consola["luis"].get(base).status_code == 404
    assert consola["luis"].post(f"{base}/{solicitud['id']}/confirmar").status_code == 404
    assert consola["luis"].post(f"{base}/{solicitud['id']}/liberar").status_code == 404


def test_confirmada_queda_apartada_aunque_pasen_las_dos_horas(consola):
    solicitar(consola)
    (solicitud,) = consola["ana"].get(f"/api/proyectos/{consola['slug']}/reservas").json()

    respuesta = consola["ana"].post(f"/api/proyectos/{consola['slug']}/reservas/{solicitud['id']}/confirmar")
    consola["reloj"].ahora += timedelta(days=3)

    assert respuesta.json()["estado"] == "confirmada"
    assert apartadas(consola).json() == {"1-7": None}


def test_liberada_vuelve_a_estar_disponible_al_tiro(consola):
    solicitar(consola)
    (solicitud,) = consola["ana"].get(f"/api/proyectos/{consola['slug']}/reservas").json()

    consola["ana"].post(f"/api/proyectos/{consola['slug']}/reservas/{solicitud['id']}/liberar")

    assert apartadas(consola).json() == {}


def test_una_vencida_se_lista_como_vencida(consola):
    solicitar(consola)
    consola["reloj"].ahora += timedelta(hours=3)

    (solicitud,) = consola["ana"].get(f"/api/proyectos/{consola['slug']}/reservas").json()

    assert solicitud["estado"] == "vencida"


def test_publicar_le_dice_al_sitio_su_loteo_y_su_consola(consola, monkeypatch):
    monkeypatch.setenv("CONSOLA_URL", "https://consola.tumasterplan.cl")
    ctp = entrar_como_ctp(consola)
    ctp.post(f"/api/plataforma/proyectos/{consola['slug']}/pago", json={"nota_cobro": "x"})

    assert consola["ana"].post(f"/api/proyectos/{consola['slug']}/publicar",
                               json={"confirmado": True}).status_code == 202

    datos = json.loads((consola["registro"].salidas / consola["slug"] / "sitio" / "datos"
                        / "parcelas.json").read_text())
    assert (datos["loteo"], datos["consola"]) == (consola["slug"], "https://consola.tumasterplan.cl")


# --- lo que encontró la revisión de seguridad --------------------------------------------

def test_un_cuerpo_gigante_se_corta_sin_leerlo_entero(consola):
    respuesta = consola["publico"].post("/api/publico/reservas", content=b"x" * 50_000,
                                        headers={"content-type": "text/plain"})

    assert respuesta.status_code == 413


def test_un_mismo_comprador_no_aparta_dos_parcelas_a_la_vez(consola):
    datos = consola["registro"].salidas / consola["slug"] / "sitio" / "datos" / "parcelas.json"
    sitio = json.loads(datos.read_text())
    sitio["parcelas"].append({"id": "1-9", "estado": "disponible"})
    datos.write_text(json.dumps(sitio))
    solicitar(consola)

    respuesta = solicitar(consola, parcela="1-9", telefono="9 8765 4321")

    assert respuesta.status_code == 409
    assert "ya tienes" in respuesta.json()["detail"].lower()


def test_un_loteo_no_puede_quedar_entero_apartado_por_solicitudes_sin_pagar(consola, monkeypatch):
    monkeypatch.setattr("consola.reservas.TOPE_PENDIENTES_POR_LOTEO", 1)
    datos = consola["registro"].salidas / consola["slug"] / "sitio" / "datos" / "parcelas.json"
    sitio = json.loads(datos.read_text())
    sitio["parcelas"].append({"id": "1-9", "estado": "disponible"})
    datos.write_text(json.dumps(sitio))
    solicitar(consola)

    respuesta = solicitar(consola, parcela="1-9", nombre="Otra Persona", email="otra@correo.cl",
                          telefono="912345678")

    assert respuesta.status_code == 409


def test_un_origen_ajeno_no_recibe_permiso_para_leer_ni_los_errores(consola):
    respuesta = consola["publico"].post("/api/publico/reservas", content=b"no es json",
                                        headers={"origin": "https://otro-sitio.example"})

    assert respuesta.status_code == 400
    assert "access-control-allow-origin" not in respuesta.headers


def test_no_se_confirma_una_solicitud_si_otra_persona_ya_aparto_la_parcela(consola):
    solicitar(consola)
    base = f"/api/proyectos/{consola['slug']}/reservas"
    (primera,) = consola["ana"].get(base).json()
    consola["ana"].post(f"{base}/{primera['id']}/liberar")
    solicitar(consola, nombre="Otra Persona", email="otra@correo.cl", telefono="912345678")

    respuesta = consola["ana"].post(f"{base}/{primera['id']}/confirmar")

    assert respuesta.status_code == 409


def test_el_correo_avisa_que_los_datos_no_estan_verificados(consola):
    solicitar(consola)

    assert "sin verificar" in consola["correo"].enviados[0]["texto"]


@pytest.mark.parametrize("email", ['a"b<x>@x.y', "pedro@correo", "http://malo.example"])
def test_un_correo_con_forma_rara_se_rechaza(consola, email):
    assert solicitar(consola, email=email).status_code == 400
