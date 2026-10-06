import cv2
import numpy as np
import pymupdf
import pytest

from pipeline.plano import pagina as pg
from pipeline.plano import union as un

PAPEL = (244, 241, 233)
TINTA = (35, 35, 40)
ANCHO, ALTO = 1500, 1000
MARGEN = 100          # papel alrededor de cada franja en su hoja, con "viñeta" incluida


def _original() -> np.ndarray:
    img = np.full((ALTO, ANCHO, 3), PAPEL, np.uint8)
    for x in range(40, ANCHO, 110):
        cv2.line(img, (x, 20), (x + 30, ALTO - 20), TINTA, 3)
    for y in range(35, ALTO, 90):
        cv2.line(img, (15, y), (ANCHO - 15, y + 12), TINTA, 2)
    for i in range(12):
        x, y = 60 + i * 117, 80 + (i * 211) % 760
        cv2.rectangle(img, (x, y), (x + 70, y + 45), (205, 45, 50), 4)
    return img


def _hoja(original, a, b, angulo, rotacion):
    """La franja x∈[a, b) del original como la traería el PDF: con papel y una viñeta
    alrededor, girada `angulo` fino y guardada girada −`rotacion` en la fuente. Devuelve
    la imagen de la fuente y la hoja de la unión que la vuelve a su lugar."""
    w, h = b - a + 2 * MARGEN, ALTO + 2 * MARGEN
    x = a - MARGEN + (w - 1) / 2
    y = -MARGEN + (h - 1) / 2
    m = un._matriz(w, h, 1.0, angulo, x, y)
    girada = cv2.warpAffine(original, m[:2], (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=PAPEL)
    # La viñeta y los timbres: fuera del recorte, no deben entrar a la unión.
    girada[:MARGEN - 30, :] = TINTA
    girada[:, w - MARGEN + 30:] = (30, 90, 200)
    fuente = pg.rotar(girada, (360 - rotacion) % 360)
    recorte = [MARGEN, MARGEN, w - MARGEN, h - MARGEN]
    return fuente, {"rotacion": rotacion, "angulo": angulo, "x": x, "y": y, "recorte": recorte}


def _partido():
    original = _original()
    fuentes, hojas = {}, []
    for n, (a, b, angulo, rotacion) in enumerate([(0, 650, 0.8, 90), (450, 1100, -1.2, 270),
                                                  (900, ANCHO, 0.3, 0)], start=1):
        fuente, hoja = _hoja(original, a, b, angulo, rotacion)
        fuentes[n] = fuente
        hojas.append({"n": n, **hoja})
    return original, fuentes, hojas


def _geometria(union, fuentes, ppmm=6.0):
    tamanos = {n: (f.shape[1], f.shape[0]) for n, f in fuentes.items()}
    return un.geometria(union, tamanos, {n: ppmm for n in fuentes})


def _en_original(lienzo, geo, x0, y0, x1, y1):
    ox, oy = geo.origen
    return lienzo[y0 - oy:y1 - oy, x0 - ox:x1 - ox].astype(float)


def test_la_union_recompone_el_plano_partido_en_hojas_giradas():
    original, fuentes, hojas = _partido()
    union = un.leer({"hojas": hojas})
    geo = _geometria(union, fuentes)
    imagenes = {h.n: pg.rotar(fuentes[h.n], h.rotacion) for h in union.hojas}
    lienzo = un.componer(imagenes, geo)
    zona = (40, 40, ANCHO - 40, ALTO - 40)
    diferencia = np.abs(_en_original(lienzo, geo, *zona) - original[40:-40, 40:-40]).mean()
    assert diferencia < 4, diferencia
    # Sin la viñeta: lo de fuera del recorte no entra (ese azul solo está en ella).
    assert not np.all(lienzo == (30, 90, 200), axis=2).any()
    # Corrida 4 px, la diferencia salta: la prueba sí mira el calce.
    corrida = un.leer({"hojas": [{**h, "x": h["x"] + 4} if h["n"] == 2 else h for h in hojas]})
    geo2 = _geometria(corrida, fuentes)
    lienzo2 = un.componer(imagenes, geo2)
    peor = np.abs(_en_original(lienzo2, geo2, *zona) - original[40:-40, 40:-40]).mean()
    assert peor > 2 * diferencia


def test_sin_giro_y_en_su_lugar_es_identica():
    original = _original()
    hojas = [{"n": 1, "x": (ANCHO - 1) / 2, "y": (ALTO - 1) / 2, "recorte": [0, 0, 800, ALTO]},
             {"n": 2, "x": (ANCHO - 1) / 2, "y": (ALTO - 1) / 2, "recorte": [700, 0, ANCHO, ALTO]}]
    geo = un.geometria(un.leer({"hojas": hojas}), {1: (ANCHO, ALTO), 2: (ANCHO, ALTO)}, {1: 6.0, 2: 6.0})
    assert (geo.ancho, geo.alto, geo.origen) == (ANCHO, ALTO, (0, 0))
    lienzo = un.componer({1: original, 2: original}, geo)
    assert np.array_equal(lienzo, original)


def _lisa(color, ancho=400, alto=300):
    return np.full((alto, ancho, 3), color, np.uint8)


def test_la_de_arriba_manda_en_el_traslape():
    rojo, azul = (200, 30, 30), (30, 30, 200)
    hojas = [{"n": 1, "x": 199.5, "y": 149.5}, {"n": 2, "x": 399.5, "y": 149.5}]
    tamanos, ppmms = {1: (400, 300), 2: (400, 300)}, {1: 6.0, 2: 6.0}
    geo = un.geometria(un.leer({"hojas": hojas}), tamanos, ppmms)
    assert (geo.ancho, geo.alto) == (600, 300)
    lienzo = un.componer({1: _lisa(rojo), 2: _lisa(azul)}, geo, papel=PAPEL)
    assert tuple(lienzo[150, 300]) == azul
    assert tuple(lienzo[150, 100]) == rojo
    al_reves = un.geometria(un.leer({"hojas": hojas[::-1]}), tamanos, ppmms)
    lienzo = un.componer({1: _lisa(rojo), 2: _lisa(azul)}, al_reves, papel=PAPEL)
    assert tuple(lienzo[150, 300]) == rojo


def test_fuera_del_recorte_no_pinta():
    rojo, azul = (200, 30, 30), (30, 30, 200)
    hojas = [{"n": 1, "x": 199.5, "y": 149.5},
             {"n": 2, "x": 199.5, "y": 149.5, "recorte": [100, 50, 200, 150]}]
    geo = un.geometria(un.leer({"hojas": hojas}), {1: (400, 300), 2: (400, 300)}, {1: 6.0, 2: 6.0})
    lienzo = un.componer({1: _lisa(rojo), 2: _lisa(azul)}, geo, papel=PAPEL)
    assert (lienzo[50:150, 100:200] == azul).all()
    rojos = np.all(lienzo == rojo, axis=2)
    assert rojos.sum() == 400 * 300 - 100 * 100
    # Una hoja recortada sola deja papel donde no hay nada.
    solo = un.geometria(un.leer({"hojas": [{"n": 1, "x": 0, "y": 0, "recorte": [0, 0, 50, 50]},
                                           {"n": 2, "x": 0, "y": 0, "recorte": [350, 250, 400, 300]}]}),
                        {1: (400, 300), 2: (400, 300)}, {1: 6.0, 2: 6.0})
    lienzo = un.componer({1: _lisa(rojo), 2: _lisa(azul)}, solo, papel=PAPEL)
    assert (solo.ancho, solo.alto, solo.origen) == (401, 301, (-200, -150))
    assert tuple(lienzo[200, 200]) == PAPEL and tuple(lienzo[10, 10]) == rojo and tuple(lienzo[275, 375]) == azul


def test_escala_a_la_resolucion_mayor_con_tope():
    hojas = [{"n": 1, "x": 0, "y": 0}, {"n": 2, "x": 500, "y": 0}]
    geo = un.geometria(un.leer({"hojas": hojas}), {1: (101, 101), 2: (101, 101)}, {1: 4.0, 2: 6.0})
    assert geo.ppmm == 6.0 and geo.hoja(1).k == 1.5 and geo.hoja(2).k == 1.0
    assert np.allclose(geo.a_hoja(1, geo.a_union(1, [[3, 7]])), [[3, 7]])
    fina = un.geometria(un.leer({"hojas": hojas}), {1: (101, 101), 2: (101, 101)}, {1: 12.0, 2: 6.0})
    assert fina.ppmm == pg.PPMM_TRABAJO_MAXIMO


def test_resoluciones_casi_iguales_son_la_misma():
    # Dos hojas del mismo escaneo: el PDF redondea y sus ppmm difieren en ~1e-8.
    ancho, alto = 9000, 6000
    hojas = [{"n": 1, "x": (ancho - 1) / 2, "y": (alto - 1) / 2}, {"n": 2, "x": 12000.5, "y": 2999.5}]
    tamanos = {1: (ancho, alto), 2: (ancho, alto)}
    geo = un.geometria(un.leer({"hojas": hojas}), tamanos, {1: 6.00000017, 2: 6.00000022})
    assert geo.hoja(1).k == 1.0 and geo.hoja(2).k == 1.0
    # Sin el redondeo de k, la esquina de la hoja 1 caía a 1e-5 px de −0 y el origen era −1.
    assert geo.origen == (0, 0) and geo.alto == alto
    distintas = un.geometria(un.leer({"hojas": hojas}), tamanos, {1: 6.0, 2: 6.0001})
    assert distintas.hoja(1).k != 1.0



@pytest.mark.parametrize("ppmm, angulo", [(2.0, 0.0), (2.0, 0.8), (1.5, -3.0), (6.0, 7.0)])
def test_la_hoja_ampliada_pinta_todo_su_recorte(ppmm, angulo):
    # Con k > 2 cada píxel de la hoja cubre más de dos de la unión: el borde del recorte
    # cae fuera de la caja de los centros de sus esquinas y no debe perderse.
    hojas = [{"n": 1, "x": 0, "y": 0},
             {"n": 2, "x": 150.3, "y": 110.7, "angulo": angulo, "recorte": [20, 30, 180, 140]}]
    geo = un.geometria(un.leer({"hojas": hojas}), {1: (400, 300), 2: (200, 170)}, {1: 6.0, 2: ppmm})
    h = geo.hoja(2)
    lienzo = np.zeros((geo.alto, geo.ancho, 3), np.uint8)
    un._pintar(lienzo, _lisa((30, 30, 200), 200, 170), h)
    x0, y0, x1, y1 = h.recorte
    m = h.matriz @ np.array([[1, 0, x0], [0, 1, y0], [0, 0, 1]], float)
    esperada = cv2.warpAffine(np.ones((y1 - y0, x1 - x0), np.uint8), m[:2], (geo.ancho, geo.alto),
                              flags=cv2.INTER_NEAREST).astype(bool)
    assert np.array_equal(lienzo.any(axis=2), esperada)

@pytest.mark.parametrize("dic, mensaje", [
    ({"hojas": [{"n": 1, "x": 0, "y": 0}]}, "entre 2 y 12"),
    ({"hojas": [{"n": i, "x": 0, "y": 0} for i in range(1, 14)]}, "entre 2 y 12"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 1, "x": 5, "y": 0}]}, "dos veces"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 2, "x": 0, "y": 0, "angulo": 10.5}]}, "giro fino"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 2, "x": 0, "y": 0, "rotacion": 45}]}, "0, 90, 180 o 270"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 2, "x": float("nan"), "y": 0}]}, "posición"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 2, "y": 0}]}, "posición"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 2, "x": 0, "y": 0, "recorte": [10, 10, 10, 50]}]}, "vacío"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 2, "x": 0, "y": 0, "recorte": [-5, 0, 10, 50]}]}, "se sale"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 2, "x": 0, "y": 0, "recorte": [0, 0, 401, 50]}]}, "se sale"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 2, "x": 0, "y": 0, "rotacion": 90,
                                          "recorte": [0, 0, 350, 50]}]}, "se sale"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 4, "x": 0, "y": 0}]}, "no es una página"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 2, "x": 0, "y": 0}], "cuadro": {"hoja": 3, "rect": [0, 0, 9, 9]}},
     "hojas unidas"),
    ({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 2, "x": 0, "y": 0}], "cuadro": {"hoja": 2, "rect": [0, 0, 9, 900]}},
     "se sale"),
])
def test_validaciones(dic, mensaje):
    with pytest.raises(ValueError, match=mensaje):
        un.leer(dic, paginas={1: (400, 300), 2: (400, 300), 3: (400, 300)})


