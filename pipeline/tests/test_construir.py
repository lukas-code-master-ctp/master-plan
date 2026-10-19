import pytest

from pipeline.construir import _revisar_ids_de_vista
from pipeline.panoramas import buscar_panoramas, leer_panorama
from pipeline.sintetico import escribir_panorama


def test_acepta_vistas_con_ids_distintos(tmp_path):
    escribir_panorama(tmp_path / "a.JPG", lon=-72.0025, relativa=118.0,
                      momento="2026-03-05T19:05:00-03:00")
    escribir_panorama(tmp_path / "b.JPG", lon=-71.9970, relativa=118.0,
                      momento="2026-03-05T19:07:00-03:00")

    _revisar_ids_de_vista(buscar_panoramas(tmp_path))   # no levanta


def test_corta_si_dos_panoramicas_comparten_id(tmp_path):
    """El mismo archivo duplicado en dos carpetas: una vista pisaría a la otra."""
    original = leer_panorama(escribir_panorama(tmp_path / "POSICION 01" / "foto.JPG"))
    copia = leer_panorama(escribir_panorama(tmp_path / "respaldo" / "foto.JPG"))
    copia.posicion = original.posicion

    with pytest.raises(ValueError, match="comparten el id de vista"):
        _revisar_ids_de_vista([original, copia])


def test_el_aviso_nombra_los_archivos_en_conflicto(tmp_path):
    uno = leer_panorama(escribir_panorama(tmp_path / "POSICION 01" / "uno.JPG"))
    otro = leer_panorama(escribir_panorama(tmp_path / "POSICION 01" / "otro.JPG"))

    with pytest.raises(ValueError) as error:
        _revisar_ids_de_vista([uno, otro])

    assert "uno.JPG" in str(error.value) and "otro.JPG" in str(error.value)
    assert uno.id in str(error.value)


# --- orden, número y rótulo de cada parcela ------------------------------------

from pipeline.construir import _armar_parcelas, _orden_lote
from pipeline.excel import FichaComercial
from pipeline.kmz import ParcelaGeometrica

ANILLO = [(-72.0, -35.0), (-71.999, -35.0), (-71.999, -34.999), (-72.0, -34.999)]


@pytest.mark.parametrize("identificador,esperado", [
    ("42", (0, 42)),
    ("A214", (0, 214)),
    ("2-7", (2, 7)),
    ("2-15", (2, 15)),
])
def test_ordena_por_etapa_y_despues_por_numero(identificador, esperado):
    assert _orden_lote(identificador) == esperado


def test_las_etapas_quedan_juntas_al_ordenar():
    ids = sorted(["2-1", "1-15", "1-7", "2-7"], key=_orden_lote)

    assert ids == ["1-7", "1-15", "2-1", "2-7"]


def test_cada_parcela_lleva_numero_etapa_y_rotulo():
    geometrias = {
        "2-7": ParcelaGeometrica(id="2-7", anillo=ANILLO, etapa=2),
        "A214": ParcelaGeometrica(id="A214", anillo=ANILLO),
        "7-1": ParcelaGeometrica(id="7-1", anillo=ANILLO),   # sector-lote, sin etapas
    }

    parcelas = {p["id"]: p for p in _armar_parcelas({}, geometrias, {})}

    assert (parcelas["2-7"]["numero"], parcelas["2-7"]["etapa"], parcelas["2-7"]["rotulo"]) == (7, 2, "7")
    assert (parcelas["A214"]["numero"], parcelas["A214"]["etapa"], parcelas["A214"]["rotulo"]) == (214, None, "214")
    assert (parcelas["7-1"]["numero"], parcelas["7-1"]["etapa"], parcelas["7-1"]["rotulo"]) == (1, None, "7-1")


