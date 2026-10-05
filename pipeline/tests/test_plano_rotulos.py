"""El lector de rótulos: números de lote, cuadrícula y cuadro de superficies.

Lo que no necesita Tesseract (interpretar, seleccionar, combinar con las semillas de la
loteadora, ajustar la cuadrícula, leer áreas) corre siempre. Lo que lee imágenes de
verdad corre solo donde está el ejecutable (la imagen de Docker)."""
import json

import cv2
import numpy as np
import pytest
from shapely.geometry import box

from pipeline.plano import rotulos
from pipeline.plano.__main__ import main
from pipeline.plano.rotulos import Rotulo
from pipeline.tests.plano_sintetico import NEGRO, PAPEL

con_tesseract = pytest.mark.skipif(not rotulos.disponible(), reason="tesseract no está instalado")


# --- números ---------------------------------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    # El rótulo como está en el plano: El Arrayán (LOTE-12), Hidango (LOTE 10-6, la
    # palabra LOTE llega aparte) y Caminos de Rapel (LOTE 8-01, con el cero).
    ("LOTE-12", "12"), ("LOTE12", "12"), ("12", "12"), ("10-6", "10-6"), ("lote-7-", "7"),
    ("8-01", "8-01"), ("LOTE-8-01", "8-01"), ("012", "012"),
    ("123,45", None), ("5.000", None), ("LOTE", None), ("0", None), ("8-00", None), ("1234", None), ("", None),
])
def test_numero(texto, esperado):
    assert rotulos.numero(texto) == esperado


def _datos(palabras):
    """Lo que devuelve pytesseract.image_to_data, con todas en la misma línea."""
    d = dict(text=[], left=[], top=[], width=[], height=[], conf=[], block_num=[], par_num=[], line_num=[])
    for t, x, y, w, h in palabras:
        for k, v in zip(("text", "left", "top", "width", "height", "conf"), (t, x, y, w, h, 90.0)):
            d[k].append(v)
        d["block_num"].append(1), d["par_num"].append(1), d["line_num"].append(1)
    return d


def test_interpretar_vuelve_al_marco_original_y_reconoce_lote():
    # Escala 2 y sin giro: la posición se divide por 2. "LOTE" como palabra anterior.
    d = _datos([("LOTE", 100, 50, 60, 20), ("12", 170, 50, 30, 20), ("123,45", 300, 50, 60, 20)])
    m = np.array([[1.0, 0, 0], [0, 1.0, 0]])
    (l,) = rotulos.interpretar(d, m, 2.0, 0.0, "gris")
    assert l["numero"] == "12" and l["lote"]
    assert l["x"] == pytest.approx((100 + 200) / 2 / 2) and l["y"] == pytest.approx(30)
    assert l["alto"] == pytest.approx(10)


def _lectura(n, x, y, lote=True, alto=10.0, ang=0, var="gris", escala=1.0, conf=80.0):
    return dict(numero=n, lote=lote, x=x, y=y, conf=conf, ang=ang, var=var, escala=escala, alto=alto)


def test_seleccionar_agrupa_por_apoyo_y_deja_un_numero_por_lugar():
    lecturas = []
    for k, ang in enumerate(range(0, 60, 15)):           # 4 pasadas leen 12 en (100, 100)
        lecturas.append(_lectura(12, 100 + k, 100, ang=ang))
    lecturas.append(_lectura(17, 102, 101, ang=90))      # una pasada lo lee como 17: pierde
    lecturas += [_lectura(5, 400, 300, ang=a) for a in (0, 15)]
    lecturas.append(_lectura(5, 900, 900, ang=30))        # el 5 en otro lugar: un lugar por número
    lecturas += [_lectura(3, 600, 600, lote=False, alto=30.0, ang=a) for a in (0, 15, 30)]   # sin LOTE
    lecturas += [_lectura(n, 50 * n, 700, ang=a) for n in range(20, 26) for a in (0,)]       # ≥ 10 con LOTE

    salida = {r.numero: r for r in rotulos.seleccionar(lecturas, alto_modal=8.0, pasadas=96)}

    assert salida["12"].apoyo == 4 and salida["12"].confianza == pytest.approx(4 / 96)
    assert "17" not in salida
    assert (salida["5"].x, salida["5"].y, salida["5"].apoyo) == (400, 300, 2)
    assert "3" not in salida                              # el plano rotula con LOTE: el suelto no cuenta


