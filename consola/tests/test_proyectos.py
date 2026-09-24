"""Los loteos de la consola, y que cada cliente vea solo los suyos."""
import json

import pytest

from consola.acceso import Sesion
from consola.datos import Base, NoEncontrado, ProyectoYaExiste
from consola.proyectos import Registro, Subida


@pytest.fixture
def base(tmp_path):
    return Base(f"sqlite:///{tmp_path / 'consola.db'}")


@pytest.fixture
def registro(base, tmp_path):
    return Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas")


def sesion_de(base, email):
    usuario = base.usuario_por_email(email)
    return Sesion(usuario_id=usuario.id, cliente_id=usuario.cliente_id,
                  rol=usuario.rol, quien=usuario.email)


def loteadora(base, registro, nombre, email):
    base.crear_cliente(nombre, email, "Quien Sea")
    return registro.para(sesion_de(base, email))


@pytest.fixture
def ana(base, registro):
    """La vista de una loteadora cualquiera."""
    return loteadora(base, registro, "Los Robles", "ana@losrobles.cl")


@pytest.fixture
def luis(base, registro):
    """La de otra, para probar que no se cruzan."""
    return loteadora(base, registro, "Del Valle", "luis@delvalle.cl")


@pytest.fixture
def ctp(base, registro):
    """El equipo de CompraTuParcela, que opera todas."""
    base.crear_cliente("CompraTuParcela", "eduardo@ctp.cl", "Eduardo")
    base.ascender_a_plataforma("eduardo@ctp.cl")
    return registro.para(sesion_de(base, "eduardo@ctp.cl"))


def carpeta_de_loteo(raiz, nombre="Loteo", con_proyecto_json=True):
    carpeta = raiz / nombre
    (carpeta / "fotos").mkdir(parents=True)
    (carpeta / "loteo.kmz").write_bytes(b"kmz")
    (carpeta / "fotos" / "a.JPG").write_bytes(b"jpg")
    if con_proyecto_json:
        (carpeta / "proyecto.json").write_text(json.dumps({"nombre": nombre}), encoding="utf-8")
    return carpeta


# --- lo de siempre ---------------------------------------------------------------

def test_al_principio_no_hay_proyectos(ana):
    assert ana.listar() == []


def test_vincular_una_carpeta_del_disco(ana, tmp_path):
    carpeta = carpeta_de_loteo(tmp_path, "Praderas de Cauquenes")

    proyecto = ana.vincular(carpeta)

    assert proyecto.slug == "praderas-de-cauquenes"
    assert proyecto.fuentes == carpeta
    assert [p.slug for p in ana.listar()] == ["praderas-de-cauquenes"]


def test_vincular_dos_veces_la_misma_carpeta_no_la_duplica(ana, tmp_path):
    carpeta = carpeta_de_loteo(tmp_path)
    ana.vincular(carpeta)
    ana.vincular(carpeta)

    assert len(ana.listar()) == 1


def test_el_registro_sobrevive_a_reiniciar(base, registro, ana, tmp_path):
    ana.vincular(carpeta_de_loteo(tmp_path))

    otra = Registro(base=Base(f"sqlite:///{tmp_path / 'consola.db'}"),
                    subidas=registro.subidas, salidas=registro.salidas)

    assert [p.slug for p in otra.para(sesion_de(base, "ana@losrobles.cl")).listar()] == ["loteo"]


def test_una_carpeta_sin_kmz_no_se_vincula(ana, tmp_path):
    vacia = tmp_path / "vacia"
    vacia.mkdir()

    with pytest.raises(ValueError, match="KMZ"):
        ana.vincular(vacia)


def test_una_carpeta_que_no_existe_avisa(ana, tmp_path):
    with pytest.raises(FileNotFoundError):
        ana.vincular(tmp_path / "no-esta")