def test_con_varias_etapas_el_rotulo_lleva_la_etapa():
    """Cauquenes tiene 4 etapas numeradas desde 1, así que del 1 al 12 cada número
    aparece cuatro veces y en pantalla se ven dos discos "7" a la vez. Un comprador
    que dice "quiero la 7" no está diciendo nada. Con etapas, el rótulo es el mismo
    nombre que usa el CRM: "2-7"."""
    geometrias = {
        "1-7": ParcelaGeometrica(id="1-7", anillo=ANILLO, etapa=1),
        "2-7": ParcelaGeometrica(id="2-7", anillo=ANILLO, etapa=2),
    }

    parcelas = {p["id"]: p for p in _armar_parcelas({}, geometrias, {})}

    assert parcelas["1-7"]["rotulo"] == "1-7"
    assert parcelas["2-7"]["rotulo"] == "2-7"
    # El número y la etapa no cambian: el rótulo es solo cómo se muestra.
    assert (parcelas["2-7"]["numero"], parcelas["2-7"]["etapa"]) == (7, 2)


def test_con_etapas_pero_sin_numeros_repetidos_el_rotulo_no_lleva_la_etapa():
    """Hacienda Vichuquén: dos etapas, pero los lotes van del A1 al A579 sin repetirse.
    La etapa delante ("1-1", "2-181") no distingue nada y no es como se llama el lote."""
    fichas = {
        "A1": FichaComercial(id="A1", numero="A1", etapa=1),
        "A181": FichaComercial(id="A181", numero="A181", etapa=2),
    }
    geometrias = {i: ParcelaGeometrica(id=i, anillo=ANILLO) for i in fichas}

    parcelas = {p["id"]: p for p in _armar_parcelas(fichas, geometrias, {})}

    assert parcelas["A1"]["rotulo"] == "1"
    assert parcelas["A181"]["rotulo"] == "181"
    # La etapa se sigue guardando: el filtro por etapa la usa.
    assert (parcelas["A181"]["numero"], parcelas["A181"]["etapa"]) == (181, 2)


def test_con_una_sola_etapa_el_rotulo_sigue_siendo_el_numero():
    """Si hay una etapa sola, anteponerla no distingue nada y ensucia la foto."""
    geometrias = {
        "1-7": ParcelaGeometrica(id="1-7", anillo=ANILLO, etapa=1),
        "1-8": ParcelaGeometrica(id="1-8", anillo=ANILLO, etapa=1),
    }

    parcelas = {p["id"]: p for p in _armar_parcelas({}, geometrias, {})}

    assert [p["rotulo"] for p in parcelas.values()] == ["7", "8"]


def test_si_el_loteo_no_esta_en_el_crm_avisa_y_sigue(tmp_path, capsys):
    """Que el loteo no figure en el export no puede tumbar la construcción: se
    avisa y las parcelas salen como no disponibles, que es lo honesto."""
    from pipeline.construir import Avisos, _leer_fichas
    from pipeline import config

    csv = tmp_path / "crm.csv"
    csv.write_text("﻿Parcela,Parcelación,ESTADO_CRM_PARCELA\n1,OTRO LOTEO,DISPONIBLE\n",
                   encoding="utf-8")
    fuentes = config.Fuentes(kmz=tmp_path / "x.kmz", panoramas=tmp_path, crm=csv)
    avisos = Avisos([])

    fichas = _leer_fichas(fuentes, config.Proyecto(nombre="Las Araucarias"), avisos)

    assert fichas == {}
    assert any("LAS ARAUCARIAS" in linea for linea in avisos.lineas)


def test_cuenta_los_vuelos_por_la_altura_del_despegue_que_guarda_el_dron():
    from types import SimpleNamespace as P

    from pipeline.construir import _vuelos

    panoramas = [P(altura_absoluta=576.2, altura_relativa=499.7), P(altura_absoluta=384.4, altura_relativa=299.6),
                 P(altura_absoluta=576.2, altura_relativa=499.7), P(altura_absoluta=584.5, altura_relativa=499.6)]

    assert _vuelos(panoramas) == [pytest.approx(76.5), pytest.approx(84.85)]


