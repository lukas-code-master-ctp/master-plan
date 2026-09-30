"""Conectar el inventario de un loteo con Cierra, contra un Cierra de mentira que
habla el contrato de GET /integrations/proyectos y GET /integrations/parcelas."""
import json

import pytest
from fastapi.testclient import TestClient

from consola.acceso import Acceso
from consola.app import crear_app
from consola.cierra import (
    Cierra,
    CierraNoResponde,
    Cifrador,
    ClaveRechazada,
    Conexiones,
    Eleccion,
    EleccionInvalida,
    etapa_sugerida,
    inventario_csv,
    revisar_eleccion,
)
from consola.datos import Base, cierra_claves
from consola.disenos import Disenos
from consola.proyectos import Registro
from consola.tests.test_app import CLAVE, ComandosDePrueba, esperar_trabajo
from consola.trabajos import Trabajos
from pipeline.excel import leer_planilla

CLAVE_CIERRA = "cierra_live_abc123_supersecreto9876"

PROYECTOS = [
    {"id": 10, "nombre": "PRADERAS DE CAUQUENES", "zona": "Maule", "activo": True,
     "parcelas_total": 3, "parcelas_disponibles": 1},
    {"id": 11, "nombre": "PRADERAS DE CAUQUENES ET2", "zona": "Maule", "activo": True,
     "parcelas_total": 2, "parcelas_disponibles": 1},
    {"id": 12, "nombre": "OTRO LOTEO", "zona": None, "activo": True,
     "parcelas_total": 1, "parcelas_disponibles": 0},
]

PARCELAS = [
    {"proyecto_id": 10, "proyecto": "PRADERAS DE CAUQUENES", "numero": "7", "estado": "disponible",
     "precio": 9990000, "moneda": "CLP", "superficie_m2": 5002.125, "servidumbre_m2": None},
    {"proyecto_id": 10, "proyecto": "PRADERAS DE CAUQUENES", "numero": "8", "estado": "reservado",
     "precio": None, "moneda": "CLP", "superficie_m2": 5100, "servidumbre_m2": 940.5},
    {"proyecto_id": 10, "proyecto": "PRADERAS DE CAUQUENES", "numero": "9", "estado": "raro",
     "precio": 0, "moneda": "CLP", "superficie_m2": None, "servidumbre_m2": None},
    {"proyecto_id": 11, "proyecto": "PRADERAS DE CAUQUENES ET2", "numero": "7", "estado": "vendido",
     "precio": 395.5, "moneda": "UF", "superficie_m2": 5000, "servidumbre_m2": None},
    {"proyecto_id": 11, "proyecto": "PRADERAS DE CAUQUENES ET2", "numero": "8", "estado": "disponible",
     "precio": 410, "moneda": "UF", "superficie_m2": 5000, "servidumbre_m2": None},
]


class CierraDeMentira:
    """Lo que contestaría api.cierra.cl, sin salir a internet."""

    def __init__(self):
        self.pedidos = []
        self.caido = False
        self.extra = []      # filas que se agregan tal cual, para probar basura

    def __call__(self, url, clave):
        self.pedidos.append((url, clave))
        if self.caido:
            raise CierraNoResponde("Cierra no contestó. Vuelve a intentarlo en un rato.")
        if clave != CLAVE_CIERRA:
            raise ClaveRechazada("Cierra no aceptó la clave.")
        if url.endswith("/integrations/proyectos"):
            return {"proyectos": PROYECTOS}
        pedidos = {int(i) for i in url.split("proyecto_id=")[1].replace("%2C", ",").split(",")}
        return {"generado": "2026-09-30T12:00:00-03:00",
                "parcelas": [p for p in PARCELAS if p["proyecto_id"] in pedidos] + self.extra}


def montar(tmp_path, cierra=True):
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    for nombre, email in (("CompraTuParcela", "ctp@ctp.cl"), ("Los Robles", "ana@losrobles.cl"),
                          ("Del Valle", "luis@delvalle.cl")):
        base.crear_cliente(nombre, email, nombre)
        base.cambiar_clave(email, CLAVE)
    base.ascender_a_plataforma("ctp@ctp.cl")
    registro = Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas")
    http = CierraDeMentira()
    comandos = ComandosDePrueba()
    app = crear_app(registro=registro, trabajos=Trabajos(), comandos=comandos,
                    acceso=Acceso(base=base, secreto="un-secreto", local=True), base=base,
                    disenos=Disenos(base=base, carpeta=tmp_path / "disenos"),
                    cierra=Cierra("https://cierra.test", http=http) if cierra else None)
    return app, base, registro, http, comandos


