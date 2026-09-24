"""La planilla comercial directo del export del CRM.

`ctp_parcelas_latest.csv` (lo genera agente_reporteria) trae todas las parcelas de
todos los loteos con su estado, superficie y precio. Este módulo solo traduce sus
encabezados al vocabulario de la planilla y filtra la parcelación pedida; la lectura
es la misma de excel.py.
"""
from __future__ import annotations

import csv
from pathlib import Path

from .excel import FichaComercial, fichas_desde_filas

# Encabezado del CRM → encabezado que entiende excel.py. SERVIDUMBRE en el CRM es
# la superficie de la servidumbre en m², no su ancho.
COLUMNAS = {
    "SUPERFICIE_CRM": "Superficie",
    "SERVIDUMBRE": "Servidumbre m2",
    "VALOR_CONTADO": "Precio",
    "ESTADO_CRM_PARCELA": "Estado",
}


def leer_crm(ruta: Path, parcelacion: str) -> dict[str, FichaComercial]:
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        filas = list(csv.reader(archivo))
    if not filas:
        return {}
    filas[0] = [COLUMNAS.get(celda.strip(), celda) for celda in filas[0]]

    fichas = fichas_desde_filas(filas, parcelacion=parcelacion, origen=Path(ruta).name)
    if not fichas:
        raise ValueError(f"no encontré la parcelación {parcelacion!r} en {Path(ruta).name}")
    return fichas
