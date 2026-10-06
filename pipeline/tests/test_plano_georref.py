import json
import math

import numpy as np
import pytest
from pyproj import Transformer

from pipeline.plano.__main__ import main
from pipeline.plano.georreferencia import (Transformacion, ajuste_fino, comparar_datum, cuadricula_suficiente,
                                           huso, por_anclas, por_cuadricula)

# Una similitud conocida, px de página → UTM 19S: 0,25 m/px, girada 20°.
ESCALA, GIRO = 0.25, 20.0
A = ESCALA * complex(math.cos(math.radians(GIRO)), math.sin(math.radians(GIRO)))
B = complex(300000.0, 6150000.0)


def _verdad(x, y, a=A, b=B):
    w = a * (np.asarray(x, float) - 1j * np.asarray(y, float)) + b
    return w.real, w.imag


def _anclas(px, epsg=32719, ruido=None, a=A, b=B):
    e, n = _verdad(px[:, 0], px[:, 1], a, b)
    if ruido is not None:
        e, n = e + ruido[:, 0], n + ruido[:, 1]
    lon, lat = Transformer.from_crs(epsg, 4326, always_xy=True).transform(e, n)
    return [dict(nombre=f"a{i}", x=float(x), y=float(y), lon=float(lo), lat=float(la))
            for i, ((x, y), lo, la) in enumerate(zip(px, lon, lat))]


PX = np.array([[600.0, 700.0], [4200.0, 900.0], [3900.0, 5200.0], [800.0, 4800.0], [2400.0, 2900.0]])
PRUEBA = np.array([[100.0, 100.0], [2500.0, 3000.0], [5000.0, 6000.0]])


def test_similitud_exacta_se_recupera():
    t = por_anclas(_anclas(PX[:4]))

    assert t.epsg == 32719 and t.tipo == "similitud"
    assert abs(t.parametros["escala_m_px"] - ESCALA) < 1e-8
    assert abs(t.parametros["rotacion_grados"] - GIRO) < 1e-6
    e, n = t.a_utm(PRUEBA[:, 0], PRUEBA[:, 1])
    ve, vn = _verdad(PRUEBA[:, 0], PRUEBA[:, 1])
    assert np.abs(e - ve).max() < 1e-6 and np.abs(n - vn).max() < 1e-6
    assert t.parametros["control"] == "ok" and t.parametros["rms_m"] < 1e-6
    assert not any(a["atipica"] for a in t.anclas)


def test_con_ruido_el_error_queda_del_orden_del_ruido():
    rng = np.random.default_rng(3)
    t = por_anclas(_anclas(PX, ruido=rng.normal(0, 1.0, (5, 2))))

    e, n = t.a_utm(PRUEBA[:, 0], PRUEBA[:, 1])
    ve, vn = _verdad(PRUEBA[:, 0], PRUEBA[:, 1])
    assert np.hypot(e - ve, n - vn).max() < 3.0
    assert 0.2 < t.parametros["rms_m"] < 3.0       # 2D, σ = 1 m por eje
    assert not any(a["atipica"] for a in t.anclas)


def test_un_ancla_corrida_15_m_queda_marcada():
    ruido = np.array([[0.6, -0.4], [-0.5, 0.3], [0.2, 0.7], [-0.3, -0.5]])
    ruido[2, 0] += 15.0
    t = por_anclas(_anclas(PX[:4], ruido=ruido))

    marcadas = [a["nombre"] for a in t.anclas if a["atipica"]]
    assert marcadas == ["a2"]
    assert t.parametros["control"] == "atipicas"
    mala = t.anclas[2]
    assert mala["residuo_sin_ella_m"] > 12.0
    # La mala contamina el ajuste: su residuo con todas es menor que sin ella.
    assert mala["residuo_m"] < mala["residuo_sin_ella_m"]
    assert "El punto a2 no calza con los demás: márcalo de nuevo o quítalo." in t.avisos


