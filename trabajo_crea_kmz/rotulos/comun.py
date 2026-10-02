"""Piezas comunes del lector Tesseract de prueba (corre dentro del contenedor rotulos-tess)."""
import re
import cv2
import numpy as np

ALTO_OBJETIVO = 32  # alto de caracter (px) al que se normaliza la imagen antes del OCR


def gris_normalizado(bgr):
    """Luminancia dividida por el fondo (quita sombras de foto y escaneo palido)."""
    g = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    k = max(31, (min(g.shape) // 40) | 1)
    fondo = cv2.medianBlur(cv2.resize(g, None, fx=0.25, fy=0.25).astype(np.uint8), k | 1)
    fondo = cv2.resize(fondo, (g.shape[1], g.shape[0])).astype(np.float32)
    n = np.clip(g / np.maximum(fondo, 1) * 255, 0, 255)
    return n.astype(np.uint8)


def alto_caracter(gris):
    """Estima el alto tipico de caracter: moda de alturas de componentes 'tipo letra'."""
    b = (gris < 150).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(b, 8)
    h = st[1:, cv2.CC_STAT_HEIGHT]; w = st[1:, cv2.CC_STAT_WIDTH]; a = st[1:, cv2.CC_STAT_AREA]
    ok = (h >= 6) & (h <= 200) & (w >= 2) & (w <= 1.3 * h) & (w >= 0.25 * h) & (a > 0.15 * w * h) & (a < 0.75 * w * h)
    hs = h[ok]
    if len(hs) < 20:
        return 20.0
    hist = np.bincount(np.clip(hs, 0, 200))
    hist = np.convolve(hist, np.ones(3), 'same')
    return float(np.argmax(hist[6:]) + 6)


RE_NUM = re.compile(r'^(?:LOTE)?-*(?:\d{1,3}-)?(\d{1,3})-*$')


def numero(texto):
    """'LOTE-12' / '12' / '10-6' (prefijo) -> 12 / 12 / 6. Descarta cotas y areas (con , o .)."""
    t = texto.strip().upper().replace('—', '-')
    if not t or ',' in t or '.' in t:
        return None
    m = RE_NUM.match(t)
    if not m:
        return None
    n = int(m.group(1))
    return n if n > 0 else None
