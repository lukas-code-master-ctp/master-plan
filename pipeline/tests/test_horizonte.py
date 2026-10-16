"""Nivelación contra el horizonte: el perfil del DEM tiene que caer sobre el borde cielo-tierra."""
import io

import numpy as np
import pytest
from PIL import Image

from pipeline import horizonte
from pipeline.calibracion import _proyectar
from pipeline.horizonte import Perfil, nivelar, nivelar_por_desnivel, perfil

RUMBO0 = 37.0
ANCHO = 3600


def perfil_de_cerros() -> Perfil:
    """Cerros cercanos al oeste y una cordillera lejana al este, como en Quillón."""
    azimut = np.arange(0.0, 360.0, horizonte.PASO_AZIMUT)
    elevacion = (0.6 * np.sin(np.radians(azimut * 3)) + 0.4 * np.sin(np.radians(azimut * 7 + 20))
                 + 1.5 * np.exp(-((azimut - 290) / 25) ** 2))
    return Perfil(azimut=azimut, elevacion=elevacion, distancia=np.full(len(azimut), 20000.0))


def foto_con_horizonte(horizonte_dem: Perfil, este: float, norte: float) -> np.ndarray:
    """Cielo azul sobre el horizonte, tierra verde bajo él, con la foto inclinada."""
    alto = ANCHO // 2
    az, el = _proyectar(np.radians(horizonte_dem.azimut), -np.tan(np.radians(horizonte_dem.elevacion)),
                        np.ones(len(horizonte_dem.azimut)), 0.0, este, norte)
    columnas = ((np.arange(ANCHO) + 0.5) / ANCHO * 360.0 + RUMBO0) % 360.0
    orden = np.argsort(az)
    borde = np.interp(columnas, az[orden], el[orden], period=360.0)
    filas = (90.0 - (np.arange(alto) + 0.5) / alto * 180.0)[:, None]
    cielo = filas > borde[None, :]
    rgb = np.empty((alto, ANCHO, 3), dtype=np.uint8)
    rgb[cielo] = (120, 170, 230)
    rgb[~cielo] = (60, 90, 50)
    return rgb


def test_recupera_una_inclinacion_conocida():
    dem = perfil_de_cerros()

    nivel = nivelar(foto_con_horizonte(dem, 0.6, 1.2), dem, RUMBO0)

    assert nivel.aplicada
    assert nivel.inclinacion_este == pytest.approx(0.6, abs=0.08)
    assert nivel.inclinacion_norte == pytest.approx(1.2, abs=0.08)
    assert nivel.residuo < 0.1


def test_una_foto_derecha_queda_derecha():
    dem = perfil_de_cerros()

    nivel = nivelar(foto_con_horizonte(dem, 0.0, 0.0), dem, RUMBO0)

    assert abs(nivel.inclinacion_este) < 0.08 and abs(nivel.inclinacion_norte) < 0.08


def test_sin_horizonte_visible_no_nivela():
    """Una foto toda nublada: no hay borde cielo-tierra y no se inventa uno."""
    gris = np.full((ANCHO // 2, ANCHO, 3), 200, dtype=np.uint8)

    nivel = nivelar(gris, perfil_de_cerros(), RUMBO0)

    assert not nivel.aplicada
    assert "horizonte" in nivel.motivo


def test_un_horizonte_cercano_no_cuenta():
    """A 500 m el horizonte son árboles y casas, que el DEM no tiene."""
    dem = perfil_de_cerros()
    cerca = Perfil(dem.azimut, dem.elevacion, np.full(len(dem.azimut), 500.0))

    nivel = nivelar(foto_con_horizonte(dem, 0.6, 1.2), cerca, RUMBO0)

    assert not nivel.aplicada
    assert "lejano" in nivel.motivo


def png_terrarium(cota: float) -> bytes:
    valor = cota + 32768
    r, resto = divmod(valor, 256)
    g, fraccion = divmod(resto, 1)
    salida = io.BytesIO()
    Image.new("RGB", (256, 256), (int(r), int(g), int(round(fraccion * 256)))).save(salida, "PNG")
    return salida.getvalue()


def test_el_perfil_de_un_terreno_plano_es_el_horizonte_geometrico(tmp_path):
    """Sobre una llanura a cota 0, desde 500 m el horizonte cae ~0,7° bajo la horizontal."""
    pedidas = []

    def descarga(url):
        pedidas.append(url)
        return png_terrarium(0.0)

    anillos = ((10, 150.0, 15000.0, 300.0), (8, 15000.0, 120000.0, 2000.0))
    resultado = perfil(-72.0, -36.0, 500.0, tmp_path, descarga=descarga, anillos=anillos)

    assert pedidas
    assert len(resultado.azimut) == 360 / horizonte.PASO_AZIMUT
    # El horizonte de una esfera con refracción: la curvatura le gana a la altura.
    assert np.all(resultado.elevacion < -0.4) and np.all(resultado.elevacion > -0.9)
    assert np.all(resultado.distancia > 50000)


def test_bajar_el_perfil_sube_los_cerros():
    """Desde 50 m más abajo, un cerro a 5 km se ve 0,57° más alto."""
    llano = Perfil(np.array([0.0, 90.0]), np.array([0.0, -1.0]), np.array([5000.0, 5000.0]))

    bajado = llano.bajado(50.0)

    assert bajado.elevacion[0] == pytest.approx(np.degrees(np.arctan(50 / 5000)), abs=1e-6)
    assert bajado.elevacion[1] > -1.0


def test_nivela_para_cada_desnivel():
    """La inclinación que calza depende de la altura supuesta: con el dron 40 m más
    abajo, el horizonte de la foto pide otra."""
    dem = perfil_de_cerros()
    foto = foto_con_horizonte(dem.bajado(40.0), 0.6, 1.2)

    niveles = nivelar_por_desnivel(foto, dem, RUMBO0, [-20.0, 20.0, 40.0])

    assert sorted(niveles) == [-20.0, 0.0, 20.0, 40.0]
    assert niveles[40.0].inclinacion_este == pytest.approx(0.6, abs=0.08)
    assert niveles[40.0].inclinacion_norte == pytest.approx(1.2, abs=0.08)
    assert niveles[0.0].aplicada
