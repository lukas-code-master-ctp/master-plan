"""Crea tu KMZ (los pasos de un KMZ de Mis KMZ): subir el plano, marcarlo,
digitalizarlo, ubicarlo y ver sus lotes. Crear, descargar y usar el KMZ, y lo de
otra loteadora, están en test_kmz.py."""
import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image
from pyproj import Transformer

from consola.comandos import Comandos
from consola.tests.test_app import entrar, esperar_trabajo, montar
from consola.trabajos import _entorno_sin_bufer
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
def ana(tmp_path):
    """Ana, con un KMZ recién creado. `raiz` es la carpeta de Mis KMZ."""
    app, _, _, comandos = montar(tmp_path)
    web = entrar(app, "ana@losrobles.cl")
    respuesta = web.post("/api/kmz", json={"nombre": "Los Robles"})
    assert respuesta.status_code == 201, respuesta.text
    return web, respuesta.json()["slug"], tmp_path / "kmz", comandos


def subir(web, slug, contenido=None, nombre="plano.pdf"):
    contenido = pdf_del_plano() if contenido is None else contenido
    return web.post(f"/api/kmz/{slug}/plano", files={"archivo": (nombre, contenido, "application/pdf")})


def carpeta_del_plano(raiz: Path, slug):
    return raiz / slug


ENTRADAS = dict(pagina=1, rotacion=0, rectangulo=[10, 10, 1550, 1016],
                semillas=[dict(numero="1", x=200, y=150), dict(numero="2", x=600, y=150),
                          dict(numero="A3", x=100, y=500)],
                anclas=ANCLAS)


def listo_para_ubicar(web, slug, raiz, entradas=ENTRADAS):
    assert subir(web, slug).status_code == 201
    assert web.put(f"/api/kmz/{slug}/entradas", json=entradas).status_code == 200
    digitalizado_a_mano(carpeta_del_plano(raiz, slug))


# --- subir ---------------------------------------------------------------------------

def test_subir_el_plano_extrae_sus_paginas(ana):
    web, slug, raiz, _ = ana

    respuesta = subir(web, slug, pdf_del_plano(paginas=2))

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json() == {"paginas": [dict(n=1, ancho=1560, alto=1026), dict(n=2, ancho=1560, alto=1026)]}
    carpeta = carpeta_del_plano(raiz, slug)
    assert sorted(p.name for p in carpeta.iterdir()) == ["paginas", "plano.pdf"]       # sin temporales
    assert sorted(p.name for p in (carpeta / "paginas").iterdir()) == ["1.jpg", "1_mini.jpg", "2.jpg", "2_mini.jpg"]


def test_la_pagina_se_sirve_como_jpeg_privado(ana):
    web, slug, _, _ = ana
    subir(web, slug)

    grande = web.get(f"/api/kmz/{slug}/paginas/1")
    mini = web.get(f"/api/kmz/{slug}/paginas/1", params={"mini": 1})

    assert grande.status_code == 200 and grande.headers["content-type"] == "image/jpeg"
    assert grande.headers["cache-control"].startswith("private")
    assert Image.open(io.BytesIO(grande.content)).size == (1560, 1026)
    assert max(Image.open(io.BytesIO(mini.content)).size) <= 480
    assert web.get(f"/api/kmz/{slug}/paginas/2").status_code == 404
    assert web.get(f"/api/kmz/{slug}/paginas/0").status_code == 404


def test_sin_plano_el_paso_es_subir(ana):
    web, slug, _, _ = ana

    assert web.get(f"/api/kmz/{slug}").json()["paso"] == "subir"


def test_lo_que_no_es_pdf_se_rechaza(ana):
    web, slug, raiz, _ = ana

    respuesta = subir(web, slug, b"\xff\xd8\xff una foto", "plano.pdf")

    assert respuesta.status_code == 400
    assert "PDF" in respuesta.json()["detail"]
    assert not (carpeta_del_plano(raiz, slug) / "plano.pdf").exists()


def test_un_pdf_danado_se_rechaza_sin_borrar_el_anterior(ana):
    web, slug, raiz, _ = ana
    subir(web, slug)

    respuesta = subir(web, slug, b"%PDF-1.7\nesto no es un pdf")

    assert respuesta.status_code == 400
    carpeta = carpeta_del_plano(raiz, slug)
    assert sorted(p.name for p in carpeta.iterdir()) == ["paginas", "plano.pdf"]
    assert (carpeta / "paginas" / "1.jpg").is_file()


def test_demasiadas_paginas_no_es_un_plano(ana):
    web, slug, _, _ = ana

    respuesta = subir(web, slug, pdf_del_plano(paginas=13))

    assert respuesta.status_code == 400
    assert "13 páginas" in respuesta.json()["detail"]


def test_una_pagina_enorme_se_rechaza_antes_de_extraerla(ana):
    """Un PDF chico puede pedir una página de gigapíxeles: no se decodifica."""
    web, slug, raiz, _ = ana
    doc = pymupdf.open()
    doc.new_page(width=14400, height=14400)     # 200 × 200 pulgadas: 1.600 MP a 200 dpi

    respuesta = subir(web, slug, doc.tobytes())

    assert respuesta.status_code == 400
    assert "demasiado grande" in respuesta.json()["detail"]
    assert not (carpeta_del_plano(raiz, slug) / "plano.pdf").exists()


