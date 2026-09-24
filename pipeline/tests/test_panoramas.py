from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from pipeline.panoramas import (
    Panorama,
    RumboResuelto,
    _numero_de_posicion,
    a_vista,
    asignar_posiciones,
    buscar_panoramas,
    leer_panorama,
    resolver_rumbo,
)
from pipeline.solar import DiscoSolar, posicion_solar

XMP_PLANTILLA = """<?xpacket begin=""?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF
 xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
 <rdf:Description rdf:about=""
   xmlns:drone-dji="http://www.uav.com/drone-dji/1.0/"
   xmlns:GPano="http://ns.google.com/photos/1.0/panorama/"
   xmlns:xmp="http://ns.adobe.com/xap/1.0/"
   xmp:CreateDate="{momento}"
   drone-dji:GpsLatitude="{lat}"
   drone-dji:GpsLongitude="{lon}"
   drone-dji:AbsoluteAltitude="{absoluta}"
   drone-dji:RelativeAltitude="{relativa}"
   drone-dji:GimbalYawDegree="{gimbal}"
   GPano:ProjectionType="equirectangular"/>
 </rdf:RDF></x:xmpmeta><?xpacket end="w"?>"""


def escribir_panorama(ruta, *, lat=-34.7969, lon=-72.0025, relativa=100.281,
                      absoluta=185.170, momento="2026-03-05T19:05:15-03:00",
                      gimbal=67.7, ancho=720, sol_x=None, sol_elevacion=None):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    alto = ancho // 2
    lienzo = np.full((alto, ancho), 110, dtype=np.uint8)
    if sol_x is not None:
        y = int((90 - sol_elevacion) / 180 * alto)
        ys, xs = np.mgrid[0:alto, 0:ancho]
        dx = np.minimum(np.abs(xs - sol_x), ancho - np.abs(xs - sol_x))
        lienzo[(dx ** 2 + (ys - y) ** 2) < 36] = 255
    imagen = Image.fromarray(lienzo).convert("RGB")
    xmp = XMP_PLANTILLA.format(lat=lat, lon=lon, relativa=relativa,
                               absoluta=absoluta, momento=momento, gimbal=gimbal)
    imagen.save(ruta, "JPEG", xmp=xmp.encode("utf-8"), quality=95)
    return ruta


# --- lectura -----------------------------------------------------------------

def test_lee_la_pose_desde_el_xmp(tmp_path):
    ruta = escribir_panorama(tmp_path / "POSICION 03" / "50 METROS.JPG")

    panorama = leer_panorama(ruta)

    assert panorama.lat == pytest.approx(-34.7969)
    assert panorama.lon == pytest.approx(-72.0025)
    assert panorama.altura_relativa == pytest.approx(100.281)
    assert panorama.altura_absoluta == pytest.approx(185.170)
    assert panorama.gimbal_yaw == pytest.approx(67.7)


def test_la_altura_sale_del_xmp_y_no_del_nombre_del_archivo(tmp_path):
    """Las fotos de POSICION 03 vienen mal rotuladas: el archivo dice 50 m y son 100."""
    ruta = escribir_panorama(tmp_path / "POSICION 03" / "50 METROS.JPG", relativa=100.281)

    panorama = leer_panorama(ruta)

    assert panorama.altura_nominal == 100
    assert panorama.id == "p03-100"


@pytest.mark.parametrize("relativa,esperada", [
    (49.275, 50), (100.094, 100), (299.893, 300), (499.723, 500),
    # Alturas que no estaban en el plan de vuelo del primer proyecto: antes se
    # aplastaban contra (50, 100, 300, 500) y 117 se rotulaba como 100.
    (117.332, 120), (118.674, 120), (226.399, 230),
])
def test_la_altura_nominal_redondea_a_la_decena(tmp_path, relativa, esperada):
    ruta = escribir_panorama(tmp_path / "POSICION 01" / "foto.JPG", relativa=relativa)
    assert leer_panorama(ruta).altura_nominal == esperada


