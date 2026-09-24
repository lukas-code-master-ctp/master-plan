"""Trabajos: correr el pipeline y ver el avance en vivo."""
import sys
import time

import pytest

from consola.trabajos import Trabajos


def esperar(trabajos, identificador, limite=15.0):
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        trabajo = trabajos.ver(identificador)
        if trabajo.terminado:
            return trabajo
        time.sleep(0.02)
    raise AssertionError(f"el trabajo no terminó: {trabajos.ver(identificador)}")


@pytest.fixture
def trabajos():
    return Trabajos()


def guion(codigo):
    return [sys.executable, "-c", codigo]


def test_un_trabajo_que_termina_bien_queda_listo(trabajos):
    identificador = trabajos.lanzar("loteo", "construir", guion("print('hola')"))

    trabajo = esperar(trabajos, identificador)

    assert trabajo.estado == "listo"
    assert trabajo.codigo == 0
    assert "hola" in trabajo.lineas


def test_un_trabajo_que_falla_guarda_el_error(trabajos):
    identificador = trabajos.lanzar("loteo", "construir", guion(
        "import sys; print('empezando'); sys.stderr.write('se cayó\\n'); sys.exit(3)"))

    trabajo = esperar(trabajos, identificador)

    assert trabajo.estado == "falló"
    assert trabajo.codigo == 3
    assert "empezando" in trabajo.lineas
    assert "se cayó" in trabajo.lineas       # stderr y stdout van al mismo hilo


def test_las_lineas_se_pueden_leer_mientras_corre(trabajos):
    identificador = trabajos.lanzar("loteo", "construir", guion(
        "import time\nfor i in range(3):\n    print(i, flush=True)\n    time.sleep(0.15)"))

    fin = time.monotonic() + 10
    while time.monotonic() < fin and not trabajos.ver(identificador).lineas:
        time.sleep(0.01)
    parciales = list(trabajos.ver(identificador).lineas)

    trabajo = esperar(trabajos, identificador)
    assert len(parciales) < len(trabajo.lineas) or trabajo.lineas == parciales
    assert trabajo.lineas == ["0", "1", "2"]


def test_se_pueden_pedir_solo_las_lineas_nuevas(trabajos):
    identificador = trabajos.lanzar("loteo", "construir", guion("print('a'); print('b'); print('c')"))
    esperar(trabajos, identificador)

    assert trabajos.ver(identificador).lineas[2:] == ["c"]


def test_no_deja_correr_dos_trabajos_del_mismo_proyecto(trabajos):
    trabajos.lanzar("loteo", "construir", guion("import time; time.sleep(2)"))

    with pytest.raises(RuntimeError, match="ya está"):
        trabajos.lanzar("loteo", "publicar", guion("print('x')"))


def test_otro_proyecto_si_puede_correr_en_paralelo(trabajos):
    trabajos.lanzar("uno", "construir", guion("import time; time.sleep(0.3)"))
    identificador = trabajos.lanzar("otro", "construir", guion("print('ok')"))

    assert esperar(trabajos, identificador).estado == "listo"


def test_el_ultimo_trabajo_de_un_proyecto_se_puede_consultar(trabajos):
    identificador = trabajos.lanzar("loteo", "construir", guion("print('ok')"))
    esperar(trabajos, identificador)

    assert trabajos.ultimo("loteo").id == identificador
    assert trabajos.ultimo("otro") is None


def test_avisa_cuando_el_trabajo_termina(trabajos):
    """La consola necesita enterarse para guardar lo que dejó el trabajo."""
    avisos = []

    identificador = trabajos.lanzar("loteo", "publicar", guion("print('listo')"),
                                    al_terminar=lambda t: avisos.append((t.proyecto, t.estado)))
    esperar(trabajos, identificador)
    for _ in range(200):          # el aviso ocurre justo después de marcar el estado
        if avisos:
            break
        time.sleep(0.01)

    assert avisos == [("loteo", "listo")]


def test_un_aviso_que_falla_no_rompe_el_trabajo(trabajos):
    def explota(_trabajo):
        raise RuntimeError("algo pasó al guardar")

    identificador = trabajos.lanzar("loteo", "publicar", guion("print('ok')"), al_terminar=explota)

    assert esperar(trabajos, identificador).estado == "listo"
