"""Planos sintéticos para probar pipeline.plano: una grilla de lotes dibujada como
la dibuja un topógrafo, con lo que estorba en un escaneo real.

A 6 px/mm, sin remuestreo. La grilla tiene COLUMNAS × FILAS lotes de LOTE_MM; entre
la primera y la segunda fila pasa un camino de doble línea, y una de las divisorias
verticales es una línea doble angosta. El dibujo trae cortes en el trazo, cotas
escritas encima de las líneas, rótulos y una franja punteada en verde.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from shapely.geometry import Polygon, box

PPMM = 6.0
PAPEL = (244, 241, 233)
NEGRO = (35, 35, 40)
ROJO = (205, 45, 50)
VERDE = (70, 160, 80)

MARGEN_MM = 30.0
LOTE_MM = (50.0, 35.0)
COLUMNAS, FILAS = 4, 3
CAMINO_MM = 6.0          # ancho del camino de doble línea entre la fila 0 y la 1
DOBLE_MM = 1.5           # separación de la divisoria doble (entre las columnas 1 y 2)


@dataclass
class Plano:
    imagen: np.ndarray
    semillas: list[tuple[str, float, float]]
    celdas: dict[str, Polygon]       # el lote ideal (entre ejes de línea), px
    contorno: Polygon                # el borde exterior del loteo, px
    camino: Polygon                  # la franja del camino, px


def _px(mm: float) -> float:
    return mm * PPMM


def dibujar(color=NEGRO, grosor_px=2) -> Plano:
    ancho_lote, alto_lote = _px(LOTE_MM[0]), _px(LOTE_MM[1])
    m = _px(MARGEN_MM)
    camino = _px(CAMINO_MM)
    ancho = int(round(2 * m + COLUMNAS * ancho_lote))
    alto = int(round(2 * m + FILAS * alto_lote + camino))
    rng = np.random.default_rng(7)
    img = np.empty((alto, ancho, 3), np.uint8)
    img[:] = PAPEL
    img = np.clip(img.astype(np.int16) + rng.integers(-4, 5, img.shape), 0, 255).astype(np.uint8)

    # Ejes de las líneas: x de las verticales, y de las horizontales (el camino separa
    # la fila 0 de las demás).
    xs = [m + i * ancho_lote for i in range(COLUMNAS + 1)]
    ys = [m, m + alto_lote, m + alto_lote + camino] + [m + camino + i * alto_lote for i in range(2, FILAS + 1)]
    x0, x1, y0, y1 = xs[0], xs[-1], ys[0], ys[-1]

    def linea(p, q, g=grosor_px):
        # cv2 dibuja con el centro del píxel en el entero.
        cv2.line(img, (int(round(p[0])), int(round(p[1]))), (int(round(q[0])), int(round(q[1]))), color, g)

    # Borde exterior, más grueso.
    for p, q in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        linea(p, q, grosor_px + 1)
    # Camino de doble línea entre la fila 0 y la 1.
    linea((x0, ys[1]), (x1, ys[1]))
    linea((x0, ys[2]), (x1, ys[2]))
    # Divisorias horizontales de las filas de abajo.
    for y in ys[3:-1]:
        linea((x0, y), (x1, y))
    # Divisorias verticales; la de entre las columnas 1 y 2 es doble y angosta.
    for i, x in enumerate(xs[1:-1], start=1):
        for a, b in ((y0, ys[1]), (ys[2], y1)):
            if i == 2:
                d = _px(DOBLE_MM) / 2
                linea((x - d, a), (x - d, b))
                linea((x + d, a), (x + d, b))
            else:
                linea((x, a), (x, b))

    # Cortes de 1 mm en el trazo, como deja un escaneo con tinta gastada.
    for (cx, cy, vertical) in ((xs[1], ys[0] + 0.5 * alto_lote, True), (xs[3], ys[3] + 0.3 * alto_lote, True),
                               (xs[0] + 0.6 * ancho_lote, ys[3], False), (xs[2] + 0.3 * ancho_lote, ys[4], False)):
        h = _px(1.0) / 2
        if vertical:
            img[int(cy - h):int(cy + h), int(cx - 4):int(cx + 5)] = PAPEL
        else:
            img[int(cy - 4):int(cy + 5), int(cx - h):int(cx + h)] = PAPEL

    # Cotas escritas encima de las líneas.
    for (cx, cy) in ((xs[1] - 30, ys[3] + 5), (xs[2] + 0.4 * ancho_lote, ys[4] + 6), (xs[4] - 50, ys[0] + 4)):
        cv2.putText(img, "123,45", (int(cx), int(cy)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 1, cv2.LINE_AA)

    # Franja punteada en verde (achurado de quebrada) que cruza dos lotes.
    for x in range(int(xs[0] + 20), int(xs[2] - 20), 9):
        for k in range(4):
            y = ys[3] + 0.5 * alto_lote + k * 8 + (x % 3)
            cv2.circle(img, (x, int(y)), 2, VERDE, -1)

    semillas, celdas = [], {}
    filas = [(ys[0], ys[1])] + [(ys[i], ys[i + 1]) for i in range(2, len(ys) - 1)]
    n = 0
    for f, (a, b) in enumerate(filas):
        for c in range(COLUMNAS):
            n += 1
            l, r = xs[c], xs[c + 1]
            cx, cy = (l + r) / 2, (a + b) / 2
            cv2.putText(img, f"LOTE {n}", (int(cx - 35), int(cy - 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        color, 1, cv2.LINE_AA)
            semillas.append((str(n), cx, cy))
            celdas[str(n)] = box(l, a, r, b)
    return Plano(img, semillas, celdas, box(x0, y0, x1, y1), box(x0, ys[1], x1, ys[2]))


def iou(a: Polygon, b: Polygon) -> float:
    return a.intersection(b).area / a.union(b).area


# Loteo girado como Caminos de Rapel: dos filas de lotes con las divisorias desfasadas
# (llegan en T al deslinde del medio) y, si `texto`, letras en negrita pegadas al borde
# norte, por fuera y por dentro.
GIRADO_MM = (260.0, 120.0)
ARRIBA_MM = [0, 30, 62, 95, 128, 160, 193, 226, 260]
ABAJO_MM = [0, 40, 75, 110, 145, 178, 212, 260]


def dibujar_girado(giro: float = -14.0, texto: bool = True) -> Plano:
    W, H = GIRADO_MM
    m = 40.0
    ancho, alto = int(round((W + 2 * m) * PPMM)), int(round((H + 2 * m) * PPMM)) + 300
    rng = np.random.default_rng(1)
    img = np.empty((alto, ancho, 3), np.uint8)
    img[:] = PAPEL
    img = np.clip(img.astype(np.int16) + rng.integers(-4, 5, img.shape), 0, 255).astype(np.uint8)
    c, s = np.cos(np.radians(giro)), np.sin(np.radians(giro))

    def P(x, y):                    # mm del loteo (origen arriba a la izquierda) -> px
        u, v = (x - W / 2) * PPMM, (y - H / 2) * PPMM
        return (ancho / 2 + c * u - s * v, alto / 2 + s * u + c * v)

    def linea(a, b, g=2):
        p, q = P(*a), P(*b)
        cv2.line(img, (int(round(p[0])), int(round(p[1]))), (int(round(q[0])), int(round(q[1]))), NEGRO, g)

    medio = H / 2
    for a, b in (((0, 0), (W, 0)), ((W, 0), (W, H)), ((W, H), (0, H)), ((0, H), (0, 0))):
        linea(a, b, 3)
    linea((0, medio), (W, medio))
    for x in ARRIBA_MM[1:-1]:
        linea((x, 0), (x, medio))
    for x in ABAJO_MM[1:-1]:
        linea((x, medio), (x, H))
    if texto:
        for x, y, t in ((70, 1.2, "SERVIDUMBRE DE TRANSITO 10,00 m"), (165, 3.2, "CAMINO VECINAL")):
            p = P(x, y)
            letras = np.zeros((alto, ancho), np.uint8)
            cv2.putText(letras, t, (int(p[0]), int(p[1])), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 255, 3, cv2.LINE_AA)
            letras = cv2.warpAffine(letras, cv2.getRotationMatrix2D(p, -giro, 1.0), (ancho, alto))
            img[letras > 100] = NEGRO

    semillas, celdas = [], {}
    n = 0
    for xs, (y0, y1) in ((ARRIBA_MM, (0, medio)), (ABAJO_MM, (medio, H))):
        for a, b in zip(xs[:-1], xs[1:]):
            n += 1
            numero = f"8-{n:02d}"
            semillas.append((numero, *P((a + b) / 2, (y0 + y1) / 2 + 6)))
            celdas[numero] = Polygon([P(a, y0), P(b, y0), P(b, y1), P(a, y1)])
            q = P((a + b) / 2 - 6, (y0 + y1) / 2 + 3)
            cv2.putText(img, f"{n:02d}", (int(q[0]), int(q[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.6, NEGRO, 1,
                        cv2.LINE_AA)
    contorno = Polygon([P(0, 0), P(W, 0), P(W, H), P(0, H)])
    return Plano(img, semillas, celdas, contorno, Polygon())
