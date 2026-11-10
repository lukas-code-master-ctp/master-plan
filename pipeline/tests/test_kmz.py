import math
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
    # Lomas de Quillón rotula su tercera etapa con guion entre la letra y el número.
    ("A-1", "A1"),
    ("A-32", "A32"),
    ("LOTE B-07", "B7"),
    # Loteos que numeran sin letra de sector (Talhuenes) o con par sector-lote.
    ("LOTE 42", "42"),
    ("lote 007", "7"),
    ("42", "42"),
    (42, "42"),
    (42.0, "42"),
    ("7-1", "7-1"),
    # Par sector-lote con ceros como en el plano (Caminos de Rapel) y LOTE con guion
    # pegado (El Arrayán).
    ("Lote 8-01", "8-1"),
    ("LOTE 8-01", "8-1"),
    ("8-01", "8-1"),
    ("LOTE 10-6", "10-6"),
    ("LOTE-12", "12"),
    ("LOTE #12", "12"),
    ("LOTE - 12", "12"),
    # Como pueden llegar desde un CRM: rotulados como parcela, con N°, o como decimal.
    ("Parcela 12", "12"),
    ("PARCELA N° 12", "12"),
    ("N°12", "12"),
    ("Nº 12", "12"),
    ("#12", "12"),
    ("12.0", "12"),
    ("12,00", "12"),
])
def test_normaliza_los_formatos_de_nombre(entrada, esperado):
    assert normalizar_id(entrada) == esperado


@pytest.mark.parametrize("entrada", [None, "", "sin numero", "12/03/2024", "A", "-12", "LOTE--12", "12-", "12.5"])
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


def lote_dibujado(este, norte, lado=70):
    """El lote cerrado, como polígono sin nombre (las "Area Features" de Global Mapper)."""
    esquinas = [desplazar(este, norte), desplazar(este + lado, norte),
                desplazar(este + lado, norte + lado), desplazar(este, norte + lado)]
    return (f"<Placemark><name></name><Polygon><outerBoundaryIs><LinearRing><coordinates>"
            f"{coords(esquinas + esquinas[:1])}</coordinates></LinearRing></outerBoundaryIs>"
            f"</Polygon></Placemark>")


def test_si_el_lote_viene_dibujado_cerrado_manda_ese_poligono_y_no_la_franja_de_la_red():
    """Hacienda Vichuquén: además de los lotes cerrados, el dibujo trae una línea a
    3,2 m del frente de cada lote. La red de líneas partía el lote en dos y el rótulo,
    puesto en el frente, caía en la franja: el sitio mostraba tiras de 3 m de ancho."""
    franja = linea([desplazar(0, 3.2), desplazar(140, 3.2)])
    contenido = kml(rejilla_de_dos() + franja + lote_dibujado(0, 0) + lote_dibujado(70, 0)
                    + punto("LOTE 1", desplazar(35, 1.5))
                    + punto("LOTE 2", desplazar(105, 1.5)))

    parcelas = _parsear(contenido)

    assert {p.id for p in parcelas} == {"1", "2"}
    assert all(p.area_m2 == pytest.approx(4900, rel=0.01) for p in parcelas)


def achurado(ancho=140, alto=70, separacion=3.2, estilo_id="rojo"):
    """Rayas a 45° cada `separacion` metros que rellenan el rectángulo [0, ancho] × [0, alto],
    de borde a borde, como el relleno que exporta el CAD."""
    paso = separacion * 2 ** 0.5        # entre rayas y = x - c, medido sobre el eje x
    rayas, c = [], -alto + paso
    while c < ancho:
        x0, x1 = max(0.0, c), min(ancho, alto + c)
        rayas.append(linea([desplazar(x0, x0 - c), desplazar(x1, x1 - c)], estilo_id))
        c += paso
    return "".join(rayas)


def test_el_achurado_no_parte_los_lotes_en_tiras():
    """Hacienda Vichuquén: el CAD rellena un sector con rayas rojas a 45° cada 3,2 m.
    En la red cada raya cortaba el lote, y el 112 quedaba como una tira de 161 m²."""
    contenido = kml(estilo("rojo", "FF0000FF") + rejilla_de_dos() + achurado()
                    + punto("LOTE 1", desplazar(35, 35))
                    + punto("LOTE 2", desplazar(105, 35)))

    parcelas = _parsear(contenido)

    assert {p.id for p in parcelas} == {"1", "2"}
    assert all(p.area_m2 == pytest.approx(4900, rel=0.01) for p in parcelas)


