"""Lectura de la planilla comercial.

Las columnas se detectan por nombre, ignorando tildes, mayúsculas y espacios. Así
puedes agregar una columna "Precio" o "Moneda" al xlsx sin tocar el código.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import openpyxl

from .config import ESTADO_POR_DEFECTO, ESTADOS
from .kmz import normalizar_id

ALIAS_COLUMNAS = {
    "id": ("parcela", "lote", "parcela/lote"),
    "parcelacion": ("parcelacion", "proyecto", "etapa"),
    "estado": ("estado", "situacion"),
    "servidumbre": ("servidumbre", "servidumbre m", "servidumbre metros"),
    "superficie": ("superficie", "superficie m2", "sup", "m2"),
    "precio": ("precio", "valor", "precio uf", "precio clp"),
    "moneda": ("moneda", "unidad"),
    "link_pago": ("link de pago", "link pago", "pago", "url de pago"),
}

ALIAS_ESTADOS = {
    "disponible": "disponible",
    "libre": "disponible",
    "reservado": "reservado",
    "reserva": "reservado",
    "vendido": "vendido",
    "vendida": "vendido",
    "no disponible": "no_disponible",
    "no en venta": "no_en_venta",
}


@dataclass
class FichaComercial:
    id: str
    parcelacion: str | None = None
    estado: str = ESTADO_POR_DEFECTO
    superficie_m2: int | None = None
    servidumbre_m: float | None = None
    precio: float | None = None
    moneda: str = "CLP"
    link_pago: str | None = None


def leer_excel(ruta: Path, hoja: str | None = None) -> dict[str, FichaComercial]:
    libro = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    pagina = libro[hoja] if hoja else libro.worksheets[0]
    filas = list(pagina.iter_rows(values_only=True))
    libro.close()

    if not filas:
        return {}

    indices = _mapear_columnas(filas[0])
    if "id" not in indices:
        raise ValueError(
            f"no encontré la columna de parcela en {ruta.name}; "
            f"encabezados leídos: {filas[0]}"
        )

    fichas: dict[str, FichaComercial] = {}
    for fila in filas[1:]:
        identificador = normalizar_id(_valor(fila, indices.get("id")))
        if not identificador:
            continue
        fichas[identificador] = FichaComercial(
            id=identificador,
            parcelacion=_texto(_valor(fila, indices.get("parcelacion"))),
            estado=normalizar_estado(_valor(fila, indices.get("estado"))),
            superficie_m2=_entero(_valor(fila, indices.get("superficie"))),
            servidumbre_m=_numero(_valor(fila, indices.get("servidumbre"))),
            precio=_numero(_valor(fila, indices.get("precio"))),
            moneda=_texto(_valor(fila, indices.get("moneda"))) or "CLP",
            link_pago=_texto(_valor(fila, indices.get("link_pago"))),
        )
    return fichas


def normalizar_estado(valor) -> str:
    clave = _sin_tildes(valor)
    if not clave:
        return ESTADO_POR_DEFECTO
    if clave in ALIAS_ESTADOS:
        return ALIAS_ESTADOS[clave]
    if clave in ESTADOS:
        return clave
    return ESTADO_POR_DEFECTO


def _mapear_columnas(encabezado) -> dict[str, int]:
    indices: dict[str, int] = {}
    normalizados = [_sin_tildes(celda) for celda in encabezado]
    for campo, alias in ALIAS_COLUMNAS.items():
        for posicion, nombre in enumerate(normalizados):
            if nombre and nombre in alias:
                indices[campo] = posicion
                break
    return indices


def _sin_tildes(valor) -> str:
    if valor is None:
        return ""
    texto = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", texto).strip().lower().rstrip(".")


def _valor(fila, indice):
    if indice is None or indice >= len(fila):
        return None
    return fila[indice]


def _texto(valor) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _numero(valor) -> float | None:
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = re.sub(r"[^\d,.\-]", "", str(valor))
    if not texto:
        return None
    if "," in texto:
        # Formato chileno con decimales: 1.234.567,89
        texto = texto.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", texto):
        # Puntos que agrupan de a tres son separador de miles: 13.124 son 13124.
        texto = texto.replace(".", "")
    try:
        return float(texto)
    except ValueError:
        return None


def _entero(valor) -> int | None:
    numero = _numero(valor)
    return None if numero is None else int(round(numero))