def test_un_plano_nuevo_borra_lo_marcado_sobre_el_anterior(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)

    assert subir(web, slug).status_code == 201

    carpeta = carpeta_del_plano(raiz, slug)
    assert sorted(p.name for p in carpeta.iterdir()) == ["paginas", "plano.pdf"]
    assert web.get(f"/api/kmz/{slug}").json()["entradas"] is None


# --- entradas ------------------------------------------------------------------------

def test_las_entradas_se_guardan_normalizadas(ana):
    web, slug, raiz, _ = ana
    subir(web, slug)

    respuesta = web.put(f"/api/kmz/{slug}/entradas",
                        json=dict(ENTRADAS, semillas=[dict(numero=12, x=3, y=4)]))

    assert respuesta.status_code == 200, respuesta.text
    entradas = respuesta.json()
    assert entradas["pdf"] == "plano.pdf"
    assert entradas["semillas"] == [dict(numero="12", x=3.0, y=4.0)]
    assert entradas["ajuste"] == dict(de=0.0, dn=0.0)
    guardadas = json.loads((carpeta_del_plano(raiz, slug) / "entradas.json").read_text(encoding="utf-8"))
    assert guardadas == entradas
    assert web.get(f"/api/kmz/{slug}").json()["paso"] == "digitalizar"


@pytest.mark.parametrize("pdf", ["../otro.pdf", "/etc/passwd", "C:\\plano.pdf", "sub/plano.pdf", ".."])
def test_el_pdf_de_las_entradas_no_sale_de_la_carpeta(ana, pdf):
    web, slug, raiz, _ = ana
    subir(web, slug)

    respuesta = web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, pdf=pdf))

    assert respuesta.status_code == 400
    assert "pdf" in respuesta.json()["detail"]
    assert not (carpeta_del_plano(raiz, slug) / "entradas.json").exists()


@pytest.mark.parametrize("cambio,mensaje", [
    (dict(semillas=[dict(numero="4", x=1, y=1), dict(numero="4", x=9, y=9)]), "repetidos"),
    (dict(pagina=2), "no existe la 2"),
    (dict(rotacion=45), "rotación"),
    (dict(rectangulo=[10, 10, 5, 5]), "vacío"),
    (dict(anclas=[dict(x=1, y=1, lon=-300, lat=0)]), "fuera de rango"),
    (dict(fuera="aquí"), "«fuera»"),
    (dict(fuera=[[1]]), "fuera[]"),
    (dict(fuera=[["a", 2]]), "fuera[]"),
])
def test_las_entradas_malas_dicen_que_esta_mal(ana, cambio, mensaje):
    web, slug, _, _ = ana
    subir(web, slug)

    respuesta = web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, **cambio))

    assert respuesta.status_code == 400
    assert mensaje in respuesta.json()["detail"]


def test_el_cuadro_de_superficies_puede_estar_fuera_del_dibujo(ana):
    web, slug, raiz, _ = ana
    subir(web, slug)

    respuesta = web.put(f"/api/kmz/{slug}/entradas",
                        json=dict(ENTRADAS, rectangulo=[100, 100, 300, 300], cuadro=[2, 2, 60, 80]))

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["cuadro"] == [2.0, 2.0, 60.0, 80.0]
    guardadas = json.loads((carpeta_del_plano(raiz, slug) / "entradas.json").read_text(encoding="utf-8"))
    assert guardadas["cuadro"] == [2.0, 2.0, 60.0, 80.0]


@pytest.mark.parametrize("cuadro,mensaje", [
    ([10, 10, 5, 5], "cuadro de superficies está vacío"),
    ([1, 2, 3], "«cuadro» debe ser una lista de 4 números"),
    ([10**6, 10**6, 10**6 + 50, 10**6 + 50], "fuera de la página"),
    ([-90, -90, -10, -10], "fuera de la página"),
])
def test_un_cuadro_malo_dice_que_esta_mal(ana, cuadro, mensaje):
    web, slug, raiz, _ = ana
    subir(web, slug)

    respuesta = web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, cuadro=cuadro))

    assert respuesta.status_code == 400
    assert mensaje in respuesta.json()["detail"]
    assert not (carpeta_del_plano(raiz, slug) / "entradas.json").exists()


def test_las_entradas_tienen_tope(ana):
    """Miles de semillas atorarían la revisión (los repetidos se buscan de a pares)."""
    web, slug, raiz, _ = ana
    subir(web, slug)
    semillas = [dict(numero=str(i), x=1, y=1) for i in range(5000)]

    respuesta = web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, semillas=semillas))

    assert respuesta.status_code == 400
    assert "semillas" in respuesta.json()["detail"]
    assert not (carpeta_del_plano(raiz, slug) / "entradas.json").exists()
    respuesta = web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, fuera=[[1, 1]] * 51))
    assert respuesta.status_code == 400 and "fuera" in respuesta.json()["detail"]


def test_sin_plano_no_hay_entradas(ana):
    web, slug, _, _ = ana

    assert web.put(f"/api/kmz/{slug}/entradas", json=ENTRADAS).status_code == 409


# --- digitalizar ---------------------------------------------------------------------

