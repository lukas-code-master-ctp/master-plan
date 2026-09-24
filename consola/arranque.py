"""Dejar la consola lista para entrar por primera vez.

    python -m consola.arranque

Hace dos cosas, las dos una sola vez y sin pisar nada:

1. Si no hay ninguna loteadora, crea la de casa con su cuenta e imprime la clave
   provisional. No hay clave por defecto ni cuenta sin clave: la clave se genera al
   azar y se muestra una vez, así que la única forma de que quede débil es que
   alguien la cambie por una débil a propósito.
2. Adopta los loteos que ya estaban a la vista antes de que hubiera cuentas, con su
   slug, su nombre y su URL intactos. Un loteo publicado no puede cambiar de
   identidad: su sitio ya está en internet con ese nombre.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pipeline import config

from .acceso import Sesion
from .datos import Base
from .proyectos import Registro

# La loteadora de casa, que además es la que opera la plataforma.
CASA = "CompraTuParcela"
CORREO_DE_CASA = "e.ruiz@compratuparcela.cl"
NOMBRE_DE_CASA = "Eduardo Ruiz"

# El índice de carpetas de cuando la consola no tenía base. Se lee una vez y se
# deja marcado como migrado; no se borra, por si hay que mirarlo.
INDICE_VIEJO = config.DATOS / "proyectos.json"


def preparar(base: Base | None = None, registro: Registro | None = None) -> list[str]:
    """Devuelve las líneas que hay que mostrar por pantalla."""
    base = base or Base()
    registro = registro or Registro(base=base, crm_por_defecto=config.csv_del_crm())
    dichos: list[str] = []

    clave = _primera_cuenta(base)
    if clave:
        dichos += [
            f"▶ Primera vez: creé la cuenta {CORREO_DE_CASA}",
            f"  Clave provisional: {clave}",
            "  Anótala: no se vuelve a mostrar. Cámbiala al entrar.",
        ]

    adoptados = _adoptar_lo_que_ya_estaba(base, registro)
    if adoptados:
        dichos.append(f"▶ Adopté {len(adoptados)} loteo(s) que ya estaban: {', '.join(adoptados)}")
    return dichos


def _primera_cuenta(base: Base) -> str | None:
    if base.clientes():
        return None
    _, clave = base.crear_cliente(CASA, CORREO_DE_CASA, NOMBRE_DE_CASA)
    base.ascender_a_plataforma(CORREO_DE_CASA)
    return clave


def _adoptar_lo_que_ya_estaba(base: Base, registro: Registro) -> list[str]:
    if not INDICE_VIEJO.is_file():
        return []
    rutas = [Path(r) for r in json.loads(INDICE_VIEJO.read_text(encoding="utf-8"))]
    duenio = base.usuario_por_email(CORREO_DE_CASA)
    if duenio is None:
        return []
    vista = registro.para(Sesion(usuario_id=duenio.id, cliente_id=duenio.cliente_id,
                                 rol=duenio.rol, quien=duenio.email))

    adoptados = []
    for ruta in rutas:
        if not ruta.is_dir():
            continue
        adoptados.append(vista.vincular(ruta).slug)
    INDICE_VIEJO.rename(INDICE_VIEJO.with_suffix(".json.migrado"))
    return adoptados


if __name__ == "__main__":
    for linea in preparar():
        print(linea)
    sys.exit(0)
