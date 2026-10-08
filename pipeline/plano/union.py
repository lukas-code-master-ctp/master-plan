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
- `k = ppmm_union / ppmm_hoja`, con `ppmm_union = min(max(ppmms), PPMM_TRABAJO_MAXIMO)`;
  si difieren menos de `TOLERANCIA_ESCALA` (relativo), `k = 1` exacto.
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
# Resoluciones que difieren menos que esto (relativo) son la misma: k = 1 exacto.
TOLERANCIA_ESCALA = 1e-6


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


def _escala(ppmm_union: float, ppmm_hoja: float) -> float:
    """k de la hoja. Las hojas de un mismo escaneo traen ppmm que difieren en ~1e-8 por
    el redondeo del PDF; con k = 1 + 8e-9 las esquinas de una hoja grande se corren
    más que TOLERANCIA_PX y la unión gana una fila de papel en el borde."""
    k = ppmm_union / ppmm_hoja
    return 1.0 if abs(k - 1.0) < TOLERANCIA_ESCALA else k


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
        k = _escala(ppmm, float(ppmms[h.n]))
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


# ---------------------------------------------------------------------------- afinar
# Afinar trabaja siempre a resolución reducida: 2 px/mm basta para que ORB encuentre el
# calce grueso y 4 px/mm para que ECC lo deje bajo el píxel de unión (≤ 8 px/mm). A
# resolución completa una zona de Constitución serían decenas de MP por hoja.
PPMM_ORB = 2.0
PPMM_ECC = 4.0
MARGEN_TRASLAPE_MM = 40.0
MIN_PUNTOS = 30
MAX_CORRECCION_MM = 60.0
MAX_CORRECCION_GRADOS = 5.0
# Arrastrada a mano en pantalla, una hoja puede quedar a 50–150 mm de su lugar, incluso
# sin tocar ya a la de abajo. Si el primer intento no calza se reintenta una vez con la
# zona por cercanía (lo de cada una a menos del margen de la otra) y el tope más grande;
# no se parte con eso porque una zona mayor da más calces ambiguos y es más lenta.
MARGEN_TRASLAPE_LEJOS_MM = 150.0
MAX_CORRECCION_LEJOS_MM = 160.0
# Menos traslape que esto (un cuadrado de 10 mm) no da puntos para calzar nada.
MIN_TRASLAPE_MM2 = 100.0
UMBRAL_RANSAC_MM = 1.5
PAPEL_GRIS = 255


@dataclass
class _Reducida:
    """Una hoja en gris a una resolución de trabajo, solo su recorte, y la matriz que
    lleva sus px a px de hoja girada a resolución completa."""
    gris: np.ndarray
    a_hoja: np.ndarray


