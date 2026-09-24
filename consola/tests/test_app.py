"""La API de la consola."""
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from consola.acceso import Acceso
from consola.app import crear_app
from consola.datos import Base
from consola.proyectos import Registro
from consola.trabajos import Trabajos

CLAVE = "la-clave-de-prueba"


def carpeta_de_loteo(raiz, nombre="Loteo"):
    carpeta = raiz / nombre
    (carpeta / "fotos").mkdir(parents=True)
    (carpeta / "loteo.kmz").write_bytes(b"kmz")
    (carpeta / "fotos" / "a.JPG").write_bytes(b"jpg" * 400)
    (carpeta / "proyecto.json").write_text(json.dumps({"nombre": nombre}), encoding="utf-8")
    return carpeta


class ComandosDePrueba:
    """En vez del pipeline de verdad, un guion que imprime y termina bien."""

    def __init__(self):
        self.pedidos = []

    def _guion(self, texto):
        return [sys.executable, "-c", f"print({texto!r})"]

    def construir(self, proyecto, sin_imagenes=False):
        self.pedidos.append(("construir", proyecto.slug, sin_imagenes))
        return self._guion(f"construyendo {proyecto.slug}")

    def control_de_calce(self, proyecto):
        self.pedidos.append(("calce", proyecto.slug, None))
        return self._guion(f"calce de {proyecto.slug}")

    def publicar(self, proyecto, vercel_proyecto, crear=False):
        self.pedidos.append(("publicar", proyecto.slug, vercel_proyecto, crear))
        return self._guion(f"publicando {proyecto.slug}")


def montar(tmp_path, local=True, crm_por_defecto=None):
    """La consola entera sobre una base de prueba, con dos loteadoras dentro."""
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    for nombre, email in (("CompraTuParcela", "ctp@ctp.cl"),
                          ("Los Robles", "ana@losrobles.cl"),
                          ("Del Valle", "luis@delvalle.cl")):
        base.crear_cliente(nombre, email, nombre)
        base.cambiar_clave(email, CLAVE)
    base.ascender_a_plataforma("ctp@ctp.cl")
    registro = Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas",
                        crm_por_defecto=crm_por_defecto)
    comandos = ComandosDePrueba()
    app = crear_app(registro=registro, trabajos=Trabajos(), comandos=comandos,
                    acceso=Acceso(base=base, secreto="un-secreto", local=local), base=base)
    return app, base, registro, comandos


def entrar(app, email="ctp@ctp.cl"):
    cliente = TestClient(app, follow_redirects=False)
    respuesta = cliente.post("/entrar", data={"email": email, "clave": CLAVE})
    assert respuesta.status_code == 303, respuesta.text
    return cliente


@pytest.fixture
def entorno(tmp_path):
    app, _, registro, comandos = montar(tmp_path)
    return entrar(app), registro, comandos


@pytest.fixture
def ana_y_luis(tmp_path):
    """Dos loteadoras y el equipo de CTP, entrando a la misma consola."""
    app, _, registro, comandos = montar(tmp_path)
    return (entrar(app, "ctp@ctp.cl"), entrar(app, "ana@losrobles.cl"),
            entrar(app, "luis@delvalle.cl"), registro, comandos)


def id_de(registro, email):
    return registro.base.usuario_por_email(email).cliente_id


def esperar_trabajo(cliente, identificador, limite=15.0):
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        cuerpo = cliente.get(f"/api/trabajos/{identificador}").json()
        if cuerpo["terminado"]:
            return cuerpo
        time.sleep(0.02)
    raise AssertionError("el trabajo no terminó")


def test_la_consola_sirve_su_pagina(entorno):
    cliente, _, _ = entorno

    respuesta = cliente.get("/")

    assert respuesta.status_code == 200
    assert "text/html" in respuesta.headers["content-type"]


def test_sin_proyectos_la_lista_viene_vacia(entorno):
    cliente, _, _ = entorno

    assert cliente.get("/api/proyectos").json() == []


def test_vincular_una_carpeta(entorno, tmp_path):
    cliente, _, _ = entorno
    carpeta = carpeta_de_loteo(tmp_path, "Praderas de Cauquenes")

    respuesta = cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta)})

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["slug"] == "praderas-de-cauquenes"
    assert cuerpo["construido"] is False
    assert cuerpo["fuentes_encontradas"]["panoramicas"] == 1
    assert cuerpo["fuentes_encontradas"]["kmz"] == "loteo.kmz"


