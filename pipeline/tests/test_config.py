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


def test_la_planilla_es_opcional(tmp_path):
    """Sin xlsx el pipeline sigue: los datos comerciales pueden venir del CRM o no venir."""
    armar(tmp_path, excel=None)

    assert descubrir_fuentes(tmp_path).excel is None


def test_toma_el_csv_del_crm_que_se_le_indica(tmp_path):
    armar(tmp_path, excel=None)
    crm = tmp_path / "ctp_parcelas_latest.csv"
    crm.write_text("Parcela\n")

    assert descubrir_fuentes(tmp_path, crm=crm).crm == crm


def test_sin_csv_del_crm_la_fuente_queda_vacia(tmp_path):
    armar(tmp_path)

    assert descubrir_fuentes(tmp_path, crm=tmp_path / "no-esta.csv").crm is None


# --- proyecto y salida -----------------------------------------------------------

from pipeline.config import RAIZ, cargar_proyecto, salida_para


def test_el_proyecto_se_lee_de_proyecto_json(tmp_path):
    armar(tmp_path)
    (tmp_path / "proyecto.json").write_text(
        '{"nombre": "Praderas de Cauquenes", "etapa": "Etapas 1 a 4", "whatsapp": "56911111111"}',
        encoding="utf-8")

    proyecto = cargar_proyecto(tmp_path)

    assert proyecto.nombre == "Praderas de Cauquenes"
    assert proyecto.etapa == "Etapas 1 a 4"
    assert proyecto.whatsapp == "56911111111"
    assert proyecto.parcelacion == "PRADERAS DE CAUQUENES"


def test_sin_proyecto_json_el_nombre_es_la_carpeta(tmp_path):
    carpeta = tmp_path / "Talhuenes"
    carpeta.mkdir()

    proyecto = cargar_proyecto(carpeta)

    assert proyecto.nombre == "Talhuenes"
    assert proyecto.whatsapp == ""


def test_lo_que_viene_por_linea_de_comandos_manda(tmp_path):
    (tmp_path / "proyecto.json").write_text('{"nombre": "Viejo"}', encoding="utf-8")

    proyecto = cargar_proyecto(tmp_path, nombre="Nuevo", parcelacion="OTRA")

    assert proyecto.nombre == "Nuevo"
    assert proyecto.parcelacion == "OTRA"


def test_la_salida_va_a_salidas_con_el_nombre_en_minusculas(tmp_path):
    proyecto = cargar_proyecto(tmp_path, nombre="Praderas de Cauquenes")

    salida = salida_para(proyecto)

    assert salida.web == RAIZ / "salidas" / "praderas-de-cauquenes" / "sitio"
    assert salida.datos == salida.web / "datos"
    assert salida.vistas == salida.web / "datos" / "vistas"
    assert salida.panoramas == salida.web / "panoramas"
    assert salida.qa == RAIZ / "salidas" / "praderas-de-cauquenes" / "control-calce"


def test_la_salida_se_puede_fijar_a_mano(tmp_path):
    proyecto = cargar_proyecto(tmp_path, nombre="X")

    assert salida_para(proyecto, base=tmp_path / "x").web == tmp_path / "x" / "sitio"


def test_el_punto_de_despegue_se_lee_de_proyecto_json(tmp_path):
    (tmp_path / "proyecto.json").write_text('{"nombre": "X", "despegue": [-72.27, -35.86]}',
                                            encoding="utf-8")

    assert cargar_proyecto(tmp_path).despegue == (-72.27, -35.86)


def test_sin_despegue_el_proyecto_no_lo_inventa(tmp_path):
    assert cargar_proyecto(tmp_path, nombre="X").despegue is None


def test_las_referencias_se_leen_de_proyecto_json(tmp_path):
    (tmp_path / "proyecto.json").write_text(
        '{"nombre": "X", "referencias": ["Cauquenes", {"nombre": "Fundo", "lon": -72.3, "lat": -35.9}]}',
        encoding="utf-8")

    proyecto = cargar_proyecto(tmp_path)

    assert proyecto.referencias == ("Cauquenes", {"nombre": "Fundo", "lon": -72.3, "lat": -35.9})
    assert cargar_proyecto(tmp_path, nombre="Y").referencias == ("Cauquenes", {"nombre": "Fundo", "lon": -72.3, "lat": -35.9})
    assert cargar_proyecto(tmp_path / "otra", nombre="Z").referencias == () if (tmp_path / "otra").mkdir() is None else True


