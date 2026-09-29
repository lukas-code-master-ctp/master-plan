"""El visor: el sitio (html, css, js, vendor) que acompaña a los datos de cada loteo.

    python -m pipeline.visor --sitio "salidas/<proyecto>/sitio"

Construir un loteo copia el visor junto a sus datos. Cuando solo cambia el visor,
no hace falta reconstruir: basta volver a copiarlo sobre un sitio ya construido.
La huella dice qué versión del visor lleva cada sitio publicado.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path

from . import config

# Lo que no es del visor: los datos y las panorámicas de prueba de la plantilla,
# las pruebas y la basura del Finder. Se aplica a cualquier nivel, como hace copytree.
IGNORAR = shutil.ignore_patterns("datos", "panoramas", "*.test.js", ".DS_Store")


def copiar(sitio: Path) -> None:
    """Copia el visor sobre el sitio sin tocar sus datos: la carpeta queda
    autocontenida y se sube tal cual."""
    shutil.copytree(config.PLANTILLA_WEB, sitio, ignore=IGNORAR, dirs_exist_ok=True)


def huella(origen: Path | None = None) -> str:
    """SHA-256 de lo que `copiar` llevaría al sitio: rutas relativas y contenido.

    Mira exactamente lo que copytree copia, así que tocar una prueba o los datos de
    la plantilla no cambia la huella. Las rutas van en formato POSIX y ordenadas
    para que dé lo mismo en Windows que en el contenedor.
    """
    origen = origen or config.PLANTILLA_WEB
    archivos = []
    for carpeta, subcarpetas, nombres in os.walk(origen, followlinks=True):
        ignorados = IGNORAR(carpeta, subcarpetas + nombres)
        subcarpetas[:] = [n for n in subcarpetas if n not in ignorados]
        archivos += [Path(carpeta, n) for n in nombres if n not in ignorados]

    suma = hashlib.sha256()
    for relativa, ruta in sorted((a.relative_to(origen).as_posix(), a) for a in archivos):
        contenido = ruta.read_bytes()
        # Ruta y largo antes del contenido: ningún archivo puede hacerse pasar
        # por el final de otro.
        suma.update(f"{relativa}\0{len(contenido)}\0".encode("utf-8"))
        suma.update(contenido)
    return suma.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Copia el visor actual sobre un sitio ya construido.")
    parser.add_argument("--sitio", type=Path, required=True,
                        help="carpeta del sitio construido (la que tiene datos/parcelas.json)")
    argumentos = parser.parse_args(argv)

    sitio = argumentos.sitio
    if not (sitio / "datos" / "parcelas.json").is_file():
        print(f"{sitio} no es un sitio construido: falta datos/parcelas.json. "
              f"Constrúyelo primero con python -m pipeline.construir.", file=sys.stderr)
        return 1

    copiar(sitio)
    print(f"Visor copiado en {sitio} (huella {huella(config.PLANTILLA_WEB)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