def test_tres_anclas_inconsistentes_se_avisan():
    ruido = np.zeros((3, 2))
    ruido[1, 1] = 15.0
    t = por_anclas(_anclas(PX[:3], ruido=ruido))

    assert t.parametros["control"] == "inconsistente"
    assert t.anclas[1]["atipica"]
    assert t.avisos


def test_dos_anclas_quedan_sin_control():
    t = por_anclas(_anclas(PX[:2]))

    assert t.parametros["control"] == "sin control"
    assert t.parametros["rms_m"] is None
    assert all("atipica" not in a for a in t.anclas)
    assert t.avisos
    e, n = t.a_utm(*PRUEBA.T)
    ve, vn = _verdad(*PRUEBA.T)
    assert np.abs(e - ve).max() < 1e-6


def test_una_sola_ancla_no_alcanza():
    with pytest.raises(ValueError):
        por_anclas(_anclas(PX[:1]))


def test_el_huso_sale_de_las_anclas():
    assert huso(-70.65, -33.45) == 32719          # Santiago
    assert huso(-72.4, -35.3) == 32718            # Constitución
    assert huso(-73.1, -41.5) == 32718            # Puerto Montt
    assert huso(-3.7, 40.4) == 32630              # hemisferio norte
    # Las anclas al oeste de 72° O caen en 18S: la similitud se ajusta en ese huso.
    b18 = complex(750000.0, 6080000.0)
    t = por_anclas(_anclas(PX[:4], epsg=32718, b=b18))
    assert t.epsg == 32718
    e, n = t.a_utm(*PRUEBA.T)
    ve, vn = _verdad(*PRUEBA.T, b=b18)
    assert np.abs(e - ve).max() < 1e-6


def test_ajuste_fino_y_json():
    t = ajuste_fino(por_anclas(_anclas(PX[:4])), 3.0, -2.0)

    e, n = t.a_utm(*PRUEBA.T)
    ve, vn = _verdad(*PRUEBA.T)
    assert np.allclose(e - ve, 3.0) and np.allclose(n - vn, -2.0)
    otra = Transformacion.desde_dict(json.loads(json.dumps(t.a_dict())))
    assert otra.ajuste == (3.0, -2.0) and otra.epsg == t.epsg
    lon, lat = otra.a_lonlat(PRUEBA[:, 0], PRUEBA[:, 1])
    lon0, lat0 = t.a_lonlat(PRUEBA[:, 0], PRUEBA[:, 1])
    assert lon.shape == (3,) and np.allclose(lon, lon0, atol=1e-12) and np.allclose(lat, lat0, atol=1e-12)
    assert -72 < lon.mean() < -66 and -50 < lat.mean() < -17


def test_foto_rectificada_la_similitud_vale_en_el_plano_enderezado():
    # Página → trabajo con perspectiva; la verdad es una similitud en px de trabajo.
    h = np.array([[1.1, 0.05, -40.0], [0.02, 0.95, 25.0], [2e-5, -1e-5, 1.0]])
    trabajo = lambda p: (np.c_[p, np.ones(len(p))] @ h.T)[:, :2] / (np.c_[p, np.ones(len(p))] @ h.T)[:, 2:]
    anclas = _anclas(trabajo(PX[:4]))
    for a, (x, y) in zip(anclas, PX[:4]):
        a["x"], a["y"] = float(x), float(y)                 # marcadas en la página

    t = por_anclas(anclas, homografia=h.tolist())

    e, n = t.a_utm(*PRUEBA.T)
    ve, vn = _verdad(*trabajo(PRUEBA).T)
    assert np.abs(e - ve).max() < 1e-6 and np.abs(n - vn).max() < 1e-6


# --- cuadrícula ----------------------------------------------------------------