# --- rutas configurables (para correr fuera del repo, en un contenedor) ---------

def test_las_rutas_de_datos_salen_del_entorno(monkeypatch, tmp_path):
    """En Cloud Run los datos viven en un volumen, no dentro del repo."""
    import importlib

    from pipeline import config as modulo
    monkeypatch.setenv("MASTERPLAN_DATOS", str(tmp_path / "datos"))
    monkeypatch.delenv("MASTERPLAN_CRM_CSV", raising=False)
    recargado = importlib.reload(modulo)
    try:
        assert recargado.DATOS == tmp_path / "datos"
        assert recargado.SALIDAS == tmp_path / "datos" / "salidas"
        assert recargado.CACHE_TERRENO == tmp_path / "datos" / "cache" / "terreno"
        assert recargado.CACHE_REFERENCIAS == tmp_path / "datos" / "cache" / "referencias.json"
    finally:
        monkeypatch.delenv("MASTERPLAN_DATOS")
        importlib.reload(modulo)


def test_sin_la_variable_todo_queda_dentro_del_repo():
    from pipeline import config as modulo

    assert modulo.DATOS == modulo.RAIZ
    assert modulo.SALIDAS == modulo.RAIZ / "salidas"


def test_no_hay_ningun_csv_global_en_la_carpeta_de_datos(tmp_path, monkeypatch):
    """Con varios clientes, un CSV global sería que quien no trae planilla hereda
    los precios de otro. El export de cada cliente llega por --crm."""
    from pipeline import config as modulo
    from pipeline.config import csv_del_crm

    monkeypatch.setenv("MASTERPLAN_DATOS", str(tmp_path))
    monkeypatch.delenv("MASTERPLAN_CRM_CSV", raising=False)
    monkeypatch.setattr(modulo, "CRM_CSV_JUNTO_AL_REPO", tmp_path / "no-esta.csv")
    monkeypatch.setattr(modulo, "DATOS", tmp_path)
    (tmp_path / "ctp_parcelas_latest.csv").write_text("Parcela\n", encoding="utf-8")

    assert csv_del_crm() is None


def test_en_este_computador_se_usa_el_export_de_reporteria(tmp_path, monkeypatch):
    from pipeline import config as modulo
    from pipeline.config import csv_del_crm

    vecino = tmp_path / "ctp_parcelas_latest.csv"
    vecino.write_text("Parcela\n", encoding="utf-8")
    monkeypatch.delenv("MASTERPLAN_CRM_CSV", raising=False)
    monkeypatch.setattr(modulo, "CRM_CSV_JUNTO_AL_REPO", vecino)

    assert csv_del_crm() == vecino


def test_la_variable_manda_sobre_el_volumen(tmp_path, monkeypatch):
    from pipeline import config as modulo
    from pipeline.config import csv_del_crm

    monkeypatch.setattr(modulo, "DATOS", tmp_path)
    propio = tmp_path / "otro.csv"
    propio.write_text("Parcela\n", encoding="utf-8")
    monkeypatch.setenv("MASTERPLAN_DATOS", str(tmp_path))
    monkeypatch.setenv("MASTERPLAN_CRM_CSV", str(propio))
    (tmp_path / "ctp_parcelas_latest.csv").write_text("Parcela\n", encoding="utf-8")

    assert csv_del_crm() == propio


# --- el slug se asigna, no se deriva -------------------------------------------

def test_sin_slug_guardado_se_sugiere_desde_el_nombre():
    from pipeline.config import sugerir_slug

    assert sugerir_slug("Praderas de Cauquenes") == "praderas-de-cauquenes"
    assert sugerir_slug("  Loteo  Ñuñoa / Etapa 2 ") == "loteo-nunoa-etapa-2"
    assert sugerir_slug("!!!") == "proyecto"