def afinar(imagenes: dict[int, np.ndarray], ppmms: dict[int, float], union: Union,
           tamanos: dict[int, tuple[int, int]] | None = None) -> list[dict]:
    """Calza cada hoja con lo ya puesto debajo, solo en el traslape. Devuelve, en el
    orden de `union.hojas`, el dic de cada hoja con x, y y angulo corregidos más
    `calzada` y `residuo_mm` (distancia cuadrática media entre los puntos que calzan tras
    afinar; None si no se calzó). La de más abajo no se mueve: `calzada` True y sin
    residuo.

    `imagenes`: n → imagen de la hoja ya girada, a **cualquier** resolución (la consola
    pasa sus JPEG reducidos). `ppmms` y `tamanos` (n → (ancho, alto) sin girar) son los
    de la página a resolución completa, porque son los que definen la geometría de la
    unión; sin `tamanos` se toma la imagen como de resolución completa."""
    if tamanos is None:
        tamanos = {h.n: _girado((imagenes[h.n].shape[1], imagenes[h.n].shape[0]), h.rotacion)
                   for h in union.hojas}
    ppmm_u = min(max(float(ppmms[h.n]) for h in union.hojas), pg.PPMM_TRABAJO_MAXIMO)
    hojas = [Hoja(h.n, h.rotacion, h.angulo, h.x, h.y, h.recorte) for h in union.hojas]
    datos = {}
    for h in hojas:
        ancho, alto = _girado(tamanos[h.n], h.rotacion)
        recorte = h.recorte if h.recorte is not None else (0, 0, ancho, alto)
        datos[h.n] = (ancho, alto, _escala(ppmm_u, float(ppmms[h.n])), recorte)
    reducidas: dict[tuple[int, float], _Reducida] = {}

    def reducida(n, r):
        if (n, r) not in reducidas:
            ancho, alto, _, recorte = datos[n]
            reducidas[(n, r)] = _reducir(imagenes[n], ancho, alto, float(ppmms[n]), recorte, r)
        return reducidas[(n, r)]

    def matriz(h):
        ancho, alto, k, _ = datos[h.n]
        return _matriz(ancho, alto, k, h.angulo, h.x, h.y)

    salida = [{**hojas[0].a_dic(), "calzada": True, "residuo_mm": None}]
    for i in range(1, len(hojas)):
        h = hojas[i]
        # Las de debajo van con su posición ya corregida en esta misma pasada.
        calce = _calzar(lambda r: reducida(h.n, r), matriz(h), datos[h.n][3],
                        lambda r: [(reducida(b.n, r), matriz(b), datos[b.n][3]) for b in hojas[:i]],
                        ppmm_u)
        if calce is None:
            salida.append({**h.a_dic(), "calzada": False, "residuo_mm": None})
            continue
        nueva, residuo = calce
        ancho, alto = datos[h.n][:2]
        angulo = math.degrees(math.atan2(nueva[1, 0], nueva[0, 0]))
        cx, cy = pg._aplicar(nueva, [((ancho - 1) / 2, (alto - 1) / 2)])[0]
        if abs(angulo) > MAX_ANGULO:
            salida.append({**h.a_dic(), "calzada": False, "residuo_mm": None})
            continue
        h.angulo, h.x, h.y = float(angulo), float(cx), float(cy)
        salida.append({**h.a_dic(), "calzada": True, "residuo_mm": residuo})
    return salida


def _reducir(imagen, ancho, alto, ppmm, recorte, r) -> _Reducida:
    """El recorte de la hoja en gris a `r` px/mm. La imagen puede venir a otra resolución
    que la página (ancho × alto girada): la escala sale de su tamaño."""
    fx, fy = imagen.shape[1] / ancho, imagen.shape[0] / alto
    x0, y0, x1, y1 = recorte
    # El recorte en px de la imagen, ampliado un píxel para no perder el borde al reducir.
    ix0, iy0 = max(int(math.floor(x0 * fx)) - 1, 0), max(int(math.floor(y0 * fy)) - 1, 0)
    ix1 = min(int(math.ceil(x1 * fx)) + 1, imagen.shape[1])
    iy1 = min(int(math.ceil(y1 * fy)) + 1, imagen.shape[0])
    trozo = imagen[iy0:iy1, ix0:ix1]
    f = r / (ppmm * fx)
    tam = (max(int(round(trozo.shape[1] * f)), 1), max(int(round(trozo.shape[0] * f)), 1))
    sx, sy = tam[0] / trozo.shape[1], tam[1] / trozo.shape[0]
    # Achicar antes de pasar a gris: la hoja completa en gris sería otra imagen enorme.
    chica = cv2.resize(trozo, tam, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)
    if chica.ndim == 3:
        chica = cv2.cvtColor(chica, cv2.COLOR_RGB2GRAY)
    # Centros de píxel en el entero: q de la reducida es (q + ½)/s − ½ del trozo.
    a_trozo = np.array([[1 / sx, 0, 0.5 / sx - 0.5], [0, 1 / sy, 0.5 / sy - 0.5], [0, 0, 1]], float)
    a_imagen = np.array([[1, 0, ix0], [0, 1, iy0], [0, 0, 1]], float) @ a_trozo
    a_hoja = np.array([[1 / fx, 0, 0.5 / fx - 0.5], [0, 1 / fy, 0.5 / fy - 0.5], [0, 0, 1]], float) @ a_imagen
    return _Reducida(np.ascontiguousarray(chica), a_hoja)


