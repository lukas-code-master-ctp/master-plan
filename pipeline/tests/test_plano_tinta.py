import cv2
import numpy as np
import pytest

from pipeline.plano import tinta
from pipeline.tests.plano_sintetico import NEGRO, PAPEL, PPMM, ROJO, VERDE


def hoja(alto=600, ancho=800):
    img = np.empty((alto, ancho, 3), np.uint8)
    img[:] = PAPEL
    return img


@pytest.mark.parametrize("color", [NEGRO, ROJO])
def test_las_lineas_rojas_y_negras_son_deslinde(color):
    img = hoja()
    cv2.line(img, (100, 300), (700, 300), color, 2)
    t = tinta.mascara(img, PPMM)
    assert t.lineas[299:302, 120:680].any(axis=0).all()
    assert t.firme[299:302, 120:680].any(axis=0).mean() > 0.95


def test_descarta_verde_azul_texto_y_puntos():
    img = hoja()
    cv2.line(img, (100, 100), (700, 100), VERDE, 2)                 # quebrada
    cv2.line(img, (100, 200), (700, 200), (40, 70, 200), 2)         # alta tensión
    for x in range(100, 700, 12):                                   # línea de puntos
        cv2.circle(img, (x, 300), 2, NEGRO, -1)
    cv2.putText(img, "LOTE 12", (300, 450), cv2.FONT_HERSHEY_SIMPLEX, 0.5, NEGRO, 1)   # texto chico
    t = tinta.mascara(img, PPMM)
    assert not t.lineas.any()


def test_achurado_es_relleno_y_no_lote():
    img = hoja()
    # Achurado cruzado: celdas de 5 × 5 px, mucho menores que HOLE_MM2.
    for k in range(200, 446, 6):
        cv2.line(img, (k, 200), (k, 400), NEGRO, 1)
    for k in range(200, 406, 6):
        cv2.line(img, (200, k), (440, k), NEGRO, 1)
    cv2.rectangle(img, (200, 200), (440, 400), NEGRO, 2)
    t = tinta.mascara(img, PPMM)
    assert t.grueso[250:350, 260:380].mean() > 0.9
    assert not t.grueso[450:, :].any()


def test_borra_el_pliegue_palido_y_deja_la_linea_que_lo_cruza():
    img = hoja(800, 900)
    cv2.line(img, (450, 0), (450, 799), (205, 205, 205), 3)          # pliegue: pálido, recto, largo
    cv2.line(img, (100, 400), (800, 400), NEGRO, 2)                  # deslinde que lo cruza
    t = tinta.mascara(img, PPMM)
    assert t.pliegues >= 1
    assert not t.lineas[100:380, 445:456].any()
    assert t.lineas[399:402, 445:456].any()


def test_ubica_y_borra_la_cuadricula():
    img = hoja(900, 900)
    # Línea vertical tenue, un poco inclinada, y un deslinde que la cruza.
    cv2.line(img, (403, 0), (409, 899), (150, 150, 150), 1, cv2.LINE_AA)
    cv2.line(img, (100, 500), (800, 500), NEGRO, 2)
    gris = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    [(p, q, valido)] = tinta.lineas_cuadricula(gris, PPMM, verticales=[400])
    assert valido
    assert p[0] == pytest.approx(403, abs=0.7)
    assert q[0] == pytest.approx(409, abs=0.7)

    sin = tinta.mascara(img, PPMM)
    banda = tinta.banda_cuadricula(img.shape, [(p, q)], PPMM)
    con = tinta.mascara(img, PPMM, banda)
    assert sin.lineas[100:400, 400:412].any()
    assert not con.lineas[100:400, 400:412].any()
    assert con.lineas[499:502, 400:412].any()
