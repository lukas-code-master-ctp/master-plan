"""La base de la consola: clientes, usuarios y proyectos."""
import pytest

from consola.datos import (
    Base, ClienteYaExiste, EmailYaExiste, NoEncontrado, ProyectoYaExiste,
    url_por_defecto)


@pytest.fixture
def base(tmp_path):
    return Base(f"sqlite:///{tmp_path / 'consola.db'}")


# --- clientes -------------------------------------------------------------------

def test_al_principio_no_hay_clientes(base):
    assert base.clientes() == []


def test_crear_un_cliente_con_su_dueño(base):
    cliente, clave = base.crear_cliente("Inmobiliaria Los Robles", "ana@losrobles.cl", "Ana Pérez")

    assert cliente.slug == "inmobiliaria-los-robles"
    assert cliente.estado == "activo"
    assert len(clave) >= 12                      # provisional, se muestra una sola vez
    duenio = base.usuario_por_email("ana@losrobles.cl")
    assert duenio.cliente_id == cliente.id
    assert duenio.rol == "dueño"
    assert duenio.debe_cambiar_clave is True


def test_la_clave_provisional_no_queda_guardada_en_claro(base):
    _, clave = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    duenio = base.usuario_por_email("ana@losrobles.cl")

    assert clave not in duenio.clave_hash
    assert base.clave_valida(duenio, clave) is True
    assert base.clave_valida(duenio, clave + "x") is False


def test_dos_clientes_no_pueden_compartir_slug(base):
    base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    with pytest.raises(ClienteYaExiste):
        base.crear_cliente("Los Robles", "otro@otro.cl", "Otro")


def test_un_email_no_puede_estar_en_dos_clientes(base):
    base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    with pytest.raises(EmailYaExiste):
        base.crear_cliente("Otra Loteadora", "ana@losrobles.cl", "Ana")


def test_si_falla_el_dueño_no_queda_el_cliente_a_medias(base):
    base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    with pytest.raises(EmailYaExiste):
        base.crear_cliente("Otra Loteadora", "ana@losrobles.cl", "Ana")

    assert [c.slug for c in base.clientes()] == ["los-robles"]


def test_suspender_y_reactivar_un_cliente(base):
    cliente, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    base.suspender(cliente.id)
    assert base.cliente(cliente.id).estado == "suspendido"

    base.reactivar(cliente.id)
    assert base.cliente(cliente.id).estado == "activo"


# --- usuarios --------------------------------------------------------------------

def test_el_equipo_de_ctp_es_un_usuario_de_plataforma(base):
    cliente, _ = base.crear_cliente("CompraTuParcela", "e.ruiz@compratuparcela.cl", "Eduardo")

    base.ascender_a_plataforma("e.ruiz@compratuparcela.cl")

    usuario = base.usuario_por_email("e.ruiz@compratuparcela.cl")
    assert usuario.rol == "plataforma"
    assert usuario.cliente_id == cliente.id      # pertenece a una fila real, no a NULL


def test_un_email_que_no_existe_no_revela_nada(base):
    assert base.usuario_por_email("nadie@ninguna.cl") is None


def test_cambiar_la_clave_limpia_la_obligacion_y_corta_las_sesiones(base):
    _, clave = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    antes = base.usuario_por_email("ana@losrobles.cl").sesiones_validas_desde

    base.cambiar_clave("ana@losrobles.cl", "una-clave-nueva-larga")

    usuario = base.usuario_por_email("ana@losrobles.cl")
    assert usuario.debe_cambiar_clave is False
    assert base.clave_valida(usuario, "una-clave-nueva-larga") is True
    assert base.clave_valida(usuario, clave) is False
    # Cambiar la clave invalida lo que estuviera abierto, sin tabla de sesiones.
    assert usuario.sesiones_validas_desde > antes


# --- proyectos --------------------------------------------------------------------

def test_un_proyecto_nace_habilitado_y_pagado(base):
    """Solo CTP los crea, y los crea cuando ya cobró."""
    cliente, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    proyecto = base.crear_proyecto(cliente.id, "Las Araucarias", nota_cobro="transferencia 4821")

    assert proyecto.slug == "las-araucarias"
    assert proyecto.cliente_id == cliente.id
    assert proyecto.pagado_en is not None
    assert proyecto.nota_cobro == "transferencia 4821"


def test_dos_clientes_con_el_mismo_nombre_reciben_slugs_distintos(base):
    """El corazón del asunto: el slug es único en todo el sistema, no por cliente,
    porque también es el nombre del proyecto en el hosting."""
    uno, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    otro, _ = base.crear_cliente("Del Valle", "luis@delvalle.cl", "Luis")

    a = base.crear_proyecto(uno.id, "Las Araucarias")
    b = base.crear_proyecto(otro.id, "Las Araucarias")

    assert a.slug == "las-araucarias"
    assert b.slug == "las-araucarias-2"
    assert a.slug != b.slug


def test_los_proyectos_se_listan_por_cliente(base):
    uno, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    otro, _ = base.crear_cliente("Del Valle", "luis@delvalle.cl", "Luis")
    base.crear_proyecto(uno.id, "Las Araucarias")
    base.crear_proyecto(otro.id, "El Mirador")

    assert [p.slug for p in base.proyectos(cliente_id=uno.id)] == ["las-araucarias"]
    assert [p.slug for p in base.proyectos(cliente_id=otro.id)] == ["el-mirador"]
    assert len(base.proyectos()) == 2            # sin filtro: la vista de plataforma