def entrar(app, email):
    web = TestClient(app, follow_redirects=False)
    assert web.post("/entrar", data={"email": email, "clave": CLAVE}).status_code == 303
    return web


@pytest.fixture
def entorno(tmp_path):
    app, base, registro, http, comandos = montar(tmp_path)
    ana = entrar(app, "ana@losrobles.cl")
    slug = ana.post("/api/proyectos", json={"nombre": "Praderas"}).json()["slug"]
    return ana, entrar(app, "luis@delvalle.cl"), entrar(app, "ctp@ctp.cl"), slug, base, registro, http, comandos


def conectar(web, slug, proyectos=({"id": 10, "etapa": 1}, {"id": 11, "etapa": 2})):
    assert web.put(f"/api/proyectos/{slug}/cierra/clave", json={"clave": CLAVE_CIERRA}).status_code == 200
    return web.put(f"/api/proyectos/{slug}/cierra", json={"proyectos": list(proyectos)})


# --- lo que no toca la red ----------------------------------------------------------------

@pytest.mark.parametrize("nombre, etapa", [
    ("PRADERAS DE CAUQUENES", 1), ("PRADERAS DE CAUQUENES ET2", 2),
    ("Praderas Etapa 3", 3), ("LOTEO ET 04", 4), ("RETIRO", 1)])
def test_la_etapa_sale_del_sufijo_del_nombre(nombre, etapa):
    assert etapa_sugerida(nombre) == etapa


def test_el_inventario_de_cierra_se_lee_como_la_planilla_con_sus_etapas(tmp_path):
    elecciones = (Eleccion(10, "PRADERAS DE CAUQUENES", 1), Eleccion(11, "PRADERAS DE CAUQUENES ET2", 2))
    ruta = tmp_path / "inventario.csv"
    ruta.write_text(inventario_csv(PARCELAS, elecciones), encoding="utf-8")

    fichas = leer_planilla(ruta)

    assert set(fichas) == {"1-7", "1-8", "1-9", "2-7", "2-8"}
    assert (fichas["1-7"].estado, fichas["1-7"].precio) == ("disponible", 9990000)
    # Con coma decimal: "5002.125" se leería como cinco millones.
    assert fichas["1-7"].superficie_m2 == 5002
    assert fichas["1-8"].servidumbre_m2 == 940.5
    assert fichas["1-9"].estado == "no_disponible"   # un estado que no conocemos no vende
    assert fichas["1-9"].precio is None
    assert (fichas["2-7"].estado, fichas["2-7"].precio, fichas["2-7"].moneda) == ("vendido", 395.5, "UF")


def test_con_una_sola_etapa_la_parcela_queda_con_su_numero(tmp_path):
    ruta = tmp_path / "inventario.csv"
    ruta.write_text(inventario_csv(PARCELAS, (Eleccion(11, "ET2", 2),)), encoding="utf-8")

    assert set(leer_planilla(ruta)) == {"7", "8"}


@pytest.mark.parametrize("pedidas, mensaje", [
    ([], "al menos un proyecto"),
    ([{"id": 99}], "de la lista de Cierra"),
    ([{"id": "x"}], "de la lista de Cierra"),
    ([{"id": 10, "etapa": 1}, {"id": 11, "etapa": 1}], "misma etapa"),
    ([{"id": 10}, {"id": 10}], "dos veces"),
    ([{"id": 10, "etapa": 0}], "de 1 a"),
    ([{"id": 10, "etapa": 500}], "de 1 a"),
])
def test_una_eleccion_que_no_calza_se_explica(pedidas, mensaje):
    from consola.cierra import ProyectoCierra
    disponibles = [ProyectoCierra(p["id"], p["nombre"], 0, 0) for p in PROYECTOS]

    with pytest.raises(EleccionInvalida, match=mensaje):
        revisar_eleccion(pedidas, disponibles)


