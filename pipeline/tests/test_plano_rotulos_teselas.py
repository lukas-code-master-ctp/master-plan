"""El lector que cabe y termina: teselas, memoria por pasada y orientaciones primero.

En producción (Cloud Run, 4 GiB y 2 vCPU) una página de 5008×7038 px con texto de 15 px
botó la instancia a la pasada 30 de 96: el dibujo se agrandaba 1,6× y, girado en
diagonal, crecía otra vez. Ahora cada pasada lee por teselas acotadas y solo se leen
las orientaciones donde el sondeo encontró rótulos."""
import re
from collections import defaultdict

import cv2
import numpy as np
import pytest

from pipeline.plano import rotulos
from pipeline.tests.plano_sintetico import PAPEL
from pipeline.tests.test_plano_rotulos import _texto, con_tesseract


# --- memoria: cuánto pide una pasada ---------------------------------------------------------

def test_memoria_de_una_pasada_cuenta_el_giro():
    assert rotulos.pixeles_girada(1000, 1000, 0) == pytest.approx(1e6)
    assert rotulos.pixeles_girada(1000, 500, 90) == pytest.approx(5e5)
    # A 45° un cuadrado ocupa el doble; una tira alargada, mucho más.
    assert rotulos.pixeles_girada(1000, 1000, 45) == pytest.approx(2e6)
    assert rotulos.pixeles_girada(4000, 500, 45) > 4 * 4000 * 500
    assert rotulos.memoria_pasada(1000, 1000, 45) == pytest.approx(
        rotulos.BYTES_FIJOS_PASADA + rotulos.BYTES_POR_PIXEL * 2e6)


@pytest.mark.parametrize("archivos, esperado", [
    # cgroup v2 (Docker, Cloud Run): el límite menos lo que usa el contenedor entero.
    ({"/sys/fs/cgroup/memory.max": str(4 * 2**30), "/sys/fs/cgroup/memory.current": str(2**30)}, 3 * 2**30),
    # cgroup v1.
    ({"/sys/fs/cgroup/memory/memory.limit_in_bytes": str(4 * 2**30),
      "/sys/fs/cgroup/memory/memory.usage_in_bytes": str(2**30)}, 3 * 2**30),
    # Sin límite (v2 "max", v1 un número enorme): lo disponible del sistema.
    ({"/sys/fs/cgroup/memory.max": "max", "/sys/fs/cgroup/memory.current": "1",
      "/proc/meminfo": "MemTotal: 16000000 kB\nMemAvailable:    2000000 kB\n"}, 2000000 * 1024),
    ({"/sys/fs/cgroup/memory/memory.limit_in_bytes": "9223372036854771712",
      "/sys/fs/cgroup/memory/memory.usage_in_bytes": "1",
      "/proc/meminfo": "MemAvailable: 1000 kB\n"}, 1000 * 1024),
    # Con límite, nunca más que lo disponible del sistema.
    ({"/sys/fs/cgroup/memory.max": str(4 * 2**30), "/sys/fs/cgroup/memory.current": "0",
      "/proc/meminfo": "MemAvailable: 1000 kB\n"}, 1000 * 1024),
    ({}, None),                                                 # Windows
])
def test_memoria_libre_es_la_del_contenedor(monkeypatch, archivos, esperado):
    monkeypatch.setattr(rotulos, "_leer_archivo", archivos.get)
    assert rotulos.memoria_libre() == esperado


# --- teselas -----------------------------------------------------------------------------------

@pytest.mark.parametrize("alto, ancho, escala", [
    (6998, 4968, 1.6),       # la página grande de producción, con texto de 15 px
    (8200, 4650, 1.2),       # Puente Negro
    (1510, 1240, 3.43),      # Curicó: texto chico, mucho agrandado
    (531, 456, 2.4),         # Caminos de Rapel: cabe en una
    (300, 9000, 1.0),        # una tira
])
def test_teselas_parten_la_imagen_y_caben(alto, ancho, escala):
    ts = rotulos.teselas(alto, ancho, escala)
    lado = (rotulos.TESELA_MPX * 1e6) ** 0.5
    margen = min(rotulos.MARGEN_TESELA_ALTOS * rotulos.ALTO_TEXTO_PX, lado / 4) / escala
    for t in ts:
        x0, y0, x1, y1 = t.recorte
        assert 0 <= x0 < x1 <= ancho and 0 <= y0 < y1 <= alto
        # Girado en diagonal, a lo más el doble de TESELA_MPX (más el redondeo).
        assert ((x1 - x0) + (y1 - y0)) * escala <= 2 * lado + 4
        assert rotulos.pixeles_girada((x1 - x0) * escala, (y1 - y0) * escala, 45) <= 2.01 * rotulos.TESELA_MPX * 1e6
        # El recorte es el núcleo más el margen (lo que quepa en la imagen).
        n0, m0, n1, m1 = t.nucleo
        assert x0 <= max(0, n0 - margen) + 1 and x1 >= min(ancho, n1 + margen) - 1
        assert y0 <= max(0, m0 - margen) + 1 and y1 >= min(alto, m1 + margen) - 1
    # Los núcleos parten la imagen: cada punto (también fuera del borde) cae en uno solo.
    rng = np.random.default_rng(0)
    for x, y in np.c_[rng.uniform(-5, ancho + 5, 400), rng.uniform(-5, alto + 5, 400)]:
        assert sum(t.tiene(x, y) for t in ts) == 1
    if (alto + ancho) * escala <= 2 * lado:                # cabe girada: una sola
        assert len(ts) == 1


