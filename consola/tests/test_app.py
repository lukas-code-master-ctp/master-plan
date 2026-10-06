"""La API de la consola."""
import io
import json
import sys
import time

import openpyxl
import pytest
from fastapi.testclient import TestClient

from consola.acceso import Acceso
from consola.app import crear_app
from consola.datos import Base
from consola.disenos import Disenos
from consola.kmzs import RegistroKmz
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

    def digitalizar_carpeta(self, carpeta):
        """Un KMZ de Mis KMZ: la carpeta se llama como su slug. Con tildes y símbolos:
        el avance del plano los trae."""
        self.pedidos.append(("digitalizar-kmz", carpeta.name, None))
        return self._guion(f"digitalizando {carpeta.name}: 1.200×900 px, rotación 90°")

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
                    acceso=Acceso(base=base, secreto="un-secreto", local=local), base=base,
                    disenos=Disenos(base=base, carpeta=tmp_path / "disenos"),
                    kmzs=RegistroKmz(base=base, carpeta=tmp_path / "kmz", limites=registro.limites))
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
    ("/vendor/leaflet.js", "text/javascript"),
    ("/vendor/leaflet.css", "text/css"),
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
    ("GET", "/vendor/{archivo}"): SOLO_SUYO,
    ("GET", "/api/sesion"): SOLO_SUYO,
    ("POST", "/api/clave"): SOLO_SUYO,
    ("GET", "/api/proyectos"): SOLO_SUYO,
    ("POST", "/api/proyectos"): SOLO_SUYO,
    ("GET", "/api/proyectos/{slug}/portada"): AJENO_404,
    ("GET", "/api/proyectos/{slug}/plantilla"): AJENO_404,
    ("GET", "/api/plantilla-inventario"): SOLO_SUYO,
    ("POST", "/api/proyectos/{slug}/inventario/actualizar"): AJENO_404,
    ("POST", "/api/tareas/cierra"): SIN_SESION,
    ("GET", "/api/cierra"): SOLO_SUYO,
    ("PUT", "/api/cierra/clave"): SOLO_SUYO,
    ("DELETE", "/api/cierra/clave"): SOLO_SUYO,
    ("GET", "/api/cierra/opciones"): SOLO_SUYO,
    ("GET", "/api/proyectos/{slug}/cierra"): AJENO_404,
    ("PUT", "/api/proyectos/{slug}/cierra"): AJENO_404,
    ("DELETE", "/api/proyectos/{slug}/cierra"): AJENO_404,
    ("PUT", "/api/proyectos/{slug}/cierra/clave"): AJENO_404,
    ("DELETE", "/api/proyectos/{slug}/cierra/clave"): AJENO_404,
    ("GET", "/api/proyectos/{slug}/cierra/opciones"): AJENO_404,
    ("POST", "/api/proyectos/{slug}/cierra/actualizar"): AJENO_404,
    ("PATCH", "/api/proyectos/{slug}"): AJENO_404,
    ("DELETE", "/api/proyectos/{slug}"): AJENO_404,
    ("POST", "/api/proyectos/{slug}/archivos"): AJENO_404,
    ("POST", "/api/proyectos/{slug}/construir"): AJENO_404,
    ("POST", "/api/proyectos/{slug}/publicar"): AJENO_404,
    ("GET", "/api/trabajos/{identificador}"): AJENO_404,
    # Master ajeno → 404 (abajo); KMZ ajeno → 404 (test_kmz.py).
    ("POST", "/api/proyectos/{slug}/kmz"): AJENO_404,
    ("GET", "/calce/{slug}/{archivo}"): AJENO_404,
    # Mis KMZ: lo ajeno se prueba en test_kmz.py (test_el_kmz_de_otra_contesta_404...).
    ("GET", "/api/kmz"): SOLO_SUYO,
    ("POST", "/api/kmz"): SOLO_SUYO,
    ("GET", "/api/kmz/{slug}"): AJENO_404,
    ("PATCH", "/api/kmz/{slug}"): AJENO_404,
    ("DELETE", "/api/kmz/{slug}"): AJENO_404,
    ("POST", "/api/kmz/{slug}/plano"): AJENO_404,
    ("GET", "/api/kmz/{slug}/paginas/{n}"): AJENO_404,
    ("PUT", "/api/kmz/{slug}/entradas"): AJENO_404,
    ("POST", "/api/kmz/{slug}/digitalizar"): AJENO_404,
    ("POST", "/api/kmz/{slug}/georreferenciar"): AJENO_404,
    ("GET", "/api/kmz/{slug}/lotes"): AJENO_404,
    ("POST", "/api/kmz/{slug}/corregir"): AJENO_404,
    ("POST", "/api/kmz/{slug}/crear"): AJENO_404,
    ("GET", "/api/kmz/{slug}/descargar"): AJENO_404,
    ("POST", "/api/proyectos/vincular"): SOLO_CTP,
    ("GET", "/api/plataforma/clientes"): SOLO_CTP,
    ("POST", "/api/plataforma/clientes"): SOLO_CTP,
    ("POST", "/api/plataforma/clientes/{cliente_id}/usuarios"): SOLO_CTP,
    ("POST", "/api/plataforma/clientes/{cliente_id}/estado"): SOLO_CTP,
    ("POST", "/api/plataforma/clientes/{cliente_id}/proyectos"): SOLO_CTP,
    ("POST", "/api/plataforma/proyectos/{slug}/pago"): SOLO_CTP,
    ("GET", "/api/plataforma/historial"): SOLO_CTP,
    ("POST", "/api/plataforma/usuarios/clave"): SOLO_CTP,
    ("GET", "/api/disenos"): SOLO_SUYO,
    ("POST", "/api/disenos"): SOLO_SUYO,
    ("PATCH", "/api/disenos/{diseno_id}"): AJENO_404,
    ("DELETE", "/api/disenos/{diseno_id}"): AJENO_404,
    ("POST", "/api/disenos/{diseno_id}/logo"): AJENO_404,
    ("DELETE", "/api/disenos/{diseno_id}/logo"): AJENO_404,
    ("GET", "/api/disenos/{diseno_id}/logo"): AJENO_404,
    ("GET", "/registro"): SIN_SESION,
    ("POST", "/registro"): SIN_SESION,
    ("GET", "/verificar"): SIN_SESION,
    ("POST", "/verificar"): SIN_SESION,
    ("GET", "/olvide"): SIN_SESION,
    ("POST", "/olvide"): SIN_SESION,
    ("GET", "/restablecer"): SIN_SESION,
    ("POST", "/restablecer"): SIN_SESION,
    ("GET", "/entrar/google"): SIN_SESION,
    ("GET", "/entrar/google/vuelta"): SIN_SESION,
    ("GET", "/registro/google"): SIN_SESION,
    ("POST", "/registro/google"): SIN_SESION,
}