def test_vincular_una_carpeta_que_no_sirve_explica_por_que(entorno, tmp_path):
    cliente, _, _ = entorno
    (tmp_path / "vacia").mkdir()

    respuesta = cliente.post("/api/proyectos/vincular", json={"ruta": str(tmp_path / "vacia")})

    assert respuesta.status_code == 400
    assert "KMZ" in respuesta.json()["detail"]


def test_desplegada_no_se_pueden_vincular_carpetas_del_servidor(tmp_path):
    """Es la máquina de otro: registrar una ruta cualquiera sería leerle el disco."""
    app, _, _, _ = montar(tmp_path, local=False)
    cliente = entrar(app)

    respuesta = cliente.post("/api/proyectos/vincular",
                             json={"ruta": str(carpeta_de_loteo(tmp_path))})

    assert respuesta.status_code == 403
    assert cliente.get("/api/sesion").json()["puede_vincular"] is False


def habilitar(cliente, cliente_id, nombre, cobro="transferencia 4821"):
    respuesta = cliente.post(f"/api/plataforma/clientes/{cliente_id}/proyectos",
                             json={"nombre": nombre, "nota_cobro": cobro})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["slug"]


def test_subir_los_archivos_a_un_loteo_habilitado(entorno, tmp_path):
    cliente, registro, _ = entorno
    slug = habilitar(cliente, id_de(registro, "ana@losrobles.cl"), "Vive Cauquenes")

    respuesta = cliente.post(f"/api/proyectos/{slug}/archivos", files=[
        ("archivos", ("loteo.kmz", b"kmz", "application/octet-stream")),
        ("archivos", ("POSICION 01/a.JPG", b"jpg", "image/jpeg")),
    ])

    assert respuesta.status_code == 201
    assert respuesta.json()["slug"] == "vive-cauquenes"
    assert respuesta.json()["fuentes_encontradas"]["panoramicas"] == 1


def test_subir_sin_kmz_avisa(entorno):
    cliente, registro, _ = entorno
    slug = habilitar(cliente, id_de(registro, "ana@losrobles.cl"), "X")

    respuesta = cliente.post(f"/api/proyectos/{slug}/archivos", files=[
        ("archivos", ("a.JPG", b"jpg", "image/jpeg")),
    ])

    assert respuesta.status_code == 400
    assert "KMZ" in respuesta.json()["detail"]


def test_ajustar_los_datos_del_proyecto(entorno, tmp_path):
    cliente, _, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})

    respuesta = cliente.patch("/api/proyectos/loteo", json={
        "etapa": "Etapa 1", "whatsapp": "56911111111",
        "despegue": [-72.1, -35.9], "referencias": ["Cauquenes", "Pelluhue"],
    })

    assert respuesta.status_code == 200
    assert respuesta.json()["etapa"] == "Etapa 1"
    assert respuesta.json()["referencias"] == ["Cauquenes", "Pelluhue"]


def test_construir_lanza_el_pipeline_y_deja_ver_el_avance(entorno, tmp_path):
    cliente, _, comandos = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})

    respuesta = cliente.post("/api/proyectos/loteo/construir", json={"sin_imagenes": True})

    assert respuesta.status_code == 202
    trabajo = esperar_trabajo(cliente, respuesta.json()["id"])
    assert trabajo["estado"] == "listo"
    # Construir deja además el control de calce hecho: es lo que hay que mirar antes
    # de publicar, y pedirlo aparte se olvida.
    assert trabajo["lineas"] == ["construyendo loteo", "calce de loteo"]
    assert comandos.pedidos == [("construir", "loteo", True), ("calce", "loteo", None)]


def test_las_lineas_se_piden_por_tramos(entorno, tmp_path):
    cliente, _, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    identificador = cliente.post("/api/proyectos/loteo/construir", json={}).json()["id"]
    esperar_trabajo(cliente, identificador)

    cuerpo = cliente.get(f"/api/trabajos/{identificador}", params={"desde": 1}).json()

    assert cuerpo["desde"] == 1 and cuerpo["lineas"] == ["calce de loteo"]
    assert cuerpo["total"] == 2