def test_las_divisorias_paralelas_de_una_hilera_de_lotes_no_son_achurado():
    """Una hilera de lotes angostos también trae muchas líneas paralelas de un mismo
    color, pero separadas por el frente de un lote, no por unos pocos metros."""
    lotes, frente = 24, 25
    a, c = desplazar(0, 0), desplazar(lotes * frente, 0)
    d, f = desplazar(0, 70), desplazar(lotes * frente, 70)
    contorno = linea([a, c]) + linea([c, f]) + linea([f, d]) + linea([d, a])
    divisorias = "".join(linea([desplazar(i * frente, 0), desplazar(i * frente, 70)], "rojo")
                         for i in range(1, lotes))
    rotulos = "".join(punto(f"LOTE {i + 1}", desplazar(i * frente + frente / 2, 35))
                      for i in range(lotes))

    parcelas = _parsear(kml(estilo("rojo", "FF0000FF") + contorno + divisorias + rotulos))

    assert len(parcelas) == lotes
    assert all(p.area_m2 == pytest.approx(frente * 70, rel=0.01) for p in parcelas)


def test_un_poligono_que_encierra_varios_rotulos_no_es_un_lote():
    """El deslinde de todo el loteo también es un polígono cerrado: no puede quedarse
    con un rótulo. Ahí manda la red."""
    contenido = kml(rejilla_de_dos() + lote_dibujado(0, 0, lado=140)
                    + punto("LOTE 1", desplazar(35, 35))
                    + punto("LOTE 2", desplazar(105, 35)))

    parcelas = _parsear(contenido)

    assert {p.id for p in parcelas} == {"1", "2"}
    assert all(p.area_m2 == pytest.approx(4900, rel=0.01) for p in parcelas)


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


def test_leer_lineas_deja_afuera_el_achurado(tmp_path):
    """Las rayas del relleno no están en la foto: no sirven para calibrar."""
    from pipeline.kmz import leer_lineas
    ruta = tmp_path / "loteo.kmz"
    with zipfile.ZipFile(ruta, "w") as archivo:
        archivo.writestr("doc.kml", kml(estilo("rojo", "FF0000FF") + rejilla_de_dos() + achurado()))

    assert len(leer_lineas(ruta)) == 5


def franja_achurada(norte_sur=-8.0, norte_norte=-2.0, largo=140.0, paso=3.0):
    """Un acceso como lo dibuja el CAD: los dos bordes y rayas cruzadas entre ellos."""
    bordes = (linea([desplazar(0, norte_sur), desplazar(largo, norte_sur)])
              + linea([desplazar(0, norte_norte), desplazar(largo, norte_norte)]))
    rayas = "".join(linea([desplazar(x, norte_sur), desplazar(x + 4, norte_norte)])
                    for x in range(0, int(largo) - 4, int(paso)))
    return bordes + rayas


def guardar_kmz(tmp_path, contenido):
    ruta = tmp_path / "loteo.kmz"
    with zipfile.ZipFile(ruta, "w") as archivo:
        archivo.writestr("doc.kml", contenido)
    return ruta


def test_leer_caminos_arma_la_franja_del_acceso(tmp_path):
    """Lomas de Quillón: los accesos son franjas achuradas en amarillo, no polígonos,
    y en el 360 no se veían."""
    from pipeline.kmz import leer_caminos
    ruta = guardar_kmz(tmp_path, kml(rejilla_de_dos() + punto("LOTE 1", desplazar(35, 35))
                                     + punto("LOTE 2", desplazar(105, 35)) + franja_achurada()))

    caminos = leer_caminos(ruta)

    assert len(caminos) == 1
    contorno = caminos[0][0]
    assert geo.contiene(contorno, desplazar(70, -5))
    assert not geo.contiene(contorno, desplazar(70, 35))
    assert 140 * 6 <= geo.area_m2(contorno) <= 140 * 12


def test_leer_caminos_no_toma_los_deslindes(tmp_path):
    from pipeline.kmz import leer_caminos
    ruta = guardar_kmz(tmp_path, kml(rejilla_de_dos() + punto("LOTE 1", desplazar(35, 35))
                                     + punto("LOTE 2", desplazar(105, 35))))

    assert leer_caminos(ruta) == []


def estero(nombre, puntos):
    return (f"<Placemark><name>{nombre}</name>"
            f"<LineString><coordinates>{coords(puntos)}</coordinates></LineString></Placemark>")


def test_un_estero_del_kmz_se_lee_aparte_y_no_parte_los_lotes(tmp_path):
    """Lomas de Quillón: el estero corre por el borde norte de los lotes. Agregado en
    Google Earth como una ruta "Estero", no puede volverse deslinde ni camino."""
    from pipeline.kmz import leer_aguas, leer_caminos
    # Cruza los dos lotes por el medio: como deslinde los partiría en cuatro.
    trazo = [desplazar(-10, 35), desplazar(150, 35)]
    ruta = guardar_kmz(tmp_path, kml(rejilla_de_dos() + punto("LOTE 1", desplazar(35, 50))
                                     + punto("LOTE 2", desplazar(105, 50)) + estero("Estero Coihueco", trazo)))

    [(nombre, puntos)] = leer_aguas(ruta)
    assert nombre == "Estero Coihueco"
    assert puntos == [pytest.approx(p, abs=1e-9) for p in trazo]
    assert sorted(p.id for p in leer_kmz(ruta)) == ["1", "2"]
    assert leer_caminos(ruta) == []


