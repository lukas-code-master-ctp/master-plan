"""Dejar la consola lista la primera vez."""
import json

import pytest

from consola import arranque
from consola.acceso import Sesion
from consola.datos import Base
from consola.proyectos import Registro


@pytest.fixture(autouse=True)
def indice_de_mentira(tmp_path, monkeypatch):
    """Ninguna prueba mira el índice de verdad.

    `preparar()` lee el índice viejo y lo renombra: apuntando al real, correr las
    pruebas migraría este computador. Cada prueba que necesite uno lo escribe en
    esta ruta.
    """
    monkeypatch.setattr(arranque, "INDICE_VIEJO", tmp_path / "proyectos.json")
    return tmp_path / "proyectos.json"


@pytest.fixture
def base(tmp_path):
    return Base(f"sqlite:///{tmp_path / 'consola.db'}")


@pytest.fixture
def registro(base, tmp_path):
    return Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas")


def carpeta_de_loteo(raiz, nombre, extra=None):
    carpeta = raiz / nombre
    carpeta.mkdir(parents=True)
    (carpeta / "loteo.kmz").write_bytes(b"kmz")
    (carpeta / "proyecto.json").write_text(
        json.dumps({"nombre": nombre, **(extra or {})}), encoding="utf-8")
    return carpeta


def test_la_primera_vez_crea_la_cuenta_de_casa_y_muestra_la_clave(base, registro):
    dichos = arranque.preparar(base, registro)

    usuario = base.usuario_por_email(arranque.CORREO_DE_CASA)
    assert usuario.rol == "plataforma"
    assert usuario.debe_cambiar_clave is True
    # La clave se muestra una sola vez y no está guardada en claro en ningún lado.
    clave = [d for d in dichos if "Clave provisional" in d][0].split(": ")[1]
    assert base.clave_valida(usuario, clave) is True
    assert clave not in usuario.clave_hash


def test_la_segunda_vez_no_toca_nada(base, registro):
    arranque.preparar(base, registro)
    antes = base.usuario_por_email(arranque.CORREO_DE_CASA)

    dichos = arranque.preparar(base, registro)

    assert dichos == []
    assert base.usuario_por_email(arranque.CORREO_DE_CASA).clave_hash == antes.clave_hash


def test_adopta_los_loteos_que_ya_estaban_con_su_identidad(base, registro, tmp_path):
    """El sitio de Praderas ya está en internet con ese nombre: no puede cambiar."""
    carpeta = carpeta_de_loteo(tmp_path, "Praderas de Cauquenes", {
        "slug": "praderas-de-cauquenes",
        "vercel_proyecto": "masterplan-praderas-de-cauquenes",
        "url_publicada": "https://masterplan-praderas-de-cauquenes.vercel.app",
    })
    indice = tmp_path / "proyectos.json"
    indice.write_text(json.dumps([str(carpeta)]), encoding="utf-8")

    arranque.preparar(base, registro)

    guardado = base.proyecto("praderas-de-cauquenes")
    assert guardado.vercel_proyecto == "masterplan-praderas-de-cauquenes"
    assert guardado.carpeta == str(carpeta)
    assert base.cliente(guardado.cliente_id).nombre == arranque.CASA
    # El índice viejo queda marcado para no volver a leerlo.
    assert not indice.exists()


def test_adoptar_no_se_repite_si_se_corre_de_nuevo(base, registro, tmp_path):
    carpeta = carpeta_de_loteo(tmp_path, "Loteo")
    indice = tmp_path / "proyectos.json"
    indice.write_text(json.dumps([str(carpeta)]), encoding="utf-8")

    arranque.preparar(base, registro)
    arranque.preparar(base, registro)

    assert len(base.proyectos()) == 1


def test_una_carpeta_que_ya_no_esta_se_salta_sin_romper(base, registro, tmp_path):
    indice = tmp_path / "proyectos.json"
    indice.write_text(json.dumps([str(tmp_path / "se-borro")]), encoding="utf-8")

    arranque.preparar(base, registro)

    assert base.proyectos() == []


def test_la_vista_con_que_adopta_es_la_de_casa(base, registro, tmp_path):
    """Y no una sin dueño: un loteo sin cliente no lo puede ver nadie."""
    carpeta = carpeta_de_loteo(tmp_path, "Loteo")
    indice = tmp_path / "proyectos.json"
    indice.write_text(json.dumps([str(carpeta)]), encoding="utf-8")
    arranque.preparar(base, registro)

    casa = base.usuario_por_email(arranque.CORREO_DE_CASA)
    vista = registro.para(Sesion(usuario_id=casa.id, cliente_id=casa.cliente_id,
                                 rol=casa.rol, quien=casa.email))

    assert [p.slug for p in vista.listar()] == ["loteo"]