def test_leer_normaliza():
    union = un.leer({"hojas": [{"n": 1, "x": 3, "y": 4}, {"n": 2, "x": 1.5, "y": 2, "rotacion": 90,
                                                         "angulo": 0.35, "recorte": [0.4, 1.6, 200, 399.6]}],
                     "cuadro": {"hoja": 2, "rect": [1, 2, 30, 40]}}, paginas={1: (400, 300), 2: (400, 300)})
    assert union.hojas[1].recorte == (0, 2, 200, 400)
    assert union.hojas[0] == un.Hoja(1, 0, 0.0, 3.0, 4.0, None)
    assert union.cuadro == {"hoja": 2, "rect": [1, 2, 30, 40]}
    assert un.leer(union.a_dic()) == union


def test_la_union_demasiado_grande_falla_antes_de_reservar_memoria():
    union = un.leer({"hojas": [{"n": 1, "x": 0, "y": 0}, {"n": 2, "x": 20000, "y": 0}]})
    with pytest.raises(ValueError, match="demasiado grande"):
        un.geometria(union, {1: (20000, 15000), 2: (20000, 15000)}, {1: 6.0, 2: 6.0})


def test_la_huella_cambia_con_cualquier_cosa_de_las_hojas():
    base = {"hojas": [{"n": 1, "x": 10, "y": 20, "rotacion": 90},
                      {"n": 2, "x": 300.5, "y": 20, "angulo": 0.3, "recorte": [0, 0, 100, 100]}]}
    h = un.huella(un.leer(base))
    assert h == un.huella(un.leer(base)) == un.huella(un.leer({"hojas": [{**base["hojas"][0], "x": 10.0},
                                                                          base["hojas"][1]]}))
    assert un.huella(un.leer({**base, "cuadro": {"hoja": 1, "rect": [0, 0, 5, 5]}})) == h
    cambios = [{"x": 11}, {"y": 21}, {"rotacion": 180}, {"angulo": 0.05}, {"recorte": [0, 0, 99, 100]}, {"n": 3}]
    for cambio in cambios:
        otra = {"hojas": [base["hojas"][0], {**base["hojas"][1], **cambio}]}
        assert un.huella(un.leer(otra)) != h, cambio
    assert un.huella(un.leer({"hojas": base["hojas"][::-1]})) != h


