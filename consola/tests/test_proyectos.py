"""Registro de proyectos de la consola."""
import json

import pytest

from consola.proyectos import Registro, Subida


@pytest.fixture
def registro(tmp_path):
    return Registro(archivo=tmp_path / "proyectos.json", subidas=tmp_path / "proyectos")


def carpeta_de_loteo(raiz, nombre="Loteo", con_proyecto_json=True):
    carpeta = raiz / nombre
    (carpeta / "fotos").mkdir(parents=True)
    (carpeta / "loteo.kmz").write_bytes(b"kmz")
    (carpeta / "fotos" / "a.JPG").write_bytes(b"jpg")
    if con_proyecto_json:
        (carpeta / "proyecto.json").write_text(json.dumps({"nombre": nombre}), encoding="utf-8")
    return carpeta


def test_al_principio_no_hay_proyectos(registro):
    assert registro.listar() == []


def test_vincular_una_carpeta_del_disco(registro, tmp_path):
    carpeta = carpeta_de_loteo(tmp_path, "Praderas de Cauquenes")

    proyecto = registro.vincular(carpeta)

    assert proyecto.slug == "praderas-de-cauquenes"
    assert proyecto.fuentes == carpeta
    assert [p.slug for p in registro.listar()] == ["praderas-de-cauquenes"]


def test_vincular_dos_veces_la_misma_carpeta_no_la_duplica(registro, tmp_path):
    carpeta = carpeta_de_loteo(tmp_path)
    registro.vincular(carpeta)
    registro.vincular(carpeta)

    assert len(registro.listar()) == 1


def test_el_registro_sobrevive_a_reiniciar(registro, tmp_path):
    registro.vincular(carpeta_de_loteo(tmp_path))

    otro = Registro(archivo=registro.archivo, subidas=registro.subidas)

    assert [p.slug for p in otro.listar()] == ["loteo"]


def test_una_carpeta_sin_kmz_no_se_vincula(registro, tmp_path):
    vacia = tmp_path / "vacia"
    vacia.mkdir()

    with pytest.raises(ValueError, match="KMZ"):
        registro.vincular(vacia)


def test_una_carpeta_que_no_existe_avisa(registro, tmp_path):
    with pytest.raises(FileNotFoundError):
        registro.vincular(tmp_path / "no-esta")


def test_crear_un_proyecto_desde_archivos_subidos(registro):
    proyecto = registro.crear("Vive Cauquenes", [
        Subida("loteo.kmz", b"kmz"),
        Subida("POSICION 01/DJI_0001.JPG", b"jpg"),
        Subida("POSICION 02/DJI_0002.JPG", b"jpg"),
    ])

    assert proyecto.slug == "vive-cauquenes"
    assert (proyecto.fuentes / "loteo.kmz").read_bytes() == b"kmz"
    # La estructura de carpetas se conserva: de ahí sale la posición de vuelo.
    assert (proyecto.fuentes / "POSICION 02" / "DJI_0002.JPG").exists()
    assert json.loads((proyecto.fuentes / "proyecto.json").read_text())["nombre"] == "Vive Cauquenes"


def test_las_rutas_de_la_subida_no_pueden_escaparse(registro):
    with pytest.raises(ValueError, match="ruta"):
        registro.crear("X", [Subida("../../fuera.kmz", b"x")])


def test_subir_sin_kmz_avisa(registro):
    with pytest.raises(ValueError, match="KMZ"):
        registro.crear("X", [Subida("fotos/a.JPG", b"jpg")])


def test_ajustar_reescribe_proyecto_json(registro, tmp_path):
    proyecto = registro.vincular(carpeta_de_loteo(tmp_path))

    actualizado = registro.ajustar(proyecto.slug, {
        "etapa": "Etapa 1", "whatsapp": "56911111111",
        "despegue": [-72.1, -35.9], "referencias": ["Cauquenes"],
    })

    guardado = json.loads((proyecto.fuentes / "proyecto.json").read_text(encoding="utf-8"))
    assert guardado["etapa"] == "Etapa 1"
    assert guardado["despegue"] == [-72.1, -35.9]
    assert guardado["nombre"] == "Loteo"          # lo que no se toca se conserva
    assert actualizado.etapa == "Etapa 1"


def test_cambiar_el_nombre_no_cambia_el_slug_del_proyecto_ya_creado(registro, tmp_path):
    """El slug es la carpeta de salida y la URL: renombrar no debe dejar huérfano el sitio."""
    proyecto = registro.vincular(carpeta_de_loteo(tmp_path))

    actualizado = registro.ajustar(proyecto.slug, {"nombre": "Otro Nombre"})

    assert actualizado.slug == "loteo"
    assert actualizado.nombre == "Otro Nombre"


def test_olvidar_saca_el_proyecto_pero_no_borra_los_archivos(registro, tmp_path):
    carpeta = carpeta_de_loteo(tmp_path)
    registro.vincular(carpeta)

    registro.olvidar("loteo")

    assert registro.listar() == []
    assert (carpeta / "loteo.kmz").exists()


