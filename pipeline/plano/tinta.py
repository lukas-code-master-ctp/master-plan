"""Qué píxeles de la imagen de trabajo son trazo de deslinde.

Los deslindes van en tinta roja o negra. Todo lo demás estorba: la tinta verde
(achurado de quebradas), la azul (timbres, líneas de alta tensión), el texto, las
cotas, los trazos sueltos de una línea segmentada, la cuadrícula UTM impresa y, en
una foto o un escaneo de un papel doblado, los pliegues.

Los parámetros son globales, los mismos para todo plano, y van en mm de papel: el
grosor de línea, el tamaño del texto y los huecos del trazo son del dibujo impreso,
no del terreno. Salen de la ronda 3 de pruebas (cuatro planos a ciegas); cambiarlos
para arreglar un plano suele romper otro.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import find_peaks
from skimage.filters import apply_hysteresis_threshold

# Tinta: oscurecimiento local respecto del papel (black-hat por canal).
BH_MM = 1.3            # estructuras oscuras más angostas que esto son tinta
INK_T = 40             # oscurecimiento mínimo (niveles de gris, canal más oscurecido)
INK_T_BAJO = 20        # umbral bajo de la histéresis: lo débil pegado a lo fuerte también es tinta
CHROMA_FRAC = 0.35     # margen relativo para declarar una tinta verde, azul o roja
DARK_MAX = 105         # tinta "firme" (un límite está dibujado): canal mínimo ≤ esto, o tinta roja
ROJO_FIRME_FRAC = 0.15  # tinta roja "firme": basta este margen (el rosado tenue de un escaneo no llega a CHROMA_FRAC)

# Cuadrícula UTM impresa.
GRID_MM = 0.5          # semiancho de la franja que se borra sobre cada línea de la cuadrícula
VENTANA_CUADRICULA_MM = 4.25   # cuánto puede desviarse la línea de la posición marcada
FRANJA_CUADRICULA_MM = 25.4    # largo de cada tramo en que se busca la línea

# Pliegues del papel: tramos rectos, alineados con la hoja, de tinta pálida.
FOLD_PALE = 180        # tinta "pálida": canal mínimo mayor que esto
FOLD_CHUNK_MM = 60.0   # largo del bloque en que se busca un pliegue recto
FOLD_FRAC = 0.5        # fracción del bloque cubierta por tinta pálida para declarar pliegue
FOLD_MM = 0.8          # semiancho de la franja del pliegue

# Líneas y rellenos.
MIN_COMP_MM = 10.0     # lado mayor mínimo de una línea: borra texto, cotas, puntos y trazos sueltos
HOLE_MM2 = 10.0        # huecos menores se rellenan (celdas de un achurado)
THICK_MM = 1.6         # lo que sobrevive a esta apertura es relleno (franja achurada): no es lote
# Un relleno de verdad es un achurado, y es grande. Lo chico que sobrevive a la apertura
# es tinta: texto pegado a una línea ("Servidumbre de tránsito 10 m" sobre el deslinde),
# rótulos en negrita, sellos, el nudo de líneas que se juntan en ángulo agudo. Como
# relleno se comía el borde o la esquina de los lotes vecinos (en Caminos de Rapel, del
# 5 al 10 % del área de los lotes 8-03 a 8-05 y 8-13); como tinta, el watershed la
# reparte por su eje. En el set de regresión lo chico mide ≤ 135 mm² (el texto sobre el
# deslinde de Rapel, 88 mm²) y los achurados ≥ 1.300 mm² (Puente Negro, 3.685 mm²; la
# prueba sintética, 1.333 mm²). El ancho y la fracción de papel no los separan.
RELLENO_MIN_MM2 = 250.0


@dataclass
class Tinta:
    lineas: np.ndarray     # bool: trazo de deslinde
    firme: np.ndarray      # bool: trazo oscuro de verdad o rojo (un pliegue no lo es)
    grueso: np.ndarray     # bool: zonas rellenas (achurados, franjas)
    pliegues: int          # tramos de pliegue borrados


def impar(x: float) -> int:
    x = max(1, int(round(x)))
    return x if x % 2 else x + 1


def mascara(imagen: np.ndarray, ppmm: float, banda_cuadricula: np.ndarray | None = None) -> Tinta:
    """La tinta de deslindes de la imagen de trabajo (RGB) a `ppmm` px por mm."""
    mm = lambda v: v * ppmm
    alto, ancho = imagen.shape[:2]
    nucleo = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (impar(mm(BH_MM)),) * 2)
    suave = cv2.GaussianBlur(imagen, (0, 0), 0.5)
    d = np.stack([cv2.morphologyEx(np.ascontiguousarray(suave[..., c]), cv2.MORPH_BLACKHAT, nucleo)
                  for c in range(3)], -1).astype(np.int16)
    del suave
    dmax = d.max(-1)
    dr, dg, db = d[..., 0], d[..., 1], d[..., 2]
    fuerte = apply_hysteresis_threshold(dmax, INK_T_BAJO - 0.5, INK_T - 0.5)
    # El canal que menos se oscurece dice el color: si es el verde, la tinta es verde.
    verde = (np.minimum(dr, db) - dg) > CHROMA_FRAC * dmax
    azul = (np.minimum(dr, dg) - db) > CHROMA_FRAC * dmax
    tinta = fuerte & ~verde & ~azul
    del fuerte, verde, azul
    pliegues = _borrar_pliegues(tinta, imagen, ppmm)
    if banda_cuadricula is not None:
        # La cuadrícula es tenue: se borra su trazo y queda lo oscuro que la cruza.
        tinta &= ~(banda_cuadricula & (dmax < 2 * INK_T))
    rojo = (np.minimum(dg, db) - dr) > ROJO_FIRME_FRAC * dmax
    firme = tinta & ((imagen.min(-1) <= DARK_MAX) | rojo)
    del d, dr, dg, db, rojo, dmax
    lineas = _lineas(tinta, ppmm)
    grueso, chico = _rellenos(lineas, ppmm)
    # Lo chico queda como línea pero no como tinta firme: si el texto encierra un trozo
    # de lote (un rótulo en diagonal de deslinde a deslinde), ese trozo se une al lote.
    firme &= ~chico
    return Tinta(lineas=lineas, firme=firme, grueso=grueso, pliegues=pliegues)


def _borrar_pliegues(tinta: np.ndarray, imagen: np.ndarray, ppmm: float) -> int:
    """Por bloques de FOLD_CHUNK_MM busca la fila o columna donde la tinta pálida
    cubre ≥ FOLD_FRAC del bloque. En una franja de ±FOLD_MM borra lo pálido; las
    líneas dibujadas que cruzan o siguen el pliegue son oscuras y quedan."""
    alto, ancho = tinta.shape
    minimo = imagen.min(-1)
    debil = minimo > FOLD_PALE
    palida = (tinta & debil).astype(np.float32)
    del minimo
    bloque = max(10, int(FOLD_CHUNK_MM * ppmm))
    semiancho = max(1, int(round(FOLD_MM * ppmm)))
    n = 0
    for eje in (0, 1):                       # 0: pliegues verticales (perfil por columnas)
        largo = alto if eje == 0 else ancho
        for s0 in range(0, largo, bloque // 2):
            trozo = palida[s0:s0 + bloque, :] if eje == 0 else palida[:, s0:s0 + bloque]
            if trozo.shape[eje] < bloque // 2:
                continue
            perfil = uniform_filter1d(trozo.mean(axis=eje), 3)
            picos, _ = find_peaks(perfil, height=FOLD_FRAC)
            for p in picos:
                n += 1
                if eje == 0:
                    franja = (slice(s0, s0 + bloque), slice(max(0, p - semiancho), p + semiancho + 1))
                else:
                    franja = (slice(max(0, p - semiancho), p + semiancho + 1), slice(s0, s0 + bloque))
                tinta[franja] &= ~debil[franja]
    return n


def _lineas(tinta: np.ndarray, ppmm: float) -> np.ndarray:
    """Componentes de tinta con lado mayor ≥ MIN_COMP_MM."""
    _, etiquetas, stats, _ = cv2.connectedComponentsWithStats(tinta.astype(np.uint8), connectivity=8)
    conservar = np.maximum(stats[:, 2], stats[:, 3]) >= MIN_COMP_MM * ppmm
    conservar[0] = False
    return conservar[etiquetas]


def _rellenos(lineas: np.ndarray, ppmm: float) -> tuple[np.ndarray, np.ndarray]:
    """Achurados y franjas: se rellenan los huecos chicos y lo que sobrevive a una
    apertura de THICK_MM es relleno, si mide al menos RELLENO_MIN_MM2. Devuelve
    (relleno, lo que sobrevive a la apertura pero es más chico)."""
    _, etiquetas, stats, _ = cv2.connectedComponentsWithStats((~lineas).astype(np.uint8), connectivity=4)
    hueco = stats[:, 4] < HOLE_MM2 * ppmm * ppmm
    hueco[0] = False
    lleno = lineas | hueco[etiquetas]
    del etiquetas
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (impar(THICK_MM * ppmm),) * 2)
    abierto = cv2.morphologyEx(lleno.astype(np.uint8), cv2.MORPH_OPEN, k)
    del lleno
    n, etiquetas, stats, _ = cv2.connectedComponentsWithStats(abierto, connectivity=8)
    grande = stats[:, 4] >= RELLENO_MIN_MM2 * ppmm * ppmm
    grande[0] = False
    return grande[etiquetas], abierto.astype(bool) & ~grande[etiquetas]


# ---------------------------------------------------------------------------- cuadrícula
def lineas_cuadricula(gris: np.ndarray, ppmm: float, verticales=(), horizontales=()):
    """Las líneas de la cuadrícula UTM impresa, a lo largo de toda la hoja.

    `gris`: la página en grises (sin máscaras: la línea cruza los cuadros). Se parte
    de la posición aproximada de cada línea (x de las verticales, y de las
    horizontales) y se la sigue por tramos de FRANJA_CUADRICULA_MM: en cada tramo, el
    pico del perfil de oscurecimiento con precisión subpíxel. Con los picos se ajusta
    una recta robusta. Devuelve [(p, q, valido)] en píxeles de página, con p y q los
    extremos de la recta en el borde de la hoja y `valido` si la recta se apoyó en
    suficientes tramos y con poca dispersión.
    """
    d = 255.0 - gris.astype(np.float32)
    alto, ancho = d.shape
    ventana = int(round(VENTANA_CUADRICULA_MM * ppmm))
    franja = int(round(FRANJA_CUADRICULA_MM * ppmm))
    salida = []
    for x in verticales:
        (a, b), n, rms = _seguir_linea(d, x, True, ventana, franja)
        salida.append(((b, 0.0), (a * alto + b, float(alto)), n >= 10 and rms <= 2.0))
    for y in horizontales:
        (c, e), n, rms = _seguir_linea(d, y, False, ventana, franja)
        salida.append(((0.0, e), (float(ancho), c * ancho + e), n >= 10 and rms <= 2.0))
    return salida


def banda_cuadricula(forma, segmentos, ppmm: float) -> np.ndarray:
    """Franja de ±GRID_MM sobre cada línea (segmentos ya en píxeles de trabajo)."""
    banda = np.zeros(forma[:2], np.uint8)
    semiancho = max(1, int(round(GRID_MM * ppmm)))
    for p, q in segmentos:
        cv2.line(banda, (int(round(p[0])), int(round(p[1]))), (int(round(q[0])), int(round(q[1]))),
                 1, 2 * semiancho + 1)
    return banda > 0


def _pico(perfil: np.ndarray) -> float | None:
    b = perfil - np.median(perfil)
    i = int(np.argmax(b))
    if b[i] < 2.5 or i == 0 or i == len(b) - 1:
        return None
    y0, y1, y2 = b[i - 1], b[i], b[i + 1]
    den = y0 - 2 * y1 + y2
    return i + (0.5 * (y0 - y2) / den if den != 0 else 0.0)


def _seguir_linea(d: np.ndarray, c: float, vertical: bool, ventana: int, franja: int):
    """Recta coord_perpendicular = m0·t + m1 de la línea que pasa cerca de `c`."""
    alto, ancho = d.shape
    largo = alto if vertical else ancho
    c = int(c)
    puntos = []
    for s in range(0, largo - franja, franja // 2):
        if vertical:
            perfil = np.median(d[s:s + franja, max(0, c - ventana):c + ventana + 1], axis=0)
        else:
            perfil = np.median(d[max(0, c - ventana):c + ventana + 1, s:s + franja], axis=1)
        p = _pico(perfil)
        if p is not None:
            puntos.append((s + franja / 2, max(0, c - ventana) + p))
    if len(puntos) < 2:
        return (0.0, float(c)), len(puntos), float("inf")
    P = np.array(puntos)
    ok = np.ones(len(P), bool)
    for _ in range(5):
        A = np.c_[P[ok, 0], np.ones(ok.sum())]
        m, *_ = np.linalg.lstsq(A, P[ok, 1], rcond=None)
        r = P[:, 1] - (m[0] * P[:, 0] + m[1])
        ok = np.abs(r) < max(1.0, 2.5 * np.median(np.abs(r[ok])))
        if ok.sum() < 2:
            return (float(m[0]), float(m[1])), int(ok.sum()), float("inf")
    return (float(m[0]), float(m[1])), int(ok.sum()), float(np.sqrt(np.mean(r[ok] ** 2)))