# Como en Algarrobo: la hoja va de lado, las verticales llevan N y las horizontales E.
# 1,27 m/px, la hoja girada 0,4°. N crece hacia la derecha y E hacia abajo.
S_GRID, GIRO_GRID = 1.27, math.radians(0.4)
E0, N0 = 255000.0, 6306000.0


def _grid(x, y):
    """px de página → (E, N) de la cuadrícula."""
    c, s = math.cos(GIRO_GRID), math.sin(GIRO_GRID)
    u, v = c * x - s * y, s * x + c * y
    return E0 + S_GRID * v, N0 + S_GRID * u


def _inversa(e, n):
    u, v = (n - N0) / S_GRID, (e - E0) / S_GRID
    c, s = math.cos(GIRO_GRID), math.sin(GIRO_GRID)
    return c * u + s * v, -s * u + c * v


def _marcas(con_rectas=True, errores=()):
    alto, ancho = 6000.0, 4000.0
    verticales, horizontales = [], []
    for valor in np.arange(6306750.0, 6309751.0, 750.0):          # N constante
        p = _inversa(E0 + 0.0, valor)
        q = _inversa(E0 + S_GRID * alto, valor)
        verticales.append(dict(valor=valor, p=list(p), q=list(q), x=(p[0] + q[0]) / 2))
    for valor in np.arange(255750.0, 262501.0, 750.0):            # E constante
        p = _inversa(valor, N0 + 0.0)
        q = _inversa(valor, N0 + S_GRID * ancho)
        horizontales.append(dict(valor=valor, p=list(p), q=list(q), y=(p[1] + q[1]) / 2))
    for familia, i, valor in errores:
        (verticales if familia == "v" else horizontales)[i]["valor"] = valor
    if not con_rectas:
        for m in verticales + horizontales:
            m.pop("p"), m.pop("q")
    return dict(verticales=verticales, horizontales=horizontales)


ERRORES = [("v", 2, 6309250.0), ("h", 0, 256750.0), ("h", 6, 216000.0)]   # lecturas equivocadas


def test_cuadricula_con_rectas_recupera_el_giro_y_descarta_valores_malos():
    t = por_cuadricula(_marcas(errores=ERRORES))

    assert t.metodo == "cuadricula" and t.epsg == 32719
    assert t.parametros["ejes"] == {"verticales": "N", "horizontales": "E"}
    usadas = {(l["familia"], l["valor"]): l["usada"] for l in t.cuadricula["lineas"]}
    assert [k for k, v in usadas.items() if not v] == [("verticales", 6309250.0), ("horizontales", 256750.0),
                                                      ("horizontales", 216000.0)]
    pts = np.array([[200.0, 300.0], [2000.0, 3000.0], [3800.0, 5800.0]])
    e, n = t.a_utm(*pts.T)
    ve, vn = _grid(*pts.T)
    assert np.abs(e - ve).max() < 1e-6 and np.abs(n - vn).max() < 1e-6
    assert t.parametros["rms_m"] < 1e-6
    # El eje x de la página apunta casi al norte (hoja de lado), girado 0,4°.
    assert abs(t.parametros["rotacion_grados"] - 89.6) < 1e-6
    assert abs(t.parametros["cizalle_grados"]) < 1e-6
    assert abs(t.parametros["escala_x_m_px"] - S_GRID) < 1e-9
    assert any("descartadas" in a for a in t.avisos)


def test_cuadricula_con_solo_posiciones_supone_la_hoja_derecha():
    t = por_cuadricula(_marcas(con_rectas=False, errores=ERRORES[:2]))

    assert sum(not l["usada"] for l in t.cuadricula["lineas"]) == 2
    pts = np.array([[200.0, 300.0], [2000.0, 3000.0], [3800.0, 5800.0]])
    e, n = t.a_utm(*pts.T)
    ve, vn = _grid(*pts.T)
    # Sin giro medido el error crece hacia los bordes: 0,4° sobre ~3 km son ~20 m.
    assert np.hypot(e - ve, n - vn).max() < 30.0
    assert any("giro" in a for a in t.avisos)