def test_digitalizar_lanza_el_trabajo_y_anota_con_que_entradas(ana):
    web, slug, raiz, comandos = ana
    subir(web, slug)
    web.put(f"/api/kmz/{slug}/entradas", json=ENTRADAS)

    respuesta = web.post(f"/api/kmz/{slug}/digitalizar")

    assert respuesta.status_code == 202, respuesta.text
    trabajo = esperar_trabajo(web, respuesta.json()["id"])
    assert trabajo["estado"] == "listo" and trabajo["accion"] == "digitalizar-plano"
    # La salida llega en UTF-8 aunque la consola del sistema no lo sea.
    assert trabajo["lineas"] == [f"digitalizando {slug}: 1.200×900 px, rotación 90°"]
    assert comandos.pedidos == [("digitalizar-kmz", slug, None)]
    huellas = json.loads((carpeta_del_plano(raiz, slug) / "huellas.json").read_text(encoding="utf-8"))
    assert set(huellas) == {"digitalizado"}
    assert web.get(f"/api/kmz/{slug}").json()["trabajo"]["id"] == respuesta.json()["id"]


def test_sin_lector_digitalizar_pide_al_menos_un_numero(ana, monkeypatch):
    monkeypatch.setattr("consola.plano.rotulos.disponible", lambda: False)
    web, slug, _, comandos = ana
    subir(web, slug)
    web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, semillas=[]))

    respuesta = web.post(f"/api/kmz/{slug}/digitalizar")

    assert respuesta.status_code == 409
    assert "lector de rótulos" in respuesta.json()["detail"]
    assert web.get(f"/api/kmz/{slug}").json()["paso"] == "marcar"
    assert comandos.pedidos == []


def test_con_lector_se_digitaliza_sin_ningun_numero(ana, monkeypatch):
    """La primera digitalización suele no tener clics: los números los lee el lector."""
    monkeypatch.setattr("consola.plano.rotulos.disponible", lambda: True)
    web, slug, _, comandos = ana
    subir(web, slug)
    web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, semillas=[]))
    estado = web.get(f"/api/kmz/{slug}").json()
    assert estado["paso"] == "digitalizar" and estado["lector"] is True

    respuesta = web.post(f"/api/kmz/{slug}/digitalizar")

    assert respuesta.status_code == 202, respuesta.text
    esperar_trabajo(web, respuesta.json()["id"])
    assert comandos.pedidos == [("digitalizar-kmz", slug, None)]


def test_con_el_lector_apagado_hace_falta_un_numero(ana, monkeypatch):
    monkeypatch.setattr("consola.plano.rotulos.disponible", lambda: True)
    web, slug, _, comandos = ana
    subir(web, slug)
    web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, semillas=[], lector=False))

    respuesta = web.post(f"/api/kmz/{slug}/digitalizar")

    assert respuesta.status_code == 409
    assert comandos.pedidos == []


def test_digitalizar_sin_plano_ni_entradas(ana):
    web, slug, _, _ = ana

    assert web.post(f"/api/kmz/{slug}/digitalizar").status_code == 409
    subir(web, slug)
    assert web.post(f"/api/kmz/{slug}/digitalizar").status_code == 409


def test_el_comando_de_verdad():
    class P:
        fuentes = Path("/datos/kmz/x")

    assert Comandos().digitalizar_carpeta(P.fuentes) == [sys.executable, "-m", "pipeline.plano",
                                                         "digitalizar", str(P.fuentes)]
    assert _entorno_sin_bufer()["PYTHONIOENCODING"] == "utf-8"


# --- ubicar --------------------------------------------------------------------------

def test_georreferenciar_con_anclas_da_el_residuo_de_cada_una(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)

    respuesta = web.post(f"/api/kmz/{slug}/georreferenciar")

    assert respuesta.status_code == 200, respuesta.text
    g = respuesta.json()
    assert g["metodo"] == "anclas" and g["epsg"] == 32719 and g["vigente"] is True
    assert [a["nombre"] for a in g["anclas"]] == ["a", "b", "c", "d"]
    assert all(a["residuo_m"] < 0.05 for a in g["anclas"]) and g["atipicas"] == []
    assert abs(g["parametros"]["escala_m_px"] - M_PX) < 1e-4
    assert g["lineas"]
    carpeta = carpeta_del_plano(raiz, slug)
    assert (carpeta / "georreferencia.json").is_file() and (carpeta / "lotes.geojson").is_file()
    estado = web.get(f"/api/kmz/{slug}").json()
    assert estado["paso"] == "crear"
    assert estado["georreferencia"]["anclas"][0]["nombre"] == "a"
    assert estado["digitalizado"]["lotes"] == 3 and estado["digitalizado"]["faltantes"] == ["9"]


def test_un_ancla_mal_marcada_queda_marcada(ana):
    web, slug, raiz, _ = ana
    anclas = ANCLAS + [ancla("mala", 500, 400, error_m=40)]
    listo_para_ubicar(web, slug, raiz, dict(ENTRADAS, anclas=anclas))

    g = web.post(f"/api/kmz/{slug}/georreferenciar").json()

    assert g["atipicas"] == ["mala"]
    assert any("mala" in a for a in g["avisos"])