def test_no_deja_publicar_lo_que_no_esta_construido(entorno, tmp_path):
    cliente, _, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})

    respuesta = cliente.post("/api/proyectos/loteo/publicar")

    assert respuesta.status_code == 409
    assert "construido" in respuesta.json()["detail"]


def construir_a_mano(registro, salidas, slug):
    """Deja la salida como la dejaría el pipeline, para probar lo que viene después."""
    from pipeline import config
    salida = config.Salida(salidas / slug)
    salida.datos.mkdir(parents=True, exist_ok=True)
    (salida.datos / "parcelas.json").write_text(
        '{"resumen": {"total": 2, "por_estado": {"disponible": 2}}, "generado": "2026-09-24T10:00:00"}')
    (salida.datos / "vistas.json").write_text(
        '{"vistas": [{"id": "p01-210", "diagnostico": {"error_elevacion": 0.4, "calibracion": {"mejora": 0.2}}}]}')


def test_publicar_usa_el_script_de_publicacion(entorno, tmp_path):
    cliente, registro, comandos = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, registro.salidas, "loteo")

    identificador = cliente.post("/api/proyectos/loteo/publicar",
                                 json={"confirmado": True}).json()["id"]

    assert esperar_trabajo(cliente, identificador)["estado"] == "listo"
    # La primera vez hay que crear el proyecto en el hosting.
    assert comandos.pedidos == [("publicar", "loteo", "masterplan-loteo", True)]


def test_no_deja_construir_dos_veces_a_la_vez(entorno, tmp_path, monkeypatch):
    cliente, _, comandos = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    monkeypatch.setattr(comandos, "construir",
                        lambda p, sin_imagenes=False: [sys.executable, "-c", "import time; time.sleep(2)"])
    cliente.post("/api/proyectos/loteo/construir", json={})

    respuesta = cliente.post("/api/proyectos/loteo/construir", json={})

    assert respuesta.status_code == 409
    assert "ya está" in respuesta.json()["detail"]


def test_construir_un_proyecto_que_no_existe_da_404(entorno):
    cliente, _, _ = entorno

    assert cliente.post("/api/proyectos/fantasma/construir", json={}).status_code == 404


def test_olvidar_un_proyecto(entorno, tmp_path):
    cliente, _, _ = entorno
    carpeta = carpeta_de_loteo(tmp_path)
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta)})

    assert cliente.delete("/api/proyectos/loteo").status_code == 204
    assert cliente.get("/api/proyectos").json() == []
    assert carpeta.is_dir()


def test_el_control_de_calce_se_sirve_como_imagen(entorno, tmp_path):
    cliente, registro, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    qa = registro.salidas / "loteo" / "control-calce"
    qa.mkdir(parents=True, exist_ok=True)
    (qa / "p01-210.jpg").write_bytes(b"\xff\xd8\xff falso jpeg")

    assert cliente.get("/api/proyectos").json()[0]["calce"] == ["p01-210.jpg"]
    respuesta = cliente.get("/calce/loteo/p01-210.jpg")
    assert respuesta.status_code == 200 and respuesta.content.startswith(b"\xff\xd8\xff")


def test_no_se_puede_pedir_cualquier_archivo_por_la_ruta_del_calce(entorno, tmp_path):
    cliente, _, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})

    assert cliente.get("/calce/loteo/..%2F..%2Fproyectos.json").status_code in (400, 404)


def test_un_proyecto_construido_muestra_su_resumen(entorno, tmp_path):
    cliente, registro, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, registro.salidas, "loteo")

    proyecto = cliente.get("/api/proyectos").json()[0]

    assert proyecto["construido"] is True
    assert proyecto["resumen"]["parcelas"] == 2
    assert proyecto["resumen"]["calce"] == [{"vista": "p01-210", "error_sol": 0.4, "mejora": 0.2}]
    assert proyecto["url"] == "https://masterplan-loteo.vercel.app"


@pytest.mark.parametrize("ruta,tipo", [
    ("/consola.css", "text/css"),
    ("/consola.js", "text/javascript"),
    ("/fuente.woff2", "font/woff2"),
])
def test_la_pagina_trae_sus_propios_archivos(entorno, ruta, tipo):
    cliente, _, _ = entorno

    respuesta = cliente.get(ruta)

    assert respuesta.status_code == 200
    assert respuesta.headers["content-type"].startswith(tipo)