def test_buscar_un_proyecto_de_otro_cliente_es_como_si_no_existiera(base):
    uno, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    otro, _ = base.crear_cliente("Del Valle", "luis@delvalle.cl", "Luis")
    base.crear_proyecto(uno.id, "Las Araucarias")

    assert base.proyecto("las-araucarias", cliente_id=uno.id).slug == "las-araucarias"
    with pytest.raises(NoEncontrado):
        base.proyecto("las-araucarias", cliente_id=otro.id)


def test_anotar_la_publicacion_guarda_nombre_y_url(base):
    cliente, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    base.crear_proyecto(cliente.id, "Las Araucarias")

    base.anotar_publicacion("las-araucarias", "masterplan-las-araucarias",
                            "https://masterplan-las-araucarias.vercel.app")

    proyecto = base.proyecto("las-araucarias", cliente_id=cliente.id)
    assert proyecto.vercel_proyecto == "masterplan-las-araucarias"
    assert proyecto.publicado_en is not None


def test_adoptar_un_proyecto_que_ya_existia(base):
    """El loteo de CTP entra con el slug, el nombre y la URL que ya tiene."""
    cliente, _ = base.crear_cliente("CompraTuParcela", "e.ruiz@compratuparcela.cl", "Eduardo")

    proyecto = base.crear_proyecto(
        cliente.id, "Praderas de Cauquenes", slug="praderas-de-cauquenes",
        vercel_proyecto="masterplan-praderas-de-cauquenes",
        url_publicada="https://masterplan-praderas-de-cauquenes.vercel.app")

    assert proyecto.slug == "praderas-de-cauquenes"
    assert proyecto.vercel_proyecto == "masterplan-praderas-de-cauquenes"


def test_la_base_sobrevive_a_reiniciar(tmp_path):
    ruta = f"sqlite:///{tmp_path / 'consola.db'}"
    cliente, _ = Base(ruta).crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    otra = Base(ruta)

    assert [c.slug for c in otra.clientes()] == ["los-robles"]
    assert otra.usuario_por_email("ana@losrobles.cl").cliente_id == cliente.id


def test_crear_una_cuenta_mas_dentro_de_una_loteadora(base):
    cliente, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    usuario, clave = base.crear_usuario(cliente.id, "luis@losrobles.cl", "Luis")

    assert usuario.cliente_id == cliente.id
    assert usuario.rol == "equipo"
    assert base.clave_valida(usuario, clave) is True
    assert [u.email for u in base.usuarios_de(cliente.id)] == ["ana@losrobles.cl",
                                                               "luis@losrobles.cl"]


def test_una_cuenta_nueva_no_puede_robarle_el_correo_a_otra(base):
    base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    otro, _ = base.crear_cliente("Del Valle", "luis@delvalle.cl", "Luis")

    with pytest.raises(EmailYaExiste):
        base.crear_usuario(otro.id, "ana@losrobles.cl", "Ana")


def test_desactivar_una_cuenta_la_deja_sin_entrar(base):
    cliente, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    base.crear_usuario(cliente.id, "luis@losrobles.cl", "Luis")

    base.desactivar_usuario("luis@losrobles.cl")

    assert base.usuario_por_email("luis@losrobles.cl").activo is False


def test_el_mismo_cliente_no_puede_repetir_el_nombre_del_loteo(base):
    """Dos loteos con el mismo nombre en la misma loteadora son un error de dedo."""
    cliente, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    base.crear_proyecto(cliente.id, "Las Araucarias")

    with pytest.raises(ProyectoYaExiste):
        base.crear_proyecto(cliente.id, "Las Araucarias")


def test_un_loteo_recuerda_la_carpeta_que_se_le_vinculo(base):
    cliente, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    proyecto = base.crear_proyecto(cliente.id, "Las Araucarias", carpeta="/Users/mac/Araucarias")

    assert base.proyecto(proyecto.slug, cliente_id=cliente.id).carpeta == "/Users/mac/Araucarias"


def test_un_loteo_subido_no_guarda_carpeta(base):
    """Vacío quiere decir 'donde van las subidas', que se arma con el slug: así la
    base sigue sirviendo si los datos cambian de lugar."""
    cliente, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    assert base.crear_proyecto(cliente.id, "Las Araucarias").carpeta is None


# --- dónde vive la base ------------------------------------------------------------

def test_en_este_computador_la_base_es_un_archivo_al_lado_de_los_datos(monkeypatch, tmp_path):
    monkeypatch.delenv("MASTERPLAN_BD", raising=False)
    monkeypatch.setenv("CONSOLA_ENTORNO", "local")
    monkeypatch.setattr("pipeline.config.DATOS", tmp_path)

    assert url_por_defecto() == f"sqlite:///{tmp_path / 'consola.db'}"


def test_desplegada_sin_MASTERPLAN_BD_no_arranca(monkeypatch):
    """En el servidor la carpeta de datos es un bucket montado, y SQLite sobre
    GCS no tiene bloqueo de archivos: la base se corrompería con los correos y
    los hashes de clave adentro. Mejor que la revisión no despliegue."""
    monkeypatch.delenv("MASTERPLAN_BD", raising=False)
    monkeypatch.setenv("CONSOLA_ENTORNO", "produccion")

    with pytest.raises(RuntimeError, match="MASTERPLAN_BD"):
        url_por_defecto()


def test_con_MASTERPLAN_BD_se_usa_esa(monkeypatch):
    monkeypatch.setenv("CONSOLA_ENTORNO", "produccion")
    monkeypatch.setenv("MASTERPLAN_BD", "postgresql+psycopg://x/y")

    assert url_por_defecto() == "postgresql+psycopg://x/y"
