import io
import json

import pymupdf
from PIL import Image

from pipeline import geo_pintado

CUADRADO = [[-72.0, -36.0], [-71.999, -36.0], [-71.999, -35.999], [-72.0, -35.999]]


def datos(*estados):
    return {"proyecto": "Hacienda Demo", "actualizado": "2026-10-27T13:40:00+00:00",
            "parcelas": [{"id": f"A{i + 1}", "estado": estado,
                          "poligono": [[x + 0.0012 * i, y] for x, y in CUADRADO]}
                         for i, estado in enumerate(estados)]}


def texto(ruta):
    return pymupdf.open(ruta)[0].get_text()


def test_cada_lote_lleva_su_nombre_y_la_leyenda_cuenta_las_disponibles(tmp_path):
    ruta = geo_pintado.generar(datos("disponible", "vendido", "reservado"), tmp_path / "geo.pdf", None)

    contenido = texto(ruta)
    assert all(f"LOTE A{n}" in contenido for n in (1, 2, 3))
    assert "Disponible (1)" in contenido
    assert "Vendido, reservado o no disponible (2)" in contenido
    assert "Hacienda Demo" in contenido


def test_la_fecha_va_en_hora_de_chile():
    # 13:40 UTC son las 10:40 en Santiago (horario de verano, UTC-3).
    assert geo_pintado.fecha_legible({"actualizado": "2026-10-27T13:40:00+00:00"}) \
        == "27 de octubre de 2026, 10:40"


def test_con_satelite_la_imagen_va_de_fondo(tmp_path):
    pedidas = []

    def teselas(z, x, y):
        pedidas.append((z, x, y))
        salida = io.BytesIO()
        Image.new("RGB", (256, 256), (30, 80, 30)).save(salida, "JPEG")
        return salida.getvalue()

    ruta = geo_pintado.generar(datos("disponible"), tmp_path / "geo.pdf", teselas)

    assert pedidas and len({z for z, _, _ in pedidas}) == 1
    assert pymupdf.open(ruta)[0].get_images()
    assert "Esri" in texto(ruta)


def test_sin_satelite_sale_igual(tmp_path):
    ruta = geo_pintado.generar(datos("disponible"), tmp_path / "geo.pdf", lambda z, x, y: None)

    assert not pymupdf.open(ruta)[0].get_images()
    assert "Sin imagen satelital" in texto(ruta)


def test_al_dia_no_rehace_si_el_inventario_no_cambio(tmp_path):
    (tmp_path / "datos").mkdir()
    (tmp_path / "datos" / "parcelas.json").write_text(json.dumps(datos("disponible")))
    primero = geo_pintado.al_dia(tmp_path, None)
    antes = primero.stat().st_mtime_ns

    assert geo_pintado.al_dia(tmp_path, None).stat().st_mtime_ns == antes


def test_un_geo_que_falla_no_corta_la_publicacion(tmp_path, capsys):
    (tmp_path / "datos").mkdir()
    (tmp_path / "datos" / "parcelas.json").write_text(json.dumps({"parcelas": []}))

    assert geo_pintado.main([str(tmp_path), "--sin-satelite"]) == 0
    assert "No se pudo hacer el geo" in capsys.readouterr().err


def test_los_rotulos_son_chicos_y_del_mismo_tamano_aunque_un_lote_sea_enorme(tmp_path):
    # Antes cada rótulo llenaba su lote: el lote grande salía con letras enormes.
    lado = 0.001
    chicos = [{"id": f"A{i + 1}", "estado": "vendido",
               "poligono": [[x + 0.0012 * i, y] for x, y in CUADRADO]} for i in range(6)]
    grande = {"id": "A7", "estado": "disponible",
              "poligono": [[-72.0, -36.01], [-72.0 + 10 * lado, -36.01],
                           [-72.0 + 10 * lado, -36.01 + 6 * lado], [-72.0, -36.01 + 6 * lado]]}
    ruta = geo_pintado.generar({"proyecto": "Hacienda Demo", "parcelas": chicos + [grande]},
                               tmp_path / "geo.pdf", None)

    tamanos = {span["text"]: span["size"]
               for bloque in pymupdf.open(ruta)[0].get_text("dict")["blocks"]
               for linea in bloque.get("lines", []) for span in linea["spans"]
               if span["text"].startswith("LOTE")}
    assert len(tamanos) == 7
    assert max(tamanos.values()) <= geo_pintado.TAMANO_ROTULO_MAX + 0.01
    assert abs(tamanos["LOTE A7"] - tamanos["LOTE A1"]) < 0.01
