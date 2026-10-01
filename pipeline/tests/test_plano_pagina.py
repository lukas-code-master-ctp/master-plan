import io

import cv2
import numpy as np
import pymupdf
import pytest
from PIL import Image

from pipeline.plano import pagina as pag


def _jpeg(ancho=640, alto=480) -> tuple[bytes, np.ndarray]:
    rng = np.random.default_rng(1)
    img = rng.integers(0, 256, (alto, ancho, 3), dtype=np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 3)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "JPEG", quality=90)
    datos = buf.getvalue()
    return datos, np.asarray(Image.open(io.BytesIO(datos)).convert("RGB"))


def test_saca_la_imagen_embebida_sin_rerasterizar(tmp_path):
    datos, esperada = _jpeg()
    doc = pymupdf.open()
    # Hoja de 10 × 7,5 pulgadas: la imagen queda a 64 dpi, lejos de los 200 del render.
    hoja = doc.new_page(width=720, height=540)
    hoja.insert_image(hoja.rect, stream=datos)
    doc.save(tmp_path / "plano.pdf")

    p = pag.extraer(tmp_path / "plano.pdf", 1)

    assert p.fuente == "embebida"
    assert p.imagen.shape == (480, 640, 3)
    assert np.array_equal(p.imagen, esperada)
    assert p.ppmm == pytest.approx(64 / 25.4)
    assert p.paginas == 1


def test_sin_imagen_que_cubra_la_hoja_renderiza_a_200_dpi(tmp_path):
    datos, _ = _jpeg(64, 48)
    doc = pymupdf.open()
    hoja = doc.new_page(width=360, height=288)
    hoja.insert_text((20, 40), "PLANO VECTORIAL")
    hoja.insert_image(pymupdf.Rect(200, 200, 264, 248), stream=datos)   # un logo chico
    doc.save(tmp_path / "plano.pdf")

    p = pag.extraer(tmp_path / "plano.pdf", 1)

    assert p.fuente == "render"
    assert p.imagen.shape == (800, 1000, 3)
    assert p.ppmm == pytest.approx(200 / 25.4)


