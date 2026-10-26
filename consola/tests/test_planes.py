"""La suscripción: el plan de la loteadora decide cuántos loteos tiene en línea."""
import pytest

from consola import planes
from consola.tests.test_app import construir_a_mano, crear, entrar, id_de, montar


@pytest.fixture
def ana_y_ctp(tmp_path):
    app, base, registro, comandos = montar(tmp_path)
    return entrar(app, "ctp@ctp.cl"), entrar(app, "ana@losrobles.cl"), registro, comandos


def nuevo_construido(web, registro, nombre):
    slug = crear(web, nombre)["slug"]
    construir_a_mano(registro, registro.salidas, slug)
    return slug


def en_linea(registro, slug):
    """Como queda tras publicar: la URL anotada es lo que lo cuenta como en línea."""
    registro.base.anotar_publicacion(slug, f"masterplan-{slug}", f"https://{slug}.vercel.app")


def dar_plan(ctp, registro, plan, **campos):
    cliente_id = id_de(registro, "ana@losrobles.cl")
    return ctp.post(f"/api/plataforma/clientes/{cliente_id}/plan",
                    json={"plan": plan, "nota_cobro": "factura 1", **campos})


def loteo(web, slug):
    [encontrado] = [p for p in web.get("/api/proyectos").json() if p["slug"] == slug]
    return encontrado


def publicar(web, slug):
    return web.post(f"/api/proyectos/{slug}/publicar", json={"confirmado": True})


def test_los_planes_son_los_de_la_landing():
    assert {c: (p.loteos, p.precio_mensual) for c, p in planes.PLANES.items()} == {
        "fly": (1, 30_000), "pro": (3, 80_000), "master": (6, 150_000),
        "enterprise": (None, None)}


def test_sin_plan_se_arma_pero_no_se_publica(ana_y_ctp):
    _, ana, registro, comandos = ana_y_ctp
    slug = nuevo_construido(ana, registro, "Uno")

    respuesta = publicar(ana, slug)

    assert respuesta.status_code == 402
    assert "elige un plan" in respuesta.json()["detail"]
    assert loteo(ana, slug)["habilitado"] is False
    assert not [p for p in comandos.pedidos if p[0] == "publicar"]


def test_el_plan_fly_deja_un_loteo_en_linea(ana_y_ctp):
    ctp, ana, registro, _ = ana_y_ctp
    uno = nuevo_construido(ana, registro, "Uno")
    dos = nuevo_construido(ana, registro, "Dos")
    assert dar_plan(ctp, registro, "fly").status_code == 200

    assert publicar(ana, uno).status_code == 202
    en_linea(registro, uno)
    lleno = publicar(ana, dos)

    assert lleno.status_code == 402
    assert "Fly incluye 1 loteo en línea" in lleno.json()["detail"]
    assert loteo(ana, dos)["habilitado"] is False
    # El que ya está en línea se sigue actualizando: no suma cupo.
    assert loteo(ana, uno)["habilitado"] is True


def test_subir_de_plan_abre_cupo(ana_y_ctp):
    ctp, ana, registro, _ = ana_y_ctp
    uno = nuevo_construido(ana, registro, "Uno")
    dos = nuevo_construido(ana, registro, "Dos")
    dar_plan(ctp, registro, "fly")
    en_linea(registro, uno)

    dar_plan(ctp, registro, "pro")

    assert publicar(ana, dos).status_code == 202


def test_un_loteo_pagado_aparte_no_ocupa_cupo(ana_y_ctp):
    ctp, ana, registro, _ = ana_y_ctp
    pagado = nuevo_construido(ana, registro, "Pagado")
    nuevo = nuevo_construido(ana, registro, "Nuevo")
    registro.base.anotar_pago(pagado, "transferencia del modelo anterior")
    en_linea(registro, pagado)

    # Sin plan, el pagado se publica igual.
    assert publicar(ana, pagado).status_code == 202
    dar_plan(ctp, registro, "fly")
    assert publicar(ana, nuevo).status_code == 202


def test_sin_plan_un_loteo_en_linea_no_se_vuelve_a_publicar(ana_y_ctp):
    ctp, ana, registro, _ = ana_y_ctp
    uno = nuevo_construido(ana, registro, "Uno")
    dar_plan(ctp, registro, "fly")
    en_linea(registro, uno)

    quitar = ctp.post(f"/api/plataforma/clientes/{id_de(registro, 'ana@losrobles.cl')}/plan",
                      json={"plan": None})

    assert quitar.status_code == 200
    assert quitar.json()["plan"]["plan"] is None
    assert publicar(ana, uno).status_code == 402
    assert [e.que for e in registro.base.historial()][:2] == ["plan quitado", "plan asignado"]