def test_crear_un_proyecto_desde_archivos_subidos(ana):
    proyecto = ana.crear("Vive Cauquenes", [
        Subida("loteo.kmz", b"kmz"),
        Subida("POSICION 01/DJI_0001.JPG", b"jpg"),
        Subida("POSICION 02/DJI_0002.JPG", b"jpg"),
    ])

    assert proyecto.slug == "vive-cauquenes"
    assert (proyecto.fuentes / "loteo.kmz").read_bytes() == b"kmz"
    # La estructura de carpetas se conserva: de ahí sale la posición de vuelo.
    assert (proyecto.fuentes / "POSICION 02" / "DJI_0002.JPG").exists()
    assert json.loads((proyecto.fuentes / "proyecto.json").read_text())["nombre"] == "Vive Cauquenes"


def test_las_rutas_de_la_subida_no_pueden_escaparse(ana):
    with pytest.raises(ValueError, match="ruta"):
        ana.crear("X", [Subida("loteo.kmz", b"kmz"), Subida("../../fuera.jpg", b"x")])


def test_una_subida_que_falla_no_deja_el_loteo_anotado(ana):
    """Si quedara anotado y vacío, el nombre quedaría tomado y no se podría reintentar."""
    with pytest.raises(ValueError):
        ana.crear("X", [Subida("loteo.kmz", b"kmz"), Subida("../../fuera.jpg", b"x")])

    assert ana.listar() == []
    assert ana.crear("X", [Subida("loteo.kmz", b"kmz")]).slug == "x"


def test_subir_sin_kmz_avisa(ana):
    with pytest.raises(ValueError, match="KMZ"):
        ana.crear("X", [Subida("fotos/a.JPG", b"jpg")])


def test_el_mismo_cliente_no_puede_subir_dos_loteos_con_el_mismo_nombre(ana):
    ana.crear("Las Araucarias", [Subida("loteo.kmz", b"kmz")])

    with pytest.raises(ProyectoYaExiste):
        ana.crear("Las Araucarias", [Subida("loteo.kmz", b"kmz")])


def test_ajustar_reescribe_proyecto_json(ana, tmp_path):
    proyecto = ana.vincular(carpeta_de_loteo(tmp_path))

    actualizado = ana.ajustar(proyecto.slug, {
        "etapa": "Etapa 1", "whatsapp": "56911111111",
        "despegue": [-72.1, -35.9], "referencias": ["Cauquenes"],
    })

    guardado = json.loads((proyecto.fuentes / "proyecto.json").read_text(encoding="utf-8"))
    assert guardado["etapa"] == "Etapa 1"
    assert guardado["despegue"] == [-72.1, -35.9]
    assert guardado["nombre"] == "Loteo"          # lo que no se toca se conserva
    assert actualizado.etapa == "Etapa 1"


def test_cambiar_el_nombre_no_cambia_el_slug_del_proyecto_ya_creado(ana, tmp_path):
    """El slug es la carpeta de salida y la URL: renombrar no debe dejar huérfano el sitio."""
    proyecto = ana.vincular(carpeta_de_loteo(tmp_path))

    actualizado = ana.ajustar(proyecto.slug, {"nombre": "Otro Nombre"})

    assert actualizado.slug == "loteo"
    assert actualizado.nombre == "Otro Nombre"


def test_olvidar_saca_el_proyecto_pero_no_borra_los_archivos(ana, tmp_path):
    carpeta = carpeta_de_loteo(tmp_path)
    ana.vincular(carpeta)

    ana.olvidar("loteo")

    assert ana.listar() == []
    assert (carpeta / "loteo.kmz").exists()


def test_las_panoramicas_repetidas_se_cuentan_una_vez(ana, tmp_path):
    """El volcado de la tarjeta suele dejar la misma foto en dos carpetas; el
    pipeline la toma una sola vez y el conteo tiene que decir lo mismo."""
    carpeta = tmp_path / "Vuelo"
    (carpeta / "360").mkdir(parents=True)
    (carpeta / "Dron").mkdir(parents=True)
    (carpeta / "loteo.kmz").write_bytes(b"kmz")
    for sub in ("360", "Dron"):
        (carpeta / sub / "DJI_0246.JPG").write_bytes(b"x" * 2_000_000)
    (carpeta / "360" / "DJI_0247.JPG").write_bytes(b"y" * 1_000_000)

    hallado = ana.vincular(carpeta).fuentes_encontradas()

    assert hallado["panoramicas"] == 2
    assert hallado["megas"] == 3