def test_publicar_exige_confirmacion_explicita(entorno, tmp_path):
    """Publicar deja el loteo a la vista de cualquiera: un POST suelto no alcanza."""
    cliente, registro, comandos = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, registro.salidas, "loteo")

    respuesta = cliente.post("/api/proyectos/loteo/publicar", json={})

    assert respuesta.status_code == 428
    assert "confirm" in respuesta.json()["detail"].lower()
    assert comandos.pedidos == []


def test_con_la_confirmacion_publica(entorno, tmp_path):
    cliente, registro, comandos = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, registro.salidas, "loteo")

    respuesta = cliente.post("/api/proyectos/loteo/publicar", json={"confirmado": True})

    assert respuesta.status_code == 202
    assert esperar_trabajo(cliente, respuesta.json()["id"])["estado"] == "listo"
    assert comandos.pedidos == [("publicar", "loteo", "masterplan-loteo", True)]


# --- dónde queda publicado cada loteo -------------------------------------------

def test_sin_dominio_propio_la_url_es_la_de_vercel(entorno, tmp_path, monkeypatch):
    monkeypatch.delenv("MASTERPLAN_DOMINIO", raising=False)
    cliente, _, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})

    assert cliente.get("/api/proyectos").json()[0]["url"] == "https://masterplan-loteo.vercel.app"


def test_con_dominio_propio_cada_loteo_es_un_subdominio(tmp_path, monkeypatch):
    """Cuando exista tumasterplan.cl, el loteo vive en <slug>.tumasterplan.cl."""
    monkeypatch.setenv("MASTERPLAN_DOMINIO", "tumasterplan.cl")
    app, _, _, _ = montar(tmp_path)
    cliente = entrar(app)
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})

    assert cliente.get("/api/proyectos").json()[0]["url"] == "https://loteo.tumasterplan.cl"


def test_republicar_no_vuelve_a_crear_el_proyecto_en_el_hosting(entorno, tmp_path):
    """Pedir `--crear` de nuevo sería intentar pisar un proyecto que ya existe."""
    cliente, registro, comandos = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, registro.salidas, "loteo")
    registro.base.anotar_publicacion("loteo", "masterplan-loteo",
                                     "https://masterplan-loteo.vercel.app")

    cliente.post("/api/proyectos/loteo/publicar", json={"confirmado": True})

    assert comandos.pedidos == [("publicar", "loteo", "masterplan-loteo", False)]


def test_al_terminar_de_publicar_se_guarda_la_url_real(entorno, tmp_path):
    """La consola muestra la URL que devolvió el hosting, no una armada a mano."""
    cliente, registro, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, registro.salidas, "loteo")
    rastro = registro.salidas / "loteo" / "publicacion.json"
    rastro.write_text('{"proyecto": "masterplan-loteo", "url": "https://otra-url.vercel.app"}')

    identificador = cliente.post("/api/proyectos/loteo/publicar",
                                 json={"confirmado": True}).json()["id"]
    esperar_trabajo(cliente, identificador)

    for _ in range(200):
        if registro.base.proyecto("loteo").url_publicada:
            break
        time.sleep(0.01)
    assert registro.base.proyecto("loteo").url_publicada == "https://otra-url.vercel.app"
    assert cliente.get("/api/proyectos").json()[0]["url"] == "https://otra-url.vercel.app"


def test_un_loteo_sin_publicar_muestra_donde_iria(entorno, tmp_path):
    cliente, _, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})

    proyecto = cliente.get("/api/proyectos").json()[0]

    assert proyecto["publicado"] is False
    assert proyecto["url"] == "https://masterplan-loteo.vercel.app"


# --- que un cliente no alcance lo de otro ----------------------------------------
#
# El inventario de abajo es el contrato: cada ruta de la consola dice qué pasa
# cuando la pide alguien que no es dueño de lo que nombra. El test que lo compara
# con `app.routes` falla si alguien agrega una ruta y no la declara, que es la
# forma en que este aislamiento se erosionaría: de a una ruta por vez.

SIN_SESION = "no pide nada: es la puerta o un archivo de la propia página"
SOLO_SUYO = "solo habla de lo de quien pide; no nombra ningún loteo ajeno"
AJENO_404 = "nombra un loteo: si no es suyo, 404"
SOLO_CTP = "back-office: una loteadora recibe 403"