def test_dar_un_plan_exige_la_nota_de_cobro(ana_y_ctp):
    ctp, _, registro, _ = ana_y_ctp

    respuesta = dar_plan(ctp, registro, "pro", nota_cobro=" ")

    assert respuesta.status_code == 400
    assert registro.base.cliente(id_de(registro, "ana@losrobles.cl")).plan is None


def test_el_plan_a_la_medida_lleva_su_cupo(ana_y_ctp):
    ctp, _, registro, _ = ana_y_ctp

    sin_cupo = dar_plan(ctp, registro, "enterprise")
    con_cupo = dar_plan(ctp, registro, "enterprise", loteos=12)

    assert sin_cupo.status_code == 400
    assert con_cupo.status_code == 200
    assert con_cupo.json()["plan"]["loteos"] == 12


def test_un_plan_que_no_existe_da_400(ana_y_ctp):
    ctp, _, registro, _ = ana_y_ctp

    assert dar_plan(ctp, registro, "gratis").status_code == 400


def test_la_loteadora_no_se_da_un_plan(ana_y_ctp):
    _, ana, registro, _ = ana_y_ctp
    cliente_id = id_de(registro, "ana@losrobles.cl")

    respuesta = ana.post(f"/api/plataforma/clientes/{cliente_id}/plan",
                         json={"plan": "master", "nota_cobro": "me lo regalo"})

    assert respuesta.status_code in (403, 404)
    assert registro.base.cliente(cliente_id).plan is None


def test_la_sesion_dice_el_plan_y_cuantos_lleva(ana_y_ctp):
    ctp, ana, registro, _ = ana_y_ctp
    uno = nuevo_construido(ana, registro, "Uno")
    dar_plan(ctp, registro, "pro")
    en_linea(registro, uno)

    sesion = ana.get("/api/sesion").json()

    assert sesion["plan"]["nombre"] == "Pro"
    assert (sesion["plan"]["loteos"], sesion["plan"]["en_linea"]) == (3, 1)
    assert [p["plan"] for p in sesion["planes"]] == ["fly", "pro", "master", "enterprise"]


def test_el_pedido_sale_de_la_cola_cuando_tiene_plan(ana_y_ctp):
    ctp, ana, registro, _ = ana_y_ctp
    slug = nuevo_construido(ana, registro, "Uno")
    ana.post(f"/api/proyectos/{slug}/habilitacion", json={"plan": "fly"})

    [pedido] = ctp.get("/api/plataforma/por-habilitar").json()
    assert pedido["plan"]["pedido"] == "fly"

    dar_plan(ctp, registro, "fly")

    assert ctp.get("/api/plataforma/por-habilitar").json() == []
    assert registro.base.cliente(id_de(registro, "ana@losrobles.cl")).plan_pedido is None


def test_un_loteo_en_linea_con_el_plan_no_se_quita_desde_la_consola(ana_y_ctp):
    ctp, ana, registro, _ = ana_y_ctp
    slug = nuevo_construido(ana, registro, "Uno")
    dar_plan(ctp, registro, "fly")
    en_linea(registro, slug)

    respuesta = ana.delete(f"/api/proyectos/{slug}")

    # Quitarlo deja el sitio en línea y libera el cupo: sería tener loteos sin plan.
    assert respuesta.status_code == 409
    assert registro.base.proyecto(slug)


def test_los_loteos_en_linea_no_cuentan_para_el_tope_sin_publicar(tmp_path):
    from consola.proyectos import Limites
    app, base, registro, _ = montar(tmp_path, limites=Limites(sin_pagar=1))
    ctp, ana = entrar(app, "ctp@ctp.cl"), entrar(app, "ana@losrobles.cl")
    uno = crear(ana, "Uno")["slug"]
    dar_plan(ctp, registro, "pro")
    en_linea(registro, uno)

    assert ana.post("/api/proyectos", json={"nombre": "Dos"}).status_code == 201


def test_una_base_de_antes_de_los_planes_gana_las_columnas(tmp_path):
    from sqlalchemy import inspect, text

    from consola.datos import Base
    url = f"sqlite:///{tmp_path / 'vieja.db'}"
    base = Base(url)
    base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    with base.motor.begin() as con:
        for columna in ("plan", "plan_loteos", "plan_nota", "plan_desde", "plan_pedido"):
            con.execute(text(f"ALTER TABLE clientes DROP COLUMN {columna}"))

    otra = Base(url)

    columnas = {c["name"] for c in inspect(otra.motor).get_columns("clientes")}
    assert {"plan", "plan_loteos", "plan_nota", "plan_desde", "plan_pedido"} <= columnas
    [cliente] = otra.clientes()
    assert cliente.plan is None
