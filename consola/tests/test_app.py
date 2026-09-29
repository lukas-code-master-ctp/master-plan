"""La API de la consola."""
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from consola.acceso import Acceso
from consola.app import crear_app
from consola.datos import Base
from consola.proyectos import Limites, Registro
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


def montar(tmp_path, local=True, crm_por_defecto=None, limites=None):
    """La consola entera sobre una base de prueba, con dos loteadoras dentro."""
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    for nombre, email in (("CompraTuParcela", "ctp@ctp.cl"),
                          ("Los Robles", "ana@losrobles.cl"),
                          ("Del Valle", "luis@delvalle.cl")):
        base.crear_cliente(nombre, email, nombre)
        base.cambiar_clave(email, CLAVE)
    base.ascender_a_plataforma("ctp@ctp.cl")
    registro = Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas",
                        crm_por_defecto=crm_por_defecto, limites=limites)
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
    ("/js/app.js", "text/javascript"),
    ("/js/plano.js", "text/javascript"),
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
    ("GET", "/js/{modulo}"): SOLO_SUYO,
    ("GET", "/api/sesion"): SOLO_SUYO,
    ("POST", "/api/clave"): SOLO_SUYO,
    ("GET", "/api/proyectos"): SOLO_SUYO,
    ("POST", "/api/proyectos"): SOLO_SUYO,
    ("GET", "/api/proyectos/{slug}/portada"): AJENO_404,
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
    ("POST", "/api/plataforma/proyectos/{slug}/pago"): SOLO_CTP,
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
    lambda web, slug: web.get(f"/api/proyectos/{slug}/portada"),
    lambda web, slug: web.post(f"/api/proyectos/{slug}/archivos",
                               files=[("archivos", ("x.kmz", b"kmz", "application/octet-stream"))]),
], ids=["ajustar", "olvidar", "construir", "publicar", "calce", "portada", "subir"])
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
    lambda web, cid: web.post("/api/plataforma/proyectos/cualquiera/pago",
                              json={"nota_cobro": "me lo regalo"}),
], ids=["listar", "crear cliente", "crear cuenta", "suspender", "habilitar loteo", "historial",
        "anotar pago"])
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


# --- publicar un loteo al que nadie puede escribirle -------------------------------

def test_la_sesion_dice_de_que_loteadora_es(entorno, registro=None):
    """La página lo usa para no ofrecer "suspender" sobre la propia loteadora,
    que es lo único que el back-office rechaza siempre."""
    cliente, registro, _ = entorno

    cuerpo = cliente.get("/api/sesion").json()

    assert cuerpo["cliente_id"] == id_de(registro, "ctp@ctp.cl")
    assert cuerpo["cliente"] == "CompraTuParcela"


def test_un_loteo_sin_whatsapp_se_marca_como_sin_contacto(entorno, tmp_path):
    """Praderas salió publicado así: el comprador mira, se decide, y no hay a quién
    escribirle. El botón de contacto del visor solo aparece si hay número."""
    cliente, _, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})

    assert cliente.get("/api/proyectos").json()[0]["sin_contacto"] is True

    cliente.patch("/api/proyectos/loteo", json={"whatsapp": "56912345678"})

    assert cliente.get("/api/proyectos").json()[0]["sin_contacto"] is False


# --- el cliente se crea sus masters; el cobro va al publicar ----------------------

def crear(web, nombre="Praderas de Cauquenes"):
    respuesta = web.post("/api/proyectos", json={"nombre": nombre})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def test_una_loteadora_se_crea_su_propio_master(ana_y_luis):
    _, ana, luis, registro, _ = ana_y_luis

    creado = crear(ana)

    assert creado["slug"] == "praderas-de-cauquenes"
    assert creado["pagado"] is False
    assert creado["construido"] is False
    guardado = registro.base.proyecto("praderas-de-cauquenes")
    assert guardado.cliente_id == id_de(registro, "ana@losrobles.cl")
    assert [p["slug"] for p in ana.get("/api/proyectos").json()] == ["praderas-de-cauquenes"]
    assert luis.get("/api/proyectos").json() == []


