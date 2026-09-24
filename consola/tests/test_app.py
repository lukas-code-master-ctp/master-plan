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
    for nombre, email in (("Los Robles", "ana@losrobles.cl"), ("Del Valle", "luis@delvalle.cl")):
        base.crear_cliente(nombre, email, nombre)
        base.cambiar_clave(email, CLAVE)
    registro = Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas",
                        crm_por_defecto=crm_por_defecto)
    comandos = ComandosDePrueba()
    app = crear_app(registro=registro, trabajos=Trabajos(), comandos=comandos,
                    acceso=Acceso(base=base, secreto="un-secreto", local=local), base=base)
    return app, base, registro, comandos


def entrar(app, email="ana@losrobles.cl"):
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
    """Dos loteadoras entrando a la misma consola."""
    app, _, registro, comandos = montar(tmp_path)
    return entrar(app, "ana@losrobles.cl"), entrar(app, "luis@delvalle.cl"), registro, comandos


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


def test_subir_los_archivos_de_un_proyecto(entorno):
    cliente, _, _ = entorno

    respuesta = cliente.post("/api/proyectos", data={"nombre": "Vive Cauquenes"}, files=[
        ("archivos", ("loteo.kmz", b"kmz", "application/octet-stream")),
        ("archivos", ("POSICION 01/a.JPG", b"jpg", "image/jpeg")),
    ])

    assert respuesta.status_code == 201
    assert respuesta.json()["slug"] == "vive-cauquenes"
    assert respuesta.json()["fuentes_encontradas"]["panoramicas"] == 1


def test_subir_sin_kmz_avisa(entorno):
    cliente, _, _ = entorno

    respuesta = cliente.post("/api/proyectos", data={"nombre": "X"}, files=[
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
    ("POST", "/api/proyectos"): SOLO_SUYO,
    ("POST", "/api/proyectos/vincular"): SOLO_SUYO,
    ("PATCH", "/api/proyectos/{slug}"): AJENO_404,
    ("DELETE", "/api/proyectos/{slug}"): AJENO_404,
    ("POST", "/api/proyectos/{slug}/construir"): AJENO_404,
    ("POST", "/api/proyectos/{slug}/publicar"): AJENO_404,
    ("GET", "/api/trabajos/{identificador}"): AJENO_404,
    ("GET", "/calce/{slug}/{archivo}"): AJENO_404,
}


def test_toda_ruta_de_la_consola_declara_que_pasa_con_un_cliente_ajeno(tmp_path):
    app, _, _, _ = montar(tmp_path)

    reales = {(metodo, ruta.path) for ruta in app.routes
              for metodo in getattr(ruta, "methods", ()) if metodo not in ("HEAD", "OPTIONS")}

    assert reales - set(RUTAS) == set(), (
        "hay rutas sin declarar en RUTAS: agrégalas diciendo qué pasa cuando las "
        "pide un cliente que no es dueño de lo que nombran, y prueba ese caso")
    assert set(RUTAS) - reales == set(), "RUTAS declara rutas que ya no existen"


def de_ana(ana, tmp_path, nombre="De Ana"):
    respuesta = ana.post("/api/proyectos/vincular",
                         json={"ruta": str(carpeta_de_loteo(tmp_path, nombre))})
    assert respuesta.status_code == 201
    return respuesta.json()["slug"]


@pytest.mark.parametrize("pedir", [
    lambda web, slug: web.patch(f"/api/proyectos/{slug}", json={"etapa": "Etapa 9"}),
    lambda web, slug: web.delete(f"/api/proyectos/{slug}"),
    lambda web, slug: web.post(f"/api/proyectos/{slug}/construir", json={}),
    lambda web, slug: web.post(f"/api/proyectos/{slug}/publicar", json={"confirmado": True}),
    lambda web, slug: web.get(f"/calce/{slug}/p01-210.jpg"),
], ids=["ajustar", "olvidar", "construir", "publicar", "calce"])
def test_el_loteo_de_otra_contesta_404_en_todas_las_rutas(ana_y_luis, tmp_path, pedir):
    ana, luis, _, comandos = ana_y_luis
    slug = de_ana(ana, tmp_path)

    assert pedir(luis, slug).status_code == 404

    # Ni se tocó: ni se lanzó un comando ni se perdió el loteo.
    assert comandos.pedidos == []
    assert [p["slug"] for p in ana.get("/api/proyectos").json()] == [slug]


def test_el_avance_de_una_construccion_ajena_tampoco_se_ve(ana_y_luis, tmp_path):
    """El avance cuenta qué loteo es y qué está pasando con él: se pide igual que el loteo."""
    ana, luis, _, _ = ana_y_luis
    slug = de_ana(ana, tmp_path)
    identificador = ana.post(f"/api/proyectos/{slug}/construir", json={}).json()["id"]

    assert luis.get(f"/api/trabajos/{identificador}").status_code == 404
    assert ana.get(f"/api/trabajos/{identificador}").status_code == 200


def test_un_trabajo_que_no_existe_tambien_da_404(ana_y_luis):
    ana, _, _, _ = ana_y_luis

    assert ana.get("/api/trabajos/noexiste").status_code == 404


def test_la_lista_de_cada_una_es_la_suya(ana_y_luis, tmp_path):
    ana, luis, _, _ = ana_y_luis
    de_ana(ana, tmp_path, "De Ana")
    luis.post("/api/proyectos/vincular",
              json={"ruta": str(carpeta_de_loteo(tmp_path, "De Luis"))})

    assert [p["slug"] for p in ana.get("/api/proyectos").json()] == ["de-ana"]
    assert [p["slug"] for p in luis.get("/api/proyectos").json()] == ["de-luis"]


def test_dos_loteadoras_con_el_mismo_nombre_de_loteo_no_se_pisan(ana_y_luis, tmp_path):
    """Antes el slug salía del nombre: la segunda en publicar desplegaba encima del
    sitio de la primera, y `vercel project add || true` se comía el error."""
    ana, luis, _, _ = ana_y_luis
    una = ana.post("/api/proyectos/vincular",
                   json={"ruta": str(carpeta_de_loteo(tmp_path / "a", "Las Araucarias"))}).json()
    otra = luis.post("/api/proyectos/vincular",
                     json={"ruta": str(carpeta_de_loteo(tmp_path / "b", "Las Araucarias"))}).json()

    assert una["slug"] == "las-araucarias"
    assert otra["slug"] == "las-araucarias-2"
    assert una["url"] != otra["url"]
