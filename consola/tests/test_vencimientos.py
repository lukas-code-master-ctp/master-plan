"""Bajar un loteo del aire y lo que pasa cuando un plan llega a su fecha."""
from datetime import date, timedelta

import pytest

from consola import planes, vencimientos
from consola.tests.test_app import esperar_trabajo
from consola.tests.test_planes import ana_y_ctp, dar_plan, loteo, nuevo_construido, publicar  # noqa: F401


def publicado(web, slug):
    esperar_trabajo(web, publicar(web, slug).json()["id"])
    assert loteo(web, slug)["publicado"]


def bajar(web, slug, confirmado=True):
    return web.post(f"/api/proyectos/{slug}/bajar", json={"confirmado": confirmado})


# --- bajar del aire -------------------------------------------------------------

def test_bajar_saca_el_sitio_y_libera_el_cupo(ana_y_ctp):
    ctp, ana, registro, comandos = ana_y_ctp
    uno = nuevo_construido(ana, registro, "Uno")
    dos = nuevo_construido(ana, registro, "Dos")
    dar_plan(ctp, registro, "fly")
    publicado(ana, uno)
    assert publicar(ana, dos).status_code == 402

    respuesta = bajar(ana, uno)

    assert respuesta.status_code == 202
    esperar_trabajo(ana, respuesta.json()["id"])
    assert ("bajar", f"masterplan-{uno}") in comandos.pedidos
    assert loteo(ana, uno)["publicado"] is False
    assert publicar(ana, dos).status_code == 202


def test_bajar_pide_confirmacion(ana_y_ctp):
    ctp, ana, registro, comandos = ana_y_ctp
    uno = nuevo_construido(ana, registro, "Uno")
    dar_plan(ctp, registro, "fly")
    publicado(ana, uno)

    assert bajar(ana, uno, confirmado=False).status_code == 428
    assert not [p for p in comandos.pedidos if p[0] == "bajar"]


def test_no_se_baja_lo_que_no_esta_en_linea(ana_y_ctp):
    _, ana, registro, _ = ana_y_ctp
    uno = nuevo_construido(ana, registro, "Uno")

    assert bajar(ana, uno).status_code == 409


def test_volver_a_publicar_uno_bajado_usa_su_mismo_nombre(ana_y_ctp):
    ctp, ana, registro, comandos = ana_y_ctp
    uno = nuevo_construido(ana, registro, "Uno")
    dar_plan(ctp, registro, "fly")
    publicado(ana, uno)
    esperar_trabajo(ana, bajar(ana, uno).json()["id"])

    publicado(ana, uno)

    # Ni crear a ciegas (chocaría con el suyo) ni dar por hecho que sigue en el hosting.
    assert comandos.pedidos[-1] == ("publicar", uno, f"masterplan-{uno}", "si-falta")


# --- la fecha del plan ----------------------------------------------------------

def test_un_plan_sin_fecha_dura_un_mes(ana_y_ctp):
    ctp, ana, registro, _ = ana_y_ctp

    assert dar_plan(ctp, registro, "pro").status_code == 200

    [cliente] = [c for c in registro.base.clientes() if c.nombre == "Los Robles"]
    assert cliente.plan_hasta == planes._un_mes_despues(planes.hoy())


def test_la_fecha_del_plan_no_puede_estar_pasada(ana_y_ctp):
    ctp, _, registro, _ = ana_y_ctp
    ayer = (planes.hoy() - timedelta(days=1)).isoformat()

    respuesta = dar_plan(ctp, registro, "pro", hasta=ayer)

    assert respuesta.status_code == 400
    assert "ya pasó" in respuesta.json()["detail"]


@pytest.mark.parametrize("dia, esperado", [
    (date(2026, 1, 31), date(2026, 2, 28)),
    (date(2026, 10, 27), date(2026, 11, 27)),
    (date(2026, 12, 15), date(2027, 1, 15)),
])
def test_un_mes_despues(dia, esperado):
    assert planes._un_mes_despues(dia) == esperado


def test_con_el_plan_vencido_no_se_publica_otro_pero_lo_en_linea_sigue(ana_y_ctp):
    ctp, ana, registro, _ = ana_y_ctp
    uno = nuevo_construido(ana, registro, "Uno")
    dos = nuevo_construido(ana, registro, "Dos")
    dar_plan(ctp, registro, "pro")
    publicado(ana, uno)
    [cliente] = [c for c in registro.base.clientes() if c.nombre == "Los Robles"]
    registro.base.asignar_plan(cliente.id, "pro", nota="factura 1",
                               hasta=planes.hoy() - timedelta(days=2))

    lleno = publicar(ana, dos)

    assert lleno.status_code == 402
    assert "venció" in lleno.json()["detail"]
    assert loteo(ana, uno)["habilitado"] is True


# --- la revisión de cada 15 minutos ---------------------------------------------

class AvisosDePrueba:
    def __init__(self):
        self.mandados = []

    def plan_por_vencer(self, **datos):
        self.mandados.append(("por vencer", datos["hasta"]))

    def plan_vencido(self, **datos):
        self.mandados.append(("vencido", datos["bajada"]))

    def plan_bajado(self, **datos):
        self.mandados.append(("bajado", datos["plan"]))