def test_crear_un_master_sin_nombre_avisa(ana_y_luis):
    _, ana, _, _, _ = ana_y_luis

    respuesta = ana.post("/api/proyectos", json={"nombre": "  "})

    assert respuesta.status_code == 400


def test_no_se_repite_el_nombre_de_un_master_propio(ana_y_luis):
    _, ana, luis, _, _ = ana_y_luis
    crear(ana)

    assert ana.post("/api/proyectos", json={"nombre": "Praderas de Cauquenes"}).status_code == 409
    # Otra loteadora sí puede llamar igual al suyo.
    assert luis.post("/api/proyectos", json={"nombre": "Praderas de Cauquenes"}).status_code == 201


def test_un_master_sin_pagar_se_construye_pero_no_se_publica(ana_y_luis):
    _, ana, _, registro, comandos = ana_y_luis
    slug = crear(ana)["slug"]
    ana.post(f"/api/proyectos/{slug}/archivos",
             files=[("archivos", ("loteo.kmz", b"kmz", "application/octet-stream"))])

    construir = ana.post(f"/api/proyectos/{slug}/construir", json={})
    assert construir.status_code == 202
    esperar_trabajo(ana, construir.json()["id"])
    construir_a_mano(registro, registro.salidas, slug)

    respuesta = ana.post(f"/api/proyectos/{slug}/publicar", json={"confirmado": True})

    assert respuesta.status_code == 402
    assert not [p for p in comandos.pedidos if p[0] == "publicar"]


def test_con_el_pago_anotado_se_publica(ana_y_luis):
    ctp, ana, _, registro, _ = ana_y_luis
    slug = crear(ana)["slug"]
    construir_a_mano(registro, registro.salidas, slug)

    pagado = ctp.post(f"/api/plataforma/proyectos/{slug}/pago",
                      json={"nota_cobro": "transferencia 5120"})

    assert pagado.status_code == 200
    assert pagado.json()["pagado"] is True
    assert registro.base.proyecto(slug).nota_cobro == "transferencia 5120"
    respuesta = ana.post(f"/api/proyectos/{slug}/publicar", json={"confirmado": True})
    assert respuesta.status_code == 202
    assert any(e.que == "loteo pagado" for e in registro.base.historial())


def test_anotar_un_pago_exige_decir_como_se_pago(ana_y_luis):
    ctp, ana, _, registro, _ = ana_y_luis
    slug = crear(ana)["slug"]

    respuesta = ctp.post(f"/api/plataforma/proyectos/{slug}/pago", json={"nota_cobro": ""})

    assert respuesta.status_code == 400
    assert registro.base.proyecto(slug).pagado is False


def test_anotar_el_pago_de_un_loteo_que_no_existe_da_404(ana_y_luis):
    ctp, _, _, _, _ = ana_y_luis

    respuesta = ctp.post("/api/plataforma/proyectos/no-existe/pago", json={"nota_cobro": "x"})

    assert respuesta.status_code == 404


def test_los_loteos_habilitados_por_ctp_siguen_naciendo_pagados(ana_y_luis):
    ctp, ana, _, registro, _ = ana_y_luis

    habilitar(ctp, id_de(registro, "ana@losrobles.cl"), "Las Araucarias")

    assert ana.get("/api/proyectos").json()[0]["pagado"] is True


# --- lo que muestra Mis planos -------------------------------------------------

def construir_con_precios(salidas, slug, parcelas):
    from pipeline import config
    salida = config.Salida(salidas / slug)
    salida.datos.mkdir(parents=True, exist_ok=True)
    conteo = {}
    for parcela in parcelas:
        conteo[parcela["estado"]] = conteo.get(parcela["estado"], 0) + 1
    (salida.datos / "parcelas.json").write_text(json.dumps({
        "generado": "2026-09-28T12:48:00",
        "resumen": {"total": len(parcelas), "por_estado": conteo},
        "parcelas": parcelas}))
    (salida.datos / "vistas.json").write_text('{"vistas": []}')