def test_una_imagen_sin_xmp_no_es_panorama(tmp_path):
    ruta = tmp_path / "simple.jpg"
    Image.new("RGB", (100, 50)).save(ruta)

    assert leer_panorama(ruta) is None


def test_un_xmp_incompleto_avisa_con_el_nombre_del_archivo(tmp_path):
    ruta = tmp_path / "rota.jpg"
    xmp = '<x:xmpmeta xmlns:x="adobe:ns:meta/">equirectangular</x:xmpmeta>'
    Image.new("RGB", (100, 50)).save(ruta, "JPEG", xmp=xmp.encode())

    with pytest.raises(ValueError, match="rota.jpg"):
        leer_panorama(ruta)


@pytest.mark.parametrize("carpeta,esperado", [
    ("POSICION 01", 1), ("POSICION 04", 4), ("Posición 12", 12), ("otra", 0),
])
def test_deduce_el_numero_de_posicion_de_la_carpeta(carpeta, esperado):
    assert _numero_de_posicion(Path(carpeta) / "foto.JPG") == esperado


def test_busca_panoramas_ordenadas_e_ignora_las_referencias(tmp_path):
    # Otra posición es otro punto de despegue: cambia el GPS, no solo la carpeta.
    escribir_panorama(tmp_path / "POSICION 02" / "100 METROS.JPG", relativa=100.0, lon=-71.9970)
    escribir_panorama(tmp_path / "POSICION 01" / "300 METROS.JPG", relativa=300.0)
    escribir_panorama(tmp_path / "POSICION 01" / "100 METROS.JPG", relativa=100.0)
    Image.new("RGB", (60, 30)).save(tmp_path / "POSICION 01" / "REFERENCIA (73, 80).jpg")

    encontradas = buscar_panoramas(tmp_path)

    assert [p.id for p in encontradas] == ["p01-100", "p01-300", "p02-100"]


# --- rumbo -------------------------------------------------------------------

def test_resuelve_el_rumbo_a_partir_del_sol(tmp_path):
    momento = datetime(2026, 3, 5, 19, 5, 15, tzinfo=timezone(timedelta(hours=-3)))
    lat, lon = -34.7969, -72.0025
    sol = posicion_solar(momento, lat, lon)

    ancho = 1440
    rumbo_verdadero = 137.0
    x_sol = int(((sol.azimut - rumbo_verdadero) % 360) / 360 * ancho)
    ruta = escribir_panorama(tmp_path / "POSICION 01" / "f.JPG", lat=lat, lon=lon,
                             ancho=ancho, sol_x=x_sol, sol_elevacion=sol.elevacion)

    resuelto = resolver_rumbo(leer_panorama(ruta), ancho_analisis=ancho)

    assert resuelto.rumbo0 == pytest.approx(rumbo_verdadero, abs=1.5)
    assert resuelto.disco.metodo == "disco"
    assert resuelto.error_elevacion < 1.5


def test_el_error_de_elevacion_delata_una_deteccion_falsa():
    sospechoso = RumboResuelto(
        rumbo0=200.0, azimut_solar=273.0, elevacion_solar=14.0,
        disco=DiscoSolar(x_normalizado=0.5, elevacion_medida=45.0, metodo="disco", pixeles=800),
    )
    assert sospechoso.error_elevacion == pytest.approx(31.0)


# --- conversión a Vista ------------------------------------------------------

def test_convierte_a_vista_conservando_la_pose(tmp_path):
    panorama = leer_panorama(escribir_panorama(tmp_path / "POSICION 04" / "f.JPG"))
    rumbo = RumboResuelto(12.345, 271.9, 12.9,
                          DiscoSolar(0.72, 12.8, "disco", 900))

    vista = a_vista(panorama, rumbo)

    assert vista.id == panorama.id
    assert vista.posicion == 4
    assert vista.rumbo0 == pytest.approx(12.35)
    assert vista.terreno_plano() == pytest.approx(185.170 - 100.281)