def test_el_slug_guardado_manda_sobre_el_derivado_del_nombre(tmp_path):
    """Dos clientes pueden llamar igual a su loteo; quien asigna el slug es la
    consola, no el nombre. Renombrar el proyecto tampoco mueve el sitio publicado."""
    (tmp_path / "proyecto.json").write_text(
        '{"nombre": "Las Araucarias", "slug": "las-araucarias-2"}', encoding="utf-8")

    proyecto = cargar_proyecto(tmp_path)

    assert proyecto.slug == "las-araucarias-2"
    assert proyecto.nombre == "Las Araucarias"


def test_sin_slug_en_el_json_se_sigue_derivando_del_nombre(tmp_path):
    (tmp_path / "proyecto.json").write_text('{"nombre": "Las Araucarias"}', encoding="utf-8")

    assert cargar_proyecto(tmp_path).slug == "las-araucarias"


def test_la_salida_usa_el_slug_asignado(tmp_path):
    from pipeline.config import salida_para

    (tmp_path / "proyecto.json").write_text(
        '{"nombre": "Las Araucarias", "slug": "las-araucarias-2"}', encoding="utf-8")

    salida = salida_para(cargar_proyecto(tmp_path))

    assert salida.web.parent.name == "las-araucarias-2"


def test_se_puede_pedir_explicitamente_que_no_haya_crm(tmp_path, monkeypatch):
    """La consola lo usa para los loteos de clientes que no traen export: sin esto
    el pipeline caería al por defecto del computador, que es de otro."""
    from pipeline import config as modulo
    armar(tmp_path)
    vecino = tmp_path / "ctp_parcelas_latest.csv"
    vecino.write_text("Parcela\n", encoding="utf-8")
    monkeypatch.setattr(modulo, "CRM_CSV_JUNTO_AL_REPO", vecino)

    assert descubrir_fuentes(tmp_path).crm == vecino
    assert descubrir_fuentes(tmp_path, sin_crm=True).crm is None


def test_el_inventario_subido_como_csv_cuenta_como_planilla(tmp_path):
    armar(tmp_path, excel="inventario.csv")

    assert descubrir_fuentes(tmp_path).excel.name == "inventario.csv"


def test_un_csv_cualquiera_no_se_toma_por_planilla(tmp_path):
    armar(tmp_path, excel="coordenadas.csv")

    assert descubrir_fuentes(tmp_path).excel is None


@pytest.mark.parametrize("inventario", ["inventario.csv", "inventario.xlsx"])
def test_el_inventario_subido_manda_sobre_el_xlsx_del_vuelo(tmp_path, inventario):
    # "aaa" va antes en el orden alfabético: sin la regla, ganaría el viejo.
    armar(tmp_path, excel="aaa-precios-de-marzo.xlsx")
    (tmp_path / inventario).write_bytes(b"inventario")

    assert descubrir_fuentes(tmp_path).excel.name == inventario


def test_sin_inventario_subido_vale_el_xlsx_del_vuelo(tmp_path):
    armar(tmp_path, excel="precios.xlsx")

    assert descubrir_fuentes(tmp_path).excel.name == "precios.xlsx"


# --- lo que genera el pipeline no es fuente, lo que se sube sí ---------------------

def _repo_falso(tmp_path, monkeypatch):
    """Un repo de mentira con los datos adentro, como corre la consola en local."""
    from pipeline import config as modulo

    raiz = tmp_path / "master-plan"
    monkeypatch.setattr(modulo, "RAIZ", raiz)
    monkeypatch.setattr(modulo, "SALIDAS", raiz / "salidas")
    monkeypatch.setattr(modulo, "SUBIDAS", raiz / "proyectos")
    return raiz


def test_encuentra_las_fuentes_de_un_master_subido_por_la_consola(tmp_path, monkeypatch):
    """Sin MASTERPLAN_DATOS las subidas quedan dentro del repo, en proyectos/<slug>."""
    raiz = _repo_falso(tmp_path, monkeypatch)
    carpeta = raiz / "proyectos" / "mi-loteo"
    carpeta.mkdir(parents=True)
    armar(carpeta, excel=None, fotos=("fotos/DJI_0001.JPG",))

    fuentes = descubrir_fuentes(carpeta, sin_crm=True)

    assert fuentes.kmz == carpeta / "loteo.kmz"
    assert fuentes.panoramas == carpeta / "fotos"


