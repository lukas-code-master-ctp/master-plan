"""Mide las detecciones de ocr.py contra los rotulos leidos a ojo (datos/verdad.json).

R = radio de acierto en px del marco del plano (~0,45 x distancia mediana entre rotulos vecinos).
Las lecturas pasan por seleccion.py (mismas reglas que tendria el producto).
- acierto: lote cuyo numero aparece a < R de su rotulo real.
- recall = aciertos / rotulos; precision = detecciones correctas / detecciones.
- numero errado: deteccion a < R de un rotulo real pero con otro numero.
- ruido: deteccion lejos (> R) de todo rotulo real (cotas, textos, lotes sin verdad).
Uso: python evaluar.py [apoyo_min] [crudo]
"""
import json, sys
import numpy as np
from seleccion import seleccionar

R = {'el_arrayan': 30, 'puente_negro': 150, 'algarrobo': 70, 'hidango': 190, 'curico': 22}


def medir(plano, unico=True, apoyo_min=1):
    V = json.load(open('datos/verdad.json'))[plano]
    D = json.load(open(f'datos/det_{plano}.json'))
    ox, oy = V['offset']; r = R[plano]
    gt = {int(n): (p[0] - ox, p[1] - oy) for n, p in V['rotulos'].items()}
    det, con_lote = seleccionar(D, r, unico=unico, apoyo_min=apoyo_min)
    nums = np.array(list(gt)); P = np.array([gt[n] for n in nums], float)
    aciertos, errores, correctas, erradas, ruido = set(), [], 0, 0, 0
    for d in det:
        dist = np.hypot(P[:, 0] - d['x'], P[:, 1] - d['y'])
        cerca = dist < r
        if d['numero'] in gt and cerca[nums == d['numero']].any():
            correctas += 1; aciertos.add(d['numero'])
            errores.append(float(dist[nums == d['numero']][0]))
        elif cerca.any():
            erradas += 1
        else:
            ruido += 1
    n = len(gt)
    return dict(plano=plano, R=r, lotes=n, aciertos=len(aciertos), recall=len(aciertos) / n,
                detecciones=len(det), correctas=correctas,
                precision=correctas / len(det) if det else 0, erradas=erradas, ruido=ruido,
                err_pos_mediano=float(np.median(errores)) if errores else None,
                segundos=D['segundos'], con_lote=con_lote, alto_modal=D['alto_modal'], paso=D['paso'],
                faltan=sorted(set(gt) - aciertos))


if __name__ == '__main__':
    apoyo = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    unico = not (len(sys.argv) > 2 and sys.argv[2] == 'crudo')
    res = []
    for p in R:
        m = medir(p, unico, apoyo)
        res.append(m)
        print(f"{p:13s} R={m['R']:3d} lotes={m['lotes']:3d} aciertos={m['aciertos']:3d} "
              f"recall={m['recall']:.0%} det={m['detecciones']:4d} prec={m['precision']:.0%} "
              f"erradas={m['erradas']:3d} ruido={m['ruido']:4d} errpos={m['err_pos_mediano']:.1f} "
              f"t={m['segundos']:.0f}s lote={m['con_lote']}")
    json.dump(res, open(f"datos/eval_apoyo{apoyo}_{'unico' if unico else 'crudo'}.json", 'w'), indent=1)
