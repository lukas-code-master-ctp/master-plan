"""Los lotes de un geo en PDF con coordenadas, como los exporta ArcMap."""
import pymupdf
import pytest
from pyproj import Transformer

from pipeline import geopdf
from pipeline.kmz import leer_kmz

# 1 punto de página = 1 metro, con la esquina de arriba a la izquierda en este UTM 19S.
ESTE, NORTE = 300_000.0, 6_220_000.0
ANCHO, ALTO = 600.0, 400.0
A_LONLAT = Transformer.from_crs(32719, 4326, always_xy=True)

AMARILLO, CELESTE = (1, 1, 0), (0, 1, 1)


def _lonlat(x, y):
    return A_LONLAT.transform(ESTE + x, NORTE - y)


def geo_pdf(destino=None, *, coordenadas=True, rotulos=True) -> bytes:
    """Dos lotes de 200 × 200 m con borde amarillo; el primero achurado en celeste
    (disponible), como en el geo hecho a mano."""
    documento = pymupdf.open()
    pagina = documento.new_page(width=ANCHO, height=ALTO)
    for x0 in (100, 300):
        for a, b in [((x0, 100), (x0 + 200, 100)), ((x0 + 200, 100), (x0 + 200, 300)),
                     ((x0 + 200, 300), (x0, 300)), ((x0, 300), (x0, 100))]:
            pagina.draw_line(a, b, color=AMARILLO, width=0.72)
    # El achurado cruza el lote entero y lo partiría en tiras si se tomara como borde.
    for d in range(0, 400, 20):
        pagina.draw_line((100 + d, 100), (100, 100 + d), color=CELESTE, width=0.48)
    if rotulos:
        for numero, x0 in (("1", 100), ("2", 300)):
            pagina.insert_textbox(pymupdf.Rect(x0 + 60, 180, x0 + 160, 220), f"LOTE {numero}\n40000M2",
                                  fontsize=8, color=AMARILLO)
    if coordenadas:
        # Como ArcMap: la caja con y hacia arriba, y los GPTS en (lat, lon).
        esquinas = [(0, 1), (0, 0), (1, 0), (1, 1)]
        gpts = []
        for u, v in esquinas:
            lon, lat = _lonlat(u * ANCHO, v * ALTO)
            gpts += [lat, lon]
        medida = documento.get_new_xref()
        documento.update_object(medida, (
            "<< /Type /Measure /Subtype /GEO /Bounds [0 1 0 0 1 0 1 1] "
            f"/GPTS [{' '.join(f'{g:.9f}' for g in gpts)}] "
            f"/LPTS [{' '.join(f'{c}' for u, v in esquinas for c in (u, v))}] >>"))
        documento.xref_set_key(pagina.xref, "VP",
                               f"[<< /Type /Viewport /BBox [0 {ALTO} {ANCHO} 0] /Measure {medida} 0 R >>]")
    contenido = documento.tobytes()
    if destino:
        destino.write_bytes(contenido)
    return contenido


def test_reconoce_un_geo_con_coordenadas():
    assert geopdf.es_geopdf(geo_pdf())
    assert not geopdf.es_geopdf(geo_pdf(coordenadas=False))
    assert not geopdf.es_geopdf(b"no es un pdf")


def test_lee_cada_lote_con_su_numero_su_forma_y_su_superficie():
    lectura = geopdf.leer(geo_pdf())

    assert [l["numero"] for l in lectura.lotes] == ["1", "2"]
    assert [l["area_oficial"] for l in lectura.lotes] == [40000, 40000]
    assert lectura.transformacion.epsg == 32719
    # Los GPTS se escriben con 6 decimales (~0,1 m): el residuo es ese redondeo.
    assert lectura.transformacion.parametros["residuo_m"] < 0.5
    assert lectura.avisos == []


def test_el_kmz_queda_donde_dice_el_pdf(tmp_path):
    geopdf.a_kmz(geo_pdf(), tmp_path / "loteo.kmz")

    lotes = {g.id: g for g in leer_kmz(tmp_path / "loteo.kmz")}
    assert set(lotes) == {"1", "2"}
    # El achurado no partió el lote: mide lo que dice el geo.
    assert lotes["1"].area_m2 == pytest.approx(40_000, rel=0.01)
    lon, lat = _lonlat(200, 200)
    assert lotes["1"].centroide[0] == pytest.approx(lon, abs=1e-5)
    assert lotes["1"].centroide[1] == pytest.approx(lat, abs=1e-5)


def test_sin_coordenadas_o_sin_rotulos_dice_que_vaya_a_crea_tu_kmz(tmp_path):
    with pytest.raises(geopdf.NoEsGeoPdf, match="Crea tu KMZ"):
        geopdf.leer(geo_pdf(coordenadas=False))
    with pytest.raises(ValueError, match="LOTE n"):
        geopdf.leer(geo_pdf(rotulos=False))


def test_la_linea_de_comandos_escribe_el_kmz(tmp_path, capsys):
    geo_pdf(tmp_path / "geo.pdf")

    assert geopdf.main([str(tmp_path / "geo.pdf"), str(tmp_path / "loteo.kmz")]) == 0
    assert "2 lotes" in capsys.readouterr().out
    assert (tmp_path / "loteo.kmz").is_file()