def rutas_de(rutas, prefijo=""):
    """Todas las rutas, entrando también a los routers incluidos.

    FastAPI 0.14x guarda un `include_router` como un objeto aparte, sin `path` ni
    `methods`: recorrer solo `app.routes` se salteaba en silencio todo lo que
    colgara de un router, y ese es justo el lugar donde se agregan rutas nuevas.
    """
    for ruta in rutas:
        incluido = getattr(ruta, "original_router", None)
        if incluido is not None:
            yield from rutas_de(incluido.routes, prefijo + getattr(incluido, "prefix", ""))
            continue
        for metodo in getattr(ruta, "methods", ()):
            if metodo not in ("HEAD", "OPTIONS"):
                yield metodo, prefijo + ruta.path


def test_el_inventario_ve_las_rutas_de_los_routers_incluidos(tmp_path):
    app, _, _, _ = montar(tmp_path)

    assert ("POST", "/registro") in set(rutas_de(app.routes))


def test_toda_ruta_de_la_consola_declara_que_pasa_con_un_cliente_ajeno(tmp_path):
    app, _, _, _ = montar(tmp_path)

    reales = set(rutas_de(app.routes))

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
    lambda web, slug: web.get(f"/api/proyectos/{slug}/plantilla"),
    lambda web, slug: web.post(f"/api/proyectos/{slug}/archivos",
                               files=[("archivos", ("x.kmz", b"kmz", "application/octet-stream"))]),
    lambda web, slug: web.post(f"/api/proyectos/{slug}/kmz", json={"kmz": "x", "confirmar_reemplazo": True}),
], ids=["ajustar", "olvidar", "construir", "publicar", "calce", "portada", "plantilla", "subir",
        "usar-kmz"])
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
    lambda web, cid: web.post("/api/plataforma/usuarios/clave", json={"email": "luis@delvalle.cl"}),
], ids=["listar", "crear cliente", "crear cuenta", "suspender", "habilitar loteo", "historial",
        "anotar pago", "clave nueva"])
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
    assert cliente.get("/vendor/..%2F..%2Fconsola%2Fapp.py").status_code == 404
    assert cliente.get("/vendor/fuentes").status_code == 404


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