def test_seleccionar_guarda_el_rotulo_completo_y_junta_las_formas():
    # "LOTE 8-01" en Caminos de Rapel: unas pasadas leen "8-01", otra "8-1" y otra solo
    # "01" (sin el sector). Es un solo rótulo y se queda como en el plano.
    lecturas = [_lectura("8-01", 100, 100, ang=a) for a in (0, 15, 30)]
    lecturas += [_lectura("8-1", 101, 100, ang=45), _lectura("01", 102, 101, ang=60)]
    lecturas += [_lectura("10-6", 500, 500, ang=a) for a in (0, 15)]
    lecturas += [_lectura(n, 50 * n, 900) for n in range(20, 28)]                  # ≥ 10 con LOTE

    salida = {r.numero: r for r in rotulos.seleccionar(lecturas, alto_modal=8.0, pasadas=96)}

    assert salida["8-01"].apoyo == 5 and (salida["8-01"].x, salida["8-01"].y) == (100, 100)
    assert "8-1" not in salida and "01" not in salida
    assert salida["10-6"].apoyo == 2


def test_seleccionar_sin_lote_pide_texto_grande():
    lecturas = ([_lectura(4, 100, 100, lote=False, alto=20.0)]
                + [_lectura(9, 300, 100, lote=False, alto=9.0)])        # cota chica
    assert [r.numero for r in rotulos.seleccionar(lecturas, alto_modal=10.0, pasadas=96)] == ["4"]


# --- semillas: la loteadora manda ------------------------------------------------------

def test_combinar_da_prioridad_a_la_loteadora():
    lector = [Rotulo("1", 100, 100, 0.5, 48), Rotulo("2", 300, 100, 0.4, 40),      # ella lo renumeró
              Rotulo("3", 500, 100, 0.3, 30), Rotulo("4", 700, 100, 0.01, 1),       # apoyo 1: no
              Rotulo("5", 900, 100, 0.2, 20), Rotulo("6", 1100, 100, 0.2, 20)]
    usuario = [dict(numero="22", x=305, y=102),          # corrige el 2 (a menos del radio)
               ("5", 1500, 500),                         # mueve el 5: el leído se descarta
               ("8", 1150, 150)]                         # hace clic en el lote del 6, lejos del rótulo
    poligonos = [box(1000, 0, 1200, 200).exterior.coords]

    salida = rotulos.combinar(usuario, lector, radio=20, apoyo_min=2, poligonos=poligonos)

    por_numero = {s["numero"]: s for s in salida}
    assert sorted(por_numero) == ["1", "22", "3", "5", "8"]
    assert por_numero["22"]["origen"] == "usuario" and por_numero["22"]["confianza"] is None
    assert (por_numero["5"]["x"], por_numero["5"]["origen"]) == (1500.0, "usuario")
    assert por_numero["1"] == dict(numero="1", x=100.0, y=100.0, origen="lector", confianza=0.5, apoyo=48)
    assert [s["origen"] for s in salida[:3]] == ["usuario"] * 3


def test_combinar_compara_numeros_normalizados():
    # Ella escribió "8-1" lejos del rótulo "8-01": es el mismo lote, gana ella. Y en
    # Hidango marcó "6" donde el plano dice "LOTE 10-6".
    lector = [Rotulo("8-01", 100, 100, 0.5, 48), Rotulo("10-6", 300, 100, 0.4, 40),
              Rotulo("8-02", 500, 100, 0.3, 30)]
    usuario = [("8-1", 900, 900), ("6", 1200, 900)]
    salida = rotulos.combinar(usuario, lector, radio=20)
    assert [s["numero"] for s in salida] == ["8-1", "6", "8-02"]


def test_combinar_sin_semillas_de_la_loteadora_toma_las_del_lector():
    lector = [Rotulo("1", 100, 100, 0.5, 48), Rotulo("2", 300, 100, 0.01, 1)]
    assert [s["numero"] for s in rotulos.combinar([], lector, radio=20)] == ["1"]
    assert [s["numero"] for s in rotulos.combinar([], lector, radio=20, apoyo_min=1)] == ["1", "2"]


# --- sin Tesseract ----------------------------------------------------------------------

def test_sin_tesseract_no_se_cae(monkeypatch):
    monkeypatch.setattr(rotulos.shutil, "which", lambda nombre: None)
    lineas = []
    imagen = np.full((200, 300, 3), 255, np.uint8)

    assert rotulos.leer(imagen, 6.0, avance=lineas.append) == []
    assert rotulos.leer_cuadricula(imagen, 6.0, avance=lineas.append) is None
    assert rotulos.leer_cuadro(imagen, [[0, 0, 300, 200]], avance=lineas.append) == {}
    assert lineas == ["sin lector de rótulos: tesseract no está instalado"]
    assert not rotulos.disponible()


def test_una_pasada_que_falla_se_salta():
    def mala(*_):
        raise RuntimeError("tesseract se cayó")
    lineas = []
    salida = rotulos._correr([(mala,), (lambda: [1, 2],)], 2, lineas.append, "Rótulos")
    assert salida == [1, 2]
    assert lineas[-1] == "Rótulos: 1 pasadas fallaron y se saltaron"


