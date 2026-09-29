"""La portada de un loteo: el recorte de su mejor vista donde está el loteo.

La panorámica entera no sirve de portada: es una esfera aplanada, con medio cielo
arriba y el pie del dron abajo, y el loteo ocupa una franja cualquiera según hacia
dónde miraba la cámara. Acá se recorta la panorámica de la vista inicial —la que
el pipeline eligió por encuadrar mejor el loteo— alrededor de sus parcelas, y se
dibujan los contornos en blanco, que es como se ven en el visor.

Se genera la primera vez que se pide y se guarda junto a la salida; se rehace
solo si la construcción es más nueva que la portada.
"""
from __future__ import annotations

import json
import math
import os
import threading
from pathlib import Path

from PIL import Image, ImageDraw

from pipeline import config

ANCHO_PORTADA = 1280
PROPORCION = 16 / 9
# Cuánto margen se deja alrededor del loteo, en grados de la panorámica.
MARGEN_GRADOS = 8.0
# Ni tan cerca que se pierda el contexto, ni tan lejos que el loteo sea una
# manchita: el ancho del recorte queda entre estos dos.
ANCHO_MINIMO_GRADOS = 70.0
ANCHO_MAXIMO_GRADOS = 200.0
CONTORNO = (255, 255, 255, 210)
NOMBRE = "portada.jpg"


def portada(salida: config.Salida) -> Path | None:
    """La portada del loteo, generándola si hace falta. None si no está construido."""
    vistas = salida.datos / "vistas.json"
    if not vistas.is_file():
        return None
    destino = salida.base / NOMBRE
    if destino.is_file() and destino.stat().st_mtime >= vistas.stat().st_mtime:
        return destino
    # Se escribe aparte y se cambia de nombre al final: la lista y el detalle la
    # piden a la vez, y la segunda petición no puede servir un JPEG a medio escribir.
    temporal = destino.with_name(f".{NOMBRE}.{os.getpid()}-{threading.get_ident()}")
    try:
        imagen = _dibujar(salida, json.loads(vistas.read_text(encoding="utf-8")))
        imagen.save(temporal, "JPEG", quality=82, optimize=True, progressive=True)
        os.replace(temporal, destino)
    except (FileNotFoundError, KeyError, ValueError, OSError):
        # Una construcción a medias o sin imágenes (`--sin-imagenes`) no tiene
        # de dónde sacar la portada. No es un error: la lista muestra un hueco.
        temporal.unlink(missing_ok=True)
        return None
    return destino


def _dibujar(salida: config.Salida, vistas: dict) -> Image.Image:
    inicial = vistas.get("inicial") or vistas["vistas"][0]["id"]
    vista = next(v for v in vistas["vistas"] if v["id"] == inicial)
    parcelas = json.loads((salida.vistas / f"{inicial}.json").read_text(encoding="utf-8"))["parcelas"]
    with Image.open(salida.panoramas / inicial / "previa.jpg") as original:
        panoramica = original.convert("RGB")

    ancho, alto = panoramica.size
    rumbo0 = float(vista["rumbo0"])
    puntos = [p for parcela in parcelas for p in parcela["anillo"]]
    if not puntos:
        raise ValueError("la vista inicial no tiene parcelas")

    # Se gira la panorámica para que el centro del loteo quede al medio: así un
    # loteo que cruza el borde de la imagen no queda partido en dos.
    centro_az = _azimut_medio([p[0] for p in puntos])
    girada = _girar(panoramica, (centro_az - rumbo0 - 180.0) % 360.0 / 360.0)
    rumbo_girado = centro_az - 180.0

    def a_pixel(az: float, el: float) -> tuple[float, float]:
        return (((az - rumbo_girado) % 360.0) / 360.0 * ancho, (90.0 - el) / 180.0 * alto)

    xs = [a_pixel(az, el)[0] for az, el in puntos]
    ys = [a_pixel(az, el)[1] for az, el in puntos]
    grados = (max(xs) - min(xs)) / ancho * 360.0 + 2 * MARGEN_GRADOS
    grados = min(max(grados, ANCHO_MINIMO_GRADOS), ANCHO_MAXIMO_GRADOS)
    caja_ancho = grados / 360.0 * ancho
    caja_alto = min(caja_ancho / PROPORCION, alto)
    medio_x = (max(xs) + min(xs)) / 2
    medio_y = (max(ys) + min(ys)) / 2
    # El centro del recorte es el del loteo, pero sin salirse de la panorámica:
    # fuera de ella el recorte se rellena con negro.
    izquierda = min(max(medio_x - caja_ancho / 2, 0.0), ancho - caja_ancho)
    arriba = min(max(medio_y - caja_alto / 2, 0.0), alto - caja_alto)

    capa = Image.new("RGBA", girada.size, (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(capa)
    grosor = max(1, round(ancho / 1024))
    for parcela in parcelas:
        anillo = [a_pixel(az, el) for az, el in parcela["anillo"]]
        for inicio, fin in zip(anillo, anillo[1:] + anillo[:1]):
            if abs(inicio[0] - fin[0]) > ancho / 2:
                continue
            dibujo.line([inicio, fin], fill=CONTORNO, width=grosor)
    compuesta = Image.alpha_composite(girada.convert("RGBA"), capa).convert("RGB")

    recorte = compuesta.crop((round(izquierda), round(arriba),
                              round(izquierda + caja_ancho), round(arriba + caja_alto)))
    alto_final = round(ANCHO_PORTADA / PROPORCION)
    return recorte.resize((ANCHO_PORTADA, alto_final), Image.LANCZOS)


def _azimut_medio(azimuts: list[float]) -> float:
    """El promedio de ángulos, que no es el promedio de números: 350° y 10° dan 0°."""
    x = sum(math.cos(math.radians(a)) for a in azimuts)
    y = sum(math.sin(math.radians(a)) for a in azimuts)
    return math.degrees(math.atan2(y, x)) % 360.0


def _girar(imagen: Image.Image, fraccion: float) -> Image.Image:
    """Corre la panorámica hacia la izquierda en esa fracción de su ancho."""
    ancho, alto = imagen.size
    corte = round(fraccion * ancho) % ancho
    girada = Image.new(imagen.mode, (ancho, alto))
    girada.paste(imagen.crop((corte, 0, ancho, alto)), (0, 0))
    girada.paste(imagen.crop((0, 0, corte, alto)), (ancho - corte, 0))
    return girada
