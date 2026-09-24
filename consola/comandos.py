"""Los comandos que la consola le pide al pipeline.

Están aparte del servidor para poder verlos de un vistazo —y para que las pruebas
corran sin construir un loteo entero.

Todo va explícito: la consola dice dónde va la salida, cuál es el CSV comercial y
cómo se llama el proyecto en el hosting. El pipeline no resuelve nada por su cuenta,
porque sus constantes globales son las mismas para todos los clientes.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pipeline import config

PUBLICAR = config.RAIZ / "publicar.sh"


class Comandos:
    def construir(self, proyecto, sin_imagenes: bool = False) -> list[str]:
        orden = [sys.executable, "-m", "pipeline.construir",
                 "--proyecto", str(proyecto.fuentes),
                 "--salida", str(proyecto.salida.base)]
        orden += ["--crm", str(proyecto.crm)] if proyecto.crm else ["--sin-crm"]
        if sin_imagenes:
            orden.append("--sin-imagenes")
        return orden

    def control_de_calce(self, proyecto) -> list[str]:
        return [sys.executable, "-m", "pipeline.qa_overlay",
                "--proyecto", str(proyecto.fuentes),
                "--salida", str(proyecto.salida.base)]

    def publicar(self, proyecto, vercel_proyecto: str, crear: bool = False) -> list[str]:
        orden = [str(PUBLICAR), str(proyecto.salida.web), vercel_proyecto]
        if crear:
            orden.append("--crear")
        return orden


def encadenar(*comandos: list[str]) -> list[str]:
    """Un solo comando que corre varios en fila y corta al primer error.

    Sirve para que "Construir" deje también el control de calce hecho sin que el
    usuario tenga que apretar dos veces.
    """
    guion = " && ".join(" ".join(_escapar(parte) for parte in comando) for comando in comandos)
    return ["/bin/sh", "-c", guion]


def _escapar(parte: str) -> str:
    return "'" + str(parte).replace("'", "'\\''") + "'"
