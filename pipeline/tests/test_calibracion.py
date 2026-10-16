"""Calibración fina de la pose contra la foto: las líneas del KMZ deben caer sobre los caminos."""
import math

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFilter

from pipeline import geo
from pipeline.calibracion import Ajuste, aplicar, calibrar, calibrar_altura, mapa_de_caminos
from pipeline.proyeccion import Vista, proyectar_punto

VISTA = Vista(id="p01-100", posicion=1, lon=-72.0, lat=-35.0,
              altura_relativa=100.0, altura_absoluta=350.0, rumbo0=37.0)
GRADO_LON = geo.metros_por_grado_lon(VISTA.lat)


def desplazar(este_m, norte_m):
    return (VISTA.lon + este_m / GRADO_LON, VISTA.lat + norte_m / geo.METROS_POR_GRADO_LAT)


# Una rejilla de "caminos" alrededor del dron, a 150-400 m.
LINEAS = [[desplazar(-400, n), desplazar(400, n)] for n in (-350, -200, 200, 350)] + \
         [[desplazar(e, -400), desplazar(e, 400)] for e in (-350, -200, 200, 350)]


def foto_sintetica(vista_real: Vista, ancho=2048) -> np.ndarray:
    """Un mapa de caminos donde las líneas se ven exactamente donde las pone `vista_real`."""
    alto = ancho // 2
    lienzo = Image.new("L", (ancho, alto), 0)
    dibujo = ImageDraw.Draw(lienzo)
    for linea in LINEAS:
        puntos = []
        for k in range(201):
            f = k / 200
            p = (linea[0][0] + (linea[1][0] - linea[0][0]) * f, linea[0][1] + (linea[1][1] - linea[0][1]) * f)
            az, el, _ = proyectar_punto(vista_real, p)
            puntos.append((((az - vista_real.rumbo0) % 360) / 360 * ancho, (90 - el) / 180 * alto))
        for a, b in zip(puntos, puntos[1:]):
            if abs(a[0] - b[0]) < ancho / 2:
                dibujo.line([a, b], fill=255, width=3)
    return np.asarray(lienzo.filter(ImageFilter.GaussianBlur(3))).astype(np.float64) / 255


def test_el_mapa_de_caminos_marca_lo_claro_y_poco_saturado(tmp_path):
    imagen = Image.new("RGB", (400, 200), (60, 110, 40))            # pasto
    ImageDraw.Draw(imagen).rectangle([0, 90, 400, 110], fill=(205, 190, 160))   # camino de tierra
    ruta = tmp_path / "pano.jpg"
    imagen.save(ruta, "JPEG", quality=95)

    mapa = mapa_de_caminos(ruta, ancho=400)

    assert mapa.shape == (200, 400)
    assert mapa[100, 200] > 0.8
    assert mapa[30, 200] < 0.1


def test_recupera_una_inclinacion_conocida():
    real = Vista(**{**VISTA.__dict__, "giro": 0.3, "inclinacion_este": 0.8,
                    "inclinacion_norte": -0.4, "desnivel": 0.0})
    mapa = foto_sintetica(real)

    ajuste = calibrar(VISTA, LINEAS, None, mapa)

    assert ajuste.giro == pytest.approx(0.3, abs=0.1)
    assert ajuste.inclinacion_este == pytest.approx(0.8, abs=0.1)
    assert ajuste.inclinacion_norte == pytest.approx(-0.4, abs=0.1)
    assert abs(ajuste.desnivel) <= 3.0
    assert ajuste.aplicado


def test_no_aplica_un_ajuste_que_no_mejora_nada():
    ruido = np.random.default_rng(1).random((512, 1024)) * 0.05

    ajuste = calibrar(VISTA, LINEAS, None, ruido)

    assert not ajuste.aplicado
    assert (ajuste.giro, ajuste.inclinacion_este, ajuste.inclinacion_norte, ajuste.desnivel) == (0, 0, 0, 0)


def test_descarta_un_ajuste_que_queda_pegado_al_tope():
    """Hacienda Vichuquén, punto IV: con el sol bajo los potreros secos también son
    claros, y la búsqueda arrastró las líneas hacia ellos hasta el tope de cada
    parámetro. Pegado al tope no es un óptimo sino algo que el ajuste no puede
    explicar: el dibujo quedaba corrido y sin ajuste calzaba bien."""
    real = Vista(**{**VISTA.__dict__, "giro": 3.5, "inclinacion_este": 0.0,
                    "inclinacion_norte": 0.0, "desnivel": 0.0})
    mapa = foto_sintetica(real)

    ajuste = calibrar(VISTA, LINEAS, None, mapa)

    assert not ajuste.aplicado
    assert "giro" in ajuste.tope


def test_un_ajuste_dentro_de_los_limites_no_avisa_tope():
    real = Vista(**{**VISTA.__dict__, "giro": 0.3, "inclinacion_este": 0.8,
                    "inclinacion_norte": -0.4, "desnivel": 0.0})

    assert calibrar(VISTA, LINEAS, None, foto_sintetica(real)).tope == ""


