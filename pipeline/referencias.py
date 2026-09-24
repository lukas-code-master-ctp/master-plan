"""Puntos de referencia en el horizonte.

Un visitante que mira el loteo desde el aire no sabe hacia dónde queda el pueblo, la
costa o la carretera. Un rótulo "Cauquenes · 12 km" en el horizonte lo ubica. Los
nombres se geocodifican una vez (Open-Meteo, sin llave) eligiendo, entre los
homónimos, el más cercano al loteo; el resultado queda en caché. También se aceptan
coordenadas explícitas.
"""
from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from . import geo
from .proyeccion import Vista, proyectar_punto

URL_GEOCODING = "https://geocoding-api.open-meteo.com/v1/search?"
PAIS_POR_DEFECTO = "CL"

# La tierra "efectiva" con refracción atmosférica estándar: el horizonte se ve un
# poco más lejos de lo que la geometría pura dice.
RADIO_TIERRA_EFECTIVO_M = 6371000.0 * 1.17

Geocodificador = Callable[[str, str], list[dict]]


@dataclass(frozen=True)
class Referencia:
    nombre: str
    lon: float
    lat: float
    cota: float | None = None   # metros sobre el nivel del mar, si se sabe


def resolver(entradas: list, cerca_de: geo.Punto, cache: Path, pais: str = PAIS_POR_DEFECTO,
             geocodificar: Geocodificador | None = None) -> list[Referencia]:
    """Cada entrada es un nombre ("Cauquenes") o un dict con nombre, lon, lat [, cota]."""
    geocodificar = geocodificar or _geocodificar
    cache = Path(cache)
    guardadas: dict = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}

    referencias: list[Referencia] = []
    for entrada in entradas:
        if isinstance(entrada, dict):
            referencias.append(Referencia(nombre=str(entrada["nombre"]), lon=float(entrada["lon"]),
                                          lat=float(entrada["lat"]),
                                          cota=float(entrada["cota"]) if entrada.get("cota") is not None else None))
            continue
        nombre = str(entrada).strip()
        clave = f"{pais}|{nombre.lower()}"
        if clave not in guardadas:
            candidatos = geocodificar(nombre, pais)
            if not candidatos:
                print(f"  aviso: no encontré '{nombre}' en el geocodificador; se omite")
                continue
            elegido = min(candidatos, key=lambda c: geo.distancia((c["longitude"], c["latitude"]), cerca_de))
            guardadas[clave] = asdict(Referencia(
                nombre=nombre, lon=float(elegido["longitude"]), lat=float(elegido["latitude"]),
                cota=float(elegido["elevation"]) if elegido.get("elevation") is not None else None))
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(guardadas, ensure_ascii=False, indent=1), encoding="utf-8")
        referencias.append(Referencia(**guardadas[clave]))
    return referencias


def proyectar(vista: Vista, referencia: Referencia, cota_datum_dron: float) -> dict:
    """Dónde cae la referencia en la panorámica: azimut, elevación y distancia.

    `cota_datum_dron` es la cota del lugar expresada en el datum del dron (ver
    terreno.modelo_para_vista). A decenas de kilómetros la curvatura de la tierra ya
    baja el punto unas décimas de grado, así que se descuenta.
    """
    azimut, elevacion, distancia = proyectar_punto(vista, (referencia.lon, referencia.lat), cota_datum_dron)
    elevacion -= math.degrees(distancia / (2.0 * RADIO_TIERRA_EFECTIVO_M))
    return {
        "nombre": referencia.nombre,
        "az": round(azimut, 2),
        "el": round(elevacion, 2),
        "distancia_km": round(distancia / 1000.0, 1),
    }


def _geocodificar(nombre: str, pais: str) -> list[dict]:
    consulta = urllib.parse.urlencode({"name": nombre, "count": 5, "language": "es", "countryCode": pais})
    with urllib.request.urlopen(URL_GEOCODING + consulta, timeout=30) as respuesta:
        return json.load(respuesta).get("results", []) or []