def test_una_carpeta_que_contiene_el_repo_no_toma_lo_generado(tmp_path, monkeypatch):
    """Si se apunta a una carpeta del disco que contiene al repo, las salidas del
    pipeline no deben confundirse con las fuentes."""
    raiz = _repo_falso(tmp_path, monkeypatch)
    armar(tmp_path, kmz="z-loteo.kmz", fotos=("vuelo/a.JPG",))
    sitio = raiz / "salidas" / "otro" / "sitio"
    (sitio / "panoramas").mkdir(parents=True)
    (sitio / "panoramas" / "p.jpg").write_bytes(b"jpg")
    (raiz / "a.kmz").write_bytes(b"kmz")

    fuentes = descubrir_fuentes(tmp_path, sin_crm=True)

    assert fuentes.kmz == tmp_path / "z-loteo.kmz"
    assert fuentes.panoramas == tmp_path / "vuelo"


# --- Crea tu KMZ: la carpeta plano/ ----------------------------------------------

from pipeline.config import kmz_en


def _plano_de_crea_tu_kmz(carpeta):
    """Lo que deja la consola: el PDF, sus páginas en JPEG y, a medio crear, el KMZ."""
    plano = carpeta / "plano"
    (plano / "paginas").mkdir(parents=True)
    (plano / "plano.pdf").write_bytes(b"%PDF-1.7")
    (plano / "paginas" / "1.jpg").write_bytes(b"jpg")
    (plano / "paginas" / "1_mini.jpg").write_bytes(b"jpg")
    (plano / "subdivision.kmz").write_bytes(b"kmz")


def test_lo_de_crea_tu_kmz_no_es_fuente(tmp_path):
    armar(tmp_path, kmz="z-loteo.kmz", fotos=("vuelo/a.JPG",))
    _plano_de_crea_tu_kmz(tmp_path)

    fuentes = descubrir_fuentes(tmp_path, sin_crm=True)

    assert fuentes.kmz == tmp_path / "z-loteo.kmz"
    assert fuentes.panoramas == tmp_path / "vuelo"
    assert kmz_en(tmp_path) == [tmp_path / "z-loteo.kmz"]


@pytest.mark.parametrize("carpeta", ["plano", "planos", "Plano"])
def test_una_carpeta_plano_del_vuelo_sigue_siendo_fuente(tmp_path, carpeta):
    """Sin el PDF ni las páginas de Crea tu KMZ, "plano/" es del topógrafo o del piloto."""
    (tmp_path / carpeta).mkdir()
    armar(tmp_path, kmz=f"{carpeta}/loteo.kmz", excel=f"{carpeta}/parcelas.xlsx",
          fotos=(f"{carpeta}/fotos/a.JPG",))

    fuentes = descubrir_fuentes(tmp_path, sin_crm=True)

    assert fuentes.kmz == tmp_path / carpeta / "loteo.kmz"
    assert fuentes.excel == tmp_path / carpeta / "parcelas.xlsx"
    assert fuentes.panoramas == tmp_path / carpeta / "fotos"


def test_crea_tu_kmz_en_una_carpeta_vinculada_dentro_del_repo(tmp_path, monkeypatch):
    """El modo local: las subidas viven en <repo>/proyectos y el plano adentro."""
    raiz = _repo_falso(tmp_path, monkeypatch)
    carpeta = raiz / "proyectos" / "mi-loteo"
    carpeta.mkdir(parents=True)
    armar(carpeta, excel=None, fotos=("DJI_0001.JPG",))
    _plano_de_crea_tu_kmz(carpeta)

    fuentes = descubrir_fuentes(carpeta, sin_crm=True)

    assert fuentes.kmz == carpeta / "loteo.kmz"
    # Las fotos están en la raíz: sin excluir el plano, el ancestro común no cambia,
    # pero las páginas tampoco se cuentan como panorámicas (ver test_panoramas).
    assert fuentes.panoramas == carpeta
