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
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

import openpyxl

from .config import ESTADO_POR_DEFECTO, ESTADOS
from .kmz import normalizar_id

ALIAS_COLUMNAS = {
    "id": ("parcela", "lote", "parcela/lote"),
    "parcelacion": ("parcelacion", "proyecto", "nombre proyecto", "nombre del proyecto"),
    # La etapa también puede venir en su propia columna: "2", "ET2" o "Etapa 2".
    "etapa": ("etapa",),
    "estado": ("estado", "situacion"),
    "servidumbre": ("servidumbre", "servidumbre m", "servidumbre metros"),
    "servidumbre_m2": ("servidumbre m2", "servidumbre_m2", "superficie servidumbre",
                       "servidumbre superficie"),
    "superficie": ("superficie", "superficie m2", "sup", "m2"),
    "precio": ("precio", "valor", "precio uf", "precio clp"),
    "moneda": ("moneda", "unidad"),
    "link_pago": ("link de pago", "link pago", "pago", "url de pago"),
    # Lo que la ficha muestra en sus tarjetas y en el precio, si la planilla lo trae.
    "rol": ("rol", "rol de avaluo", "rol avaluo", "rol sii", "rol de avaluo fiscal"),
    "topografia": ("topografia", "relieve"),
    "pie": ("pie", "pie minimo", "monto pie", "pie inicial"),
    "cuotas": ("cuotas", "n cuotas", "numero de cuotas", "cantidad de cuotas", "nro cuotas"),
    "valor_cuota": ("valor cuota", "valor de la cuota", "monto cuota", "cuota"),
    "reserva": ("reserva", "monto reserva", "monto de reserva", "valor reserva"),
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
    "salida cbr": "vendido",
    "promesa": "vendido",
    # Cierra: una parcela EN_PROCESO tiene una venta andando; INSCRITA ya es de otro.
    "en proceso": "reservado",
    "enviado cliente": "reservado",
    "inscrita": "vendido",
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
    rol: str | None = None
    topografia: str | None = None
    # El pie y la cuota van en la moneda del precio; la reserva, en pesos.
    pie: float | None = None
    cuotas: int | None = None
    valor_cuota: float | None = None
    reserva: float | None = None


def alinear_con(fichas: dict[str, FichaComercial], ids: set[str] | dict,
                explicaciones: list[str] | None = None) -> dict[str, FichaComercial]:
    """Las fichas con el id que usa el KMZ cuando la planilla y el KMZ nombran distinto.

    Con varias etapas la planilla arma "etapa-número" ("1-A1"), pero el KMZ no siempre
    rotula igual. Las fichas que ya calzan se quedan como están; el resto se cruza:

    1. Por el número solo, si no se repite entre etapas (Hacienda Vichuquén: la
       planilla dice 1-A1, el KMZ A1). Si "7" está en la etapa 1 y en la 2, sin etapa
       no hay cómo saber cuál es.
    2. Por descarte, etapa contra grupo de rótulos del KMZ (Lomas de Quillón: la etapa
       2 viene "2-7", la 1 sin prefijo, "7", y la 3 con letra, "A-7"). Un grupo del KMZ
       se asigna a la única etapa que contiene sus números, y se repite hasta que no
       quede ninguno sin ambigüedad.

    En `explicaciones` se dice qué se cruzó, para que la persona lo pueda revisar.
    """
    conocidos = set(ids)
    pendientes = [f for f in fichas.values() if f.id not in conocidos]
    libres = conocidos - set(fichas)
    if not pendientes or not libres:
        return fichas

    nuevos: dict[str, str] = {}
    repeticiones = Counter(f.numero for f in pendientes)
    for ficha in pendientes:
        if ficha.numero in libres and repeticiones[ficha.numero] == 1:
            nuevos[ficha.id] = ficha.numero
    if nuevos and explicaciones is not None:
        explicaciones.append(f"{len(nuevos)} parcela(s) se cruzaron con el KMZ por el número "
                             "del lote, sin la etapa")
    libres -= set(nuevos.values())

    etapas: dict[int, dict[str, FichaComercial]] = {}
    for ficha in pendientes:
        if ficha.id not in nuevos and ficha.numero and ficha.etapa is not None:
            etapas.setdefault(ficha.etapa, {})[ficha.numero] = ficha
    grupos: dict[str, dict[str, str]] = {}
    for identificador in libres:
        prefijo, numero = _prefijo_y_numero(identificador)
        grupos.setdefault(prefijo, {})[numero] = identificador

    asignado = True
    while asignado and grupos and etapas:
        asignado = False
        for prefijo, numeros in list(grupos.items()):
            candidatas = [e for e, propias in etapas.items()
                          if sum(n in propias for n in numeros) >= CALCE_POR_DESCARTE * len(numeros)]
            if len(candidatas) != 1:
                continue
            etapa = candidatas[0]
            cruzadas = 0
            for numero, identificador in numeros.items():
                if numero in etapas[etapa]:
                    nuevos[etapas[etapa][numero].id] = identificador
                    cruzadas += 1
            if explicaciones is not None:
                rotulo = f"con prefijo «{prefijo}»" if prefijo else "sin prefijo"
                explicaciones.append(f"la etapa {etapa} de la planilla se cruzó con los lotes "
                                     f"{rotulo} del KMZ ({cruzadas} parcelas)")
            del grupos[prefijo]
            del etapas[etapa]
            asignado = True

    if not nuevos:
        return fichas
    return {nuevos.get(f.id, f.id): replace(f, id=nuevos.get(f.id, f.id)) for f in fichas.values()}


# Un grupo del KMZ se cruza con una etapa si casi todos sus números están en ella: un
# lote de más en el dibujo (un "RESTO", una reserva) no debe impedir el cruce.
CALCE_POR_DESCARTE = 0.9


def _prefijo_y_numero(identificador: str) -> tuple[str, str]:
    """"A7" → ("A", "7").  "7" → ("", "7").  "3-7" → ("3-", "7")."""
    coincidencia = re.fullmatch(r"(.*?)(\d+)", identificador)
    if not coincidencia:
        return identificador, ""
    return coincidencia.group(1), coincidencia.group(2)


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
                       origen: str = "la planilla",
                       permitir_repetidas: bool = False) -> dict[str, FichaComercial]:
    """Las fichas de una tabla ya leída.

    Una planilla que repite una parcela se rechaza. El export del CRM no: trae de
    vez en cuando una fila duplicada y cortar la construcción por eso sería peor;
    ahí queda la última, como siempre.
    """
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
        # Una columna Etapa, si la hay, manda sobre el sufijo del nombre.
        etapa = _etapa_de(_texto(_valor(fila, indices.get("etapa"))), None) or etapa
        crudas.append((numero, etapa, nombre_parcelacion, fila))

    # Sin sufijo es la etapa 1, pero solo cuando alguna fila sí trae sufijo: en un
    # loteo sin etapas nadie es "etapa 1".
    if any(etapa is not None for _, etapa, _, _ in crudas):
        crudas = [(n, e if e is not None else 1, p, f) for n, e, p, f in crudas]
    varias_etapas = len({etapa for _, etapa, _, _ in crudas}) > 1

    fichas: dict[str, FichaComercial] = {}
    repetidas: list[str] = []
    for numero, etapa, nombre_parcelacion, fila in crudas:
        identificador = f"{etapa}-{numero}" if varias_etapas else numero
        if identificador in fichas:
            repetidas.append(identificador)
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
            rol=_texto(_valor(fila, indices.get("rol"))),
            topografia=_texto(_valor(fila, indices.get("topografia"))),
            pie=_pie(_valor(fila, indices.get("pie")), precio),
            # Como el precio: un cero es una celda que nadie llenó.
            cuotas=_entero(_valor(fila, indices.get("cuotas"))) or None,
            valor_cuota=_numero(_valor(fila, indices.get("valor_cuota"))) or None,
            reserva=_numero(_valor(fila, indices.get("reserva"))) or None,
        )
    # Una parcela dos veces es casi siempre dos etapas que numeran desde 1 sin decir
    # cuál es cuál. Quedarse con la última publicaría el precio de otra parcela.
    if repetidas and not permitir_repetidas:
        unicas = sorted(set(repetidas), key=lambda i: (len(i), i))
        raise ValueError(
            f"{origen} repite {len(unicas)} parcela(s): {', '.join(unicas[:10])}"
            f"{' y otras' if len(unicas) > 10 else ''}. Si son de etapas distintas, pon el nombre "
            "del proyecto con su etapa (\"… ET2\") en la columna Proyecto, o usa la "
            "plantilla del loteo, que ya viene así.")
    return fichas


def normalizar_estado(valor) -> str:
    # "NO_DISPONIBLE", "EN_PROCESO": así los escribe Cierra.
    clave = _sin_tildes(valor).replace("_", " ")
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
    if base is None and limpio.isdigit():
        return int(limpio)   # una columna Etapa con solo el número
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


def _pie(valor, precio: float | None) -> float | None:
    """El pie como monto. "20%" se calcula sobre el precio; sin precio no se puede."""
    if isinstance(valor, str) and "%" in valor:
        porcentaje = _numero(valor.replace("%", ""))
        return round(precio * porcentaje / 100) if porcentaje and precio else None
    return _numero(valor) or None


def _entero(valor) -> int | None:
    numero = _numero(valor)
    return None if numero is None else int(round(numero))
