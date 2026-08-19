import zipfile

import pytest

from pipeline import geo
from pipeline.kmz import ParcelaGeometrica, leer_kmz, normalizar_id
from pipeline.kmz import _parsear

LAT, LON = -34.79, -72.0
GRADO_LON = geo.metros_por_grado_lon(LAT)


def desplazar(este_m, norte_m):
    return (LON + este_m / GRADO_LON, LAT + norte_m / geo.METROS_POR_GRADO_LAT)


def coords(puntos):
    return " ".join(f"{lon:.10f},{lat:.10f},0" for lon, lat in puntos)


def kml(cuerpo):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>{cuerpo}</Document></kml>"""


def poligono(puntos, descripcion="0", nombre=None):
    etiqueta = f"<name>{nombre}</name>" if nombre else ""
    return f"""<Placemark>{etiqueta}<description>{descripcion}</description>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>{coords(puntos)}</coordinates>
      </LinearRing></outerBoundaryIs></Polygon></Placemark>"""


def punto(nombre, lonlat):
    return f"""<Placemark><name>{nombre}</name>
      <Point><coordinates>{lonlat[0]:.10f},{lonlat[1]:.10f},0</coordinates></Point></Placemark>"""


def cuadrado(este, norte, lado=70):
    return [desplazar(este, norte), desplazar(este + lado, norte),
            desplazar(este + lado, norte + lado), desplazar(este, norte + lado)]


# --- normalizar_id -----------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("LOTE A24", "A24"),
    ("Lote A 420", "A420"),
    ("A214", "A214"),
    ("  lote a 007 ", "A7"),
    ("LOTES A99", "A99"),
    ("B15", "B15"),
])
def test_normaliza_los_formatos_de_nombre(entrada, esperado):
    assert normalizar_id(entrada) == esperado


@pytest.mark.parametrize("entrada", [None, "", "sin numero", "123"])
def test_devuelve_none_cuando_no_hay_lote(entrada):
    assert normalizar_id(entrada) is None


# --- lectura -----------------------------------------------------------------

def test_lee_poligonos_y_les_pone_el_nombre_de_la_etiqueta_que_contienen():
    contenido = kml(
        poligono(cuadrado(0, 0)) +
        poligono(cuadrado(100, 0)) +
        punto("LOTE A10", desplazar(35, 35)) +
        punto("LOTE A11", desplazar(135, 35))
    )
    parcelas = _parsear(contenido)

    assert {p.id for p in parcelas} == {"A10", "A11"}


def test_marca_las_parcelas_que_no_estan_en_venta():
    contenido = kml(
        poligono(cuadrado(0, 0), descripcion="NO EN VENTA") +
        poligono(cuadrado(100, 0), descripcion="0")
    )
    parcelas = _parsear(contenido)

    assert [p.en_venta for p in parcelas] == [False, True]


def test_una_etiqueta_fuera_de_su_poligono_se_resuelve_por_cercania():
    contenido = kml(
        poligono(cuadrado(0, 0)) +
        punto("LOTE A10", desplazar(35, -20))   # justo afuera, al sur
    )
    parcelas = _parsear(contenido)

    assert parcelas[0].id == "A10"


def test_una_etiqueta_lejisimos_no_secuestra_un_poligono():
    contenido = kml(
        poligono(cuadrado(0, 0)) +
        punto("LOTE A10", desplazar(5000, 5000))
    )
    parcelas = _parsear(contenido)

    assert parcelas[0].id is None


def test_calcula_area_y_centroide_de_cada_parcela():
    parcelas = _parsear(kml(poligono(cuadrado(0, 0, lado=100))))

    assert parcelas[0].area_m2 == pytest.approx(10000, rel=1e-3)
    assert geo.contiene(parcelas[0].anillo, parcelas[0].centroide)


def test_el_anillo_queda_abierto_aunque_el_kml_lo_cierre():
    puntos = cuadrado(0, 0)
    cerrado = puntos + [puntos[0]]
    parcelas = _parsear(kml(poligono(cerrado)))

    assert len(parcelas[0].anillo) == 4


def test_ignora_los_puntos_sin_nombre_de_lote():
    contenido = kml(poligono(cuadrado(0, 0)) + punto("TEXTOS REPARO", desplazar(35, 35)))
    parcelas = _parsear(contenido)

    assert parcelas[0].id is None


def test_lee_un_kmz_real_desde_disco(tmp_path):
    ruta = tmp_path / "prueba.kmz"
    contenido = kml(poligono(cuadrado(0, 0)) + punto("LOTE A5", desplazar(35, 35)))
    with zipfile.ZipFile(ruta, "w") as archivo:
        archivo.writestr("doc.kml", contenido)

    parcelas = leer_kmz(ruta)

    assert [p.id for p in parcelas] == ["A5"]


def test_un_kmz_sin_kml_avisa_claramente(tmp_path):
    ruta = tmp_path / "vacio.kmz"
    with zipfile.ZipFile(ruta, "w") as archivo:
        archivo.writestr("leeme.txt", "nada")

    with pytest.raises(ValueError, match="no contiene"):
        leer_kmz(ruta)
