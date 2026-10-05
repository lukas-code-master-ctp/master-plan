import logging

from consola.app import mostrar_registro
from consola.tests.test_app import montar


def olvidar_el_registro():
    # El manejador se crea con el sys.stdout de ese momento, y el nivel queda puesto
    # para todo el proceso: sin esto cada prueba vería lo que dejó la anterior.
    consola = logging.getLogger("consola")
    consola.setLevel(logging.NOTSET)
    for manejador in list(consola.handlers):
        if getattr(manejador, "_de_la_consola", False):
            consola.removeHandler(manejador)


def test_la_linea_de_cierra_llega_a_la_salida_estandar(capsys):
    olvidar_el_registro()

    mostrar_registro()
    logging.getLogger("consola.inventario").info("[cierra] %s: %s", "praderas", "sin cambios")

    assert "[cierra] praderas: sin cambios" in capsys.readouterr().out


def test_llamarla_de_nuevo_no_duplica_las_lineas():
    mostrar_registro()
    mostrar_registro()

    propios = [m for m in logging.getLogger("consola").handlers
               if getattr(m, "_de_la_consola", False)]
    assert len(propios) == 1


def test_la_consola_lo_deja_puesto_al_arrancar(tmp_path):
    olvidar_el_registro()

    montar(tmp_path)

    assert logging.getLogger("consola.inventario").isEnabledFor(logging.INFO)
