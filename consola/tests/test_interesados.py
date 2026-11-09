"""Interesados y estadísticas: el sitio publicado avisa quién pregunta y qué se mira."""
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from consola.acceso import Acceso
from consola.app import crear_app
from consola.datos import Base
from consola.disenos import Disenos
from consola.estadisticas import EVENTOS_POR_PEDIDO, Estadisticas
from consola.interesados import Interesados
from consola.kmzs import RegistroKmz
from consola.proyectos import Registro
from consola.reservas import Reservas
from consola.tests.test_app import CLAVE, ComandosDePrueba, entrar
from consola.tests.test_reservas import CorreoDePrueba, Reloj
from consola.trabajos import Trabajos

COMPRADOR = {"nombre": "Pedro Pérez", "telefono": "9 8765 4321", "horario": "tarde"}


@pytest.fixture
def consola(tmp_path):
    """Dos loteadoras; Ana tiene un loteo publicado con dos parcelas."""
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    for nombre, email in (("Los Robles", "ana@losrobles.cl"), ("Del Valle", "luis@delvalle.cl")):
        base.crear_cliente(nombre, email, nombre)
        base.cambiar_clave(email, CLAVE)
    registro = Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas")
    correo, reloj = CorreoDePrueba(), Reloj()
    app = crear_app(registro=registro, trabajos=Trabajos(), comandos=ComandosDePrueba(),
                    acceso=Acceso(base=base, secreto="un-secreto", local=False), base=base,
                    disenos=Disenos(base=base, carpeta=tmp_path / "disenos"), google=None, cierra=None,
                    kmzs=RegistroKmz(base=base, carpeta=tmp_path / "kmz", limites=registro.limites),
                    reservas=Reservas(base=base, correo=correo, ahora=reloj, en_segundo_plano=False),
                    interesados=Interesados(base=base, correo=correo, ahora=reloj, en_segundo_plano=False),
                    estadisticas=Estadisticas(base=base, ahora=reloj))
    ana, luis = entrar(app, "ana@losrobles.cl"), entrar(app, "luis@delvalle.cl")
    slug = ana.post("/api/proyectos", json={"nombre": "Praderas"}).json()["slug"]
    datos = registro.salidas / slug / "sitio" / "datos"
    datos.mkdir(parents=True)
    (datos / "parcelas.json").write_text(json.dumps({"parcelas": [
        {"id": "1-7", "estado": "disponible"}, {"id": "1-8", "estado": "vendido"}]}))
    base.anotar_publicacion(slug, f"masterplan-{slug}", f"https://masterplan-{slug}.vercel.app")
    publico = TestClient(app, headers={"origin": f"https://masterplan-{slug}.vercel.app"})
    return {"publico": publico, "ana": ana, "luis": luis, "slug": slug, "correo": correo,
            "reloj": reloj, "base": base}


def me_interesa(c, parcela="1-7", **cambios):
    cuerpo = {"loteo": c["slug"], "parcela": parcela, **COMPRADOR, **cambios}
    return c["publico"].post("/api/publico/interesados", content=json.dumps(cuerpo),
                             headers={"content-type": "text/plain"})


def eventos(c, lista):
    return c["publico"].post("/api/publico/eventos",
                             content=json.dumps({"loteo": c["slug"], "eventos": lista}),
                             headers={"content-type": "text/plain"})


def lista(c, quien="ana"):
    return c[quien].get(f"/api/proyectos/{c['slug']}/interesados")


# --- "Me interesa" desde el sitio --------------------------------------------------

def test_un_interesado_queda_en_la_consola_y_la_loteadora_recibe_un_correo(consola):
    respuesta = me_interesa(consola)

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.headers["access-control-allow-origin"] == f"https://masterplan-{consola['slug']}.vercel.app"
    (interesado,) = lista(consola).json()
    assert interesado["parcela"] == "1-7" and interesado["estado"] == "nuevo"
    assert interesado["telefono"] == "56987654321" and interesado["horario"] == "tarde"
    (correo,) = consola["correo"].enviados
    assert correo["para"] == "ana@losrobles.cl"
    assert "1-7" in correo["asunto"] and "Praderas" in correo["asunto"]
    for dato in ("Pedro Pérez", "56987654321", "en la tarde"):
        assert dato in correo["texto"]


def test_tambien_se_puede_interesar_en_una_parcela_vendida(consola):
    # No aparta nada: es un contacto, y la loteadora puede ofrecerle otra.
    assert me_interesa(consola, parcela="1-8").status_code == 201


def test_el_mismo_telefono_por_la_misma_parcela_no_se_duplica_en_24_horas(consola):
    me_interesa(consola)
    me_interesa(consola, telefono="+56 9 8765 4321")
    assert len(lista(consola).json()) == 1
    assert len(consola["correo"].enviados) == 1

    consola["reloj"].ahora += timedelta(hours=25)
    me_interesa(consola)
    assert len(lista(consola).json()) == 2