def test_aplicar_deja_la_correccion_en_la_vista():
    ajuste = Ajuste(giro=0.2, inclinacion_este=0.5, inclinacion_norte=-0.1, desnivel=2.0,
                    puntaje_antes=0.1, puntaje_despues=0.13)

    corregida = aplicar(VISTA, ajuste)

    assert (corregida.giro, corregida.inclinacion_este, corregida.inclinacion_norte,
            corregida.desnivel) == (0.2, 0.5, -0.1, 2.0)
    assert corregida.rumbo0 == VISTA.rumbo0


def test_aplicar_suma_a_la_pose_que_ya_traia_la_vista():
    """La nivelación con el horizonte deja una pose; el ajuste fino se suma a ella."""
    nivelada = Vista(**{**VISTA.__dict__, "inclinacion_este": 0.6, "inclinacion_norte": 1.2})
    ajuste = Ajuste(giro=0.2, inclinacion_este=-0.1, inclinacion_norte=0.1, desnivel=2.0)

    corregida = aplicar(nivelada, ajuste)

    assert (corregida.giro, corregida.inclinacion_este, corregida.inclinacion_norte,
            corregida.desnivel) == (0.2, 0.5, 1.3, 2.0)


def test_busca_a_partir_de_la_pose_nivelada():
    """Con la vista ya cerca del óptimo, el ajuste es solo la diferencia que falta,
    aunque la inclinación total pase el tope de la búsqueda."""
    real = Vista(**{**VISTA.__dict__, "giro": 0.3, "inclinacion_este": 2.6,
                    "inclinacion_norte": -0.4, "desnivel": 0.0})
    nivelada = Vista(**{**VISTA.__dict__, "inclinacion_este": 2.0})

    ajuste = calibrar(nivelada, LINEAS, None, foto_sintetica(real))

    assert ajuste.tope == ""
    assert ajuste.inclinacion_este == pytest.approx(0.6, abs=0.1)
    assert aplicar(nivelada, ajuste).inclinacion_este == pytest.approx(2.6, abs=0.1)


def inclinacion_por_desnivel(desnivel: float) -> tuple[float, float]:
    """Lo que daría el horizonte: la inclinación cambia con la altura supuesta del dron."""
    return 0.6 - 0.01 * desnivel, 1.1 - 0.012 * desnivel


INCLINACIONES = {float(d): inclinacion_por_desnivel(d) for d in range(-40, 41, 10)}

# Desde 500 m, como en Quillón: unas decenas de metros de desnivel son un pequeño
# estiramiento, no otro dibujo.
VISTA_ALTA = Vista(**{**VISTA.__dict__, "altura_relativa": 500.0, "altura_absoluta": 750.0})


def vista_con_desnivel(desnivel: float, giro: float = 0.0) -> Vista:
    este, norte = inclinacion_por_desnivel(desnivel)
    return Vista(**{**VISTA_ALTA.__dict__, "giro": giro, "inclinacion_este": este,
                    "inclinacion_norte": norte, "desnivel": desnivel})


def test_calibrar_altura_encuentra_el_desnivel_con_la_inclinacion_del_horizonte():
    """Lomas de Quillón: el dron estaba ~55 m más abajo de lo que decía, el dibujo
    quedaba estirado hacia afuera y la nivelación con el horizonte no lo arreglaba,
    porque la inclinación que da depende de esa altura."""
    nivelada = vista_con_desnivel(0.0)
    mapa = foto_sintetica(vista_con_desnivel(22.0, giro=0.3))

    ajuste = calibrar_altura(nivelada, LINEAS, None, mapa, INCLINACIONES)
    corregida = aplicar(nivelada, ajuste)

    assert ajuste.tope == ""
    assert corregida.desnivel == pytest.approx(22.0, abs=2.0)
    assert corregida.giro == pytest.approx(0.3, abs=0.05)
    # La inclinación no se busca: es la del horizonte para ese desnivel.
    assert (corregida.inclinacion_este, corregida.inclinacion_norte) == pytest.approx(
        inclinacion_por_desnivel(corregida.desnivel), abs=0.01)


def test_calibrar_altura_sin_caminos_no_cambia_nada():
    ruido = np.random.default_rng(1).random((512, 1024)) * 0.05

    ajuste = calibrar_altura(vista_con_desnivel(0.0), LINEAS, None, ruido, INCLINACIONES)

    assert not ajuste.aplicado


def test_calibrar_altura_descarta_un_desnivel_en_el_borde_de_lo_probado():
    mapa = foto_sintetica(vista_con_desnivel(55.0))

    ajuste = calibrar_altura(vista_con_desnivel(0.0), LINEAS, None, mapa, INCLINACIONES)

    assert not ajuste.aplicado
    assert "desnivel" in ajuste.tope
