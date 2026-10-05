import math

import cv2
import numpy as np
import pytest
from shapely import affinity as shapely_affinity
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from pipeline.plano import particion
from pipeline.plano.digitalizar import digitalizar_imagen
from pipeline.plano.tinta import mascara
from pipeline.tests.plano_sintetico import NEGRO, PPMM, ROJO, dibujar, iou

# Medio píxel de tolerancia a lo largo de todo el contorno de un lote.
EPSILON_PX2 = 1.0


def _digitalizar(plano, **kw):
    alto, ancho = plano.imagen.shape[:2]
    return digitalizar_imagen(plano.imagen, PPMM, plano.semillas, [0, 0, ancho, alto], avance=lambda _: None, **kw)


def _revisar_topologia(lotes, sin_numero, contorno):
    # Sin traslapes: la suma de áreas es el área de la unión.
    union = unary_union(list(lotes.values()))
    assert sum(p.area for p in lotes.values()) - union.area < EPSILON_PX2
    # Sin huecos dentro del contorno: lotes y caras sin número lo cubren entero.
    todo = unary_union(list(lotes.values()) + sin_numero)
    assert todo.geom_type == "Polygon" and not list(todo.interiors)
    assert iou(todo, contorno) > 0.99
    # Los lotes vecinos comparten el deslinde: se tocan a lo largo de una línea, no
    # en un punto ni con una franja entre ellos.
    compartidos = 0
    for a, pa in lotes.items():
        for b, pb in lotes.items():
            if a < b and pa.distance(pb) < 0.5:
                contacto = pa.intersection(pb)
                assert contacto.area < EPSILON_PX2
                compartidos += contacto.length > 10
    return compartidos


@pytest.mark.parametrize("color", [NEGRO, ROJO], ids=["negra", "roja"])
def test_grilla_de_lotes(color):
    plano = dibujar(color)
    r = _digitalizar(plano)

    assert len(r.lotes) == len(plano.semillas)
    assert r.estadisticas["faltantes"] == []
    for numero, x, y in plano.semillas:
        dueños = [n for n, p in r.lotes.items() if p.contains(Point(x, y))]
        assert dueños == [numero]
        assert iou(r.lotes[numero], plano.celdas[numero]) > 0.95
    # 12 lotes en 3 filas de 4: 9 deslindes horizontales... salvo los que cruza el camino.
    assert _revisar_topologia(r.lotes, r.sin_numero, plano.contorno) >= 3 * 3 + 2 * 4 - 4
    # El camino de doble línea es una cara sin número, no un lote.
    assert any(iou(c, plano.camino) > 0.8 for c in r.sin_numero)
    # Deslindes rectos: pocos vértices por lote.
    vertices = [len(p.exterior.coords) - 1 for p in r.lotes.values()]
    assert np.median(vertices) <= 6
    assert max(vertices) <= 10


def test_la_divisoria_doble_angosta_se_reparte_entre_los_vecinos():
    plano = dibujar()
    r = _digitalizar(plano)
    # Lotes 2 y 3 (fila 0) y 6 y 7 (fila 1) están a ambos lados de la línea doble.
    for a, b in (("2", "3"), ("6", "7")):
        x0, y0, x1, y1 = plano.celdas[a].bounds
        contacto = r.lotes[a].intersection(r.lotes[b])
        assert contacto.length > 0.9 * (y1 - y0)
        assert abs(contacto.centroid.x - x1) < 6


