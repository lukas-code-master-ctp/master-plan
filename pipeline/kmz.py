"""Lectura del KMZ del loteo.

El KMZ trae los polígonos y las etiquetas por separado: las etiquetas son puntos
sueltos con el nombre del lote. Emparejarlas es trabajo de este módulo.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from . import geo

NS = "{http://www.opengis.net/kml/2.2}"
DISTANCIA_MAXIMA_ETIQUETA_M = 150.0


@dataclass
class ParcelaGeometrica:
    id: str | None
    anillo: geo.Anillo
    en_venta: bool = True
    centroide: geo.Punto = field(init=False)
    area_m2: float = field(init=False)

    def __post_init__(self):
        self.centroide = geo.centroide(self.anillo)
        self.area_m2 = geo.area_m2(self.anillo)


def normalizar_id(texto: str | None) -> str | None:
    """"LOTE A 420" → "A420".  "A214" → "A214".  Basura → None."""
    if texto is None:
        return None
    limpio = re.sub(r"\bLOTES?\b", " ", str(texto).strip().upper())
    coincidencia = re.search(r"([A-Z])\s*0*(\d+)", limpio)
    if not coincidencia:
        return None
    return f"{coincidencia.group(1)}{int(coincidencia.group(2))}"


def leer_kmz(ruta: Path) -> list[ParcelaGeometrica]:
    with zipfile.ZipFile(ruta) as archivo:
        nombres = [n for n in archivo.namelist() if n.lower().endswith(".kml")]
        if not nombres:
            raise ValueError(f"{ruta.name} no contiene ningún .kml")
        kml = archivo.read(nombres[0]).decode("utf-8", "ignore")
    return _parsear(kml)


def _parsear(kml: str) -> list[ParcelaGeometrica]:
    raiz = ET.fromstring(kml)
    etiquetas: dict[str, geo.Punto] = {}
    parcelas: list[ParcelaGeometrica] = []

    for marca in raiz.iter(NS + "Placemark"):
        nombre = marca.find(NS + "name")
        descripcion = marca.find(NS + "description")
        punto = marca.find(f".//{NS}Point/{NS}coordinates")
        anillo = marca.find(f".//{NS}Polygon//{NS}LinearRing/{NS}coordinates")

        if punto is not None and nombre is not None:
            identificador = normalizar_id(nombre.text)
            if identificador:
                etiquetas[identificador] = _coordenadas(punto.text)[0]

        if anillo is not None:
            texto_desc = (descripcion.text or "") if descripcion is not None else ""
            parcelas.append(ParcelaGeometrica(
                id=normalizar_id(nombre.text) if nombre is not None else None,
                anillo=_coordenadas(anillo.text),
                en_venta="NO EN VENTA" not in texto_desc.upper(),
            ))

    _asignar_etiquetas(etiquetas, parcelas)
    return parcelas


def _coordenadas(texto: str) -> geo.Anillo:
    puntos = []
    for trozo in texto.split():
        partes = trozo.split(",")
        if len(partes) >= 2:
            puntos.append((float(partes[0]), float(partes[1])))
    # El anillo KML cierra repitiendo el primer punto; lo dejamos abierto.
    if len(puntos) > 2 and puntos[0] == puntos[-1]:
        puntos.pop()
    return puntos


def _asignar_etiquetas(etiquetas: dict[str, geo.Punto], parcelas: list[ParcelaGeometrica]) -> None:
    """Empareja cada etiqueta con su polígono.

    Primero por contención, que es inequívoca. Las etiquetas que quedan fuera de todo
    polígono (o dentro de varios) se resuelven por cercanía al centroide, y solo si
    hay un polígono libre razonablemente cerca.
    """
    sin_asignar = [p for p in parcelas if p.id is None]
    pendientes: list[tuple[str, geo.Punto]] = []

    for identificador, punto in etiquetas.items():
        contenedores = [p for p in sin_asignar if p.id is None and geo.contiene(p.anillo, punto)]
        if len(contenedores) == 1:
            contenedores[0].id = identificador
        else:
            pendientes.append((identificador, punto))

    for identificador, punto in pendientes:
        libres = [p for p in sin_asignar if p.id is None]
        if not libres:
            break
        cercano = min(libres, key=lambda p: geo.distancia(p.centroide, punto))
        if geo.distancia(cercano.centroide, punto) <= DISTANCIA_MAXIMA_ETIQUETA_M:
            cercano.id = identificador
