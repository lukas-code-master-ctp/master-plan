import io
import json

import cv2
import numpy as np
import pymupdf
import pytest
from PIL import Image
from shapely.geometry import Point, Polygon

from pipeline.plano.__main__ import main
from pipeline.plano.digitalizar import digitalizar
from pipeline.tests.plano_sintetico import NEGRO, PPMM, dibujar, iou


def _carpeta(tmp_path):
    """Un PDF con el plano sintético escaneado de lado (hay que girarlo 90° horario
    para leerlo) y un cajetín en el margen que la loteadora tapa con una máscara."""
    plano = dibujar()
    img = plano.imagen.copy()
    cv2.rectangle(img, (1200, 900), (1500, 1010), NEGRO, 2)          # cajetín
    cv2.line(img, (1200, 950), (1500, 950), NEGRO, 2)
    cruda = np.ascontiguousarray(np.rot90(img, k=1))                 # de lado
    buf = io.BytesIO()
    Image.fromarray(cruda).save(buf, "JPEG", quality=95)
    alto, ancho = cruda.shape[:2]
    doc = pymupdf.open()
    hoja = doc.new_page(width=ancho / PPMM / 25.4 * 72, height=alto / PPMM / 25.4 * 72)
    hoja.insert_image(hoja.rect, stream=buf.getvalue())
    doc.save(tmp_path / "plano.pdf")
    entradas = dict(pdf="plano.pdf", pagina=1, rotacion=90,
                    rectangulo=[100, 100, img.shape[1] - 20, img.shape[0] - 5],
                    mascaras=[[1190, 890, 1510, 1020]], esquinas=None, marco_mm=None, cuadricula=None,
                    semillas=[dict(numero=n, x=x, y=y) for n, x, y in plano.semillas],
                    anclas=[])
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")
    return plano


def test_digitalizar_desde_la_carpeta(tmp_path, capsys):
    plano = _carpeta(tmp_path)

    assert main(["digitalizar", str(tmp_path)]) == 0

    lineas = capsys.readouterr().out.strip().splitlines()
    assert len(lineas) >= 6
    assert lineas[0].startswith("Página 1 de 1")
    datos = json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["digitalizado.json", "entradas.json", "plano.pdf"]
    assert datos["pagina"]["rotacion"] == 90
    assert (datos["pagina"]["ancho"], datos["pagina"]["alto"]) == (plano.imagen.shape[1], plano.imagen.shape[0])
    assert abs(datos["pagina"]["ppmm"] - PPMM) < 1e-3
    assert datos["faltantes"] == []
    assert len(datos["lotes"]) == len(plano.semillas)
    for lote in datos["lotes"]:
        p = Polygon(lote["poligono"], lote["huecos"])
        assert p.contains(Point(lote["semilla"]))
        assert iou(p, plano.celdas[lote["numero"]]) > 0.95
    # La homografía lleva de la página al trabajo (un recorte: escala 1 y traslación).
    h = np.array(datos["trabajo"]["homografia"])
    assert np.allclose(h[:2, :2], np.eye(2))
    assert np.allclose(h[:2, 2], [-100, -100])
    # El cajetín quedó tapado: no aparece como cara sin número.
    assert all(Polygon(c["poligono"]).centroid.y < 850 for c in datos["sin_numero"])
    # El camino no es un lote sin número, y la numeración (1…12) no tiene huecos.
    assert datos["huecos"] == []
    assert all(c["de_lote"] is False and c["sugerencia"] is None for c in datos["sin_numero"])


def test_los_huecos_de_la_numeracion_quedan_en_el_digitalizado(tmp_path):
    _carpeta(tmp_path)
    entradas = json.loads((tmp_path / "entradas.json").read_text(encoding="utf-8"))
    entradas["semillas"] = [s for s in entradas["semillas"] if s["numero"] not in ("6", "7")]
    entradas["lector"] = False
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")

    datos = digitalizar(tmp_path, avance=lambda _: None)

    assert datos["huecos"] == ["6", "7"]
    assert json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))["huecos"] == ["6", "7"]


def test_el_resto_de_la_propiedad_sobrevive_a_digitalizar(tmp_path):
    """"Resto" no es un número de lote, pero es el nombre que ella le da al resto de la
    propiedad cuando el cuadro no le da número: queda en su lote al volver a leer."""
    plano = _carpeta(tmp_path)
    entradas = json.loads((tmp_path / "entradas.json").read_text(encoding="utf-8"))
    entradas["semillas"][0]["numero"] = "Resto"
    entradas["lector"] = False
    entradas["fuera"] = [[10, 10]]                        # no cambia cómo se parte
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")

    datos = digitalizar(tmp_path, avance=lambda _: None)

    resto = next(l for l in datos["lotes"] if l["numero"] == "Resto")
    assert iou(Polygon(resto["poligono"], resto["huecos"]), plano.celdas[plano.semillas[0][0]]) > 0.95


def test_sin_entradas(tmp_path, capsys):
    assert main(["digitalizar", str(tmp_path)]) == 2
    assert "entradas.json" in capsys.readouterr().err


def test_sin_semillas_no_hay_lotes_y_no_falla(tmp_path):
    _carpeta(tmp_path)
    entradas = json.loads((tmp_path / "entradas.json").read_text(encoding="utf-8"))
    entradas["semillas"] = []
    entradas["lector"] = False             # sin lector: con Tesseract leería los rótulos
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")

    assert main(["digitalizar", str(tmp_path)]) == 0

    datos = json.loads((tmp_path / "digitalizado.json").read_text(encoding="utf-8"))
    assert datos["lotes"] == [] and datos["faltantes"] == []
    assert len(datos["sin_numero"]) >= 12


@pytest.mark.parametrize("cambio, mensaje", [
    (dict(pdf="otro.pdf"), "no está el PDF del plano: otro.pdf"),
    (dict(pagina=3), "no existe la 3"),
    (dict(pagina="uno"), "«pagina» debe ser un número entero"),
    (dict(rotacion=45), "0, 90, 180 o 270"),
    (dict(rectangulo=[1, 2, 3]), "«rectangulo» debe ser una lista de 4 números"),
    (dict(rectangulo=[500, 500, 100, 100]), "rectángulo del dibujo está vacío"),
    (dict(semillas=[dict(numero="1", y=5)]), "semilla 1: x, y"),
    (dict(semillas=[dict(numero="1", x=5, y=5), dict(numero=1, x=50, y=50)]), "repetidos en las semillas: 1"),
    (dict(esquinas=[[0, 0], [100, 0], [200, 0], [300, 0]]), "no forman un cuadrilátero"),
])
def test_entradas_malas_dan_un_mensaje_claro(tmp_path, capsys, cambio, mensaje):
    _carpeta(tmp_path)
    entradas = json.loads((tmp_path / "entradas.json").read_text(encoding="utf-8"))
    entradas.update(cambio)
    (tmp_path / "entradas.json").write_text(json.dumps(entradas), encoding="utf-8")

    assert main(["digitalizar", str(tmp_path)]) == 1

    assert mensaje in capsys.readouterr().err
    assert not (tmp_path / "digitalizado.json").exists()


def test_pdf_que_no_es_pdf(tmp_path, capsys):
    _carpeta(tmp_path)
    (tmp_path / "plano.pdf").write_bytes(b"no es un pdf")
    assert main(["digitalizar", str(tmp_path)]) == 1
    assert "no se pudo abrir plano.pdf como PDF" in capsys.readouterr().err