# --- cuadro de superficies --------------------------------------------------------------

@pytest.mark.parametrize("texto, esperado", [
    ("5,00hás", 50000), ("5,00 has", 50000), ("0,52 ha", 5200), ("5.000", 5000), ("5.000 m²", 5000),
    ("5.000,50 m2", 5000.5), ("12.345.678", 12345678), ("5,00", 50000), ("5000", 5000), ("abc", None),
])
def test_area_m2(texto, esperado):
    assert rotulos.area_m2(texto) == esperado


def test_areas_de_filas_usa_la_ultima_columna_y_decide_la_unidad_por_columna():
    texto = "1 10,00 0,00 10,00\n2 10,63 0,21 10,84\nTOTAL\n2 9,99\n202 222\n3 13,45 0,43 13,88\n"
    filas = rotulos.filas_cuadro(texto)
    assert [f[0] for f in filas] == ["1", "2", "2", "3"]          # '202 222' no termina en área
    assert rotulos.areas_de_filas(filas) == {"1": 100000.0, "2": 108400.0, "3": 138800.0}
    # En m² (la mediana es grande): '5.000' son 5000 m², no 5000 ha.
    assert rotulos.areas_de_filas([["1", "5.000"], ["2", "5.230,5"]]) == {"1": 5000.0, "2": 5230.5}


def test_cuadro_como_el_de_caminos_de_rapel():
    """LOTE | SUP. SERVIDUMBRE | TOTAL, con el número como está impreso ("8-01") y la unidad
    pegada. El total es la columna de más a la derecha; la del medio no cuenta. El resto
    de la propiedad no empieza con un número de lote en la línea que trae las áreas (el
    "8" va solo en la línea de arriba): no es fila. Sin la "m" en la lista blanca,
    Tesseract leía "5.0002": eso no tiene forma de área y no es fila."""
    texto = (".0\n8-01 1.342m2 5.000m2\n8-02 435 m2 5.000 m2\n8-02 4352 5.0002\n8-03 456m2 5.000m2\n"
             "8\ns 0.000m2 760.000m2\n0sa 0.000m2 760.000m2\n")
    filas = rotulos.filas_cuadro(texto)
    assert filas == [["8-01", "1.342m2", "5.000m2"], ["8-02", "435 m2", "5.000 m2"], ["8-03", "456m2", "5.000m2"]]
    assert rotulos.areas_de_filas(filas) == {"8-01": 5000.0, "8-02": 5000.0, "8-03": 5000.0}
    # Si una pasada lee el resto en una sola línea, queda en el cuadro con su número.
    assert rotulos.areas_de_filas(rotulos.filas_cuadro("8 o resto 0.000 m2 760.000 m2")) == {"8": 760000.0}
    # La unidad de la celda manda sobre la de la columna: "5,00hás" son 5 ha aunque las
    # demás estén en m².
    assert rotulos.areas_de_filas([["1", "5.000"], ["2", "5.100"], ["3", "5,00hás"]]) \
        == {"1": 5000.0, "2": 5100.0, "3": 50000.0}


def test_areas_de_filas_gana_el_valor_mas_leido():
    filas = [["8-01", "5.000m2"], ["8-1", "6.000m2"], ["8-01", "5.000m2"], ["2", "5.100"], ["02", "5.100"]]
    assert rotulos.areas_de_filas(filas) == {"8-01": 5000.0, "2": 5100.0}


# --- cuadrícula --------------------------------------------------------------------------

def test_progresion_saca_la_lectura_que_rompe_el_paso():
    assert rotulos.progresion([255750, 256500, 257250, 258000]) == [255750, 256500, 257250, 258000]
    assert rotulos.progresion([255750, 256500, 256506, 257250]) == [255750, 256500, 257250]
    assert rotulos.progresion([255750, 256500]) == []                 # dos no hacen progresión


def test_ajustar_cuadricula_robusta_a_lecturas_malas():
    # Como Algarrobo: N rotula las verticales (x) y E las horizontales (y); 590 px cada 750 m.
    lecturas = []
    for k, v in enumerate((6306750, 6307500, 6308250, 6309000, 6309750)):
        lecturas += [("N", v, 693 + 590 * k, 150), ("N", v, 694 + 590 * k, 6100)]
    for k, v in enumerate((255750, 256500, 257250, 258000, 258750)):
        lecturas += [("E", v, 181, 275 + 590 * k), ("E", v, 3455, 271 + 590 * k)]
    lecturas += [("E", 120000, 3221, 453), ("E", 259750, 3451, 274),   # malas: fuera de su recta
                 ("E", 298750, 3455, 2635), ("N", 4352012, 2380, 4712)]

    c = rotulos.ajustar_cuadricula(lecturas, tolerancia=18, separacion=59)

    assert [m["valor"] for m in c["verticales"]] == [6306750, 6307500, 6308250, 6309000, 6309750]
    assert [m["valor"] for m in c["horizontales"]] == [255750, 256500, 257250, 258000, 258750]
    assert c["verticales"][0]["x"] == pytest.approx(693.5)
    assert c["horizontales"][1]["y"] == pytest.approx(863)          # mediana de 865 y 861
    assert c["epsg"] is None


