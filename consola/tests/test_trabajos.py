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


def test_un_traceback_llega_sin_codigos_de_color(trabajos, monkeypatch):
    # Lanzada desde una terminal con color forzado, un Python 3.13+ pinta los
    # tracebacks con ANSI; en la página eso sale como "[35m".
    monkeypatch.setenv("FORCE_COLOR", "1")
    identificador = trabajos.lanzar("loteo", "construir", guion("raise ValueError('mal')"))

    trabajo = esperar(trabajos, identificador)

    assert not any("\x1b[" in linea for linea in trabajo.lineas)
    assert any("ValueError: mal" in linea for linea in trabajo.lineas)


def test_esperar_bloquea_hasta_que_termina(trabajos):
    identificador = trabajos.lanzar("loteo", "construir", guion("print('hola')"))

    trabajo = trabajos.esperar(identificador)

    assert trabajo.terminado and trabajo.estado == "listo"
    assert "hola" in trabajo.lineas


def test_esperar_incluye_lo_que_se_guarda_al_terminar(trabajos):
    guardados = []

    def guardar(trabajo):
        time.sleep(0.2)
        guardados.append(trabajo.estado)

    identificador = trabajos.lanzar("loteo", "publicar", guion("print('ok')"),
                                    al_terminar=guardar)
    trabajos.esperar(identificador)

    assert guardados == ["listo"]


def test_esperar_no_se_queda_pegado_si_el_comando_no_existe(trabajos):
    identificador = trabajos.lanzar("loteo", "construir", ["/no/existe/este-comando"])

    trabajo = trabajos.esperar(identificador, tope=10)

    assert trabajo.estado == "falló"


def test_esperar_con_tope_devuelve_el_trabajo_aunque_siga_corriendo(trabajos):
    identificador = trabajos.lanzar("loteo", "construir", guion("import time; time.sleep(3)"))

    trabajo = trabajos.esperar(identificador, tope=0.1)

    assert not trabajo.terminado


def test_tildes_y_bytes_que_no_son_utf8_no_rompen_el_trabajo(trabajos):
    """El pipeline escribe en UTF-8; lo de otros (la CLI de Vercel) puede no serlo."""
    identificador = trabajos.lanzar("loteo", "publicar", guion(
        "import sys; print('rotación 90°, 1.200×900 px', flush=True);"
        r" sys.stdout.buffer.write(b'latin1: \xe9xito\n'); sys.stdout.flush()"))

    trabajo = esperar(trabajos, identificador)

    assert trabajo.estado == "listo"
    assert "rotación 90°, 1.200×900 px" in trabajo.lineas
    assert trabajo.lineas[-1] == "latin1: \N{REPLACEMENT CHARACTER}xito"


# --- La cola: los trabajos pesados pasan de a uno ------------------------------------
#
# Una construcción grande usa más de 4 GB y la instancia tiene 8: dos a la vez la
# pueden matar y con ella todo lo que corría. Las que llegan mientras otra corre
# esperan su turno en orden, y parten solas.

def tapon(segundos=0.6):
    """Un trabajo que ocupa el turno un rato."""
    return guion(f"import time; time.sleep({segundos}); print('listo')")


@pytest.fixture
def de_a_uno():
    return Trabajos(simultaneos=1)


def test_el_segundo_trabajo_pesado_espera_en_cola(de_a_uno):
    primero = de_a_uno.lanzar("loteo-a", "construir", tapon())
    segundo = de_a_uno.lanzar("loteo-b", "construir", guion("print('después')"))

    en_cola = de_a_uno.ver(segundo)
    assert en_cola.estado == "en_cola"
    assert not en_cola.terminado
    assert en_cola.como_json()["posicion"] == 1
    assert de_a_uno.corriendo("loteo-b")       # nadie más le lanza nada encima

    assert esperar(de_a_uno, segundo).estado == "listo"
    assert de_a_uno.ver(primero).terminado
    # Partió recién cuando terminó el primero.
    assert de_a_uno.ver(segundo).partio >= de_a_uno.ver(primero).termino


def test_la_cola_respeta_el_orden_de_llegada(de_a_uno):
    de_a_uno.lanzar("loteo-a", "construir", tapon())
    segundo = de_a_uno.lanzar("loteo-b", "construir", tapon(0.2))
    tercero = de_a_uno.lanzar("loteo-c", "digitalizar-plano", guion("print('c')"))

    assert de_a_uno.ver(segundo).como_json()["posicion"] == 1
    assert de_a_uno.ver(tercero).como_json()["posicion"] == 2

    esperar(de_a_uno, tercero)
    assert de_a_uno.ver(tercero).partio >= de_a_uno.ver(segundo).termino


def test_publicar_no_hace_cola(de_a_uno):
    de_a_uno.lanzar("loteo-a", "construir", tapon())

    publicar = de_a_uno.lanzar("loteo-b", "publicar", guion("print('arriba')"), pesado=False)

    assert de_a_uno.ver(publicar).estado != "en_cola"
    assert esperar(de_a_uno, publicar).estado == "listo"


def test_un_trabajo_que_falla_igual_suelta_el_turno(de_a_uno):
    de_a_uno.lanzar("loteo-a", "construir", guion("import sys; sys.exit(2)"))
    segundo = de_a_uno.lanzar("loteo-b", "construir", guion("print('ok')"))

    assert esperar(de_a_uno, segundo).estado == "listo"


def test_un_comando_que_no_existe_igual_suelta_el_turno(de_a_uno):
    de_a_uno.lanzar("loteo-a", "construir", ["/no/existe/este/comando"])
    segundo = de_a_uno.lanzar("loteo-b", "construir", guion("print('ok')"))

    assert esperar(de_a_uno, segundo).estado == "listo"


def test_con_dos_turnos_corren_dos_y_el_tercero_espera():
    trabajos = Trabajos(simultaneos=2)
    trabajos.lanzar("loteo-a", "construir", tapon())
    trabajos.lanzar("loteo-b", "construir", tapon())

    tercero = trabajos.lanzar("loteo-c", "construir", guion("print('c')"))

    assert trabajos.ver(tercero).estado == "en_cola"
    assert esperar(trabajos, tercero).estado == "listo"


def test_sin_tope_no_hay_cola(trabajos):
    trabajos.lanzar("loteo-a", "construir", tapon())

    segundo = trabajos.lanzar("loteo-b", "construir", guion("print('b')"))

    assert trabajos.ver(segundo).estado == "corriendo"


@pytest.mark.parametrize("valor, esperado", [("", 1), ("2", 2), ("0", 1)])
def test_el_tope_de_la_consola_sale_del_entorno(monkeypatch, valor, esperado):
    from consola.app import _simultaneos
    monkeypatch.setenv("CONSOLA_TRABAJOS_SIMULTANEOS", valor)

    assert _simultaneos() == esperado