RUTAS = {
    ("GET", "/entrar"): SIN_SESION,
    ("POST", "/entrar"): SIN_SESION,
    ("POST", "/salir"): SIN_SESION,
    ("GET", "/consola.css"): SIN_SESION,
    ("GET", "/fuente.woff2"): SIN_SESION,
    ("GET", "/"): SOLO_SUYO,
    ("GET", "/consola.js"): SOLO_SUYO,
    ("GET", "/api/sesion"): SOLO_SUYO,
    ("POST", "/api/clave"): SOLO_SUYO,
    ("GET", "/api/proyectos"): SOLO_SUYO,
    ("PATCH", "/api/proyectos/{slug}"): AJENO_404,
    ("DELETE", "/api/proyectos/{slug}"): AJENO_404,
    ("POST", "/api/proyectos/{slug}/archivos"): AJENO_404,
    ("POST", "/api/proyectos/{slug}/construir"): AJENO_404,
    ("POST", "/api/proyectos/{slug}/publicar"): AJENO_404,
    ("GET", "/api/trabajos/{identificador}"): AJENO_404,
    ("GET", "/calce/{slug}/{archivo}"): AJENO_404,
    ("POST", "/api/proyectos/vincular"): SOLO_CTP,
    ("GET", "/api/plataforma/clientes"): SOLO_CTP,
    ("POST", "/api/plataforma/clientes"): SOLO_CTP,
    ("POST", "/api/plataforma/clientes/{cliente_id}/usuarios"): SOLO_CTP,
    ("POST", "/api/plataforma/clientes/{cliente_id}/estado"): SOLO_CTP,
    ("POST", "/api/plataforma/clientes/{cliente_id}/proyectos"): SOLO_CTP,
    ("GET", "/api/plataforma/historial"): SOLO_CTP,
}


def test_toda_ruta_de_la_consola_declara_que_pasa_con_un_cliente_ajeno(tmp_path):
    app, _, _, _ = montar(tmp_path)

    reales = {(metodo, ruta.path) for ruta in app.routes
              for metodo in getattr(ruta, "methods", ()) if metodo not in ("HEAD", "OPTIONS")}

    assert reales - set(RUTAS) == set(), (
        "hay rutas sin declarar en RUTAS: agrégalas diciendo qué pasa cuando las "
        "pide un cliente que no es dueño de lo que nombran, y prueba ese caso")
    assert set(RUTAS) - reales == set(), "RUTAS declara rutas que ya no existen"


def test_toda_ruta_de_plataforma_esta_declarada_como_tal(tmp_path):
    """Al revés que el de arriba: que nadie cuelgue algo de /api/plataforma/ y lo
    declare como si cualquiera pudiera pedirlo."""
    for (_, ruta), quien in RUTAS.items():
        if ruta.startswith("/api/plataforma/"):
            assert quien == SOLO_CTP, f"{ruta} cuelga del back-office pero no lo dice"


def de_ana(ctp, ana, registro, nombre="De Ana"):
    """Un loteo habilitado a nombre de Ana, con su KMZ adentro."""
    slug = habilitar(ctp, id_de(registro, "ana@losrobles.cl"), nombre)
    respuesta = ana.post(f"/api/proyectos/{slug}/archivos",
                         files=[("archivos", ("loteo.kmz", b"kmz", "application/octet-stream"))])
    assert respuesta.status_code == 201, respuesta.text
    return slug


@pytest.mark.parametrize("pedir", [
    lambda web, slug: web.patch(f"/api/proyectos/{slug}", json={"etapa": "Etapa 9"}),
    lambda web, slug: web.delete(f"/api/proyectos/{slug}"),
    lambda web, slug: web.post(f"/api/proyectos/{slug}/construir", json={}),
    lambda web, slug: web.post(f"/api/proyectos/{slug}/publicar", json={"confirmado": True}),
    lambda web, slug: web.get(f"/calce/{slug}/p01-210.jpg"),
    lambda web, slug: web.post(f"/api/proyectos/{slug}/archivos",
                               files=[("archivos", ("x.kmz", b"kmz", "application/octet-stream"))]),
], ids=["ajustar", "olvidar", "construir", "publicar", "calce", "subir"])
def test_el_loteo_de_otra_contesta_404_en_todas_las_rutas(ana_y_luis, pedir):
    ctp, ana, luis, registro, comandos = ana_y_luis
    slug = de_ana(ctp, ana, registro)

    assert pedir(luis, slug).status_code == 404

    # Ni se tocó: ni se lanzó un comando ni se perdió el loteo.
    assert comandos.pedidos == []
    assert [p["slug"] for p in ana.get("/api/proyectos").json()] == [slug]


