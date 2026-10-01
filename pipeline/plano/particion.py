"""De la tinta a los lotes: regiones con semilla, red de deslindes y polígonos.

1. Núcleos: un cierre direccional (CLOSE_MM, 18 ángulos) sella los cortes del trazo;
   el fondo que queda, erosionado CORE_R_MM, se parte en núcleos. La erosión también
   separa pasos angostos y franjas de camino de doble línea.
2. Semillas: cada rótulo (número y posición) cae en un núcleo.
   - Núcleo con un rótulo: el núcleo es la semilla.
   - Núcleo con varios (un deslinde cortado): cada rótulo siembra un disco y el
     watershed reparte el núcleo por distancia geodésica, respetando las líneas que
     sí están.
   - Rótulo que cae en el exterior (un hueco en el deslinde del predio): se reintenta
     solo para él con un cierre más largo (×2, ×3, ×4), y si no, un disco.
   Los núcleos sin rótulo son regiones "sin número" (caminos, quebradas, sobrantes).
3. Watershed sobre la tinta suavizada: el límite queda en el eje de la línea. Una
   región sin número interior cuyo límite con un lote casi no tiene tinta (la inventó
   el cierre, no el dibujo) se une a ese lote.
4. Red de deslindes: las grietas entre etiquetas forman una red plana. Cada deslinde
   entre dos regiones es UNA arista, compartida por ambas. Se endereza (recta si cabe
   en DP_MM, si no Douglas-Peucker con cada tramo ajustado por mínimos cuadrados), los
   nodos van a la intersección de sus rectas y `polygonize` da las caras. Como todas
   las caras salen de la misma red, no hay traslapes ni huecos por construcción.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import cv2
import numpy as np
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union
from skimage.segmentation import watershed

from .tinta import Tinta, impar

# Parámetros globales en mm de papel, de la ronda 3 de pruebas (ver `tinta`).
CLOSE_MM = 5.0         # largo del cierre direccional
CORE_R_MM = 1.2        # erosión del fondo para formar núcleos
CORE_MIN_MM2 = 15.0    # área mínima (erosionada) de un núcleo
SEED_R_MM = 3.0        # radio para asignar un rótulo a su núcleo
FUS_DISC_MM = 3.0      # disco de cada rótulo en un núcleo compartido
DISC_MM = 1.5          # disco de un rótulo sin núcleo propio
EXCL_MM = 12.0         # alrededor de un rótulo que cayó en el exterior, el exterior no se siembra
MERGE_INK_FRAC = 0.85  # región sin número cuyo límite con un lote tiene menos tinta firme: se une
BLUR_MM = 0.25         # suavizado de la tinta para el watershed
DP_MM = 0.34           # tolerancia del enderezado (≈ 2 px a 6 px/mm: el ancho de la línea)
NODE_MOV_MM = 0.5      # lo más que se mueve un nodo hacia la intersección de sus rectas

# Etiquetas de la partición: 1 = relleno, 2.. = regiones sin número, LOTE0 + i = la
# semilla i-ésima.
LOTE0 = 100000


@dataclass
class Particion:
    etiquetas: np.ndarray                 # int32, la partición de la imagen de trabajo
    numeros: dict[int, str]               # etiqueta -> número del lote
    estadisticas: dict = field(default_factory=dict)


@dataclass
class Red:
    lotes: dict[str, Polygon]             # número -> polígono, en px de trabajo
    sin_numero: list[Polygon]             # caras interiores que no son de ningún lote
    deslindes: list[LineString]           # aristas que tocan algún lote
    estadisticas: dict = field(default_factory=dict)


def _linea_kernel(largo: int, angulo: float) -> np.ndarray:
    k = np.zeros((largo, largo), np.uint8)
    c = largo // 2
    t = np.deg2rad(angulo)
    cv2.line(k, (int(round(c - c * np.cos(t))), int(round(c - c * np.sin(t)))),
             (int(round(c + c * np.cos(t))), int(round(c + c * np.sin(t)))), 1, 1)
    return k


def particionar(tinta: Tinta, ppmm: float, semillas) -> Particion:
    """`semillas`: [(numero, x, y)] en píxeles de trabajo. Los números no se repiten."""
    numeros = [str(n) for n, _, _ in semillas]
    repetidos = sorted(n for n, c in Counter(numeros).items() if c > 1)
    if repetidos:
        raise ValueError(f"números de lote repetidos en las semillas: {', '.join(repetidos)}")
    rotulos = {i: (float(x), float(y)) for i, (_, x, y) in enumerate(semillas)}
    mm = lambda v: v * ppmm
    lineas, grueso = tinta.lineas, tinta.grueso
    alto, ancho = lineas.shape

    def nucleos(factor):
        largo = impar(mm(CLOSE_MM) * factor)
        base = lineas.astype(np.uint8)
        cerrado = base.copy()
        for angulo in range(0, 180, 10):
            cerrado = np.maximum(cerrado, cv2.morphologyEx(base, cv2.MORPH_CLOSE, _linea_kernel(largo, angulo)))
        fondo = ((cerrado == 0) & ~grueso).astype(np.uint8)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (impar(2 * mm(CORE_R_MM)),) * 2)
        erosionado = cv2.erode(fondo, k)
        erosionado[0, :] = erosionado[-1, :] = erosionado[:, 0] = erosionado[:, -1] = 0
        _, lab, st, _ = cv2.connectedComponentsWithStats(erosionado, connectivity=4)
        es_nucleo = st[:, 4] >= mm(mm(CORE_MIN_MM2))
        es_nucleo[0] = False
        # Núcleos que tocan el borde de la imagen (el exterior), con CORE_R de holgura.
        m = int(mm(CORE_R_MM)) + 2
        borde = set(np.unique(np.concatenate([lab[m, :], lab[-m - 1, :], lab[:, m], lab[:, -m - 1]])).tolist())
        return lab, es_nucleo, borde

    lab, es_nucleo, borde = nucleos(1)
    R = int(round(mm(SEED_R_MM)))
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    disco_r = (yy ** 2 + xx ** 2) <= R * R

    def nucleo_de(x, y):
        xi, yi = int(round(x)), int(round(y))
        if not (R <= xi < ancho - R and R <= yi < alto - R):
            return 0
        ventana = lab[yi - R:yi + R + 1, xi - R:xi + R + 1][disco_r]
        ventana = ventana[es_nucleo[ventana]]
        return int(np.bincount(ventana).argmax()) if ventana.size else 0

    nucleo = {i: nucleo_de(*p) for i, p in rotulos.items()}
    cuenta = Counter(nucleo.values())
    ids_sin_numero = np.zeros(len(es_nucleo), np.int32)
    ids_sin_numero[es_nucleo] = 2 + np.arange(es_nucleo.sum())
    marcas = ids_sin_numero[lab]                     # todo núcleo parte sin número
    marcas[grueso & (marcas == 0)] = 1
    especiales = {}
    # Rótulos cuyo núcleo se escapa al exterior: se reintenta solo para ellos con un
    # cierre más largo.
    rescate = {}
    pendientes = [i for i, c in nucleo.items() if c == 0 or c in borde]
    for factor in (2, 3, 4):
        if not pendientes:
            break
        lab2, es_nucleo2, borde2 = nucleos(factor)
        for i in list(pendientes):
            x, y = rotulos[i]
            xi, yi = int(round(x)), int(round(y))
            ventana = lab2[max(0, yi - R):yi + R + 1, max(0, xi - R):xi + R + 1]
            ventana = ventana[es_nucleo2[ventana]]
            if not ventana.size:
                continue
            c2 = int(np.bincount(ventana).argmax())
            otros = [j for j, (ox, oy) in rotulos.items() if j != i and 0 <= int(oy) < alto
                     and 0 <= int(ox) < ancho and lab2[int(oy), int(ox)] == c2]
            if c2 not in borde2 and not otros:
                # Los índices y no una máscara de la imagen entera por rótulo rescatado.
                rescate[i] = (np.flatnonzero(lab2 == c2), factor)
                pendientes.remove(i)
        del lab2
    for i in nucleo:
        if i in rescate:
            region, factor = rescate[i]
            marcas.flat[region] = LOTE0 + i
            especiales[i] = f"rescate_cierre_x{factor}"
    for i, (x, y) in rotulos.items():
        c = nucleo[i]
        if i in rescate:
            continue
        if c == 0 or c in borde:
            especiales[i] = "disco" + ("_borde" if c in borde else "_sin_nucleo")
            if c in borde:
                # Cerca del rótulo no se siembra el exterior: decide la línea.
                cv2.circle(marcas, (int(round(x)), int(round(y))), int(mm(EXCL_MM)), 0, -1)
            continue
        if cuenta[c] == 1:
            marcas[lab == c] = LOTE0 + i
        else:
            especiales[i] = f"disco_fusion({cuenta[c]})"
            marcas[lab == c] = 0
    # Los discos al final: pisan cualquier otra semilla.
    for i, (x, y) in rotulos.items():
        if i in especiales and especiales[i].startswith("disco"):
            r = FUS_DISC_MM if especiales[i].startswith("disco_fusion") else DISC_MM
            cv2.circle(marcas, (int(round(x)), int(round(y))), max(2, int(mm(r))), LOTE0 + i, -1)
    relieve = cv2.GaussianBlur(lineas.astype(np.float32), (0, 0), max(0.5, mm(BLUR_MM)))
    etiquetas = _inundar(relieve, marcas)
    del relieve, marcas, lab
    fusiones = _fusionar_sin_tinta(etiquetas, lineas & tinta.firme, ppmm)
    n = lambda i: numeros[i]
    estadisticas = dict(
        tramos_pliegue=tinta.pliegues,
        fusiones_sin_tinta=[(r, n(i)) for r, i in fusiones],
        nucleos=int(es_nucleo.sum()),
        semillas=len(rotulos),
        nucleos_con_semilla=len({c for c in nucleo.values() if c}),
        semillas_sin_nucleo=[n(i) for i, c in nucleo.items() if c == 0],
        semillas_en_borde=[n(i) for i, c in nucleo.items() if c in borde and c],
        nucleos_compartidos=[[n(i) for i in nucleo if nucleo[i] == c] for c, v in cuenta.items() if v > 1 and c],
        especiales={n(i): v for i, v in especiales.items()},
    )
    return Particion(etiquetas.astype(np.int32, copy=False), {LOTE0 + i: numeros[i] for i in rotulos},
                     estadisticas)


def _inundar(relieve: np.ndarray, marcas: np.ndarray) -> np.ndarray:
    """El watershed de skimage, sembrando solo el borde de cada marca.

    skimage mete en su cola de prioridad cada píxel marcado (~40 bytes por píxel, y
    la cola crece al doble), y los núcleos marcan casi toda la imagen: en un escaneo
    de 38 Mpx eso son 4 GB. Un píxel marcado sin vecinos libres no inunda nada, así
    que se deja fuera con la máscara y conserva su marca."""
    libre = marcas == 0
    # Vecinos 4-conexos: la conectividad por defecto del watershed.
    cruz = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    activo = cv2.dilate(libre.astype(np.uint8), cruz) > 0
    del libre
    salida = watershed(relieve, marcas, mask=activo)
    np.copyto(salida, marcas, where=~activo)
    return salida


def _fusionar_sin_tinta(ws: np.ndarray, firme: np.ndarray, ppmm: float) -> list[tuple[int, int]]:
    """Une al lote vecino cada región sin número que no toca el borde y cuyo límite
    con ese lote casi no tiene tinta firme. Si hay varios, al del límite con menos
    tinta (mínimo 3 mm de límite común). Modifica `ws`."""
    tinta = cv2.dilate(firme.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    fusiones = []
    for _ in range(4):
        borde = set(np.unique(np.concatenate([ws[0], ws[-1], ws[:, 0], ws[:, -1]])).tolist())
        dv, dh = ws[1:, :] != ws[:-1, :], ws[:, 1:] != ws[:, :-1]
        a = np.concatenate([ws[1:, :][dv], ws[:, 1:][dh]]).astype(np.int64)
        b = np.concatenate([ws[:-1, :][dv], ws[:, :-1][dh]]).astype(np.int64)
        t = np.concatenate([(tinta[1:, :] | tinta[:-1, :])[dv], (tinta[:, 1:] | tinta[:, :-1])[dh]])
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        unicos, inverso = np.unique(lo * 10 ** 7 + hi, return_inverse=True)
        total = np.bincount(inverso)
        con_tinta = np.bincount(inverso, weights=t)
        mejor = {}
        for clave, n, k in zip(unicos.tolist(), total.tolist(), con_tinta.tolist()):
            p, q = clave // 10 ** 7, clave % 10 ** 7
            for r, lote in ((p, q), (q, p)):
                if (2 <= r < LOTE0 and lote >= LOTE0 and r not in borde and n >= 3 * ppmm
                        and k / n < MERGE_INK_FRAC and k / n < mejor.get(r, (0, 2.0))[1]):
                    mejor[r] = (lote, k / n)
        if not mejor:
            break
        tabla = np.arange(ws.max() + 1, dtype=np.int32)
        for r, (lote, _) in mejor.items():
            tabla[r] = lote
            fusiones.append((int(r), int(lote) - LOTE0))
        ws[...] = tabla[ws]
    return fusiones


# ---------------------------------------------------------------------------- red de deslindes
def red_de_deslindes(particion: Particion, ppmm: float) -> Red:
    tolerancia = DP_MM * ppmm
    mov_maximo = NODE_MOV_MM * ppmm
    ws = particion.etiquetas.astype(np.int32).copy()
    alto, ancho = ws.shape
    ws[0, :] = ws[-1, :] = ws[:, 0] = ws[:, -1] = 1
    aristas, nodos = _grietas(ws)

    tramos, polilineas = [], []
    rectas = 0
    for cadena, _ in aristas:
        P = np.array([(c[1] - 0.5, c[0] - 0.5) for c in cadena], float)
        idx = _douglas_peucker(P, tolerancia)
        rs = []
        for s, e in zip(idx[:-1], idx[1:]):
            seg = P[s:e + 1]
            if len(seg) >= 3:
                rs.append(_recta(seg))
            else:
                dv = seg[-1] - seg[0]
                rs.append((seg.mean(0), dv / max(1e-9, math.hypot(*dv))))
        V = [P[0]]
        for k in range(1, len(idx) - 1):
            x = _cruce(rs[k - 1], rs[k])
            V.append(x if x is not None and math.hypot(*(x - P[idx[k]])) < 3 * tolerancia else P[idx[k]])
        V.append(P[-1])
        rectas += len(idx) == 2
        tramos.append(rs)
        polilineas.append(np.array(V))

    # Nodos: a la intersección por mínimos cuadrados de las rectas incidentes.
    incidentes = defaultdict(list)
    for (cadena, _), rs in zip(aristas, tramos):
        if cadena[0] == cadena[-1] and cadena[0] not in nodos:
            continue
        incidentes[cadena[0]].append(rs[0])
        incidentes[cadena[-1]].append(rs[-1])
    nuevo = {}
    movidos = 0
    for c in nodos:
        p0 = np.array((c[1] - 0.5, c[0] - 0.5))
        ls = incidentes[c]
        if len(ls) >= 2:
            M = np.zeros((2, 2))
            b = np.zeros(2)
            for p, u in ls:
                nn = np.outer((-u[1], u[0]), (-u[1], u[0]))
                M += nn
                b += nn @ p
            if np.linalg.cond(M) < 1e3:
                x = np.linalg.solve(M, b)
                if math.hypot(*(x - p0)) <= mov_maximo:
                    nuevo[c] = x
                    movidos += 1
                    continue
        nuevo[c] = p0

    lineas, de_lote = [], []
    for (cadena, par), V in zip(aristas, polilineas):
        V = V.copy()
        if cadena[0] in nuevo:
            V[0] = nuevo[cadena[0]]
        if cadena[-1] in nuevo:
            V[-1] = nuevo[cadena[-1]]
        if len(V) >= 2:
            lineas.append(LineString(V))
            de_lote.append(max(par) >= LOTE0)
    caras = list(polygonize(unary_union(lineas)))
    por_etiqueta = defaultdict(list)
    for cara in caras:
        p = cara.representative_point()
        e = int(ws[min(alto - 1, max(0, int(round(p.y)))), min(ancho - 1, max(0, int(round(p.x))))])
        por_etiqueta[e].append(cara)

    lotes, multicara = {}, {}
    for e, fs in por_etiqueta.items():
        if e < LOTE0 or e not in particion.numeros:
            continue
        numero = particion.numeros[e]
        u = unary_union(fs)
        if u.geom_type == "MultiPolygon":
            multicara[numero] = len(u.geoms)
            u = max(u.geoms, key=lambda g: g.area)
        lotes[numero] = u
    lotes = _rellenar_huecos(lotes)

    original = particion.etiquetas
    afuera = set(np.unique(np.concatenate([original[0], original[-1], original[:, 0], original[:, -1]])).tolist())
    afuera.discard(1)       # el relleno es una sola etiqueta: decide si la cara toca el marco
    sin_numero = _caras_interiores([(e, c) for e, fs in por_etiqueta.items() if e < LOTE0 for c in fs],
                                   list(lotes.values()), afuera, ancho, alto)

    estadisticas = dict(
        nodos=len(nodos), aristas=len(aristas), aristas_rectas=int(rectas), nodos_movidos=movidos,
        caras=len(caras), lotes_multicara=multicara,
        vertices_mediana=float(np.median([len(p.exterior.coords) - 1 for p in lotes.values()])) if lotes else 0.0,
    )
    return Red(lotes, sin_numero, [l for l, d in zip(lineas, de_lote) if d], estadisticas)


def _caras_interiores(caras: list[tuple[int, Polygon]], lotes: list[Polygon], afuera: set[int],
                      ancho: int, alto: int) -> list[Polygon]:
    """Las caras que no son de ningún lote pero quedan dentro del loteo: caminos,
    quebradas, lotes sin rótulo. Es exterior la cara de una región que toca el borde
    de la imagen (`afuera`) y la que toca el marco. Los islotes dentro de un lote
    (texto, achurado) son del lote."""
    marco = Polygon([(-0.5, -0.5), (ancho - 0.5, -0.5), (ancho - 0.5, alto - 0.5), (-0.5, alto - 0.5)]).exterior
    union = unary_union(lotes)
    return [c for e, c in caras
            if e not in afuera and c.distance(marco) >= 1.5 and not union.contains(c.representative_point())]


def _rellenar_huecos(lotes: dict[str, Polygon]) -> dict[str, Polygon]:
    """El anillo exterior de cada lote: los islotes de texto o achurado dentro de un
    lote son del lote. Un hueco ocupado por otro lote sí se respeta, para que los
    lotes no se traslapen."""
    salida = {}
    for numero, p in lotes.items():
        lleno = Polygon(p.exterior)
        huecos = [h for h in p.interiors
                  if any(o is not p and Polygon(h).contains(o.representative_point()) for o in lotes.values())]
        salida[numero] = Polygon(p.exterior, huecos) if huecos else lleno
    return salida


def _grietas(ws: np.ndarray):
    """Grafo de grietas: las fronteras entre píxeles de distinta etiqueta, sobre las
    esquinas de píxel (i, j) = punto (x=j-0,5, y=i-0,5). Nodos donde confluyen 3 o más
    etiquetas; aristas = cadenas de grietas entre nodos, con su par de etiquetas."""
    adj = defaultdict(list)
    ii, jj = np.nonzero(ws[1:, :] != ws[:-1, :])
    for i, j in zip((ii + 1).tolist(), jj.tolist()):
        a, b = ws[i - 1, j], ws[i, j]
        par = (min(a, b), max(a, b))
        adj[(i, j)].append(((i, j + 1), par))
        adj[(i, j + 1)].append(((i, j), par))
    ii, jj = np.nonzero(ws[:, 1:] != ws[:, :-1])
    for i, j in zip(ii.tolist(), (jj + 1).tolist()):
        a, b = ws[i, j - 1], ws[i, j]
        par = (min(a, b), max(a, b))
        adj[(i, j)].append(((i + 1, j), par))
        adj[(i + 1, j)].append(((i, j), par))

    def es_nodo(c):
        return len(adj[c]) != 2 or adj[c][0][1] != adj[c][1][1]

    visitadas = set()
    aristas = []
    for c in list(adj):
        if not es_nodo(c):
            continue
        for vecino, par in adj[c]:
            e = frozenset((c, vecino))
            if e in visitadas:
                continue
            visitadas.add(e)
            cadena = [c, vecino]
            previo, actual = c, vecino
            while not es_nodo(actual):
                siguiente = [q for q, _ in adj[actual] if q != previo][0]
                visitadas.add(frozenset((actual, siguiente)))
                previo, actual = actual, siguiente
                cadena.append(actual)
            aristas.append((cadena, par))
    # Lazos cerrados sin nodos: una región rodeada por una sola etiqueta.
    for c in list(adj):
        for vecino, par in adj[c]:
            e = frozenset((c, vecino))
            if e in visitadas:
                continue
            visitadas.add(e)
            cadena = [c, vecino]
            previo, actual = c, vecino
            while actual != c:
                siguiente = [q for q, _ in adj[actual] if q != previo][0]
                visitadas.add(frozenset((actual, siguiente)))
                previo, actual = actual, siguiente
                cadena.append(actual)
            aristas.append((cadena, par))
    nodos = {c for c in adj if es_nodo(c)}
    return aristas, nodos


def _douglas_peucker(P: np.ndarray, tolerancia: float) -> list[int]:
    """Índices que conserva Douglas-Peucker."""
    conservar = [0, len(P) - 1]
    pila = [(0, len(P) - 1)]
    while pila:
        s, e = pila.pop()
        if e <= s + 1:
            continue
        a, b = P[s], P[e]
        ab = b - a
        largo = math.hypot(*ab)
        seg = P[s + 1:e]
        if largo < 1e-9:
            d = np.hypot(*(seg - a).T)
        else:
            d = np.abs(ab[0] * (seg[:, 1] - a[1]) - ab[1] * (seg[:, 0] - a[0])) / largo
        k = int(np.argmax(d))
        if d[k] > tolerancia:
            m = s + 1 + k
            conservar.append(m)
            pila += [(s, m), (m, e)]
    return sorted(set(conservar))


def _recta(P: np.ndarray):
    """Recta por mínimos cuadrados: (punto, dirección unitaria)."""
    m = P.mean(0)
    _, _, vt = np.linalg.svd(P - m)
    return m, vt[0]


def _cruce(l1, l2):
    (p, u), (q, v) = l1, l2
    den = u[0] * v[1] - u[1] * v[0]
    if abs(den) < math.sin(math.radians(8)):
        return None
    t = ((q[0] - p[0]) * v[1] - (q[1] - p[1]) * v[0]) / den
    return p + t * u
