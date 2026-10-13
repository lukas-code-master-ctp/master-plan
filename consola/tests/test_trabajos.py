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


# --- El tope: uno trabado no frena la cola ----------------------------------------------
#
# La instancia corre los pesados de a uno. Uno que se colgaba (una descarga que nunca
# volvía) dejaba la cola tomada para todas las loteadoras hasta reiniciar.

def colgado():
    """Un trabajo que no termina nunca ni imprime nada."""
    return guion("import time; time.sleep(600)")


def vivo(pid):
    import os
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # Un zombi todavía responde a la señal 0; muerto es muerto aunque nadie lo recoja.
    try:
        with open(f"/proc/{pid}/stat") as stat:
            return stat.read().split(")")[-1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def test_un_trabajo_trabado_se_corta_al_vencer_y_suelta_el_turno():
    trabajos = Trabajos(simultaneos=1, tope_pesado=0.5)
    trabado = trabajos.lanzar("loteo-a", "construir", colgado())
    segundo = trabajos.lanzar("loteo-b", "construir", guion("print('ok')"))

    assert esperar(trabajos, segundo).estado == "listo"
    cortado = trabajos.ver(trabado)
    assert cortado.estado == "falló"
    assert cortado.vencido
    assert cortado.como_json()["vencido"] is True
    assert "lo corté" in cortado.lineas[-1]
    assert not trabajos.corriendo("loteo-a")       # se puede volver a lanzar


def test_al_vencer_avisa_igual_para_guardar_lo_suyo():
    trabajos = Trabajos(tope_pesado=0.3)
    vistos = []

    identificador = trabajos.lanzar("loteo", "construir", colgado(), al_terminar=vistos.append)

    trabajo = trabajos.esperar(identificador, tope=15)
    assert trabajo.terminado
    assert vistos == [trabajo] and vistos[0].estado == "falló"


@pytest.mark.skipif(sys.platform == "win32", reason="grupos de procesos POSIX")
def test_al_vencer_se_corta_tambien_lo_que_lanzo(tmp_path):
    # El pipeline lanza sus propios procesos (el lector del plano); cortar solo el de
    # arriba dejaba al hijo comiendo memoria y con la salida abierta.
    archivo = tmp_path / "hijo.pid"
    trabajos = Trabajos(tope_pesado=0.5)
    identificador = trabajos.lanzar("loteo", "construir", guion(
        "import subprocess, sys, time\n"
        "hijo = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
        f"open({str(archivo)!r}, 'w').write(str(hijo.pid))\n"
        "time.sleep(600)"))

    trabajo = esperar(trabajos, identificador)

    assert trabajo.vencido
    hijo = int(archivo.read_text())
    fin = time.monotonic() + 5
    while vivo(hijo) and time.monotonic() < fin:
        time.sleep(0.05)
    assert not vivo(hijo)


@pytest.mark.skipif(sys.platform == "win32", reason="grupos de procesos POSIX")
def test_un_nieto_que_se_queda_con_la_salida_no_retiene_el_turno(monkeypatch):
    # El proceso termina bien, pero dejó vivo a alguien que se escapó de su grupo con
    # la salida abierta: antes la lectura no terminaba nunca y el turno tampoco.
    monkeypatch.setattr("consola.trabajos.ESPERA_SALIDA", 0.3)
    trabajos = Trabajos(simultaneos=1)
    identificador = trabajos.lanzar("loteo-a", "construir", guion(
        "import subprocess, sys\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)'],"
        " start_new_session=True)\n"
        "print('listo')"))
    segundo = trabajos.lanzar("loteo-b", "construir", guion("print('ok')"))

    assert esperar(trabajos, segundo, limite=4).estado == "listo"
    assert trabajos.ver(identificador).estado == "listo"
    assert "listo" in trabajos.ver(identificador).lineas


def test_publicar_tiene_su_propio_tope():
    trabajos = Trabajos(tope_pesado=600, tope_liviano=0.3)

    identificador = trabajos.lanzar("loteo", "publicar", colgado(), pesado=False)

    assert esperar(trabajos, identificador).vencido


def test_un_trabajo_dentro_del_tope_no_se_corta():
    trabajos = Trabajos(tope_pesado=10)

    trabajo = esperar(trabajos, trabajos.lanzar("loteo", "construir", tapon(0.2)))

    assert trabajo.estado == "listo"
    assert not trabajo.vencido


def test_cortar_todo_termina_lo_que_corre(trabajos):
    identificador = trabajos.lanzar("loteo", "construir", colgado())
    fin = time.monotonic() + 5
    while not trabajos._procesos and time.monotonic() < fin:
        time.sleep(0.01)

    trabajos.cortar_todo()

    assert esperar(trabajos, identificador).estado == "falló"


def test_los_topes_de_la_consola_tienen_margen():
    from consola.trabajos import TOPE_LIVIANO, TOPE_PESADO
    # Una construcción grande toma ~5 min de CPU: el tope no puede cortar una lenta.
    assert TOPE_PESADO >= 30 * 60
    assert TOPE_LIVIANO >= 10 * 60
    assert Trabajos().tope_pesado == TOPE_PESADO
