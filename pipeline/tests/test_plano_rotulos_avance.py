"""El lector guarda su avance por pasada y lo retoma.

El 2026-10-08 Constitución se cortó en la pasada 42 de 96, a los 16 minutos, porque
Cloud Run cambió la instancia; reintentar empezaba de cero. Ahora cada pasada terminada
queda en un JSON y una lectura nueva sobre la misma carpeta parte donde quedó."""
import json
import re

import numpy as np
import pytest

from pipeline.plano import rotulos
from pipeline.plano.__main__ import main
from pipeline.plano.digitalizar import AVANCE_LECTOR, huella_lector, leer_entradas
from pipeline.tests.test_plano_rotulos import _carpeta_sin_semillas
from pipeline.tests.test_plano_rotulos_teselas import _barra, _lector_de_barras


class Corte(BaseException):
    """Hace de la instancia que muere: no es un Exception, así que nada la ataja."""


def _imagen():
    img = np.full((1500, 1200, 3), 255, np.uint8)
    for k in range(6, 15):
        _barra(img, str(k), (100 + 70 * k, 80 + 95 * k))
    return img


@pytest.fixture
def llamadas(monkeypatch):
    """El lector de barras de `test_plano_rotulos_teselas` en teselas chicas, anotando
    qué pasada lee cada llamada (una por tesela)."""
    vistas = []

    def lector(imagen, escala, angulo, variante):
        vistas.append((round(escala, 4), angulo, variante))
        return _lector_de_barras(imagen, escala, angulo, variante)
    monkeypatch.setattr(rotulos, "motivo_no_disponible", lambda: None)
    monkeypatch.setattr(rotulos, "_pasada_rotulos", lector)
    monkeypatch.setattr(rotulos, "TESELA_MPX", 0.4)
    return vistas


def _leer(img, carpeta, lineas=None):
    # Una hebra: el orden de las pasadas (y dónde cae el corte) no depende del azar.
    return rotulos.leer(img, 6.0, avance=(lineas if lineas is not None else []).append, hebras=1,
                        paso=90, avance_en=carpeta)


def _resumen(leidos):
    return sorted((r.numero, r.apoyo, round(r.x), round(r.y)) for r in leidos)


def _pasadas(vistas):
    return set(vistas)


def _teselas_e0(vistas):
    """Cuántas teselas tiene una pasada a la escala del texto (la del sondeo)."""
    return vistas.count(vistas[0])


def test_una_lectura_cortada_se_retoma_donde_quedo(tmp_path, llamadas, monkeypatch):
    img = _imagen()
    corrido = _leer(img, tmp_path / "corrido")
    todas = _pasadas(llamadas)
    teselas = _teselas_e0(llamadas)
    assert teselas > 1 and len(todas) > 8, "la prueba necesita varias teselas y las dos fases"
    assert len(list((tmp_path / "corrido").glob("*.json"))) == len(todas)

    # La instancia muere a mitad de una pasada (la quinta), después de 4 enteras.
    del llamadas[:]
    original = rotulos._pasada_rotulos

    def muere(*args):
        if len(llamadas) >= 4 * teselas + 1:
            raise Corte()
        return original(*args)
    monkeypatch.setattr(rotulos, "_pasada_rotulos", muere)
    with pytest.raises(Corte):
        _leer(img, tmp_path / "cortado")
    guardadas = sorted(p.name for p in (tmp_path / "cortado").glob("*.json"))
    assert len(guardadas) == 4
    assert not list((tmp_path / "cortado").glob(".*"))              # ni temporales a medias
    leidas_antes = _pasadas(llamadas[:4 * teselas])

    # Se retoma: da lo mismo que de corrido y no vuelve a leer las 4 pasadas guardadas.
    monkeypatch.setattr(rotulos, "_pasada_rotulos", original)
    del llamadas[:]
    lineas = []
    retomado = _leer(img, tmp_path / "cortado", lineas)

    assert _resumen(retomado) == _resumen(corrido)
    assert not _pasadas(llamadas) & leidas_antes
    assert _pasadas(llamadas) | leidas_antes == todas
    assert "Rótulos: se retoman 4 pasadas ya leídas" in lineas