def test_las_panoramicas_repetidas_se_cuentan_una_vez(registro, tmp_path):
    """El volcado de la tarjeta suele dejar la misma foto en dos carpetas; el
    pipeline la toma una sola vez y el conteo tiene que decir lo mismo."""
    carpeta = tmp_path / "Vuelo"
    (carpeta / "360").mkdir(parents=True)
    (carpeta / "Dron").mkdir(parents=True)
    (carpeta / "loteo.kmz").write_bytes(b"kmz")
    for sub in ("360", "Dron"):
        (carpeta / sub / "DJI_0246.JPG").write_bytes(b"x" * 2_000_000)
    (carpeta / "360" / "DJI_0247.JPG").write_bytes(b"y" * 1_000_000)

    hallado = registro.vincular(carpeta).fuentes_encontradas()

    assert hallado["panoramicas"] == 2
    assert hallado["megas"] == 3


def test_el_registro_por_defecto_vive_junto_a_los_datos(monkeypatch, tmp_path):
    import importlib

    from consola import proyectos as modulo
    from pipeline import config as ajustes
    monkeypatch.setenv("MASTERPLAN_DATOS", str(tmp_path))
    importlib.reload(ajustes)
    recargado = importlib.reload(modulo)
    try:
        assert recargado.ARCHIVO_REGISTRO == tmp_path / "proyectos.json"
        assert recargado.CARPETA_SUBIDAS == tmp_path / "proyectos"
    finally:
        monkeypatch.delenv("MASTERPLAN_DATOS")
        importlib.reload(ajustes)
        importlib.reload(modulo)


# --- identidad en el hosting ----------------------------------------------------

def test_un_proyecto_nuevo_no_tiene_hosting_todavia(registro, tmp_path):
    proyecto = registro.vincular(carpeta_de_loteo(tmp_path))

    assert proyecto.vercel_proyecto is None
    assert proyecto.url_publicada is None
    assert proyecto.publicado is False


def test_al_publicar_se_guarda_el_nombre_y_la_url_reales(registro, tmp_path):
    """No se adivinan: las dice el hosting y quedan escritas."""
    registro.vincular(carpeta_de_loteo(tmp_path))

    proyecto = registro.anotar_publicacion(
        "loteo", vercel_proyecto="masterplan-loteo", url="https://masterplan-loteo.vercel.app")

    assert proyecto.vercel_proyecto == "masterplan-loteo"
    assert proyecto.url_publicada == "https://masterplan-loteo.vercel.app"
    assert proyecto.publicado is True
    assert registro.ver("loteo").url_publicada == "https://masterplan-loteo.vercel.app"


def test_un_loteo_ya_publicado_conserva_su_nombre_en_el_hosting(registro, tmp_path):
    """El sitio de CTP sigue en masterplan-praderas-de-cauquenes aunque el esquema
    de nombres cambie: el nombre está guardado, no derivado."""
    carpeta = carpeta_de_loteo(tmp_path, "Praderas de Cauquenes")
    (carpeta / "proyecto.json").write_text(json.dumps({
        "nombre": "Praderas de Cauquenes",
        "slug": "praderas-de-cauquenes",
        "vercel_proyecto": "masterplan-praderas-de-cauquenes",
        "url_publicada": "https://masterplan-praderas-de-cauquenes.vercel.app",
    }), encoding="utf-8")

    proyecto = registro.vincular(carpeta)

    assert proyecto.slug == "praderas-de-cauquenes"
    assert proyecto.vercel_proyecto == "masterplan-praderas-de-cauquenes"


def test_ajustar_no_borra_lo_que_sabe_del_hosting(registro, tmp_path):
    registro.vincular(carpeta_de_loteo(tmp_path))
    registro.anotar_publicacion("loteo", vercel_proyecto="masterplan-loteo",
                                url="https://masterplan-loteo.vercel.app")

    registro.ajustar("loteo", {"etapa": "Etapa 2"})

    assert registro.ver("loteo").vercel_proyecto == "masterplan-loteo"


# --- el CRM es de cada cliente, nunca global -------------------------------------

def test_un_loteo_usa_el_crm_que_tiene_en_su_carpeta(registro, tmp_path):
    carpeta = carpeta_de_loteo(tmp_path)
    (carpeta / "crm.csv").write_text("Parcela\n", encoding="utf-8")

    assert registro.vincular(carpeta).crm == carpeta / "crm.csv"


def test_sin_crm_propio_un_loteo_no_hereda_el_de_nadie(registro, tmp_path):
    """Un cliente sin planilla publica sus parcelas como no disponibles, que es
    honesto. Lo que no puede pasar es que muestre los precios de otro."""
    assert registro.vincular(carpeta_de_loteo(tmp_path)).crm is None


def test_en_este_computador_se_puede_fijar_un_crm_por_defecto(tmp_path):
    """El dueño trabaja con el export de su CRM al lado; en el servidor no hay tal cosa."""
    global_csv = tmp_path / "ctp_parcelas_latest.csv"
    global_csv.write_text("Parcela\n", encoding="utf-8")
    propio = Registro(archivo=tmp_path / "p.json", subidas=tmp_path / "p",
                      salidas=tmp_path / "s", crm_por_defecto=global_csv)

    assert propio.vincular(carpeta_de_loteo(tmp_path)).crm == global_csv
