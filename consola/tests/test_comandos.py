"""Qué le pide exactamente la consola al pipeline.

Importa que sea explícito: la consola dice DÓNDE va cada cosa en vez de dejar que
el pipeline lo resuelva de constantes globales, porque con varios clientes esas
constantes son las mismas para todos.
"""
from pathlib import Path

import pytest

from consola.comandos import Comandos, encadenar
from consola.proyectos import Proyecto
from pipeline import config


def proyecto_de_prueba(tmp_path, slug="las-araucarias"):
    return Proyecto(
        slug=slug, nombre="Las Araucarias", etapa="", whatsapp="",
        despegue=None, referencias=(),
        fuentes=tmp_path / "fuentes",
        salida=config.Salida(tmp_path / "salidas" / slug),
    )


@pytest.fixture
def comandos():
    return Comandos()


def test_construir_dice_donde_va_la_salida(comandos, tmp_path):
    proyecto = proyecto_de_prueba(tmp_path)

    orden = comandos.construir(proyecto)

    assert "--proyecto" in orden and str(proyecto.fuentes) in orden
    assert "--salida" in orden
    assert orden[orden.index("--salida") + 1] == str(proyecto.salida.base)


def test_el_control_de_calce_apunta_a_la_misma_salida(comandos, tmp_path):
    proyecto = proyecto_de_prueba(tmp_path)

    orden = comandos.control_de_calce(proyecto)

    assert orden[orden.index("--salida") + 1] == str(proyecto.salida.base)


def test_sin_imagenes_se_pasa_como_bandera(comandos, tmp_path):
    assert "--sin-imagenes" in comandos.construir(proyecto_de_prueba(tmp_path), sin_imagenes=True)
    assert "--sin-imagenes" not in comandos.construir(proyecto_de_prueba(tmp_path))


def test_publicar_recibe_el_nombre_del_proyecto_del_hosting(comandos, tmp_path):
    """No se deduce del slug en el script: se lo dice la consola, que es quien lo
    tiene guardado. Así un loteo ya publicado conserva su nombre."""
    proyecto = proyecto_de_prueba(tmp_path)

    orden = comandos.publicar(proyecto, vercel_proyecto="masterplan-praderas-de-cauquenes")

    assert str(proyecto.salida.web) in orden
    assert "masterplan-praderas-de-cauquenes" in orden
    assert "--crear" not in orden


def test_la_primera_publicacion_pide_crear_el_proyecto(comandos, tmp_path):
    orden = comandos.publicar(proyecto_de_prueba(tmp_path),
                              vercel_proyecto="masterplan-las-araucarias", crear=True)

    assert "--crear" in orden


def test_encadenar_corta_al_primer_error():
    orden = encadenar(["echo", "uno"], ["false"], ["echo", "tres"])

    assert orden[:2] == ["/bin/sh", "-c"]
    assert " && " in orden[2]


def test_un_loteo_sin_export_lo_dice_explicitamente(comandos, tmp_path):
    """Callar no alcanza: el pipeline caería al export por defecto, que es de otro."""
    orden = comandos.construir(proyecto_de_prueba(tmp_path))

    assert "--sin-crm" in orden and "--crm" not in orden


def test_un_loteo_con_export_propio_lo_pasa(comandos, tmp_path):
    from dataclasses import replace
    propio = tmp_path / "crm.csv"
    proyecto = replace(proyecto_de_prueba(tmp_path), crm=propio)

    orden = comandos.construir(proyecto)

    assert orden[orden.index("--crm") + 1] == str(propio)
    assert "--sin-crm" not in orden