def test_el_umbral_de_otsu_es_el_de_la_imagen_escalada_entera():
    """Las teselas se binarizan con el umbral que tendría la imagen escalada entera (el
    de la imagen sin escalar no sirve: Caminos de Rapel perdía la mitad de los rótulos)."""
    rng = np.random.default_rng(3)
    g = np.full((900, 700), 235, np.uint8)
    for _ in range(300):
        x, y = rng.integers(0, 680), rng.integers(0, 880)
        g[y:y + rng.integers(2, 20), x:x + rng.integers(2, 20)] = rng.integers(20, 140)
    g = cv2.GaussianBlur(g, (5, 5), 0)
    assert rotulos.otsu_de_histograma(np.bincount(g.ravel(), minlength=256)) == \
        cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0]
    for escala in (2.2, 0.9):
        entero = cv2.threshold(cv2.GaussianBlur(rotulos._escalar(g, escala), (3, 3), 0), 0, 255,
                               cv2.THRESH_BINARY + cv2.THRESH_OTSU)[0]
        una = rotulos.teselas(*g.shape, escala)
        varias = rotulos.teselas(*g.shape, escala, 0.3)
        assert len(una) == 1 and len(varias) > 4
        assert rotulos.umbral_otsu(g, escala, una) == entero
        assert abs(rotulos.umbral_otsu(g, escala, varias) - entero) <= 2


def _lector_de_barras(imagen, escala, angulo, variante):
    """Hace de Tesseract: cada barra negra es un rótulo "LOTE n", con n su largo / 10 (px
    sin escalar). Una barra cortada por el borde del recorte se lee con el largo que se
    ve: un número equivocado, como el "LOTE 1" de un "LOTE 12" cortado."""
    _, _, st, centros = cv2.connectedComponentsWithStats((imagen < 128).astype(np.uint8), 8)
    return [dict(numero=str(round(w / escala / 10)), lote=True, x=float(cx / escala), y=float(cy / escala),
                 conf=90.0, ang=angulo, var=variante, escala=round(escala, 4), alto=float(h / escala))
            for (_, _, w, h, _), (cx, cy) in zip(st[1:], centros[1:]) if h >= 3]


def _barra(img, numero, centro):
    largo, (cx, cy) = int(numero) * 10, centro
    cv2.rectangle(img, (int(cx - largo / 2), int(cy - 10)), (int(cx + largo / 2) - 1, int(cy + 9)), (0, 0, 0), -1)


@pytest.fixture
def lector_falso(monkeypatch):
    """Teselas chicas (0,4 Mpx) para que una imagen de 1200×1500 se lea en varias."""
    monkeypatch.setattr(rotulos, "motivo_no_disponible", lambda: None)
    monkeypatch.setattr(rotulos, "_pasada_rotulos", _lector_de_barras)
    monkeypatch.setattr(rotulos, "TESELA_MPX", 0.4)
    return monkeypatch