# --- posiciones de vuelo -----------------------------------------------------

def test_un_vuelo_sin_carpetas_posicion_numera_por_cercania(tmp_path):
    """Sin carpetas `POSICION NN` todas caían en la posición 0 y compartían id."""
    for i, (lon, minuto) in enumerate([(-72.0025, 10), (-71.9970, 12), (-71.9915, 14)]):
        escribir_panorama(tmp_path / f"DJI_{i}.JPG", lon=lon, relativa=118.0,
                          momento=f"2026-03-05T19:{minuto}:00-03:00")

    encontradas = buscar_panoramas(tmp_path)

    assert [p.posicion for p in encontradas] == [1, 2, 3]
    assert [p.id for p in encontradas] == ["p01-120", "p02-120", "p03-120"]


def test_dos_alturas_en_el_mismo_punto_son_una_sola_posicion(tmp_path):
    escribir_panorama(tmp_path / "baja.JPG", lon=-72.0025, relativa=118.0,
                      momento="2026-03-05T19:10:00-03:00")
    escribir_panorama(tmp_path / "alta.JPG", lon=-72.0023, relativa=226.4,
                      momento="2026-03-05T19:12:00-03:00")

    encontradas = buscar_panoramas(tmp_path)

    assert {p.posicion for p in encontradas} == {1}
    assert [p.id for p in encontradas] == ["p01-120", "p01-230"]


def test_las_posiciones_se_numeran_en_orden_de_captura(tmp_path):
    escribir_panorama(tmp_path / "segunda.JPG", lon=-71.9970,
                      momento="2026-03-05T19:20:00-03:00")
    escribir_panorama(tmp_path / "primera.JPG", lon=-72.0025,
                      momento="2026-03-05T19:05:00-03:00")

    pors = {p.ruta.stem: p.posicion for p in buscar_panoramas(tmp_path)}

    assert pors == {"primera": 1, "segunda": 2}


def test_las_carpetas_posicion_siguen_mandando_cuando_existen(tmp_path):
    """El primer proyecto trae las fotos rotuladas y ese número no se toca."""
    escribir_panorama(tmp_path / "POSICION 03" / "a.JPG", lon=-72.0025)
    escribir_panorama(tmp_path / "POSICION 01" / "b.JPG", lon=-71.9970)

    encontradas = buscar_panoramas(tmp_path)

    assert [p.posicion for p in encontradas] == [1, 3]


def test_los_numeros_asignados_continuan_despues_de_los_rotulados(tmp_path):
    escribir_panorama(tmp_path / "POSICION 02" / "rotulada.JPG", lon=-72.0025)
    escribir_panorama(tmp_path / "suelta.JPG", lon=-71.9900)

    pors = {p.ruta.stem: p.posicion for p in buscar_panoramas(tmp_path)}

    assert pors == {"rotulada": 2, "suelta": 3}


def test_asignar_posiciones_no_toca_una_lista_ya_numerada(tmp_path):
    panoramas = [leer_panorama(escribir_panorama(tmp_path / "POSICION 07" / "a.JPG"))]

    asignar_posiciones(panoramas)

    assert panoramas[0].posicion == 7


# --- copias -------------------------------------------------------------------

def test_ignora_las_copias_de_una_misma_panoramica(tmp_path):
    """El piloto suele dejar la misma foto en dos carpetas (la de trabajo y el
    volcado de la tarjeta). Es una vista, no dos."""
    escribir_panorama(tmp_path / "360" / "DJI_0246.JPG", momento="2026-03-05T19:05:00-03:00")
    escribir_panorama(tmp_path / "Dron" / "DJI_0246.JPG", momento="2026-03-05T19:05:00-03:00")

    panoramas = buscar_panoramas(tmp_path)

    assert len(panoramas) == 1
    assert panoramas[0].ruta.parent.name == "360"