@pytest.mark.parametrize("nombre, es_agua", [
    ("Estero", True), ("estero las Toscas", True), ("Río Itata", True), ("Rio Itata", True),
    ("Quebrada Honda", True), ("Canal de regadío", True), ("LOTE 7", False), ("Laguna", False),
    ("Esterilla", False),
])
def test_que_nombres_cuentan_como_agua(nombre, es_agua):
    from pipeline.kmz import NOMBRE_DE_AGUA
    assert bool(NOMBRE_DE_AGUA.match(nombre)) is es_agua


def test_una_zona_de_conservacion_se_lee_aparte_y_no_es_lote(tmp_path):
    """Fundo Atalaya: la zona de conservación va como un polígono con ese nombre al
    lado de los lotes. Se pinta, pero no es un lote ni parte la red de deslindes."""
    from pipeline.kmz import leer_zonas
    zona = [desplazar(-200, 0), desplazar(-10, 0), desplazar(-10, 70), desplazar(-200, 70)]
    ruta = guardar_kmz(tmp_path, kml(rejilla_de_dos() + punto("LOTE 1", desplazar(35, 35))
                                     + punto("LOTE 2", desplazar(105, 35))
                                     + poligono(zona, nombre="Zona de conservación")))

    [(nombre, anillo)] = leer_zonas(ruta)
    assert nombre == "Zona de conservación"
    assert anillo == [pytest.approx(p, abs=1e-9) for p in zona]
    assert sorted(p.id for p in leer_kmz(ruta)) == ["1", "2"]


def test_una_zona_entre_poligonos_no_sale_como_lote_sin_numero(tmp_path):
    from pipeline.kmz import leer_zonas
    lote = [desplazar(0, 0), desplazar(50, 0), desplazar(50, 50), desplazar(0, 50)]
    zona = [desplazar(60, 0), desplazar(200, 0), desplazar(200, 50), desplazar(60, 50)]
    ruta = guardar_kmz(tmp_path, kml(poligono(lote, nombre="LOTE 1") + poligono(zona, nombre="Área verde")))

    assert [p.id for p in leer_kmz(ruta)] == ["1"]
    assert [nombre for nombre, _ in leer_zonas(ruta)] == ["Área verde"]


def test_el_borde_de_una_zona_no_es_camino(tmp_path):
    """El cerco del predio corre por el borde de la zona de conservación: como no es
    deslinde de ningún lote, salía pintado de camino."""
    from pipeline.kmz import leer_caminos
    zona = [desplazar(-200, 0), desplazar(0, 0), desplazar(0, 70), desplazar(-200, 70)]
    cerco = [desplazar(0, 0), desplazar(-200, 0), desplazar(-200, 70), desplazar(0, 70)]
    ruta = guardar_kmz(tmp_path, kml(rejilla_de_dos() + punto("LOTE 1", desplazar(35, 35))
                                     + punto("LOTE 2", desplazar(105, 35))
                                     + estero("Cerco", cerco).replace("Cerco", "cerco poniente")
                                     + poligono(zona, nombre="Zona de conservación")))

    assert leer_caminos(ruta) == []


def lotes_como_poligonos():
    """Dos lotes de 70 × 70 m como polígonos con nombre, separados 10 m de norte a sur."""
    return (poligono(cuadrado(0, 0), nombre="LOTE 1") + poligono(cuadrado(0, 80), nombre="LOTE 2"))


def test_una_servidumbre_como_ruta_en_un_kmz_de_poligonos_se_pinta_como_camino(tmp_path):
    """Parque Algarrobo: los lotes vienen como polígonos y la servidumbre no venía. Una
    ruta "Servidumbre" agregada en Google Earth pasaba el KMZ al modo CAD."""
    from pipeline.kmz import leer_caminos
    eje = [desplazar(-20, 75), desplazar(90, 75)]
    ruta = guardar_kmz(tmp_path, kml(lotes_como_poligonos() + estero("x", eje).replace("x", "Servidumbre")))

    assert sorted(p.id for p in leer_kmz(ruta)) == ["1", "2"]
    [[contorno]] = leer_caminos(ruta)
    assert geo.contiene(contorno, desplazar(35, 75))
    assert not geo.contiene(contorno, desplazar(35, 35))
    # La franja de 10 m de ancho, con las dos puntas redondas.
    assert geo.area_m2(contorno) == pytest.approx(110 * 10 + math.pi * 5 ** 2, rel=0.03)


