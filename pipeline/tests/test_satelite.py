"""Calzar una vista contra la imagen satelital: el verdor de la foto, puesto sobre el
suelo, tiene que coincidir con el del satélite."""
import json
import struct
import zlib
from datetime import date

import cv2
import numpy as np
import pytest
from pyproj import Transformer

from pipeline import geo, satelite
from pipeline.proyeccion import Vista

# Sobre el meridiano central del huso 19, donde el norte de la grilla es el norte.
LON, LAT = -69.0, -36.0
PASO_M = 10.0
LADO_M = 4000.0
ALTURA = 500.0


def _suelo() -> np.ndarray:
    """Manchas de 50 a 200 m: bosque, pradera y potreros a la escala de Sentinel."""
    lado = int(LADO_M / PASO_M)
    capas = [cv2.resize(np.random.default_rng(semilla).random((lado // celda, lado // celda))
                        .astype(np.float32), (lado, lado), interpolation=cv2.INTER_CUBIC)
             for semilla, celda in ((3, 20), (4, 6))]
    return 0.6 * capas[0] + 0.4 * capas[1]


def _verdor(suelo: np.ndarray) -> satelite.Verdor:
    este, norte = satelite.a_utm(np.array([LON]), np.array([LAT]), 19, True)
    return satelite.Verdor(suelo, float(este[0]) - LADO_M / 2, float(norte[0]) + LADO_M / 2, PASO_M, 19, True)


def _foto(suelo: np.ndarray, desnivel: float, giro: float, ancho: int = 1800) -> np.ndarray:
    """Lo que vería el dron sobre suelo plano si el suelo estuviera `desnivel` metros
    más arriba y la foto girada `giro` grados."""
    alto = ancho // 2
    az, el = np.meshgrid(20.0 + (np.arange(ancho) + 0.5) / ancho * 360.0,
                         90.0 - (np.arange(alto) + 0.5) / alto * 180.0)
    az = np.radians(az + giro)
    debajo = el < -2.0
    distancia = np.where(debajo, (ALTURA - desnivel) / np.tan(np.radians(-np.minimum(el, -2.0))), 0.0)
    px = ((distancia * np.sin(az) + LADO_M / 2) / PASO_M - 0.5).astype(np.float32)
    py = ((LADO_M / 2 - distancia * np.cos(az)) / PASO_M - 0.5).astype(np.float32)
    foto = cv2.remap(suelo, px, py, cv2.INTER_LINEAR, borderValue=0.5)
    foto[~debajo] = 0.5
    return foto


def _vista(**pose) -> Vista:
    return Vista("p01-500", 1, LON, LAT, ALTURA, ALTURA, 20.0, **pose)


def _sin_relieve(lon, lat):
    return np.zeros_like(np.asarray(lon, dtype=np.float64))


def test_encuentra_la_altura_y_el_giro_que_calzan_con_el_satelite():
    """Parque Algarrobo: el dron estaba 18 m más abajo de lo que decía y la foto 2°
    girada; con los caminos la búsqueda se iba al tope."""
    suelo = _suelo()
    ajuste = satelite.calibrar(_vista(), _foto(suelo, desnivel=18.0, giro=-2.0), ALTURA,
                               _sin_relieve, _verdor(suelo))

    assert ajuste.desnivel == pytest.approx(18.0, abs=3.0)
    assert ajuste.giro == pytest.approx(-2.0, abs=0.15)
    assert abs(ajuste.inclinacion_este) < 0.2 and abs(ajuste.inclinacion_norte) < 0.2
    assert ajuste.puntaje_despues > 0.9 > ajuste.puntaje_antes


def test_quita_la_inclinacion_que_la_foto_no_tiene():
    """El horizonte con bruma le dio a la vista 2,8° de inclinación que no tenía."""
    suelo = _suelo()
    ajuste = satelite.calibrar(_vista(inclinacion_este=1.1, inclinacion_norte=2.8),
                               _foto(suelo, desnivel=0.0, giro=0.0), ALTURA, _sin_relieve, _verdor(suelo))

    assert ajuste.inclinacion_este == pytest.approx(-1.1, abs=0.2)
    assert ajuste.inclinacion_norte == pytest.approx(-2.8, abs=0.2)
    assert ajuste.desnivel == pytest.approx(0.0, abs=3.0)


def test_una_foto_que_no_se_parece_al_satelite_queda_como_estaba():
    suelo = _suelo()
    otro = np.random.default_rng(9).random(suelo.shape).astype(np.float32)
    ajuste = satelite.calibrar(_vista(), _foto(suelo, 0.0, 0.0), ALTURA, _sin_relieve, _verdor(otro))

    assert not ajuste.aplicado


def test_una_vista_que_ya_calza_no_se_toca():
    suelo = _suelo()
    ajuste = satelite.calibrar(_vista(), _foto(suelo, 0.0, 0.0), ALTURA, _sin_relieve, _verdor(suelo))

    assert not ajuste.aplicado
    assert ajuste.puntaje_antes > 0.9


@pytest.mark.parametrize("lon, lat, cuadro", [
    (-71.597, -33.350, "19HBD"),     # Parque Algarrobo
    (-70.650, -33.450, "19HCC"),     # Santiago
    (-73.050, -36.830, "18HXE"),     # Concepción
    (2.350, 48.850, "31UDQ"),        # París: hemisferio norte y huso impar
])
def test_nombra_el_cuadro_de_sentinel(lon, lat, cuadro):
    assert satelite.cuadro_mgrs(lon, lat) == cuadro


def test_pasa_a_utm_como_proj():
    lon, lat = np.array([-71.597, -72.9, -68.2]), np.array([-33.35, -41.4, -18.5])
    este, norte = satelite.a_utm(lon, lat, 19, True)
    esperado = Transformer.from_crs(4326, 32719, always_xy=True).transform(lon, lat)

    assert este == pytest.approx(esperado[0], abs=0.01)
    assert norte == pytest.approx(esperado[1], abs=0.01)


# --- leer un trozo de un GeoTIFF en teselas -------------------------------------

def _tif(imagen: np.ndarray, lado: int) -> bytes:
    """Un TIFF en teselas con deflate y predictor horizontal, como los de Sentinel."""
    alto, ancho = imagen.shape
    teselas = []
    for y in range(0, alto, lado):
        for x in range(0, ancho, lado):
            tesela = np.zeros((lado, lado), dtype="<u2")
            trozo = imagen[y:y + lado, x:x + lado]
            tesela[:trozo.shape[0], :trozo.shape[1]] = trozo
            tesela[:, 1:] = tesela[:, 1:] - tesela[:, :-1]
            teselas.append(zlib.compress(tesela.tobytes()))
    etiquetas = [(256, 3, 1, ancho), (257, 3, 1, alto), (258, 3, 1, 16), (259, 3, 1, 8),
                 (317, 3, 1, 2), (322, 3, 1, lado), (323, 3, 1, lado)]
    inicio_datos = 8 + 2 + 12 * (len(etiquetas) + 2) + 4
    tabla = inicio_datos + 8 * len(teselas)
    desde, cursor = [], tabla
    for tesela in teselas:
        desde.append(cursor)
        cursor += len(tesela)
    if len(teselas) == 1:       # un solo valor va dentro de la etiqueta, no aparte
        etiquetas += [(324, 4, 1, desde[0]), (325, 4, 1, len(teselas[0]))]
    else:
        etiquetas += [(324, 4, len(teselas), inicio_datos),
                      (325, 4, len(teselas), inicio_datos + 4 * len(teselas))]
    cabecera = b"II*\x00" + struct.pack("<I", 8) + struct.pack("<H", len(etiquetas))
    for etiqueta, tipo, cuenta, valor in etiquetas:
        cabecera += struct.pack("<HHI", etiqueta, tipo, cuenta)
        cabecera += struct.pack("<HH", valor, 0) if tipo == 3 else struct.pack("<I", valor)
    cabecera += struct.pack("<I", 0)
    return (cabecera + struct.pack(f"<{len(teselas)}I", *desde)
            + struct.pack(f"<{len(teselas)}I", *map(len, teselas)) + b"".join(teselas))


def test_lee_un_trozo_que_cruza_teselas_pidiendo_solo_esas():
    imagen = np.random.default_rng(1).integers(0, 60000, (100, 120)).astype("<u2")
    archivo = _tif(imagen, lado=32)
    pedidos = []

    def descarga(ruta, rango):
        pedidos.append(rango)
        return archivo[rango[0]:rango[1] + 1]

    # Píxeles de 10 m, con la esquina noroeste en (500000, 6000000).
    trozo, este0, norte0, paso = satelite._recorte("B04.tif", [10.0, 0, 500000.0, 0, -10.0, 6000000.0],
                                                   (500250.0, 5999400.0, 500700.0, 5999800.0), descarga)

    assert (este0, norte0, paso) == (500250.0, 5999800.0, 10.0)
    assert np.array_equal(trozo, imagen[20:60, 25:70])
    assert len(pedidos) == 1 + 2 * 3      # la cabecera y las 6 teselas que toca


def test_elige_la_imagen_despejada_mas_cercana_al_vuelo(tmp_path):
    rojo = np.full((64, 64), 1000, dtype="<u2")
    infrarrojo = np.full((64, 64), 3000, dtype="<u2")
    despejado, nublado = np.full((32, 32), 4, dtype="<u2"), np.full((32, 32), 9, dtype="<u2")
    este, norte = satelite.a_utm(np.array([LON]), np.array([LAT]), 19, True)
    esquina = (float(este[0]) - 300.0, float(norte[0]) + 300.0)
    cuadro = satelite.cuadro_mgrs(LON, LAT)
    carpeta = f"{satelite.PREFIJO}/19/{cuadro[2]}/{cuadro[3:]}/2026"
    cerca, lejos = f"{carpeta}/10/S2B_{cuadro}_20261027_0_L2A", f"{carpeta}/10/S2B_{cuadro}_20261014_0_L2A"
    archivos = {f"{cerca}/SCL.tif": _tif(nublado, 32), f"{lejos}/SCL.tif": _tif(despejado, 32),
                f"{lejos}/B04.tif": _tif(rojo, 32), f"{lejos}/B08.tif": _tif(infrarrojo, 32)}

    def ficha(paso):
        return {"proj:transform": [paso, 0, esquina[0], 0, -paso, esquina[1]]}

    def descarga(ruta, rango):
        if ruta.startswith("?"):
            if ruta.endswith("/2026/10/"):
                return "".join(f"<Prefix>{e}/</Prefix>" for e in (cerca, lejos)).encode()
            return b""
        if ruta.endswith(".json"):
            return json.dumps({"properties": {"eo:cloud_cover": 5.0},
                               "assets": {"scl": ficha(20.0), "red": ficha(10.0), "nir": ficha(10.0)}}).encode()
        return archivos[ruta][rango[0]:rango[1] + 1]

    caja = (LON - 0.0005, LAT - 0.0005, LON + 0.0005, LAT + 0.0005)
    verdor = satelite.cargar(caja, date(2026, 10, 28), tmp_path, margen_m=100.0, descarga=descarga)

    assert verdor.escena.endswith("20261014_0_L2A")
    assert verdor.en(np.array([LON]), np.array([LAT]))[0] == pytest.approx(0.5, abs=0.01)
    # La segunda vez sale del caché, sin red.
    otra = satelite.cargar(caja, date(2026, 10, 28), tmp_path, margen_m=100.0, descarga=lambda *a: 1 / 0)
    assert otra.escena == verdor.escena


def test_sin_imagen_despejada_lo_dice(tmp_path):
    with pytest.raises(ValueError, match="no hay imagen satelital despejada"):
        satelite.cargar((LON, LAT, LON, LAT), date(2026, 10, 28), tmp_path, descarga=lambda ruta, rango: b"")