def test_el_contador_con_pasadas_retomadas_no_retrocede_ni_se_pasa(tmp_path, llamadas):
    img = _imagen()
    lineas = []
    _leer(img, tmp_path, lineas)
    hechas = next(int(m.group(1)) for l in lineas if (m := re.search(r"se leen (\d+) pasadas de", l)))
    # Faltan dos del sondeo y dos del resto.
    archivos = sorted(tmp_path.glob("*.json"))
    for nombre in ("e0-gris-000.json", "e0-bin-180.json"):
        (tmp_path / nombre).unlink()
    resto = [p for p in archivos if p.name.startswith("e1")]
    for p in resto[:2]:
        p.unlink()
    lineas = []

    _leer(img, tmp_path, lineas)

    assert f"Rótulos: se retoman {hechas - 4} pasadas ya leídas" in lineas
    cuentas = [tuple(map(int, m.groups())) for l in lineas if (m := re.match(r"Rótulos: (\d+) de (\d+) pasadas", l))]
    assert cuentas, lineas
    assert all(x <= y for x, y in cuentas)
    xs = [x for x, _ in cuentas]
    assert xs == sorted(xs)
    assert cuentas[-1] == (hechas, hechas), lineas


def test_un_archivo_roto_se_vuelve_a_leer(tmp_path, llamadas):
    img = _imagen()
    corrido = _leer(img, tmp_path)
    por_pasada = _teselas_e0(llamadas)
    (tmp_path / "e0-gris-090.json").write_text("[{\"numero\": \"7\", ", encoding="utf-8")       # cortado
    (tmp_path / "e0-bin-090.json").write_text(json.dumps([{"numero": 7, "x": "1"}]), encoding="utf-8")
    (tmp_path / "e0-gris-270.json").write_text(json.dumps({"no": "es una lista"}), encoding="utf-8")
    del llamadas[:]
    lineas = []

    retomado = _leer(img, tmp_path, lineas)

    e0 = round(rotulos.ALTO_TEXTO_PX / 20.0, 4)                     # sin letras, alto_caracter da 20
    assert _pasadas(llamadas) == {(e0, 90.0, "gris"), (e0, 90.0, "bin"), (e0, 270.0, "gris")}
    assert len(llamadas) == 3 * por_pasada
    assert _resumen(retomado) == _resumen(corrido)
    # Y quedan bien escritos para la próxima.
    for nombre in ("e0-gris-090.json", "e0-bin-090.json", "e0-gris-270.json"):
        assert rotulos._cargar_pasada(tmp_path / nombre) is not None


def test_una_pasada_con_una_tesela_mala_no_se_guarda(tmp_path, llamadas, monkeypatch):
    original = rotulos._pasada_rotulos
    malas = []

    def falla_una(imagen, escala, angulo, variante):
        if (angulo, variante) == (90.0, "bin") and not malas:
            malas.append(1)
            raise RuntimeError("tesseract se cayó")
        return original(imagen, escala, angulo, variante)
    monkeypatch.setattr(rotulos, "_pasada_rotulos", falla_una)

    _leer(_imagen(), tmp_path)

    assert malas
    guardadas = {p.name for p in tmp_path.glob("*.json")}
    assert "e0-bin-090.json" not in guardadas
    assert "e0-gris-090.json" in guardadas and "e0-bin-000.json" in guardadas


def test_las_lecturas_vuelven_iguales_del_json(tmp_path):
    """Lo que usan `orientaciones` y `seleccionar` vuelve con el mismo valor y tipo,
    también si llega con tipos de numpy."""
    d = dict(numero="8-01", lote=True, x=np.float64(10.5), y=12.25, conf=np.float32(91.0), ang=45.0,
             var="gris", escala=1.2, alto=np.float64(18.0))
    ruta = tmp_path / "e0-gris-045.json"
    rotulos._guardar_pasada(str(ruta), [d])
    (vuelta,) = rotulos._cargar_pasada(ruta)
    assert vuelta == {k: (v.item() if isinstance(v, np.generic) else v) for k, v in d.items()}
    assert all(type(vuelta[k]) is type(v) for k, v in d.items() if not isinstance(v, np.generic))
    assert rotulos.seleccionar([vuelta], 10.0, 1)[0].numero == "8-01"


def test_correr_avisa_las_pasadas_completas():
    def mala():
        raise RuntimeError("tesseract se cayó")
    completas = {}
    salida = rotulos._correr([(lambda: [1],), (lambda: [2],), (mala,), (lambda: [3],), (lambda: [],)], 1,
                             lambda _: None, "Rótulos", ["a", "a", "b", "b", "c"],
                             al_completar=lambda p, leidas: completas.update({p: list(leidas)}))
    assert sorted(salida) == [1, 2, 3]
    assert completas == {"a": [1, 2], "c": []}                     # "b" tuvo una tesela mala


