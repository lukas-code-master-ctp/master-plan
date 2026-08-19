import pytest

from pipeline.config import descubrir_fuentes


def armar(carpeta, kmz="loteo.kmz", excel="parcelas.xlsx", fotos=("fotos/a.JPG",)):
    if kmz:
        (carpeta / kmz).write_bytes(b"kmz")
    if excel:
        (carpeta / excel).write_bytes(b"xlsx")
    for foto in fotos:
        destino = carpeta / foto
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"jpg")
    return carpeta


def test_encuentra_las_tres_fuentes(tmp_path):
    armar(tmp_path)

    fuentes = descubrir_fuentes(tmp_path)

    assert fuentes.kmz.name == "loteo.kmz"
    assert fuentes.excel.name == "parcelas.xlsx"
    assert fuentes.panoramas == tmp_path / "fotos"


def test_no_depende_de_como_se_llamen_los_archivos(tmp_path):
    armar(tmp_path, kmz="Talhuenes Quella Subdividido 30 Ha (1).kmz",
          excel="datos vs 3 FINAL.xlsx", fotos=("Imagenes/POS 1/x.jpg",))

    fuentes = descubrir_fuentes(tmp_path)

    assert fuentes.kmz.name.startswith("Talhuenes")
    assert fuentes.excel.name.startswith("datos")
    assert fuentes.panoramas == tmp_path / "Imagenes" / "POS 1"


def test_toma_el_ancestro_comun_cuando_hay_varias_posiciones(tmp_path):
    armar(tmp_path, fotos=("vuelo/POSICION 01/a.JPG", "vuelo/POSICION 02/b.JPG"))

    assert descubrir_fuentes(tmp_path).panoramas == tmp_path / "vuelo"


def test_ignora_los_temporales_de_excel(tmp_path):
    armar(tmp_path, excel="real.xlsx")
    (tmp_path / "~$real.xlsx").write_bytes(b"temporal")

    assert descubrir_fuentes(tmp_path).excel.name == "real.xlsx"


def test_encuentra_fuentes_en_subcarpetas(tmp_path):
    (tmp_path / "planos").mkdir()
    (tmp_path / "planos" / "loteo.kmz").write_bytes(b"kmz")
    (tmp_path / "comercial").mkdir()
    (tmp_path / "comercial" / "parcelas.xlsx").write_bytes(b"xlsx")
    armar(tmp_path, kmz=None, excel=None)

    fuentes = descubrir_fuentes(tmp_path)

    assert fuentes.kmz.parent.name == "planos"
    assert fuentes.excel.parent.name == "comercial"


@pytest.mark.parametrize("falta,mensaje", [
    ("kmz", "KMZ"),
    ("excel", "planilla"),
    ("fotos", "panorámicas"),
])
def test_avisa_con_claridad_lo_que_falta(tmp_path, falta, mensaje):
    armar(tmp_path,
          kmz=None if falta == "kmz" else "loteo.kmz",
          excel=None if falta == "excel" else "parcelas.xlsx",
          fotos=() if falta == "fotos" else ("fotos/a.JPG",))

    with pytest.raises(FileNotFoundError, match=mensaje):
        descubrir_fuentes(tmp_path)


def test_avisa_si_la_carpeta_no_existe(tmp_path):
    with pytest.raises(FileNotFoundError, match="no existe la carpeta"):
        descubrir_fuentes(tmp_path / "no-esta")
