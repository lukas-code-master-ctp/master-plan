"""Configuración → Actividad: lo que pasó en la loteadora, quién lo hizo y cuándo."""
from .test_reservas import (  # noqa: F401  (consola es fixture)
    CLAVE,
    COMPRADOR,
    consola,
    solicitar,
)


def actividad(c, quien="ana", **params):
    respuesta = c[quien].get("/api/actividad", params=params)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()


def que_paso(c, quien="ana"):
    return [e["que"] for e in actividad(c, quien)]


def test_crear_un_master_queda_anotado_con_quien_lo_hizo(consola):  # noqa: F811
    consola["ana"].post("/api/proyectos", json={"nombre": "Los Olmos"})

    (ultimo, *_) = actividad(consola)

    assert ultimo["que"] == "master creado"
    assert ultimo["detalle"] == "Los Olmos"
    assert ultimo["quien"]["email"] == "ana@losrobles.cl"
    assert ultimo["cuando"]


def test_lo_de_otra_loteadora_no_se_ve(consola):  # noqa: F811
    consola["luis"].post("/api/proyectos", json={"nombre": "Del Valle Norte"})

    assert "Del Valle Norte" not in [e["detalle"] for e in actividad(consola)]
    assert "Del Valle Norte" in [e["detalle"] for e in actividad(consola, "luis")]


def test_una_reserva_pedida_queda_sin_los_datos_del_comprador(consola):  # noqa: F811
    solicitar(consola)

    (ultimo, *_) = actividad(consola)

    assert ultimo["que"] == "reserva pedida"
    assert ultimo["quien"] is None
    assert "1-7" in ultimo["detalle"] and "Praderas" in ultimo["detalle"]
    for dato in COMPRADOR.values():
        assert dato not in ultimo["detalle"]


def test_confirmar_y_liberar_una_reserva_quedan_anotados(consola):  # noqa: F811
    solicitar(consola)
    (solicitud,) = consola["ana"].get(f"/api/proyectos/{consola['slug']}/reservas").json()

    consola["ana"].post(f"/api/proyectos/{consola['slug']}/reservas/{solicitud['id']}/confirmar")
    consola["ana"].post(f"/api/proyectos/{consola['slug']}/reservas/{solicitud['id']}/liberar")

    assert que_paso(consola)[:2] == ["reserva liberada", "reserva confirmada"]


def test_disenos_y_masters_quitados_quedan_anotados(consola):  # noqa: F811
    diseno = consola["ana"].post("/api/disenos", json={"nombre": "Marca", "color": "#166534"}).json()
    consola["ana"].delete(f"/api/disenos/{diseno['id']}")
    slug = consola["ana"].post("/api/proyectos", json={"nombre": "De paso"}).json()["slug"]
    consola["ana"].delete(f"/api/proyectos/{slug}")

    assert que_paso(consola)[:4] == ["master quitado", "master creado", "diseño borrado", "diseño creado"]


def test_cambiar_la_contrasena_queda_anotado(consola):  # noqa: F811
    consola["ana"].post("/api/clave", json={"actual": CLAVE, "nueva": "otra-clave-larga-1"})
    consola["ana"].post("/entrar", data={"email": "ana@losrobles.cl", "clave": "otra-clave-larga-1"})

    assert que_paso(consola)[0] == "contraseña cambiada"


def test_se_pide_por_partes_hacia_atras(consola):  # noqa: F811
    for numero in range(5):
        consola["ana"].post("/api/disenos", json={"nombre": f"Marca {numero}", "color": "#166534"})

    primera = actividad(consola, limite=2)
    siguiente = actividad(consola, limite=2, antes=primera[-1]["id"])

    assert [e["detalle"] for e in primera] == ["Marca 4", "Marca 3"]
    assert [e["detalle"] for e in siguiente] == ["Marca 2", "Marca 1"]