def _recorte_en_reducida(red: _Reducida, recorte) -> np.ndarray:
    """La máscara (uint8 0/1) de los px de la reducida que caen dentro del recorte."""
    x0, y0, x1, y1 = recorte
    alto, ancho = red.gris.shape
    q = pg._aplicar(red.a_hoja, np.c_[np.arange(ancho), np.zeros(ancho)])[:, 0]
    p = pg._aplicar(red.a_hoja, np.c_[np.zeros(alto), np.arange(alto)])[:, 1]
    # Mismo criterio que la composición: vale el píxel de hoja más cercano.
    dentro_x = (np.round(q) >= x0) & (np.round(q) <= x1 - 1)
    dentro_y = (np.round(p) >= y0) & (np.round(p) <= y1 - 1)
    return (dentro_y[:, None] & dentro_x[None, :]).astype(np.uint8)


@dataclass
class _Escena:
    """Lo de debajo y la hoja, en gris sobre un lienzo de trabajo a r px/mm."""
    r: float
    a_lienzo: np.ndarray          # px de unión (sin origen) → px del lienzo
    debajo: np.ndarray
    mascara_debajo: np.ndarray
    hoja: np.ndarray
    mascara_hoja: np.ndarray
    zona: np.ndarray              # dentro del traslape agrandado
    traslape: np.ndarray          # o, lejos, la zona: su centro es el que mide los topes