def _png(imagen) -> bytes:
    return cv2.imencode(".png", cv2.cvtColor(imagen, cv2.COLOR_RGB2BGR))[1].tobytes()


def test_componer_desde_pdf_usa_las_imagenes_del_pdf(tmp_path):
    original = _original()[:, :900]
    hojas, fuentes = [], {}
    for n, (a, b, angulo, rotacion) in enumerate([(0, 520, 0.5, 90), (380, 900, -0.4, 0)], start=1):
        fuentes[n], hoja = _hoja(original, a, b, angulo, rotacion)
        hojas.append({"n": n, **hoja})
    doc = pymupdf.open()
    for n in (1, 2):
        alto, ancho = fuentes[n].shape[:2]
        # A 6 px/mm: la hoja mide ancho/6 mm.
        hoja = doc.new_page(width=ancho / 6 / pg.MM_POR_PUNTO, height=alto / 6 / pg.MM_POR_PUNTO)
        hoja.insert_image(hoja.rect, stream=_png(fuentes[n]))
    pdf = tmp_path / "plano.pdf"
    doc.save(pdf)
    union = un.leer({"hojas": hojas})
    lienzo, ppmm = un.componer_desde_pdf(pdf, union)
    assert ppmm == pytest.approx(6.0, rel=1e-3)
    geo = _geometria(union, fuentes)
    esperado = un.componer({h.n: pg.rotar(fuentes[h.n], h.rotacion) for h in union.hojas}, geo)
    assert lienzo.shape == esperado.shape
    assert np.abs(lienzo.astype(int) - esperado).max() <= 1