def test_ajustar_cuadricula_sin_progresion_no_propone_nada():
    lecturas = [("E", 255750, 100, 100), ("E", 256500, 100, 700)]                 # solo dos
    assert rotulos.ajustar_cuadricula(lecturas, tolerancia=18, separacion=59) is None
    # Todas en la misma columna: la recta contra x sería plana, y contra y no hay progresión.
    lecturas = [("E", v, 3455, 300) for v in (255750, 256500, 257250, 120000)]
    assert rotulos.ajustar_cuadricula(lecturas, tolerancia=18, separacion=59) is None


@pytest.mark.parametrize("texto, esperado", [
    ("E-255750", ("E", 255750)), ("N-6306750", ("N", 6306750)), ("E255750", ("E", 255750)),
    ("E-6306750", None), ("N-255750", None), ("X-255750", None),
])
def test_marca(texto, esperado):
    assert rotulos.marca(texto) == esperado


# --- digitalizar con el lector ------------------------------------------------------------

def _carpeta_sin_semillas(tmp_path):
    from pipeline.tests.test_plano_cli import _carpeta
    plano = _carpeta(tmp_path)
    entradas = json.loads((tmp_path / "entradas.json").read_text(encoding="utf-8"))
    entradas["semillas"] = []
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    return plano, entradas


def test_digitalizar_con_las_semillas_del_lector(tmp_path, monkeypatch, capsys):
    plano, entradas = _carpeta_sin_semillas(tmp_path)
    # El lector "lee" bien los rótulos del plano sintético (en px del recorte del dibujo).
    x0, y0 = entradas["rectangulo"][:2]
    leidos = [Rotulo(n, x - x0, y - y0, 0.4, 40, 12.0) for n, x, y in plano.semillas]
    leidos.append(Rotulo("99", 5, 5, 0.01, 1, 12.0))          # ruido de apoyo 1: no es semilla
    llamadas = []
    monkeypatch.setattr(rotulos, "motivo_no_disponible", lambda: None)
    monkeypatch.setattr(rotulos, "leer", lambda imagen, ppmm, avance: llamadas.append(imagen.shape) or leidos)
    monkeypatch.setattr(rotulos, "leer_cuadricula", lambda imagen, ppmm, avance, rectangulo: None)
    monkeypatch.setattr(rotulos, "leer_cuadro", lambda imagen, rects, avance: {"1": 30600.0, "2": 28000.0, "12": 31000.0})

    assert main(["digitalizar", str(tmp_path)]) == 0

    datos = json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))
    assert len(datos["lotes"]) == len(plano.semillas)
    assert {l["origen"] for l in datos["lotes"]} == {"lector"}
    uno = next(l for l in datos["lotes"] if l["numero"] == "1")
    assert (uno["confianza"], uno["apoyo"], uno["area_oficial"]) == (0.4, 40, 30600.0)
    assert next(l for l in datos["lotes"] if l["numero"] == "3")["area_oficial"] is None
    lector = datos["lector"]
    assert lector["disponible"] and lector["semillas"] == len(plano.semillas) and len(lector["rotulos"]) == 13
    # Las posiciones guardadas están en px de página (se sumó el origen del recorte).
    r1 = next(r for r in lector["rotulos"] if r["numero"] == "1")
    s1 = next(s for s in plano.semillas if s[0] == "1")
    assert (r1["x"], r1["y"]) == (pytest.approx(s1[1]), pytest.approx(s1[2]))
    assert "Semillas: 0 de la loteadora y 12 del lector (apoyo ≥ 2)" in capsys.readouterr().out

    # La loteadora corrige el 1 (clic dentro del lote, lejos del rótulo) y digitaliza de
    # nuevo: no se vuelve a leer, y su número reemplaza al leído.
    entradas["semillas"] = [dict(numero="101", x=s1[1] + 60, y=s1[2] + 40)]
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    assert main(["digitalizar", str(tmp_path)]) == 0
    assert len(llamadas) == 1
    datos = json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))
    numeros = {l["numero"]: l["origen"] for l in datos["lotes"]}
    assert "1" not in numeros and numeros["101"] == "usuario" and len(numeros) == len(plano.semillas)


