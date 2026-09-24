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
    # Loteos que numeran sin letra de sector (Talhuenes) o con par sector-lote.
    ("LOTE 42", "42"),
    ("lote 007", "7"),
    ("42", "42"),
    (42, "42"),
    (42.0, "42"),
    ("7-1", "7-1"),
])
def test_normaliza_los_formatos_de_nombre(entrada, esperado):
    assert normalizar_id(entrada) == esperado


@pytest.mark.parametrize("entrada", [None, "", "sin numero", "12/03/2024", "A"])
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


# --- redes de líneas (KMZ exportado desde CAD) -------------------------------
#
# Global Mapper exporta el dibujo del topógrafo tal cual: los lotes no vienen como
# polígonos sino como una red de LineStrings, con un punto rotulado por lote.

def estilo(identificador, color):
    return (f'<Style id="{identificador}"><LineStyle><color>{color}</color><width>1</width>'
            f'</LineStyle><PolyStyle><color>BF000000</color><fill>0</fill></PolyStyle></Style>')


def linea(puntos, estilo_id=None):
    url = f"<styleUrl>#{estilo_id}</styleUrl>" if estilo_id else ""
    return (f"<Placemark><description>UNKNOWN_LINE_TYPE</description>{url}"
            f"<LineString><coordinates>{coords(puntos)}</coordinates></LineString></Placemark>")


def poligono_con_estilo(puntos, estilo_id):
    return (f"<Placemark><styleUrl>#{estilo_id}</styleUrl><Polygon><outerBoundaryIs>"
            f"<LinearRing><coordinates>{coords(puntos)}</coordinates></LinearRing>"
            f"</outerBoundaryIs></Polygon></Placemark>")


def rejilla_de_dos(este=0, norte=0, hueco_m=0.0, estilo_id=None):
    """Dos lotes de 70 × 70 m pegados, dibujados como líneas: el rectángulo exterior
    y una divisoria al medio. Con `hueco_m` la divisoria no llega al borde sur."""
    a, c = desplazar(este, norte), desplazar(este + 140, norte)
    d, f = desplazar(este, norte + 70), desplazar(este + 140, norte + 70)
    divisoria = [desplazar(este + 70, norte + hueco_m), desplazar(este + 70, norte + 70)]
    return (linea([a, c], estilo_id) + linea([c, f], estilo_id) + linea([f, d], estilo_id)
            + linea([d, a], estilo_id) + linea(divisoria, estilo_id))


def test_arma_los_lotes_desde_una_red_de_lineas():
    contenido = kml(rejilla_de_dos()
                    + punto("LOTE 1", desplazar(35, 35))
                    + punto("LOTE 2", desplazar(105, 35)))

    parcelas = _parsear(contenido)

    assert {p.id for p in parcelas} == {"1", "2"}
    assert all(p.area_m2 == pytest.approx(4900, rel=0.01) for p in parcelas)


def test_cierra_los_huecos_chicos_de_la_red():
    """El CAD deja divisorias que no tocan el borde por centímetros."""
    contenido = kml(rejilla_de_dos(hueco_m=0.3)
                    + punto("LOTE 1", desplazar(35, 35))
                    + punto("LOTE 2", desplazar(105, 35)))

    assert {p.id for p in _parsear(contenido)} == {"1", "2"}


def test_un_hueco_grande_deja_los_lotes_fusionados_y_sin_nombre():
    """Si la divisoria de verdad no llega, los dos lotes quedan en una sola cara.
    Esa cara se conserva sin id, para que se note en el plano y se arregle el KMZ."""
    contenido = kml(rejilla_de_dos(hueco_m=5.0)
                    + punto("LOTE 1", desplazar(35, 35))
                    + punto("LOTE 2", desplazar(105, 35)))

    parcelas = _parsear(contenido)

    assert [p.id for p in parcelas] == [None]
    assert parcelas[0].area_m2 == pytest.approx(9800, rel=0.01)


def test_descarta_las_caras_sin_etiqueta():
    """Caminos, franjas de servidumbre y el recuadro de la leyenda también cierran
    caras. Sin etiqueta de lote adentro, no son parcelas."""
    contenido = kml(rejilla_de_dos() + punto("LOTE 1", desplazar(35, 35)))

    parcelas = _parsear(contenido)

    assert [p.id for p in parcelas] == ["1"]