def test_cuadricula_con_las_dos_direcciones_en_el_mismo_eje_falla():
    marcas = _marcas()
    for m in marcas["horizontales"]:
        m["valor"] += 6000000.0
    with pytest.raises(ValueError):
        por_cuadricula(marcas)


def _anclas_cuadricula(epsg_impreso):
    px = np.array([[500.0, 800.0], [3200.0, 1500.0], [1800.0, 5200.0]])
    e, n = _grid(*px.T)
    lon, lat = Transformer.from_crs(epsg_impreso, 4326, always_xy=True).transform(e, n)
    rng = np.random.default_rng(0)
    lon, lat = lon + rng.normal(0, 3e-5, 3), lat + rng.normal(0, 3e-5, 3)    # ~3 m de error de ancla
    return [dict(x=float(x), y=float(y), lon=float(lo), lat=float(la)) for (x, y), lo, la in zip(px, lon, lat)]


@pytest.mark.parametrize("epsg_impreso, datum", [(32719, "WGS84"), (24879, "PSAD56")])
def test_las_anclas_dicen_el_datum_de_la_cuadricula(epsg_impreso, datum):
    t = por_cuadricula(_marcas())

    d = comparar_datum(t, _anclas_cuadricula(epsg_impreso))

    assert d["elegido"] == epsg_impreso and d["datum"] == datum and d["concluyente"]
    assert d["candidatos"][0]["distancia_rms_m"] < 10.0
    assert d["candidatos"][1]["distancia_rms_m"] > 200.0



def test_las_anclas_dicen_el_huso_de_la_cuadricula():
    # Un predio junto a los 72° O: las anclas eligen 18S, pero la cuadrícula viene en 19S.
    t = por_cuadricula(_marcas()).con_epsg(32718)

    d = comparar_datum(t, _anclas_cuadricula(32719))

    assert d["elegido"] == 32719 and d["huso"] == "19S" and d["concluyente"]


# --- el paso completo ------------------------------------------------------------

def _carpeta(tmp_path, lotes=None, **entradas):
    lotes = lotes or [dict(numero="1", semilla=[150, 150],
                           poligono=[[100, 100], [300, 100], [300, 300], [100, 300], [100, 100]],
                           huecos=[], area_px=40000.0, vertices=4)]
    digitalizado = dict(pagina=dict(numero=1, rotacion=0, ancho=6000, alto=6000, ppmm=6.0, fuente="embebida"),
                        trabajo=dict(ancho=6000, alto=6000, ppmm=6.0, modo="recorte",
                                     homografia=[[1, 0, 0], [0, 1, 0], [0, 0, 1]]),
                        lotes=lotes, sin_numero=[], faltantes=[], cuadricula=None, estadisticas={})
    (tmp_path / "digitalizado.json").write_text(json.dumps(digitalizado), encoding="utf-8")
    (tmp_path / "entradas.json").write_text(json.dumps(dict(pdf="plano.pdf", semillas=[], **entradas)),
                                            encoding="utf-8")


def test_georreferenciar_con_anclas(tmp_path, capsys):
    _carpeta(tmp_path, anclas=_anclas(PX[:4]), ajuste=dict(de=1.5, dn=0.0))

    assert main(["georreferenciar", str(tmp_path)]) == 0

    salida = capsys.readouterr().out
    assert "Anclas: 4" in salida and "Ajuste fino" in salida
    g = json.loads((tmp_path / "georreferencia.json").read_text(encoding="utf-8"))
    assert g["metodo"] == "anclas" and g["epsg"] == 32719 and g["ajuste"] == dict(de=1.5, dn=0.0)
    assert len(g["anclas"]) == 4 and g["datum"] is None
    t = Transformacion.desde_dict(g)
    e, _ = t.a_utm(100.0, 100.0)
    assert abs(e - (_verdad(100.0, 100.0)[0] + 1.5)) < 1e-6
    mapa = json.loads((tmp_path / "lotes.geojson").read_text(encoding="utf-8"))
    assert mapa["features"][0]["properties"]["numero"] == "1"
    assert abs(mapa["features"][0]["properties"]["area_m2"] - 40000 * ESCALA ** 2) < 0.5


