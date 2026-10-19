"""Puntos de referencia en el horizonte.

Un visitante que mira el loteo desde el aire no sabe hacia dónde queda el pueblo, la
costa o la carretera. Un rótulo "Cauquenes · 12 km" en el horizonte lo ubica. Los
nombres se geocodifican una vez (Open-Meteo, sin llave) eligiendo, entre los
homónimos, el más cercano al loteo; el resultado queda en caché. También se aceptan
coordenadas explícitas.

Desde la consola llegan como texto, y el texto puede traer dos cosas más: el tiempo
de viaje ("Quillón 10 minutos"), que la loteadora prefiere mostrar en vez de los
kilómetros porque es lo que pregunta un comprador, y las coordenadas copiadas de
Google Maps entre paréntesis ("Ruta 5 (-36.74, -72.33)") para lo que el
geocodificador no conoce: un parque, una playa o el acceso a una carretera.
"""
from __future__ import annotations

import json
import math
import re
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
    tiempo: str | None = None   # "10 min", "1 h 20 min": se rotula en vez de los km


# "10 minutos", "1 hora 20 minutos", "1 h y 20 min", "45 min" al final del texto.
_TIEMPO = re.compile(
    r"\s+(?:(?P<horas>\d+)\s*(?:h|hr|hrs|horas?)\.?(?:\s*(?:y\s*)?(?P<minutos_h>\d+)\s*(?:m|min|mins|minutos?)\.?)?"
    r"|(?P<minutos>\d+)\s*(?:m|min|mins|minutos?)\.?)\s*$",
    re.IGNORECASE)
# "(-36.7465, -72.3378)": latitud y longitud, en el orden en que las copia Google Maps.
_COORDENADAS = re.compile(r"\(\s*(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)\s*\)")


def leer_entrada(texto: str) -> dict:
    """"Ruta 5 (-36.74, -72.33) 20 minutos" → {"nombre", "tiempo", y "lon"/"lat" si vienen}.

    El tiempo se toma solo al final y con su unidad, para que "Ruta 5" siga siendo
    un nombre y no "Ruta" a 5 minutos.
    """
    texto = " ".join(str(texto).split())
    entrada: dict = {}
    coordenadas = _COORDENADAS.search(texto)
    if coordenadas:
        lat, lon = float(coordenadas.group(1)), float(coordenadas.group(2))
        entrada.update(lat=lat, lon=lon)
        texto = (texto[:coordenadas.start()] + " " + texto[coordenadas.end():]).strip()
        texto = " ".join(texto.split())
    tiempo = _TIEMPO.search(texto)
    if tiempo:
        entrada["tiempo"] = formatear_tiempo(
            int(tiempo.group("horas") or 0),
            int(tiempo.group("minutos_h") or tiempo.group("minutos") or 0))
        texto = texto[:tiempo.start()].strip()
    entrada["nombre"] = texto.rstrip(" ,·-:")
    return entrada


def formatear_tiempo(horas: int, minutos: int) -> str:
    """Corto, porque va en un rótulo sobre la foto: "10 min", "1 h", "1 h 20 min"."""
    horas, minutos = horas + minutos // 60, minutos % 60
    if horas and minutos:
        return f"{horas} h {minutos} min"
    return f"{horas} h" if horas else f"{minutos} min"


def resolver(entradas: list, cerca_de: geo.Punto, cache: Path, pais: str = PAIS_POR_DEFECTO,
             geocodificar: Geocodificador | None = None) -> list[Referencia]:
    """Cada entrada es un texto ("Cauquenes", "Quillón 10 min", "Ruta 5 (-36.7, -72.3)")
    o un dict con nombre, lon, lat [, cota, tiempo]. Los nombres que no se encuentran
    se saltan con un aviso; quien llama sabe cuáles faltan comparando nombres."""
    geocodificar = geocodificar or _geocodificar
    cache = Path(cache)
    guardadas: dict = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}

    referencias: list[Referencia] = []
    for entrada in entradas:
        if not isinstance(entrada, dict):
            entrada = leer_entrada(entrada)
        tiempo = str(entrada["tiempo"]).strip() if entrada.get("tiempo") else None
        if entrada.get("lon") is not None and entrada.get("lat") is not None:
            referencias.append(Referencia(nombre=str(entrada["nombre"]), lon=float(entrada["lon"]),
                                          lat=float(entrada["lat"]),
                                          cota=float(entrada["cota"]) if entrada.get("cota") is not None else None,
                                          tiempo=tiempo))
            continue
        nombre = str(entrada["nombre"]).strip()
        if not nombre:
            continue
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
        # El caché guarda el lugar, no el tiempo: ese lo pone cada loteo.
        guardada = {c: v for c, v in guardadas[clave].items() if c != "tiempo"}
        referencias.append(Referencia(**guardada, tiempo=tiempo))
    return referencias


def proyectar(vista: Vista, referencia: Referencia, cota_datum_dron: float) -> dict:
    """Dónde cae la referencia en la panorámica: azimut, elevación y distancia.

    `cota_datum_dron` es la cota del lugar expresada en el datum del dron (ver
    terreno.modelo_para_vista). A decenas de kilómetros la curvatura de la tierra ya
    baja el punto unas décimas de grado, así que se descuenta.
    """
    azimut, elevacion, distancia = proyectar_punto(vista, (referencia.lon, referencia.lat), cota_datum_dron)
    elevacion -= math.degrees(distancia / (2.0 * RADIO_TIERRA_EFECTIVO_M))
    proyectada = {
        "nombre": referencia.nombre,
        "az": round(azimut, 2),
        "el": round(elevacion, 2),
        "distancia_km": round(distancia / 1000.0, 1),
    }
    if referencia.tiempo:
        proyectada["tiempo"] = referencia.tiempo
    return proyectada


def _geocodificar(nombre: str, pais: str) -> list[dict]:
    consulta = urllib.parse.urlencode({"name": nombre, "count": 5, "language": "es", "countryCode": pais})
    with urllib.request.urlopen(URL_GEOCODING + consulta, timeout=30) as respuesta:
        return json.load(respuesta).get("results", []) or []
