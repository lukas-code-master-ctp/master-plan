"""Las fotos comunes de las referencias: van al sitio y no se confunden con el vuelo."""
import json

from PIL import Image

from pipeline import config
from pipeline.construir import LADO_FOTO_REFERENCIA, _con_fotos
from pipeline.referencias import Referencia, proyectar
from pipeline.proyeccion import Vista


def _foto(ruta, tamano=(4000, 3000)):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", tamano, (180, 120, 70)).save(ruta, "JPEG")


def test_las_fotos_de_una_referencia_no_son_panoramicas(tmp_path):
    (tmp_path / "loteo.kmz").write_bytes(b"kmz")
    _foto(tmp_path / "vuelo" / "DJI_0001.JPG", (200, 100))
    _foto(tmp_path / config.CARPETA_FOTOS_REFERENCIAS / "acceso" / "01.jpg", (30, 20))

    fuentes = config.descubrir_fuentes(tmp_path, sin_crm=True)

    # Si las contara, el ancestro común de las "panorámicas" sería la carpeta entera.
    assert fuentes.panoramas == tmp_path / "vuelo"
    assert fuentes.fotos_referencias == tmp_path / config.CARPETA_FOTOS_REFERENCIAS


def test_cada_referencia_lleva_sus_fotos_achicadas_al_sitio(tmp_path):
    carpeta = tmp_path / config.CARPETA_FOTOS_REFERENCIAS
    _foto(carpeta / "acceso" / "01.jpg")
    _foto(carpeta / "acceso" / "03.jpg", (1000, 1500))
    salida = config.Salida(tmp_path / "salida")
    # Una que se quitó en la consola no puede seguir en el sitio.
    _foto(salida.datos / "fotos" / "acceso" / "09.jpg", (10, 10))
    hitos = [Referencia("Acceso", -71.62, -33.355), Referencia("Santiago", -70.65, -33.44)]

    acceso, santiago = _con_fotos(hitos, carpeta, salida)

    assert acceso.fotos == ("datos/fotos/acceso/01.jpg", "datos/fotos/acceso/02.jpg")
    assert santiago.fotos == ()
    assert sorted(p.name for p in (salida.datos / "fotos" / "acceso").iterdir()) == ["01.jpg", "02.jpg"]
    with Image.open(salida.web / acceso.fotos[0]) as grande:
        assert max(grande.size) == LADO_FOTO_REFERENCIA
    with Image.open(salida.web / acceso.fotos[1]) as chica:
        assert chica.size == (1000, 1500)


def test_sin_carpeta_de_fotos_las_referencias_quedan_igual(tmp_path):
    hitos = [Referencia("Acceso", -71.62, -33.355)]

    assert _con_fotos(hitos, None, config.Salida(tmp_path)) == hitos


def test_la_vista_dice_que_la_referencia_tiene_fotos():
    vista = Vista(id="p01", posicion=1, lon=-71.6, lat=-33.35, altura_relativa=100.0,
                  altura_absoluta=200.0, rumbo0=0.0)
    hito = Referencia("Acceso", -71.62, -33.355, fotos=("datos/fotos/acceso/01.jpg",))

    assert proyectar(vista, hito, 0.0)["fotos"] == ["datos/fotos/acceso/01.jpg"]
    assert "fotos" not in proyectar(vista, Referencia("Santiago", -70.65, -33.44), 0.0)
