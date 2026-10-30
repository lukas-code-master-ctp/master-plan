"""Corre un trabajo de la consola en su propia máquina (un Cloud Run Job).

    python -m consola.obrero <id>

La consola anota el trabajo en la base y enciende el job con su id
(`consola/trabajos_remotos.py`). Acá se corre igual que antes en la consola, con
`Trabajos` (mismo subproceso, mismo tope, mismo corte del árbol de procesos), y se
copia el avance a la base cada `LATIDO` segundos para que la pantalla lo vea.

Siempre sale con 0: si el trabajo falló, eso queda anotado en la base y lo muestra la
pantalla. Un código distinto haría que Google reintente, y un trabajo no se corre dos
veces (`TrabajosRemotos.tomar`).
"""
from __future__ import annotations

import json
import sys
import traceback

from pipeline import config

from .datos import Base
from .trabajos import Trabajos
from .trabajos_remotos import TrabajosRemotos

LATIDO = 3.0


def correr(identificador: str, base: Base, armar_cierre=None, latido: float = LATIDO,
           trabajos: Trabajos | None = None) -> str:
    """Corre el trabajo y devuelve cómo terminó. `armar_cierre(descriptores)` vuelve a
    armar su `al_terminar`; sin él se usa el de la consola (`cierre_desde`)."""
    remotos = TrabajosRemotos(base, lanzador=None)
    fila = remotos.fila(identificador)
    if fila is None or not remotos.tomar(identificador):
        print(f"[obrero] {identificador}: no está esperando; no se corre", flush=True)
        return "saltado"

    lineas = json.loads(fila.lineas)
    try:
        al_terminar = (armar_cierre or _cierre_de_la_consola(base))(json.loads(fila.cierres))
    except Exception:                       # noqa: BLE001 - lo ve la pantalla
        print(traceback.format_exc(), flush=True)
        remotos.anotar(identificador, estado="falló", codigo=-1,
                       lineas=lineas + ["no pude preparar el trabajo: avísanos"])
        return "falló"

    trabajos = trabajos or Trabajos(directorio=config.RAIZ)
    local = trabajos.lanzar(fila.proyecto, fila.accion, json.loads(fila.comando),
                            al_terminar=al_terminar, lineas=lineas, pesado=bool(fila.pesado),
                            identificador=identificador)
    trabajo = trabajos.ver(local)
    # Mientras corra su `al_terminar` sigue "corriendo" en la base: la consola no deja
    # lanzar otro sobre el mismo loteo hasta que lo que dejó esté guardado.
    while not trabajo.fin.wait(latido):
        remotos.anotar(identificador, lineas=list(trabajo.lineas))
    remotos.anotar(identificador, estado=trabajo.estado, codigo=trabajo.codigo,
                   vencido=trabajo.vencido, lineas=list(trabajo.lineas))
    print(f"[obrero] {identificador}: {fila.accion} de {fila.proyecto} terminó "
          f"{trabajo.estado} (código {trabajo.codigo})", flush=True)
    return trabajo.estado


def _cierre_de_la_consola(base: Base):
    # Recién acá: importar la app arma FastAPI entero, y las pruebas del obrero no lo necesitan.
    from .app import cierre_desde
    from .disenos import Disenos
    from .kmzs import RegistroKmz
    from .proyectos import Registro

    registro, disenos, kmzs = Registro(base=base), Disenos(base=base), RegistroKmz(base=base)
    return lambda descriptores: cierre_desde(descriptores, registro, disenos, kmzs)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("uso: python -m consola.obrero <id del trabajo>", file=sys.stderr)
        return 2
    correr(argv[0], Base())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