def test_mover_un_ancla_deja_la_ubicacion_atrasada(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    web.post(f"/api/kmz/{slug}/georreferenciar")

    web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, anclas=ANCLAS[:3]))

    estado = web.get(f"/api/kmz/{slug}").json()
    assert estado["paso"] == "ubicar"
    assert estado["georreferencia"]["vigente"] is False
    assert estado["digitalizado"]["vigente"] is True
    assert web.post(f"/api/kmz/{slug}/crear").status_code == 409


def test_cambiar_los_numeros_pide_digitalizar_de_nuevo(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    trabajo = web.post(f"/api/kmz/{slug}/digitalizar").json()["id"]
    esperar_trabajo(web, trabajo)

    web.put(f"/api/kmz/{slug}/entradas",
            json=dict(ENTRADAS, semillas=ENTRADAS["semillas"][:2]))

    assert web.get(f"/api/kmz/{slug}").json()["paso"] == "digitalizar"
    respuesta = web.post(f"/api/kmz/{slug}/georreferenciar")
    assert respuesta.status_code == 409
    assert "lee el plano de nuevo" in respuesta.json()["detail"]


# La cuadrícula UTM que "leyó" el lector, en el mismo sistema que las anclas.
PROPUESTA = dict(verticales=[dict(x=300.0, valor=E0 + M_PX * 300), dict(x=900.0, valor=E0 + M_PX * 900)],
                 horizontales=[dict(y=200.0, valor=N0 - M_PX * 200), dict(y=700.0, valor=N0 - M_PX * 700)],
                 epsg=None)


def con_propuesta(carpeta, cuadricula):
    """Al digitalizado a mano le agrega lo que leyó el lector, con su cuadrícula."""
    ruta = carpeta / "digitalizado.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["lector"] = dict(activo=True, disponible=True, rotulos=[], semillas=0, apoyo_min=2,
                           sin_poligono=[], cuadricula=cuadricula, cuadro={})
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def test_usar_o_quitar_la_cuadricula_propuesta_no_atrasa_los_lotes(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    con_propuesta(carpeta_del_plano(raiz, slug), PROPUESTA)
    esperar_trabajo(web, web.post(f"/api/kmz/{slug}/digitalizar").json()["id"])
    assert web.post(f"/api/kmz/{slug}/georreferenciar").json()["metodo"] == "anclas"
    huellas = carpeta_del_plano(raiz, slug) / "huellas.json"
    digitalizado = json.loads(huellas.read_text(encoding="utf-8"))["digitalizado"]

    # Como la manda el navegador: la propuesta tal cual, con un valor corregido.
    elegida = dict(PROPUESTA, verticales=[dict(PROPUESTA["verticales"][0]),
                                          dict(PROPUESTA["verticales"][1], valor=E0 + M_PX * 900)])
    assert web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, cuadricula=elegida)).status_code == 200

    estado = web.get(f"/api/kmz/{slug}").json()
    assert estado["digitalizado"]["vigente"] is True
    # La ubicación sí queda atrasada: es lo que cambia.
    assert estado["paso"] == "ubicar" and estado["georreferencia"]["vigente"] is False
    g = web.post(f"/api/kmz/{slug}/georreferenciar")
    assert g.status_code == 200, g.text
    assert g.json()["metodo"] == "cuadricula"
    assert web.get(f"/api/kmz/{slug}").json()["paso"] == "crear"

    web.put(f"/api/kmz/{slug}/entradas", json=ENTRADAS)
    estado = web.get(f"/api/kmz/{slug}").json()
    assert estado["digitalizado"]["vigente"] is True and estado["georreferencia"]["vigente"] is False
    assert json.loads(huellas.read_text(encoding="utf-8"))["digitalizado"] == digitalizado


def test_otra_cuadricula_que_la_propuesta_si_pide_digitalizar(ana):
    """Otras líneas que las leídas cambian lo que se borra del dibujo: eso sí atrasa."""
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    con_propuesta(carpeta_del_plano(raiz, slug), PROPUESTA)
    esperar_trabajo(web, web.post(f"/api/kmz/{slug}/digitalizar").json()["id"])

    corrida = dict(PROPUESTA, verticales=[dict(PROPUESTA["verticales"][0], x=350.0), PROPUESTA["verticales"][1]])
    web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, cuadricula=corrida))

    estado = web.get(f"/api/kmz/{slug}").json()
    assert estado["digitalizado"]["vigente"] is False and estado["paso"] == "digitalizar"


def test_digitalizar_con_la_propuesta_elegida_queda_al_dia(ana):
    """Si ya estaba elegida y el lector la vuelve a leer igual, digitalizar no la cuenta
    y quitarla después tampoco atrasa."""
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz, dict(ENTRADAS, cuadricula=PROPUESTA))
    con_propuesta(carpeta_del_plano(raiz, slug), PROPUESTA)
    esperar_trabajo(web, web.post(f"/api/kmz/{slug}/digitalizar").json()["id"])
    assert web.get(f"/api/kmz/{slug}").json()["digitalizado"]["vigente"] is True

    web.put(f"/api/kmz/{slug}/entradas", json=ENTRADAS)

    assert web.get(f"/api/kmz/{slug}").json()["digitalizado"]["vigente"] is True


