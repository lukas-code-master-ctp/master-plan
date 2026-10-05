"""qa/bajar.sh solo mata lo que levantó qa/levantar.sh: un .pid viejo que apunta a
un proceso ajeno (el número se reusó) se borra sin mandar señales."""
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

BAJAR = Path(__file__).resolve().parents[2] / "qa" / "bajar.sh"
DORMIR = "import time; time.sleep(60)"


@pytest.fixture
def qa(tmp_path):
    (tmp_path / "pids").mkdir()
    return tmp_path


@pytest.fixture
def lanzar():
    procesos = []

    def lanzar(*argumentos):
        # Grupo propio, como los de levantar.sh: las señales al grupo no llegan a pytest.
        proceso = subprocess.Popen(list(argumentos), start_new_session=True)
        # Alguien lo recoge apenas muere, como hace init con los de levantar.sh:
        # si no, queda zombi y bajar.sh lo ve vivo.
        threading.Thread(target=proceso.wait, daemon=True).start()
        procesos.append(proceso)
        return proceso

    yield lanzar
    for proceso in procesos:
        if proceso.poll() is None:
            proceso.kill()
        proceso.wait()


def anotar(qa, nombre, proceso):
    archivo = qa / "pids" / f"{nombre}.pid"
    archivo.write_text(f"{proceso.pid}\n")
    return archivo


def bajar(qa):
    return subprocess.run(
        ["bash", str(BAJAR)], env={"PATH": "/usr/bin:/bin", "QA_DIR": str(qa)},
        capture_output=True, text=True, check=True,
    ).stdout


def sigue_vivo(proceso, segundos=0.5):
    try:
        proceso.wait(timeout=segundos)
    except subprocess.TimeoutExpired:
        return True
    return False


def test_no_toca_un_proceso_ajeno(qa, lanzar):
    ajeno = lanzar("sleep", "60")
    archivo = anotar(qa, "cierra_falsa", ajeno)

    salida = bajar(qa)

    assert f"el PID {ajeno.pid} ya no es cierra_falsa (lo usa otro proceso): no lo toco" in salida
    assert not archivo.exists()
    assert sigue_vivo(ajeno)


def test_publicados_de_otra_carpeta_no_es_de_qa(qa, lanzar, tmp_path_factory):
    otra = tmp_path_factory.mktemp("otra")
    ajeno = lanzar(sys.executable, "-c", DORMIR, "http.server", str(otra / "publicados"))
    archivo = anotar(qa, "publicados", ajeno)

    assert "no lo toco" in bajar(qa)
    assert not archivo.exists()
    assert sigue_vivo(ajeno)


@pytest.mark.parametrize("nombre, huella", [
    ("cierra_falsa", ["qa.cierra_falsa"]),
    ("publicados", ["http.server", "{qa}/publicados"]),
    ("consola", ["hypercorn", "consola.app:crear_app()"]),
])
def test_baja_el_proceso_de_qa(qa, lanzar, nombre, huella):
    propio = lanzar(sys.executable, "-c", DORMIR, *(h.format(qa=qa) for h in huella))
    archivo = anotar(qa, nombre, propio)

    salida = bajar(qa)

    assert f"✓ {nombre} bajado (PID {propio.pid})" in salida
    assert not archivo.exists()
    assert not sigue_vivo(propio, segundos=5)


def test_sin_nada_arriba_sale_bien(qa):
    assert "No había nada de QA arriba" in bajar(qa)


@pytest.fixture
def grupo_sin_jefe():
    """Un grupo cuyo jefe ya murió y que sigue vivo por un miembro: devuelve el pgid."""
    def crear(*argumentos_del_miembro):
        # Grupo propio pero en la sesión de pytest: si no, el miembro no puede unirse.
        jefe = subprocess.Popen(["sleep", "60"], preexec_fn=lambda: os.setpgid(0, 0))
        # Miembro del grupo del jefe; es hijo de pytest, así que lo recoge su hilo
        # apenas muere (no depende de que init recoja huérfanos).
        miembro = subprocess.Popen(list(argumentos_del_miembro), preexec_fn=lambda: os.setpgid(0, jefe.pid))
        threading.Thread(target=miembro.wait, daemon=True).start()
        jefe.kill()
        jefe.wait()  # muerto y recogido: kill -0 <pgid> falla, kill -0 -<pgid> no
        miembros.append(miembro)
        return jefe.pid

    miembros = []
    yield crear
    for miembro in miembros:
        if miembro.poll() is None:
            miembro.kill()
        miembro.wait()


def grupo_vivo(pgid, segundos=0.5):
    limite = time.monotonic() + segundos
    while True:
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        if time.monotonic() >= limite:
            return True
        time.sleep(0.05)


def test_grupo_sin_jefe_ajeno_no_se_toca(qa, grupo_sin_jefe):
    pgid = grupo_sin_jefe("sleep", "60")
    archivo = qa / "pids" / "cierra_falsa.pid"
    archivo.write_text(f"{pgid}\n")

    assert "no lo toco" in bajar(qa)
    assert not archivo.exists()
    assert grupo_vivo(pgid)


def test_grupo_sin_jefe_de_qa_se_baja(qa, grupo_sin_jefe):
    pgid = grupo_sin_jefe(sys.executable, "-c", DORMIR, "qa.cierra_falsa")
    archivo = qa / "pids" / "cierra_falsa.pid"
    archivo.write_text(f"{pgid}\n")

    assert f"✓ cierra_falsa bajado (PID {pgid})" in bajar(qa)
    assert not archivo.exists()
    assert not grupo_vivo(pgid, segundos=0)
