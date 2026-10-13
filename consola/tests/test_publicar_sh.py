"""publicar.sh guarda la URL fija del loteo, no la de cada despliegue.

Corre el script de verdad con un `vercel` de mentira en el PATH, que contesta lo
mismo que el CLI 59: el deploy imprime la URL del despliegue (cambia cada vez) y
`inspect` lista los alias de producción.
"""
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "publicar.sh"
DESPLIEGUE = "https://masterplan-loteo-5huo5t5m5.vercel.app"
LOCAL = "http://127.0.0.1:8792/masterplan-loteo/"

INSPECT = """
  General

    id\t\tdpl_123
    url\t\t{despliegue}

  Aliases

{alias}

  Builds

    ╶ .        [0ms]
"""


def vercel_de_mentira(carpeta: Path, alias: list[str], inspect_falla: bool = False,
                      despliegue: str = DESPLIEGUE) -> Path:
    bin_ = carpeta / "bin"
    bin_.mkdir()
    lineas = "\n".join(f"    ╶ {a}" for a in alias)
    salida_inspect = INSPECT.format(despliegue=despliegue, alias=lineas)
    (bin_ / "inspect.txt").write_text(salida_inspect, encoding="utf-8")
    inspect = "exit 1" if inspect_falla else f'cat "{bin_ / "inspect.txt"}"'
    guion = f"""#!/bin/sh
case "$1" in
  deploy) echo "{despliegue}" ;;
  inspect) {inspect} ;;
  *) exit 0 ;;
esac
"""
    vercel = bin_ / "vercel"
    vercel.write_text(guion, encoding="utf-8")
    vercel.chmod(vercel.stat().st_mode | stat.S_IEXEC)
    return bin_


def correr(tmp_path, alias, inspect_falla=False,
           despliegue=DESPLIEGUE) -> subprocess.CompletedProcess:
    sitio = tmp_path / "salida" / "sitio"
    sitio.mkdir(parents=True)
    (sitio / "index.html").write_text("<html></html>", encoding="utf-8")
    bin_ = vercel_de_mentira(tmp_path, alias, inspect_falla, despliegue)
    entorno = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "VERCEL_TOKEN": "x"}
    return subprocess.run(["bash", str(SCRIPT), str(sitio), "masterplan-loteo"],
                          env=entorno, capture_output=True, text=True)


def publicar(tmp_path, alias, inspect_falla=False, despliegue=DESPLIEGUE) -> dict:
    hecho = correr(tmp_path, alias, inspect_falla, despliegue)
    assert hecho.returncode == 0, hecho.stderr
    return json.loads((tmp_path / "salida" / "publicacion.json").read_text(encoding="utf-8"))


def test_guarda_el_alias_fijo_y_no_el_del_despliegue(tmp_path):
    datos = publicar(tmp_path, ["https://masterplan-loteo.vercel.app",
                                "https://masterplan-loteo-lrencoret-1882s-projects.vercel.app"])

    assert datos["url"] == "https://masterplan-loteo.vercel.app"
    assert datos["despliegue"] == DESPLIEGUE


def test_con_dominio_propio_guarda_el_dominio(tmp_path):
    datos = publicar(tmp_path, ["https://masterplan-loteo.vercel.app",
                                "https://loteo.tumasterplan.cl"])

    assert datos["url"] == "https://loteo.tumasterplan.cl"


@pytest.mark.parametrize("alias, falla", [([], False), (["https://masterplan-loteo.vercel.app"], True)])
def test_sin_alias_queda_la_del_despliegue(tmp_path, alias, falla):
    assert publicar(tmp_path, alias, inspect_falla=falla)["url"] == DESPLIEGUE


# QA local: el `vercel` falso publica en la máquina y devuelve http. Se acepta
# solo hacia 127.0.0.1 o localhost; el real nunca devuelve http.
@pytest.mark.parametrize("local", [LOCAL, "http://localhost:8792/masterplan-loteo/",
                                   "http://localhost/masterplan-loteo/"])
def test_acepta_la_url_http_local(tmp_path, local):
    datos = publicar(tmp_path, [local], despliegue=local)

    assert datos["url"] == local
    assert datos["despliegue"] == local


