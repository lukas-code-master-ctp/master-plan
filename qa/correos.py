"""Lo que hay en el buzón de QA: los correos que la consola local "mandó".

    python -m qa.correos                      # todos, del más nuevo al más viejo
    python -m qa.correos --para duenio@loteadora-demo.test
    python -m qa.correos --ultimo             # solo el enlace del último, para qa:captura

La carpeta es la de `QA_BUZON` o, si no está, `.qa/buzon` del repo: la misma que
`qa:levantar` le pasa a la consola como `CONSOLA_BUZON`. Cada correo es un JSON que
escribe `consola.cuentas.CorreoEnCarpeta`, con un nombre que empieza con la hora en
nanosegundos, así que ordenar por nombre es ordenar por tiempo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def carpeta_del_buzon() -> Path:
    propia = os.environ.get("QA_BUZON", "").strip()
    return Path(propia) if propia else REPO / ".qa" / "buzon"


def leer_correos(carpeta: Path, para: str | None = None) -> list[dict]:
    """Los correos de la carpeta, del más nuevo al más viejo.

    Los `.tmp` son correos a medio escribir (empiezan con punto y no terminan en
    `.json`), así que no entran. Un JSON roto tampoco: se avisa y se sigue.
    """
    if not carpeta.is_dir():
        return []
    correos = []
    for archivo in sorted(carpeta.glob("*.json"), key=lambda a: a.name, reverse=True):
        if archivo.name.startswith("."):
            continue
        try:
            correo = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            print(f"aviso: no se pudo leer {archivo.name}: {error}", file=sys.stderr)
            continue
        if not isinstance(correo, dict):
            print(f"aviso: {archivo.name} no es un correo", file=sys.stderr)
            continue
        if para and str(correo.get("para", "")).strip().lower() != para.strip().lower():
            continue
        correo["archivo"] = archivo.name
        correos.append(correo)
    return correos


def como_texto(correo: dict) -> str:
    lineas = [
        f"{correo.get('enviado_en', '?')}  para {correo.get('para', '?')}",
        f"  {correo.get('asunto', '(sin asunto)')}",
    ]
    lineas += [f"  → {enlace}" for enlace in correo.get("enlaces") or []]
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qa:correos", description=__doc__.split("\n\n")[0])
    parser.add_argument("--ultimo", action="store_true",
                        help="imprime solo el primer enlace del correo más nuevo")
    parser.add_argument("--para", metavar="CORREO", help="solo los correos a esta dirección")
    args = parser.parse_args(argv)

    carpeta = carpeta_del_buzon()
    correos = leer_correos(carpeta, args.para)

    if args.ultimo:
        # Exit 1 si no hay enlace: quien lo pega en otro comando no debe seguir
        # con una URL vacía.
        if not correos:
            print(f"No hay correos en {carpeta}.", file=sys.stderr)
            return 1
        enlaces = correos[0].get("enlaces") or []
        if not enlaces:
            print(f"El último correo ({correos[0].get('asunto', '')}) no trae enlaces.",
                  file=sys.stderr)
            return 1
        print(enlaces[0])
        return 0

    if not correos:
        filtro = f" para {args.para}" if args.para else ""
        print(f"No hay correos{filtro} en {carpeta}.")
        return 0
    print("\n\n".join(como_texto(c) for c in correos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
