"""Poner al día estados y precios de un sitio construido, sin reconstruirlo."""
import json

from pipeline import config
from pipeline.inventario import actualizar

POLIGONO = [[-72.0, -35.0], [-72.0, -35.001], [-72.001, -35.001]]


def sitio(tmp_path, parcelas):
    salida = config.Salida(tmp_path / "salida")
    salida.datos.mkdir(parents=True)
    (salida.datos / "parcelas.json").write_text(json.dumps({
        "generado": "2026-10-01T10:00:00-03:00",
        "resumen": {"total": len(parcelas), "con_geometria": len(parcelas),
                    "con_vista_aerea": len(parcelas), "por_estado": {}},
        "parcelas": parcelas,
    }), encoding="utf-8")
    return salida


def parcela(id_, estado="no_disponible", en_planilla=False, precio=None, poligono=True):
    return {"id": id_, "estado": estado, "superficie_m2": 5000, "servidumbre_m": None,
            "servidumbre_m2": None, "precio": precio, "moneda": "CLP", "link_pago": None,
            "en_planilla": en_planilla, "area_kmz_m2": 5000,
            "poligono": POLIGONO if poligono else None, "mejor_vista": "p01" if poligono else None}


def fuentes_con(tmp_path, csv):
    (tmp_path / "fuentes").mkdir(exist_ok=True)
    (tmp_path / "fuentes" / "inventario.csv").write_text(csv, encoding="utf-8")
    return config.Fuentes(kmz=tmp_path / "x.kmz", panoramas=tmp_path,
                          excel=tmp_path / "fuentes" / "inventario.csv")


def proyecto(tmp_path):
    return config.cargar_proyecto(tmp_path / "fuentes", nombre="Loteo")


def leer(salida):
    return json.loads((salida.datos / "parcelas.json").read_text(encoding="utf-8"))


def test_cambia_solo_los_datos_comerciales_y_el_resumen(tmp_path):
    salida = sitio(tmp_path, [parcela("1"), parcela("2"), parcela("3")])
    fuentes = fuentes_con(tmp_path, "Parcela,Estado,Precio,Superficie m2,Servidumbre m2\n"
                                    "1,Disponible,9990000,5002,940\n2,Vendido,,5100,\n")

    resultado = actualizar(fuentes, proyecto(tmp_path), salida)

    datos = leer(salida)
    por_id = {p["id"]: p for p in datos["parcelas"]}
    assert resultado.cambiadas == ("1", "2") and not resultado.requiere_reconstruir
    assert (por_id["1"]["estado"], por_id["1"]["precio"], por_id["1"]["superficie_m2"],
            por_id["1"]["servidumbre_m2"]) == ("disponible", 9990000, 5002, 940)
    assert por_id["2"]["estado"] == "vendido"
    # La 3 no está en la planilla: queda como no disponible, con la superficie del KMZ.
    assert por_id["3"]["estado"] == "no_disponible" and por_id["3"]["superficie_m2"] == 5000
    # El dibujo no se toca.
    assert por_id["1"]["poligono"] == POLIGONO and por_id["1"]["mejor_vista"] == "p01"
    assert datos["resumen"]["por_estado"] == {"disponible": 1, "vendido": 1, "no_disponible": 1}
    assert datos["generado"] == "2026-10-01T10:00:00-03:00" and datos["actualizado"]


def test_sin_cambios_no_reescribe_nada(tmp_path):
    salida = sitio(tmp_path, [parcela("1", "disponible", en_planilla=True, precio=9990000.0)])
    fuentes = fuentes_con(tmp_path, "Parcela,Estado,Precio,Superficie m2\n1,Disponible,9990000,5000\n")
    antes = (salida.datos / "parcelas.json").read_text(encoding="utf-8")

    resultado = actualizar(fuentes, proyecto(tmp_path), salida)

    assert resultado.cambiadas == ()
    assert (salida.datos / "parcelas.json").read_text(encoding="utf-8") == antes


def test_una_parcela_que_el_sitio_no_tiene_pide_reconstruir_y_no_escribe(tmp_path):
    salida = sitio(tmp_path, [parcela("1")])
    fuentes = fuentes_con(tmp_path, "Parcela,Estado\n1,Disponible\n99,Disponible\n")
    antes = (salida.datos / "parcelas.json").read_text(encoding="utf-8")

    resultado = actualizar(fuentes, proyecto(tmp_path), salida)

    assert resultado.requiere_reconstruir and resultado.faltan == ("99",)
    assert (salida.datos / "parcelas.json").read_text(encoding="utf-8") == antes


def test_una_parcela_que_solo_existia_por_la_planilla_tambien_pide_reconstruir(tmp_path):
    salida = sitio(tmp_path, [parcela("1"), parcela("7", "disponible", en_planilla=True, poligono=False)])
    fuentes = fuentes_con(tmp_path, "Parcela,Estado\n1,Disponible\n")

    assert actualizar(fuentes, proyecto(tmp_path), salida).faltan == ("7",)


def test_lo_que_el_dibujo_dice_no_en_venta_se_mantiene_sin_ficha(tmp_path):
    salida = sitio(tmp_path, [parcela("1"), parcela("2", "no_en_venta")])
    fuentes = fuentes_con(tmp_path, "Parcela,Estado\n1,Disponible\n")

    actualizar(fuentes, proyecto(tmp_path), salida)

    assert {p["id"]: p["estado"] for p in leer(salida)["parcelas"]} == {"1": "disponible", "2": "no_en_venta"}