def test_alias_http_a_otro_host_no_se_acepta(tmp_path):
    datos = publicar(tmp_path, ["http://loteo.tumasterplan.cl",
                                "http://localhost.tumasterplan.cl/x",
                                "http://masterplan-loteo.vercel.app"])

    assert datos["url"] == DESPLIEGUE


def test_alias_https_gana_aunque_haya_uno_http(tmp_path):
    datos = publicar(tmp_path, ["http://127.0.0.1.tumasterplan.cl",
                                "https://loteo.tumasterplan.cl",
                                "https://masterplan-loteo.vercel.app"])

    assert datos["url"] == "https://loteo.tumasterplan.cl"


@pytest.mark.parametrize("despliegue", ["http://masterplan-loteo-5huo5t5m5.vercel.app",
                                        "http://127.0.0.1.evil.cl/"])
def test_despliegue_http_a_otro_host_no_se_acepta(tmp_path, despliegue):
    hecho = correr(tmp_path, [], despliegue=despliegue)

    assert hecho.returncode != 0
    assert not (tmp_path / "salida" / "publicacion.json").exists()


# --- el dominio propio del loteo ---------------------------------------------------

def con_dominio(tmp_path, respuesta_domains: str, falla: bool):
    """Publica con --dominio y un `vercel domains add` que contesta `respuesta_domains`."""
    sitio = tmp_path / "salida" / "sitio"
    sitio.mkdir(parents=True)
    (sitio / "index.html").write_text("<html></html>", encoding="utf-8")
    bin_ = vercel_de_mentira(tmp_path, ["https://masterplan-loteo.vercel.app"])
    vercel = bin_ / "vercel"
    salida = 1 if falla else 0
    vercel.write_text(vercel.read_text(encoding="utf-8").replace(
        "case \"$1\" in\n",
        f"case \"$1\" in\n  domains) echo \"$@\" > \"{bin_ / 'domains.txt'}\"; "
        f"echo '{respuesta_domains}'; exit {salida} ;;\n"), encoding="utf-8")
    entorno = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "VERCEL_TOKEN": "x"}
    hecho = subprocess.run(["bash", str(SCRIPT), str(sitio), "masterplan-loteo",
                            "--dominio", "loteo.tumasterplan.cl"],
                           env=entorno, capture_output=True, text=True)
    assert hecho.returncode == 0, hecho.stderr
    datos = json.loads((tmp_path / "salida" / "publicacion.json").read_text(encoding="utf-8"))
    return datos, hecho, (bin_ / "domains.txt").read_text(encoding="utf-8")


def test_pide_el_dominio_para_el_proyecto_del_loteo(tmp_path):
    datos, _, pedido = con_dominio(tmp_path, "Success! Domain added", falla=False)

    assert pedido.split()[:4] == ["domains", "add", "loteo.tumasterplan.cl", "masterplan-loteo"]
    assert datos["url"] == "https://loteo.tumasterplan.cl"


def test_ya_asignado_a_este_proyecto_es_lo_normal_al_republicar(tmp_path):
    datos, _, _ = con_dominio(tmp_path, "Error: Domain is already assigned to this project", falla=True)

    assert datos["url"] == "https://loteo.tumasterplan.cl"


def test_si_el_dominio_es_de_otro_proyecto_publica_en_vercel_app_y_avisa(tmp_path):
    datos, hecho, _ = con_dominio(
        tmp_path, "Error: Domain is already in use by a different project", falla=True)

    assert datos["url"] == "https://masterplan-loteo.vercel.app"
    assert "No se pudo asignar loteo.tumasterplan.cl" in hecho.stderr


def test_una_opcion_desconocida_no_publica(tmp_path):
    sitio = tmp_path / "salida" / "sitio"
    sitio.mkdir(parents=True)
    (sitio / "index.html").write_text("<html></html>", encoding="utf-8")
    bin_ = vercel_de_mentira(tmp_path, [])
    entorno = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"}

    hecho = subprocess.run(["bash", str(SCRIPT), str(sitio), "masterplan-loteo", "--dominoi", "x"],
                           env=entorno, capture_output=True, text=True)

    assert hecho.returncode == 2