def test_datos_que_no_sirven_se_rechazan_con_el_motivo(consola):
    assert "nombre" in me_interesa(consola, nombre="").json()["detail"]
    assert "teléfono" in me_interesa(consola, telefono="123").json()["detail"]
    assert me_interesa(consola, email="no-es-correo").status_code == 400
    assert me_interesa(consola, parcela="9-99").status_code == 404
    assert lista(consola).json() == []


def test_el_campo_trampa_contesta_bien_pero_no_guarda_nada(consola):
    assert me_interesa(consola, sitio="http://spam").status_code == 201
    assert lista(consola).json() == [] and consola["correo"].enviados == []


def test_desde_otro_sitio_no_se_acepta(consola):
    respuesta = consola["publico"].post(
        "/api/publico/interesados", headers={"origin": "https://otro.cl", "content-type": "text/plain"},
        content=json.dumps({"loteo": consola["slug"], "parcela": "1-7", **COMPRADOR}))
    assert respuesta.status_code == 403
    assert "access-control-allow-origin" not in respuesta.headers


def test_hay_tope_de_envios_por_ip(consola):
    for n in range(5):
        me_interesa(consola, telefono=f"9876543{n:02d}")
    assert me_interesa(consola, telefono="987654399").status_code == 429


# --- seguirlos en la consola -------------------------------------------------------

def test_la_loteadora_cambia_estado_responsable_y_nota(consola):
    me_interesa(consola)
    (interesado,) = lista(consola).json()
    url = f"/api/proyectos/{consola['slug']}/interesados/{interesado['id']}"

    respuesta = consola["ana"].patch(url, json={"estado": "contactado", "responsable": "Marta",
                                                "nota": "Llamar el jueves.\nQuiere ver la 1-7."})

    assert respuesta.status_code == 200
    assert respuesta.json()["estado"] == "contactado"
    assert respuesta.json()["responsable"] == "Marta"
    assert respuesta.json()["nota"] == "Llamar el jueves.\nQuiere ver la 1-7."
    assert consola["ana"].patch(url, json={"estado": "inventado"}).status_code == 400


def test_otra_loteadora_no_ve_ni_cambia_los_interesados(consola):
    me_interesa(consola)
    (interesado,) = lista(consola).json()

    assert lista(consola, "luis").status_code == 404
    assert consola["luis"].patch(f"/api/proyectos/{consola['slug']}/interesados/{interesado['id']}",
                                 json={"estado": "descartado"}).status_code == 404
    assert consola["luis"].get(f"/api/proyectos/{consola['slug']}/estadisticas").status_code == 404
    assert lista(consola).json()[0]["estado"] == "nuevo"


# --- estadísticas -------------------------------------------------------------------

def test_los_eventos_se_suman_por_dia_y_por_parcela(consola):
    assert eventos(consola, [{"tipo": "visita"}, {"tipo": "ficha", "parcela": "1-7"},
                             {"tipo": "ficha", "parcela": "1-7"}, {"tipo": "whatsapp", "parcela": "1-7"},
                             {"tipo": "ficha", "parcela": "1-8"}]).status_code == 204
    eventos(consola, [{"tipo": "visita"}, {"tipo": "reservar", "parcela": "1-7"}])
    me_interesa(consola)

    cifras = consola["ana"].get(f"/api/proyectos/{consola['slug']}/estadisticas?dias=7").json()

    assert cifras["totales"] == {"visita": 2, "ficha": 3, "whatsapp": 1, "reservar": 1,
                                 "interesa": 1, "reservas": 0}
    assert len(cifras["por_dia"]) == 7
    assert cifras["por_dia"][-1] == {"dia": "2026-10-06", "visitas": 2}
    primera, segunda = cifras["parcelas"]
    assert primera == {"parcela": "1-7", "estado": "disponible", "ficha": 2, "whatsapp": 1,
                       "reservar": 1, "interesa": 1, "reservas": 0}
    assert segunda["parcela"] == "1-8" and segunda["estado"] == "vendido"


def test_las_parcelas_inventadas_y_los_tipos_raros_se_descartan(consola):
    eventos(consola, [{"tipo": "ficha", "parcela": "9-99"}, {"tipo": "borrar"}, "basura"])

    cifras = consola["ana"].get(f"/api/proyectos/{consola['slug']}/estadisticas").json()

    assert cifras["parcelas"] == [] and cifras["totales"]["ficha"] == 0


def test_demasiados_eventos_en_un_pedido_se_rechazan(consola):
    assert eventos(consola, [{"tipo": "visita"}] * (EVENTOS_POR_PEDIDO + 1)).status_code == 400


def test_los_dias_viejos_quedan_fuera_del_periodo(consola):
    eventos(consola, [{"tipo": "visita"}])
    consola["reloj"].ahora += timedelta(days=10)
    eventos(consola, [{"tipo": "visita"}])

    semana = consola["ana"].get(f"/api/proyectos/{consola['slug']}/estadisticas?dias=7").json()
    mes = consola["ana"].get(f"/api/proyectos/{consola['slug']}/estadisticas?dias=30").json()

    assert semana["totales"]["visita"] == 1 and mes["totales"]["visita"] == 2
    assert consola["ana"].get(f"/api/proyectos/{consola['slug']}/estadisticas?dias=12").status_code == 400
