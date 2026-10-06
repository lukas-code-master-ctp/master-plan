"""La unión de hojas: varias páginas del PDF puestas en un solo lienzo.

Hay planos que el CBR entrega partidos en varias láminas que se traslapan. La
loteadora pone las hojas en un lienzo, cada una recortada a su dibujo, y la unión
pasa a ser una página más (la "página 0"): todo lo demás de entradas (rectángulo,
máscaras, semillas, anclas) se marca en sus px como en cualquier página. Ver
docs/specs/2026-10-06-kmz-unir-hojas.md.

Convenciones de píxeles (las de `pagina`): el **centro** del píxel está en el
entero, y un rectángulo [x0, y0, x1, y1] abarca los píxeles x0..x1−1 e y0..y1−1
(como `imagen[y0:y1, x0:x1]`).

Geometría. Para cada hoja, con `p` en px de la hoja **ya girada** (su `rotacion`):

    p_unión = R(angulo) · k · (p − c) + (x, y) − origen

- `c = ((ancho − 1) / 2, (alto − 1) / 2)`: el centro de la hoja girada, con ancho
  y alto de la hoja girada.
- `R(a) = [[cos a, −sin a], [sin a, cos a]]`, `angulo` en grados. Con la y hacia
  abajo, un ángulo positivo gira en sentido horario en pantalla.
- `k = ppmm_union / ppmm_hoja`, con `ppmm_union = min(max(ppmms), PPMM_TRABAJO_MAXIMO)`.
- `(x, y)`: dónde cae `c` en el lienzo de la unión, antes de restar el origen.
- `origen = piso(mínimo)` de las esquinas de todos los recortes transformados (sin
  restar origen). Las esquinas de un recorte son los **centros** de sus píxeles
  extremos: (x0, y0), (x1 − 1, y0), (x1 − 1, y1 − 1), (x0, y1 − 1). Así una sola hoja
  sin giro con x, y = c da una unión idéntica a la hoja.
- `ancho = techo(máximo_x) − origen_x + 1` y lo mismo para `alto`.

Composición: fondo del color del papel; las hojas se pintan en el orden de la lista
(la primera abajo, la última arriba) y cada una solo donde el píxel de la unión, al
volver a la hoja, cae en un píxel de su recorte (vecino más cercano: la máscara no se
suaviza). El color se interpola lineal.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from . import pagina as pg

# Constitución (3 láminas a 5,9 px/mm) da ~120 MP; en RGB eso ya son ~360 MB.
MAX_MEGAPIXELES = 250
MIN_HOJAS = 2
MAX_HOJAS = 12
# La pantalla deja ±5°; el resto es margen para lo que proponga Afinar.
MAX_ANGULO = 10.0
ROTACIONES = (0, 90, 180, 270)


@dataclass
class Hoja:
    n: int                                          # página del PDF, desde 1
    rotacion: int = 0                               # 0, 90, 180 o 270, horario
    angulo: float = 0.0                             # giro fino en grados, horario
    x: float = 0.0                                  # centro de la hoja girada en la unión
    y: float = 0.0
    recorte: tuple[int, int, int, int] | None = None   # px de hoja girada; None = entera

    def a_dic(self) -> dict:
        return {"n": self.n, "rotacion": self.rotacion, "angulo": self.angulo, "x": self.x, "y": self.y,
                "recorte": list(self.recorte) if self.recorte is not None else None}


@dataclass
class Union:
    hojas: list[Hoja]                               # de abajo hacia arriba
    cuadro: dict | None = None                      # {"hoja": n, "rect": [x0, y0, x1, y1]}

    def a_dic(self) -> dict:
        return {"hojas": [h.a_dic() for h in self.hojas], "cuadro": self.cuadro}


# ---------------------------------------------------------------------------- lectura
def leer(dic, paginas: dict[int, tuple[int, int]] | None = None) -> Union:
    """Valida y normaliza `entradas.union`. `paginas` (n → (ancho, alto) sin girar)
    permite revisar que cada hoja exista y que los recortes y el cuadro quepan; sin
    ella solo se revisa la forma. Los errores son ValueError con el mensaje para la
    loteadora."""
    if not isinstance(dic, dict):
        raise ValueError("la unión de hojas no tiene la forma esperada")
    crudas = dic.get("hojas")
    if not isinstance(crudas, list):
        raise ValueError("la unión de hojas no trae la lista de hojas")
    if not MIN_HOJAS <= len(crudas) <= MAX_HOJAS:
        raise ValueError(f"la unión lleva entre {MIN_HOJAS} y {MAX_HOJAS} hojas; trae {len(crudas)}")
    hojas = [_leer_hoja(h, paginas) for h in crudas]
    numeros = [h.n for h in hojas]
    repetidas = sorted({n for n in numeros if numeros.count(n) > 1})
    if repetidas:
        raise ValueError(f"la hoja {repetidas[0]} está dos veces en la unión")
    cuadro = _leer_cuadro(dic.get("cuadro"), hojas, paginas)
    return Union(hojas, cuadro)


def _leer_hoja(h, paginas) -> Hoja:
    if not isinstance(h, dict):
        raise ValueError("una hoja de la unión no tiene la forma esperada")
    n = h.get("n")
    if not _es_entero(n) or n < 1:
        raise ValueError(f"la hoja {n!r} no es una página del PDF")
    if paginas is not None and n not in paginas:
        raise ValueError(f"la hoja {n} no es una página del PDF (tiene {len(paginas)})")
    rotacion = h.get("rotacion", 0)
    if not _es_entero(rotacion) or rotacion not in ROTACIONES:
        raise ValueError(f"la hoja {n}: el giro es de 0, 90, 180 o 270 grados, no {rotacion!r}")
    angulo = _numero(h.get("angulo", 0.0), f"la hoja {n}: el giro fino no es un número")
    if abs(angulo) > MAX_ANGULO:
        raise ValueError(f"la hoja {n}: el giro fino va entre −{MAX_ANGULO:g}° y {MAX_ANGULO:g}°, no {angulo:g}°")
    x = _numero(h.get("x"), f"la hoja {n}: falta su posición en la unión")
    y = _numero(h.get("y"), f"la hoja {n}: falta su posición en la unión")
    recorte = h.get("recorte")
    tamano = _girado(paginas[n], rotacion) if paginas is not None else None
    if recorte is not None:
        recorte = _leer_rect(recorte, tamano, f"la hoja {n}: el recorte")
    return Hoja(int(n), int(rotacion), angulo, x, y, recorte)


def _leer_cuadro(cuadro, hojas, paginas):
    if cuadro is None:
        return None
    if not isinstance(cuadro, dict):
        raise ValueError("el cuadro de superficies de la unión no tiene la forma esperada")
    usadas = {h.n: h for h in hojas}
    n = cuadro.get("hoja")
    if not _es_entero(n) or n not in usadas:
        raise ValueError("el cuadro de superficies tiene que estar en una de las hojas unidas")
    tamano = _girado(paginas[n], usadas[n].rotacion) if paginas is not None else None
    rect = _leer_rect(cuadro.get("rect"), tamano, "el cuadro de superficies")
    return {"hoja": int(n), "rect": list(rect)}


def _leer_rect(rect, tamano, que) -> tuple[int, int, int, int]:
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        raise ValueError(f"{que} no es un rectángulo [x0, y0, x1, y1]")
    x0, y0, x1, y1 = (int(round(_numero(v, f"{que} no es un rectángulo [x0, y0, x1, y1]"))) for v in rect)
    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"{que} está vacío")
    if x0 < 0 or y0 < 0 or (tamano is not None and (x1 > tamano[0] or y1 > tamano[1])):
        raise ValueError(f"{que} se sale de la hoja")
    return x0, y0, x1, y1


def _es_entero(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _numero(v, mensaje) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(mensaje)
    return float(v)


def _girado(tamano, rotacion) -> tuple[int, int]:
    ancho, alto = (int(v) for v in tamano)
    return (alto, ancho) if rotacion % 180 else (ancho, alto)


def huella(union: Union) -> str:
    """Huella de lo que cambia la imagen de la unión (las hojas, en su orden). El
    cuadro no entra: no cambia la imagen y la caché de la página 0 no debe vencerse
    por él (quien lo lea, como el lector, lo agrega a su propia huella)."""
    hojas = [{"n": h.n, "rotacion": h.rotacion, "angulo": float(h.angulo), "x": float(h.x), "y": float(h.y),
              "recorte": list(h.recorte) if h.recorte is not None else None} for h in union.hojas]
    texto = json.dumps(hojas, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(texto.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------- geometría
def transformar_punto(px: float, py: float, ancho: int, alto: int, k: float, angulo: float,
                      x: float, y: float, origen_x: float = 0.0, origen_y: float = 0.0) -> tuple[float, float]:
    """El punto (px, py) de una hoja girada de ancho×alto, en px de la unión. Es la
    fórmula del módulo, sin numpy, para replicarla tal cual en kmz_union.js."""
    a = math.radians(angulo)
    cos, sen = math.cos(a), math.sin(a)
    dx = k * (px - (ancho - 1) / 2)
    dy = k * (py - (alto - 1) / 2)
    return cos * dx - sen * dy + x - origen_x, sen * dx + cos * dy + y - origen_y


def _matriz(ancho, alto, k, angulo, x, y) -> np.ndarray:
    """La matriz 3×3 de `transformar_punto` sin el origen."""
    a = math.radians(angulo)
    cos, sen = math.cos(a), math.sin(a)
    cx, cy = (ancho - 1) / 2, (alto - 1) / 2
    return np.array([[k * cos, -k * sen, x - k * (cos * cx - sen * cy)],
                     [k * sen, k * cos, y - k * (sen * cx + cos * cy)],
                     [0, 0, 1]], float)


def _esquinas(recorte) -> np.ndarray:
    x0, y0, x1, y1 = recorte
    return np.array([[x0, y0], [x1 - 1, y0], [x1 - 1, y1 - 1], [x0, y1 - 1]], float)


def _pegar(v: np.ndarray) -> np.ndarray:
    # El ruido de redondeo (±1e-13) de un giro de 0° no debe sumar un píxel en floor/ceil.
    cerca = np.round(v)
    return np.where(np.abs(v - cerca) < pg.TOLERANCIA_PX, cerca, v)


@dataclass
class HojaGeometria:
    n: int
    ancho: int                    # de la hoja girada, en sus px
    alto: int
    ppmm: float
    k: float
    recorte: tuple[int, int, int, int]
    matriz: np.ndarray            # 3×3, px de hoja girada → px de unión (con el origen)


@dataclass
class Geometria:
    ancho: int
    alto: int
    ppmm: float
    origen: tuple[int, int]       # lo que se resta a (x, y) para que la unión empiece en 0
    hojas: list[HojaGeometria] = field(default_factory=list)

    def hoja(self, n: int) -> HojaGeometria:
        for h in self.hojas:
            if h.n == n:
                return h
        raise KeyError(n)

    def a_union(self, n: int, puntos) -> np.ndarray:
        return pg._aplicar(self.hoja(n).matriz, puntos)

    def a_hoja(self, n: int, puntos) -> np.ndarray:
        return pg._aplicar(np.linalg.inv(self.hoja(n).matriz), puntos)


def geometria(union: Union, tamanos: dict[int, tuple[int, int]], ppmms: dict[int, float]) -> Geometria:
    """La geometría de la unión. `tamanos`: n → (ancho, alto) de la página sin girar;
    `ppmms`: n → px por mm de papel. Falla si la unión pasa de MAX_MEGAPIXELES, antes
    de que nadie reserve memoria para ella."""
    ppmm = min(max(float(ppmms[h.n]) for h in union.hojas), pg.PPMM_TRABAJO_MAXIMO)
    previas = []
    esquinas = []
    for h in union.hojas:
        ancho, alto = _girado(tamanos[h.n], h.rotacion)
        recorte = h.recorte if h.recorte is not None else (0, 0, ancho, alto)
        if recorte[2] > ancho or recorte[3] > alto:
            raise ValueError(f"la hoja {h.n}: el recorte se sale de la hoja")
        k = ppmm / float(ppmms[h.n])
        m = _matriz(ancho, alto, k, h.angulo, h.x, h.y)
        previas.append((h.n, ancho, alto, float(ppmms[h.n]), k, recorte, m))
        esquinas.append(pg._aplicar(m, _esquinas(recorte)))
    todas = _pegar(np.vstack(esquinas))
    ox, oy = (int(v) for v in np.floor(todas.min(0)))
    ancho_u = int(np.ceil(todas[:, 0].max())) - ox + 1
    alto_u = int(np.ceil(todas[:, 1].max())) - oy + 1
    if ancho_u * alto_u > MAX_MEGAPIXELES * 1e6:
        raise ValueError(f"La unión es demasiado grande ({ancho_u * alto_u / 1e6:.0f} MP; el tope es "
                         f"{MAX_MEGAPIXELES}): recorta las hojas a su dibujo")
    menos_origen = np.array([[1, 0, -ox], [0, 1, -oy], [0, 0, 1]], float)
    hojas = [HojaGeometria(n, a, al, p, k, r, menos_origen @ m) for n, a, al, p, k, r, m in previas]
    return Geometria(ancho_u, alto_u, ppmm, (ox, oy), hojas)


# ---------------------------------------------------------------------------- composición
def componer(imagenes: dict[int, np.ndarray], geometria: Geometria, papel=None) -> np.ndarray:
    """La imagen de la unión (RGB uint8). `imagenes`: n → imagen de la hoja ya girada."""
    for h in geometria.hojas:
        if imagenes[h.n].shape[:2] != (h.alto, h.ancho):
            raise ValueError(f"la imagen de la hoja {h.n} no es del tamaño de su geometría")
    if papel is None:
        papel = _mediana([pg.color_papel(imagenes[h.n], h.recorte) for h in geometria.hojas])
    lienzo = _lienzo(geometria, papel)
    for h in geometria.hojas:
        _pintar(lienzo, imagenes[h.n], h)
    return lienzo


def componer_desde_pdf(pdf: Path, union: Union) -> tuple[np.ndarray, float]:
    """La unión compuesta desde las imágenes del PDF (no los JPEG de pantalla), y sus
    px por mm. Se extrae cada hoja dos veces para no tenerlas todas en memoria junto
    al lienzo: la primera para el tamaño, la resolución y el papel; la segunda para
    pintarla."""
    tamanos, ppmms, papeles = {}, {}, []
    for h in union.hojas:
        p = pg.extraer(pdf, h.n)
        alto, ancho = p.imagen.shape[:2]
        tamanos[h.n], ppmms[h.n] = (ancho, alto), p.ppmm
        girada = pg.rotar(p.imagen, h.rotacion)
        del p
        recorte = h.recorte if h.recorte is not None else (0, 0, girada.shape[1], girada.shape[0])
        papeles.append(pg.color_papel(girada, recorte))
        del girada
    geo = geometria(union, tamanos, ppmms)
    lienzo = _lienzo(geo, _mediana(papeles))
    for h, hg in zip(union.hojas, geo.hojas):
        girada = pg.rotar(pg.extraer(pdf, h.n).imagen, h.rotacion)
        _pintar(lienzo, girada, hg)
        del girada
    return lienzo, geo.ppmm


def _mediana(papeles) -> np.ndarray:
    return np.median(np.asarray(papeles, float), axis=0).astype(np.uint8)


def _lienzo(geo: Geometria, papel) -> np.ndarray:
    if geo.ancho * geo.alto > MAX_MEGAPIXELES * 1e6:
        raise ValueError("La unión es demasiado grande: recorta las hojas a su dibujo")
    lienzo = np.empty((geo.alto, geo.ancho, 3), np.uint8)
    lienzo[:] = np.asarray(papel, np.uint8)
    return lienzo


def _pintar(lienzo: np.ndarray, imagen: np.ndarray, h: HojaGeometria) -> None:
    """Pinta la hoja en el lienzo, solo en la caja de su recorte transformado: un
    lienzo entero por hoja sería otra unión completa en memoria."""
    x0, y0, x1, y1 = h.recorte
    trozo = imagen[y0:y1, x0:x1]
    m = h.matriz @ np.array([[1, 0, x0], [0, 1, y0], [0, 0, 1]], float)
    caja = _pegar(pg._aplicar(h.matriz, _esquinas(h.recorte)))
    # Las esquinas son centros de píxel: el vecino más cercano de la máscara llega hasta
    # medio píxel de hoja más allá (k/2 px de unión, algo más con giro). Con k > 2 eso
    # pasa de un píxel y la caja justa dejaba fuera el borde del recorte.
    margen = int(math.ceil(h.k)) + 1
    bx0, by0 = (max(int(v) - margen, 0) for v in np.floor(caja.min(0)))
    bx1 = min(int(np.ceil(caja[:, 0].max())) + 1 + margen, lienzo.shape[1])
    by1 = min(int(np.ceil(caja[:, 1].max())) + 1 + margen, lienzo.shape[0])
    if bx1 <= bx0 or by1 <= by0:
        return
    m = np.array([[1, 0, -bx0], [0, 1, -by0], [0, 0, 1]], float) @ m
    tam = (bx1 - bx0, by1 - by0)
    # Borde replicado: en el filo del recorte la interpolación no mezcla con negro;
    # lo que queda fuera lo descarta la máscara.
    color = cv2.warpAffine(trozo, m[:2], tam, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    unos = np.ones(trozo.shape[:2], np.uint8)
    mascara = cv2.warpAffine(unos, m[:2], tam, flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT,
                             borderValue=0)
    del unos
    # La máscara es 0/1 en uint8: verla como bool no copia otra imagen del tamaño de la caja.
    np.copyto(lienzo[by0:by1, bx0:bx1], color, where=mascara.view(bool)[..., None])