def test_un_rotulo_en_el_borde_de_dos_teselas_se_lee_una_vez(lector_falso):
    alto, ancho = 1500, 1200
    img = np.full((alto, ancho, 3), 255, np.uint8)
    e1 = rotulos.ALTO_TEXTO_PX / 20.0                     # sin letras, alto_caracter da 20
    ts = rotulos.teselas(alto, ancho, e1, 0.4)
    xs = sorted({t.nucleo[2] for t in ts if np.isfinite(t.nucleo[2])})
    ys = sorted({t.nucleo[3] for t in ts if np.isfinite(t.nucleo[3])})
    assert xs and ys, "la prueba necesita varias teselas en cada eje"
    primera = next(t for t in ts if t.nucleo[0] == -np.inf and t.nucleo[1] == -np.inf)
    barras = {                                            # número: centro
        "6": (xs[0], (ys[0] + ys[1]) / 2),                 # sobre un borde vertical entre núcleos
        "8": ((xs[0] + xs[1]) / 2, ys[0]),                 # sobre un borde horizontal
        "10": (xs[0], ys[0]),                              # sobre una esquina de cuatro
        "12": (primera.recorte[2], 120),                   # cortada por el borde del recorte de la primera
        "14": (150, 1400),                                 # bien adentro
    }
    for n, centro in barras.items():
        _barra(img, n, centro)
    vistas = []
    lector_falso.setattr(rotulos, "seleccionar", lambda lecturas, *a, **k: vistas.extend(lecturas) or [])

    rotulos.leer(img, 6.0, avance=lambda _: None, paso=90, sondeo=())

    por_pasada = defaultdict(list)
    for d in vistas:
        por_pasada[(d["escala"], d["ang"], d["var"])].append(d["numero"])
    assert len(por_pasada) == 16                           # 4 ángulos × 2 escalas × gris/Otsu
    for pasada, numeros in por_pasada.items():
        # Cada barra una vez por pasada: ni repetida por dos teselas ni el pedazo cortado.
        assert sorted(numeros, key=int) == sorted(barras, key=int), pasada
    for d in vistas:
        cx, cy = barras[d["numero"]]
        assert abs(d["x"] - cx) < 3 and abs(d["y"] - cy) < 3


def test_leer_por_teselas_junta_las_lecturas(lector_falso):
    """De punta a punta: cada barra sale una vez, con el apoyo de todas las pasadas."""
    img = np.full((1500, 1200, 3), 255, np.uint8)
    centros = {str(k): (100 + 70 * k, 80 + 95 * k) for k in range(6, 15)}
    for n, centro in centros.items():
        _barra(img, n, centro)
    lineas = []

    leidos = rotulos.leer(img, 6.0, avance=lineas.append, paso=90, sondeo=())

    assert sorted(r.numero for r in leidos) == sorted(centros)
    assert all(r.apoyo == 16 for r in leidos)
    avance = [l for l in lineas if re.match(r"Rótulos: \d+ de \d+ pasadas", l)]
    assert avance[-1].startswith("Rótulos: 16 de 16 pasadas")


def test_las_hebras_se_cuentan_con_la_tesela_agrandada_y_girada(lector_falso):
    pedido = []
    original = rotulos._hebras
    lector_falso.setattr(rotulos, "_hebras", lambda h, n, b=0: pedido.append(b) or original(h, n, b))
    img = np.full((1500, 1200, 3), 255, np.uint8)

    rotulos.leer(img, 6.0, avance=lambda _: None, paso=90, sondeo=())

    e1 = rotulos.ALTO_TEXTO_PX / 20.0
    mayor = max(rotulos.memoria_pasada((t.recorte[2] - t.recorte[0]) * e1, (t.recorte[3] - t.recorte[1]) * e1, 45)
                for t in rotulos.teselas(1500, 1200, e1, 0.4))
    assert pedido[0] == pytest.approx(mayor)
    # Nunca más que una tesela girada en diagonal: no crece con la imagen.
    assert pedido[0] <= rotulos.BYTES_FIJOS_PASADA + rotulos.BYTES_POR_PIXEL * 2.01 * 0.4e6


def test_correr_cuenta_pasadas_y_no_teselas():
    lineas = []
    tareas = [(lambda k=k: [k],) for k in range(6)]
    salida = rotulos._correr(tareas, 2, lineas.append, "Rótulos", ["a", "a", "a", "b", "b", "b"],
                             previas=4, inicio=0.0)
    assert sorted(salida) == list(range(6))
    # Dos pasadas (de tres teselas cada una) después de 4 ya hechas: "6 de 6".
    assert [re.sub(r" \(\d+ s\)", "", l) for l in lineas] == ["Rótulos: 6 de 6 pasadas"]


def test_una_tesela_que_falla_salta_su_pasada_una_vez():
    def mala():
        raise RuntimeError("tesseract se cayó")
    lineas = []
    salida = rotulos._correr([(mala,), (mala,), (lambda: [1],)], 1, lineas.append, "Rótulos", ["a", "a", "b"])
    assert salida == [1]
    assert lineas[-1] == "Rótulos: 1 pasadas fallaron y se saltaron"


# --- orientaciones primero -------------------------------------------------------------------