def _escena(red, m_hoja, recorte, debajo, ppmm_u, r, lejos=False) -> _Escena | None:
    """Arma el lienzo alrededor de la hoja (su caja agrandada el margen) con lo de
    debajo compuesto como en `componer`. None si no hay traslape o, `lejos`, si la hoja
    y lo de debajo no quedan a menos del margen."""
    s = r / ppmm_u
    caja = pg._aplicar(m_hoja, _esquinas(recorte)) * s
    margen = (MARGEN_TRASLAPE_LEJOS_MM if lejos else MARGEN_TRASLAPE_MM) * r
    bx, by = np.floor(caja.min(0) - margen)
    a_lienzo = np.array([[s, 0, -bx], [0, s, -by], [0, 0, 1]], float)
    ancho = int(np.ceil(caja[:, 0].max() + margen - bx)) + 1
    alto = int(np.ceil(caja[:, 1].max() + margen - by)) + 1
    tam = (ancho, alto)

    def render(red_, m, rec, borde):
        mm = a_lienzo @ m @ red_.a_hoja
        gris = cv2.warpAffine(red_.gris, mm[:2], tam, flags=cv2.INTER_LINEAR, borderMode=borde,
                              borderValue=PAPEL_GRIS)
        mascara = cv2.warpAffine(_recorte_en_reducida(red_, rec), mm[:2], tam, flags=cv2.INTER_NEAREST,
                                 borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        return gris, mascara

    fondo = np.full((alto, ancho), PAPEL_GRIS, np.uint8)
    mascara_debajo = np.zeros((alto, ancho), np.uint8)
    for red_b, m_b, rec_b in debajo:
        gris, mascara = render(red_b, m_b, rec_b, cv2.BORDER_REPLICATE)
        np.copyto(fondo, gris, where=mascara.view(bool))
        mascara_debajo |= mascara
    # La hoja con borde replicado: ECC mira un poco más allá del filo al moverla.
    gris_h, mascara_h = render(red, m_hoja, recorte, cv2.BORDER_REPLICATE)
    traslape = mascara_h & mascara_debajo
    minimo = MIN_TRASLAPE_MM2 * r * r
    if lejos:
        cerca_h = cv2.distanceTransform(1 - mascara_h, cv2.DIST_L2, 5) <= margen
        cerca_d = cv2.distanceTransform(1 - mascara_debajo, cv2.DIST_L2, 5) <= margen
        zona = (cerca_h & cerca_d).astype(np.uint8)
        if (zona & mascara_h).sum() < minimo or (zona & mascara_debajo).sum() < minimo:
            return None
        return _Escena(r, a_lienzo, fondo, mascara_debajo, gris_h, mascara_h, zona, zona)
    if traslape.sum() < minimo:
        return None
    distancia = cv2.distanceTransform((1 - traslape).astype(np.uint8), cv2.DIST_L2, 5)
    zona = (distancia <= margen).astype(np.uint8)
    return _Escena(r, a_lienzo, fondo, mascara_debajo, gris_h, mascara_h, zona, traslape)


def _calzar(reducida_hoja, m_hoja, recorte, debajo_a, ppmm_u):
    """La matriz corregida de la hoja (px de hoja → unión sin origen) y el residuo en
    mm, o None si no calza dentro de los topes."""
    # 1) ORB + RANSAC a 2 px/mm: el calce grueso; si no sale, con la zona de una hoja lejos.
    for lejos, tope_mm in ((False, MAX_CORRECCION_MM), (True, MAX_CORRECCION_LEJOS_MM)):
        grueso = _calce_grueso(reducida_hoja, m_hoja, recorte, debajo_a, ppmm_u, lejos, tope_mm)
        if grueso is not None:
            break
    else:
        return None
    esc, m_orb, tope_mm = grueso

    # 2) ECC euclídeo a 4 px/mm, partiendo de lo que dio ORB.
    m_final = m_orb
    esc4 = _escena(reducida_hoja(PPMM_ECC), m_orb, recorte, debajo_a(PPMM_ECC), ppmm_u, PPMM_ECC)
    if esc4 is not None:
        t4 = _ecc(esc4)
        if t4 is not None:
            m_ecc = np.linalg.inv(esc4.a_lienzo) @ t4 @ esc4.a_lienzo @ m_orb
            # El tope se mide contra la posición de partida, no contra la de ORB.
            t_total = esc.a_lienzo @ m_ecc @ np.linalg.inv(m_hoja) @ np.linalg.inv(esc.a_lienzo)
            if _dentro_de_topes(t_total, esc, tope_mm):
                m_final = m_ecc
        residuo = _residuo(esc4 if m_final is m_orb else
                           _escena(reducida_hoja(PPMM_ECC), m_final, recorte, debajo_a(PPMM_ECC), ppmm_u,
                                   PPMM_ECC))
    else:
        residuo = None
    return m_final, residuo


def _calce_grueso(reducida_hoja, m_hoja, recorte, debajo_a, ppmm_u, lejos, tope_mm):
    """La escena a 2 px/mm, la matriz que da ORB y el tope usado, o None."""
    esc = _escena(reducida_hoja(PPMM_ORB), m_hoja, recorte, debajo_a(PPMM_ORB), ppmm_u, PPMM_ORB, lejos)
    if esc is None:
        return None
    pares = _pares_orb(esc)
    if pares is None:
        return None
    src, dst = pares
    t = _rigido_ransac(src, dst, UMBRAL_RANSAC_MM * PPMM_ORB)
    if t is None:
        return None
    t, inliers = t
    if inliers < MIN_PUNTOS or not _dentro_de_topes(t, esc, tope_mm):
        return None
    return esc, np.linalg.inv(esc.a_lienzo) @ t @ esc.a_lienzo @ m_hoja, tope_mm


def _pares_orb(esc: _Escena):
    orb = cv2.ORB_create(nfeatures=6000, scaleFactor=1.2, nlevels=6, fastThreshold=10)
    k1, d1 = orb.detectAndCompute(esc.hoja, (esc.mascara_hoja & esc.zona) * 255)
    k2, d2 = orb.detectAndCompute(esc.debajo, (esc.mascara_debajo & esc.zona) * 255)
    if d1 is None or d2 is None or len(k1) < MIN_PUNTOS or len(k2) < MIN_PUNTOS:
        return None
    buenos = []
    for par in cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(d1, d2, k=2):
        # Prueba de Lowe: un plano repite mucho (líneas, números); lo ambiguo no sirve.
        if len(par) == 2 and par[0].distance < 0.8 * par[1].distance:
            buenos.append(par[0])
    if len(buenos) < MIN_PUNTOS:
        return None
    src = np.float64([k1[m.queryIdx].pt for m in buenos])
    dst = np.float64([k2[m.trainIdx].pt for m in buenos])
    return src, dst


def _rigido(src, dst) -> np.ndarray:
    """Giro y traslado que mejor lleva src a dst (Kabsch, sin escala), 3×3."""
    cs, cd = src.mean(0), dst.mean(0)
    u, _, vt = np.linalg.svd((src - cs).T @ (dst - cd))
    d = np.sign(np.linalg.det(vt.T @ u.T))
    rot = vt.T @ np.diag([1, d]) @ u.T
    m = np.eye(3)
    m[:2, :2] = rot
    m[:2, 2] = cd - rot @ cs
    return m


def _rigido_ransac(src, dst, umbral):
    # RANSAC de similitud de OpenCV para separar los calces buenos; la escala de una
    # misma lámina impresa no cambia, así que se ajusta un rígido sobre los inliers.
    _, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=umbral,
                                         maxIters=5000, confidence=0.999)
    if inl is None or inl.sum() < 3:
        return None
    sel = inl.ravel().astype(bool)
    for _ in range(3):
        t = _rigido(src[sel], dst[sel])
        error = np.linalg.norm(pg._aplicar(t, src) - dst, axis=1)
        nueva = error < umbral
        if nueva.sum() < 3 or np.array_equal(nueva, sel):
            break
        sel = nueva
    return _rigido(src[sel], dst[sel]), int(sel.sum())