def test_georreferenciar_con_cuadricula_en_psad56(tmp_path, capsys):
    marcas = _marcas(con_rectas=False)
    _carpeta(tmp_path, cuadricula=marcas, anclas=_anclas_cuadricula(24879))
    # Las rectas detectadas las deja `digitalizar` en digitalizado.json.
    d = json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))
    d["cuadricula"] = _marcas()
    for m in d["cuadricula"]["verticales"] + d["cuadricula"]["horizontales"]:
        m["valida"] = True
    (tmp_path / "digitalizado.json").write_text(json.dumps(d), encoding="utf-8")

    assert main(["georreferenciar", str(tmp_path)]) == 0

    salida = capsys.readouterr().out
    assert "Cuadrícula:" in salida and "Datum PSAD56" in salida
    g = json.loads((tmp_path / "georreferencia.json").read_text(encoding="utf-8"))
    assert g["metodo"] == "cuadricula" and g["epsg"] == 24879 and g["datum"]["datum"] == "PSAD56"
    assert g["parametros"]["rms_m"] < 1e-6


def test_georreferenciar_sin_ubicacion_falla(tmp_path, capsys):
    _carpeta(tmp_path, anclas=_anclas(PX[:1]))
    assert main(["georreferenciar", str(tmp_path)]) == 1
    assert "2 puntos" in capsys.readouterr().err


def test_ancla_mal_escrita_se_avisa_con_su_nombre(tmp_path, capsys):
    _carpeta(tmp_path, anclas=[dict(nombre="roja", x=1, y=2, lon="-70")])
    assert main(["georreferenciar", str(tmp_path)]) == 1
    assert "roja" in capsys.readouterr().err


def test_digitalizar_entrega_las_rectas_de_la_cuadricula():
    import cv2
    from pipeline.plano.digitalizar import digitalizar_imagen
    from pipeline.tests.plano_sintetico import PPMM, dibujar

    plano = dibujar()
    img = plano.imagen.copy()
    alto, ancho = img.shape[:2]
    cv2.line(img, (63, 0), (67, alto - 1), (150, 150, 150), 1, cv2.LINE_AA)      # vertical, algo inclinada
    cv2.line(img, (0, 40), (ancho - 1, 40), (150, 150, 150), 1, cv2.LINE_AA)
    cuadricula = dict(verticales=[dict(x=60, valor=6306750)], horizontales=[dict(y=42, valor=255750)])

    r = digitalizar_imagen(img, PPMM, plano.semillas, cuadricula=cuadricula, avance=lambda _: None)

    [v], [h] = r.cuadricula["verticales"], r.cuadricula["horizontales"]
    assert v["valor"] == 6306750 and v["valida"]
    assert v["p"][0] == pytest.approx(63, abs=0.7) and v["q"][0] == pytest.approx(67, abs=0.7)
    assert h["valor"] == 255750 and h["p"][1] == pytest.approx(40, abs=0.7)
    json.dumps(r.cuadricula)


def test_cuadricula_en_una_sola_direccion_sin_anclas_dice_por_que(tmp_path, capsys):
    marcas = _marcas(con_rectas=False)
    marcas["horizontales"] = []
    _carpeta(tmp_path, cuadricula=marcas)
    assert main(["georreferenciar", str(tmp_path)]) == 1
    assert "en cada dirección" in capsys.readouterr().err


