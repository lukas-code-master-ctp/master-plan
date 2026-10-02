"""Lee el cuadro de superficies de Algarrobo (recorte = su rectangulo de mascara, como lo
marcaria la loteadora) y lo compara con las areas oficiales leidas a ojo. Corre en el contenedor.

Rotacion: se prueban 0/90/180/270 y se queda la que da mas valores con forma d,dd. Escala x2, psm 6 (bloque) y psm 4 (columna), gris y Otsu; por cada lote se toma la
primera lectura que lo trae. Antes se borran las lineas de la grilla. Fila correcta (estricta): primer numero = lote y
el ultimo (columna TOTAL) = area oficial en ha con 2 decimales. Laxa: el area oficial aparece en la fila.
"""
import json, re, time
import cv2, numpy as np, pytesseract
from comun import gris_normalizado
from ocr import rotar

NUM = re.compile(r'\d+(?:[.,]\d+)?')


def filas(img, psm):
    t = pytesseract.image_to_string(img, config=f'--oem 1 --psm {psm} -c tessedit_char_whitelist=0123456789,.')
    out = []
    for linea in t.splitlines():
        v = NUM.findall(linea)
        if v and re.fullmatch(r'\d{1,3}', v[0]):
            out.append([x.replace('.', ',') for x in v])
    return out


def sin_lineas(g):
    """Borra las lineas de la grilla del cuadro (aperturas morfologicas largas)."""
    b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    h = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (60, 1)))
    v = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 60)))
    m = cv2.dilate(cv2.bitwise_or(h, v), np.ones((3, 3), np.uint8))
    out = g.copy(); out[m > 0] = 255
    return out


def main():
    t0 = time.time()
    V = json.load(open('datos/verdad.json'))['algarrobo']['areas']
    oficial = {int(n): f'{a / 10000:.2f}'.replace('.', ',') for n, a in V.items()}
    g = gris_normalizado(cv2.imread('datos/alg_tabla.png'))
    g = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    def decimales(a):
        t = pytesseract.image_to_string(sin_lineas(rotar(g, a)[0]), config='--oem 1 --psm 6 -c tessedit_char_whitelist=0123456789,.')
        return len(re.findall(r'(?<![\d,.])\d{1,2},\d{2}(?![\d,.])', t))
    puntajes = {a: decimales(a) for a in (0, 90, 180, 270)}
    mejor = max(puntajes, key=puntajes.get)
    r = sin_lineas(rotar(g, mejor)[0])
    b = cv2.threshold(cv2.GaussianBlur(r, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    por_lote = {}
    for psm in (6, 4):
        for img in (r, b):
            for f in filas(img, psm):
                n = int(f[0])
                if n in oficial and n not in por_lote:
                    por_lote[n] = f
    estricta = sum(1 for n, f in por_lote.items() if len(f) > 1 and f[-1] == oficial[n])
    laxa = sum(1 for n, f in por_lote.items() if oficial[n] in f[1:])
    res = dict(segundos=time.time() - t0, rotacion=mejor, puntajes=puntajes, filas=len(oficial), lotes_leidos=len(por_lote),
               estricta=estricta, laxa=laxa,
               ejemplos=[(n, por_lote[n], oficial[n]) for n in sorted(por_lote)[:10]])
    json.dump(res, open('datos/tabla_res.json', 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == '__main__':
    main()