def _lector_falso(monkeypatch, cuadro, leidos=None):
    """El lector sin Tesseract: guarda lo que recibe y devuelve `leidos` y `cuadro`."""
    visto = {}
    monkeypatch.setattr(rotulos, "motivo_no_disponible", lambda: None)
    monkeypatch.setattr(rotulos, "leer", lambda imagen, ppmm, avance: visto.update(dibujo=imagen) or (leidos or []))
    monkeypatch.setattr(rotulos, "leer_cuadricula", lambda imagen, ppmm, avance, rectangulo: None)
    monkeypatch.setattr(rotulos, "leer_cuadro",
                        lambda imagen, rects, avance: visto.update(pagina=imagen.shape, rects=rects) or cuadro)
    return visto


def test_el_cuadro_marcado_fuera_del_dibujo_se_lee_y_da_los_faltantes(tmp_path, monkeypatch):
    """El cuadro de Caminos de Rapel está fuera del rectángulo del dibujo: se lee igual
    (de la página entera), no tapa nada del dibujo, y sus números dan los faltantes (el
    13, que el lector nunca leyó) y el área oficial de cada lote."""
    plano, entradas = _carpeta_sin_semillas(tmp_path)
    x0, y0 = entradas["rectangulo"][:2]
    leidos = [Rotulo(n, x - x0, y - y0, 0.4, 40, 12.0) for n, x, y in plano.semillas]
    cuadro = {str(n): 5000.0 + n for n in range(1, 14)}
    entradas["cuadro"] = [2, 2, x0 - 10, y0 - 10]                      # fuera del dibujo
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    visto = _lector_falso(monkeypatch, cuadro, leidos)

    assert main(["digitalizar", str(tmp_path)]) == 0

    datos = json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))
    assert visto["rects"] == [[2.0, 2.0, x0 - 10.0, y0 - 10.0]]
    assert visto["pagina"][:2] == (plano.imagen.shape[0], plano.imagen.shape[1])    # la página entera
    assert datos["huecos"] == ["13"]
    assert datos["lector"]["cuadro"] == cuadro
    assert {l["numero"]: l["area_oficial"] for l in datos["lotes"]} == {str(n): 5000.0 + n for n in range(1, 13)}
    # Fuera del dibujo no tapa nada: lo que lee el lector es el dibujo tal cual.
    assert not (visto["dibujo"] == visto["dibujo"][0, 0]).all()


def test_el_resto_de_la_propiedad_no_es_un_faltante(tmp_path, monkeypatch):
    plano, entradas = _carpeta_sin_semillas(tmp_path)
    x0, y0 = entradas["rectangulo"][:2]
    # Como Rapel: lotes "8-01"… y el resto, "8", con su área.
    leidos = [Rotulo(f"8-{int(n):02d}", x - x0, y - y0, 0.4, 40, 12.0) for n, x, y in plano.semillas]
    cuadro = {f"8-{n:02d}": 5000.0 for n in range(1, 14)} | {"8": 760000.0}
    entradas["cuadro"] = [2, 2, x0 - 10, y0 - 10]
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    _lector_falso(monkeypatch, cuadro, leidos)

    assert main(["digitalizar", str(tmp_path)]) == 0

    datos = json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))
    assert datos["huecos"] == ["8-13"]
    assert {l["area_oficial"] for l in datos["lotes"]} == {5000.0}


def test_un_numero_sin_sector_es_de_la_serie(tmp_path, monkeypatch, capsys):
    """Caminos de Rapel en producción: un clic viejo "9" entre lecturas "8-01"… es el
    "8-09", no otro lote, y el 8-09 no se avisa como faltante."""
    plano, entradas = _carpeta_sin_semillas(tmp_path)
    x0, y0 = entradas["rectangulo"][:2]
    leidos = [Rotulo(f"8-{int(n):02d}", x - x0, y - y0, 0.4, 40, 12.0) for n, x, y in plano.semillas]
    _, x9, y9 = next(s for s in plano.semillas if s[0] == "9")
    entradas["semillas"] = [dict(numero="9", x=x9, y=y9)]
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    cuadro = {f"8-{n:02d}": 5000.0 for n in range(1, 13)}
    _lector_falso(monkeypatch, cuadro, leidos)

    assert main(["digitalizar", str(tmp_path)]) == 0

    datos = json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))
    numeros = {l["numero"]: l for l in datos["lotes"]}
    assert "9" not in numeros and numeros["8-09"]["origen"] == "usuario"
    assert numeros["8-09"]["area_oficial"] == 5000.0
    assert len(numeros) == len(plano.semillas)
    assert datos["huecos"] == [] and datos["faltantes"] == []
    assert "Sin sector: 9 → 8-09" in capsys.readouterr().out