def test_un_rotulo_subrayado_que_toca_los_deslindes_no_parte_el_lote():
    # Un lote angosto (12 mm) con el rótulo en negrita y subrayado de lado a lado: el
    # texto pasa por línea y toca los dos deslindes, pero el lote sale entero.
    ancho_mm, alto_mm, m = 12.0, 30.0, 20.0
    px = lambda v: int(round(v * PPMM))
    img = np.full((px(alto_mm + 2 * m), px(3 * ancho_mm + 2 * m), 3), 245, np.uint8)
    xs = [px(m + i * ancho_mm) for i in range(4)]
    y0, y1 = px(m), px(m + alto_mm)
    for x in xs:
        cv2.line(img, (x, y0), (x, y1), ROJO, 2)
    for y in (y0, y1):
        cv2.line(img, (xs[0], y), (xs[-1], y), ROJO, 2)
    semillas = []
    for i in range(3):
        cx, cy = (xs[i] + xs[i + 1]) / 2, (y0 + y1) / 2
        cv2.putText(img, "LOTE", (xs[i] + 4, int(cy) - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, NEGRO, 2)
        cv2.line(img, (xs[i] + 1, int(cy) + 4), (xs[i + 1] - 1, int(cy) + 4), NEGRO, 2)   # subrayado
        semillas.append((str(i + 1), cx, cy))
    alto, ancho = img.shape[:2]
    r = digitalizar_imagen(img, PPMM, semillas, [0, 0, ancho, alto], avance=lambda _: None)
    for i in range(3):
        celda = Polygon([(xs[i], y0), (xs[i + 1], y0), (xs[i + 1], y1), (xs[i], y1)])
        assert iou(r.lotes[str(i + 1)], celda) > 0.9


def test_un_lote_chico_aislado_no_se_borra_como_texto_del_rotulo():
    # Un enclave de 14 mm dibujado suelto dentro de otro lote: cabe entero en el cuadrado
    # de ±ROTULO_MM de su rótulo, pero lo encierra, así que es deslinde y no texto.
    px = lambda v: int(round(v * PPMM))
    img = np.full((px(80), px(100), 3), 245, np.uint8)
    cv2.rectangle(img, (px(10), px(10)), (px(90), px(70)), ROJO, 2)
    a, b, c, d = px(43), px(57), px(33), px(47)
    cv2.rectangle(img, (a, c), (b, d), ROJO, 2)
    cv2.putText(img, "7", (px(50) - 5, px(40) + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, NEGRO, 2)
    semillas = [("1", px(20), px(20)), ("7", px(50), px(40))]
    r = digitalizar_imagen(img, PPMM, semillas, [0, 0, img.shape[1], img.shape[0]], avance=lambda _: None)
    assert iou(r.lotes["7"], Polygon([(a, c), (b, c), (b, d), (a, d)])) > 0.95


def test_un_escaneo_muy_fino_se_digitaliza_reducido_y_vuelve_en_px_de_pagina():
    # El mismo plano escaneado al doble (12 px/mm > PPMM_TRABAJO_MAXIMO): se trabaja
    # reducido, pero los lotes vuelven en px de la página de 12 px/mm.
    plano = dibujar()
    base = _digitalizar(plano)
    grande = cv2.resize(plano.imagen, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    alto, ancho = grande.shape[:2]
    semillas = [(n, 2 * x + 0.5, 2 * y + 0.5) for n, x, y in plano.semillas]
    r = digitalizar_imagen(grande, 2 * PPMM, semillas, [0, 0, ancho, alto], avance=lambda _: None)
    assert r.encuadre.ppmm == pytest.approx(8.0)
    assert set(r.lotes) == set(base.lotes)
    for n, p in r.lotes.items():
        # Centro de píxel: x_grande = 2·x + 0,5.
        de_vuelta = shapely_affinity.affine_transform(p, [0.5, 0, 0, 0.5, -0.25, -0.25])
        assert iou(de_vuelta, base.lotes[n]) > 0.95, n
        # Igual de cerca del lote ideal que sin reducir: no hay corrimiento de coordenadas.
        assert iou(de_vuelta, plano.celdas[n]) > iou(base.lotes[n], plano.celdas[n]) - 0.01, n


def test_semillas_repetidas():
    plano = dibujar()
    t = mascara(plano.imagen, PPMM)
    with pytest.raises(ValueError, match="repetidos"):
        particion.particionar(t, PPMM, [("1", 300, 300), ("1", 600, 300)])


def test_sin_semilla_el_lote_queda_sin_numero():
    plano = dibujar()
    semillas = [s for s in plano.semillas if s[0] != "10"]
    alto, ancho = plano.imagen.shape[:2]
    r = digitalizar_imagen(plano.imagen, PPMM, semillas, [0, 0, ancho, alto], avance=lambda _: None)
    assert "10" not in r.lotes and len(r.lotes) == len(semillas)
    assert any(iou(c, plano.celdas["10"]) > 0.9 for c in r.sin_numero)
    _revisar_topologia(r.lotes, r.sin_numero, plano.contorno)


def test_foto_en_perspectiva_rectificada_por_el_marco():
    plano = dibujar()
    alto, ancho = plano.imagen.shape[:2]
    # El marco impreso es el borde de la hoja sintética; la foto la inclina.
    marco = np.float32([[0, 0], [ancho, 0], [ancho, alto], [0, alto]])
    foto_marco = np.float32([[80, 60], [ancho + 40, 120], [ancho + 10, alto + 150], [50, alto + 90]])
    hoja = plano.imagen.copy()
    # Un pliegue del papel: pálido, recto, de lado a lado de la hoja.
    cv2.line(hoja, (ancho // 2 - 150, 0), (ancho // 2 - 150, alto - 1), (200, 198, 192), 3)
    H = cv2.getPerspectiveTransform(marco, foto_marco)
    foto = cv2.warpPerspective(hoja, H, (ancho + 140, alto + 240), flags=cv2.INTER_CUBIC,
                               borderValue=(120, 110, 100))
    a_foto = lambda pts: cv2.perspectiveTransform(np.float32(pts).reshape(-1, 1, 2), H).reshape(-1, 2)
    semillas = [(n, *a_foto([[x, y]])[0]) for n, x, y in plano.semillas]
    rect = [*foto_marco.min(0), *foto_marco.max(0)]

    r = digitalizar_imagen(foto, 1.5, semillas, rect, esquinas=foto_marco.tolist(),
                           marco_mm=[ancho / PPMM, alto / PPMM], avance=lambda _: None)

    assert r.encuadre.modo == "perspectiva"
    assert r.estadisticas["particion"]["tramos_pliegue"] >= 1
    assert len(r.lotes) == len(plano.semillas)
    for numero, celda in plano.celdas.items():
        ideal = Polygon(a_foto(np.asarray(celda.exterior.coords)))
        assert iou(r.lotes[numero], ideal) > 0.95
    # En la imagen de trabajo la geometría es la del papel: los lotes vuelven a ser
    # rectángulos de 50 × 35 mm.
    for numero, p in r.lotes_trabajo.items():
        if numero in ("1", "4", "9", "12"):
            x0, y0, x1, y1 = p.bounds
            assert (x1 - x0) / PPMM == pytest.approx(50, abs=1.0)
            assert (y1 - y0) / PPMM == pytest.approx(35, abs=1.0)
            assert p.area / ((x1 - x0) * (y1 - y0)) > 0.98


def test_inundar_solo_desde_el_borde_de_las_marcas_da_el_mismo_watershed():
    from skimage.segmentation import watershed
    plano = dibujar()
    t = mascara(plano.imagen, PPMM)
    # Un relieve sin empates: con empates el orden de la cola de skimage es arbitrario.
    ruido = np.random.default_rng(3).random(t.lineas.shape, np.float32) * 1e-3
    relieve = cv2.GaussianBlur(t.lineas.astype(np.float32), (0, 0), 1.5) + ruido
    # Marcas grandes (como los núcleos): todo menos una franja alrededor de las líneas.
    fondo = (cv2.dilate(t.lineas.astype(np.uint8), np.ones((15, 15), np.uint8)) == 0).astype(np.uint8)
    _, marcas = cv2.connectedComponents(fondo, connectivity=4)
    marcas = marcas.astype(np.int32)
    assert (marcas > 0).mean() > 0.5

    nuevo = particion._inundar(relieve, marcas)

    assert nuevo.dtype == np.int32
    assert np.array_equal(nuevo, watershed(relieve, marcas))


def _grilla_tenue(sin_semilla=("2", "6", "7"), franja=True):
    """4 × 2 lotes de 30 × 40 mm con el borde negro y las divisorias en gris claro
    (tinta que no es "firme", como en Caminos de Rapel): un lote sin semilla se uniría
    a su vecino sin aviso. En el lote 1, una franja de 7 mm cerrada por otra línea gris
    (un bolsillo que sí se une)."""
    px = lambda v: int(round(v * PPMM))
    m, w, h = 20.0, 30.0, 40.0
    img = np.full((px(2 * m + 2 * h), px(2 * m + 4 * w), 3), (244, 241, 233), np.uint8)
    gris = (165, 165, 165)
    xs = [px(m + i * w) for i in range(5)]
    ys = [px(m + j * h) for j in range(3)]
    for x in xs[1:-1]:
        cv2.line(img, (x, ys[0]), (x, ys[-1]), gris, 2)
    cv2.line(img, (xs[0], ys[1]), (xs[-1], ys[1]), gris, 2)
    if franja:
        cv2.line(img, (xs[0], px(m + 7)), (xs[1], px(m + 7)), gris, 2)
    cv2.rectangle(img, (xs[0], ys[0]), (xs[-1], ys[-1]), NEGRO, 3)
    celdas, semillas = {}, []
    for j in range(2):
        for i in range(4):
            n = str(j * 4 + i + 1)
            celdas[n] = Polygon([(xs[i], ys[j]), (xs[i + 1], ys[j]), (xs[i + 1], ys[j + 1]), (xs[i], ys[j + 1])])
            if n not in sin_semilla:
                semillas.append((n, (xs[i] + xs[i + 1]) / 2, (ys[j] + ys[j + 1]) / 2 + px(3)))
    return img, semillas, celdas


def test_un_lote_sin_rotulo_no_se_pega_a_su_vecino(monkeypatch):
    img, semillas, celdas = _grilla_tenue()
    alto, ancho = img.shape[:2]
    r = digitalizar_imagen(img, PPMM, semillas, [0, 0, ancho, alto], avance=lambda _: None)

    # Los 3 lotes sin semilla quedan como caras sin número del tamaño de un lote...
    assert len(r.lotes) == 5 and r.estadisticas["sin_numero_lote"] == 3
    de_lote = [c for c, es in zip(r.sin_numero, r.sin_numero_lote) if es]
    for n in ("2", "6", "7"):
        assert sum(iou(c, celdas[n]) > 0.9 for c in de_lote) == 1, n
    # ...y los numerados no crecen.
    for n, p in r.lotes.items():
        assert iou(p, celdas[n]) > 0.9, n
    # La franja de 7 mm del lote 1 sí se une: es un trozo, no un lote.
    assert r.estadisticas["particion"]["fusiones_sin_tinta"]
    assert not any(iou(c, celdas["1"]) > 0.05 for c in r.sin_numero)

    # Lo que pasaba antes: sin el tope, los tres se pegaban a un vecino.
    monkeypatch.setattr(particion, "LOTE_FRAC", 1e9)
    antes = digitalizar_imagen(img, PPMM, semillas, [0, 0, ancho, alto], avance=lambda _: None)
    assert antes.estadisticas["sin_numero_lote"] == 0
    assert len(antes.estadisticas["particion"]["fusiones_sin_tinta"]) >= 4
    assert max(p.area for p in antes.lotes.values()) > 1.8 * celdas["1"].area


def test_un_rotulo_pegado_al_lado_largo_no_une_al_vecino_sin_numero():
    # El rótulo del 1 a 1,5 mm de su deslinde con el 2 (sin semilla): está "sobre el
    # corte", pero el lado común (40 mm) es mucho más largo que el texto. No es el
    # rótulo partiendo su lote: el 2 queda como lote sin número.
    img, semillas, celdas = _grilla_tenue(franja=False)
    x1 = celdas["1"].bounds[2]
    semillas = [(n, x1 - 1.5 * PPMM, y) if n == "1" else (n, x, y) for n, x, y in semillas]
    alto, ancho = img.shape[:2]
    r = digitalizar_imagen(img, PPMM, semillas, [0, 0, ancho, alto], avance=lambda _: None)

    assert r.estadisticas["sin_numero_lote"] == 3
    assert iou(r.lotes["1"], celdas["1"]) > 0.9
    assert sum(iou(c, celdas["2"]) > 0.9 for c, es in zip(r.sin_numero, r.sin_numero_lote) if es) == 1


def test_las_lecturas_con_poco_apoyo_se_sugieren_en_su_lote_sin_numero():
    from pipeline.plano.digitalizar import _sugerencias
    from pipeline.plano.rotulos import Rotulo
    caras = [Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]), Polygon([(10, 0), (20, 0), (20, 10), (10, 10)]),
             Polygon([(20, 0), (30, 0), (30, 10), (20, 10)])]
    de_lote = [True, True, False]
    leidos = [Rotulo("8-03", 5, 5, 0.01, 1), Rotulo("8-3", 6, 6, 0.005, 1),      # el mismo, peor leído
              Rotulo("8-04", 15, 5, 0.3, 3),                                    # con apoyo: era semilla
              Rotulo("8-02", 16, 5, 0.01, 1),                                   # ya es de otro lote
              Rotulo("8-05", 25, 5, 0.01, 1)]                                   # cara que no es lote
    s = _sugerencias(caras, de_lote, leidos, 2, ["8-02"])
    assert s == [dict(numero="8-03", confianza=0.01, apoyo=1), None, None]
    assert _sugerencias(caras, de_lote, [], 2, []) == [None, None, None]


def _lotes_con_texto_en_el_borde():
    """Dos lotes de 50 × 35 mm; sobre el deslinde exterior de arriba, por dentro, un
    texto en negrita pegado a la línea ("Servidumbre de tránsito 10 m", como en Caminos
    de Rapel)."""
    px = lambda v: int(round(v * PPMM))
    img = np.full((px(75), px(140), 3), 245, np.uint8)
    x0, x1, x2, y0, y1 = px(20), px(70), px(120), px(20), px(55)
    cv2.rectangle(img, (x0, y0), (x2, y1), NEGRO, 2)
    cv2.line(img, (x1, y0), (x1, y1), NEGRO, 2)
    for x in (x0 + 4, x1 + 4):
        cv2.putText(img, "SERVIDUMBRE 10M", (x, y0 + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.7, NEGRO, 2)
    semillas = [("1", (x0 + x1) / 2, (y0 + y1) / 2 + 20), ("2", (x1 + x2) / 2, (y0 + y1) / 2 + 20)]
    celdas = {"1": Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]),
              "2": Polygon([(x1, y0), (x2, y0), (x2, y1), (x1, y1)])}
    return img, semillas, celdas


def test_el_texto_pegado_al_deslinde_no_es_relleno():
    img, _, celdas = _lotes_con_texto_en_el_borde()
    t = mascara(img, PPMM)
    x0, y0, x1, _ = celdas["1"].bounds
    assert t.lineas[int(y0) + 4:int(y0) + 14, int(x0) + 10:int(x1) - 10].any()     # el texto es tinta
    assert not t.grueso.any()                                                       # pero no relleno


def test_el_texto_pegado_al_deslinde_no_se_come_el_lote():
    # Como relleno, el texto quedaba fuera del lote (−3 % del área, y 10 caras sin
    # número entre las letras); como tinta, el watershed la reparte y el lote llega a
    # la línea.
    img, semillas, celdas = _lotes_con_texto_en_el_borde()
    alto, ancho = img.shape[:2]
    r = digitalizar_imagen(img, PPMM, semillas, [0, 0, ancho, alto], avance=lambda _: None)
    for n, celda in celdas.items():
        assert r.lotes[n].area / celda.area - 1 > -0.015
        assert iou(r.lotes[n], celda) > 0.98
    assert r.sin_numero == []


def test_el_texto_que_cruza_el_lote_de_deslinde_a_deslinde_no_lo_parte():
    # Un rótulo en negrita que toca los dos deslindes ("TRANSFERIDO" en los lotes 79 y 92
    # de Curicó) encierra un trozo del lote. Como tinta firme, ese trozo quedaba sin
    # número (el 92 perdía un 20 %); es línea pero no firme, y el trozo se une al lote.
    px = lambda v: int(round(v * PPMM))
    img = np.full((px(80), px(110), 3), 245, np.uint8)
    x0, x1, x2, y0, y1 = px(10), px(30), px(100), px(10), px(70)
    cv2.rectangle(img, (x0, y0), (x2, y1), NEGRO, 2)
    cv2.line(img, (x1, y0), (x1, y1), NEGRO, 2)
    yb = y0 + px(28)
    cv2.putText(img, "TRANSFERID", (x0 - 6, yb), cv2.FONT_HERSHEY_SIMPLEX, 0.75, NEGRO, 2)
    for y in (yb + 3, yb - 17):                     # enmarcado: las letras quedan en un bloque
        cv2.line(img, (x0 - 6, y), (x0 + 128, y), NEGRO, 1)
    semillas = [("1", (x0 + x1) / 2, y0 + px(45)), ("2", (x1 + x2) / 2, y0 + px(45))]
    celdas = {"1": Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]),
              "2": Polygon([(x1, y0), (x2, y0), (x2, y1), (x1, y1)])}
    t = mascara(img, PPMM)
    assert t.lineas[yb - 17:yb + 4, x0 + px(3):x1 - px(3)].any(axis=0).all()   # el texto es línea
    assert not t.grueso.any()
    alto, ancho = img.shape[:2]
    r = digitalizar_imagen(img, PPMM, semillas, [0, 0, ancho, alto], avance=lambda _: None)
    assert r.sin_numero == []
    for n, celda in celdas.items():
        assert iou(r.lotes[n], celda) > 0.97


