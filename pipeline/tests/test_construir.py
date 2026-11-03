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


def test_un_estero_se_proyecta_como_linea_y_se_corta_lejos():
    from pipeline.construir import _proyectar_aguas
    from pipeline.proyeccion import Vista

    aqui = Vista(id="p01-100", posicion=1, lon=-72.0, lat=-35.0, altura_relativa=100.0,
                 altura_absoluta=400.0, rumbo0=0.0)
    norte = lambda m: (-72.0, -35.0 + m / 111320.0)
    # De 100 m a 300 m al norte, y un tramo a 5 km que el visor no muestra.
    aguas = [("Estero", [norte(100), norte(300)]), ("Río lejano", [norte(5000), norte(5100)])]

    proyectadas = _proyectar_aguas(aqui, aguas, None)

    assert [a["nombre"] for a in proyectadas] == ["Estero"]
    tramo = proyectadas[0]["tramos"][0]
    assert len(tramo) > 20                      # densificado para seguir el terreno
    assert all(az == pytest.approx(0.0, abs=0.05) for az, _ in tramo)
    assert tramo[0][1] == pytest.approx(-45.0, abs=0.1) and tramo[-1][1] == pytest.approx(-18.43, abs=0.1)


def test_el_sitio_abre_en_un_punto_con_el_loteo_dibujado():
    from pipeline.construir import _vista_inicial
    vistas = [{"id": "p01", "puntaje_encuadre": 10.0},
              {"id": "p03", "puntaje_encuadre": 0.0, "solo_foto": True}]
    assert _vista_inicial(vistas) == "p01"
    # Si todos son solo foto, igual abre en alguno.
    assert _vista_inicial([vistas[1]]) == "p03"


# --- un despegue por foto ------------------------------------------------------

def _vista_de(tmp_path, nombre, lon, lat):
    from types import SimpleNamespace
    ruta = tmp_path / nombre
    return (SimpleNamespace(ruta=ruta), None,
            SimpleNamespace(id=f"vista-{ruta.stem}", origen=(lon, lat)))


def test_cada_vista_se_mide_desde_el_despegue_de_su_foto(tmp_path):
    from pipeline import config
    from pipeline.construir import Avisos, _despegues_por_vista

    vistas = [_vista_de(tmp_path, "DJI_0487_D.JPG", -71.5970, -33.3500),
              _vista_de(tmp_path, "DJI_0494_D.JPG", -71.6030, -33.3487)]
    proyecto = config.Proyecto(nombre="X", despegues=(("dji_0494_d", (-71.602915, -33.348602)),))
    avisos = Avisos([])

    despegue_de = _despegues_por_vista(proyecto, vistas, (-71.596974, -33.350092), avisos)

    assert despegue_de(vistas[0][2]) == (-71.596974, -33.350092)   # el del proyecto
    assert despegue_de(vistas[1][2]) == (-71.602915, -33.348602)   # el suyo
    assert avisos.lineas == []


def test_avisa_la_foto_que_no_esta_y_el_despegue_al_reves(tmp_path):
    from pipeline import config
    from pipeline.construir import Avisos, _despegues_por_vista

    vistas = [_vista_de(tmp_path, "DJI_0494_D.JPG", -71.6030, -33.3487)]
    proyecto = config.Proyecto(nombre="X", despegues=(
        ("DJI_0494_D", (-33.348602, -71.602915)),   # lat, lon: al revés
        ("DJI_9999_D", (-71.6, -33.35)),
    ))
    avisos = Avisos([])

    _despegues_por_vista(proyecto, vistas, (-71.596974, -33.350092), avisos)

    assert any("al revés" in linea for linea in avisos.lineas)
    assert any("DJI_9999_D" in linea and "ninguna panorámica" in linea for linea in avisos.lineas)