def test_separa_por_etapa_segun_el_color_de_la_leyenda():
    """Cada etapa repite la numeración desde 1. El KMZ las distingue por color, y
    la leyenda (un cuadrito de cada color junto a su rótulo ETAPA) dice cuál es cuál."""
    contenido = kml(
        estilo("rojo", "FF0000FF") + estilo("azul", "FFFF0000")
        + rejilla_de_dos(norte=0, estilo_id="rojo")
        + punto("LOTE 1", desplazar(35, 35)) + punto("LOTE 2", desplazar(105, 35))
        + rejilla_de_dos(norte=500, estilo_id="azul")
        + punto("LOTE 1", desplazar(35, 535)) + punto("LOTE 2", desplazar(105, 535))
        # leyenda, lejos del loteo
        + poligono_con_estilo(cuadrado(1000, 0, lado=20), "rojo")
        + punto("ROL 409-37 ETAPA 1", desplazar(1030, 10))
        + poligono_con_estilo(cuadrado(1000, 100, lado=20), "azul")
        + punto("ROL 409-41 ETAPA 2", desplazar(1030, 110))
    )

    parcelas = _parsear(contenido)

    assert {p.id for p in parcelas} == {"1-1", "1-2", "2-1", "2-2"}
    assert {p.etapa for p in parcelas} == {1, 2}
    assert all(p.area_m2 == pytest.approx(4900, rel=0.01) for p in parcelas)


def test_avisa_si_hay_lotes_repetidos_y_no_puede_separarlos():
    contenido = kml(
        rejilla_de_dos(norte=0)
        + punto("LOTE 1", desplazar(35, 35)) + punto("LOTE 2", desplazar(105, 35))
        + rejilla_de_dos(norte=500)
        + punto("LOTE 1", desplazar(35, 535)) + punto("LOTE 2", desplazar(105, 535))
    )

    with pytest.raises(ValueError, match="repetid"):
        _parsear(contenido)


def test_los_rotulos_de_etapa_no_se_confunden_con_lotes():
    """"ROL 409-37 ETAPA 1" tiene una letra seguida de dígitos, pero no es un lote."""
    contenido = kml(poligono(cuadrado(0, 0)) + punto("ROL 409-37 ETAPA 1", desplazar(35, 35)))

    parcelas = _parsear(contenido)

    assert parcelas[0].id is None


def test_un_poligono_toma_la_etapa_del_color_de_su_contorno():
    contenido = kml(
        estilo("rojo", "FF0000FF")
        + poligono_con_estilo(cuadrado(0, 0), "rojo") + punto("LOTE 3", desplazar(35, 35))
        + poligono_con_estilo(cuadrado(1000, 0, lado=20), "rojo")
        + punto("ETAPA 2", desplazar(1030, 10))
    )

    parcelas = _parsear(contenido)

    assert [(p.id, p.etapa) for p in parcelas] == [("2-3", 2)]


# --- líneas para calibrar ------------------------------------------------------

def test_leer_lineas_trae_deslindes_y_caminos_pero_no_la_leyenda(tmp_path):
    from pipeline.kmz import leer_lineas
    contenido = kml(
        estilo("rojo", "FF0000FF")
        + rejilla_de_dos(estilo_id="rojo") + punto("LOTE 1", desplazar(35, 35))
        + linea([desplazar(0, -20), desplazar(140, -20)])                     # un camino suelto
        + poligono_con_estilo(cuadrado(1000, 0, lado=20), "rojo")             # cuadrito de la leyenda
        + punto("ETAPA 1", desplazar(1030, 10))
        + poligono_con_estilo(cuadrado(900, -100, lado=300), "rojo")          # el marco de la leyenda
    )
    ruta = tmp_path / "loteo.kmz"
    with zipfile.ZipFile(ruta, "w") as archivo:
        archivo.writestr("doc.kml", contenido)

    lineas = leer_lineas(ruta)

    assert len(lineas) == 6            # 5 de la rejilla + el camino; nada de la leyenda
