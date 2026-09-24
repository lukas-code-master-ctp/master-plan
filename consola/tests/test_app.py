"""La API de la consola."""
import json
import sys
import time

import pytest
from fastapi.testclient import TestClient

from consola.app import crear_app
from consola.proyectos import Registro
from consola.trabajos import Trabajos


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


@pytest.fixture
def entorno(tmp_path):
    registro = Registro(archivo=tmp_path / "proyectos.json", subidas=tmp_path / "proyectos",
                        salidas=tmp_path / "salidas")
    comandos = ComandosDePrueba()
    app = crear_app(registro=registro, trabajos=Trabajos(), comandos=comandos)
    return TestClient(app), registro, comandos


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


def construir_a_mano(registro, slug):
    """Deja la salida como la dejaría el pipeline, para probar lo que viene después."""
    salida = registro.ver(slug).salida
    salida.datos.mkdir(parents=True, exist_ok=True)
    (salida.datos / "parcelas.json").write_text(
        '{"resumen": {"total": 2, "por_estado": {"disponible": 2}}, "generado": "2026-09-24T10:00:00"}')
    (salida.datos / "vistas.json").write_text(
        '{"vistas": [{"id": "p01-210", "diagnostico": {"error_elevacion": 0.4, "calibracion": {"mejora": 0.2}}}]}')


def test_publicar_usa_el_script_de_publicacion(entorno, tmp_path):
    cliente, registro, comandos = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, "loteo")

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
    proyecto = registro.ver("loteo")
    proyecto.salida.qa.mkdir(parents=True, exist_ok=True)
    (proyecto.salida.qa / "p01-210.jpg").write_bytes(b"\xff\xd8\xff falso jpeg")

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
    construir_a_mano(registro, "loteo")

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
    construir_a_mano(registro, "loteo")

    respuesta = cliente.post("/api/proyectos/loteo/publicar", json={})

    assert respuesta.status_code == 428
    assert "confirm" in respuesta.json()["detail"].lower()
    assert comandos.pedidos == []


def test_con_la_confirmacion_publica(entorno, tmp_path):
    cliente, registro, comandos = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, "loteo")

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
    cliente = TestClient(crear_app(
        registro=Registro(archivo=tmp_path / "p.json", subidas=tmp_path / "p",
                          salidas=tmp_path / "s"),
        trabajos=Trabajos(), comandos=ComandosDePrueba()))
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})

    assert cliente.get("/api/proyectos").json()[0]["url"] == "https://loteo.tumasterplan.cl"


def test_republicar_no_vuelve_a_crear_el_proyecto_en_el_hosting(entorno, tmp_path):
    """Pedir `--crear` de nuevo sería intentar pisar un proyecto que ya existe."""
    cliente, registro, comandos = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, "loteo")
    registro.anotar_publicacion("loteo", vercel_proyecto="masterplan-loteo",
                                url="https://masterplan-loteo.vercel.app")

    cliente.post("/api/proyectos/loteo/publicar", json={"confirmado": True})

    assert comandos.pedidos == [("publicar", "loteo", "masterplan-loteo", False)]


def test_al_terminar_de_publicar_se_guarda_la_url_real(entorno, tmp_path):
    """La consola muestra la URL que devolvió el hosting, no una armada a mano."""
    cliente, registro, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})
    construir_a_mano(registro, "loteo")
    rastro = registro.ver("loteo").salida.base / "publicacion.json"
    rastro.write_text('{"proyecto": "masterplan-loteo", "url": "https://otra-url.vercel.app"}')

    identificador = cliente.post("/api/proyectos/loteo/publicar",
                                 json={"confirmado": True}).json()["id"]
    esperar_trabajo(cliente, identificador)

    for _ in range(200):
        if registro.ver("loteo").url_publicada:
            break
        time.sleep(0.01)
    assert registro.ver("loteo").url_publicada == "https://otra-url.vercel.app"
    assert cliente.get("/api/proyectos").json()[0]["url"] == "https://otra-url.vercel.app"


def test_un_loteo_sin_publicar_muestra_donde_iria(entorno, tmp_path):
    cliente, _, _ = entorno
    cliente.post("/api/proyectos/vincular", json={"ruta": str(carpeta_de_loteo(tmp_path))})

    proyecto = cliente.get("/api/proyectos").json()[0]

    assert proyecto["publicado"] is False
    assert proyecto["url"] == "https://masterplan-loteo.vercel.app"