def test_los_nombres_de_la_eleccion_salen_de_cierra_y_no_del_navegador():
    from consola.cierra import ProyectoCierra
    disponibles = [ProyectoCierra(p["id"], p["nombre"], 0, 0) for p in PROYECTOS]

    [eleccion] = revisar_eleccion([{"id": 11, "nombre": "<script>"}], disponibles)

    assert eleccion == Eleccion(11, "PRADERAS DE CAUQUENES ET2", 2)


def test_la_clave_se_guarda_cifrada_y_con_otro_secreto_no_se_lee(tmp_path):
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    cliente = base.usuario_por_email("ana@losrobles.cl").cliente_id
    Conexiones(base, Cifrador("uno")).guardar_clave(cliente, CLAVE_CIERRA)

    with base.motor.connect() as con:
        guardada = con.execute(cierra_claves.select()).first()

    assert CLAVE_CIERRA not in guardada.cifrada
    assert guardada.pista == "9876"
    assert Conexiones(base, Cifrador("uno")).clave(cliente) == CLAVE_CIERRA
    assert Conexiones(base, Cifrador("otro")).clave(cliente) is None


# --- las rutas ------------------------------------------------------------------------------

def test_sin_cierra_configurado_no_se_ofrece(tmp_path):
    app, *_ = montar(tmp_path, cierra=False)
    ana = entrar(app, "ana@losrobles.cl")
    slug = ana.post("/api/proyectos", json={"nombre": "X"}).json()["slug"]

    assert ana.get(f"/api/proyectos/{slug}/cierra").json() == {"disponible": False}
    assert ana.put(f"/api/proyectos/{slug}/cierra/clave", json={"clave": "x"}).status_code == 404


def test_conectar_trae_el_inventario_y_lo_deja_en_la_carpeta(entorno):
    ana, _, _, slug, _, registro, http, _ = entorno

    respuesta = conectar(ana, slug)

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["parcelas"] == 5
    carpeta = registro.subidas / slug
    assert set(leer_planilla(carpeta / "inventario.csv")) == {"1-7", "1-8", "1-9", "2-7", "2-8"}
    estado = ana.get(f"/api/proyectos/{slug}/cierra").json()
    assert estado["conectado"] is True
    assert estado["pista"] == "9876"
    assert [p["nombre"] for p in estado["proyectos"]] == ["PRADERAS DE CAUQUENES", "PRADERAS DE CAUQUENES ET2"]
    assert estado["sincronizado_en"]
    # La clave viaja en la cabecera, nunca en la URL.
    assert all(CLAVE_CIERRA not in url for url, _ in http.pedidos)
    assert CLAVE_CIERRA not in json.dumps(estado)


def test_una_clave_que_cierra_no_acepta_no_se_guarda(entorno):
    ana, _, _, slug, _, _, _, _ = entorno

    respuesta = ana.put(f"/api/proyectos/{slug}/cierra/clave", json={"clave": "cierra_live_mala"})

    assert respuesta.status_code == 400
    assert "parcelas:read" in respuesta.json()["detail"]
    assert ana.get(f"/api/proyectos/{slug}/cierra").json()["pista"] is None


@pytest.mark.parametrize("clave", ["", "   ", "corta", "con espacios adentro del todo", "x" * 301])
def test_una_clave_mal_pegada_se_rechaza_sin_preguntarle_a_cierra(entorno, clave):
    ana, _, _, slug, _, _, http, _ = entorno

    assert ana.put(f"/api/proyectos/{slug}/cierra/clave", json={"clave": clave}).status_code == 400
    assert http.pedidos == []


def test_las_opciones_traen_la_etapa_sugerida(entorno):
    ana, _, _, slug, _, _, _, _ = entorno
    ana.put(f"/api/proyectos/{slug}/cierra/clave", json={"clave": CLAVE_CIERRA})

    opciones = ana.get(f"/api/proyectos/{slug}/cierra/opciones").json()["proyectos"]

    assert [(p["id"], p["etapa_sugerida"]) for p in opciones] == [(10, 1), (11, 2), (12, 1)]


def test_sin_clave_no_hay_opciones_ni_conexion(entorno):
    ana, _, _, slug, _, _, _, _ = entorno

    assert ana.get(f"/api/proyectos/{slug}/cierra/opciones").status_code == 409
    assert ana.put(f"/api/proyectos/{slug}/cierra", json={"proyectos": [{"id": 10}]}).status_code == 409