# ---------------------------------------------------------------------------- casos para JS
# CASOS PARA kmz_union.test.js: los mismos números deben dar lo mismo en JS (Tarea 5).
# transformar_punto(px, py, ancho, alto, k, angulo, x, y, origen_x, origen_y) → (ux, uy)
CASOS_PUNTO = [
    ((100, 50, 1001, 801, 1.0, 90.0, 0, 0, 0, 0), (350.0, -400.0)),
    ((2400.0, 130.5, 4961, 3508, 0.75, 0.35, 6120.5, 2210.0, -37, 12), (6104.93683033259, 980.4061942936326)),
    ((10, 3999, 3000, 4000, 1.0, -2.5, 1500, 2000, 0, 0), (99.13463899081216, 4062.5679965335926)),
]
# geometria: hojas, tamaños sin girar y ppmm → origen, ancho, alto, ppmm y dos esquinas
# del recorte de la hoja 1 en px de unión.
CASO_GEOMETRIA = {
    "hojas": [{"n": 1, "rotacion": 90, "angulo": 1.5, "x": 500.0, "y": 400.0, "recorte": [10, 20, 790, 980]},
              {"n": 2, "rotacion": 0, "angulo": -0.4, "x": 1200.0, "y": 420.0, "recorte": None}],
    "tamanos": {1: (1000, 800), 2: (900, 850)},
    "ppmms": {1: 5.906, 2: 5.906},
    "origen": (98, -90), "ancho": 1556, "alto": 981, "ppmm": 5.906,
    "hoja1": [((10, 20), (25.185318635645615, 0.46839130830370834)),
              ((789, 979), (778.8146813643544, 979.5316086916963))],
}


