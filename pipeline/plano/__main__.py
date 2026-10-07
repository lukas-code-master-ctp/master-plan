"""Crea tu KMZ desde la línea de comandos.

    python -m pipeline.plano digitalizar <carpeta-del-plano>
    python -m pipeline.plano georreferenciar <carpeta-del-plano>
    python -m pipeline.plano kmz <carpeta-del-plano> <destino.kmz>

El formato de `entradas.json` y `digitalizado.json` está en `pipeline/plano/digitalizar.py`;
el de `georreferencia.json`, en `pipeline/plano/georreferencia.py`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .digitalizar import ENTRADAS, digitalizar
from .georreferencia import georreferenciar
from .salida import kmz


def _avance(texto: str) -> None:
    # La consola lee la salida en vivo: cada etapa sale apenas termina.
    print(texto, flush=True)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline.plano",
                                     description="Del plano aprobado a los lotes de la subdivisión.")
    sub = parser.add_subparsers(dest="comando", required=True)
    d = sub.add_parser("digitalizar", help="lee entradas.json y escribe digitalizado.json")
    d.add_argument("carpeta", type=Path)
    g = sub.add_parser("georreferenciar",
                       help="cuadrícula, anclas o un punto con su coordenada → georreferencia.json y lotes.geojson")
    g.add_argument("carpeta", type=Path)
    k = sub.add_parser("kmz", help="digitalizado.json + georreferencia.json → KMZ de la subdivisión")
    k.add_argument("carpeta", type=Path)
    k.add_argument("destino", type=Path)
    args = parser.parse_args(argv)
    if not (args.carpeta / ENTRADAS).is_file():
        print(f"No está {args.carpeta / ENTRADAS}", file=sys.stderr)
        return 2
    try:
        if args.comando == "digitalizar":
            digitalizar(args.carpeta, avance=_avance)
        elif args.comando == "georreferenciar":
            georreferenciar(args.carpeta, avance=_avance)
        else:
            kmz(args.carpeta, args.destino, avance=_avance)
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