def test_mis_planos_trae_disponibles_y_precio_desde(ana_y_luis):
    _, ana, _, registro, _ = ana_y_luis
    slug = crear(ana)["slug"]
    construir_con_precios(registro.salidas, slug, [
        {"estado": "disponible", "precio": 12_500_000, "moneda": "CLP"},
        {"estado": "disponible", "precio": 9_990_000, "moneda": "CLP"},
        # Vendida más barata: no cuenta para "desde".
        {"estado": "vendido", "precio": 5_000_000, "moneda": "CLP"},
        # Sin precio ("a consultar"): tampoco.
        {"estado": "disponible", "precio": None, "moneda": "CLP"},
        {"estado": "reservado", "precio": 8_000_000, "moneda": "CLP"},
    ])

    resumen = ana.get("/api/proyectos").json()[0]["resumen"]

    assert resumen["parcelas"] == 5
    assert resumen["disponibles"] == 3
    assert resumen["precio_desde"] == {"monto": 9_990_000, "moneda": "CLP"}


def test_sin_disponibles_con_precio_no_hay_precio_desde(ana_y_luis):
    _, ana, _, registro, _ = ana_y_luis
    slug = crear(ana)["slug"]
    construir_con_precios(registro.salidas, slug, [
        {"estado": "vendido", "precio": 5_000_000, "moneda": "CLP"},
    ])

    resumen = ana.get("/api/proyectos").json()[0]["resumen"]

    assert resumen["disponibles"] == 0
    assert resumen["precio_desde"] is None


def test_un_master_sin_construir_no_tiene_portada(ana_y_luis):
    _, ana, _, _, _ = ana_y_luis
    slug = crear(ana)["slug"]

    assert ana.get(f"/api/proyectos/{slug}/portada").status_code == 404


def test_el_nombre_en_el_crm_vuelve_como_se_guardo(entorno, tmp_path):
    cliente, _, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    assert cliente.get("/api/proyectos").json()[0]["parcelacion"] == ""

    respuesta = cliente.patch("/api/proyectos/loteo", json={"parcelacion": "LOTEO ET2"})

    assert respuesta.json()["parcelacion"] == "LOTEO ET2"


def test_la_pagina_no_sirve_modulos_que_no_son_suyos(entorno):
    cliente, _, _ = entorno

    assert cliente.get("/js/..%2Fapp.py").status_code == 404
    assert cliente.get("/js/otro.js").status_code == 404


def test_un_pago_anotado_no_se_pisa(ana_y_luis):
    ctp, ana, _, registro, _ = ana_y_luis
    slug = crear(ana)["slug"]
    ctp.post(f"/api/plataforma/proyectos/{slug}/pago", json={"nota_cobro": "transferencia 1"})

    respuesta = ctp.post(f"/api/plataforma/proyectos/{slug}/pago", json={"nota_cobro": "otra"})

    assert respuesta.status_code == 409
    assert registro.base.proyecto(slug).nota_cobro == "transferencia 1"


# --- lo que puede gastar una loteadora antes de pagar ------------------------------

@pytest.fixture
def con_topes(tmp_path):
    limites = Limites(sin_pagar=2, megas_por_loteo=1, construcciones=1)
    app, _, registro, comandos = montar(tmp_path, limites=limites)
    return (entrar(app, "ctp@ctp.cl"), entrar(app, "ana@losrobles.cl"), registro, comandos)


def test_no_se_pasa_del_tope_de_masters_sin_pagar(con_topes):
    _, ana, _, _ = con_topes
    crear(ana, "Uno")
    crear(ana, "Dos")

    respuesta = ana.post("/api/proyectos", json={"nombre": "Tres"})

    assert respuesta.status_code == 409
    assert "sin habilitar" in respuesta.json()["detail"]


def test_un_master_pagado_libera_su_lugar(con_topes):
    ctp, ana, _, _ = con_topes
    uno = crear(ana, "Uno")["slug"]
    crear(ana, "Dos")
    ctp.post(f"/api/plataforma/proyectos/{uno}/pago", json={"nota_cobro": "transferencia"})

    assert ana.post("/api/proyectos", json={"nombre": "Tres"}).status_code == 201


