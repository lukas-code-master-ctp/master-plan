"""Modelo de elevación: teselas Terrarium decodificadas y muestreadas."""
import io

import numpy as np
import pytest
from PIL import Image

from pipeline.proyeccion import Vista
from pipeline.terreno import LADO, Terreno, a_pixel_global, cargar, decodificar, modelo_para_vista


def png_terrarium(cota: float, lado: int = LADO) -> bytes:
    """Una tesela plana a la cota pedida, codificada como la sirve AWS."""
    valor = cota + 32768
    r, resto = divmod(valor, 256)
    g, fraccion = divmod(resto, 1)
    imagen = Image.new("RGB", (lado, lado), (int(r), int(g), int(round(fraccion * 256))))
    salida = io.BytesIO()
    imagen.save(salida, "PNG")
    return salida.getvalue()


def test_decodifica_la_formula_terrarium():
    cotas = decodificar(png_terrarium(260.5))

    assert cotas.shape == (LADO, LADO)
    assert cotas[0, 0] == pytest.approx(260.5, abs=1e-6)


def test_la_tesela_de_una_coordenada_conocida():
    """p02 de Praderas de Cauquenes cae en la tesela 14/4902/9942."""
    x, y = a_pixel_global((-72.273131439, -35.864468873), zoom=14)

    assert (int(x // LADO), int(y // LADO)) == (4902, 9942)


def test_la_cota_interpola_entre_pixeles():
    # Un mosaico de 2 × 2 píxeles con una rampa de 100 a 130 m de oeste a este.
    cotas = np.array([[100.0, 130.0], [100.0, 130.0]])
    terreno = Terreno(zoom=14, x0=0, y0=0, cotas=cotas)
    # Puntos a mitad de camino entre los centros de los dos píxeles, en la fila 0.
    def punto_en_pixel(px, py):
        n = 2 ** 14 * LADO
        lon = px / n * 360 - 180
        import math
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * py / n))))
        return (lon, lat)

    assert terreno.cota(punto_en_pixel(0.5, 0.5)) == pytest.approx(100.0, abs=0.01)
    assert terreno.cota(punto_en_pixel(1.0, 0.5)) == pytest.approx(115.0, abs=0.01)
    assert terreno.cota(punto_en_pixel(1.5, 0.5)) == pytest.approx(130.0, abs=0.01)


def test_cargar_baja_las_teselas_que_cubren_la_caja_y_las_cachea(tmp_path):
    descargas = []

    def descarga_falsa(url):
        descargas.append(url)
        return png_terrarium(250.0)

    caja = (-72.2760, -35.8680, -72.2705, -35.8530)   # el loteo, ~500 × 1600 m
    terreno = cargar(caja, tmp_path, descarga=descarga_falsa)

    assert terreno.cotas.shape[0] >= LADO and terreno.cotas.shape[1] >= LADO
    assert len(descargas) >= 1
    assert all("terrarium/14/" in url for url in descargas)
    assert terreno.cota((-72.2730, -35.8600)) == pytest.approx(250.0, abs=1e-6)

    # La segunda vez no baja nada: las teselas quedaron en disco.
    de_nuevo = cargar(caja, tmp_path, descarga=lambda url: (_ for _ in ()).throw(AssertionError(url)))
    assert de_nuevo.cotas.shape == terreno.cotas.shape


def test_el_modelo_ancla_la_cota_del_despegue_al_datum_del_dron():
    """El dron mide alturas respecto del despegue. El DEM solo aporta los desniveles."""
    cotas = np.full((2, 2), 250.0)
    cotas[:, 1] = 270.0
    terreno = Terreno(zoom=14, x0=0, y0=0, cotas=cotas)
    vista = Vista(id="p01-100", posicion=1, lon=-72.0, lat=-35.0,
                  altura_relativa=100.0, altura_absoluta=380.0, rumbo0=0.0)
    n = 2 ** 14 * LADO
    despegue = (0.5 / n * 360 - 180, 89.99)     # píxel oeste (cota 250)
    lejos = (1.5 / n * 360 - 180, 89.99)        # píxel este (cota 270)

    modelo = modelo_para_vista(terreno, vista, despegue)

    assert modelo(despegue) == pytest.approx(vista.terreno_plano())
    assert modelo(lejos) == pytest.approx(vista.terreno_plano() + 20.0)
