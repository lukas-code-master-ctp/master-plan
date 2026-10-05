"""La página del plano: de la hoja del PDF a la imagen de trabajo.

Un plano del CBR es un escaneo (o una foto) metido en un PDF. La imagen se saca tal
como viene guardada, sin rerasterizar: rasterizar de nuevo un JPEG suaviza el trazo
y cambia la resolución. Solo si la página no es una imagen única que la cubra se
renderiza a 200 dpi.

Hay dos sistemas de píxeles:
- los de **página**: la imagen extraída y ya rotada a la lectura que eligió la
  loteadora. Ahí se marcan el rectángulo, las máscaras, las esquinas y las semillas.
- los de **trabajo**: el recorte del dibujo remuestreado a entre 6 y 8 px por mm de
  papel o, si es una foto, la hoja rectificada. Ahí se digitaliza.

Una homografía 3×3 lleva de página a trabajo; con el recorte es una escala y una
traslación, con la foto una perspectiva. Los polígonos vuelven a la página con su
inversa, y como una homografía lleva rectas a rectas, basta mover los vértices.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import pymupdf
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

# Los parámetros del método están en mm de papel (grosor de línea, tamaño del texto,
# huecos del trazo). Por debajo de esta resolución el trazo es demasiado delgado
# para separarlo del papel, y la imagen de trabajo se remuestrea hasta aquí.
PPMM_TRABAJO_MINIMO = 6.0
# Y por encima de esta se reduce: un A0 a 300 dpi (11,8 px/mm, ~140 Mpx) pasaría de
# 4 GiB, y el set de regresión no mejora con más resolución (ver
# docs/specs/2026-10-01-crea-tu-kmz-regresion.md).
PPMM_TRABAJO_MAXIMO = 8.0

# Sin una imagen embebida que cubra la página, se renderiza a esta resolución.
DPI_RENDER = 200

# Una imagen cuenta como "la página" si cubre al menos esta fracción de la hoja.
COBERTURA_MINIMA = 0.8

MM_POR_PUNTO = 25.4 / 72

# Distancia bajo la cual una coordenada rectificada se considera entera.
TOLERANCIA_PX = 1e-6


@dataclass
class Pagina:
    imagen: np.ndarray      # RGB uint8, sin rotar
    ppmm: float             # píxeles por mm de papel, según el tamaño de la hoja del PDF
    fuente: str             # "embebida" o "render"
    paginas: int            # cuántas páginas tiene el PDF


def extraer(pdf: Path, numero: int) -> Pagina:
    """La imagen de la página `numero` (desde 1)."""
    # Los errores de pymupdf no son los de Python (FileNotFoundError, ValueError):
    # se traducen para que la consola muestre el mensaje y no una traza.
    if not Path(pdf).is_file():
        raise FileNotFoundError(f"no está el PDF del plano: {Path(pdf).name}")
    try:
        documento = pymupdf.open(pdf)
    except RuntimeError as e:
        raise ValueError(f"no se pudo abrir {Path(pdf).name} como PDF") from e
    with documento:
        if not 1 <= numero <= documento.page_count:
            raise ValueError(f"el PDF tiene {documento.page_count} páginas; no existe la {numero}")
        hoja = documento[numero - 1]
        embebida = _embebida(documento, hoja)
        if embebida is not None:
            imagen, ppmm = embebida
            return Pagina(imagen, ppmm, "embebida", documento.page_count)
        pixmap = hoja.get_pixmap(dpi=DPI_RENDER, colorspace=pymupdf.csRGB, alpha=False)
        imagen = np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.height, pixmap.width, 3).copy()
        return Pagina(imagen, DPI_RENDER / 25.4, "render", documento.page_count)


def _embebida(documento, hoja) -> tuple[np.ndarray, float] | None:
    imagenes = hoja.get_images(full=True)
    if not imagenes:
        return None
    xref, _, ancho, alto = max(imagenes, key=lambda im: im[2] * im[3])[:4]
    rectangulos = hoja.get_image_rects(xref)
    if len(rectangulos) != 1:
        return None
    caja = rectangulos[0] & hoja.rect
    if caja.is_empty or caja.width * caja.height < COBERTURA_MINIMA * hoja.rect.width * hoja.rect.height:
        return None
    datos = documento.extract_image(xref)
    if datos.get("ext") in ("jpeg", "jpg", "png"):
        imagen = np.asarray(Image.open(io.BytesIO(datos["image"])).convert("RGB")).copy()
    else:
        # JPX, JBIG2, CCITT: que MuPDF lo decodifique y lo pase a RGB.
        pixmap = pymupdf.Pixmap(documento, xref)
        if pixmap.alpha:
            pixmap = pymupdf.Pixmap(pixmap, 0)
        if pixmap.n != 3:
            pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
        imagen = np.frombuffer(pixmap.samples, np.uint8).reshape(pixmap.height, pixmap.width, 3).copy()
    alto_px, ancho_px = imagen.shape[:2]
    # La imagen puede ir girada dentro de la hoja; el producto de los lados no cambia.
    ppmm = float(np.sqrt(ancho_px * alto_px / ((caja.width * MM_POR_PUNTO) * (caja.height * MM_POR_PUNTO))))
    return imagen, ppmm


# ---------------------------------------------------------------------------- rotación
def rotar(imagen: np.ndarray, grados: int) -> np.ndarray:
    """Gira la imagen `grados` en sentido horario (0, 90, 180 o 270)."""
    return np.ascontiguousarray(np.rot90(imagen, k=-_cuartos(grados)))


def rotar_punto(x: float, y: float, grados: int, ancho: int, alto: int) -> tuple[float, float]:
    """Dónde queda el píxel (x, y) de una imagen ancho×alto sin rotar al girarla
    `grados` en sentido horario. Coordenadas con el centro del píxel en el entero."""
    k = _cuartos(grados)
    if k == 0:
        return x, y
    if k == 1:
        return alto - 1 - y, x
    if k == 2:
        return ancho - 1 - x, alto - 1 - y
    return y, ancho - 1 - x


def _cuartos(grados: int) -> int:
    if grados % 90:
        raise ValueError(f"la rotación es 0, 90, 180 o 270 grados, no {grados}")
    return (grados // 90) % 4


# ---------------------------------------------------------------------------- encuadre
@dataclass
class Encuadre:
    imagen: np.ndarray        # imagen de trabajo, RGB
    ppmm: float               # px de trabajo por mm de papel
    homografia: np.ndarray    # 3×3, píxel de página → píxel de trabajo
    modo: str                 # "recorte" o "perspectiva"

    def a_trabajo(self, puntos) -> np.ndarray:
        return _aplicar(self.homografia, puntos)

    def a_pagina(self, puntos) -> np.ndarray:
        return _aplicar(np.linalg.inv(self.homografia), puntos)


def _aplicar(h: np.ndarray, puntos) -> np.ndarray:
    p = np.asarray(puntos, float).reshape(-1, 2)
    q = np.c_[p, np.ones(len(p))] @ h.T
    return q[:, :2] / q[:, 2:3]


def color_papel(imagen: np.ndarray, rectangulo) -> np.ndarray:
    """Color mediano dentro del rectángulo del dibujo: casi todo es papel."""
    x0, y0, x1, y1 = _rect_entero(rectangulo, imagen.shape)
    muestra = imagen[y0:y1:7, x0:x1:7].reshape(-1, 3)
    return np.median(muestra, axis=0).astype(np.uint8)


def tapar(imagen: np.ndarray, mascaras, papel: np.ndarray) -> np.ndarray:
    """Pinta del color del papel los rectángulos que no son dibujo (cuadros, cajetín,
    timbres, croquis). Devuelve una copia."""
    salida = imagen.copy()
    for rect in mascaras:
        x0, y0, x1, y1 = _rect_entero(rect, imagen.shape)
        salida[y0:y1, x0:x1] = papel
    return salida


def encuadrar(imagen: np.ndarray, ppmm_pagina: float, rectangulo, esquinas=None,
              marco_mm=None, papel=None) -> Encuadre:
    """La imagen de trabajo: el rectángulo del dibujo a entre PPMM_TRABAJO_MINIMO y
    PPMM_TRABAJO_MAXIMO px/mm.

    Con `esquinas` (las 4 del marco impreso, en orden sup-izq, sup-der, inf-der,
    inf-izq) se corrige la perspectiva de una foto: el marco pasa a ser un rectángulo
    de `marco_mm` (ancho, alto) de papel. Sin `marco_mm`, el rectángulo toma el largo
    medio de los lados opuestos y se supone la escala de la hoja del PDF.
    """
    if esquinas is not None:
        return _rectificar(imagen, ppmm_pagina, rectangulo, esquinas, marco_mm, papel)
    x0, y0, x1, y1 = _rect_entero(rectangulo, imagen.shape)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"el rectángulo del dibujo está vacío: {list(rectangulo)}")
    s = _escala(ppmm_pagina)
    trabajo = imagen[y0:y1, x0:x1]
    if s != 1.0:
        trabajo = cv2.resize(trabajo, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC if s > 1 else cv2.INTER_AREA)
    # Centro de píxel en el entero: u = (x - x0 + 0,5)·s - 0,5.
    h = np.array([[s, 0, s * (0.5 - x0) - 0.5], [0, s, s * (0.5 - y0) - 0.5], [0, 0, 1]], float)
    return Encuadre(np.ascontiguousarray(trabajo), ppmm_pagina * s, h, "recorte")


def _escala(ppmm_pagina: float) -> float:
    """Factor página → trabajo: lleva la resolución a [PPMM_TRABAJO_MINIMO, PPMM_TRABAJO_MAXIMO]."""
    return min(max(ppmm_pagina, PPMM_TRABAJO_MINIMO), PPMM_TRABAJO_MAXIMO) / ppmm_pagina


def _rectificar(imagen, ppmm_pagina, rectangulo, esquinas, marco_mm, papel) -> Encuadre:
    origen = np.float32(esquinas)
    if origen.shape != (4, 2):
        raise ValueError("las esquinas del marco son 4 puntos [x, y]")
    # Las 4 esquinas, en su orden, deben dar un cuadrilátero convexo y no
    # degenerado: si no, la homografía no es la de una foto de la hoja.
    a = np.roll(origen, -1, 0) - origen                  # lado i: de la esquina i a la i+1
    b = np.roll(a, -1, 0)
    giros = a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0]
    if not (all(g > 0 for g in giros) or all(g < 0 for g in giros)):
        raise ValueError("las esquinas del marco no forman un cuadrilátero: van en orden sup-izq, sup-der,"
                         " inf-der, inf-izq")
    lados = [float(np.hypot(*(origen[i] - origen[(i + 1) % 4]))) for i in range(4)]
    if marco_mm is not None:
        ancho_mm, alto_mm = (float(v) for v in marco_mm)
        ppmm = PPMM_TRABAJO_MINIMO
    else:
        ancho_mm = (lados[0] + lados[2]) / 2 / ppmm_pagina
        alto_mm = (lados[1] + lados[3]) / 2 / ppmm_pagina
        ppmm = ppmm_pagina * _escala(ppmm_pagina)
    destino = np.float32([[0, 0], [ancho_mm * ppmm, 0], [ancho_mm * ppmm, alto_mm * ppmm], [0, alto_mm * ppmm]])
    h = cv2.getPerspectiveTransform(origen, destino).astype(float)
    x0, y0, x1, y1 = rectangulo
    c4 = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
    # El divisor de la homografía cambia de signo en el horizonte de la foto.
    w = np.c_[np.asarray(c4, float), np.ones(4)] @ h[2]
    if (w * (np.r_[origen.mean(0), 1.0] @ h[2]) <= 0).any():
        # El rectángulo cruza el horizonte de la foto: rectificado sería infinito.
        raise ValueError("el rectángulo del dibujo se sale de la hoja fotografiada: ajústalo al marco")
    c4 = _aplicar(h, c4)
    # Una esquina que cae en un entero llega con ruido de redondeo (±1e-13) que cambia
    # según la versión de OpenCV; sin pegarla al entero, floor/ceil suman un píxel.
    cerca = np.round(c4)
    c4 = np.where(np.abs(c4 - cerca) < TOLERANCIA_PX, cerca, c4)
    rx0, ry0 = np.floor(c4.min(0)).astype(int)
    rx1, ry1 = np.ceil(c4.max(0)).astype(int)
    if (rx1 - rx0) * (ry1 - ry0) > 4 * ancho_mm * alto_mm * ppmm * ppmm:
        # Cerca del horizonte la rectificación estira sin límite (y sin memoria).
        raise ValueError("el rectángulo del dibujo se sale de la hoja fotografiada: ajústalo al marco")
    h =np.array([[1, 0, -rx0], [0, 1, -ry0], [0, 0, 1]], float) @ h
    fondo = [int(v) for v in (papel if papel is not None else color_papel(imagen, rectangulo))]
    trabajo = cv2.warpPerspective(imagen, h, (int(rx1 - rx0), int(ry1 - ry0)), flags=cv2.INTER_CUBIC,
                                  borderMode=cv2.BORDER_CONSTANT, borderValue=fondo)
    return Encuadre(trabajo, ppmm, h, "perspectiva")


def _rect_entero(rect, forma) -> tuple[int, int, int, int]:
    alto, ancho = forma[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in rect)
    return (min(max(x0, 0), ancho), min(max(y0, 0), alto),
            min(max(x1, 0), ancho), min(max(y1, 0), alto))
