"""Crea tu KMZ desde la línea de comandos.

    python -m pipeline.plano digitalizar <carpeta-del-plano>

El formato de `entradas.json` y `digitalizado.json` está en `pipeline/plano/digitalizar.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .digitalizar import digitalizar


def _avance(texto: str) -> None:
    # La consola lee la salida en vivo: cada etapa sale apenas termina.
    print(texto, flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline.plano",
                                     description="Del plano aprobado a los lotes de la subdivisión.")
    sub = parser.add_subparsers(dest="comando", required=True)
    d = sub.add_parser("digitalizar", help="lee entradas.json y escribe digitalizado.json")
    d.add_argument("carpeta", type=Path)
    args = parser.parse_args(argv)
    if args.comando == "digitalizar":
        if not (args.carpeta / "entradas.json").is_file():
            print(f"No está {args.carpeta / 'entradas.json'}", file=sys.stderr)
            return 2
        try:
            digitalizar(args.carpeta, avance=_avance)
        except (ValueError, KeyError, FileNotFoundError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