def test_la_cuadricula_alcanza_con_dos_lineas_de_valor_distinto_por_direccion():
    assert cuadricula_suficiente(_marcas(con_rectas=False))
    assert cuadricula_suficiente(_marcas())
    # Lo que leyó el lector en Rapel: cuatro verticales y ninguna horizontal.
    rapel = dict(verticales=[dict(x=2377.3 + 500 * i, valor=6213500 + 500 * i) for i in range(4)],
                 horizontales=[], epsg=None)
    assert not cuadricula_suficiente(rapel)
    for familia in ("verticales", "horizontales"):
        marcas = _marcas(con_rectas=False)
        marcas[familia] = marcas[familia][:1]
        assert not cuadricula_suficiente(marcas)
        with pytest.raises(ValueError, match="en cada dirección"):
            por_cuadricula(marcas)
        # Dos líneas sin valor, o con el mismo valor, tampoco dan una progresión.
        marcas = _marcas(con_rectas=False)
        marcas[familia] = [dict(m, valor=marcas[familia][0]["valor"]) for m in marcas[familia]]
        assert not cuadricula_suficiente(marcas)
        marcas[familia] = [{k: v for k, v in m.items() if k != "valor"} for m in marcas[familia]]
        assert not cuadricula_suficiente(marcas)
    assert not cuadricula_suficiente(None) and not cuadricula_suficiente({})


def test_epsg_de_la_cuadricula_que_no_es_utm_falla(tmp_path, capsys):
    _carpeta(tmp_path, cuadricula=dict(_marcas(con_rectas=False), epsg=4326))
    assert main(["georreferenciar", str(tmp_path)]) == 1
    assert "4326" in capsys.readouterr().err


def _lotes_con_cuadro(area_oficial):
    """4 lotes de 200 × 200 px (2.500 m² a ESCALA) con su área del cuadro."""
    lotes = []
    for i in range(4):
        x = 100 + 200 * i
        lotes.append(dict(numero=str(i + 1), semilla=[x + 100, 200], area_px=40000.0, vertices=4, huecos=[],
                          poligono=[[x, 100], [x + 200, 100], [x + 200, 300], [x, 300], [x, 100]],
                          area_oficial=area_oficial))
    return lotes


def test_la_escala_de_las_anclas_contra_el_cuadro_de_superficies_se_avisa(tmp_path, capsys):
    # El cuadro dice 2.500 / 0,97² m²: las anclas dan una escala 3 % menor que la del plano.
    _carpeta(tmp_path, lotes=_lotes_con_cuadro(2500 / 0.97 ** 2), anclas=_anclas(PX[:4]))
    assert main(["georreferenciar", str(tmp_path)]) == 0
    g = json.loads((tmp_path / "georreferencia.json").read_text(encoding="utf-8"))
    assert g["parametros"]["escala_cuadro"] == dict(lotes=4, area_pct=-5.91, escala_pct=-3.0)
    aviso = [a for a in g["avisos"] if "cuadro de superficies" in a]
    # Lo que la loteadora ve en Revisar: los lotes más chicos que lo oficial, y qué revisar.
    assert aviso and aviso[0].startswith("Los lotes salen un 5,9 % más chicos que en el cuadro de superficies")
    assert "un 3,0 % más cortos" in aviso[0] and "Revisa los puntos" in aviso[0]
    assert not any(t in aviso[0] for t in ("ancla", "escala", "mediana"))


def test_los_lotes_mas_grandes_que_el_cuadro_se_dicen_mas_grandes(tmp_path, capsys):
    # El cuadro dice menos que lo medido: los puntos estiran el plano.
    _carpeta(tmp_path, lotes=_lotes_con_cuadro(2500 / 1.04 ** 2), anclas=_anclas(PX[:4]))
    assert main(["georreferenciar", str(tmp_path)]) == 0
    g = json.loads((tmp_path / "georreferencia.json").read_text(encoding="utf-8"))
    assert g["parametros"]["escala_cuadro"]["escala_pct"] > 0
    aviso = [a for a in g["avisos"] if "cuadro de superficies" in a]
    assert aviso and "% más grandes" in aviso[0] and "% más largos" in aviso[0]


