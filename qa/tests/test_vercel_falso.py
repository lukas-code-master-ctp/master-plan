"""El `vercel` de QA deja publicar con el `publicar.sh` de verdad, sin hosting.

Se corre el script tal cual, con `qa/bin` primero en el PATH y la carpeta de
publicados en `tmp_path`: tiene que copiar el sitio, anotar una URL que se abra
en la máquina y fallar si `--crear` choca con un proyecto que ya existe.
"""
import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "publicar.sh"
BIN = REPO / "qa" / "bin"
BASE = "http://127.0.0.1:9999"
PROYECTO = "masterplan-praderas-demo"


def sitio_con(tmp_path: Path, contenido: str) -> Path:
    sitio = tmp_path / "salida" / "sitio"
    sitio.mkdir(parents=True, exist_ok=True)
    (sitio / "index.html").write_text(contenido, encoding="utf-8")
    return sitio


def publicar(tmp_path: Path, sitio: Path, *extra: str) -> subprocess.CompletedProcess:
    entorno = {**os.environ,
               "PATH": f"{BIN}:{os.environ['PATH']}",
               "QA_PUBLICADOS": str(tmp_path / "publicados"),
               "QA_URL_PUBLICADOS": BASE,
               "VERCEL_TOKEN": "qa"}
    return subprocess.run(["bash", str(SCRIPT), str(sitio), PROYECTO, *extra],
                          env=entorno, capture_output=True, text=True)


def rastro(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "salida" / "publicacion.json").read_text(encoding="utf-8"))


def test_crear_copia_el_sitio_y_anota_la_url_local(tmp_path):
    sitio = sitio_con(tmp_path, "<html>primera</html>")

    hecho = publicar(tmp_path, sitio, "--crear")

    assert hecho.returncode == 0, hecho.stderr
    publicado = tmp_path / "publicados" / PROYECTO
    assert (publicado / "index.html").read_text(encoding="utf-8") == "<html>primera</html>"
    assert not (publicado / ".vercel").exists()
    datos = rastro(tmp_path)
    assert datos["proyecto"] == PROYECTO
    assert datos["url"] == f"{BASE}/{PROYECTO}/"
    assert datos["despliegue"] == f"{BASE}/{PROYECTO}/"


def test_publicar_de_nuevo_reemplaza_el_contenido(tmp_path):
    sitio = sitio_con(tmp_path, "<html>primera</html>")
    (sitio / "viejo.js").write_text("", encoding="utf-8")
    assert publicar(tmp_path, sitio, "--crear").returncode == 0
    (sitio / "viejo.js").unlink()
    sitio_con(tmp_path, "<html>segunda</html>")

    hecho = publicar(tmp_path, sitio)

    assert hecho.returncode == 0, hecho.stderr
    publicado = tmp_path / "publicados" / PROYECTO
    assert (publicado / "index.html").read_text(encoding="utf-8") == "<html>segunda</html>"
    assert not (publicado / "viejo.js").exists()
    assert rastro(tmp_path)["url"] == f"{BASE}/{PROYECTO}/"


def test_crear_dos_veces_el_mismo_proyecto_falla(tmp_path):
    sitio = sitio_con(tmp_path, "<html>primera</html>")
    assert publicar(tmp_path, sitio, "--crear").returncode == 0
    sitio_con(tmp_path, "<html>de otro</html>")

    hecho = publicar(tmp_path, sitio, "--crear")

    assert hecho.returncode != 0
    assert "already exists" in hecho.stderr
    publicado = tmp_path / "publicados" / PROYECTO / "index.html"
    assert publicado.read_text(encoding="utf-8") == "<html>primera</html>"


def test_inspect_de_un_despliegue_que_no_existe_falla(tmp_path):
    hecho = subprocess.run([str(BIN / "vercel"), "inspect", f"{BASE}/no-existe/"],
                           capture_output=True, text=True,
                           env={**os.environ, "QA_PUBLICADOS": str(tmp_path),
                                "QA_URL_PUBLICADOS": BASE})

    assert hecho.returncode == 1
    assert "no se encontró" in hecho.stderr


def test_otro_subcomando_falla(tmp_path):
    hecho = subprocess.run([str(BIN / "vercel"), "env", "ls"], capture_output=True, text=True,
                           env={**os.environ, "QA_PUBLICADOS": str(tmp_path)})

    assert hecho.returncode == 1
    assert "no existe" in hecho.stderr
