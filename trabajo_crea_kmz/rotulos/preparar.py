"""Prepara las imagenes de entrada (fuera de git, en datos/) y la verdad de terreno.

Marco de coordenadas de cada plano = el de la ronda anterior:
- ronda 3 (puente_negro, algarrobo, hidango, curico): imagen cruda embebida de la pagina,
  sin rotar (work/<plano>_raw.png). Rotulos en ese marco.
- el_arrayan: pagina 1 rotada 90 horario, recorte del inset (4450, 2300, 6300, 5000)
  (poc_kmz/work/inset_full.png). Rotulos en el marco del inset.
Se escribe datos/<plano>_dibujo.png = recorte del rectangulo del dibujo con las mascaras
en blanco, y datos/verdad.json con {plano: {offset, rotulos, ...}}.
"""
import json, os, sys
import numpy as np
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
S = os.environ.get('SCRATCH') or sys.argv[1]
sys.path.insert(0, os.path.join(S, 'ronda3_ciega')); sys.path.insert(0, os.path.join(S, 'poc_kmz'))
from entradas import PLANOS
import etiquetas_leidas
os.makedirs('datos', exist_ok=True)
verdad = {}
for k, c in PLANOS.items():
    raw = Image.open(os.path.join(S, 'ronda3_ciega', 'work', f'{k}_raw.png')).convert('RGB')
    a = np.asarray(raw).copy()
    for (x0, y0, x1, y1) in c['mascaras']:
        a[y0:y1, x0:x1] = 255
    x0, y0, x1, y1 = c['rect']
    Image.fromarray(a[y0:y1, x0:x1]).save(f'datos/{k}_dibujo.png')
    verdad[k] = dict(offset=[x0, y0], rotulos={str(n): p for n, p in c['rotulos'].items()},
                     areas={str(n): v for n, v in c.get('areas', {}).items()},
                     cuadricula=c.get('cuadricula'), mascaras=c['mascaras'], rect=c['rect'])
    raw.save(f'datos/{k}_raw.png') if k in ('algarrobo', 'puente_negro') else None
    if k == 'algarrobo':  # cuadro de superficies (su mascara) para tabla.py
        tx0, ty0, tx1, ty1 = c['mascaras'][2]
        raw.crop((tx0, ty0, tx1, ty1)).save('datos/alg_tabla.png')
    print(k, a.shape, len(c['rotulos']))
ins = Image.open(os.path.join(S, 'poc_kmz', 'work', 'inset_full.png')).convert('RGB')
ins.save('datos/el_arrayan_dibujo.png')
verdad['el_arrayan'] = dict(offset=[0, 0], rotulos={str(n): p for n, p in etiquetas_leidas.globales().items()})
print('el_arrayan', ins.size, len(verdad['el_arrayan']['rotulos']))
json.dump(verdad, open('datos/verdad.json', 'w'), indent=0)