@pytest.mark.parametrize("entrada, salida", CASOS_PUNTO)
def test_casos_numericos_de_transformar_punto(entrada, salida):
    assert un.transformar_punto(*entrada) == pytest.approx(salida, abs=1e-9)


def test_caso_numerico_de_geometria():
    c = CASO_GEOMETRIA
    geo = un.geometria(un.leer({"hojas": c["hojas"]}), c["tamanos"], c["ppmms"])
    assert (geo.origen, geo.ancho, geo.alto, geo.ppmm) == (c["origen"], c["ancho"], c["alto"], c["ppmm"])
    for p, q in c["hoja1"]:
        assert geo.a_union(1, [p])[0] == pytest.approx(q, abs=1e-9)
        h = c["hojas"][0]
        assert un.transformar_punto(*p, 800, 1000, 1.0, h["angulo"], h["x"], h["y"], *geo.origen) == \
            pytest.approx(q, abs=1e-9)


# ---------------------------------------------------------------------------- afinar
PPMM_AFINAR = 4.0
PLANO_AFINAR = (1440, 960)      # 360 × 240 mm a 4 px/mm


def _plano_con_textura() -> np.ndarray:
    """Un plano con dibujo de sobra para ORB: líneas de loteo, lotes, números y círculos,
    sin repetir un patrón (lo repetido calza en cualquier lado)."""
    rng = np.random.default_rng(7)
    ancho, alto = PLANO_AFINAR
    img = np.full((alto, ancho, 3), PAPEL, np.uint8)
    for _ in range(70):
        p, q = rng.integers(0, (ancho, alto), 2), rng.integers(0, (ancho, alto), 2)
        cv2.line(img, tuple(int(v) for v in p), tuple(int(v) for v in q), TINTA, int(rng.integers(1, 4)))
    for _ in range(90):
        x, y = (int(v) for v in rng.integers(0, (ancho - 60, alto - 40)))
        w, h = (int(v) for v in rng.integers(20, (90, 70)))
        cv2.rectangle(img, (x, y), (x + w, y + h), TINTA, int(rng.integers(1, 3)))
    for _ in range(160):
        x, y = (int(v) for v in rng.integers(0, (ancho - 40, alto)))
        cv2.putText(img, str(int(rng.integers(1, 999))), (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    float(rng.uniform(0.4, 0.9)), TINTA, 1, cv2.LINE_AA)
    for _ in range(25):
        c = tuple(int(v) for v in rng.integers(0, (ancho, alto)))
        cv2.circle(img, c, int(rng.integers(8, 40)), (190, 50, 50), 2)
    return img


@pytest.fixture(scope="module")
def plano_afinar():
    return _plano_con_textura()


def _franjas(plano, cortes):
    """Hojas sin giro con las franjas x∈[a, b) del plano y su posición verdadera."""
    imagenes, verdad = {}, {}
    for n, (a, b) in enumerate(cortes, start=1):
        imagenes[n] = np.ascontiguousarray(plano[:, a:b])
        w, h = b - a, plano.shape[0]
        verdad[n] = (a + (w - 1) / 2, (h - 1) / 2)
    return imagenes, verdad


def _error_px(hoja: dict, imagen, verdad) -> float:
    """Lo más que se alejan las esquinas de la hoja de su lugar verdadero, en px de unión."""
    alto, ancho = imagen.shape[:2]
    esquinas = un._esquinas((0, 0, ancho, alto))
    bien = pg._aplicar(un._matriz(ancho, alto, 1.0, 0.0, *verdad), esquinas)
    hecha = pg._aplicar(un._matriz(ancho, alto, 1.0, hoja["angulo"], hoja["x"], hoja["y"]), esquinas)
    return float(np.linalg.norm(bien - hecha, axis=1).max())


def _union(verdad, perturbaciones):
    hojas = []
    for n, (dx, dy, angulo) in perturbaciones.items():
        x, y = verdad[n]
        hojas.append({"n": n, "x": x + dx * PPMM_AFINAR, "y": y + dy * PPMM_AFINAR, "angulo": angulo})
    return un.leer({"hojas": hojas})


def test_afinar_devuelve_las_hojas_a_su_lugar(plano_afinar):
    imagenes, verdad = _franjas(plano_afinar, [(0, 620), (380, 1060), (820, 1440)])
    # mm y grados: la 1 queda donde está; la 2 y la 3 corridas 10–40 mm y giradas 1–2°.
    union = _union(verdad, {1: (0, 0, 0), 2: (32, -14, 1.6), 3: (-12, 25, -1.2)})
    salida = un.afinar(imagenes, {n: PPMM_AFINAR for n in imagenes}, union)
    assert [h["n"] for h in salida] == [1, 2, 3]
    assert salida[0]["x"] == verdad[1][0] and salida[0]["y"] == verdad[1][1] and salida[0]["angulo"] == 0
    for h in salida[1:]:
        assert h["calzada"], h
        assert _error_px(h, imagenes[h["n"]], verdad[h["n"]]) < 1.0, h
        assert h["residuo_mm"] is not None and h["residuo_mm"] < 0.25


def test_afinar_con_imagenes_reducidas(plano_afinar):
    """La consola pasa sus JPEG de pantalla: imágenes más chicas, con el tamaño y la
    resolución de la página completa aparte."""
    imagenes, verdad = _franjas(plano_afinar, [(0, 760), (560, 1440)])
    chicas = {n: cv2.resize(im, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA) for n, im in imagenes.items()}
    tamanos = {n: (im.shape[1], im.shape[0]) for n, im in imagenes.items()}
    union = _union(verdad, {1: (0, 0, 0), 2: (-20, 18, -1.0)})
    salida = un.afinar(chicas, {n: PPMM_AFINAR for n in imagenes}, union, tamanos)
    assert salida[1]["calzada"]
    assert _error_px(salida[1], imagenes[2], verdad[2]) < 1.0


def test_afinar_calza_una_hoja_dejada_lejos(plano_afinar):
    """Arrastrada a mano puede quedar a 100 mm: el primer intento no alcanza y el
    reintento con la zona y el tope grandes la calza."""
    imagenes, verdad = _franjas(plano_afinar, [(0, 620), (380, 1060)])
    # Traslape real de 60 mm; corrida 100 mm a la derecha ya ni toca a la de abajo.
    union = _union(verdad, {1: (0, 0, 0), 2: (100, 6, 1.0)})
    salida = un.afinar(imagenes, {n: PPMM_AFINAR for n in imagenes}, union)
    assert salida[1]["calzada"], salida[1]
    assert _error_px(salida[1], imagenes[2], verdad[2]) < 1.0


def test_afinar_sin_traslape_deja_la_hoja_como_estaba(plano_afinar):
    # Franjas que no comparten dibujo; la segunda, corrida 40 mm a la izquierda, tapa
    # 20 mm de la primera en el lienzo, pero ahí no hay nada que calzar.
    imagenes, verdad = _franjas(plano_afinar, [(0, 620), (700, 1440)])
    union = _union(verdad, {1: (5, 3, 0.5), 2: (-40, 0, 0)})
    salida = un.afinar(imagenes, {n: PPMM_AFINAR for n in imagenes}, union)
    assert salida[0] == {**union.hojas[0].a_dic(), "calzada": True, "residuo_mm": None}
    assert salida[1] == {**union.hojas[1].a_dic(), "calzada": False, "residuo_mm": None}


def test_afinar_no_acepta_un_calce_con_otro_dibujo(plano_afinar):
    imagenes, verdad = _franjas(plano_afinar, [(0, 620), (380, 1060)])
    # La segunda hoja es papel con otro dibujo: lo que encuentre ORB no pasa los topes.
    otro = np.full_like(imagenes[2], PAPEL)
    cv2.putText(otro, "OTRA LAMINA", (40, 400), cv2.FONT_HERSHEY_SIMPLEX, 2.0, TINTA, 3)
    imagenes[2] = otro
    union = _union(verdad, {1: (0, 0, 0), 2: (10, 10, 0)})
    salida = un.afinar(imagenes, {n: PPMM_AFINAR for n in imagenes}, union)
    assert salida[1]["calzada"] is False
    assert (salida[1]["x"], salida[1]["y"]) == (union.hojas[1].x, union.hojas[1].y)