def test_un_kmz_que_digitalizo_con_la_propuesta_antes_del_cambio_sigue_al_dia(ana):
    """Antes la huella llevaba la cuadrícula elegida tal cual, aunque fuera la propuesta:
    esos KMZ no quedan atrasados porque ahora la propuesta no cuente."""
    from consola.plano import huella_digitalizar
    from pipeline.plano.digitalizar import leer_entradas

    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz, dict(ENTRADAS, cuadricula=PROPUESTA))
    carpeta = carpeta_del_plano(raiz, slug)
    con_propuesta(carpeta, PROPUESTA)
    (carpeta / "huellas.json").write_text(
        json.dumps(dict(digitalizado=huella_digitalizar(leer_entradas(carpeta)))), encoding="utf-8")

    estado = web.get(f"/api/kmz/{slug}").json()
    assert estado["digitalizado"]["vigente"] is True and estado["paso"] == "ubicar"


def test_la_cuadricula_se_ofrece_solo_si_alcanza_para_ubicar(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    carpeta = carpeta_del_plano(raiz, slug)
    con_propuesta(carpeta, PROPUESTA)
    assert web.get(f"/api/kmz/{slug}").json()["digitalizado"]["lector"]["cuadricula"] == PROPUESTA

    # Lo que leyó en Rapel: cuatro verticales con valor y ninguna horizontal.
    rapel = dict(verticales=[dict(x=2377.3 + 400 * i, valor=6213500 + 500 * i) for i in range(4)],
                 horizontales=[], epsg=None)
    con_propuesta(carpeta, rapel)
    lector = web.get(f"/api/kmz/{slug}").json()["digitalizado"]["lector"]
    assert lector is not None and lector["cuadricula"] is None

    con_propuesta(carpeta, dict(PROPUESTA, horizontales=PROPUESTA["horizontales"][:1]))
    assert web.get(f"/api/kmz/{slug}").json()["digitalizado"]["lector"]["cuadricula"] is None


def test_sin_anclas_no_se_puede_ubicar(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz, dict(ENTRADAS, anclas=ANCLAS[:1]))

    respuesta = web.post(f"/api/kmz/{slug}/georreferenciar")

    assert respuesta.status_code == 400
    assert "2 puntos" in respuesta.json()["detail"]


def test_ubicar_sin_digitalizar(ana):
    web, slug, _, _ = ana
    subir(web, slug)
    web.put(f"/api/kmz/{slug}/entradas", json=ENTRADAS)

    assert web.post(f"/api/kmz/{slug}/georreferenciar").status_code == 409
    assert web.get(f"/api/kmz/{slug}/lotes").status_code == 409


# --- lotes ---------------------------------------------------------------------------

def test_lotes_en_pixeles_antes_de_ubicar(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)

    lotes = web.get(f"/api/kmz/{slug}/lotes").json()

    assert lotes["type"] == "FeatureCollection" and lotes["en"] == "px"
    rasgos = lotes["features"]
    assert [r["properties"]["numero"] for r in rasgos] == ["1", "2", "A3", None]
    assert rasgos[0]["geometry"]["coordinates"][0][2] == [400, 300]
    assert len(rasgos[2]["geometry"]["coordinates"]) == 2                       # con su hueco
    assert "area_m2" not in rasgos[0]["properties"]
    assert rasgos[3]["properties"]["banderas"] == ["sin_numero"]
    assert web.get(f"/api/kmz/{slug}/lotes", params={"en": "lonlat"}).status_code == 409
    assert web.get(f"/api/kmz/{slug}/lotes", params={"en": "utm"}).status_code == 400


def test_lotes_dicen_de_donde_salio_su_numero(ana):
    """La pantalla pinta distinto el número que leyó el lector (con su confianza) del
    que marcó la loteadora, y pone el rótulo en la semilla."""
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    lotes = [dict(numero="1", poligono=_cuadro(0, 0, 400, 300), huecos=[], semilla=[200, 150],
                  origen="lector", confianza=0.82, apoyo=3),
             dict(numero="2", poligono=_cuadro(400, 0, 800, 300), huecos=[], semilla=[600, 150],
                  origen="usuario", confianza=None, apoyo=None),
             dict(numero="3", poligono=_cuadro(0, 300, 800, 700), huecos=[])]
    digitalizado_a_mano(carpeta_del_plano(raiz, slug), lotes)

    uno, dos, tres, _ = (r["properties"] for r in web.get(f"/api/kmz/{slug}/lotes").json()["features"])

    assert (uno["origen"], uno["confianza"], uno["apoyo"], uno["semilla"]) == ("lector", 0.82, 3, [200, 150])
    assert (dos["origen"], dos["confianza"], dos["semilla"]) == ("usuario", None, [600, 150])
    assert tres["origen"] == "usuario" and tres["semilla"] is None


def test_lotes_ubicados_con_area_y_error_contra_el_cuadro(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    web.post(f"/api/kmz/{slug}/georreferenciar")

    rasgos = web.get(f"/api/kmz/{slug}/lotes", params={"en": "lonlat"}).json()["features"]

    uno, dos, a3, cara = (r["properties"] for r in rasgos)
    assert abs(uno["area_m2"] - 30000) < 5 and abs(a3["area_m2"] - 70000) < 10
    assert uno["nivel"] == "verde" and abs(uno["error_area"] + 0.0196) < 0.001       # 30000 vs 30600
    assert dos["nivel"] == "rojo"                                                    # 30000 vs 28000
    assert "error_area" not in a3
    assert abs(cara["area_m2"] - 2500) < 1
    lon, lat = rasgos[0]["geometry"]["coordinates"][0][0]
    assert -72 < lon < -71 and -34 < lat < -33


def test_numeros_que_chocan_se_marcan_y_no_dan_kmz(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    lotes = [dict(numero="7", poligono=_cuadro(0, 0, 400, 300), huecos=[]),
             dict(numero="07", poligono=_cuadro(400, 0, 800, 300), huecos=[]),
             dict(numero="??", poligono=_cuadro(0, 300, 800, 700), huecos=[])]
    digitalizado_a_mano(carpeta_del_plano(raiz, slug), lotes)
    web.post(f"/api/kmz/{slug}/georreferenciar")

    rasgos = web.get(f"/api/kmz/{slug}/lotes").json()["features"]

    assert [r["properties"]["banderas"] for r in rasgos[:3]] == [["duplicado"], ["duplicado"], ["sin_numero"]]
    respuesta = web.post(f"/api/kmz/{slug}/crear")
    assert respuesta.status_code == 400
    assert not list(carpeta_del_plano(raiz, slug).glob("*.kmz"))


def _con_lote_sin_numero(carpeta):
    """El digitalizado de `listo_para_ubicar` con un lote sin número (con la lectura que
    no alcanzó a ser semilla) y los huecos de la numeración."""
    datos = json.loads((carpeta / "digitalizado.json").read_text(encoding="utf-8"))
    datos["sin_numero"].append(dict(poligono=_cuadro(800, 300, 1000, 700), area_px=80000, de_lote=True,
                                    sugerencia=dict(numero="4", confianza=0.01, apoyo=1)))
    datos["huecos"] = ["4"]
    (carpeta / "digitalizado.json").write_text(json.dumps(datos), encoding="utf-8")


def test_un_lote_sin_numero_se_marca_con_su_sugerencia(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    _con_lote_sin_numero(carpeta_del_plano(raiz, slug))

    rasgos = [r["properties"] for r in web.get(f"/api/kmz/{slug}/lotes").json()["features"]]

    camino, lote = rasgos[3], rasgos[4]
    assert camino["banderas"] == ["sin_numero"] and camino["de_lote"] is False and camino["sugerencia"] is None
    assert lote["numero"] is None and lote["banderas"] == ["sin_numero", "de_lote"] and lote["de_lote"] is True
    assert lote["sugerencia"] == dict(numero="4", confianza=0.01, apoyo=1)
    d = web.get(f"/api/kmz/{slug}").json()["digitalizado"]
    assert (d["sin_numero"], d["sin_numero_lote"], d["sugerencias"], d["huecos"]) == (2, 1, 1, ["4"])


def test_con_lotes_sin_numero_el_kmz_pide_confirmar(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    carpeta = carpeta_del_plano(raiz, slug)
    _con_lote_sin_numero(carpeta)
    assert web.post(f"/api/kmz/{slug}/georreferenciar").status_code == 200

    respuesta = web.post(f"/api/kmz/{slug}/crear")

    assert respuesta.status_code == 409
    assert respuesta.json()["sin_numero"] == 1 and "1 lote sin número" in respuesta.json()["detail"]
    assert not list(carpeta.glob("*.kmz"))
    assert web.post(f"/api/kmz/{slug}/crear", json={"omitir_sin_numero": False}).status_code == 409

    respuesta = web.post(f"/api/kmz/{slug}/crear", json={"omitir_sin_numero": True})

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["lotes"] == 3                 # sin el lote sin número
    assert web.get(f"/api/kmz/{slug}").json()["paso"] == "listo"


def test_un_camino_sin_numero_no_pide_confirmar(ana):
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)              # su única cara sin número no es de lote
    assert web.post(f"/api/kmz/{slug}/georreferenciar").status_code == 200

    assert web.post(f"/api/kmz/{slug}/crear").status_code == 201


def test_el_estado_trae_los_numeros_del_cuadro_de_superficies(ana):
    """La pantalla los usa para escribir el número como en el cuadro y ofrecer los que faltan."""
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    carpeta = carpeta_del_plano(raiz, slug)
    con_propuesta(carpeta, None)
    assert web.get(f"/api/kmz/{slug}").json()["digitalizado"]["lector"]["numeros_cuadro"] == []

    ruta = carpeta / "digitalizado.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["lector"]["cuadro"] = {"8-01": 5000.0, "8-08": 5000.0, "8-16": 5000.0}
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    lector = web.get(f"/api/kmz/{slug}").json()["digitalizado"]["lector"]
    assert lector["numeros_cuadro"] == ["8-01", "8-08", "8-16"] and lector["areas"] == 3


# --- el resto de la propiedad -----------------------------------------------------------

RAPEL = {"8-01": 5000.0, "8-02": 5000.0, "8-03": 5000.0, "8": 760000.0}
# Un punto dentro del resto de `_con_resto`.
EN_EL_RESTO = [500, 500]


def _con_resto(carpeta, cuadro=None, area_resto=(0, 300, 1000, 1000)):
    """Caminos de Rapel en chico: lotes chicos y el resto de la propiedad, una parte sin
    número del tamaño de un lote (no se pegó a un vecino) pero enorme. Con `cuadro`, lo
    que leyó el lector del cuadro de superficies."""
    ruta = carpeta / "digitalizado.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    datos["lotes"] = [dict(numero=n, poligono=_cuadro(x, 0, x + 300, 300), huecos=[], area_px=90000,
                           area_oficial=5000.0 if cuadro else None)
                      for n, x in (("8-01", 0), ("8-02", 300), ("8-03", 600))]
    x0, y0, x1, y1 = area_resto
    datos["sin_numero"] = [dict(poligono=_cuadro(x0, y0, x1, y1), area_px=float((x1 - x0) * (y1 - y0)),
                                de_lote=True, sugerencia=None),
                           dict(poligono=_cuadro(900, 0, 1000, 300), area_px=30000.0, de_lote=False,
                                sugerencia=None)]
    datos["lector"] = dict(activo=True, disponible=True, rotulos=[], semillas=0, apoyo_min=2, sin_poligono=[],
                           cuadricula=None, cuadro=cuadro or {})
    ruta.write_text(json.dumps(datos), encoding="utf-8")


def test_el_resto_de_la_propiedad_se_marca_para_preguntar(ana):
    """Sin cuadro, por su tamaño (más de 5 veces la mediana de los lotes); con la fila del
    resto en el cuadro, con su número y su área."""
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    carpeta = carpeta_del_plano(raiz, slug)
    _con_resto(carpeta)

    resto, camino = (r["properties"] for r in web.get(f"/api/kmz/{slug}/lotes").json()["features"][3:])

    assert resto["resto"] is True and resto["numero_resto"] is None and resto["de_lote"] is True
    x, y = resto["punto"]
    assert 0 < x < 1000 and 300 < y < 1000
    assert "resto" not in camino

    _con_resto(carpeta, RAPEL)
    resto = web.get(f"/api/kmz/{slug}/lotes").json()["features"][3]["properties"]
    assert (resto["numero_resto"], resto["area_resto_m2"]) == ("8", 760000.0)
    lector = web.get(f"/api/kmz/{slug}").json()["digitalizado"]["lector"]
    # El resto no es un número que falte: va aparte.
    assert lector["numeros_cuadro"] == ["8-01", "8-02", "8-03"] and lector["resto"] == "8"


def test_una_parte_un_poco_mas_grande_es_resto_solo_si_el_cuadro_lo_trae(ana):
    """Un lote sin número que quedó pegado a otro mide el doble: no se pregunta si es el
    resto, salvo que el cuadro traiga la fila del resto."""
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    carpeta = carpeta_del_plano(raiz, slug)
    _con_resto(carpeta, area_resto=(0, 300, 600, 600))           # 2 veces la mediana

    assert "resto" not in web.get(f"/api/kmz/{slug}/lotes").json()["features"][3]["properties"]
    _con_resto(carpeta, RAPEL, area_resto=(0, 300, 600, 600))
    assert web.get(f"/api/kmz/{slug}/lotes").json()["features"][3]["properties"]["resto"] is True


def test_dejar_fuera_el_resto_no_lo_cuenta_ni_pide_confirmar_al_crear(ana):
    from consola.plano import huella_digitalizar
    from pipeline.plano.digitalizar import leer_entradas

    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    carpeta = carpeta_del_plano(raiz, slug)
    _con_resto(carpeta, RAPEL)
    (carpeta / "huellas.json").write_text(
        json.dumps(dict(digitalizado=huella_digitalizar(leer_entradas(carpeta)))), encoding="utf-8")
    assert web.post(f"/api/kmz/{slug}/georreferenciar").status_code == 200
    assert web.get(f"/api/kmz/{slug}").json()["digitalizado"]["sin_numero_lote"] == 1
    assert web.post(f"/api/kmz/{slug}/crear").status_code == 409

    respuesta = web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, fuera=[EN_EL_RESTO]))

    assert respuesta.status_code == 200 and respuesta.json()["fuera"] == [[500.0, 500.0]]
    estado = web.get(f"/api/kmz/{slug}").json()
    # Es qué va al KMZ, no cómo se parte el dibujo: no hay que volver a leer ni a ubicar.
    assert estado["digitalizado"]["vigente"] is True and estado["georreferencia"]["vigente"] is True
    d = estado["digitalizado"]
    assert (d["sin_numero_lote"], d["sin_numero"], d["fuera"]) == (0, 1, 1)
    resto = web.get(f"/api/kmz/{slug}/lotes", params={"en": "lonlat"}).json()["features"][3]["properties"]
    assert resto["banderas"] == ["sin_numero", "fuera"] and resto["fuera"] is True and resto["de_lote"] is False
    assert resto["resto"] is True                       # la tarjeta lo muestra para poder cambiarlo
    respuesta = web.post(f"/api/kmz/{slug}/crear")
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["lotes"] == 3