def test_pagina_que_no_existe(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    doc.save(tmp_path / "plano.pdf")
    with pytest.raises(ValueError, match="1 páginas"):
        pag.extraer(tmp_path / "plano.pdf", 2)


@pytest.mark.parametrize("grados", [0, 90, 180, 270])
def test_rotar_y_rotar_punto_coinciden(grados):
    img = np.arange(5 * 7 * 3, dtype=np.uint8).reshape(5, 7, 3)
    girada = pag.rotar(img, grados)
    for x, y in ((0, 0), (6, 0), (3, 2), (6, 4)):
        xr, yr = pag.rotar_punto(x, y, grados, 7, 5)
        assert np.array_equal(girada[int(yr), int(xr)], img[y, x])
    assert girada.shape == ((5, 7, 3) if grados in (0, 180) else (7, 5, 3))


def test_rotacion_invalida():
    with pytest.raises(ValueError):
        pag.rotar(np.zeros((2, 2, 3), np.uint8), 45)


def test_recorte_remuestrea_y_vuelve_a_la_pagina():
    img = np.zeros((400, 500, 3), np.uint8)
    e = pag.encuadrar(img, 3.0, [100, 50, 300, 250])
    assert e.modo == "recorte"
    assert e.ppmm == pytest.approx(pag.PPMM_TRABAJO_MINIMO)
    assert e.imagen.shape[:2] == (400, 400)
    puntos = np.array([[100, 50], [299, 249], [150.5, 75.25]])
    assert np.allclose(e.a_pagina(e.a_trabajo(puntos)), puntos)
    # El centro del primer píxel del recorte, escalado ×2.
    assert np.allclose(e.a_trabajo([[100, 50]]), [[0.5, 0.5]])


def test_un_escaneo_muy_fino_se_reduce_al_tope():
    # Un A0 a 300 dpi (11,8 px/mm) se digitaliza a PPMM_TRABAJO_MAXIMO: si no, no cabe en memoria.
    img = np.zeros((1200, 1000, 3), np.uint8)
    e = pag.encuadrar(img, 12.0, [100, 100, 700, 1000])
    assert e.ppmm == pytest.approx(pag.PPMM_TRABAJO_MAXIMO)
    assert e.imagen.shape[:2] == (600, 400)
    puntos = np.array([[100, 100], [699, 999], [321.5, 456.25]])
    assert np.allclose(e.a_pagina(e.a_trabajo(puntos)), puntos)
    # Entre el mínimo y el tope, la imagen queda tal cual.
    assert pag.encuadrar(img, 7.0, [0, 0, 1000, 1200]).imagen.shape[:2] == (1200, 1000)


def test_tapar_pinta_del_color_del_papel():
    img = np.full((50, 50, 3), 240, np.uint8)
    img[10:20, 10:20] = 0
    papel = pag.color_papel(img, [0, 0, 50, 50])
    tapada = pag.tapar(img, [[5, 5, 25, 25]], papel)
    assert (tapada[10:20, 10:20] == 240).all()
    assert (img[10:20, 10:20] == 0).all()


def test_rectifica_la_perspectiva_por_las_esquinas_del_marco():
    # Una hoja con un marco de 200 × 150 mm a 6 px/mm, fotografiada en perspectiva.
    ppmm, marco = 6.0, (200.0, 150.0)
    w, h = int(marco[0] * ppmm), int(marco[1] * ppmm)
    hoja = np.full((h + 120, w + 120, 3), 240, np.uint8)
    esquinas_hoja = np.float32([[60, 60], [60 + w, 60], [60 + w, 60 + h], [60, 60 + h]])
    cv2.polylines(hoja, [esquinas_hoja.astype(np.int32)], True, (0, 0, 0), 2)
    cv2.circle(hoja, (60 + 300, 60 + 450), 20, (0, 0, 0), -1)
    foto_esquinas = np.float32([[90, 40], [1280, 110], [1230, 1000], [40, 930]])
    H = cv2.getPerspectiveTransform(esquinas_hoja, foto_esquinas)
    foto = cv2.warpPerspective(hoja, H, (1350, 1050), flags=cv2.INTER_CUBIC, borderValue=(240, 240, 240))

    e = pag.encuadrar(foto, 2.0, [0, 0, 1350, 1050], esquinas=foto_esquinas.tolist(), marco_mm=marco)

    assert e.modo == "perspectiva"
    assert e.ppmm == pytest.approx(6.0)
    # Las esquinas del marco quedan a 200 × 150 mm de papel.
    c = e.a_trabajo(foto_esquinas)
    assert np.linalg.norm(c[1] - c[0]) == pytest.approx(w, abs=0.5)
    assert np.linalg.norm(c[3] - c[0]) == pytest.approx(h, abs=0.5)
    assert np.dot(c[1] - c[0], c[3] - c[0]) == pytest.approx(0, abs=1.0)
    # El círculo vuelve a su lugar en mm de papel (50, 75) desde la esquina del marco.
    gris = cv2.cvtColor(e.imagen, cv2.COLOR_RGB2GRAY)
    ys, xs = np.nonzero(gris < 100)
    dentro = (abs(xs - c[0][0] - 300) < 40) & (abs(ys - c[0][1] - 450) < 40)
    assert xs[dentro].mean() - c[0][0] == pytest.approx(300, abs=1.0)
    assert ys[dentro].mean() - c[0][1] == pytest.approx(450, abs=1.0)
    # Ida y vuelta entre la foto y el trabajo.
    p = np.array([[400.0, 300.0], [1000.0, 800.0]])
    assert np.allclose(e.a_pagina(e.a_trabajo(p)), p)


def test_sin_tamano_de_marco_conserva_el_largo_medio_de_los_lados():
    img = np.full((300, 400, 3), 240, np.uint8)
    esquinas = [[10, 10], [310, 20], [300, 220], [20, 210]]
    e = pag.encuadrar(img, 8.0, [0, 0, 400, 300], esquinas=esquinas)
    c = e.a_trabajo(esquinas)
    arriba, izquierda = np.linalg.norm(c[1] - c[0]), np.linalg.norm(c[3] - c[0])
    medio_ancho = (np.hypot(300, 10) + np.hypot(280, 10)) / 2
    medio_alto = (np.hypot(10, 200) + np.hypot(10, 200)) / 2
    assert arriba == pytest.approx(medio_ancho, rel=1e-3)
    assert izquierda == pytest.approx(medio_alto, rel=1e-3)
    assert e.ppmm == 8.0


def test_el_rectangulo_no_puede_cruzar_el_horizonte_de_la_foto():
    # Una foto oblicua: los lados del marco se juntan en y = -300 (el horizonte).
    img = np.full((600, 800, 3), 240, np.uint8)
    esquinas = [[250, 100], [550, 100], [700, 500], [100, 500]]
    e = pag.encuadrar(img, 4.0, [100, 100, 700, 500], esquinas=esquinas, marco_mm=[200, 200])
    assert e.imagen.shape[:2] == (1202, 2401)
    for rect in ([0, -400, 800, 600],      # cruza el horizonte
                 [0, 0, 800, 600]):        # no lo cruza, pero rectificado sería enorme
        with pytest.raises(ValueError, match="se sale de la hoja"):
            pag.encuadrar(img, 4.0, rect, esquinas=esquinas, marco_mm=[200, 200])