def test_las_subidas_viven_junto_a_los_datos(monkeypatch, tmp_path):
    import importlib

    from consola import proyectos as modulo
    from pipeline import config as ajustes
    monkeypatch.setenv("MASTERPLAN_DATOS", str(tmp_path))
    importlib.reload(ajustes)
    recargado = importlib.reload(modulo)
    try:
        assert recargado.CARPETA_SUBIDAS == tmp_path / "proyectos"
    finally:
        monkeypatch.delenv("MASTERPLAN_DATOS")
        importlib.reload(ajustes)
        importlib.reload(modulo)


# --- que un cliente no vea lo de otro --------------------------------------------

def test_cada_loteadora_solo_ve_sus_loteos(ana, luis, tmp_path):
    ana.vincular(carpeta_de_loteo(tmp_path, "De Ana"))
    luis.vincular(carpeta_de_loteo(tmp_path, "De Luis"))

    assert [p.slug for p in ana.listar()] == ["de-ana"]
    assert [p.slug for p in luis.listar()] == ["de-luis"]


def test_pedir_el_loteo_de_otra_es_como_si_no_existiera(ana, luis, tmp_path):
    ana.vincular(carpeta_de_loteo(tmp_path, "De Ana"))

    with pytest.raises(NoEncontrado):
        luis.ver("de-ana")


@pytest.mark.parametrize("hacer", [
    lambda vista: vista.ver("de-ana"),
    lambda vista: vista.ajustar("de-ana", {"etapa": "Etapa 9"}),
    lambda vista: vista.olvidar("de-ana"),
    lambda vista: vista.anotar_publicacion("de-ana", vercel_proyecto="x", url="https://x"),
])
def test_nada_de_lo_que_se_puede_hacer_alcanza_el_loteo_de_otra(ana, luis, tmp_path, hacer):
    ana.vincular(carpeta_de_loteo(tmp_path, "De Ana"))

    with pytest.raises(NoEncontrado):
        hacer(luis)

    # Y lo de Ana quedó intacto.
    assert ana.ver("de-ana").etapa == ""


def test_dos_loteadoras_pueden_llamar_igual_a_su_loteo_sin_pisarse(ana, luis, tmp_path):
    """El agujero que había: el slug salía del nombre, así que la segunda en
    publicar desplegaba encima del sitio de la primera."""
    una = ana.vincular(carpeta_de_loteo(tmp_path / "a", "Las Araucarias"))
    otra = luis.vincular(carpeta_de_loteo(tmp_path / "b", "Las Araucarias"))

    assert una.slug == "las-araucarias"
    assert otra.slug == "las-araucarias-2"
    assert una.salida.base != otra.salida.base
    assert una.fuentes != otra.fuentes


def test_el_equipo_de_ctp_ve_los_loteos_de_todas(ana, luis, ctp, tmp_path):
    ana.vincular(carpeta_de_loteo(tmp_path, "De Ana"))
    luis.vincular(carpeta_de_loteo(tmp_path, "De Luis"))

    assert sorted(p.slug for p in ctp.listar()) == ["de-ana", "de-luis"]
    assert ctp.ver("de-ana").nombre == "De Ana"


def test_lo_que_sube_ctp_queda_a_nombre_de_ctp(base, ctp):
    """Mira los de todas, pero lo que crea es suyo: si quedara a nombre del último
    cliente que miró, el dueño del loteo dependería del orden de los clics."""
    proyecto = ctp.crear("Vuelo Propio", [Subida("loteo.kmz", b"kmz")])

    guardado = base.proyecto(proyecto.slug)
    assert guardado.cliente_id == base.usuario_por_email("eduardo@ctp.cl").cliente_id


# --- identidad en el hosting ----------------------------------------------------

def test_un_proyecto_nuevo_no_tiene_hosting_todavia(ana, tmp_path):
    proyecto = ana.vincular(carpeta_de_loteo(tmp_path))

    assert proyecto.vercel_proyecto is None
    assert proyecto.url_publicada is None
    assert proyecto.publicado is False