def _lectura(numero, x, y, ang, var, lote=True, alto=20.0):
    return dict(numero=numero, lote=lote, x=x, y=y, conf=90.0, ang=ang, var=var, escala=1.2, alto=alto)


def test_orientaciones_por_los_pares_de_gris_y_otsu():
    lecturas = []
    for k in range(10):                                    # rótulos derechos: pares a 0°
        for var in ("gris", "bin"):
            lecturas.append(_lectura(str(k + 1), 100 * k, 50, 0, var))
    for k in range(4):                                     # unos pocos verticales: pares a 90°
        for var in ("gris", "bin"):
            lecturas.append(_lectura(str(k + 20), 50, 100 * k, 90, var))
    for a in range(0, 360, 45):                            # ruido: lecturas sueltas en todos
        for k in range(15):
            lecturas.append(_lectura(str(k + 40), 137 * k + a, 900 + 11 * a, a, "gris" if k % 2 else "bin"))

    assert rotulos.orientaciones(lecturas, 15.0) == [0, 15, 75, 90, 105, 345]
    # Sin pares en ningún ángulo no se sabe: se leen todos.
    assert rotulos.orientaciones([d for d in lecturas if int(d["numero"]) >= 40], 15.0) is None
    assert rotulos.orientaciones([], 15.0) is None


def test_orientaciones_sobre_el_ruido():
    """Como Algarrobo (sin LOTE): los números grandes de las cotas también dan pares, en
    todos los ángulos. Cuenta el ángulo que se despega de ese piso."""
    lecturas = []
    for a in range(0, 360, 45):
        for k in range(73 if a == 90 else 11):
            for var in ("gris", "bin"):
                lecturas.append(_lectura(str(k % 99 + 1), 60 * k, 13 * a, a, var, lote=False, alto=30))
    assert rotulos.orientaciones(lecturas, 15.0) == [75, 90, 105]
    # Un plano que dice LOTE no tiene ese piso: un solo par basta (un rótulo diagonal suelto).
    solo = [_lectura("7", 10, 10, 315, v) for v in ("gris", "bin")]
    derechos = [_lectura(str(k + 1), 100 * k, 50, 0, v) for k in range(9) for v in ("gris", "bin")]
    assert rotulos.orientaciones(solo + derechos, 15.0) == [0, 15, 300, 315, 330, 345]


def test_orientaciones_sin_lote_cuentan_los_numeros_grandes():
    # Algarrobo no dice LOTE: cuentan los números de ALTO_SUELTO × el texto modal o más.
    chicos = [_lectura(str(k + 1), 100 * k, 50, 0, v, lote=False, alto=12) for k in range(10) for v in ("gris", "bin")]
    grandes = [_lectura(str(k + 1), 100 * k, 50, 90, v, lote=False, alto=30) for k in range(5) for v in ("gris", "bin")]
    assert rotulos.orientaciones(chicos + grandes, 15.0) == [75, 90, 105]


@con_tesseract
def test_el_sondeo_lee_solo_las_orientaciones_de_los_rotulos():
    img = np.full((1100, 1600, 3), PAPEL, np.uint8)
    derechos = {str(n): (180 + 300 * (k % 5), 150 + 220 * (k // 5)) for k, n in enumerate(range(11, 21))}
    verticales = {str(n): (150 + 400 * k, 850) for k, n in enumerate(range(31, 35))}
    for n, centro in derechos.items():
        _texto(img, f"LOTE {n}", centro, 0.9)
    for n, centro in verticales.items():
        _texto(img, f"LOTE {n}", centro, 0.9, 90)
    lineas = []

    leidos = {r.numero: r for r in rotulos.leer(img, 6.0, avance=lineas.append)}

    eleccion = next(l for l in lineas if "orientaciones de los rótulos" in l)
    angulos = [int(a) for a in re.findall(r"(\d+)°", eleccion)]
    assert 0 in angulos and (90 in angulos or 270 in angulos), eleccion
    assert not {135, 180, 225} & set(angulos), eleccion
    hechas = int(re.search(r"se leen (\d+) pasadas de 96", eleccion).group(1))
    assert hechas <= 48
    # La última línea de avance cuenta las pasadas que de verdad se leyeron.
    avance = [l for l in lineas if re.match(r"Rótulos: \d+ de \d+ pasadas", l)]
    assert avance[-1].startswith(f"Rótulos: {hechas} de {hechas} pasadas")
    for n, (x, y) in {**derechos, **verticales}.items():
        assert n in leidos, (n, sorted(leidos))
        assert abs(leidos[n].x - x) < 40 and abs(leidos[n].y - y) < 40