def test_un_error_al_guardar_no_tumba_la_lectura():
    def lleno(p, leidas):
        raise OSError("No queda espacio en el disco")
    lineas = []
    salida = rotulos._correr([(lambda k=k: [k],) for k in range(3)], 1, lineas.append, "Rótulos",
                             al_completar=lleno)
    assert salida == [0, 1, 2]
    errores = [l for l in lineas if "no se pudo guardar" in l]
    assert len(errores) == 1 and "No queda espacio" in errores[0]


# --- digitalizar ------------------------------------------------------------------------------

def test_digitalizar_guarda_el_avance_por_huella_y_lo_borra_al_terminar(tmp_path, monkeypatch):
    _carpeta_sin_semillas(tmp_path)
    huella = huella_lector(tmp_path, leer_entradas(tmp_path))
    vieja = tmp_path / AVANCE_LECTOR / "otrahuella"
    vieja.mkdir(parents=True)
    (vieja / "e0-gris-000.json").write_text("[]", encoding="utf-8")
    visto = {}

    def leer(imagen, ppmm, avance, avance_en=None):
        visto.update(avance_en=avance_en, vieja=vieja.exists())
        avance_en.mkdir(parents=True, exist_ok=True)
        (avance_en / "e0-gris-000.json").write_text("[]", encoding="utf-8")
        return [rotulos.Rotulo("1", 10, 10, 0.4, 40, 12.0)]
    monkeypatch.setattr(rotulos, "motivo_no_disponible", lambda: None)
    monkeypatch.setattr(rotulos, "leer", leer)
    monkeypatch.setattr(rotulos, "leer_cuadricula", lambda imagen, ppmm, avance, rectangulo:
                        visto.update(en_cuadricula=(tmp_path / AVANCE_LECTOR / huella).exists()))
    monkeypatch.setattr(rotulos, "leer_cuadro", lambda imagen, rects, avance: {})

    assert main(["digitalizar", str(tmp_path)]) == 0

    assert visto["avance_en"] == tmp_path / AVANCE_LECTOR / huella
    assert visto["vieja"] is False                                  # otra huella: se borró al empezar
    assert visto["en_cuadricula"] is True                           # se borra al terminar, no antes
    assert not (tmp_path / AVANCE_LECTOR).exists()


def test_el_avance_sobrevive_si_digitalizar_muere_despues_del_lector(tmp_path, monkeypatch):
    """Si la instancia muere digitalizando los lotes, digitalizado.json no tiene la
    lectura: el avance tiene que seguir ahí para retomarla sin releer."""
    from pipeline.plano import digitalizar as dig
    _carpeta_sin_semillas(tmp_path)

    def leer(imagen, ppmm, avance, avance_en=None):
        avance_en.mkdir(parents=True, exist_ok=True)
        (avance_en / "e0-gris-000.json").write_text("[]", encoding="utf-8")
        return [rotulos.Rotulo("1", 10, 10, 0.4, 40, 12.0)]

    def muere(*args, **kwargs):
        raise Corte()
    monkeypatch.setattr(rotulos, "motivo_no_disponible", lambda: None)
    monkeypatch.setattr(rotulos, "leer", leer)
    monkeypatch.setattr(rotulos, "leer_cuadricula", lambda imagen, ppmm, avance, rectangulo: None)
    monkeypatch.setattr(rotulos, "leer_cuadro", lambda imagen, rects, avance: {})
    monkeypatch.setattr(dig, "digitalizar_imagen", muere)

    with pytest.raises(Corte):
        dig.digitalizar(tmp_path, avance=lambda _: None)

    huella = huella_lector(tmp_path, leer_entradas(tmp_path))
    assert (tmp_path / AVANCE_LECTOR / huella / "e0-gris-000.json").exists()


def test_digitalizar_sin_tesseract_no_guarda_avance(tmp_path, monkeypatch):
    monkeypatch.setattr(rotulos.shutil, "which", lambda nombre: None)
    _carpeta_sin_semillas(tmp_path)

    assert main(["digitalizar", str(tmp_path)]) == 0

    assert not (tmp_path / AVANCE_LECTOR).exists()