def test_la_escala_que_calza_con_el_cuadro_no_se_avisa(tmp_path, capsys):
    # +1 % de área (0,5 % de escala) es el error del digitalizado, no de la ubicación.
    _carpeta(tmp_path, lotes=_lotes_con_cuadro(2500 / 1.01), anclas=_anclas(PX[:4]))
    assert main(["georreferenciar", str(tmp_path)]) == 0
    g = json.loads((tmp_path / "georreferencia.json").read_text(encoding="utf-8"))
    assert g["parametros"]["escala_cuadro"]["lotes"] == 4
    assert not [a for a in g["avisos"] if "cuadro de superficies" in a]


def test_sin_cuadro_no_se_mide_la_escala(tmp_path, capsys):
    _carpeta(tmp_path, anclas=_anclas(PX[:4]))
    assert main(["georreferenciar", str(tmp_path)]) == 0
    g = json.loads((tmp_path / "georreferencia.json").read_text(encoding="utf-8"))
    assert "escala_cuadro" not in g["parametros"]


def _plano_con_cuadricula(tmp_path, giro=0.4):
    """El plano sintético con una cuadrícula UTM gris impresa en los márgenes, girada
    `giro` grados (la hoja escaneada algo torcida), y lo que "lee" el lector de ella."""
    import io

    import cv2
    import pymupdf
    from PIL import Image

    from pipeline.tests.plano_sintetico import PPMM, dibujar

    plano = dibujar()
    img = plano.imagen.copy()
    alto, ancho = img.shape[:2]
    c, s = math.cos(math.radians(giro)), math.sin(math.radians(giro))
    # u, v: la página girada; E = E0 + u/2, N = N0 − v/2.
    e0, n0 = 280000.0, 6290000.0
    verdad = lambda x, y: (e0 + 0.5 * (x * c + y * s), n0 - 0.5 * (-x * s + y * c))
    a16 = lambda p: (int(round(p[0] * 16)), int(round(p[1] * 16)))
    propuesta = dict(verticales=[], horizontales=[], epsg=None)
    for u in (60.0, 1500.0):                    # verticales: u constante, en los márgenes
        x_en = lambda y: (u - y * s) / c
        cv2.line(img, a16((x_en(0), 0)), a16((x_en(alto - 1), alto - 1)), (150, 150, 150), 1, cv2.LINE_AA, 4)
        propuesta["verticales"].append(dict(x=round(x_en(alto / 2), 1), valor=e0 + 0.5 * u))
    for v in (60.0, 990.0):                     # horizontales: v constante
        y_en = lambda x: (v + x * s) / c
        cv2.line(img, a16((0, y_en(0))), a16((ancho - 1, y_en(ancho - 1))), (150, 150, 150), 1, cv2.LINE_AA, 4)
        propuesta["horizontales"].append(dict(y=round(y_en(ancho / 2), 1), valor=n0 - 0.5 * v))
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "JPEG", quality=95)
    doc = pymupdf.open()
    hoja = doc.new_page(width=ancho / PPMM / 25.4 * 72, height=alto / PPMM / 25.4 * 72)
    hoja.insert_image(hoja.rect, stream=buf.getvalue())
    doc.save(tmp_path / "plano.pdf")
    entradas = dict(pdf="plano.pdf", pagina=1, rotacion=0, rectangulo=[100, 100, ancho - 100, alto - 100],
                    mascaras=[], esquinas=None, marco_mm=None, cuadricula=None, lector=True,
                    semillas=[dict(numero=n, x=x, y=y) for n, x, y in plano.semillas], anclas=[])
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    return entradas, propuesta, verdad