def test_el_cuadro_dentro_del_dibujo_lo_tapa(tmp_path, monkeypatch):
    plano, entradas = _carpeta_sin_semillas(tmp_path)
    x0, y0 = entradas["rectangulo"][:2]
    entradas["cuadro"] = [x0 + 10, y0 + 10, x0 + 200, y0 + 150]
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    visto = _lector_falso(monkeypatch, {})

    assert main(["digitalizar", str(tmp_path)]) == 0

    tapado = visto["dibujo"][12:148, 12:198]                     # en px del recorte del dibujo
    assert (tapado == tapado[0, 0]).all()
    assert visto["rects"] == [entradas["cuadro"]]


def test_una_lectura_vacia_no_se_reusa(tmp_path, monkeypatch):
    """Si el lector no leyó nada (suele ser que falló), digitalizar de nuevo vuelve a leer."""
    _carpeta_sin_semillas(tmp_path)
    llamadas = []
    monkeypatch.setattr(rotulos, "motivo_no_disponible", lambda: None)
    monkeypatch.setattr(rotulos, "leer", lambda imagen, ppmm, avance: llamadas.append(1) or [])
    monkeypatch.setattr(rotulos, "leer_cuadricula", lambda imagen, ppmm, avance, rectangulo: None)
    monkeypatch.setattr(rotulos, "leer_cuadro", lambda imagen, rects, avance: {})

    assert main(["digitalizar", str(tmp_path)]) == 0
    assert main(["digitalizar", str(tmp_path)]) == 0

    assert len(llamadas) == 2


def test_cambiar_las_mascaras_vuelve_a_leer(tmp_path, monkeypatch):
    plano, entradas = _carpeta_sin_semillas(tmp_path)
    llamadas = []
    monkeypatch.setattr(rotulos, "motivo_no_disponible", lambda: None)
    monkeypatch.setattr(rotulos, "leer", lambda imagen, ppmm, avance: llamadas.append(1)
                        or [Rotulo("1", 10, 10, 0.4, 40, 12.0)])
    monkeypatch.setattr(rotulos, "leer_cuadricula", lambda imagen, ppmm, avance, rectangulo: None)
    monkeypatch.setattr(rotulos, "leer_cuadro", lambda imagen, rects, avance: {})

    assert main(["digitalizar", str(tmp_path)]) == 0
    assert main(["digitalizar", str(tmp_path)]) == 0
    assert len(llamadas) == 1                                       # misma huella: se reusa
    x0, y0 = entradas["rectangulo"][:2]
    entradas["mascaras"] = (entradas.get("mascaras") or []) + [[x0, y0, x0 + 5, y0 + 5]]
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    assert main(["digitalizar", str(tmp_path)]) == 0
    assert len(llamadas) == 2


def test_digitalizar_sin_tesseract_sigue_con_las_semillas(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rotulos.shutil, "which", lambda nombre: None)
    from pipeline.tests.test_plano_cli import _carpeta
    plano = _carpeta(tmp_path)

    assert main(["digitalizar", str(tmp_path)]) == 0

    assert "sin lector de rótulos: tesseract no está instalado" in capsys.readouterr().out
    datos = json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))
    assert len(datos["lotes"]) == len(plano.semillas)
    assert {l["origen"] for l in datos["lotes"]} == {"usuario"}
    assert datos["lector"]["disponible"] is False and datos["lector"]["semillas"] == 0


def test_lector_apagado(tmp_path, monkeypatch):
    plano, entradas = _carpeta_sin_semillas(tmp_path)
    entradas["lector"] = False
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    monkeypatch.setattr(rotulos, "leer", lambda *a, **k: pytest.fail("el lector está apagado"))

    assert main(["digitalizar", str(tmp_path)]) == 0

    datos = json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))
    assert datos["lotes"] == [] and datos["lector"] == {"activo": False}


@pytest.mark.parametrize("cambio, mensaje", [
    (dict(lector="sí"), "«lector» es true o false"),
    (dict(lector_apoyo_min=0), "«lector_apoyo_min» es 1 o más"),
    (dict(cuadro=[10, 10, 5, 5]), "cuadro de superficies está vacío"),
])
def test_entradas_del_lector_malas(tmp_path, capsys, cambio, mensaje):
    _, entradas = _carpeta_sin_semillas(tmp_path)
    entradas.update(cambio)
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    assert main(["digitalizar", str(tmp_path)]) == 1
    assert mensaje in capsys.readouterr().err


# --- con Tesseract de verdad (en la imagen de Docker) ---------------------------------------