def test_una_servidumbre_como_poligono_no_es_lote_sin_numero(tmp_path):
    from pipeline.kmz import leer_caminos
    franja = [desplazar(0, 70), desplazar(70, 70), desplazar(70, 80), desplazar(0, 80)]
    ruta = guardar_kmz(tmp_path, kml(lotes_como_poligonos() + poligono(franja, nombre="SERVIDUMBRE")))

    assert sorted(p.id for p in leer_kmz(ruta)) == ["1", "2"]
    [[contorno]] = leer_caminos(ruta)
    assert geo.area_m2(contorno) == pytest.approx(700, rel=0.05)


def test_en_un_kmz_cad_una_linea_camino_sigue_siendo_deslinde(tmp_path):
    """En el CAD la línea con nombre puede ser el borde de un lote: sacarla de la red
    fusionaría los lotes."""
    a, c = desplazar(0, 0), desplazar(140, 0)
    d, f = desplazar(0, 70), desplazar(140, 70)
    dibujo = (linea([a, c]) + linea([c, f]) + linea([f, d]) + linea([d, a])
              + estero("x", [desplazar(70, 0), desplazar(70, 70)]).replace("x", "Camino interior"))
    ruta = guardar_kmz(tmp_path, kml(dibujo + punto("LOTE 1", desplazar(35, 35))
                                     + punto("LOTE 2", desplazar(105, 35))))

    assert sorted(p.id for p in leer_kmz(ruta)) == ["1", "2"]


@pytest.mark.parametrize("nombre, es_camino", [
    ("Servidumbre", True), ("SERVIDUMBRE DE TRÁNSITO", True), ("servidumbres", True),
    ("Camino", True), ("Camino interior", True), ("Acceso", True), ("LOTE 7", False),
    ("Caminata", False), ("Estero", False),
])
def test_que_nombres_cuentan_como_camino(nombre, es_camino):
    from pipeline.kmz import NOMBRE_DE_CAMINO
    assert bool(NOMBRE_DE_CAMINO.match(nombre)) is es_camino


@pytest.mark.parametrize("nombre, es_zona", [
    ("Zona de conservación", True), ("ZONA DE CONSERVACION", True), ("Área verde", True),
    ("Areas verdes", True), ("Reserva", True), ("Conservación", True), ("Bosque nativo", True),
    ("Zona protegida", True), ("LOTE 7", False), ("A214", False), ("Zonal", False), ("Estero", False),
])
def test_que_nombres_cuentan_como_zona(nombre, es_zona):
    from pipeline.kmz import NOMBRE_DE_ZONA
    assert bool(NOMBRE_DE_ZONA.match(nombre)) is es_zona


@pytest.mark.parametrize("pendiente", [0.05 + i * 0.0371 for i in range(14)])
def test_una_divisoria_que_llega_a_un_borde_inclinado_separa_los_lotes(pendiente):
    """Fundo Atalaya: la divisoria termina a décimas de milímetro de un borde en
    diagonal. Pegada al punto más cercano quedaba a una millonésima, la red no
    cortaba ahí y los dos lotes salían como uno solo sin número."""
    import math
    x = 70 + (pendiente - 0.05) / 0.0371 * 0.173
    y = x * pendiente
    largo = math.hypot(1, pendiente)
    fin = desplazar(x - pendiente / largo * 0.0004, y + 1 / largo * 0.0004)
    a, c = desplazar(0, 0), desplazar(140, 140 * pendiente)
    d, f = desplazar(0, 90), desplazar(140, 90)
    contenido = kml(linea([a, c]) + linea([c, f]) + linea([f, d]) + linea([d, a])
                    + linea([desplazar(x, 90), fin])
                    + punto("LOTE 1", desplazar(30, 60)) + punto("LOTE 2", desplazar(110, 75)))

    assert {p.id for p in _parsear(contenido)} == {"1", "2"}


def test_el_eje_de_una_servidumbre_se_redondea_sin_mover_las_puntas():
    """Parque Algarrobo: las servidumbres se trazaron con pocos clics y salían quebradas."""
    from pipeline.kmz import CAMINO_EJE_CORTE_M, _suavizar
    eje = [(0.0, 0.0), (100.0, 0.0), (100.0, 20.0), (300.0, 20.0)]

    suave = _suavizar(eje)

    assert suave[0] == eje[0] and suave[-1] == eje[-1]
    assert len(suave) > len(eje)
    # La esquina ya no está, pero el eje no se aleja de ella más que el corte.
    assert (100.0, 0.0) not in suave
    assert min(math.dist(p, (100.0, 0.0)) for p in suave) < CAMINO_EJE_CORTE_M
    # Un tramo largo sigue recto: lejos de las esquinas no se mueve.
    assert all(abs(y - 20.0) < 1e-9 for x, y in suave if x > 120.0)