# ---------------------------------------------------------------- enderezado de los deslindes
def _linea_temblorosa(img, p, q, rng, temblor_px=1, grosor=2):
    """Una línea escaneada: el eje tiembla ±temblor_px cada ~1 mm."""
    n = max(2, int(math.hypot(q[0] - p[0], q[1] - p[1]) / PPMM))
    t = np.linspace(0, 1, n + 1)
    normal = np.array((-(q[1] - p[1]), q[0] - p[0])) / math.hypot(q[0] - p[0], q[1] - p[1])
    puntos = np.outer(1 - t, p) + np.outer(t, q)
    puntos[1:-1] += np.outer(rng.integers(-temblor_px, temblor_px + 1, n - 1), normal)
    cv2.polylines(img, [puntos.round().astype(np.int32)], False, NEGRO, grosor)


@pytest.mark.parametrize("escala", [1.0, 4 / 3])
def test_un_deslinde_recto_con_texto_y_achurado_pegados_sale_recto(escala):
    # Caminos de Rapel: el borde exterior junto al camino trae "Servidumbre de tránsito"
    # pegado, achurado y el temblor del escaneo; salía ondulado. Recto en el dibujo,
    # recto en el polígono: 4 vértices por lote más el nodo del deslinde común.
    px = lambda v: int(round(v * PPMM))
    rng = np.random.default_rng(3)
    img = np.full((px(80), px(150), 3), 245, np.uint8)
    x0, x1, x2, y0, y1 = px(20), px(75), px(130), px(20), px(60)
    for p, q in (((x0, y0), (x2, y0)), ((x2, y0), (x2, y1)), ((x2, y1), (x0, y1)), ((x0, y1), (x0, y0)),
                 ((x1, y0), (x1, y1))):
        _linea_temblorosa(img, p, q, rng)
    # Texto en negrita pegado por dentro al borde de abajo, en los dos lotes.
    for x in (x0 + px(3), x1 + px(3)):
        cv2.putText(img, "SERVIDUMBRE 8M", (x, y1 - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.75, NEGRO, 2)
    # Texto vertical pegado por dentro al borde izquierdo.
    texto = np.full((px(6), px(32), 3), 245, np.uint8)
    cv2.putText(texto, "CAMINO 10M", (2, px(6) - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.75, NEGRO, 2)
    img[y0 + px(4):y0 + px(4) + px(32), x0 + 1:x0 + 1 + px(6)] = np.rot90(texto)
    # Achurado (manchas) pegado por fuera al borde de arriba.
    for x in range(x0 + px(5), x2 - px(5), px(4)):
        cv2.circle(img, (x, y0 - 4), 4, NEGRO, -1)
    semillas = [("1", (x0 + x1) / 2, (y0 + y1) / 2 - px(5)), ("2", (x1 + x2) / 2, (y0 + y1) / 2 - px(5))]
    celdas = {"1": Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]),
              "2": Polygon([(x1, y0), (x2, y0), (x2, y1), (x1, y1)])}
    if escala != 1:
        # El mismo plano a 8 px/mm: los umbrales van en mm de papel, no en píxeles.
        img = cv2.resize(img, None, fx=escala, fy=escala, interpolation=cv2.INTER_LINEAR)
        semillas = [(n, x * escala, y * escala) for n, x, y in semillas]
        celdas = {n: Polygon(np.asarray(c.exterior.coords) * escala) for n, c in celdas.items()}
    alto, ancho = img.shape[:2]
    r = digitalizar_imagen(img, PPMM * escala, semillas, [0, 0, ancho, alto], avance=lambda _: None)
    for n, celda in celdas.items():
        lote = r.lotes[n]
        # 4 esquinas y el nodo del deslinde común (arriba y abajo): cada lado, una recta.
        assert len(lote.exterior.coords) - 1 <= 6, (n, list(lote.exterior.coords))
        assert iou(lote, celda) > 0.98
        # Ningún vértice del lote se aparta del rectángulo del dibujo más de 0,4 mm.
        assert max(celda.exterior.distance(Point(c)) for c in lote.exterior.coords) < 0.4 * PPMM * escala
    assert r.estadisticas["red"]["aristas_robustas"] >= 1