# --- mis diseños ---------------------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def un_diseno(web, nombre="Marca Robles", **campos):
    respuesta = web.post("/api/disenos", json={"nombre": nombre, "color": "#1f5132", **campos})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()


def test_crear_y_listar_un_diseno(ana_y_luis):
    _, ana, luis, _, _ = ana_y_luis

    creado = un_diseno(ana, tipografia="serif", texto_contacto="Quiero esta")

    assert creado["color"] == "#1f5132"
    assert creado["tipografia"] == "serif"
    assert creado["texto_contacto"] == "Quiero esta"
    assert creado["logo"] is False
    assert [d["nombre"] for d in ana.get("/api/disenos").json()] == ["Marca Robles"]
    assert luis.get("/api/disenos").json() == []


@pytest.mark.parametrize("campos,mensaje", [
    ({"nombre": ""}, "nombre"),
    ({"nombre": "X", "color": "verde"}, "#RRGGBB"),
    ({"nombre": "X", "tipografia": "comic-sans"}, "tipografía"),
])
def test_un_diseno_invalido_explica_por_que(ana_y_luis, campos, mensaje):
    _, ana, _, _, _ = ana_y_luis

    respuesta = ana.post("/api/disenos", json=campos)

    assert respuesta.status_code == 400
    assert mensaje in respuesta.json()["detail"]


def test_no_se_repite_el_nombre_de_un_diseno(ana_y_luis):
    _, ana, luis, _, _ = ana_y_luis
    un_diseno(ana)

    assert ana.post("/api/disenos", json={"nombre": "Marca Robles"}).status_code == 409
    assert luis.post("/api/disenos", json={"nombre": "Marca Robles"}).status_code == 201


@pytest.mark.parametrize("pedir", [
    lambda web, i: web.patch(f"/api/disenos/{i}", json={"color": "#000000"}),
    lambda web, i: web.delete(f"/api/disenos/{i}"),
    lambda web, i: web.post(f"/api/disenos/{i}/logo", files={"archivo": ("l.png", PNG, "image/png")}),
    lambda web, i: web.delete(f"/api/disenos/{i}/logo"),
    lambda web, i: web.get(f"/api/disenos/{i}/logo"),
], ids=["ajustar", "borrar", "subir logo", "quitar logo", "ver logo"])
def test_el_diseno_de_otra_contesta_404(ana_y_luis, pedir):
    _, ana, luis, _, _ = ana_y_luis
    diseno = un_diseno(ana)
    ana.post(f"/api/disenos/{diseno['id']}/logo", files={"archivo": ("l.png", PNG, "image/png")})

    assert pedir(luis, diseno["id"]).status_code == 404


def test_subir_y_ver_el_logo(ana_y_luis):
    _, ana, _, _, _ = ana_y_luis
    diseno = un_diseno(ana)

    subido = ana.post(f"/api/disenos/{diseno['id']}/logo",
                      files={"archivo": ("logo.png", PNG, "image/png")})
    visto = ana.get(f"/api/disenos/{diseno['id']}/logo")

    assert subido.json()["logo"] is True
    assert visto.status_code == 200
    assert visto.content == PNG
    assert "default-src 'none'" in visto.headers["content-security-policy"]