def test_el_avance_de_una_construccion_ajena_tampoco_se_ve(ana_y_luis):
    """El avance cuenta qué loteo es y qué está pasando con él: se pide igual que el loteo."""
    ctp, ana, luis, registro, _ = ana_y_luis
    slug = de_ana(ctp, ana, registro)
    identificador = ana.post(f"/api/proyectos/{slug}/construir", json={}).json()["id"]

    assert luis.get(f"/api/trabajos/{identificador}").status_code == 404
    assert ana.get(f"/api/trabajos/{identificador}").status_code == 200


def test_un_trabajo_que_no_existe_tambien_da_404(ana_y_luis):
    _, ana, _, _, _ = ana_y_luis

    assert ana.get("/api/trabajos/noexiste").status_code == 404


def test_la_lista_de_cada_una_es_la_suya(ana_y_luis):
    ctp, ana, luis, registro, _ = ana_y_luis
    de_ana(ctp, ana, registro, "De Ana")
    habilitar(ctp, id_de(registro, "luis@delvalle.cl"), "De Luis")

    assert [p["slug"] for p in ana.get("/api/proyectos").json()] == ["de-ana"]
    assert [p["slug"] for p in luis.get("/api/proyectos").json()] == ["de-luis"]


def test_ctp_ve_los_loteos_de_todas(ana_y_luis):
    ctp, ana, _, registro, _ = ana_y_luis
    de_ana(ctp, ana, registro, "De Ana")
    habilitar(ctp, id_de(registro, "luis@delvalle.cl"), "De Luis")

    assert sorted(p["slug"] for p in ctp.get("/api/proyectos").json()) == ["de-ana", "de-luis"]


def test_dos_loteadoras_con_el_mismo_nombre_de_loteo_no_se_pisan(ana_y_luis):
    """Antes el slug salía del nombre: la segunda en publicar desplegaba encima del
    sitio de la primera, y `vercel project add || true` se comía el error."""
    ctp, _, _, registro, _ = ana_y_luis

    una = habilitar(ctp, id_de(registro, "ana@losrobles.cl"), "Las Araucarias")
    otra = habilitar(ctp, id_de(registro, "luis@delvalle.cl"), "Las Araucarias")

    assert una == "las-araucarias"
    assert otra == "las-araucarias-2"


# --- el back-office es solo de CTP ------------------------------------------------

@pytest.mark.parametrize("pedir", [
    lambda web, cid: web.get("/api/plataforma/clientes"),
    lambda web, cid: web.post("/api/plataforma/clientes",
                              json={"nombre": "Trucha", "email": "t@t.cl"}),
    lambda web, cid: web.post(f"/api/plataforma/clientes/{cid}/usuarios",
                              json={"email": "otro@t.cl"}),
    lambda web, cid: web.post(f"/api/plataforma/clientes/{cid}/estado",
                              json={"estado": "suspendido"}),
    lambda web, cid: web.post(f"/api/plataforma/clientes/{cid}/proyectos",
                              json={"nombre": "Gratis", "nota_cobro": "no pagué"}),
    lambda web, cid: web.get("/api/plataforma/historial"),
], ids=["listar", "crear cliente", "crear cuenta", "suspender", "habilitar loteo", "historial"])
def test_una_loteadora_no_entra_al_back_office(ana_y_luis, pedir):
    """Sobre todo la penúltima: si un cliente pudiera habilitarse loteos solo,
    el cobro no existiría."""
    _, ana, _, registro, _ = ana_y_luis

    assert pedir(ana, id_de(registro, "ana@losrobles.cl")).status_code == 403


def test_vincular_una_carpeta_tampoco_es_para_las_loteadoras(ana_y_luis, tmp_path):
    _, ana, _, _, _ = ana_y_luis

    respuesta = ana.post("/api/proyectos/vincular",
                         json={"ruta": str(carpeta_de_loteo(tmp_path))})

    assert respuesta.status_code == 403


# --- dar de alta una loteadora y cobrarle -----------------------------------------

