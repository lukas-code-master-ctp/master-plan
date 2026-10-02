"""Lector Tesseract GLOBAL (mismos parametros para todos los planos).

Uso (en el contenedor): python ocr.py <plano> [paso_grados=15]
Entrada datos/<plano>_dibujo.png; salida datos/det_<plano>.json con las palabras numericas
leidas: numero, texto, x, y (en px del dibujo), confianza, angulo, escala.

Metodo: gris normalizado por fondo -> alto tipico de caracter (moda) -> 2 escalas (texto
modal a 24 px, y 2,5x mas chica para rotulos grandes) -> la imagen se rota cada `paso`
grados (0..360), en gris y binarizada (Otsu) -> Tesseract psm 11 (texto disperso) con lista blanca LOTE0-9-,. ->
el centro de cada palabra se lleva de vuelta al marco del dibujo.
"""
import json, os, sys, time
from multiprocessing import Pool
import cv2
import numpy as np
import pytesseract
from comun import gris_normalizado, alto_caracter, numero

CFG = '--oem 1 --psm 11 -c tessedit_char_whitelist=LOTE0123456789-,.'


def rotar(img, ang):
    h, w = img.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    c, s = abs(M[0, 0]), abs(M[0, 1])
    W, H = int(h * s + w * c), int(h * c + w * s)
    M[0, 2] += W / 2 - w / 2; M[1, 2] += H / 2 - h / 2
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=255), M


def trabajo(args):
    ruta, escala, ang, var = args
    g = cv2.imread(ruta, cv2.IMREAD_GRAYSCALE)
    g = cv2.resize(g, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_CUBIC)
    if var == 'bin':
        g = cv2.threshold(cv2.GaussianBlur(g, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    r, M = rotar(g, ang)
    Mi = cv2.invertAffineTransform(M)
    d = pytesseract.image_to_data(r, config=CFG, output_type=pytesseract.Output.DICT)
    out = []
    txt = d['text']
    for i, t in enumerate(txt):
        n = numero(t)
        if n is None:
            continue
        x0, y0 = d['left'][i], d['top'][i]; x1, y1 = x0 + d['width'][i], y0 + d['height'][i]
        # "LOTE" pegado (LOTE-12) o como palabra anterior en la misma linea (LOTE 12)
        lote = 'OTE' in t.upper()
        j = i - 1
        if not lote and j >= 0 and 'OTE' in txt[j].upper() and (d['block_num'][j], d['par_num'][j], d['line_num'][j]) == (d['block_num'][i], d['par_num'][i], d['line_num'][i]):
            lote = True
            x0 = min(x0, d['left'][j]); y0 = min(y0, d['top'][j]); y1 = max(y1, d['top'][j] + d['height'][j])
        x, y = Mi @ np.array([(x0 + x1) / 2, (y0 + y1) / 2, 1.0])
        out.append(dict(numero=n, texto=t, lote=lote, x=float(x / escala), y=float(y / escala),
                        conf=float(d['conf'][i]), ang=ang, var=var, escala=round(escala, 3),
                        alto=float(d['height'][i] / escala)))
    return out


def main():
    plano = sys.argv[1]; paso = int(sys.argv[2]) if len(sys.argv) > 2 else 15
    t0 = time.time()
    img = cv2.imread(f'datos/{plano}_dibujo.png')
    g = gris_normalizado(img)
    h = alto_caracter(g)
    ruta = f'datos/_g_{plano}.png'; cv2.imwrite(ruta, g)
    s1 = 24.0 / h; escalas = [s1, s1 / 2.5]
    jobs = [(ruta, s, a, v) for s in escalas for a in range(0, 360, paso) for v in ('gris', 'bin')]
    with Pool(min(len(jobs), os.cpu_count())) as p:
        res = p.map(trabajo, jobs)
    det = [x for r in res for x in r]
    seg = time.time() - t0
    json.dump(dict(plano=plano, alto_modal=h, escalas=escalas, paso=paso, segundos=seg,
                   cpus=os.cpu_count(), det=det), open(f'datos/det_{plano}.json', 'w'))
    os.remove(ruta)
    print(plano, 'alto', h, 'escalas', [round(s, 2) for s in escalas], 'det', len(det), f'{seg:.0f}s')


if __name__ == '__main__':
    main()