def test_al_publicar_se_guarda_el_nombre_y_la_url_reales(ana, tmp_path):
    """No se adivinan: las dice el hosting y quedan escritas."""
    ana.vincular(carpeta_de_loteo(tmp_path))

    proyecto = ana.anotar_publicacion(
        "loteo", vercel_proyecto="masterplan-loteo", url="https://masterplan-loteo.vercel.app")

    assert proyecto.vercel_proyecto == "masterplan-loteo"
    assert proyecto.url_publicada == "https://masterplan-loteo.vercel.app"
    assert proyecto.publicado is True
    assert ana.ver("loteo").url_publicada == "https://masterplan-loteo.vercel.app"


def test_un_loteo_ya_publicado_conserva_su_nombre_en_el_hosting(ana, tmp_path):
    """El sitio de CTP sigue en masterplan-praderas-de-cauquenes aunque el esquema
    de nombres cambie: el nombre está guardado, no derivado."""
    carpeta = carpeta_de_loteo(tmp_path, "Praderas de Cauquenes")
    (carpeta / "proyecto.json").write_text(json.dumps({
        "nombre": "Praderas de Cauquenes",
        "slug": "praderas-de-cauquenes",
        "vercel_proyecto": "masterplan-praderas-de-cauquenes",
        "url_publicada": "https://masterplan-praderas-de-cauquenes.vercel.app",
    }), encoding="utf-8")

    proyecto = ana.vincular(carpeta)

    assert proyecto.slug == "praderas-de-cauquenes"
    assert proyecto.vercel_proyecto == "masterplan-praderas-de-cauquenes"


def test_ajustar_no_borra_lo_que_sabe_del_hosting(ana, tmp_path):
    ana.vincular(carpeta_de_loteo(tmp_path))
    ana.anotar_publicacion("loteo", vercel_proyecto="masterplan-loteo",
                           url="https://masterplan-loteo.vercel.app")

    ana.ajustar("loteo", {"etapa": "Etapa 2"})

    assert ana.ver("loteo").vercel_proyecto == "masterplan-loteo"


def test_la_carpeta_se_describe_a_si_misma_por_si_hay_que_rehacer_la_base(ana, tmp_path):
    """Publicar escribe también en `proyecto.json`: así el loteo se puede volver a
    adoptar con su identidad aunque la base se pierda."""
    carpeta = carpeta_de_loteo(tmp_path)
    ana.vincular(carpeta)

    ana.anotar_publicacion("loteo", vercel_proyecto="masterplan-loteo",
                           url="https://masterplan-loteo.vercel.app")

    guardado = json.loads((carpeta / "proyecto.json").read_text(encoding="utf-8"))
    assert guardado["url_publicada"] == "https://masterplan-loteo.vercel.app"


# --- el CRM es de cada cliente, nunca global -------------------------------------

def test_un_loteo_usa_el_crm_que_tiene_en_su_carpeta(ana, tmp_path):
    carpeta = carpeta_de_loteo(tmp_path)
    (carpeta / "crm.csv").write_text("Parcela\n", encoding="utf-8")

    assert ana.vincular(carpeta).crm == carpeta / "crm.csv"


def test_sin_crm_propio_un_loteo_no_hereda_el_de_nadie(ana, tmp_path):
    """Un cliente sin planilla publica sus parcelas como no disponibles, que es
    honesto. Lo que no puede pasar es que muestre los precios de otro."""
    assert ana.vincular(carpeta_de_loteo(tmp_path)).crm is None


def test_en_este_computador_se_puede_fijar_un_crm_por_defecto(base, tmp_path):
    """El dueño trabaja con el export de su CRM al lado; en el servidor no hay tal cosa."""
    global_csv = tmp_path / "ctp_parcelas_latest.csv"
    global_csv.write_text("Parcela\n", encoding="utf-8")
    propio = Registro(base=base, subidas=tmp_path / "p", salidas=tmp_path / "s",
                      crm_por_defecto=global_csv)
    vista = loteadora(base, propio, "Los Robles", "ana@losrobles.cl")

    assert vista.vincular(carpeta_de_loteo(tmp_path)).crm == global_csv