def _texto(img, texto, centro, escala, angulo=0):
    """Escribe `texto` centrado en `centro`, girado `angulo` grados (antihorario)."""
    (w, h), base = cv2.getTextSize(texto, cv2.FONT_HERSHEY_SIMPLEX, escala, 2)
    lado = int(max(w, h) * 1.6) + 10
    parche = np.full((lado, lado), 255, np.uint8)
    cv2.putText(parche, texto, ((lado - w) // 2, (lado + h) // 2), cv2.FONT_HERSHEY_SIMPLEX, escala, 0, 2,
                cv2.LINE_AA)
    parche = cv2.warpAffine(parche, cv2.getRotationMatrix2D((lado / 2, lado / 2), angulo, 1.0), (lado, lado),
                            borderValue=255)
    x0, y0 = int(centro[0] - lado / 2), int(centro[1] - lado / 2)
    a, b = max(0, -x0), max(0, -y0)                       # lo que se sale de la imagen se corta
    zona = img[y0 + b:y0 + lado, x0 + a:x0 + lado]
    np.minimum(zona, parche[b:b + zona.shape[0], a:a + zona.shape[1], None], out=zona)


@con_tesseract
def test_leer_rotulos_de_verdad():
    img = np.full((1000, 1500, 3), PAPEL, np.uint8)
    esperados = {"12": (250, 200, 0), "7": (700, 200, 45), "31": (1100, 250, 90), "5": (300, 650, 0),
                 "48": (750, 650, 0), "26": (1150, 650, 30)}
    for n, (x, y, a) in esperados.items():
        _texto(img, f"LOTE {n}", (x, y), 1.0, a)
    for n in range(60, 66):                                  # más rótulos rectos: el plano rotula con LOTE
        _texto(img, f"LOTE {n}", (150 + 220 * (n - 60), 870), 0.9)
    _texto(img, "123,45", (500, 420), 1.0)                   # una cota: no es lote
    lineas = []

    leidos = {r.numero: r for r in rotulos.leer(img, 6.0, avance=lineas.append)}

    for n, (x, y, _) in esperados.items():
        assert n in leidos, (n, sorted(leidos))
        assert abs(leidos[n].x - x) < 40 and abs(leidos[n].y - y) < 40
        assert leidos[n].apoyo >= rotulos.APOYO_MIN
    assert "123" not in leidos and "45" not in leidos
    assert any("pasadas" in l for l in lineas)


@con_tesseract
def test_leer_cuadro_de_verdad():
    filas = [("1", "10,00"), ("2", "10,84"), ("3", "13,88"), ("4", "15,90"), ("5", "15,93")]
    img = np.full((60 + 50 * len(filas), 700, 3), 255, np.uint8)
    for k, (n, a) in enumerate(filas):
        y = 50 + 50 * k
        cv2.putText(img, n, (40, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, NEGRO, 2, cv2.LINE_AA)
        cv2.putText(img, "0,21", (250, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, NEGRO, 2, cv2.LINE_AA)
        cv2.putText(img, a, (500, y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, NEGRO, 2, cv2.LINE_AA)
        cv2.line(img, (10, y + 15), (690, y + 15), NEGRO, 2)              # la grilla del cuadro
    for x in (10, 200, 450, 690):
        cv2.line(img, (x, 10), (x, img.shape[0] - 10), NEGRO, 2)
    grande = np.full((800, 1200, 3), 255, np.uint8)
    grande[100:100 + img.shape[0], 300:1000] = img

    areas = rotulos.leer_cuadro(grande, [[0, 0, 200, 200], [290, 90, 1010, 110 + img.shape[0]]], avance=print)

    assert areas == {n: round(float(a.replace(",", ".")) * 10000, 2) for n, a in filas}


@con_tesseract
def test_leer_cuadricula_de_verdad():
    img = np.full((2000, 2000, 3), 255, np.uint8)
    for k in range(4):
        x = 400 + 350 * k
        cv2.line(img, (x, 300), (x, 1700), NEGRO, 1)
        _texto(img, f"E-{255750 + 750 * k}", (x - 25, 160), 1.0, 90)
        y = 400 + 350 * k
        cv2.line(img, (300, y), (1700, y), NEGRO, 1)
        _texto(img, f"N-{6309750 - 750 * k}", (1820, y - 25), 0.8, 0)

    c = rotulos.leer_cuadricula(img, 6.0, avance=print)

    assert c is not None
    vert = {m["valor"]: m["x"] for m in c["verticales"]}
    hori = {m["valor"]: m["y"] for m in c["horizontales"]}
    assert len(vert) >= 3 and len(hori) >= 3
    for v, x in vert.items():
        assert abs(x - (400 + 350 * (v - 255750) / 750)) < 60
    for v, y in hori.items():
        assert abs(y - (400 + 350 * (6309750 - v) / 750)) < 60


def test_franjas_alrededor_del_dibujo():
    # Como Algarrobo: marcas a 8 mm por fuera y a 14 mm por dentro del rectángulo.
    cajas = rotulos.franjas([100, 300, 3520, 6150], (6957, 3636), 30 * 5.91)
    assert len(cajas) == 4
    for x, y in ((181, 4409), (3455, 2045), (1284, 151), (1874, 6107)):
        assert any(a0 <= x < a1 and b0 <= y < b1 for a0, b0, a1, b1 in cajas), (x, y)
    assert all(0 <= a0 < a1 <= 3636 and 0 <= b0 < b1 <= 6957 for a0, b0, a1, b1 in cajas)
    assert not any(a0 <= 1800 < a1 and b0 <= 3000 < b1 for a0, b0, a1, b1 in cajas)    # el centro no


def test_combinar_con_cuadro_compara_el_numero_dentro_del_sector():
    # El cuadro de Rapel lista 1…16 (o 8-01…8-16): "8-03" es el 3; "8-450" no está.
    lector = [Rotulo("8-03", 100, 100, 0.5, 48), Rotulo("8-450", 300, 100, 0.4, 40)]
    for cuadro in ({"1": 5000.0, "2": 5000.0, "3": 5000.0}, {"8-01": 5000.0, "8-02": 5000.0, "8-03": 5000.0}):
        assert [s["numero"] for s in rotulos.combinar([], lector, radio=20, oficiales=cuadro)] == ["8-03"]


def test_combinar_con_cuadro_descarta_numeros_que_no_son_lotes():
    lector = [Rotulo("12", 100, 100, 0.5, 48), Rotulo("450", 300, 100, 0.4, 40),     # una cota
              Rotulo("30", 500, 100, 0.3, 30)]                                     # falta en el cuadro leído
    oficiales = {"1": 5000.0, "12": 5100.0, "76": 5200.0}
    salida = rotulos.combinar([], lector, radio=20, oficiales=oficiales)
    assert [s["numero"] for s in salida] == ["12", "30"]


def test_combinar_ignora_un_cuadro_que_dejaria_fuera_a_la_mayoria():
    """Un cuadro de coordenadas (vértices 1…3) leído como si fuera el de superficies no
    puede borrar los lotes 4…10."""
    lector = [Rotulo(str(n), 100 * n, 100, 0.5, 48) for n in range(1, 11)]
    salida = rotulos.combinar([], lector, radio=20, oficiales={"1": 5000.0, "2": 5000.0, "3": 5000.0})
    assert sorted(int(s["numero"]) for s in salida) == list(range(1, 11))


def test_las_hebras_caben_en_la_memoria(monkeypatch):
    monkeypatch.setattr(rotulos, "nucleos", lambda: 16)
    monkeypatch.delenv("LECTOR_HEBRAS", raising=False)
    monkeypatch.setattr(rotulos, "memoria_libre", lambda: 4 * 2**30)
    # 600 MB por pasada: en el 60 % de 4 GiB caben 4.
    assert rotulos._hebras(None, 96, 600e6) == 4
    assert rotulos._hebras(None, 3, 1e6) == 3
    # Aunque no quepa ni una, se lee con una.
    assert rotulos._hebras(None, 96, 8e9) == 1
    monkeypatch.setattr(rotulos, "memoria_libre", lambda: None)
    assert rotulos._hebras(None, 96, 600e6) == 16
    monkeypatch.setenv("LECTOR_HEBRAS", "2")
    assert rotulos._hebras(None, 96) == 2


@pytest.mark.parametrize("archivos, esperado", [
    ({"/sys/fs/cgroup/cpu.max": "200000 100000"}, 2),           # docker --cpus=2 / Cloud Run --cpu=2
    ({"/sys/fs/cgroup/cpu.max": "150000 100000"}, 2),           # 1,5 → 2
    ({"/sys/fs/cgroup/cpu.max": "50000 100000"}, 1),
    ({"/sys/fs/cgroup/cpu.max": "max 100000"}, 16),             # sin cuota: los de la afinidad
    ({"/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "300000",          # cgroup v1
      "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000"}, 3),
    ({"/sys/fs/cgroup/cpu/cpu.cfs_quota_us": "-1",
      "/sys/fs/cgroup/cpu/cpu.cfs_period_us": "100000"}, 16),
    ({}, 16),                                                   # Windows: ni cgroup
])
def test_nucleos_respeta_la_cuota_del_contenedor(monkeypatch, archivos, esperado):
    """En un contenedor os.cpu_count() da los núcleos del host: con 16 hebras en 2 vCPU
    la memoria se multiplica sin ganar velocidad."""
    monkeypatch.setattr(rotulos.os, "sched_getaffinity", lambda pid: set(range(16)), raising=False)
    monkeypatch.setattr(rotulos, "_leer_archivo", archivos.get)
    assert rotulos.nucleos() == esperado
