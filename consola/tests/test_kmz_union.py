"""Crea tu KMZ con las hojas unidas: lo que la consola sirve, guarda y afina de la
unión (docs/specs/2026-10-06-kmz-unir-hojas.md). La geometría y el calce en sí están
en pipeline/tests/test_plano_union.py."""
import io
import threading

import cv2
import numpy as np
import pymupdf
import pytest
from PIL import Image

from consola import plano as plano_mod
from consola.tests.test_plano import ana, carpeta_del_plano, subir  # noqa: F401 - el fixture
from pipeline.plano import pagina as pg
from pipeline.plano import union as un

PPMM = 4.0
PAPEL, TINTA = (246, 244, 236), (30, 30, 30)
# Un plano de 360 × 240 mm a 4 px/mm, partido en dos láminas que se traslapan 240 px.
ANCHO, ALTO = 1440, 960
CORTE_1, CORTE_2 = 840, 600          # la hoja 1 llega hasta x = 840; la 2 parte en x = 600


def _plano() -> np.ndarray:
    """Dibujo de sobra para que Afinar encuentre puntos, sin un patrón repetido."""
    rng = np.random.default_rng(11)
    img = np.full((ALTO, ANCHO, 3), PAPEL, np.uint8)
    for _ in range(70):
        p, q = rng.integers(0, (ANCHO, ALTO), 2), rng.integers(0, (ANCHO, ALTO), 2)
        cv2.line(img, tuple(int(v) for v in p), tuple(int(v) for v in q), TINTA, int(rng.integers(1, 4)))
    for _ in range(90):
        x, y = (int(v) for v in rng.integers(0, (ANCHO - 60, ALTO - 40)))
        w, h = (int(v) for v in rng.integers(20, (90, 70)))
        cv2.rectangle(img, (x, y), (x + w, y + h), TINTA, int(rng.integers(1, 3)))
    for _ in range(160):
        x, y = (int(v) for v in rng.integers(0, (ANCHO - 40, ALTO)))
        cv2.putText(img, str(int(rng.integers(1, 999))), (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    float(rng.uniform(0.4, 0.9)), TINTA, 1, cv2.LINE_AA)
    return img


@pytest.fixture(scope="module")
def plano():
    return _plano()


def _pdf(imagenes, ppmm=PPMM) -> bytes:
    doc = pymupdf.open()
    for img in imagenes:
        buf = io.BytesIO()
        Image.fromarray(img).save(buf, "JPEG", quality=95)
        alto, ancho = img.shape[:2]
        hoja = doc.new_page(width=ancho / ppmm / pg.MM_POR_PUNTO, height=alto / ppmm / pg.MM_POR_PUNTO)
        hoja.insert_image(hoja.rect, stream=buf.getvalue())
    return doc.tobytes()


def pdf_partido(plano) -> bytes:
    """La hoja 1 tal cual y la 2 de lado en el PDF (se usa con giro de 90°)."""
    return _pdf([np.ascontiguousarray(plano[:, :CORTE_1]), pg.rotar(plano[:, CORTE_2:], 270)])


def hojas(dx_mm=0.0, dy_mm=0.0, angulo=0.0):
    """Las dos hojas en su lugar (la 2 corrida y girada lo que se pida), sin recortar."""
    ancho_2 = ANCHO - CORTE_2
    return [{"n": 1, "rotacion": 0, "angulo": 0.0, "x": (CORTE_1 - 1) / 2, "y": (ALTO - 1) / 2, "recorte": None},
            {"n": 2, "rotacion": 90, "angulo": angulo, "x": CORTE_2 + (ancho_2 - 1) / 2 + dx_mm * PPMM,
             "y": (ALTO - 1) / 2 + dy_mm * PPMM, "recorte": None}]


def entradas_unidas(lista=None, **cambios):
    return {**dict(pagina=0, rotacion=0, rectangulo=[10, 10, ANCHO - 10, ALTO - 10],
                   semillas=[dict(numero="1", x=200, y=150)], union={"hojas": lista or hojas()}), **cambios}


@pytest.fixture
def unido(ana, plano):  # noqa: F811 - el fixture de test_plano
    web, slug, raiz, comandos = ana
    assert subir(web, slug, pdf_partido(plano)).status_code == 201
    return web, slug, carpeta_del_plano(raiz, slug)


def _guardar(web, slug, entradas):
    return web.put(f"/api/kmz/{slug}/entradas", json=entradas)


def _imagen(respuesta) -> Image.Image:
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.headers["content-type"] == "image/jpeg"
    return Image.open(io.BytesIO(respuesta.content))


# --- las páginas para el editor --------------------------------------------------------

def test_subir_deja_la_pagina_media_y_la_resolucion_de_cada_una(ana):  # noqa: F811
    web, slug, raiz, _ = ana
    grande = np.full((900, 3000, 3), PAPEL, np.uint8)
    cv2.line(grande, (0, 0), (2999, 899), TINTA, 5)

    assert subir(web, slug, _pdf([grande, grande[:, :1200]])).status_code == 201

    carpeta = carpeta_del_plano(raiz, slug) / "paginas"
    assert sorted(p.name for p in carpeta.iterdir()) == [
        "1.jpg", "1_medio.jpg", "1_mini.jpg", "2.jpg", "2_medio.jpg", "2_mini.jpg", "info.json"]
    assert Image.open(carpeta / "1_medio.jpg").size == (2400, 720)
    assert Image.open(carpeta / "2_medio.jpg").size == (1200, 900)        # ya era chica
    medio = _imagen(web.get(f"/api/kmz/{slug}/paginas/1", params={"medio": 1}))
    assert medio.size == (2400, 720)
    info = plano_mod.Plano(carpeta.parent, carpeta.parent / "x.kmz").info()
    assert info[1]["ancho"] == 3000 and info[1]["alto"] == 900 and info[1]["ppmm"] == pytest.approx(PPMM)
    # Ni la media ni info.json son páginas.
    assert [p["n"] for p in web.get(f"/api/kmz/{slug}").json()["paginas"]] == [1, 2]


def test_la_pagina_media_se_hace_al_primer_pedido_en_un_pdf_de_antes(unido):
    web, slug, carpeta = unido
    (carpeta / "paginas" / "2_medio.jpg").unlink()
    (carpeta / "paginas" / "info.json").unlink()

    medio = _imagen(web.get(f"/api/kmz/{slug}/paginas/2", params={"medio": 1}))

    assert medio.size == (ALTO, ANCHO - CORTE_2)            # sin girar, como la página
    assert (carpeta / "paginas" / "2_medio.jpg").is_file()
    assert not [p for p in (carpeta / "paginas").iterdir() if p.name.startswith(".")]   # sin temporales
    # La resolución sale del PDF sin decodificar las páginas, y queda anotada.
    info = plano_mod.Plano(carpeta, carpeta / "x.kmz").info()
    assert {n: (p["ancho"], p["alto"]) for n, p in info.items()} == {1: (CORTE_1, ALTO), 2: (ALTO, ANCHO - CORTE_2)}
    assert all(p["ppmm"] == pytest.approx(PPMM) for p in info.values())
    assert (carpeta / "paginas" / "info.json").is_file()


def test_la_resolucion_de_una_pagina_sin_imagen_es_la_del_render(tmp_path):
    doc = pymupdf.open()
    doc.new_page(width=300, height=200).insert_text((20, 50), "plano vectorial")
    ruta = tmp_path / "vectorial.pdf"
    doc.save(ruta)

    [(megas, ppmm)] = plano_mod._medidas(ruta)

    assert ppmm == pytest.approx(pg.DPI_RENDER / 25.4)
    p = pg.extraer(ruta, 1)
    assert ppmm == pytest.approx(p.ppmm) and megas == pytest.approx(p.imagen.size / 3 / 1e6, rel=0.01)


# --- guardar la unión ------------------------------------------------------------------

def test_la_union_se_guarda_y_el_estado_dice_su_tamano(unido):
    web, slug, _ = unido

    respuesta = _guardar(web, slug, entradas_unidas())

    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["pagina"] == 0
    estado = web.get(f"/api/kmz/{slug}").json()
    union = un.leer({"hojas": hojas()})
    geo = un.geometria(union, {1: (CORTE_1, ALTO), 2: (ALTO, ANCHO - CORTE_2)}, {1: PPMM, 2: PPMM})
    assert (geo.ancho, geo.alto) == (ANCHO, ALTO)
    assert estado["union"] == dict(ancho=ANCHO, alto=ALTO, ppmm=pytest.approx(PPMM),
                                   hojas=estado["entradas"]["union"]["hojas"], huella=un.huella(union))
    # Las páginas, con su resolución (la geometría de la pantalla la necesita), y sin
    # la unión ni las cachés.
    assert estado["paginas"] == [dict(n=1, ancho=CORTE_1, alto=ALTO, ppmm=pytest.approx(PPMM)),
                                 dict(n=2, ancho=ALTO, alto=ANCHO - CORTE_2, ppmm=pytest.approx(PPMM))]
    web.get(f"/api/kmz/{slug}/paginas/0")
    assert [p["n"] for p in web.get(f"/api/kmz/{slug}").json()["paginas"]] == [1, 2]


def test_sin_union_el_estado_no_la_trae(unido):
    web, slug, _ = unido
    assert _guardar(web, slug, dict(pagina=1, rotacion=0)).status_code == 200
    assert web.get(f"/api/kmz/{slug}").json()["union"] is None


@pytest.mark.parametrize("cambio, mensaje", [
    (lambda h: h.append({**h[0], "n": 3}), "la hoja 3 no es una página del PDF"),
    (lambda h: h.append(dict(h[0])), "la hoja 1 está dos veces"),
    (lambda h: h.pop(), "entre 2 y 12 hojas"),
    (lambda h: h[1].update(recorte=[0, 0, ALTO + 1, 100]), "el recorte se sale de la hoja"),
    (lambda h: h[1].update(angulo=12), "el giro fino va entre"),
    (lambda h: h[1].update(x=float("1e12")), "demasiado grande"),
])
def test_una_union_mala_dice_que_esta_mal(unido, cambio, mensaje):
    web, slug, carpeta = unido
    lista = hojas()
    cambio(lista)

    respuesta = _guardar(web, slug, entradas_unidas(lista))

    assert respuesta.status_code == 400
    assert mensaje in respuesta.json()["detail"]
    assert not (carpeta / "entradas.json").exists()


def test_la_union_demasiado_grande_se_rechaza(unido, monkeypatch):
    web, slug, _ = unido
    monkeypatch.setattr(un, "MAX_MEGAPIXELES", 1.0)          # la unión tiene 1,38 MP

    respuesta = _guardar(web, slug, entradas_unidas())

    assert respuesta.status_code == 400
    assert "La unión es demasiado grande" in respuesta.json()["detail"]


@pytest.mark.parametrize("entradas, mensaje", [
    (dict(pagina=0, rotacion=0), "no hay hojas unidas"),
    (entradas_unidas(rotacion=90), "«rotacion» es 0"),
    (entradas_unidas(union={"hojas": hojas(), "cuadro": {"hoja": 2, "rect": [0, 0, 50, 2000]}}),
     "el cuadro de superficies se sale de la hoja"),
    (entradas_unidas(union={"hojas": hojas(), "cuadro": {"hoja": 3, "rect": [0, 0, 50, 50]}}),
     "una de las hojas unidas"),
])
def test_pagina_cero_y_cuadro_de_la_union(unido, entradas, mensaje):
    web, slug, _ = unido
    respuesta = _guardar(web, slug, entradas)
    assert respuesta.status_code == 400
    assert mensaje in respuesta.json()["detail"]


def test_el_cuadro_de_la_union_va_en_px_de_su_hoja(unido):
    web, slug, _ = unido
    # La hoja 2 girada mide ALTO × (ANCHO − CORTE_2) = 960 × 840: el rect cabe en ella
    # aunque no tenga sentido en px de unión.
    cuadro = {"hoja": 2, "rect": [10, 700, 300, 830]}
    respuesta = _guardar(web, slug, entradas_unidas(union={"hojas": hojas(), "cuadro": cuadro}))
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["union"]["cuadro"] == cuadro


# --- la imagen de la unión ---------------------------------------------------------------

def _componer_contado(monkeypatch):
    llamadas = []
    original = un.componer

    def contado(*args, **kwargs):
        llamadas.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(un, "componer", contado)
    return llamadas


def test_la_pagina_cero_es_la_union_y_queda_en_cache(unido, plano, monkeypatch):
    web, slug, carpeta = unido
    _guardar(web, slug, entradas_unidas())
    huella = web.get(f"/api/kmz/{slug}").json()["union"]["huella"]
    llamadas = _componer_contado(monkeypatch)

    imagen = _imagen(web.get(f"/api/kmz/{slug}/paginas/0", params={"v": huella}))
    otra_vez = web.get(f"/api/kmz/{slug}/paginas/0", params={"v": huella})

    assert imagen.size == (ANCHO, ALTO)
    # Las dos hojas en su lugar recomponen el plano (salvo el JPEG).
    diferencia = np.abs(np.asarray(imagen.convert("RGB"), float) - plano.astype(float))
    assert diferencia.mean() < 6
    assert otra_vez.content == web.get(f"/api/kmz/{slug}/paginas/0", params={"v": huella}).content
    assert llamadas == [1]
    assert otra_vez.headers["cache-control"] == "private, no-cache"
    cache = carpeta / "paginas" / f"union-{huella}.jpg"
    assert cache.is_file()
    assert max(_imagen(web.get(f"/api/kmz/{slug}/paginas/0", params={"mini": 1})).size) <= 480
    assert llamadas == [1]


def test_dos_pedidos_a_la_vez_componen_una_sola_vez(unido, monkeypatch):
    web, slug, carpeta = unido
    _guardar(web, slug, entradas_unidas())
    llamadas = _componer_contado(monkeypatch)
    p = plano_mod.Plano(carpeta, carpeta / "x.kmz")
    rutas = []
    hilos = [threading.Thread(target=lambda: rutas.append(p.imagen(0))) for _ in range(3)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join()
    assert len(rutas) == 3 and len(set(rutas)) == 1 and rutas[0].is_file()
    assert llamadas == [1]


def test_una_union_grande_se_sirve_reducida(unido, plano, monkeypatch):
    web, slug, _ = unido
    _guardar(web, slug, entradas_unidas())
    monkeypatch.setattr(plano_mod, "MAX_MEGAPIXELES_PANTALLA", ANCHO * ALTO / 4 / 1e6)

    imagen = _imagen(web.get(f"/api/kmz/{slug}/paginas/0"))

    assert imagen.size == (ANCHO // 2, ALTO // 2)
    # Estirada a los px de página, es la misma unión.
    chica = cv2.resize(plano, (ANCHO // 2, ALTO // 2), interpolation=cv2.INTER_AREA)
    assert np.abs(np.asarray(imagen.convert("RGB"), float) - chica).mean() < 8
    # El tamaño lógico no cambia.
    assert web.get(f"/api/kmz/{slug}").json()["union"]["ancho"] == ANCHO


def test_cambiar_la_union_borra_la_cache_de_la_anterior(unido):
    web, slug, carpeta = unido
    _guardar(web, slug, entradas_unidas())
    web.get(f"/api/kmz/{slug}/paginas/0")
    lista = hojas()
    lista[1]["recorte"] = [240, 0, ANCHO - CORTE_2, ALTO]       # sin el traslape
    assert _guardar(web, slug, entradas_unidas(lista)).status_code == 200

    nueva = web.get(f"/api/kmz/{slug}").json()["union"]["huella"]
    assert _imagen(web.get(f"/api/kmz/{slug}/paginas/0")).size == (ANCHO, ALTO)

    assert {p.name for p in (carpeta / "paginas").glob("union-*")} == {
        f"union-{nueva}.jpg", f"union-{nueva}_medio.jpg", f"union-{nueva}_mini.jpg"}


def test_sin_union_la_pagina_cero_no_existe(unido):
    web, slug, _ = unido
    respuesta = web.get(f"/api/kmz/{slug}/paginas/0")
    assert respuesta.status_code == 404
    assert "no hay hojas unidas" in respuesta.json()["detail"]


def test_otro_pdf_se_lleva_la_union(unido, plano):
    web, slug, carpeta = unido
    _guardar(web, slug, entradas_unidas())
    web.get(f"/api/kmz/{slug}/paginas/0")

    assert subir(web, slug, pdf_partido(plano)).status_code == 201

    assert not list((carpeta / "paginas").glob("union-*"))
    assert not (carpeta / "entradas.json").exists()
    assert web.get(f"/api/kmz/{slug}").json()["union"] is None
    assert web.get(f"/api/kmz/{slug}/paginas/0").status_code == 404



def test_la_union_se_relee_con_el_candado_y_falta_una_se_compone(unido):
    web, slug, carpeta = unido
    _guardar(web, slug, entradas_unidas())
    vieja = web.get(f"/api/kmz/{slug}").json()["union"]["huella"]
    assert web.get(f"/api/kmz/{slug}/paginas/0").status_code == 200
    lista = hojas()
    lista[1]["recorte"] = [240, 0, ANCHO - CORTE_2, ALTO]
    assert _guardar(web, slug, entradas_unidas(lista)).status_code == 200
    nueva = web.get(f"/api/kmz/{slug}").json()["union"]["huella"]
    assert nueva != vieja
    p = plano_mod.Plano(carpeta, carpeta / "x.kmz")

    # Un pedido que leyó la unión vieja antes de esperar el candado compone la guardada.
    assert p._componer_union("").name == f"union-{nueva}.jpg"
    assert not list((carpeta / "paginas").glob(f"union-{vieja}*"))
    # Si falta la media (la consola se cayó a medio escribir), se hace de nuevo.
    (carpeta / "paginas" / f"union-{nueva}_medio.jpg").unlink()
    assert _imagen(web.get(f"/api/kmz/{slug}/paginas/0", params={"medio": 1})).size == (ANCHO, ALTO)


def test_volver_a_una_pagina_borra_la_imagen_de_la_union(unido):
    web, slug, carpeta = unido
    _guardar(web, slug, entradas_unidas())
    assert web.get(f"/api/kmz/{slug}/paginas/0").status_code == 200

    assert _guardar(web, slug, entradas_unidas(pagina=1, union=None)).status_code == 200

    assert not list((carpeta / "paginas").glob("union-*"))


def test_un_info_json_danado_se_vuelve_a_calcular(unido):
    _, _, carpeta = unido
    (carpeta / "paginas" / "info.json").write_text("{", encoding="utf-8")

    info = plano_mod.Plano(carpeta, carpeta / "x.kmz").info()

    assert {n: (p["ancho"], p["alto"]) for n, p in info.items()} == {1: (CORTE_1, ALTO), 2: (ALTO, ANCHO - CORTE_2)}
    assert all(p["ppmm"] == pytest.approx(PPMM) for p in info.values())


# --- afinar ------------------------------------------------------------------------------

def _error_px(hoja: dict, verdad: dict) -> float:
    """Lo más que se alejan las esquinas de la hoja 2 girada de su lugar verdadero."""
    ancho, alto = ALTO, ANCHO - CORTE_2
    esquinas = un._esquinas((0, 0, ancho, alto))
    bien = pg._aplicar(un._matriz(ancho, alto, 1.0, verdad["angulo"], verdad["x"], verdad["y"]), esquinas)
    hecha = pg._aplicar(un._matriz(ancho, alto, 1.0, hoja["angulo"], hoja["x"], hoja["y"]), esquinas)
    return float(np.linalg.norm(bien - hecha, axis=1).max())


def test_afinar_calza_la_hoja_corrida_y_no_guarda_nada(unido):
    web, slug, carpeta = unido
    antes = sorted(p.name for p in carpeta.rglob("*"))

    respuesta = web.post(f"/api/kmz/{slug}/union/afinar", json={"hojas": hojas(18, -11, 1.3)})

    assert respuesta.status_code == 200, respuesta.text
    salida = respuesta.json()["hojas"]
    assert [h["n"] for h in salida] == [1, 2]
    assert salida[0] == {**hojas()[0], "calzada": True, "residuo_mm": None}
    assert salida[1]["calzada"] is True and salida[1]["rotacion"] == 90
    assert _error_px(salida[1], hojas()[1]) < 1.5
    assert salida[1]["residuo_mm"] < 0.5
    assert sorted(p.name for p in carpeta.rglob("*")) == antes


def test_afinar_una_hoja_lejos_la_deja_como_estaba(unido):
    web, slug, _ = unido
    # Más allá de lo que Afinar busca aun con una hoja lejos (MAX_CORRECCION_LEJOS_MM).
    lejos = hojas(400, 0, 0)

    salida = web.post(f"/api/kmz/{slug}/union/afinar", json={"hojas": lejos}).json()["hojas"]

    assert salida[1] == {**lejos[1], "calzada": False, "residuo_mm": None}


def test_afinar_revisa_las_hojas_y_pide_el_pdf(ana, plano):  # noqa: F811
    web, slug, _, _ = ana
    assert web.post(f"/api/kmz/{slug}/union/afinar", json={"hojas": hojas()}).status_code == 409
    subir(web, slug, pdf_partido(plano))
    lista = hojas()
    lista[1]["n"] = 7
    respuesta = web.post(f"/api/kmz/{slug}/union/afinar", json={"hojas": lista})
    assert respuesta.status_code == 400
    assert "la hoja 7 no es una página del PDF" in respuesta.json()["detail"]
