"""Crea tu KMZ en la consola: subir el plano, marcarlo, digitalizarlo, ubicarlo y
sacar el KMZ del master."""
import io
import json
import sys

import numpy as np
import pymupdf
import pytest
from PIL import Image
from pyproj import Transformer

from consola.comandos import Comandos
from consola.proyectos import Limites
from consola.tests.test_app import entrar, esperar_trabajo, id_de, montar
from consola.trabajos import _entorno_sin_bufer
from pipeline.kmz import leer_kmz
from pipeline.plano.digitalizar import digitalizar
from pipeline.tests.plano_sintetico import PPMM, dibujar

# Página → UTM 19S: 0,5 m/px, sin giro, y hacia abajo en la imagen.
E0, N0, M_PX = 280000.0, 6290000.0, 0.5
A_LONLAT = Transformer.from_crs(32719, 4326, always_xy=True)


def pdf_del_plano(paginas=1, imagen=None):
    """Un PDF como los del CBR: el escaneo como JPEG embebido, una página por hoja."""
    imagen = dibujar().imagen if imagen is None else imagen
    buf = io.BytesIO()
    Image.fromarray(imagen).save(buf, "JPEG", quality=92)
    alto, ancho = imagen.shape[:2]
    doc = pymupdf.open()
    for _ in range(paginas):
        hoja = doc.new_page(width=ancho / PPMM / 25.4 * 72, height=alto / PPMM / 25.4 * 72)
        hoja.insert_image(hoja.rect, stream=buf.getvalue())
    return doc.tobytes()


def ancla(nombre, x, y, error_m=0.0):
    lon, lat = A_LONLAT.transform(E0 + M_PX * x + error_m, N0 - M_PX * y)
    return dict(nombre=nombre, x=x, y=y, lon=lon, lat=lat)


ANCLAS = [ancla("a", 0, 0), ancla("b", 1000, 0), ancla("c", 1000, 800), ancla("d", 0, 800)]