def _cadena_y_tinta(puntos, ancho=200, alto=200):
    """Una cadena de grietas (escalera de píxeles) que sigue `puntos` y la tinta de la
    línea dibujada por `puntos`."""
    tinta = np.zeros((alto, ancho), np.uint8)
    cv2.polylines(tinta, [np.asarray(puntos).round().astype(np.int32)], False, 1, 2)
    densa = []
    for p, q in zip(puntos[:-1], puntos[1:]):
        n = int(max(abs(q[0] - p[0]), abs(q[1] - p[1]))) + 1
        densa += [tuple(v) for v in np.linspace(p, q, n, endpoint=False).round()]
    densa.append(tuple(np.round(puntos[-1])))
    cadena = [densa[0]]
    for x, y in densa[1:]:
        while cadena[-1] != (x, y):         # pasos de a un eje, como las grietas
            cx, cy = cadena[-1]
            cadena.append((cx + np.sign(x - cx), cy) if cx != x else (cx, cy + np.sign(y - cy)))
    return np.array(cadena, float), tinta.astype(bool)


def test_una_esquina_en_l_son_dos_tramos():
    P, lineas = _cadena_y_tinta([(20, 30), (20, 160), (170, 160)])
    tinta = particion._tinta_cercana(lineas, PPMM)
    rs, idx = particion._poligonal(P, tinta, PPMM)
    assert len(rs) == 2
    V = particion._vertices(P, idx, rs, 10 * PPMM)
    assert len(V) == 3
    assert np.hypot(*(V[1] - (20, 160))) < 1.0


