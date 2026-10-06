import cv2
import numpy as np
import pytest
from shapely import affinity as shapely_affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from pipeline.plano import particion
from pipeline.plano.digitalizar import digitalizar_imagen
from pipeline.plano.tinta import mascara
from pipeline.tests.plano_sintetico import NEGRO, PPMM, ROJO, dibujar, dibujar_girado, iou

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


def test_con_cuadro_la_sugerencia_se_corrige_o_no_se_ofrece():
    """Caminos de Rapel: en 8-09 el lector leía "6-48" o "6-09". Con el cuadro, "6-09" se
    sugiere como 8-09 y "6-48" (más que todo el cuadro) no se sugiere."""
    from pipeline.plano.digitalizar import _sugerencias
    from pipeline.plano.rotulos import Rotulo
    caras = [Polygon([(0, 0), (10, 0), (10, 10), (0, 10)]), Polygon([(10, 0), (20, 0), (20, 10), (10, 10)])]
    cuadro = {"8-08": 5000.0, "8-09": 5000.0, "8-10": 5000.0}
    leidos = [Rotulo("6-09", 5, 5, 0.04, 1), Rotulo("6-48", 15, 5, 0.04, 1)]
    s = _sugerencias(caras, [True, True], leidos, 2, ["8-08"], cuadro)
    assert s == [dict(numero="8-09", confianza=0.04, apoyo=1), None]
    assert _sugerencias(caras, [True, True], leidos, 2, ["8-08"])[1]["numero"] == "6-48"


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


def _quiebres(lotes, celdas) -> float:
    """El mayor giro (grados) de un lote en un vértice que no es esquina de su celda
    ideal: lo que en el KMZ se ve como una línea quebrada."""
    peor = 0.0
    for n, celda in celdas.items():
        cs = np.asarray(lotes[n].exterior.coords)[:-1]
        esquinas = np.asarray(celda.exterior.coords)[:-1]
        for i, b in enumerate(cs):
            if np.hypot(*(esquinas - b).T).min() < PPMM:
                continue
            u, v = b - cs[i - 1], cs[(i + 1) % len(cs)] - b
            giro = np.degrees(np.arctan2(u[0] * v[1] - u[1] * v[0], u @ v))
            peor = max(peor, abs(giro))
    return peor


@pytest.mark.parametrize("texto", [False, True], ids=["limpio", "texto_pegado"])
def test_los_deslindes_de_un_loteo_girado_salen_rectos(texto):
    # Caminos de Rapel: el loteo va girado, las divisorias llegan en T al deslinde del
    # medio y el borde norte tiene texto en negrita pegado a la línea. El borde salía en
    # dientes a lo largo del texto (hasta 2,6 mm del deslinde y giros de 135°).
    plano = dibujar_girado(texto=texto)
    r = _digitalizar(plano)
    assert set(r.lotes) == set(plano.celdas)
    for n, celda in plano.celdas.items():
        assert r.lotes[n].hausdorff_distance(celda) < 0.3 * PPMM, n
        assert len(r.lotes[n].exterior.coords) - 1 <= 6, n
    assert _quiebres(r.lotes, plano.celdas) < 1.0
    _revisar_topologia(r.lotes, r.sin_numero, plano.contorno)