def test_otra_loteadora_no_ve_ni_toca_la_conexion(entorno):
    ana, luis, _, slug, _, _, _, _ = entorno
    conectar(ana, slug)

    for pedir in (lambda: luis.get(f"/api/proyectos/{slug}/cierra"),
                  lambda: luis.get(f"/api/proyectos/{slug}/cierra/opciones"),
                  lambda: luis.post(f"/api/proyectos/{slug}/cierra/actualizar"),
                  lambda: luis.delete(f"/api/proyectos/{slug}/cierra"),
                  lambda: luis.delete(f"/api/proyectos/{slug}/cierra/clave"),
                  lambda: luis.put(f"/api/proyectos/{slug}/cierra/clave", json={"clave": CLAVE_CIERRA})):
        assert pedir().status_code == 404
    assert ana.get(f"/api/proyectos/{slug}/cierra").json()["conectado"] is True


def test_la_clave_es_de_la_loteadora_duena_y_no_de_quien_pide(entorno):
    ana, _, ctp, slug, base, _, _, _ = entorno

    # El equipo deja conectado el loteo de Ana con la clave de Ana.
    conectar(ctp, slug)

    ana_id = base.usuario_por_email("ana@losrobles.cl").cliente_id
    with base.motor.connect() as con:
        assert [f.cliente_id for f in con.execute(cierra_claves.select())] == [ana_id]
    assert ana.get(f"/api/proyectos/{slug}/cierra").json()["pista"] == "9876"


def test_si_cierra_se_cae_lo_que_habia_queda(entorno):
    ana, _, _, slug, _, registro, http, _ = entorno
    conectar(ana, slug)
    antes = (registro.subidas / slug / "inventario.csv").read_text()
    http.caido = True

    respuesta = ana.post(f"/api/proyectos/{slug}/cierra/actualizar")

    assert respuesta.status_code == 502
    assert (registro.subidas / slug / "inventario.csv").read_text() == antes


def test_lo_de_cierra_reemplaza_al_inventario_subido_a_mano(entorno):
    ana, _, _, slug, _, registro, _, _ = entorno
    carpeta = registro.subidas / slug
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "inventario.xlsx").write_bytes(b"viejo")

    conectar(ana, slug)

    assert not (carpeta / "inventario.xlsx").exists()


def test_construir_un_loteo_conectado_trae_lo_ultimo_de_cierra(entorno):
    ana, _, _, slug, _, registro, http, _ = entorno
    conectar(ana, slug)
    (registro.subidas / slug / "loteo.kmz").write_bytes(b"kmz")
    pedidos_antes = len(http.pedidos)

    respuesta = ana.post(f"/api/proyectos/{slug}/construir", json={})

    assert respuesta.status_code == 202
    assert "aviso" not in respuesta.json()
    assert len(http.pedidos) == pedidos_antes + 1
    esperar_trabajo(ana, respuesta.json()["id"])


def test_si_cierra_no_contesta_se_construye_igual_y_se_avisa(entorno):
    ana, _, _, slug, _, registro, http, comandos = entorno
    conectar(ana, slug)
    (registro.subidas / slug / "loteo.kmz").write_bytes(b"kmz")
    http.caido = True

    respuesta = ana.post(f"/api/proyectos/{slug}/construir", json={})

    assert respuesta.status_code == 202
    assert "último inventario" in respuesta.json()["aviso"]
    esperar_trabajo(ana, respuesta.json()["id"])
    assert ("construir", slug, False) in comandos.pedidos


def test_desconectar_deja_el_ultimo_inventario(entorno):
    ana, _, _, slug, _, registro, _, _ = entorno
    conectar(ana, slug)

    assert ana.delete(f"/api/proyectos/{slug}/cierra").status_code == 204

    assert ana.get(f"/api/proyectos/{slug}/cierra").json()["conectado"] is False
    assert (registro.subidas / slug / "inventario.csv").exists()