def test_crear_una_loteadora_devuelve_su_clave_una_sola_vez(ana_y_luis):
    ctp, _, _, registro, _ = ana_y_luis

    respuesta = ctp.post("/api/plataforma/clientes",
                         json={"nombre": "Bosques del Sur", "email": "pia@bosques.cl",
                               "duenio": "Pía Soto"})

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    clave = cuerpo["clave_provisional"]
    assert len(clave) >= 12
    assert cuerpo["cuentas"] == ["pia@bosques.cl"]
    assert cuerpo["loteos"] == 0
    # Con esa clave se entra, y no vuelve a aparecer en ninguna respuesta.
    assert "clave_provisional" not in ctp.get("/api/plataforma/clientes").json()[0]
    assert registro.base.clave_valida(registro.base.usuario_por_email("pia@bosques.cl"), clave)


def test_no_se_puede_repetir_el_correo_de_otra_loteadora(ana_y_luis):
    ctp, _, _, _, _ = ana_y_luis

    respuesta = ctp.post("/api/plataforma/clientes",
                         json={"nombre": "Otra", "email": "ana@losrobles.cl"})

    assert respuesta.status_code == 409


def test_un_loteo_no_se_habilita_sin_decir_como_se_pagó(ana_y_luis):
    """No hay pasarela: el cobro pasa por transferencia y esta línea de texto es
    todo el control de pago que existe. Sin ella no se habilita nada."""
    ctp, _, _, registro, _ = ana_y_luis

    respuesta = ctp.post(f"/api/plataforma/clientes/{id_de(registro, 'ana@losrobles.cl')}/proyectos",
                         json={"nombre": "Las Araucarias"})

    assert respuesta.status_code == 402
    assert ctp.get("/api/proyectos").json() == []


def test_habilitar_un_loteo_lo_deja_vacio_esperando_las_fotos(ana_y_luis):
    ctp, ana, _, registro, _ = ana_y_luis

    slug = habilitar(ctp, id_de(registro, "ana@losrobles.cl"), "Las Araucarias", "transf. 4821")

    assert registro.base.proyecto(slug).pagado is True
    mio = ana.get("/api/proyectos").json()[0]
    assert mio["slug"] == slug
    assert mio["construido"] is False
    assert mio["fuentes_encontradas"]["kmz"] is None


def test_suspender_una_loteadora_la_deja_afuera_en_la_peticion_siguiente(ana_y_luis):
    ctp, ana, _, registro, _ = ana_y_luis
    assert ana.get("/api/proyectos").status_code == 200

    ctp.post(f"/api/plataforma/clientes/{id_de(registro, 'ana@losrobles.cl')}/estado",
             json={"estado": "suspendido"})

    assert ana.get("/api/proyectos").status_code == 401


def test_ctp_no_puede_suspenderse_a_si_misma(ana_y_luis):
    """No hay nadie por encima que lo arregle: quedaría la consola sin operador."""
    ctp, _, _, registro, _ = ana_y_luis

    respuesta = ctp.post(f"/api/plataforma/clientes/{id_de(registro, 'ctp@ctp.cl')}/estado",
                         json={"estado": "suspendido"})

    assert respuesta.status_code == 409
    assert ctp.get("/api/plataforma/clientes").status_code == 200


def test_agregar_una_cuenta_mas_a_una_loteadora(ana_y_luis):
    ctp, _, _, registro, _ = ana_y_luis

    respuesta = ctp.post(f"/api/plataforma/clientes/{id_de(registro, 'ana@losrobles.cl')}/usuarios",
                         json={"email": "socio@losrobles.cl", "nombre": "Socio"})

    assert respuesta.status_code == 201
    assert len(respuesta.json()["clave_provisional"]) >= 12
    cuentas = [c for c in ctp.get("/api/plataforma/clientes").json()
               if c["nombre"] == "Los Robles"][0]["cuentas"]
    assert "socio@losrobles.cl" in cuentas


def test_lo_que_decide_algo_queda_anotado(ana_y_luis):
    """Sin pasarela, el historial es lo único que dice quién habilitó qué y por
    qué cobro. Construir y publicar no se anotan: eso está en el disco."""
    ctp, ana, _, registro, _ = ana_y_luis
    slug = de_ana(ctp, ana, registro)

    historial = ctp.get("/api/plataforma/historial").json()

    assert [h["que"] for h in historial] == ["loteo habilitado"]
    assert "transferencia 4821" in historial[0]["detalle"]
    assert slug in historial[0]["detalle"]