def test_sin_vuelo_y_solo_geo_arma_las_parcelas_sin_vistas(tmp_path):
    """Un loteo sin dron: las parcelas con su forma y estado, y ninguna vista 360."""
    import json
    import zipfile

    from pipeline import construir as modulo
    from pipeline.config import Proyecto, Salida, descubrir_fuentes
    kmz = tmp_path / "fuentes" / "loteo.kmz"
    kmz.parent.mkdir()
    with zipfile.ZipFile(kmz, "w") as archivo:
        archivo.writestr("doc.kml", (
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>LOTE 1</name>'
            '<Polygon><outerBoundaryIs><LinearRing><coordinates>-72,-36 -72.001,-36 '
            '-72.001,-36.001 -72,-36.001 -72,-36</coordinates></LinearRing></outerBoundaryIs>'
            '</Polygon></Placemark></Document></kml>'))
    salida = Salida(tmp_path / "salida")

    with pytest.raises(FileNotFoundError, match="panorámicas"):
        descubrir_fuentes(kmz.parent, sin_crm=True)
    fuentes = descubrir_fuentes(kmz.parent, sin_crm=True, sin_panoramas=True)
    resultado = modulo.construir(fuentes, Proyecto(nombre="Don Danilo"), salida, solo_geo=True)

    assert resultado["parcelas"] == 1 and resultado["vistas"] == 0
    datos = json.loads((salida.datos / "parcelas.json").read_text(encoding="utf-8"))
    assert datos["solo_geo"] is True
    assert datos["parcelas"][0]["id"] == "1" and datos["parcelas"][0]["poligono"]
    assert json.loads((salida.datos / "vistas.json").read_text(encoding="utf-8")) == {
        "inicial": None, "vistas": []}
    # Lleva el visor igual: es el que manda al geo, y republicar lo pone al día.
    assert (salida.web / "index.html").is_file()


# --- un ajuste con los caminos que ninguna otra vista confirma ------------------

from types import SimpleNamespace

from pipeline import construir
from pipeline.calibracion import Ajuste
from pipeline.cruce import Cruce
from pipeline.proyeccion import Vista

INCLINACIONES_CRUCE = {-80.0: (0.0, 0.0), 0.0: (0.3, 0.1), 80.0: (0.6, 0.2)}


def _tres_vistas(desnivel_referencia: float, soles=None):
    def vista(nombre, posicion, desnivel=0.0, giro=0.0):
        return Vista(nombre, posicion, -71.66, -33.73, 400.0, 480.0, 0.0, giro=giro,
                     inclinacion_este=0.3 + 0.3 * desnivel / 80.0,
                     inclinacion_norte=0.1 + 0.1 * desnivel / 80.0, desnivel=desnivel)
    panorama = SimpleNamespace(ruta="foto.JPG")
    # El rumbo solo importa por el error de elevación del sol (ver _rumbo_por_cruces).
    soles = soles or {}
    rumbo = {v: SimpleNamespace(error_elevacion=e) for v, e in soles.items()}
    return [(panorama, rumbo.get("p01"), vista("p01", 1)), (panorama, rumbo.get("p02"), vista("p02", 2)),
            (panorama, rumbo.get("p03"), vista("p03", 3, desnivel_referencia, giro=-0.3))]


def _cruzar(monkeypatch, cruces, ajustes=None, soles=None):
    """`cruces` va de la vista, de (vista, referencia) o de (vista, referencia, desnivel
    de la referencia) al resultado del cruce."""
    def calibrar_contra(vista, panorama, cota, referencia, *resto):
        for clave in ((vista.id, referencia.id, referencia.desnivel), (vista.id, referencia.id), vista.id):
            if clave in cruces:
                return cruces[clave]
        return Cruce(None, motivo="no calza")
    monkeypatch.setattr(construir.cruce, "cargar_panorama", lambda ruta: None)
    monkeypatch.setattr(construir.cruce, "calibrar_contra", calibrar_contra)
    monkeypatch.setattr(construir.terreno, "modelo_para_vista", lambda *a: None)
    ajustes = ajustes or {"p01": Ajuste(tope="giro +1.5°"), "p02": Ajuste(tope="giro +1.5°"),
                          "p03": Ajuste(giro=-0.3, desnivel=73.0, puntaje_antes=1.0, puntaje_despues=1.44)}
    avisos = construir.Avisos([])
    desnivel = 73.0 if ajustes["p03"].aplicado else 0.0
    vistas = construir._cruzar_vistas(_tres_vistas(desnivel, soles), ajustes,
                                      {v: INCLINACIONES_CRUCE for v in ajustes}, object(),
                                      lambda v: (-71.66, -33.73), [[(-71.66, -33.73), (-71.65, -33.72)]],
                                      avisos)
    return {v.id: v for _, _, v in vistas}, avisos


