"""La portada de Mis planos y el precio desde."""
import json
import os

from PIL import Image

from consola.portada import ANCHO_PORTADA, _azimut_medio, portada
from consola.proyectos import precio_desde
from pipeline import config


def construido(tmp_path, rumbo0=0.0, azimuts=(80, 100), anillo=None):
    """Una salida mínima: una vista con una panorámica y una parcela."""
    salida = config.Salida(tmp_path / "salida")
    (salida.panoramas / "p01-210").mkdir(parents=True)
    salida.vistas.mkdir(parents=True)
    # La mitad izquierda roja y la derecha azul, para saber qué lado se recortó.
    panoramica = Image.new("RGB", (2048, 1024), (200, 0, 0))
    panoramica.paste((0, 0, 200), (1024, 0, 2048, 1024))
    panoramica.save(salida.panoramas / "p01-210" / "previa.jpg")
    if anillo is None:
        izquierda, derecha = azimuts
        anillo = [[izquierda, -30], [derecha, -30], [derecha, -50], [izquierda, -50]]
    (salida.vistas / "p01-210.json").write_text(json.dumps({"parcelas": [{"anillo": anillo}]}))
    (salida.datos / "vistas.json").write_text(json.dumps(
        {"inicial": "p01-210", "vistas": [{"id": "p01-210", "rumbo0": rumbo0}]}))
    return salida


def test_sin_construir_no_hay_portada(tmp_path):
    assert portada(config.Salida(tmp_path / "nada")) is None


def test_la_portada_es_un_recorte_apaisado(tmp_path):
    archivo = portada(construido(tmp_path))

    with Image.open(archivo) as imagen:
        assert imagen.size == (ANCHO_PORTADA, 720)


def test_la_portada_mira_hacia_donde_esta_el_loteo(tmp_path):
    # Con rumbo0 = 0 la columna x de la panorámica es el azimut: el loteo entre
    # 260° y 280° cae en la mitad azul.
    archivo = portada(construido(tmp_path, azimuts=(260, 280)))

    with Image.open(archivo) as imagen:
        rojo, _, azul = imagen.getpixel((ANCHO_PORTADA // 2, 100))
    assert azul > rojo


def test_un_loteo_que_cruza_el_borde_no_queda_partido(tmp_path):
    archivo = portada(construido(tmp_path, azimuts=(350, 10)))

    with Image.open(archivo) as imagen:
        # El centro del recorte es el azimut 0: justo el borde entre azul y rojo.
        izquierda = imagen.getpixel((ANCHO_PORTADA // 2 - 20, 100))
        derecha = imagen.getpixel((ANCHO_PORTADA // 2 + 20, 100))
    assert izquierda[2] > izquierda[0]
    assert derecha[0] > derecha[2]


def test_la_portada_se_reusa_hasta_que_se_reconstruye(tmp_path):
    salida = construido(tmp_path)
    archivo = portada(salida)
    antes = archivo.stat().st_mtime_ns
    assert portada(salida).stat().st_mtime_ns == antes

    vistas = salida.datos / "vistas.json"
    os.utime(vistas, ns=(antes + 10**9, antes + 10**9))

    assert portada(salida).stat().st_mtime_ns != antes


def test_una_construccion_sin_imagenes_no_rompe(tmp_path):
    salida = construido(tmp_path)
    (salida.panoramas / "p01-210" / "previa.jpg").unlink()

    assert portada(salida) is None


def test_el_promedio_de_azimuts_da_la_vuelta():
    assert round(_azimut_medio([350, 10])) % 360 == 0
    assert round(_azimut_medio([80, 100])) == 90


# --- precio desde ---------------------------------------------------------------

def test_precio_desde_mira_solo_las_disponibles_con_precio():
    parcelas = [
        {"estado": "disponible", "precio": 20, "moneda": "CLP"},
        {"estado": "disponible", "precio": 0, "moneda": "CLP"},
        {"estado": "vendido", "precio": 1, "moneda": "CLP"},
        {"estado": "disponible", "precio": 15, "moneda": "CLP"},
    ]

    assert precio_desde(parcelas) == {"monto": 15, "moneda": "CLP"}


def test_con_monedas_mezcladas_manda_la_que_mas_se_ve():
    parcelas = [
        {"estado": "disponible", "precio": 900, "moneda": "UF"},
        {"estado": "disponible", "precio": 950, "moneda": "UF"},
        {"estado": "disponible", "precio": 30_000_000, "moneda": "CLP"},
    ]

    assert precio_desde(parcelas) == {"monto": 900, "moneda": "UF"}


def test_sin_nada_disponible_no_hay_precio_desde():
    assert precio_desde([]) is None
    assert precio_desde([{"estado": "reservado", "precio": 10, "moneda": "CLP"}]) is None


def test_un_loteo_ancho_y_disparejo_no_deja_franjas_negras(tmp_path):
    # Casi todo el loteo en un punto y una esquina lejos: el promedio de azimuts
    # queda cerca del grueso, el recorte se centra en el medio de los extremos,
    # y sin acotarlo se sale por la derecha de la panorámica.
    anillo = [[0, -40]] * 8 + [[179, -40], [355, -40]]
    salida = construido(tmp_path, anillo=anillo)

    with Image.open(portada(salida)) as imagen:
        borde = imagen.getpixel((ANCHO_PORTADA - 3, 100))
    assert sum(borde) > 60


def test_no_quedan_temporales_de_la_portada(tmp_path):
    salida = construido(tmp_path)

    portada(salida)

    assert [p.name for p in salida.base.iterdir() if p.name.startswith(".")] == []