def _zigzag(P, desde, hasta, alto_px, paso_px):
    """Dientes de `alto_px` sobre el tramo horizontal de P entre `desde` y `hasta` (x)."""
    P = P.copy()
    dentro = (P[:, 0] > desde) & (P[:, 0] < hasta)
    P[dentro, 1] += np.where((P[dentro, 0] // paso_px) % 2 == 0, alto_px, 0)
    return P


def _tramos(segs):
    return [(s, e) for s, e, *_ in segs]


def test_enderezar_reemplaza_los_dientes_entre_dos_tramos_de_la_misma_recta():
    tol = particion.DP_MM * PPMM
    P = np.array([(x, 100.0) for x in range(0, 600)])
    P = _zigzag(P, 200, 400, 2.0 * PPMM, 25)
    segs, _ = particion._enderezar(P, tol, PPMM)
    assert _tramos(segs) == [(0, len(P) - 1)]
    assert segs[0][3]                               # enderezado
    p, u = segs[0][2]
    assert abs(p[1] - 100) < 0.5 and abs(u[1]) < 1e-3


def test_enderezar_une_por_una_recta_dos_tramos_casi_paralelos_con_dientes_entre_medio():
    # Caminos de Rapel, borde norte de 8-04: el deslinde se corre 1,5 mm bajo el texto y
    # cambia unos grados de rumbo; entre los dos tramos quedaban dientes de hasta 2 mm.
    tol = particion.DP_MM * PPMM
    a = [(x, 100.0) for x in range(0, 200)]
    b = [(x, 100.0 + 1.5 * PPMM + (x - 300) * np.tan(np.radians(3))) for x in range(300, 600)]
    medio = _zigzag(np.array([(x, 100.0 + 0.75 * PPMM) for x in range(200, 300)]), 199, 300, 1.2 * PPMM, 12)
    P = np.array(a + [tuple(q) for q in medio] + b)
    segs, _ = particion._enderezar(P, tol, PPMM)
    assert _tramos(segs) == [(0, 199), (199, 300), (300, len(P) - 1)]
    assert segs[1][3]                               # el puente, enderezado
    assert not segs[0][3] and not segs[2][3]


def test_enderezar_respeta_un_escalon_y_una_esquina_de_verdad():
    tol = particion.DP_MM * PPMM
    # Un entrante de 4 × 8 mm entre dos tramos de la misma recta: es corto para lo que
    # se aparta (la mitad de su largo), así que es del dibujo.
    x0, x1, y0, h = 200, 200 + int(8 * PPMM), 100, int(4 * PPMM)
    P = np.array([(x, y0) for x in range(0, x0)] + [(x0, y) for y in range(y0, y0 + h)]
                 + [(x, y0 + h) for x in range(x0, x1)] + [(x1, y) for y in range(y0 + h, y0, -1)]
                 + [(x, y0) for x in range(x1, 600)], float)
    segs, _ = particion._enderezar(P, tol, PPMM)
    assert len(segs) == 5 and not any(t[3] for t in segs)
    # Un ochavo de 6 mm en una esquina en ángulo recto.
    c = int(6 * PPMM / np.sqrt(2))
    P = np.array([(x, 0) for x in range(0, 300 - c)] + [(300 - c + k, k) for k in range(c)]
                 + [(300, y) for y in range(c, 300)], float)
    segs, _ = particion._enderezar(P, tol, PPMM)
    assert len(segs) == 3 and not any(t[3] for t in segs)


def test_enderezar_respeta_un_lado_corto_en_la_punta_y_las_curvas():
    tol = particion.DP_MM * PPMM
    # Una esquina de verdad a 5 mm del nodo donde termina la línea.
    P = np.array([(x, 0) for x in range(301)] + [(300, y) for y in range(1, 31)], float)
    segs, _ = particion._enderezar(P, tol, PPMM)
    assert _tramos(segs) == [(0, 300), (300, 330)] and not any(t[3] for t in segs)
    # Una curva (una calle en arco, un retorno) no se toma por dientes ni se simplifica
    # más que Douglas-Peucker; y cadenas largas no se demoran.
    import time
    for radio in (500, 2000):
        t = np.linspace(0, np.pi, int(np.pi * radio))
        P = np.c_[radio * np.cos(t), radio * np.sin(t)]
        inicio = time.time()
        segs, fijos = particion._enderezar(P, tol, PPMM)
        assert time.time() - inicio < 2
        assert not any(s[3] for s in segs)
        vertices = [P[0]] + [P[s] for s, *_ in segs[1:]] + [P[-1]]
        assert max(abs(np.hypot(*v) - radio) for v in vertices) < 2 * tol


def test_enderezar_no_mueve_las_puntas_al_nodo_de_una_arista_corta():
    # Planos CBR Constitución: una cadena que empieza con una arista de pocos píxeles
    # (el nodo queda a 6 px de la punta). La punta saltaba al nodo, esa arista quedaba
    # sin tramos y la red de deslindes caía con "list index out of range".
    tol = particion.DP_MM * PPMM
    P = np.array([(x, 100.0) for x in range(0, 100)])
    for uniones in ([6], [93], [6, 93]):
        segs, _ = particion._enderezar(P, tol, PPMM, uniones)
        assert segs[0][0] == 0 and segs[-1][1] == len(P) - 1


def _loteo_con_borde(borde):
    """Dos lotes (1, 2) con el borde sur exterior en `borde(x0, x1, y)` (los vértices de
    entre medio, de izquierda a derecha), dos lotes al norte (3, 4) y el resto de la
    propiedad al oriente, que comparte el lado este de 2 y 4. La divisoria 1/2 llega al
    borde en (300, `t`): el texto puede dejar ese nodo dentro de un diente."""
    def caras(t=200.0):
        sur1 = [(x, y) for x, y in borde(0, 300, 200.0)][::-1]
        sur2 = [(x, y) for x, y in borde(300, 600, 200.0)][::-1]
        return {
            "1": Polygon([(0, 0), (300, 0), (300, t), *sur1, (0, 200)]),
            "2": Polygon([(300, 0), (600, 0), (600, 200), *sur2, (300, t)]),
            "3": Polygon([(0, -200), (300, -200), (300, 0), (0, 0)]),
            "4": Polygon([(300, -200), (600, -200), (600, 0), (300, 0)]),
            "resto": Polygon([(600, -200), (900, -200), (900, 200), (600, 200), (600, 0)]),
        }
    return caras


def _dientes(alto_px):
    # Las letras pegadas al borde: el trazado sube y baja cada 20 px.
    return lambda x0, x1, y: [(x, y - alto_px if (x // 20) % 2 else y + 0.3 * alto_px)
                              for x in range(x0 + 20, x1, 20)]


def _enderezar_borde(caras):
    nombres = list(caras)
    salida, n = particion.enderezar_borde_exterior([caras[k] for k in nombres], PPMM)
    return dict(zip(nombres, salida)), n


def test_el_borde_exterior_en_dientes_por_un_rotulo_sale_recto():
    # Caminos de Rapel: "Servidumbre de Tránsito 8m" pegado al deslinde poniente de 8-01
    # y 8-10; el borde seguía las letras, y el nodo de su divisoria quedaba en un diente.
    caras = _loteo_con_borde(_dientes(1.5 * PPMM))(t=200 - 1.4 * PPMM)
    salida, n = _enderezar_borde(caras)
    assert n == 2
    for numero, celda in (("1", box(0, 0, 300, 200)), ("2", box(300, 0, 600, 200))):
        assert salida[numero].hausdorff_distance(celda) < 0.5, numero
        assert len(salida[numero].exterior.coords) - 1 == 4, numero
    # Los lados compartidos no se mueven: los vecinos quedan iguales.
    for numero in ("3", "4", "resto"):
        assert salida[numero].equals_exact(caras[numero], 1e-9), numero
    # Sin huecos ni traslapes: los lotes siguen cubriendo la red completa.
    todo = unary_union(list(salida.values()))
    assert sum(g.area for g in salida.values()) - todo.area < EPSILON_PX2
    assert todo.geom_type == "Polygon" and not list(todo.interiors)
    assert salida["1"].intersection(salida["2"]).length > 199


def test_el_borde_exterior_curvo_o_con_un_entrante_de_verdad_no_se_endereza():
    # Una curva de 4 mm de flecha (una calle en arco): gira siempre al mismo lado.
    arco = lambda x0, x1, y: [(x, y + 4 * PPMM * np.sin(np.pi * (x - x0) / (x1 - x0)))
                              for x in range(x0 + 10, x1, 10)]
    # Una curva suave (1 mm) tampoco: no zigzaguea.
    suave = lambda x0, x1, y: [(x, y + PPMM * np.sin(np.pi * (x - x0) / (x1 - x0)))
                               for x in range(x0 + 10, x1, 10)]
    # Dientes de 4 mm: más de BORDE_MM, son del dibujo.
    for borde in (arco, suave, _dientes(4 * PPMM)):
        caras = _loteo_con_borde(borde)()
        salida, n = _enderezar_borde(caras)
        assert n == 0
        for numero in caras:
            assert salida[numero].equals_exact(caras[numero], 1e-9), numero


def test_el_borde_compartido_con_el_resto_de_la_propiedad_no_se_toca():
    # Los dientes en el lado que el lote 2 comparte con el resto: no es borde exterior.
    caras = _loteo_con_borde(lambda x0, x1, y: [])()
    este = [(600 + (9 if (y // 20) % 2 else 0), y) for y in range(20, 200, 20)]
    caras["2"] = Polygon([(300, 0), (600, 0), *este, (600, 200), (300, 200)])
    caras["resto"] = Polygon([(600, -200), (900, -200), (900, 200), (600, 200), *este[::-1], (600, 0)])
    salida, n = _enderezar_borde(caras)
    assert n == 0
    for numero in caras:
        assert salida[numero].equals_exact(caras[numero], 1e-9), numero