def test_olvidar_la_clave_desconecta_los_loteos_de_esa_loteadora(entorno):
    ana, _, _, slug, _, _, _, _ = entorno
    conectar(ana, slug)

    assert ana.delete(f"/api/proyectos/{slug}/cierra/clave").status_code == 204

    estado = ana.get(f"/api/proyectos/{slug}/cierra").json()
    assert (estado["pista"], estado["conectado"]) == (None, False)


def test_quitar_el_loteo_de_la_lista_borra_su_conexion(entorno):
    ana, _, _, slug, base, _, _, _ = entorno
    conectar(ana, slug)

    assert ana.delete(f"/api/proyectos/{slug}").status_code in (200, 204)

    from consola.datos import cierra_loteos
    with base.motor.connect() as con:
        assert con.execute(cierra_loteos.select()).first() is None


def test_la_clave_cifrada_de_una_loteadora_no_le_sirve_a_otra(tmp_path):
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    cifrador = Cifrador("uno")

    copiada = cifrador.cifrar(1, CLAVE_CIERRA)

    assert cifrador.descifrar(1, copiada) == CLAVE_CIERRA
    assert cifrador.descifrar(2, copiada) is None
    del base


def test_si_cierra_no_entrega_parcelas_se_mantiene_el_inventario(entorno):
    ana, _, _, slug, _, registro, _, _ = entorno
    conectar(ana, slug)
    antes = (registro.subidas / slug / "inventario.csv").read_text()
    PARCELAS_GUARDADAS = list(PARCELAS)
    PARCELAS.clear()
    try:
        respuesta = ana.post(f"/api/proyectos/{slug}/cierra/actualizar")
    finally:
        PARCELAS.extend(PARCELAS_GUARDADAS)

    assert respuesta.status_code == 502
    assert "inventario anterior" in respuesta.json()["detail"]
    assert (registro.subidas / slug / "inventario.csv").read_text() == antes


def test_datos_raros_de_cierra_no_rompen_la_construccion(entorno):
    ana, _, _, slug, _, registro, http, _ = entorno
    conectar(ana, slug)
    (registro.subidas / slug / "loteo.kmz").write_bytes(b"kmz")
    http.extra = ["no soy una parcela"]

    respuesta = ana.post(f"/api/proyectos/{slug}/construir", json={})

    assert respuesta.status_code == 202
    assert "último inventario" in respuesta.json()["aviso"]
    esperar_trabajo(ana, respuesta.json()["id"])


def test_numeros_imposibles_quedan_vacios():
    fila = {"proyecto_id": 10, "numero": "7", "estado": "disponible", "precio": 10 ** 400,
            "moneda": "CLP" * 20, "superficie_m2": float("nan")}

    texto = inventario_csv([fila], (Eleccion(10, "X", 1),))

    assert texto.splitlines()[1] == "7,CIERRA,Disponible,,CLPCLPCL,,"


def test_una_clave_de_otra_cuenta_desconecta_los_loteos(entorno):
    ana, _, _, slug, base, _, _, _ = entorno
    conectar(ana, slug)
    ana_id = base.usuario_por_email("ana@losrobles.cl").cliente_id
    conexiones = Conexiones(base, Cifrador("un-secreto"))

    conexiones.guardar_clave(ana_id, "cierra_live_otra_cuenta_0000")

    assert ana.get(f"/api/proyectos/{slug}/cierra").json()["conectado"] is False


def test_pegar_la_misma_clave_no_desconecta_nada(entorno):
    ana, _, _, slug, _, _, _, _ = entorno
    conectar(ana, slug)

    ana.put(f"/api/proyectos/{slug}/cierra/clave", json={"clave": CLAVE_CIERRA})

    assert ana.get(f"/api/proyectos/{slug}/cierra").json()["conectado"] is True


def test_cierra_sin_https_no_se_acepta(monkeypatch):
    from consola.cierra import cierra_del_entorno
    monkeypatch.setenv("CIERRA_API_URL", "http://api.cierra.cl")
    with pytest.raises(ValueError, match="https"):
        cierra_del_entorno()
    monkeypatch.setenv("CIERRA_API_URL", "http://127.0.0.1:8790")
    assert cierra_del_entorno() is not None


def test_una_redireccion_no_se_sigue_con_la_clave():
    from consola.cierra import _SinRedirecciones
    assert _SinRedirecciones().redirect_request(None, None, 302, "Found", {}, "https://otro.cl") is None