def test_el_resto_incluido_va_al_kmz_con_su_numero(ana):
    """Con el número del cuadro ("8", con su área) o "Resto": no es un lote sin número."""
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    carpeta = carpeta_del_plano(raiz, slug)
    _con_resto(carpeta, RAPEL)
    ruta = carpeta / "digitalizado.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    resto = datos["sin_numero"].pop(0)
    datos["lotes"].append(dict(numero="8", poligono=resto["poligono"], huecos=[], area_px=resto["area_px"],
                               area_oficial=760000.0, origen="usuario"))
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert web.post(f"/api/kmz/{slug}/georreferenciar").status_code == 200

    ocho = web.get(f"/api/kmz/{slug}/lotes", params={"en": "lonlat"}).json()["features"][3]["properties"]

    assert ocho["numero"] == "8" and ocho["banderas"] == [] and ocho["resto"] is True
    assert ocho["area_oficial_m2"] == 760000.0
    assert web.post(f"/api/kmz/{slug}/crear").json()["lotes"] == 4
    with zipfile.ZipFile(next(carpeta.glob("*.kmz"))) as z:
        assert "<name>LOTE 8</name>" in z.read("doc.kml").decode("utf-8")

    # Sin número en el cuadro, como "Resto": ya no queda rojo por no ser un número de lote.
    datos["lotes"][3]["numero"] = "Resto"
    datos["lector"]["cuadro"] = {}
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    resto = web.get(f"/api/kmz/{slug}/lotes").json()["features"][3]["properties"]
    assert resto["banderas"] == [] and resto["resto"] is True
    assert web.post(f"/api/kmz/{slug}/crear").status_code == 201
    with zipfile.ZipFile(next(carpeta.glob("*.kmz"))) as z:
        assert "<name>RESTO</name>" in z.read("doc.kml").decode("utf-8")