def test_el_equipo_no_tiene_tope_de_masters(con_topes):
    ctp, _, _, _ = con_topes

    for nombre in ("Uno", "Dos", "Tres"):
        assert ctp.post("/api/proyectos", json={"nombre": nombre}).status_code == 201


def test_una_subida_que_no_cabe_no_deja_nada(con_topes):
    _, ana, registro, _ = con_topes
    slug = crear(ana)["slug"]

    respuesta = ana.post(f"/api/proyectos/{slug}/archivos", files=[
        ("archivos", ("loteo.kmz", b"kmz", "application/octet-stream")),
        ("archivos", ("a.JPG", b"x" * (1024 * 1024 + 1), "image/jpeg")),
    ])

    assert respuesta.status_code == 413
    assert "máximo" in respuesta.json()["detail"]
    assert not (registro.subidas / slug / "loteo.kmz").exists()


def test_la_sesion_dice_los_topes_a_la_loteadora_y_no_al_equipo(con_topes):
    ctp, ana, _, _ = con_topes

    assert ana.get("/api/sesion").json()["limites"] == {"megas_por_loteo": 1, "sin_pagar": 2}
    assert ctp.get("/api/sesion").json()["limites"] is None


def test_una_construccion_a_la_vez_por_loteadora(con_topes, monkeypatch):
    _, ana, _, comandos = con_topes
    slugs = []
    for nombre in ("Uno", "Dos"):
        slug = crear(ana, nombre)["slug"]
        ana.post(f"/api/proyectos/{slug}/archivos",
                 files=[("archivos", ("loteo.kmz", b"kmz", "application/octet-stream"))])
        slugs.append(slug)
    monkeypatch.setattr(comandos, "construir",
                        lambda p, sin_imagenes=False: [sys.executable, "-c", "import time; time.sleep(2)"])
    assert ana.post(f"/api/proyectos/{slugs[0]}/construir", json={}).status_code == 202

    respuesta = ana.post(f"/api/proyectos/{slugs[1]}/construir", json={})

    assert respuesta.status_code == 429


def test_quitar_un_master_sin_pagar_borra_sus_archivos(con_topes):
    _, ana, registro, _ = con_topes
    slug = crear(ana)["slug"]
    ana.post(f"/api/proyectos/{slug}/archivos",
             files=[("archivos", ("loteo.kmz", b"kmz", "application/octet-stream"))])
    construir_a_mano(registro, registro.salidas, slug)

    assert ana.delete(f"/api/proyectos/{slug}").status_code == 204

    assert not (registro.subidas / slug).exists()
    assert not (registro.salidas / slug).exists()


def test_quitar_un_loteo_pagado_no_borra_nada(con_topes):
    ctp, ana, registro, _ = con_topes
    slug = habilitar(ctp, id_de(registro, "ana@losrobles.cl"), "Pagado")
    construir_a_mano(registro, registro.salidas, slug)

    assert ana.delete(f"/api/proyectos/{slug}").status_code == 204

    assert (registro.subidas / slug / "proyecto.json").exists()
    assert (registro.salidas / slug / "sitio" / "datos" / "parcelas.json").exists()


def test_no_se_quita_un_loteo_mientras_construye(con_topes, monkeypatch):
    _, ana, registro, comandos = con_topes
    slug = crear(ana)["slug"]
    ana.post(f"/api/proyectos/{slug}/archivos",
             files=[("archivos", ("loteo.kmz", b"kmz", "application/octet-stream"))])
    monkeypatch.setattr(comandos, "construir",
                        lambda p, sin_imagenes=False: [sys.executable, "-c", "import time; time.sleep(2)"])
    ana.post(f"/api/proyectos/{slug}/construir", json={})

    assert ana.delete(f"/api/proyectos/{slug}").status_code == 409
    assert (registro.subidas / slug).exists()