def test_un_desnivel_que_nadie_confirma_no_se_reparte(monkeypatch):
    """Fundo Atalaya: los deslindes del KMZ no se ven en el potrero, el punto III
    eligió +73 m y los otros dos no calzaron contra él. Todo queda sin desnivel."""
    vistas, avisos = _cruzar(monkeypatch, {"p01": Cruce(None, motivo="quedó en el borde de lo probado"),
                                           "p02": Cruce(None, 37, motivo="solo 37 coincidencias")})

    for vista in vistas.values():
        assert vista.desnivel == pytest.approx(0.0)
        assert vista.giro == pytest.approx(0.0)
        assert (vista.inclinacion_este, vista.inclinacion_norte) == pytest.approx((0.3, 0.1))
    assert any("no lo confirma ninguna otra vista" in a for a in avisos.lineas)


def test_si_otra_vista_calza_contra_la_referencia_su_desnivel_vale(monkeypatch):
    """Lomas de Quillón: el punto II calzó contra el I, así que el I queda como estaba."""
    vistas, _ = _cruzar(monkeypatch, {
        "p01": Cruce(Ajuste(desnivel=70.0), 120, 30.0, 4.0),
        "p02": Cruce(None, 37, motivo="solo 37 coincidencias")})

    assert vistas["p03"].desnivel == pytest.approx(73.0)
    assert vistas["p01"].desnivel == pytest.approx(70.0)
    assert vistas["p02"].desnivel == pytest.approx(73.0)


TODAS_AL_TOPE = {"p01": Ajuste(tope="giro +1.5°"), "p02": Ajuste(tope="giro +1.5°"),
                 "p03": Ajuste(tope="desnivel +80 m")}
# Fundo Atalaya: el sol del punto I se midió 1,2° corrido, el del III 0,5° y el del II 0,1°.
SOLES_ATALAYA = {"p01": 1.2, "p02": 0.1, "p03": 0.5}


def _par(giro_ida, giro_vuelta):
    return {("p01", "p03"): Cruce(Ajuste(giro=giro_ida, desnivel=-27.0), 240, 45.0, 2.0),
            ("p03", "p01"): Cruce(Ajuste(giro=giro_vuelta, desnivel=26.0), 230, 48.0, 2.0)}


def test_sin_caminos_el_giro_lo_pone_la_vista_con_el_sol_mejor_medido(monkeypatch):
    """Fundo Atalaya con el despegue real: ninguna vista calibra con los caminos, I y
    III se cruzan bien de ida y de vuelta, y el II no calza con nadie. El I, con el sol
    peor medido, toma el giro; el desnivel no se toca."""
    vistas, avisos = _cruzar(monkeypatch, _par(1.94, -1.92), TODAS_AL_TOPE, SOLES_ATALAYA)

    assert vistas["p01"].giro == pytest.approx(1.94)
    assert vistas["p01"].desnivel == pytest.approx(0.0)
    assert vistas["p03"].giro == pytest.approx(-0.3)
    assert vistas["p02"].giro == pytest.approx(0.0)
    assert any("p01: el rumbo del sol no calzaba con p03" in a for a in avisos.lineas)


def test_un_cruce_que_no_sale_igual_de_vuelta_no_se_cree(monkeypatch):
    """El punto I contra el II dio 2,9° con el dron corrido 38 m, y el II contra el I no
    calzó: ese giro no se aplica."""
    cruces = _par(1.94, -1.0)
    cruces[("p01", "p02")] = Cruce(Ajuste(giro=2.89), 243, 58.0, 5.0)
    vistas, _ = _cruzar(monkeypatch, cruces, TODAS_AL_TOPE, SOLES_ATALAYA)

    assert vistas["p01"].giro == pytest.approx(0.0)
    assert vistas["p03"].giro == pytest.approx(-0.3)


def test_tras_descartar_un_desnivel_sin_confirmar_tambien_se_cruzan(monkeypatch):
    """Fundo Atalaya con el despegue supuesto: el +73 m del punto III se descarta y
    después el I toma el giro del cruce con el III."""
    cruces = _par(1.94, -1.92)
    # Contra el III con +73 m no calza ninguna.
    cruces[("p01", "p03", 73.0)] = Cruce(None, motivo="quedó en el borde de lo probado")
    cruces["p02"] = Cruce(None, 37, motivo="solo 37 coincidencias")
    vistas, _ = _cruzar(monkeypatch, cruces, soles=SOLES_ATALAYA)

    assert vistas["p01"].giro == pytest.approx(1.94)
    assert vistas["p03"].desnivel == pytest.approx(0.0)
    assert vistas["p03"].giro == pytest.approx(0.0)