def test_dejar_fuera_el_resto_que_numero_el_lector_lo_saca_del_kmz(ana):
    """En Caminos de Rapel el lector lee el "LOTE 8" impreso en el resto. Con la fila del
    resto en el cuadro no lo numera solo (`rotulos.combinar`), pero sin ella, o en un
    digitalizado de antes, sí: va al KMZ. Si ella lo deja fuera, no va, sin volver a leer
    el plano; el KMZ que ya estaba queda atrasado."""
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    carpeta = carpeta_del_plano(raiz, slug)
    _con_resto(carpeta, RAPEL)
    ruta = carpeta / "digitalizado.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    resto = datos["sin_numero"].pop(0)
    datos["lotes"].append(dict(numero="8", poligono=resto["poligono"], huecos=[], area_px=resto["area_px"],
                               area_oficial=760000.0, origen="lector", confianza=0.9, apoyo=3))
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert web.post(f"/api/kmz/{slug}/georreferenciar").status_code == 200
    assert web.post(f"/api/kmz/{slug}/crear").json()["lotes"] == 4
    assert web.get(f"/api/kmz/{slug}").json()["paso"] == "listo"

    assert web.put(f"/api/kmz/{slug}/entradas", json=dict(ENTRADAS, fuera=[EN_EL_RESTO])).status_code == 200

    estado = web.get(f"/api/kmz/{slug}").json()
    assert estado["paso"] == "crear" and estado["georreferencia"]["vigente"] is True
    assert (estado["digitalizado"]["lotes"], estado["digitalizado"]["fuera"]) == (3, 1)
    ocho = web.get(f"/api/kmz/{slug}/lotes").json()["features"][3]["properties"]
    assert ocho["numero"] == "8" and ocho["fuera"] is True and ocho["resto"] is True and ocho["banderas"] == ["fuera"]
    assert web.post(f"/api/kmz/{slug}/crear").json()["lotes"] == 3
    with zipfile.ZipFile(next(carpeta.glob("*.kmz"))) as z:
        assert "<name>LOTE 8</name>" not in z.read("doc.kml").decode("utf-8")
    assert web.get(f"/api/kmz/{slug}").json()["paso"] == "listo"


