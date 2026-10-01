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

INSPECT = """
  General

    id\t\tdpl_123
    url\t\t{despliegue}

  Aliases

{alias}

  Builds

    ╶ .        [0ms]
"""


def vercel_de_mentira(carpeta: Path, alias: list[str], inspect_falla: bool = False) -> Path:
    bin_ = carpeta / "bin"
    bin_.mkdir()
    lineas = "\n".join(f"    ╶ {a}" for a in alias)
    salida_inspect = INSPECT.format(despliegue=DESPLIEGUE, alias=lineas)
    (bin_ / "inspect.txt").write_text(salida_inspect, encoding="utf-8")
    inspect = "exit 1" if inspect_falla else f'cat "{bin_ / "inspect.txt"}"'
    guion = f"""#!/bin/sh
case "$1" in
  deploy) echo "{DESPLIEGUE}" ;;
  inspect) {inspect} ;;
  *) exit 0 ;;
esac
"""
    vercel = bin_ / "vercel"
    vercel.write_text(guion, encoding="utf-8")
    vercel.chmod(vercel.stat().st_mode | stat.S_IEXEC)
    return bin_


def publicar(tmp_path, alias, inspect_falla=False) -> dict:
    sitio = tmp_path / "salida" / "sitio"
    sitio.mkdir(parents=True)
    (sitio / "index.html").write_text("<html></html>", encoding="utf-8")
    bin_ = vercel_de_mentira(tmp_path, alias, inspect_falla)
    entorno = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "VERCEL_TOKEN": "x"}
    subprocess.run(["bash", str(SCRIPT), str(sitio), "masterplan-loteo"], check=True,
                   env=entorno, capture_output=True, text=True)
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
