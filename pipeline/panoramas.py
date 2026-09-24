"""Lectura de las panorámicas del dron y resolución de su rumbo.

Cada foto trae en su XMP la posición GPS, la altura y la hora de captura. Lo único
que falta para poder proyectar es hacia dónde apunta la columna x=0 de la imagen, y
eso se resuelve con el sol.

Nota: `drone-dji:GimbalYawDegree` NO sirve para esto. DJI graba el yaw de un
sub-fotograma arbitrario del stitching y el desfase contra el norte real cambia entre
vuelos. Se guarda solo como dato de diagnóstico.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from . import geo
from .proyeccion import Vista
from .solar import DiscoSolar, detectar_disco, posicion_solar, rumbo_desde_sol

Image.MAX_IMAGE_PIXELS = None

ANCHO_ANALISIS = 3600

# El rótulo de altura se redondea a la decena. El GPS reporta la altura con
# decimales (117,3 / 118,7 / 119,1) y las alturas de vuelo son valores redondos.
# Antes se ajustaba a la lista fija (50, 100, 300, 500), que era el plan de vuelo
# del primer proyecto: un vuelo a 118 m caía en 100 y tres tomas distintas
# terminaban compartiendo el mismo id.
PASO_ALTURA_M = 10

# Dos tomas separadas por menos que esto son la misma posición de vuelo: el dron
# despega del mismo punto y deriva unos metros al subir. Entre posiciones distintas
# hay cientos de metros, así que el umbral no es delicado.
DISTANCIA_MISMA_POSICION_M = 60.0


@dataclass
class Panorama:
    ruta: Path
    posicion: int
    lon: float
    lat: float
    altura_relativa: float
    altura_absoluta: float
    momento: datetime
    ancho: int
    alto: int
    gimbal_yaw: float | None

    @property
    def altura_nominal(self) -> int:
        return int(round(self.altura_relativa / PASO_ALTURA_M) * PASO_ALTURA_M)

    @property
    def id(self) -> str:
        return f"p{self.posicion:02d}-{self.altura_nominal}"

    @property
    def etiqueta(self) -> str:
        return f"Posición {self.posicion} · {self.altura_nominal} m"


@dataclass
class RumboResuelto:
    rumbo0: float
    azimut_solar: float
    elevacion_solar: float
    disco: DiscoSolar

    @property
    def error_elevacion(self) -> float:
        """Diferencia entre la elevación calculada del sol y la medida en la imagen.

        Es el control de calidad: si el sol detectado está a la altura que predice la
        astronomía, es el sol. Si no, se detectó otra cosa."""
        return abs(self.disco.elevacion_medida - self.elevacion_solar)


def buscar_panoramas(carpeta: Path) -> list[Panorama]:
    """Recorre la carpeta y devuelve las panorámicas ordenadas.

    La misma foto suele estar dos veces (la carpeta de trabajo y el volcado de la
    tarjeta). Misma hora, mismo GPS y misma altura es la misma toma, y una toma es
    una vista; el nombre del archivo no sirve porque se repite entre posiciones.
    """
    encontradas = []
    tomas: set[tuple] = set()
    for ruta in sorted(carpeta.rglob("*")):
        if ruta.suffix.lower() not in (".jpg", ".jpeg"):
            continue
        if "REFERENCIA" in ruta.stem.upper():
            continue
        panorama = leer_panorama(ruta)
        if not panorama:
            continue
        toma = (panorama.momento, round(panorama.lon, 7), round(panorama.lat, 7),
                round(panorama.altura_relativa, 1))
        if toma in tomas:
            continue
        tomas.add(toma)
        encontradas.append(panorama)
    asignar_posiciones(encontradas)
    encontradas.sort(key=lambda p: (p.posicion, p.altura_nominal))
    return encontradas


def asignar_posiciones(panoramas: list[Panorama]) -> None:
    """Numera las posiciones de vuelo que la carpeta no rotula.

    En el primer proyecto las fotos venían separadas en carpetas `POSICION NN` y de
    ahí salía el número. Un vuelo entregado sin esas carpetas dejaba a todas las
    tomas en la posición 0; como el id de la vista es posición + altura, varias
    vistas quedaban con el mismo id y `construir` las sobreescribía sin avisar.

    Las que ya traen número se respetan. Al resto se le agrupa por cercanía y se
    numera en orden de captura, que es el orden en que voló el piloto.
    """
    sin_numero = [p for p in panoramas if p.posicion == 0]
    if not sin_numero:
        return

    grupos: list[list[Panorama]] = []
    for panorama in sorted(sin_numero, key=lambda p: p.momento):
        cercano = next(
            (g for g in grupos
             if any(geo.distancia((o.lon, o.lat), (panorama.lon, panorama.lat))
                    <= DISTANCIA_MISMA_POSICION_M for o in g)),
            None)
        if cercano is None:
            grupos.append([panorama])
        else:
            cercano.append(panorama)

    numero = max((p.posicion for p in panoramas), default=0)
    for grupo in grupos:
        numero += 1
        for panorama in grupo:
            panorama.posicion = numero


def leer_panorama(ruta: Path) -> Panorama | None:
    """Devuelve None si el archivo no es una panorámica del dron."""
    with Image.open(ruta) as imagen:
        xmp = imagen.info.get("xmp", b"")
        ancho, alto = imagen.size

    if not xmp:
        return None
    texto = xmp.decode("utf-8", "ignore")
    if "equirectangular" not in texto:
        return None

    def campo(clave):
        coincidencia = re.search(re.escape(clave) + r'="([^"]*)"', texto)
        return coincidencia.group(1) if coincidencia else None

    try:
        lon = float(campo("drone-dji:GpsLongitude"))
        lat = float(campo("drone-dji:GpsLatitude"))
        relativa = float(campo("drone-dji:RelativeAltitude"))
        absoluta = float(campo("drone-dji:AbsoluteAltitude"))
        momento = datetime.fromisoformat(campo("xmp:CreateDate"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"{ruta.name}: XMP incompleto ({error})") from error

    gimbal = campo("drone-dji:GimbalYawDegree")

    return Panorama(
        ruta=ruta,
        posicion=_numero_de_posicion(ruta),
        lon=lon,
        lat=lat,
        altura_relativa=relativa,
        altura_absoluta=absoluta,
        momento=momento,
        ancho=ancho,
        alto=alto,
        gimbal_yaw=float(gimbal) if gimbal else None,
    )


def _numero_de_posicion(ruta: Path) -> int:
    for parte in reversed(ruta.parts):
        coincidencia = re.search(r"POSICI[OÓ]N\s*(\d+)", parte, re.IGNORECASE)
        if coincidencia:
            return int(coincidencia.group(1))
    return 0


def resolver_rumbo(panorama: Panorama, ancho_analisis: int = ANCHO_ANALISIS) -> RumboResuelto:
    """Calcula dónde estaba el sol, lo busca en la imagen, y deduce el rumbo."""
    sol = posicion_solar(panorama.momento, panorama.lat, panorama.lon)
    gris = _gris_reducido(panorama.ruta, ancho_analisis)
    disco = detectar_disco(gris, sol.elevacion)
    return RumboResuelto(
        rumbo0=rumbo_desde_sol(sol.azimut, disco.x_normalizado),
        azimut_solar=sol.azimut,
        elevacion_solar=sol.elevacion,
        disco=disco,
    )


def _gris_reducido(ruta: Path, ancho: int) -> np.ndarray:
    with Image.open(ruta) as imagen:
        # draft() decodifica el JPEG ya reducido: mucho más rápido que decodificar
        # 100 megapíxeles para después achicarlos.
        imagen.draft("L", (ancho, ancho // 2))
        return np.asarray(imagen.convert("L").resize((ancho, ancho // 2), Image.BILINEAR))


def a_vista(panorama: Panorama, rumbo: RumboResuelto) -> Vista:
    return Vista(
        id=panorama.id,
        posicion=panorama.posicion,
        lon=panorama.lon,
        lat=panorama.lat,
        altura_relativa=panorama.altura_relativa,
        altura_absoluta=panorama.altura_absoluta,
        rumbo0=round(rumbo.rumbo0, 2),
    )