def test_el_resto_no_es_repetido_de_un_numero_que_no_se_reconoce(ana):
    """"Resto" y un número inválido no tienen id para el lector de KMZ: no son el mismo lote."""
    web, slug, raiz, _ = ana
    listo_para_ubicar(web, slug, raiz)
    carpeta = carpeta_del_plano(raiz, slug)
    _con_resto(carpeta)
    ruta = carpeta / "digitalizado.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    resto = datos["sin_numero"].pop(0)
    datos["lotes"].append(dict(numero="Resto", poligono=resto["poligono"], huecos=[], area_px=resto["area_px"]))
    datos["lotes"][0]["numero"] = "?"
    ruta.write_text(json.dumps(datos), encoding="utf-8")

    rasgos = [r["properties"] for r in web.get(f"/api/kmz/{slug}/lotes").json()["features"]]

    assert rasgos[0]["banderas"] == ["sin_numero"]
    assert rasgos[3]["numero"] == "Resto" and rasgos[3]["banderas"] == []
    # Dos "Resto" sí son el mismo, como al crear.
    datos["lotes"][0]["numero"] = "RESTO"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    rasgos = [r["properties"] for r in web.get(f"/api/kmz/{slug}/lotes").json()["features"]]
    assert rasgos[0]["banderas"] == rasgos[3]["banderas"] == ["duplicado"]