def _cuadro(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def digitalizado_a_mano(carpeta, lotes=None):
    """Lo que dejaría el trabajo de fondo, sin correrlo."""
    lotes = lotes or [
        dict(numero="1", poligono=_cuadro(0, 0, 400, 300), huecos=[], area_px=120000, area_oficial=30600),
        dict(numero="2", poligono=_cuadro(400, 0, 800, 300), huecos=[], area_px=120000, area_oficial=28000),
        dict(numero="A3", poligono=_cuadro(0, 300, 800, 700), huecos=[_cuadro(300, 400, 500, 600)],
             area_px=280000),
    ]
    datos = dict(pagina=dict(numero=1, rotacion=0, ancho=1560, alto=1026, ppmm=PPMM, fuente="embebida"),
                 trabajo=dict(modo="recorte", homografia=np.eye(3).tolist()), lotes=lotes,
                 sin_numero=[dict(poligono=_cuadro(800, 0, 900, 100), area_px=10000)], faltantes=["9"],
                 cuadricula=None, estadisticas=dict(segundos=1.0))
    (carpeta / "digitalizado.json").write_text(json.dumps(datos), encoding="utf-8")


@pytest.fixture
def consola(tmp_path):
    app, base, registro, comandos = montar(tmp_path)
    return app, registro, comandos


@pytest.fixture
def ana(consola):
    """Ana, con un master recién creado y sin KMZ: va por el plano."""
    app, registro, comandos = consola
    web = entrar(app, "ana@losrobles.cl")
    respuesta = web.post("/api/proyectos", json={"nombre": "Los Robles"})
    assert respuesta.status_code == 201, respuesta.text
    return web, respuesta.json()["slug"], registro, comandos


def subir(web, slug, contenido=None, nombre="plano.pdf"):
    contenido = pdf_del_plano() if contenido is None else contenido
    return web.post(f"/api/proyectos/{slug}/plano", files={"archivo": (nombre, contenido, "application/pdf")})


def carpeta_del_plano(registro, slug):
    return registro.subidas / slug / "plano"


ENTRADAS = dict(pagina=1, rotacion=0, rectangulo=[10, 10, 1550, 1016],
                semillas=[dict(numero="1", x=200, y=150), dict(numero="2", x=600, y=150),
                          dict(numero="A3", x=100, y=500)],
                anclas=ANCLAS)


def listo_para_ubicar(web, slug, registro, entradas=ENTRADAS):
    assert subir(web, slug).status_code == 201
    assert web.put(f"/api/proyectos/{slug}/plano/entradas", json=entradas).status_code == 200
    digitalizado_a_mano(carpeta_del_plano(registro, slug))


# --- subir ---------------------------------------------------------------------------

def test_subir_el_plano_extrae_sus_paginas(ana):
    web, slug, registro, _ = ana

    respuesta = subir(web, slug, pdf_del_plano(paginas=2))

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json() == {"paginas": [dict(n=1, ancho=1560, alto=1026), dict(n=2, ancho=1560, alto=1026)]}
    carpeta = carpeta_del_plano(registro, slug)
    assert sorted(p.name for p in carpeta.iterdir()) == ["paginas", "plano.pdf"]       # sin temporales
    assert sorted(p.name for p in (carpeta / "paginas").iterdir()) == ["1.jpg", "1_mini.jpg", "2.jpg", "2_mini.jpg"]


def test_la_pagina_se_sirve_como_jpeg_privado(ana):
    web, slug, _, _ = ana
    subir(web, slug)

    grande = web.get(f"/api/proyectos/{slug}/plano/paginas/1")
    mini = web.get(f"/api/proyectos/{slug}/plano/paginas/1", params={"mini": 1})

    assert grande.status_code == 200 and grande.headers["content-type"] == "image/jpeg"
    assert grande.headers["cache-control"].startswith("private")
    assert Image.open(io.BytesIO(grande.content)).size == (1560, 1026)
    assert max(Image.open(io.BytesIO(mini.content)).size) <= 480
    assert web.get(f"/api/proyectos/{slug}/plano/paginas/2").status_code == 404
    assert web.get(f"/api/proyectos/{slug}/plano/paginas/0").status_code == 404


def test_un_master_sin_kmz_puede_ir_por_el_plano_pero_no_construirse(ana):
    web, slug, _, comandos = ana
    subir(web, slug)

    proyecto = web.get("/api/proyectos").json()[0]
    # Las páginas del plano no son panorámicas, y todavía no hay KMZ.
    assert proyecto["fuentes_encontradas"]["panoramicas"] == 0
    assert proyecto["fuentes_encontradas"]["kmz"] is None
    assert proyecto["plano"] == {"paso": "marcar"}

    respuesta = web.post(f"/api/proyectos/{slug}/construir", json={})
    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "falta el KMZ: súbelo o créalo desde el plano"
    assert comandos.pedidos == []


def test_con_el_plano_en_curso_se_puede_subir_el_vuelo_sin_kmz(ana):
    web, slug, _, _ = ana
    subir(web, slug)

    respuesta = web.post(f"/api/proyectos/{slug}/archivos",
                         files=[("archivos", ("POSICION 01/a.JPG", b"jpg", "image/jpeg"))])

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["fuentes_encontradas"]["panoramicas"] == 1


def test_sin_plano_el_master_no_lo_muestra(ana):
    web, slug, _, _ = ana

    assert web.get("/api/proyectos").json()[0]["plano"] is None
    assert web.get(f"/api/proyectos/{slug}/plano").json()["paso"] == "subir"


def test_lo_que_no_es_pdf_se_rechaza(ana):
    web, slug, registro, _ = ana

    respuesta = subir(web, slug, b"\xff\xd8\xff una foto", "plano.pdf")

    assert respuesta.status_code == 400
    assert "PDF" in respuesta.json()["detail"]
    assert not (carpeta_del_plano(registro, slug) / "plano.pdf").exists()


def test_un_pdf_danado_se_rechaza_sin_borrar_el_anterior(ana):
    web, slug, registro, _ = ana
    subir(web, slug)

    respuesta = subir(web, slug, b"%PDF-1.7\nesto no es un pdf")

    assert respuesta.status_code == 400
    carpeta = carpeta_del_plano(registro, slug)
    assert sorted(p.name for p in carpeta.iterdir()) == ["paginas", "plano.pdf"]
    assert (carpeta / "paginas" / "1.jpg").is_file()


def test_demasiadas_paginas_no_es_un_plano(ana):
    web, slug, _, _ = ana

    respuesta = subir(web, slug, pdf_del_plano(paginas=13))

    assert respuesta.status_code == 400
    assert "13 páginas" in respuesta.json()["detail"]


def test_una_pagina_enorme_se_rechaza_antes_de_extraerla(ana):
    """Un PDF chico puede pedir una página de gigapíxeles: no se decodifica."""
    web, slug, registro, _ = ana
    doc = pymupdf.open()
    doc.new_page(width=14400, height=14400)     # 200 × 200 pulgadas: 1.600 MP a 200 dpi

    respuesta = subir(web, slug, doc.tobytes())

    assert respuesta.status_code == 400
    assert "demasiado grande" in respuesta.json()["detail"]
    assert not (carpeta_del_plano(registro, slug) / "plano.pdf").exists()


def test_el_plano_cuenta_para_el_tope_del_loteo(tmp_path):
    app, _, _, _ = montar(tmp_path, limites=Limites(megas_por_loteo=0))
    web = entrar(app, "ana@losrobles.cl")
    slug = web.post("/api/proyectos", json={"nombre": "Chico"}).json()["slug"]

    respuesta = subir(web, slug)

    assert respuesta.status_code == 413
    assert "MB" in respuesta.json()["detail"]


def test_un_plano_nuevo_borra_lo_marcado_sobre_el_anterior(ana):
    web, slug, registro, _ = ana
    listo_para_ubicar(web, slug, registro)

    assert subir(web, slug).status_code == 201

    carpeta = carpeta_del_plano(registro, slug)
    assert sorted(p.name for p in carpeta.iterdir()) == ["paginas", "plano.pdf"]
    assert web.get(f"/api/proyectos/{slug}/plano").json()["entradas"] is None


# --- entradas ------------------------------------------------------------------------

def test_las_entradas_se_guardan_normalizadas(ana):
    web, slug, registro, _ = ana
    subir(web, slug)

    respuesta = web.put(f"/api/proyectos/{slug}/plano/entradas",
                        json=dict(ENTRADAS, semillas=[dict(numero=12, x=3, y=4)]))

    assert respuesta.status_code == 200, respuesta.text
    entradas = respuesta.json()
    assert entradas["pdf"] == "plano.pdf"
    assert entradas["semillas"] == [dict(numero="12", x=3.0, y=4.0)]
    assert entradas["ajuste"] == dict(de=0.0, dn=0.0)
    guardadas = json.loads((carpeta_del_plano(registro, slug) / "entradas.json").read_text(encoding="utf-8"))
    assert guardadas == entradas
    assert web.get(f"/api/proyectos/{slug}/plano").json()["paso"] == "digitalizar"


@pytest.mark.parametrize("pdf", ["../otro.pdf", "/etc/passwd", "C:\\plano.pdf", "sub/plano.pdf", ".."])
def test_el_pdf_de_las_entradas_no_sale_de_la_carpeta(ana, pdf):
    web, slug, registro, _ = ana
    subir(web, slug)

    respuesta = web.put(f"/api/proyectos/{slug}/plano/entradas", json=dict(ENTRADAS, pdf=pdf))

    assert respuesta.status_code == 400
    assert "pdf" in respuesta.json()["detail"]
    assert not (carpeta_del_plano(registro, slug) / "entradas.json").exists()


@pytest.mark.parametrize("cambio,mensaje", [
    (dict(semillas=[dict(numero="4", x=1, y=1), dict(numero="4", x=9, y=9)]), "repetidos"),
    (dict(pagina=2), "no existe la 2"),
    (dict(rotacion=45), "rotación"),
    (dict(rectangulo=[10, 10, 5, 5]), "vacío"),
    (dict(anclas=[dict(x=1, y=1, lon=-300, lat=0)]), "fuera de rango"),
])
def test_las_entradas_malas_dicen_que_esta_mal(ana, cambio, mensaje):
    web, slug, _, _ = ana
    subir(web, slug)

    respuesta = web.put(f"/api/proyectos/{slug}/plano/entradas", json=dict(ENTRADAS, **cambio))

    assert respuesta.status_code == 400
    assert mensaje in respuesta.json()["detail"]


def test_las_entradas_tienen_tope(ana):
    """Miles de semillas atorarían la revisión (los repetidos se buscan de a pares)."""
    web, slug, registro, _ = ana
    subir(web, slug)
    semillas = [dict(numero=str(i), x=1, y=1) for i in range(5000)]

    respuesta = web.put(f"/api/proyectos/{slug}/plano/entradas", json=dict(ENTRADAS, semillas=semillas))

    assert respuesta.status_code == 400
    assert "semillas" in respuesta.json()["detail"]
    assert not (carpeta_del_plano(registro, slug) / "entradas.json").exists()


def test_sin_plano_no_hay_entradas(ana):
    web, slug, _, _ = ana

    assert web.put(f"/api/proyectos/{slug}/plano/entradas", json=ENTRADAS).status_code == 409


# --- digitalizar ---------------------------------------------------------------------

def test_digitalizar_lanza_el_trabajo_y_anota_con_que_entradas(ana):
    web, slug, registro, comandos = ana
    subir(web, slug)
    web.put(f"/api/proyectos/{slug}/plano/entradas", json=ENTRADAS)

    respuesta = web.post(f"/api/proyectos/{slug}/plano/digitalizar")

    assert respuesta.status_code == 202, respuesta.text
    trabajo = esperar_trabajo(web, respuesta.json()["id"])
    assert trabajo["estado"] == "listo" and trabajo["accion"] == "digitalizar-plano"
    # La salida llega en UTF-8 aunque la consola del sistema no lo sea.
    assert trabajo["lineas"] == [f"digitalizando {slug}: 1.200×900 px, rotación 90°"]
    assert comandos.pedidos == [("digitalizar-plano", slug, None)]
    huellas = json.loads((carpeta_del_plano(registro, slug) / "huellas.json").read_text(encoding="utf-8"))
    assert set(huellas) == {"digitalizado"}
    assert web.get(f"/api/proyectos/{slug}/plano").json()["trabajo"]["id"] == respuesta.json()["id"]


def test_sin_lector_digitalizar_pide_al_menos_un_numero(ana, monkeypatch):
    monkeypatch.setattr("consola.plano.rotulos.disponible", lambda: False)
    web, slug, _, comandos = ana
    subir(web, slug)
    web.put(f"/api/proyectos/{slug}/plano/entradas", json=dict(ENTRADAS, semillas=[]))

    respuesta = web.post(f"/api/proyectos/{slug}/plano/digitalizar")

    assert respuesta.status_code == 409
    assert "lector de rótulos" in respuesta.json()["detail"]
    assert web.get(f"/api/proyectos/{slug}/plano").json()["paso"] == "marcar"
    assert comandos.pedidos == []


def test_con_lector_se_digitaliza_sin_ningun_numero(ana, monkeypatch):
    """La primera digitalización suele no tener clics: los números los lee el lector."""
    monkeypatch.setattr("consola.plano.rotulos.disponible", lambda: True)
    web, slug, _, comandos = ana
    subir(web, slug)
    web.put(f"/api/proyectos/{slug}/plano/entradas", json=dict(ENTRADAS, semillas=[]))
    estado = web.get(f"/api/proyectos/{slug}/plano").json()
    assert estado["paso"] == "digitalizar" and estado["lector"] is True

    respuesta = web.post(f"/api/proyectos/{slug}/plano/digitalizar")

    assert respuesta.status_code == 202, respuesta.text
    esperar_trabajo(web, respuesta.json()["id"])
    assert comandos.pedidos == [("digitalizar-plano", slug, None)]


def test_con_el_lector_apagado_hace_falta_un_numero(ana, monkeypatch):
    monkeypatch.setattr("consola.plano.rotulos.disponible", lambda: True)
    web, slug, _, comandos = ana
    subir(web, slug)
    web.put(f"/api/proyectos/{slug}/plano/entradas", json=dict(ENTRADAS, semillas=[], lector=False))

    respuesta = web.post(f"/api/proyectos/{slug}/plano/digitalizar")

    assert respuesta.status_code == 409
    assert comandos.pedidos == []


def test_digitalizar_sin_plano_ni_entradas(ana):
    web, slug, _, _ = ana

    assert web.post(f"/api/proyectos/{slug}/plano/digitalizar").status_code == 409
    subir(web, slug)
    assert web.post(f"/api/proyectos/{slug}/plano/digitalizar").status_code == 409


def test_el_comando_de_verdad():
    class P:
        fuentes = __import__("pathlib").Path("/datos/proyectos/x")

    assert Comandos().digitalizar_plano(P()) == [sys.executable, "-m", "pipeline.plano", "digitalizar",
                                                  str(P.fuentes / "plano")]
    assert _entorno_sin_bufer()["PYTHONIOENCODING"] == "utf-8"


# --- ubicar --------------------------------------------------------------------------

def test_georreferenciar_con_anclas_da_el_residuo_de_cada_una(ana):
    web, slug, registro, _ = ana
    listo_para_ubicar(web, slug, registro)

    respuesta = web.post(f"/api/proyectos/{slug}/plano/georreferenciar")

    assert respuesta.status_code == 200, respuesta.text
    g = respuesta.json()
    assert g["metodo"] == "anclas" and g["epsg"] == 32719 and g["vigente"] is True
    assert [a["nombre"] for a in g["anclas"]] == ["a", "b", "c", "d"]
    assert all(a["residuo_m"] < 0.05 for a in g["anclas"]) and g["atipicas"] == []
    assert abs(g["parametros"]["escala_m_px"] - M_PX) < 1e-4
    assert g["lineas"]
    carpeta = carpeta_del_plano(registro, slug)
    assert (carpeta / "georreferencia.json").is_file() and (carpeta / "lotes.geojson").is_file()
    estado = web.get(f"/api/proyectos/{slug}/plano").json()
    assert estado["paso"] == "crear"
    assert estado["georreferencia"]["anclas"][0]["nombre"] == "a"
    assert estado["digitalizado"]["lotes"] == 3 and estado["digitalizado"]["faltantes"] == ["9"]


def test_un_ancla_mal_marcada_queda_marcada(ana):
    web, slug, registro, _ = ana
    anclas = ANCLAS + [ancla("mala", 500, 400, error_m=40)]
    listo_para_ubicar(web, slug, registro, dict(ENTRADAS, anclas=anclas))

    g = web.post(f"/api/proyectos/{slug}/plano/georreferenciar").json()

    assert g["atipicas"] == ["mala"]
    assert any("mala" in a for a in g["avisos"])


def test_mover_un_ancla_deja_la_ubicacion_atrasada(ana):
    web, slug, registro, _ = ana
    listo_para_ubicar(web, slug, registro)
    web.post(f"/api/proyectos/{slug}/plano/georreferenciar")

    web.put(f"/api/proyectos/{slug}/plano/entradas", json=dict(ENTRADAS, anclas=ANCLAS[:3]))

    estado = web.get(f"/api/proyectos/{slug}/plano").json()
    assert estado["paso"] == "ubicar"
    assert estado["georreferencia"]["vigente"] is False
    assert estado["digitalizado"]["vigente"] is True
    assert web.post(f"/api/proyectos/{slug}/plano/kmz", json={}).status_code == 409


def test_cambiar_los_numeros_pide_digitalizar_de_nuevo(ana):
    web, slug, registro, _ = ana
    listo_para_ubicar(web, slug, registro)
    trabajo = web.post(f"/api/proyectos/{slug}/plano/digitalizar").json()["id"]
    esperar_trabajo(web, trabajo)

    web.put(f"/api/proyectos/{slug}/plano/entradas",
            json=dict(ENTRADAS, semillas=ENTRADAS["semillas"][:2]))

    assert web.get(f"/api/proyectos/{slug}/plano").json()["paso"] == "digitalizar"
    respuesta = web.post(f"/api/proyectos/{slug}/plano/georreferenciar")
    assert respuesta.status_code == 409
    assert "digitaliza de nuevo" in respuesta.json()["detail"]


def test_sin_anclas_no_se_puede_ubicar(ana):
    web, slug, registro, _ = ana
    listo_para_ubicar(web, slug, registro, dict(ENTRADAS, anclas=ANCLAS[:1]))

    respuesta = web.post(f"/api/proyectos/{slug}/plano/georreferenciar")

    assert respuesta.status_code == 400
    assert "anclas" in respuesta.json()["detail"]


def test_ubicar_sin_digitalizar(ana):
    web, slug, _, _ = ana
    subir(web, slug)
    web.put(f"/api/proyectos/{slug}/plano/entradas", json=ENTRADAS)

    assert web.post(f"/api/proyectos/{slug}/plano/georreferenciar").status_code == 409
    assert web.get(f"/api/proyectos/{slug}/plano/lotes").status_code == 409


# --- lotes ---------------------------------------------------------------------------

def test_lotes_en_pixeles_antes_de_ubicar(ana):
    web, slug, registro, _ = ana
    listo_para_ubicar(web, slug, registro)

    lotes = web.get(f"/api/proyectos/{slug}/plano/lotes").json()

    assert lotes["type"] == "FeatureCollection" and lotes["en"] == "px"
    rasgos = lotes["features"]
    assert [r["properties"]["numero"] for r in rasgos] == ["1", "2", "A3", None]
    assert rasgos[0]["geometry"]["coordinates"][0][2] == [400, 300]
    assert len(rasgos[2]["geometry"]["coordinates"]) == 2                       # con su hueco
    assert "area_m2" not in rasgos[0]["properties"]
    assert rasgos[3]["properties"]["banderas"] == ["sin_numero"]
    assert web.get(f"/api/proyectos/{slug}/plano/lotes", params={"en": "lonlat"}).status_code == 409
    assert web.get(f"/api/proyectos/{slug}/plano/lotes", params={"en": "utm"}).status_code == 400


def test_lotes_ubicados_con_area_y_error_contra_el_cuadro(ana):
    web, slug, registro, _ = ana
    listo_para_ubicar(web, slug, registro)
    web.post(f"/api/proyectos/{slug}/plano/georreferenciar")

    rasgos = web.get(f"/api/proyectos/{slug}/plano/lotes", params={"en": "lonlat"}).json()["features"]

    uno, dos, a3, cara = (r["properties"] for r in rasgos)
    assert abs(uno["area_m2"] - 30000) < 5 and abs(a3["area_m2"] - 70000) < 10
    assert uno["nivel"] == "verde" and abs(uno["error_area"] + 0.0196) < 0.001       # 30000 vs 30600
    assert dos["nivel"] == "rojo"                                                    # 30000 vs 28000
    assert "error_area" not in a3
    assert abs(cara["area_m2"] - 2500) < 1
    lon, lat = rasgos[0]["geometry"]["coordinates"][0][0]
    assert -72 < lon < -71 and -34 < lat < -33


def test_numeros_que_chocan_se_marcan_y_no_dan_kmz(ana):
    web, slug, registro, _ = ana
    listo_para_ubicar(web, slug, registro)
    lotes = [dict(numero="7", poligono=_cuadro(0, 0, 400, 300), huecos=[]),
             dict(numero="07", poligono=_cuadro(400, 0, 800, 300), huecos=[]),
             dict(numero="??", poligono=_cuadro(0, 300, 800, 700), huecos=[])]
    digitalizado_a_mano(carpeta_del_plano(registro, slug), lotes)
    web.post(f"/api/proyectos/{slug}/plano/georreferenciar")

    rasgos = web.get(f"/api/proyectos/{slug}/plano/lotes").json()["features"]

    assert [r["properties"]["banderas"] for r in rasgos[:3]] == [["duplicado"], ["duplicado"], ["sin_numero"]]
    respuesta = web.post(f"/api/proyectos/{slug}/plano/kmz", json={})
    assert respuesta.status_code == 400
    assert not list(registro.subidas.joinpath(slug).glob("*.kmz"))


# --- KMZ -----------------------------------------------------------------------------

def test_crear_el_kmz_del_master(ana):
    web, slug, registro, _ = ana
    listo_para_ubicar(web, slug, registro)
    web.post(f"/api/proyectos/{slug}/plano/georreferenciar")

    respuesta = web.post(f"/api/proyectos/{slug}/plano/kmz", json={})

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json() == dict(kmz="subdivision.kmz", lotes=3, anteriores=[])
    kmz = registro.subidas / slug / "subdivision.kmz"
    assert sorted(p.id for p in leer_kmz(kmz)) == ["1", "2", "A3"]
    assert not (carpeta_del_plano(registro, slug) / "subdivision.kmz").exists()
    proyecto = web.get("/api/proyectos").json()[0]
    assert proyecto["fuentes_encontradas"]["kmz"] == "subdivision.kmz"
    assert proyecto["plano"] == {"paso": "listo"}


def test_reemplazar_un_kmz_pide_confirmar_y_guarda_el_anterior(ana):
    web, slug, registro, _ = ana
    carpeta = registro.subidas / slug
    web.post(f"/api/proyectos/{slug}/archivos",
             files=[("archivos", ("vuelo/Loteo Final.kmz", b"el del topografo", "application/octet-stream"))])
    listo_para_ubicar(web, slug, registro)
    web.post(f"/api/proyectos/{slug}/plano/georreferenciar")

    sin_confirmar = web.post(f"/api/proyectos/{slug}/plano/kmz", json={})

    assert sin_confirmar.status_code == 409
    assert sin_confirmar.json()["existentes"] == ["vuelo/Loteo Final.kmz"]
    assert "vuelo/Loteo Final.kmz" in sin_confirmar.json()["detail"]
    assert not (carpeta / "subdivision.kmz").exists()

    confirmado = web.post(f"/api/proyectos/{slug}/plano/kmz", json={"confirmar_reemplazo": True})

    assert confirmado.status_code == 201, confirmado.text
    assert confirmado.json()["anteriores"] == ["vuelo/Loteo Final.kmz.anterior"]
    assert (carpeta / "vuelo" / "Loteo Final.kmz.anterior").read_bytes() == b"el del topografo"
    # Construir encuentra uno solo: el nuevo.
    assert web.get("/api/proyectos").json()[0]["fuentes_encontradas"]["kmz"] == "subdivision.kmz"

    # Rehacerlo también pide confirmar: el que hay ahora es el del plano.
    assert web.post(f"/api/proyectos/{slug}/plano/kmz", json={}).status_code == 409
    otra = web.post(f"/api/proyectos/{slug}/plano/kmz", json={"confirmar_reemplazo": True})
    assert otra.json()["anteriores"] == ["subdivision.kmz.anterior"]
    assert (carpeta / "subdivision.kmz").is_file()


def test_no_se_toca_el_kmz_mientras_corre_un_trabajo(ana, monkeypatch):
    web, slug, registro, comandos = ana
    listo_para_ubicar(web, slug, registro)
    web.post(f"/api/proyectos/{slug}/plano/georreferenciar")
    monkeypatch.setattr(comandos, "digitalizar_plano",
                        lambda p: [sys.executable, "-c", "import time; time.sleep(2)"])
    web.post(f"/api/proyectos/{slug}/plano/digitalizar")

    assert web.post(f"/api/proyectos/{slug}/plano/kmz", json={}).status_code == 409
    assert web.post(f"/api/proyectos/{slug}/plano/georreferenciar").status_code == 409
    assert subir(web, slug).status_code == 409
    assert web.post(f"/api/proyectos/{slug}/plano/digitalizar").status_code == 409


# --- de punta a punta ----------------------------------------------------------------

def test_del_pdf_al_kmz_con_el_plano_sintetico(ana):
    """El método de verdad (digitalizar en el proceso, sin subprocesos)."""
    web, slug, registro, _ = ana
    plano = dibujar()
    alto, ancho = plano.imagen.shape[:2]
    subir(web, slug, pdf_del_plano(imagen=plano.imagen))
    entradas = dict(pagina=1, rotacion=0, rectangulo=[100, 100, ancho - 20, alto - 5],
                    semillas=[dict(numero=n, x=x, y=y) for n, x, y in plano.semillas],
                    anclas=[ancla("a", 150, 150), ancla("b", ancho - 150, 150),
                            ancla("c", ancho - 150, alto - 150), ancla("d", 150, alto - 150)])
    assert web.put(f"/api/proyectos/{slug}/plano/entradas", json=entradas).status_code == 200
    esperar_trabajo(web, web.post(f"/api/proyectos/{slug}/plano/digitalizar").json()["id"])
    digitalizar(carpeta_del_plano(registro, slug), avance=lambda _: None)

    assert web.post(f"/api/proyectos/{slug}/plano/georreferenciar").status_code == 200
    respuesta = web.post(f"/api/proyectos/{slug}/plano/kmz", json={})

    assert respuesta.status_code == 201, respuesta.text
    parcelas = leer_kmz(registro.subidas / slug / "subdivision.kmz")
    assert sorted(p.id for p in parcelas) == sorted(n for n, _, _ in plano.semillas)
    assert web.get(f"/api/proyectos/{slug}/plano").json()["paso"] == "listo"


# --- de otra loteadora ---------------------------------------------------------------

def test_el_plano_de_otra_no_se_ve_ni_se_toca(consola):
    app, registro, comandos = consola
    ana, luis = entrar(app, "ana@losrobles.cl"), entrar(app, "luis@delvalle.cl")
    slug = ana.post("/api/proyectos", json={"nombre": "De Ana"}).json()["slug"]
    listo_para_ubicar(ana, slug, registro)
    carpeta = carpeta_del_plano(registro, slug)
    antes = {p.name: p.stat().st_mtime_ns for p in carpeta.iterdir()}

    for respuesta in (
        subir(luis, slug),
        luis.get(f"/api/proyectos/{slug}/plano"),
        luis.get(f"/api/proyectos/{slug}/plano/paginas/1"),
        luis.put(f"/api/proyectos/{slug}/plano/entradas", json=ENTRADAS),
        luis.post(f"/api/proyectos/{slug}/plano/digitalizar"),
        luis.post(f"/api/proyectos/{slug}/plano/georreferenciar"),
        luis.get(f"/api/proyectos/{slug}/plano/lotes"),
        luis.post(f"/api/proyectos/{slug}/plano/kmz", json={"confirmar_reemplazo": True}),
    ):
        assert respuesta.status_code == 404, respuesta.request.url

    assert comandos.pedidos == []
    assert {p.name: p.stat().st_mtime_ns for p in carpeta.iterdir()} == antes
    assert not (registro.subidas / slug / "subdivision.kmz").exists()
