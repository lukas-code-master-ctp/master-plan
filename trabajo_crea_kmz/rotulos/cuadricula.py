"""Lee las marcas de cuadricula UTM (E-xxxxxx / N-xxxxxxx) de la pagina completa de Algarrobo
y las compara con la cuadricula leida a ojo (datos/verdad.json). Corre en el contenedor.

Pagina cruda (las marcas estan en el margen, fuera del rectangulo del dibujo), gris
normalizado, escala para texto modal a 24 px, rotaciones 0/90/180/270, gris y Otsu,
psm 11, lista blanca EN0-9-. Una marca es correcta si el valor esta en la cuadricula real
y su posicion cae a < 60 px de la linea que rotula (N: columna x; E: fila y).
"""
import json, re, time, os
from multiprocessing import Pool
import cv2, numpy as np, pytesseract
from comun import gris_normalizado, alto_caracter
from ocr import rotar

CFG = '--oem 1 --psm 11 -c tessedit_char_whitelist=EN0123456789-'
RE = re.compile(r'^([EN])-*(\d{6,7})$')


def pasada(args):
    ruta, esc, ang, var = args
    g = cv2.imread(ruta, cv2.IMREAD_GRAYSCALE)
    g = cv2.resize(g, None, fx=esc, fy=esc, interpolation=cv2.INTER_CUBIC)
    if var == 'bin':
        g = cv2.threshold(cv2.GaussianBlur(g, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    r, M = rotar(g, ang); Mi = cv2.invertAffineTransform(M)
    d = pytesseract.image_to_data(r, config=CFG, output_type=pytesseract.Output.DICT)
    out = []
    for i, t in enumerate(d['text']):
        m = RE.match(t.strip())
        if not m:
            continue
        x, y = Mi @ np.array([d['left'][i] + d['width'][i] / 2, d['top'][i] + d['height'][i] / 2, 1.0])
        out.append((m.group(1), int(m.group(2)), float(x / esc), float(y / esc), float(d['conf'][i])))
    return out


def main():
    t0 = time.time()
    V = json.load(open('datos/verdad.json'))['algarrobo']['cuadricula']
    g = gris_normalizado(cv2.imread('datos/algarrobo_raw.png'))
    esc = 24.0 / alto_caracter(g)
    cv2.imwrite('datos/_g_cuad.png', g)
    jobs = [('datos/_g_cuad.png', esc, a, v) for a in (0, 90, 180, 270) for v in ('gris', 'bin')]
    with Pool(len(jobs)) as p:
        lect = [x for r in p.map(pasada, jobs) for x in r]
    os.remove('datos/_g_cuad.png')
    Ncol = {v: int(k) for k, v in V['N_cols'].items()}; Efil = {v: int(k) for k, v in V['E_filas'].items()}
    marcas = {}
    for eje, val, x, y, c in lect:
        key = (eje, val, round(x / 100), round(y / 100))
        marcas.setdefault(key, (eje, val, x, y, c))
    buenas, malas = set(), []
    for eje, val, x, y, c in marcas.values():
        ok = (eje == 'N' and val in Ncol and abs(x - Ncol[val]) < 60) or \
             (eje == 'E' and val in Efil and abs(y - Efil[val]) < 60)
        (buenas.add((eje, val)) if ok else malas.append((eje, val, int(x), int(y))))
    res = dict(segundos=time.time() - t0, lecturas=len(lect), marcas=len(marcas),
               N_reales=len(Ncol), E_reales=len(Efil),
               N_bien=sorted(v for e, v in buenas if e == 'N'), E_bien=sorted(v for e, v in buenas if e == 'E'),
               malas=malas)
    json.dump(res, open('datos/cuadricula_res.json', 'w'), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == '__main__':
    main()
