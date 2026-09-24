"""Lectura de la planilla comercial.

Las columnas se detectan por nombre, ignorando tildes, mayúsculas y espacios. Así
puedes agregar una columna "Precio" o "Moneda" al xlsx sin tocar el código. La
misma tabla puede venir en .xlsx o en .csv.

Si la parcelación lleva sufijo de etapa ("PRADERAS DE CAUQUENES ET2") y hay más de
una etapa, el id del lote queda como "etapa-número" ("2-7"), igual que lo arma
kmz.py con los colores del dibujo. La parcelación sin sufijo es la etapa 1.
"""
from __future__ import annotations

import csv
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
    "servidumbre_m2": ("servidumbre m2", "servidumbre_m2", "superficie servidumbre",
                       "servidumbre superficie"),
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
    # Estados del CRM: una venta en curso saca el lote de la vitrina.
    "pre-reserva": "reservado",
    "pre reserva": "reservado",
    "agenda": "reservado",
    "borrador": "reservado",
    "vendido": "vendido",
    "vendida": "vendido",
    "escritura": "vendido",
    "entrada cbr": "vendido",
    "no disponible": "no_disponible",
    "no en venta": "no_en_venta",
}


@dataclass
class FichaComercial:
    id: str
    numero: str | None = None
    etapa: int | None = None
    parcelacion: str | None = None
    estado: str = ESTADO_POR_DEFECTO
    superficie_m2: int | None = None
    servidumbre_m: float | None = None
    servidumbre_m2: float | None = None
    precio: float | None = None
    moneda: str = "CLP"
    link_pago: str | None = None


def leer_planilla(ruta: Path, parcelacion: str | None = None) -> dict[str, FichaComercial]:
    """La planilla, venga como .xlsx o como .csv.

    Con `parcelacion` se queda solo con las filas de ese loteo (y sus etapas), para
    cuando la tabla trae varios proyectos, como el export del CRM.
    """
    ruta = Path(ruta)
    filas = _filas_csv(ruta) if ruta.suffix.lower() == ".csv" else _filas_excel(ruta)
    return fichas_desde_filas(filas, parcelacion=parcelacion, origen=ruta.name)


def leer_excel(ruta: Path, hoja: str | None = None) -> dict[str, FichaComercial]:
    return fichas_desde_filas(_filas_excel(ruta, hoja), origen=Path(ruta).name)


def fichas_desde_filas(filas: list, parcelacion: str | None = None,
                       origen: str = "la planilla") -> dict[str, FichaComercial]:
    if not filas:
        return {}

    indices = _mapear_columnas(filas[0])
    if "id" not in indices:
        raise ValueError(
            f"no encontré la columna de parcela en {origen}; "
            f"encabezados leídos: {filas[0]}"
        )

    base = _sin_tildes(parcelacion) if parcelacion else None
    crudas: list[tuple[str, int | None, str | None, tuple]] = []
    for fila in filas[1:]:
        numero = normalizar_id(_valor(fila, indices.get("id")))
        if not numero:
            continue
        nombre_parcelacion = _texto(_valor(fila, indices.get("parcelacion")))
        etapa = _etapa_de(nombre_parcelacion, base)
        if base is not None and etapa is None:
            continue   # otra parcelación
        crudas.append((numero, etapa, nombre_parcelacion, fila))

    # Sin sufijo es la etapa 1, pero solo cuando alguna fila sí trae sufijo: en un
    # loteo sin etapas nadie es "etapa 1".
    if any(etapa is not None for _, etapa, _, _ in crudas):
        crudas = [(n, e if e is not None else 1, p, f) for n, e, p, f in crudas]
    varias_etapas = len({etapa for _, etapa, _, _ in crudas}) > 1

    fichas: dict[str, FichaComercial] = {}
    for numero, etapa, nombre_parcelacion, fila in crudas:
        identificador = f"{etapa}-{numero}" if varias_etapas else numero
        precio = _numero(_valor(fila, indices.get("precio")))
        fichas[identificador] = FichaComercial(
            id=identificador,
            numero=numero,
            etapa=etapa,
            parcelacion=nombre_parcelacion,
            estado=normalizar_estado(_valor(fila, indices.get("estado"))),
            superficie_m2=_entero(_valor(fila, indices.get("superficie"))),
            # Un cero no es un dato: es lo que queda cuando nadie lo llenó.
            servidumbre_m=_numero(_valor(fila, indices.get("servidumbre"))) or None,
            servidumbre_m2=_numero(_valor(fila, indices.get("servidumbre_m2"))) or None,
            # Y un precio en cero no es un precio: es "a consultar".
            precio=precio if precio else None,
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


def _filas_excel(ruta: Path, hoja: str | None = None) -> list:
    libro = openpyxl.load_workbook(ruta, data_only=True, read_only=True)
    pagina = libro[hoja] if hoja else libro.worksheets[0]
    filas = list(pagina.iter_rows(values_only=True))
    libro.close()
    return filas


def _filas_csv(ruta: Path) -> list:
    # utf-8-sig se come la marca de orden de bytes que Excel deja al exportar.
    with open(ruta, encoding="utf-8-sig", newline="") as archivo:
        return list(csv.reader(archivo))


def _etapa_de(nombre_parcelacion: str | None, base: str | None) -> int | None:
    """Número de etapa según el sufijo de la parcelación ("… ET2", "… ETAPA 2").

    Con `base` además exige que la parcelación sea esa (con o sin sufijo); si no lo
    es devuelve None. Sin sufijo y con base, es la etapa 1.
    """
    limpio = _sin_tildes(nombre_parcelacion)
    if base is not None:
        coincidencia = re.fullmatch(re.escape(base) + r"(?:\s*(?:et|etapa)\s*0*(\d+))?", limpio)
        if not coincidencia:
            return None
        return int(coincidencia.group(1)) if coincidencia.group(1) else 1
    coincidencia = re.search(r"\b(?:et|etapa)\s*0*(\d+)\b", limpio)
    return int(coincidencia.group(1)) if coincidencia else None


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