def test_una_recta_con_un_bulto_de_texto_es_un_tramo():
    # La cadena rodea un bloque de texto pegado a la línea (2 mm de alto); la tinta de
    # la línea sigue debajo del texto.
    P, _ = _cadena_y_tinta([(10, 100), (70, 100), (70, 88), (110, 88), (110, 100), (190, 100)])
    lineas = np.zeros((200, 200), bool)
    lineas[99:101, 10:191] = True
    lineas[88:100, 70:111] = True                    # el texto también es tinta
    rs, idx = particion._poligonal(P, particion._tinta_cercana(lineas, PPMM), PPMM)
    assert len(rs) == 1 and idx == [0, len(P) - 1]
    (m, u), = rs
    assert abs(((10, 100) - m) @ (-u[1], u[0])) < 0.5 and abs(u[1]) < 0.01


def test_un_estero_curvo_sigue_curvo_pero_simplificado():
    # Un estero: la línea del dibujo es curva. Ni una recta ni pocos tramos van por la
    # tinta: queda a Douglas-Peucker, con más vértices que una poligonal de 4 tramos y
    # muchos menos que la escalera de píxeles.
    t = np.linspace(0, np.pi, 60)
    puntos = np.c_[20 + 160 * t / np.pi, 100 + 40 * np.sin(t) + 8 * np.sin(5 * t)]
    P, lineas = _cadena_y_tinta(puntos)
    assert particion._poligonal(P, particion._tinta_cercana(lineas, PPMM), PPMM) is None
    idx = particion._douglas_peucker(P, particion.DP_MM * PPMM)
    assert particion.TRAMOS_MAX + 1 < len(idx) < len(P) / 5


def test_una_astilla_suelta_de_un_lote_pasa_al_vecino_y_no_deja_hueco():
    # Dos aristas que se cruzan cerca de un nodo movido dejan una astilla de la región
    # del lote "1" separada de él, pegada al "2". Botarla dejaba un hueco en el KMZ.
    uno = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    dos = Polygon([(10, 0), (20, 0), (20, 10), (11, 10), (10, 9)])
    astilla = Polygon([(10, 9), (11, 10), (10, 10)])  # 0,5: más borde con el "2"
    lejana = Polygon([(50, 50), (50.2, 50), (50, 50.2)])
    lotes = particion._repartir_restos({"1": uno, "2": dos}, [astilla, lejana], 1.0)
    assert lotes["2"].geom_type == "Polygon" and lotes["1"].equals(uno)
    assert lotes["2"].area == pytest.approx(dos.area + astilla.area)
    assert unary_union(list(lotes.values())).area == pytest.approx(200)
    # Una grande no se reparte.
    grande = Polygon([(-2, 0), (0, 0), (0, 2), (-2, 2)])
    assert particion._repartir_restos({"1": uno}, [grande], 1.0)["1"].equals(uno)