def _dentro_de_topes(t, esc: _Escena, tope_mm=MAX_CORRECCION_MM) -> bool:
    """El giro y lo que se mueve el centro del traslape, en px de lienzo → mm/grados."""
    ys, xs = np.nonzero(esc.traslape)
    centro = np.array([[xs.mean(), ys.mean()]])
    mm = float(np.linalg.norm(pg._aplicar(t, centro) - centro)) / esc.r
    grados = abs(math.degrees(math.atan2(t[1, 0], t[0, 0])))
    return mm <= tope_mm and grados <= MAX_CORRECCION_GRADOS


def _caja_mascara(mascara, margen):
    ys, xs = np.nonzero(mascara)
    alto, ancho = mascara.shape
    return (max(xs.min() - margen, 0), max(ys.min() - margen, 0),
            min(xs.max() + margen + 1, ancho), min(ys.max() + margen + 1, alto))


def _ecc(esc: _Escena):
    """El rígido (en px del lienzo) que lleva la hoja a lo de debajo, o None si ECC no
    converge o deja peor la correlación que la de partida."""
    # Solo donde están las dos, lejos del filo: ahí el borde replicado inventa dibujo.
    adentro = cv2.erode(esc.mascara_hoja, np.ones((7, 7), np.uint8)) & esc.mascara_debajo
    if adentro.sum() < MIN_TRASLAPE_MM2 * esc.r * esc.r:
        return None
    x0, y0, x1, y1 = _caja_mascara(adentro, 8)
    # Plantilla = debajo (fija); entrada = hoja. ECC busca W con debajo(x) ≈ hoja(W x).
    plantilla = esc.debajo[y0:y1, x0:x1].astype(np.float32)
    entrada = esc.hoja[y0:y1, x0:x1].astype(np.float32)
    mascara = adentro[y0:y1, x0:x1]
    w = np.eye(2, 3, dtype=np.float32)
    try:
        antes = cv2.computeECC(plantilla, entrada, mascara)
        _, w = cv2.findTransformECC(plantilla, entrada, w, cv2.MOTION_EUCLIDEAN,
                                    (cv2.TERM_CRITERIA_COUNT | cv2.TERM_CRITERIA_EPS, 50, 1e-4), mascara, 5)
        movida = cv2.warpAffine(entrada, w, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP,
                                borderMode=cv2.BORDER_REPLICATE)
        despues = cv2.computeECC(plantilla, movida, mascara)
    except cv2.error:
        return None
    if not np.all(np.isfinite(w)) or despues < antes:
        return None
    # W lleva px de debajo a px de hoja (en la caja); la corrección de la hoja es W⁻¹,
    # expresada en px del lienzo entero.
    caja = np.array([[1, 0, x0], [0, 1, y0], [0, 0, 1]], float)
    w3 = np.vstack([w.astype(float), [0, 0, 1]])
    return caja @ np.linalg.inv(w3) @ np.linalg.inv(caja)


def _residuo(esc: _Escena | None) -> float | None:
    """Distancia cuadrática media, en mm, entre los puntos que calzan con la hoja ya
    afinada: lo que queda sin corregir en el traslape. No la mediana: ORB da muchos
    puntos en px enteros que coinciden exactos y la mediana diría 0."""
    if esc is None:
        return None
    pares = _pares_orb(esc)
    if pares is None:
        return None
    src, dst = pares
    t = _rigido_ransac(src, dst, UMBRAL_RANSAC_MM * esc.r)
    if t is None:
        return None
    error = np.linalg.norm(src - dst, axis=1)
    sel = np.linalg.norm(pg._aplicar(t[0], src) - dst, axis=1) < UMBRAL_RANSAC_MM * esc.r
    return round(float(np.sqrt(np.mean(error[sel] ** 2))) / esc.r, 3)