@pytest.fixture
def con_plan(ana_y_ctp):
    """Ana con un Pro pagado hasta el 30/11 y un loteo en línea."""
    ctp, ana, registro, comandos = ana_y_ctp
    uno = nuevo_construido(ana, registro, "Uno")
    dar_plan(ctp, registro, "pro")
    publicado(ana, uno)
    [cliente] = [c for c in registro.base.clientes() if c.nombre == "Los Robles"]
    hasta = date(2026, 11, 30)
    registro.base.asignar_plan(cliente.id, "pro", nota="factura 1", hasta=hasta)
    return registro.base, cliente.id, uno, hasta


def revisar(base, dia, bajados, ocupados=()):
    avisos = AvisosDePrueba()
    hechas = vencimientos.revisar(base, avisos, hoy=dia, bajar=bajados.append,
                                  ocupado=lambda slug: slug in ocupados)
    return [h.que for h in hechas], avisos.mandados


def test_antes_de_los_cinco_dias_no_pasa_nada(con_plan):
    base, _, _, hasta = con_plan

    assert revisar(base, hasta - timedelta(days=6), []) == ([], [])


def test_cinco_dias_antes_avisa_una_sola_vez(con_plan):
    base, _, _, hasta = con_plan

    assert revisar(base, hasta - timedelta(days=5), []) == (["recordatorio"], [("por vencer", hasta)])
    assert revisar(base, hasta - timedelta(days=4), []) == ([], [])


def test_al_vencer_avisa_cuando_se_bajan(con_plan):
    base, _, _, hasta = con_plan

    que, mandados = revisar(base, hasta + timedelta(days=1), [])

    assert que == ["vencido"]
    assert mandados == [("vencido", date(2026, 12, 8))]
    # El último día de gracia todavía no se baja nada.
    assert revisar(base, date(2026, 12, 7), []) == ([], [])


def test_a_los_siete_dias_baja_y_recien_con_todo_abajo_quita_el_plan(con_plan):
    base, cliente_id, uno, _ = con_plan
    bajados = []

    assert revisar(base, date(2026, 12, 8), bajados) == (["bajando"], [])
    assert bajados == [uno]
    assert base.cliente(cliente_id).plan == "pro"

    base.anotar_bajada(uno)
    que, mandados = revisar(base, date(2026, 12, 8), bajados)

    assert que == ["plan quitado"]
    assert mandados == [("bajado", "Pro")]
    assert base.cliente(cliente_id).plan is None


def test_uno_que_se_esta_bajando_no_se_lanza_dos_veces(con_plan):
    base, _, uno, _ = con_plan
    bajados = []

    revisar(base, date(2026, 12, 8), bajados, ocupados={uno})

    assert bajados == []


def test_renovar_vuelve_a_armar_los_avisos(con_plan):
    base, cliente_id, _, hasta = con_plan
    revisar(base, hasta - timedelta(days=5), [])

    nuevo = date(2026, 12, 30)
    base.asignar_plan(cliente_id, "pro", nota="factura 2", hasta=nuevo)

    assert revisar(base, hasta + timedelta(days=1), []) == ([], [])
    assert revisar(base, nuevo - timedelta(days=5), [])[0] == ["recordatorio"]


def test_un_plan_sin_fecha_no_vence(con_plan):
    base, cliente_id, _, _ = con_plan
    base.asignar_plan(cliente_id, "pro", nota="de antes", hasta=None)

    assert revisar(base, date(2030, 1, 1), []) == ([], [])


def test_la_tarea_de_planes_pide_su_clave(tmp_path, monkeypatch):
    from consola.tests.test_app import montar
    from fastapi.testclient import TestClient

    app, _, _, _ = montar(tmp_path)
    web = TestClient(app)
    assert web.post("/api/tareas/planes").status_code == 404

    monkeypatch.setenv("CONSOLA_TAREAS_CLAVE", "clave-de-prueba")
    assert web.post("/api/tareas/planes").status_code == 401
    respuesta = web.post("/api/tareas/planes", headers={"X-Tarea-Clave": "clave-de-prueba"})
    assert respuesta.status_code == 200
    assert respuesta.json() == {"planes": []}


def test_dar_el_plan_atiende_los_pedidos_y_no_vuelven_al_vencer(ana_y_ctp):
    ctp, ana, registro, _ = ana_y_ctp
    uno = nuevo_construido(ana, registro, "Uno")
    ana.post(f"/api/proyectos/{uno}/habilitacion", json={"plan": "fly"})
    assert [p["slug"] for p in ctp.get("/api/plataforma/por-habilitar").json()] == [uno]

    dar_plan(ctp, registro, "fly")
    [cliente] = [c for c in registro.base.clientes() if c.nombre == "Los Robles"]
    registro.base.asignar_plan(cliente.id, None)

    assert ctp.get("/api/plataforma/por-habilitar").json() == []
