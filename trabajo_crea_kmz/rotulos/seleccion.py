"""De lecturas crudas de ocr.py a rotulos (numero, x, y, confianza). Reglas GLOBALES:
1. Si el plano rotula con "LOTE" (>= 10 lecturas con LOTE), solo cuentan esas. Si no, solo
   numeros sueltos de alto >= 1,4x el texto modal (descarta cotas y textos chicos).
2. Grupos: mismo numero a < r -> un candidato; apoyo = cuantas pasadas (escala, angulo,
   variante) lo leyeron.
3. Un numero por lugar: candidatos de distinto numero a < r/2 -> gana el de mas apoyo.
4. Un lugar por numero: si un numero sale en varios lugares, gana el de mas apoyo.
   (Se probo puntaje = apoyo x alto del texto: no mejora.)
r es un parametro (en el producto: ~ alto del rotulo x 4; aqui se usa el R de la medicion).
"""
import numpy as np


def seleccionar(D, r, unico=True, apoyo_min=1):
    det = D['det']
    con_lote = sum(d['lote'] for d in det) >= 10
    if con_lote:
        det = [d for d in det if d['lote']]
    else:
        det = [d for d in det if d['alto'] >= 1.4 * D['alto_modal']]
    grupos = []
    for d in sorted(det, key=lambda d: -d['conf']):
        for g in grupos:
            if g['numero'] == d['numero'] and np.hypot(g['x'] - d['x'], g['y'] - d['y']) < r:
                g['pasadas'].add((d['escala'], d['ang'], d.get('var')))
                g['alto'] = max(g['alto'], d['alto'])
                break
        else:
            grupos.append(dict(numero=d['numero'], x=d['x'], y=d['y'], conf=d['conf'], alto=d['alto'],
                               pasadas={(d['escala'], d['ang'], d.get('var'))}))
    for g in grupos:
        g['apoyo'] = len(g.pop('pasadas'))
    grupos = [g for g in grupos if g['apoyo'] >= apoyo_min]
    if not unico:
        return grupos, con_lote
    grupos.sort(key=lambda g: (-g['apoyo'], -g['conf']))
    out = []
    for g in grupos:
        if any(np.hypot(o['x'] - g['x'], o['y'] - g['y']) < r / 2 for o in out):
            continue
        if any(o['numero'] == g['numero'] for o in out):
            continue
        out.append(g)
    return out, con_lote