@pytest.mark.parametrize("nombre,contenido", [
    ("logo.png", b"no soy un png"),
    ("logo.gif", b"GIF89a"),
    ("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
    ("logo.svg", b'<svg onload="alert(1)"></svg>'),
    ("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><a:script xmlns:a="http://www.w3.org/2000/svg">'
                 b'alert(1)</a:script></svg>'),
    ("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><div/></foreignObject></svg>'),
    ("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(https://x.cl/a.css);</style></svg>'),
    ("logo.svg", b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink">'
                 b'<use x:href="https://x.cl/a.svg#b"/></svg>'),
    ("logo.svg", b'<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg>&a;</svg>'),
    ("logo.png", b"\x89PNG\r\n\x1a\n" + b"0" * (600 * 1024)),
], ids=["png falso", "gif", "svg con script", "svg con evento", "script con prefijo",
        "foreignObject", "css de afuera", "href externo", "entidades", "muy pesado"])
def test_un_logo_que_no_sirve_se_rechaza(ana_y_luis, nombre, contenido):
    _, ana, _, _, _ = ana_y_luis
    diseno = un_diseno(ana)

    respuesta = ana.post(f"/api/disenos/{diseno['id']}/logo",
                         files={"archivo": (nombre, contenido, "application/octet-stream")})

    assert respuesta.status_code == 400
    assert ana.get("/api/disenos").json()[0]["logo"] is False


def test_un_svg_limpio_sirve_de_logo(ana_y_luis):
    """Como sale de Illustrator o Figma: degradados y <use> con referencias internas."""
    _, ana, _, _, _ = ana_y_luis
    diseno = un_diseno(ana)
    svg = (b'<?xml version="1.0" encoding="UTF-8"?>'
           b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
           b'<defs><linearGradient id="g"><stop offset="0" stop-color="#1f5132"/></linearGradient>'
           b'<circle id="c" cx="5" cy="5" r="4"/></defs>'
           b'<style>.a{fill:url(#g)}</style>'
           b'<use href="#c" class="a"/><use xlink:href="#c" fill="url(#g)"/></svg>')

    respuesta = ana.post(f"/api/disenos/{diseno['id']}/logo",
                         files={"archivo": ("logo.svg", svg, "image/svg+xml")})

    assert respuesta.status_code == 200
    assert ana.get(f"/api/disenos/{diseno['id']}/logo").headers["content-type"] == "image/svg+xml"


def test_un_master_nace_con_su_diseno(ana_y_luis):
    _, ana, _, _, _ = ana_y_luis
    diseno = un_diseno(ana)

    creado = ana.post("/api/proyectos", json={"nombre": "Con marca", "diseno_id": diseno["id"]})

    assert creado.status_code == 201
    assert creado.json()["diseno_id"] == diseno["id"]


def test_no_se_usa_el_diseno_de_otra_loteadora(ana_y_luis):
    _, ana, luis, _, _ = ana_y_luis
    ajeno = un_diseno(luis)

    creado = ana.post("/api/proyectos", json={"nombre": "Robado", "diseno_id": ajeno["id"]})

    assert creado.status_code == 404
    assert ana.get("/api/proyectos").json() == []


def test_el_equipo_no_le_pone_a_un_cliente_la_marca_de_otro(ana_y_luis):
    ctp, ana, luis, _, _ = ana_y_luis
    slug = crear(ana)["slug"]
    de_luis = un_diseno(luis)

    respuesta = ctp.patch(f"/api/proyectos/{slug}", json={"diseno_id": de_luis["id"]})

    assert respuesta.status_code == 400
    assert "otra loteadora" in respuesta.json()["detail"]


def test_cambiar_y_quitar_el_diseno_de_un_master(ana_y_luis):
    _, ana, _, _, _ = ana_y_luis
    slug = crear(ana)["slug"]
    diseno = un_diseno(ana)

    puesto = ana.patch(f"/api/proyectos/{slug}", json={"diseno_id": diseno["id"]})
    quitado = ana.patch(f"/api/proyectos/{slug}", json={"diseno_id": None})

    assert puesto.json()["diseno_id"] == diseno["id"]
    assert quitado.json()["diseno_id"] is None


def test_borrar_un_diseno_devuelve_sus_masters_al_por_defecto(ana_y_luis):
    _, ana, _, _, _ = ana_y_luis
    diseno = un_diseno(ana)
    slug = ana.post("/api/proyectos", json={"nombre": "X", "diseno_id": diseno["id"]}).json()["slug"]

    assert ana.delete(f"/api/disenos/{diseno['id']}").status_code == 204

    assert [p["diseno_id"] for p in ana.get("/api/proyectos").json() if p["slug"] == slug] == [None]


def test_un_cambio_de_nombre_que_falla_no_cambia_el_diseno(ana_y_luis):
    _, ana, _, _, _ = ana_y_luis
    crear(ana, "Uno")
    slug = crear(ana, "Dos")["slug"]
    diseno = un_diseno(ana)

    respuesta = ana.patch(f"/api/proyectos/{slug}", json={"nombre": "Uno", "diseno_id": diseno["id"]})

    assert respuesta.status_code == 400
    assert [p["diseno_id"] for p in ana.get("/api/proyectos").json() if p["slug"] == slug] == [None]


def test_publicar_deja_el_diseno_en_el_sitio(ana_y_luis):
    ctp, ana, _, registro, _ = ana_y_luis
    diseno = un_diseno(ana, texto_pago="Reservar ya")
    ana.post(f"/api/disenos/{diseno['id']}/logo", files={"archivo": ("logo.png", PNG, "image/png")})
    slug = ana.post("/api/proyectos", json={"nombre": "Con marca", "diseno_id": diseno["id"]}).json()["slug"]
    construir_a_mano(registro, registro.salidas, slug)
    ctp.post(f"/api/plataforma/proyectos/{slug}/pago", json={"nota_cobro": "transferencia"})

    assert ana.post(f"/api/proyectos/{slug}/publicar", json={"confirmado": True}).status_code == 202

    datos = registro.salidas / slug / "sitio" / "datos"
    escrito = json.loads((datos / "diseno.json").read_text())
    assert escrito["color"] == "#1f5132"
    assert escrito["texto_pago"] == "Reservar ya"
    assert escrito["logo"] == "logo.png"
    assert (datos / "logo.png").read_bytes() == PNG


def test_publicar_lleva_al_sitio_el_whatsapp_cambiado_sin_reconstruir(ana_y_luis):
    """El número se cambia en la consola y llega al sitio con solo volver a publicar."""
    ctp, ana, _, registro, _ = ana_y_luis
    slug = ana.post("/api/proyectos", json={"nombre": "Con contacto"}).json()["slug"]
    construir_a_mano(registro, registro.salidas, slug)
    ctp.post(f"/api/plataforma/proyectos/{slug}/pago", json={"nota_cobro": "transferencia"})
    ana.patch(f"/api/proyectos/{slug}", json={"whatsapp": "+56 9 1234 5678", "etapa": "Etapa 1"})

    assert ana.post(f"/api/proyectos/{slug}/publicar", json={"confirmado": True}).status_code == 202

    datos = json.loads((registro.salidas / slug / "sitio" / "datos" / "parcelas.json").read_text())
    assert (datos["whatsapp"], datos["proyecto"], datos["etapa"]) == ("56912345678", "Con contacto", "Etapa 1")


def test_publicar_lleva_al_sitio_el_link_y_el_monto_de_reserva_del_loteo(ana_y_luis):
    ctp, ana, _, registro, _ = ana_y_luis
    slug = ana.post("/api/proyectos", json={"nombre": "Con reserva"}).json()["slug"]
    construir_a_mano(registro, registro.salidas, slug)
    ctp.post(f"/api/plataforma/proyectos/{slug}/pago", json={"nota_cobro": "transferencia"})

    guardado = ana.patch(f"/api/proyectos/{slug}",
                         json={"link_reserva": "https://pago.cl/reserva", "monto_reserva": "250.000"})

    assert guardado.status_code == 200
    assert (guardado.json()["link_reserva"], guardado.json()["monto_reserva"]) == ("https://pago.cl/reserva", 250000)
    assert ana.post(f"/api/proyectos/{slug}/publicar", json={"confirmado": True}).status_code == 202
    datos = json.loads((registro.salidas / slug / "sitio" / "datos" / "parcelas.json").read_text())
    assert (datos["link_reserva"], datos["monto_reserva"]) == ("https://pago.cl/reserva", 250000)


@pytest.mark.parametrize("campos", [
    {"link_reserva": "pago.cl/reserva"},
    {"link_reserva": "javascript:alert(1)"},
    {"monto_reserva": "doscientos mil"},
])
def test_un_link_o_monto_de_reserva_que_no_sirve_se_rechaza(ana_y_luis, campos):
    _, ana, _, _, _ = ana_y_luis
    slug = ana.post("/api/proyectos", json={"nombre": "Reserva rara"}).json()["slug"]

    respuesta = ana.patch(f"/api/proyectos/{slug}", json=campos)

    assert respuesta.status_code == 400
    assert ana.get("/api/proyectos").json()[0].get("link_reserva", "") == ""


def test_publicar_sin_diseno_deja_el_diseno_vacio(ana_y_luis):
    ctp, ana, _, registro, _ = ana_y_luis
    diseno = un_diseno(ana)
    slug = ana.post("/api/proyectos", json={"nombre": "X", "diseno_id": diseno["id"]}).json()["slug"]
    construir_a_mano(registro, registro.salidas, slug)
    ctp.post(f"/api/plataforma/proyectos/{slug}/pago", json={"nota_cobro": "transferencia"})
    primera = ana.post(f"/api/proyectos/{slug}/publicar", json={"confirmado": True}).json()["id"]
    esperar_trabajo(ana, primera)
    ana.patch(f"/api/proyectos/{slug}", json={"diseno_id": None})

    assert ana.post(f"/api/proyectos/{slug}/publicar", json={"confirmado": True}).status_code == 202

    datos = registro.salidas / slug / "sitio" / "datos"
    # Vacío y no borrado: el visor lo pide siempre, y un 404 ensucia su consola.
    assert (datos / "diseno.json").read_text() == "null"
    assert not list(datos.glob("logo.*"))


def test_la_pagina_toma_prestada_la_marca_del_visor(entorno):
    cliente, _, _ = entorno

    respuesta = cliente.get("/js/marca.js")

    assert respuesta.status_code == 200
    assert "export function paleta" in respuesta.text


# --- clave nueva desde el equipo (sin correo, es la única forma) ---------------------

def test_el_equipo_da_una_clave_provisional_nueva(ana_y_luis):
    ctp, ana, _, registro, _ = ana_y_luis

    respuesta = ctp.post("/api/plataforma/usuarios/clave", json={"email": "Ana@LosRobles.cl"})

    assert respuesta.status_code == 200
    clave = respuesta.json()["clave_provisional"]
    # La sesión que tenía abierta se corta, y entra con la nueva.
    assert ana.get("/api/sesion").status_code == 401
    assert ana.post("/entrar", data={"email": "ana@losrobles.cl", "clave": CLAVE}).status_code == 401
    assert ana.post("/entrar", data={"email": "ana@losrobles.cl", "clave": clave}).status_code == 303
    assert ana.get("/api/sesion").json()["debe_cambiar_clave"] is True
    assert any(e.que == "clave provisional nueva" for e in registro.base.historial())


def test_una_clave_nueva_para_un_correo_sin_cuenta_da_404(ana_y_luis):
    ctp, _, _, _, _ = ana_y_luis

    assert ctp.post("/api/plataforma/usuarios/clave", json={"email": "nadie@x.cl"}).status_code == 404


def test_la_plantilla_del_loteo_sale_con_sus_parcelas(ana_y_luis):
    _, ana, _, registro, _ = ana_y_luis
    slug = crear(ana)["slug"]
    construir_con_precios(registro.salidas, slug, [
        {"id": "7", "estado": "disponible", "precio": 9_990_000, "moneda": "CLP", "en_planilla": True},
    ])

    respuesta = ana.get(f"/api/proyectos/{slug}/plantilla")

    assert respuesta.status_code == 200
    assert f'filename="inventario-{slug}.xlsx"' in respuesta.headers["content-disposition"]
    hoja = openpyxl.load_workbook(io.BytesIO(respuesta.content)).active
    assert [c.value for c in hoja[2]][:4] == ["PRADERAS DE CAUQUENES", "7", "Disponible", 9_990_000]


def test_sin_construir_la_plantilla_del_loteo_es_la_de_ejemplo(ana_y_luis):
    _, ana, _, _, _ = ana_y_luis
    slug = crear(ana)["slug"]

    en_blanco = ana.get("/api/plantilla-inventario")
    del_loteo = ana.get(f"/api/proyectos/{slug}/plantilla")

    assert en_blanco.status_code == del_loteo.status_code == 200
    hoja = openpyxl.load_workbook(io.BytesIO(del_loteo.content)).active
    assert (hoja["A2"].value, hoja["B2"].value) == ("MI LOTEO", "1")


def test_construir_con_publicar_deja_al_dia_un_loteo_publicado(entorno, tmp_path):
    """Lo pide "Actualizar desde Cierra": los precios nuevos llegan también al sitio."""
    cliente, registro, comandos = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, registro.salidas, "loteo")
    registro.base.anotar_publicacion("loteo", "masterplan-loteo", "https://masterplan-loteo.vercel.app")
    (registro.salidas / "loteo" / "sitio" / "datos" / "diseno.json").unlink(missing_ok=True)

    respuesta = cliente.post("/api/proyectos/loteo/construir",
                             json={"sin_imagenes": True, "publicar": True})
    trabajo = esperar_trabajo(cliente, respuesta.json()["id"])

    assert trabajo["accion"] == "actualizar"
    assert comandos.pedidos == [("construir", "loteo", True), ("calce", "loteo", None),
                                ("publicar", "loteo", "masterplan-loteo", False)]
    # Sale con la marca escrita antes de subir, no después.
    assert (registro.salidas / "loteo" / "sitio" / "datos" / "diseno.json").is_file()


def test_construir_con_publicar_no_publica_lo_que_nunca_se_publico(entorno, tmp_path):
    """La primera publicación se confirma a mano: no la dispara una actualización."""
    cliente, registro, comandos = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, registro.salidas, "loteo")

    respuesta = cliente.post("/api/proyectos/loteo/construir",
                             json={"sin_imagenes": True, "publicar": True})
    trabajo = esperar_trabajo(cliente, respuesta.json()["id"])

    assert trabajo["accion"] == "construir"
    assert not any(p[0] == "publicar" for p in comandos.pedidos)


def test_construir_con_publicar_no_publica_sin_pago(ana_y_luis):
    _, ana, _, registro, comandos = ana_y_luis
    slug = ana.post("/api/proyectos", json={"nombre": "Sin pagar"}).json()["slug"]
    (registro.subidas / slug).mkdir(parents=True, exist_ok=True)
    (registro.subidas / slug / "loteo.kmz").write_bytes(b"kmz")
    construir_a_mano(registro, registro.salidas, slug)
    registro.base.anotar_publicacion(slug, f"masterplan-{slug}", f"https://masterplan-{slug}.vercel.app")

    respuesta = ana.post(f"/api/proyectos/{slug}/construir", json={"publicar": True})
    esperar_trabajo(ana, respuesta.json()["id"])

    assert not any(p[0] == "publicar" for p in comandos.pedidos)
