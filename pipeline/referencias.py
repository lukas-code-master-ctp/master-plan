"""Puntos de referencia en el horizonte.

Un visitante que mira el loteo desde el aire no sabe hacia dónde queda el pueblo, la
costa o la carretera. Un rótulo "Cauquenes · 12 km" en el horizonte lo ubica. Los
nombres se geocodifican solos (Open-Meteo, sin llave): entre lo que devuelve la
búsqueda se prefiere el pueblo que se llama exactamente así y, entre homónimos, el
más cercano al loteo. Los candidatos quedan en caché. También se aceptan
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
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from . import geo, terreno
from .proyeccion import Vista, proyectar_punto

URL_GEOCODING = "https://geocoding-api.open-meteo.com/v1/search?"
PAIS_POR_DEFECTO = "CL"

# La tierra "efectiva" con refracción atmosférica estándar: el horizonte se ve un
# poco más lejos de lo que la geometría pura dice.
RADIO_TIERRA_EFECTIVO_M = 6371000.0 * 1.17

Geocodificador = Callable[[str, str], list[dict]]

# Para decidir si un cerro tapa el hito. Como en horizonte.perfil: cerca hace falta
# detalle, a decenas de km basta un DEM grueso. (zoom, desde m, hasta m, paso m)
TRAMOS_CRESTA = ((12, 150.0, 15000.0, 30.0), (10, 15000.0, 60000.0, 150.0),
                 (8, 60000.0, 250000.0, 500.0))
REFRACCION = 0.13
# Un pueblo no es un punto en el suelo: sus techos y árboles asoman unos metros.
ALTO_VISIBLE_M = 20.0
# Cuánto tiene que sobresalir el cerro para darlo por tapado: menos es ruido del DEM.
MARGEN_TAPADO_GRADOS = 0.1


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
        candidatos = _candidatos(guardadas.get(clave))
        if candidatos is None:
            try:
                encontrados = geocodificar(nombre, pais)
            except OSError as error:
                encontrados = None
                print(f"  aviso: el geocodificador no respondió para '{nombre}' ({error})")
            if encontrados:
                candidatos = [{"lon": float(c["longitude"]), "lat": float(c["latitude"]),
                               "cota": float(c["elevation"]) if c.get("elevation") is not None else None,
                               "nombre": c.get("name"), "tipo": c.get("feature_code")}
                              for c in encontrados]
                guardadas[clave] = {"candidatos": candidatos}
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(guardadas, ensure_ascii=False, indent=1), encoding="utf-8")
            elif clave in guardadas and "lon" in guardadas[clave]:
                # Sin red, mejor el lugar de antes que ninguno.
                candidatos = [guardadas[clave]]
            if not candidatos:
                print(f"  aviso: no encontré '{nombre}' en el geocodificador; se omite")
                continue
        # Se elige en cada loteo y no al guardar: el caché lo comparten todos, y el
        # homónimo más cercano a un loteo puede quedar en la otra punta del país para
        # el siguiente (un "Chillán" mal elegido aparecía al poniente de Quillón).
        elegido = _elegir(nombre, candidatos, cerca_de)
        # El tiempo no viene del caché: ese lo pone cada loteo.
        referencias.append(Referencia(nombre=nombre, lon=elegido["lon"], lat=elegido["lat"],
                                      cota=elegido.get("cota"), tiempo=tiempo))
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


def cresta(desde: geo.Punto, altura: float, hito: Referencia, cache: Path,
           descarga: terreno.Descarga = None) -> Referencia | None:
    """El punto del relieve que tapa el hito visto desde `desde` a `altura` metros
    (las dos cotas en el datum del DEM), o None si el hito se ve.

    Desde un punto bajo, Chillán o Concepción quedan detrás de los cerros y su
    alfiler caía sobre la ladera, como si el pueblo estuviera en el cerro. Sabiendo
    qué cerro lo tapa, el visor pone el rótulo sobre su cumbre y dice que está detrás.
    """
    if hito.cota is None:
        return None
    total = geo.distancia(desde, (hito.lon, hito.lat))
    hasta = total - max(300.0, 0.02 * total)   # el terreno del propio pueblo no lo tapa
    if hasta <= 0:
        return None

    def angulo(cota, distancia):
        caida = distancia ** 2 / (2 * 6371000.0) * (1 - REFRACCION)
        return np.degrees(np.arctan2(cota - caida - altura, distancia))

    mejor = None
    for zoom, inicio, fin, paso in TRAMOS_CRESTA:
        distancias = np.arange(inicio, min(fin, hasta), paso)
        if not len(distancias):
            continue
        fraccion = distancias / total
        lons = desde[0] + (hito.lon - desde[0]) * fraccion
        lats = desde[1] + (hito.lat - desde[1]) * fraccion
        modelo = terreno.cargar((min(lons), min(lats), max(lons), max(lats)), cache,
                                margen_m=2 * paso, zoom=zoom, descarga=descarga)
        cotas = modelo.cotas_en(lons, lats)
        angulos = angulo(cotas, distancias)
        i = int(angulos.argmax())
        if mejor is None or angulos[i] > mejor[0]:
            mejor = (float(angulos[i]), float(lons[i]), float(lats[i]), float(cotas[i]))
    if mejor is None or mejor[0] <= angulo(hito.cota + ALTO_VISIBLE_M, total) + MARGEN_TAPADO_GRADOS:
        return None
    return Referencia(nombre=hito.nombre, lon=mejor[1], lat=mejor[2], cota=mejor[3])


def _elegir(nombre: str, candidatos: list[dict], cerca_de: geo.Punto) -> dict:
    """El lugar que la loteadora quiso decir. La búsqueda trae también lo que solo
    empieza parecido ("Chillán Viejo", "Nevados de Chillán") y lugares que no son
    pueblos (un río, un cerro, un fundo con el mismo nombre): primero los que se
    llaman exactamente así, de esos los que son pueblos o ciudades, y entre los que
    quedan, el más cercano al loteo (hay dos Chanco en el Maule)."""
    def preferencia(c):
        mismo_nombre = _normalizar(c.get("nombre") or nombre) == _normalizar(nombre)
        poblado = str(c.get("tipo") or "PPL").startswith("PPL")
        return (not mismo_nombre, not poblado, geo.distancia((c["lon"], c["lat"]), cerca_de))
    return min(candidatos, key=preferencia)


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


def _candidatos(guardada: dict | None) -> list[dict] | None:
    """Los homónimos guardados, o None si hay que preguntar. Las entradas antiguas
    guardaban un solo lugar, ya elegido para otro loteo: esas se vuelven a preguntar."""
    if guardada and guardada.get("candidatos"):
        return guardada["candidatos"]
    return None


def _geocodificar(nombre: str, pais: str) -> list[dict]:
    consulta = urllib.parse.urlencode({"name": nombre, "count": 10, "language": "es", "countryCode": pais})
    with urllib.request.urlopen(URL_GEOCODING + consulta, timeout=30) as respuesta:
        return json.load(respuesta).get("results", []) or []
