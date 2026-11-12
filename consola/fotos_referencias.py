"""Las fotos comunes de las referencias: el portón del acceso, la sala de ventas.

En el visor, tocar el rótulo de una referencia con fotos abre una galería. La
loteadora las sube desde la consola, una tanda por referencia, y quedan en las
fuentes del loteo (`fotos-de-referencias/<referencia>/NN.jpg`), que es de donde las
toma la construcción. Llegaron por Parque Algarrobo (noviembre de 2026): la
gente pregunta cómo es la entrada, y desde el dron no se ve el portón.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from pipeline import config
from pipeline.referencias import leer_entrada

# Lo que se guarda en las fuentes: bastante más que lo que va al sitio (2048 px,
# ver `pipeline.construir`), por si mañana el sitio pide más, y mucho menos que
# los 12 a 48 MP que trae una foto de celular.
LADO_GUARDADO = 3000
CALIDAD = 88
# Una galería de veinte fotos de un portón ya no se mira entera.
MAXIMO_POR_REFERENCIA = 20
# Una foto de celular pesa menos de 15 MB; más es un video o un RAW.
MEGAS_POR_FOTO = 40

_CARPETA = re.compile(r"^[a-z0-9-]+$")
_ARCHIVO = re.compile(r"^\d{2,3}\.jpg$")


def nombres_de_referencias(referencias) -> list[str]:
    """Los nombres como los rotula el visor: "Acceso (-33.35, -71.62)" es "Acceso"."""
    nombres = []
    for entrada in referencias or ():
        nombre = str(entrada.get("nombre") if isinstance(entrada, dict)
                     else leer_entrada(entrada).get("nombre") or "").strip()
        if nombre and nombre not in nombres:
            nombres.append(nombre)
    return nombres


def _carpeta(fuentes: Path) -> Path:
    return Path(fuentes) / config.CARPETA_FOTOS_REFERENCIAS


def listar(fuentes: Path, referencias) -> list[dict]:
    """Cada referencia del loteo con sus fotos, para pintarlas en la consola."""
    return [{"referencia": nombre, "carpeta": config.carpeta_de_fotos(nombre),
             "fotos": [p.name for p in config.fotos_de_referencia(_carpeta(fuentes), nombre)]}
            for nombre in nombres_de_referencias(referencias)]


def agregar(fuentes: Path, referencias, nombre: str, archivos: list[BinaryIO]) -> list[str]:
    """Guarda las fotos al final de la galería de `nombre`, como JPEG derechos y
    achicados. Revisa todas antes de escribir: una que no es foto no deja la tanda
    a medias."""
    if nombre not in nombres_de_referencias(referencias):
        raise ValueError(f"no hay una referencia llamada «{nombre}»: agrégala y guarda primero")
    if not archivos:
        raise ValueError("no llegó ninguna foto")
    destino = _carpeta(fuentes) / config.carpeta_de_fotos(nombre)
    ya = config.fotos_de_referencia(_carpeta(fuentes), nombre)
    if len(ya) + len(archivos) > MAXIMO_POR_REFERENCIA:
        raise ValueError(f"caben {MAXIMO_POR_REFERENCIA} fotos por referencia y "
                         f"{nombre} ya tiene {len(ya)}")
    imagenes = []
    for archivo in archivos:
        try:
            with Image.open(archivo) as original:
                imagen = ImageOps.exif_transpose(original).convert("RGB")
        except (UnidentifiedImageError, OSError) as error:
            raise ValueError("una de las fotos no es una imagen (JPEG, PNG o WebP)") from error
        imagen.thumbnail((LADO_GUARDADO, LADO_GUARDADO), Image.Resampling.LANCZOS)
        imagenes.append(imagen)
    destino.mkdir(parents=True, exist_ok=True)
    # Numeradas a continuación de la última: el orden de la galería es el de subida,
    # y quitar una del medio no reordena las demás.
    siguiente = max((int(p.stem) for p in ya if p.stem.isdigit()), default=0) + 1
    nuevas = []
    for numero, imagen in enumerate(imagenes, start=siguiente):
        nombre_archivo = f"{numero:02d}.jpg"
        imagen.save(destino / nombre_archivo, "JPEG", quality=CALIDAD, optimize=True)
        nuevas.append(nombre_archivo)
    return nuevas


def ruta(fuentes: Path, carpeta: str, archivo: str) -> Path:
    """La foto pedida por la consola. Los nombres se validan: vienen de la URL."""
    if not _CARPETA.match(carpeta) or not _ARCHIVO.match(archivo):
        raise FileNotFoundError(archivo)
    camino = _carpeta(fuentes) / carpeta / archivo
    if not camino.is_file():
        raise FileNotFoundError(archivo)
    return camino


def quitar(fuentes: Path, carpeta: str, archivo: str) -> None:
    ruta(fuentes, carpeta, archivo).unlink()
