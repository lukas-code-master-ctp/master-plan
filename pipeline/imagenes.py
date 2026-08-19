"""Generación de los niveles de imagen que consume el visor.

Tres niveles por panorámica en vez de un sistema de mosaicos: una textura por nivel
es mucho más simple y a 8192 px da 22,8 px por grado, de sobra para web.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from .config import CALIDAD_JPEG, NIVELES_IMAGEN

Image.MAX_IMAGE_PIXELS = None


def generar_niveles(origen: Path, destino: Path, forzar: bool = False) -> dict[str, str]:
    """Escribe previa/media/alta y devuelve los nombres de archivo generados."""
    destino.mkdir(parents=True, exist_ok=True)
    salidas = {}
    for nombre, ancho in sorted(NIVELES_IMAGEN.items(), key=lambda par: par[1]):
        archivo = destino / f"{nombre}.jpg"
        if forzar or _hay_que_regenerar(origen, archivo):
            _redimensionar(origen, archivo, ancho)
        salidas[nombre] = archivo.name
    return salidas


def _hay_que_regenerar(origen: Path, destino: Path) -> bool:
    return not destino.exists() or destino.stat().st_mtime < origen.stat().st_mtime


def _redimensionar(origen: Path, destino: Path, ancho: int) -> None:
    alto = ancho // 2
    with Image.open(origen) as imagen:
        # draft() pide al decodificador JPEG que entregue la imagen ya reducida.
        # Ahorra decodificar 100 megapíxeles para después achicarlos.
        imagen.draft("RGB", (ancho, alto))
        reducida = imagen.convert("RGB").resize((ancho, alto), Image.LANCZOS)
    reducida.save(destino, "JPEG", quality=CALIDAD_JPEG, optimize=True, progressive=True)