def _lector_que_propone(monkeypatch, propuesta):
    from pipeline.plano import rotulos

    monkeypatch.setattr(rotulos, "motivo_no_disponible", lambda: None)
    monkeypatch.setattr(rotulos, "leer", lambda imagen, ppmm, avance: [])
    monkeypatch.setattr(rotulos, "leer_cuadricula", lambda imagen, ppmm, avance, rectangulo: propuesta)
    monkeypatch.setattr(rotulos, "leer_cuadro", lambda imagen, rects, avance: {})


def test_ubicar_con_la_propuesta_sin_digitalizar_de_nuevo_mide_el_giro(tmp_path, monkeypatch, capsys):
    """La loteadora digitaliza sin cuadrícula y elige la que propone el lector recién en
    Ubicar: ubicar usa las rectas detectadas de esa propuesta (mide el giro), sin que
    digitalizar haya borrado su tinta."""
    entradas, propuesta, verdad = _plano_con_cuadricula(tmp_path)
    sin_propuesta = tmp_path / "sin_propuesta"
    sin_propuesta.mkdir()
    _plano_con_cuadricula(sin_propuesta)
    _lector_que_propone(monkeypatch, None)
    assert main(["digitalizar", str(sin_propuesta)]) == 0
    _lector_que_propone(monkeypatch, propuesta)

    assert main(["digitalizar", str(tmp_path)]) == 0

    d = json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))
    assert d["lector"]["cuadricula"] == propuesta
    assert [m["x"] for m in d["cuadricula"]["verticales"]] == [m["x"] for m in propuesta["verticales"]]
    assert all(m["valida"] for f in ("verticales", "horizontales") for m in d["cuadricula"][f])
    # Los lotes son los mismos que sin la propuesta: su tinta no se borró.
    otro = json.loads((sin_propuesta / "digitalizado.json").read_text(encoding="utf-8"))
    assert otro["cuadricula"] is None
    assert d["lotes"] == otro["lotes"] and d["sin_numero"] == otro["sin_numero"]

    # Elige la propuesta (como la manda el navegador) y ubica, sin digitalizar de nuevo.
    (tmp_path / "entradas.json").write_text(json.dumps(dict(entradas, cuadricula=propuesta)), encoding="utf-8")
    capsys.readouterr()
    assert main(["georreferenciar", str(tmp_path)]) == 0

    g = json.loads((tmp_path / "georreferencia.json").read_text(encoding="utf-8"))
    assert g["metodo"] == "cuadricula"
    assert not any("Sin las líneas detectadas" in a or "cambiaron" in a for a in g["avisos"])
    assert abs(abs(g["parametros"]["rotacion_grados"]) - 0.4) < 0.05
    t = Transformacion.desde_dict(g)
    for x, y in ((0, 0), (1560, 0), (1560, 1026), (0, 1026)):
        e, n = t.a_utm(float(x), float(y))
        assert math.hypot(e - verdad(x, y)[0], n - verdad(x, y)[1]) < 1.0


def test_otra_cuadricula_que_la_detectada_no_usa_sus_rectas(tmp_path, monkeypatch):
    """Las rectas guardadas son de la propuesta: si la elegida tiene otras líneas (aunque
    sean tantas como ellas), no se usan, y se dice que hay que leer el plano de nuevo."""
    entradas, propuesta, _ = _plano_con_cuadricula(tmp_path)
    _lector_que_propone(monkeypatch, propuesta)
    assert main(["digitalizar", str(tmp_path)]) == 0
    corrida = dict(propuesta, verticales=[dict(propuesta["verticales"][0], x=200.0), propuesta["verticales"][1]])
    (tmp_path / "entradas.json").write_text(json.dumps(dict(entradas, cuadricula=corrida)), encoding="utf-8")

    assert main(["georreferenciar", str(tmp_path)]) == 0

    g = json.loads((tmp_path / "georreferencia.json").read_text(encoding="utf-8"))
    assert any("cambiaron desde la última lectura" in a for a in g["avisos"])