# --- lo que dejó la publicación sobrevive a una reconstrucción ------------------------
#
# La publicación anota en parcelas.json a qué consola pide reservas el sitio y cuál es
# su loteo. Reconstruir escribe parcelas.json de nuevo: si lo pierde, "Actualizar desde
# Cierra" sube un sitio sin reservas.

def test_conserva_la_consola_y_el_loteo_de_la_publicacion(tmp_path):
    from pipeline.construir import _datos_de_la_publicacion
    archivo = tmp_path / "parcelas.json"
    archivo.write_text('{"proyecto": "Praderas", "loteo": "praderas", '
                       '"consola": "https://consola.cl", "parcelas": []}', encoding="utf-8")

    assert _datos_de_la_publicacion(archivo) == {"loteo": "praderas", "consola": "https://consola.cl"}


def test_sin_publicacion_previa_no_agrega_nada(tmp_path):
    from pipeline.construir import _datos_de_la_publicacion
    sin_publicar = tmp_path / "sin.json"
    sin_publicar.write_text('{"proyecto": "Praderas", "parcelas": []}', encoding="utf-8")
    roto = tmp_path / "roto.json"
    roto.write_text("{a medias", encoding="utf-8")

    assert _datos_de_la_publicacion(tmp_path / "no-existe.json") == {}
    assert _datos_de_la_publicacion(sin_publicar) == {}
    assert _datos_de_la_publicacion(roto) == {}


def test_sin_panoramicas_validas_corta_con_un_mensaje_claro(tmp_path, capsys):
    from PIL import Image

    from pipeline import construir as modulo
    from pipeline.config import Fuentes, Proyecto, Salida
    import zipfile
    Image.new("RGB", (400, 300)).save(tmp_path / "DJI_0001.JPG", "JPEG")
    kmz = tmp_path / "loteo.kmz"
    with zipfile.ZipFile(kmz, "w") as archivo:
        archivo.writestr("doc.kml", (
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>LOTE 1</name>'
            '<Polygon><outerBoundaryIs><LinearRing><coordinates>-72,-36 -72.001,-36 '
            '-72.001,-36.001 -72,-36.001 -72,-36</coordinates></LinearRing></outerBoundaryIs>'
            '</Polygon></Placemark></Document></kml>'))

    with pytest.raises(modulo.SinPanoramas) as error:
        modulo.construir(Fuentes(kmz=kmz, panoramas=tmp_path), Proyecto(nombre="X"),
                         Salida(tmp_path / "salida"), sin_imagenes=True)

    assert "DJI_0001.JPG" in str(error.value)
    assert "XMP" in str(error.value)


# --- los otros puntos de vuelo, para saltar entre 360 -------------------------------

def test_marca_el_suelo_bajo_cada_otro_punto_una_vez_por_punto():
    from pipeline.construir import _proyectar_puntos
    from pipeline.proyeccion import Vista

    def vista(id_, posicion, lat, relativa=100.0):
        return Vista(id=id_, posicion=posicion, lon=-72.0, lat=lat, altura_relativa=relativa,
                     altura_absoluta=300.0 + relativa, rumbo0=0.0)

    aqui = vista("p01-100", 1, -35.0)
    todas = [aqui, vista("p01-300", 1, -35.0, 300.0),               # el mismo punto, más alto
             vista("p02-100", 2, -35.0 + 500 / 111320.0),           # 500 m al norte
             vista("p02-300", 2, -35.0 + 500 / 111320.0, 300.0)]

    puntos = _proyectar_puntos(aqui, todas, None)

    assert [p["posicion"] for p in puntos] == [2]
    assert puntos[0]["az"] == pytest.approx(0.0, abs=0.05)
    # 100 m más abajo y a 500 m: unos 11° bajo el horizonte.
    assert puntos[0]["el"] == pytest.approx(-11.3, abs=0.1)
    assert puntos[0]["distancia_m"] == pytest.approx(500, abs=1)
