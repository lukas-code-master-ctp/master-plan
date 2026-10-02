"""De la tinta a los lotes: regiones con semilla, red de deslindes y polígonos.

1. Núcleos: un cierre direccional (CLOSE_MM, 18 ángulos) sella los cortes del trazo;
   el fondo que queda, erosionado CORE_R_MM, se parte en núcleos. La erosión también
   separa pasos angostos y franjas de camino de doble línea.
   Antes se borra el texto de los rótulos que pasó por línea (negrita, subrayado):
   en un lote angosto toca los deslindes y lo parte en dos.
2. Semillas: cada rótulo (número y posición) cae en un núcleo (a SEED_R_MM o, si el
   texto tapó el fondo, el núcleo libre más cercano hasta SEED_R_MAX_MM).
   - Núcleo con un rótulo: el núcleo es la semilla.
   - Núcleo con varios (un deslinde cortado): cada rótulo siembra un disco y el
     watershed reparte el núcleo por distancia geodésica, respetando las líneas que
     sí están.
   - Rótulo que cae en el exterior (un hueco en el deslinde del predio): se reintenta
     solo para él con un cierre más largo (×2, ×3, ×4), y si no, un disco.
   Los núcleos sin rótulo son regiones "sin número" (caminos, quebradas, sobrantes).
3. Watershed sobre la tinta suavizada: el límite queda en el eje de la línea. Una
   región sin número interior cuyo límite con un lote casi no tiene tinta (la inventó
   el cierre, no el dibujo, o es el texto del rótulo) se une a ese lote. Salvo si es
   del tamaño de un lote (≥ LOTE_FRAC de la mediana de los lotes con número): es un
   lote cuyo número no se leyó, y queda como cara sin número "de lote" para que la
   loteadora lo numere. Pegarlo al vecino duplica ese lote sin aviso.
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
from skimage.morphology import skeletonize
from skimage.segmentation import watershed

from . import numeros as numeros_lote
from .tinta import Tinta, impar

# Parámetros globales en mm de papel, de la ronda 3 de pruebas (ver `tinta`). Los del
# texto de los rótulos (SEED_R_MAX_MM, ROTULO_MM, FUSION_ROTULO_MM, RECTO_MM) son del set
# de regresión (`pipeline/plano/regresion.py`): arreglan El Arrayán sin mover a los demás.
CLOSE_MM = 5.0         # largo del cierre direccional
CORE_R_MM = 1.2        # erosión del fondo para formar núcleos
CORE_MIN_MM2 = 15.0    # área mínima (erosionada) de un núcleo
SEED_R_MM = 3.0        # radio para asignar un rótulo a su núcleo
SEED_R_MAX_MM = 6.0    # si no hay núcleo a SEED_R_MM, el libre más cercano hasta aquí
ROTULO_MM = 10.0       # trazo que cabe entero a menos de esto de un rótulo es su texto
FUSION_ROTULO_MM = 5.0  # al unir regiones sin número, la tinta a menos de esto del rótulo no cuenta
RECTO_MM = 3.0         # junto a un rótulo, la tinta que no sigue un tramo recto así de largo es letra
FUS_DISC_MM = 3.0      # disco de cada rótulo en un núcleo compartido
DISC_MM = 1.5          # disco de un rótulo sin núcleo propio
EXCL_MM = 12.0         # alrededor de un rótulo que cayó en el exterior, el exterior no se siembra
MERGE_INK_FRAC = 0.85  # región sin número cuyo límite con un lote tiene menos tinta firme: se une
# Lo que no se une aunque el límite no tenga tinta: una región de al menos LOTE_FRAC de
# la mediana de los lotes con número es un lote sin número. En el set de regresión los
# trozos unidos (franjas, restos de texto, bolsillos del cierre) miden ≤ 0,36 de la
# mediana y los lotes sin rótulo de Caminos de Rapel 0,91–1,01. La excepción son las
# mitades de un lote que partió su propio rótulo (El Arrayán: 0,46–0,74): ahí el
# rótulo está sobre el corte, a ≤ 1,5 mm del límite común (en Rapel, a ≥ 3,3 mm), y el
# corte cae entero en la caja de ±FUSION_ROTULO_MM del rótulo (≥ 95 % del límite, de
# 9 a 16 mm de largo). Se piden las dos cosas: un rótulo pegado a un lado largo de un
# lote vecino sin número (lotes angostos) no basta para unirlos. Lo que queda sin
# distinguir es un lado común corto (≲ 10 mm) tapado por el rótulo.
LOTE_FRAC = 0.4
CORTE_ROTULO_MM = 2.0
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
    de_lote: set[int] = field(default_factory=set)   # regiones sin número del tamaño de un lote


@dataclass
class Red:
    lotes: dict[str, Polygon]             # número -> polígono, en px de trabajo
    sin_numero: list[Polygon]             # caras interiores que no son de ningún lote
    deslindes: list[LineString]           # aristas que tocan algún lote
    estadisticas: dict = field(default_factory=dict)
    # Por cara sin número: ¿es un lote sin número (no se unió a su vecino por tamaño)?
    sin_numero_lote: list[bool] = field(default_factory=list)


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
    repetidos = numeros_lote.repetidos(numeros)
    if repetidos:
        raise ValueError(f"números de lote repetidos en las semillas: {', '.join(repetidos)}")
    rotulos = {i: (float(x), float(y)) for i, (_, x, y) in enumerate(semillas)}
    mm = lambda v: v * ppmm
    lineas, grueso, n_rotulos = _sin_rotulos(tinta.lineas, tinta.grueso, list(rotulos.values()), ppmm)
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
    especiales = {}

    def nucleo_de(x, y):
        xi, yi = int(round(x)), int(round(y))
        if not (R <= xi < ancho - R and R <= yi < alto - R):
            return 0
        ventana = lab[yi - R:yi + R + 1, xi - R:xi + R + 1][disco_r]
        ventana = ventana[es_nucleo[ventana]]
        return int(np.bincount(ventana).argmax()) if ventana.size else 0

    nucleo = {i: nucleo_de(*p) for i, p in rotulos.items()}
    # Un rótulo entintado (negrita, subrayado) se cierra como un bloque y tapa el
    # fondo alrededor de su centro: si no hay núcleo a SEED_R_MM, se toma el más
    # cercano hasta SEED_R_MAX_MM que no sea del exterior ni de otro rótulo.
    R2 = int(round(mm(SEED_R_MAX_MM)))
    for i, (x, y) in rotulos.items():
        if nucleo[i]:
            continue
        xi, yi = int(round(x)), int(round(y))
        y0, x0 = max(0, yi - R2), max(0, xi - R2)
        ventana = lab[y0:yi + R2 + 1, x0:xi + R2 + 1]
        tomados = set(nucleo.values()) | borde
        libre = es_nucleo[ventana] & ~np.isin(ventana, list(tomados))
        if libre.any():
            py, px = np.nonzero(libre)
            d2 = (py + y0 - y) ** 2 + (px + x0 - x) ** 2
            k = int(np.argmin(d2))
            if d2[k] <= R2 * R2:
                nucleo[i] = int(ventana[py[k], px[k]])
                especiales[i] = "nucleo_cercano"
    cuenta = Counter(nucleo.values())
    ids_sin_numero = np.zeros(len(es_nucleo), np.int32)
    ids_sin_numero[es_nucleo] = 2 + np.arange(es_nucleo.sum())
    marcas = ids_sin_numero[lab]                     # todo núcleo parte sin número
    marcas[grueso & (marcas == 0)] = 1
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
            # El 0 (fondo erosionado) también toca el margen: sin núcleo no es exterior.
            especiales[i] = "disco" + ("_borde" if c else "_sin_nucleo")
            if c:
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
    fusiones, de_lote = _fusionar_sin_tinta(etiquetas, lineas & tinta.firme, ppmm, rotulos)
    n = lambda i: numeros[i]
    estadisticas = dict(
        tramos_pliegue=tinta.pliegues,
        trazos_de_rotulo=n_rotulos,
        fusiones_sin_tinta=[(r, n(i)) for r, i in fusiones],
        regiones_de_lote=de_lote,
        nucleos=int(es_nucleo.sum()),
        semillas=len(rotulos),
        nucleos_con_semilla=len({c for c in nucleo.values() if c}),
        semillas_sin_nucleo=[n(i) for i, c in nucleo.items() if c == 0],
        semillas_en_borde=[n(i) for i, c in nucleo.items() if c in borde and c],
        nucleos_compartidos=[[n(i) for i in nucleo if nucleo[i] == c] for c, v in cuenta.items() if v > 1 and c],
        especiales={n(i): v for i, v in especiales.items()},
    )
    return Particion(etiquetas.astype(np.int32, copy=False), {LOTE0 + i: numeros[i] for i in rotulos},
                     estadisticas, set(de_lote))


def _sin_rotulos(lineas: np.ndarray, grueso: np.ndarray, rotulos, ppmm: float):
    """Borra el texto de los rótulos. Un rótulo en negrita o subrayado pasa por línea
    (mide más de MIN_COMP_MM) y, si toca un deslinde, parte el lote. En el cuadrado de
    ±ROTULO_MM alrededor de cada rótulo:
    1. se borra la tinta que no está en un tramo recto de RECTO_MM (las letras; los
       deslindes son rectos o curvas suaves a esa escala);
    2. se borran los trazos y rellenos que quedan enteros dentro del cuadrado (el
       subrayado, lo que sobró de las letras). Un deslinde es parte de una red que se
       sale del cuadrado, o encierra el rótulo (un lote chico aislado).
    Devuelve (lineas, grueso, trazos borrados)."""
    if not rotulos:
        return lineas, grueso, 0
    r = int(round(ROTULO_MM * ppmm))
    alto, ancho = lineas.shape
    largo = impar(RECTO_MM * ppmm)
    kernels = [_linea_kernel(largo, a) for a in range(0, 180, 5)]
    cruz3 = np.ones((3, 3), np.uint8)
    disco5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    lineas = lineas.copy()
    cajas = []
    for x, y in rotulos:
        x0, y0 = max(0, int(round(x)) - r), max(0, int(round(y)) - r)
        x1, y1 = min(ancho, int(round(x)) + r + 1), min(alto, int(round(y)) + r + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        cajas.append((x0, y0, x1 - 1, y1 - 1))
        trozo = lineas[y0:y1, x0:x1]
        # Sobre el esqueleto (una letra en negrita no es una mancha donde cabe un
        # tramo recto), engordado 1 px: un trazo a 5° del núcleo sigue siendo recto.
        gordo = cv2.dilate(skeletonize(trozo).astype(np.uint8), cruz3)
        recto = np.zeros_like(gordo)
        for k in kernels:
            recto |= cv2.morphologyEx(gordo, cv2.MORPH_OPEN, k)
        trozo &= cv2.dilate(recto, disco5) > 0
    if not cajas:
        return lineas, grueso, 0
    c = np.asarray(cajas)
    salida, n = [], 0
    for mascara in (lineas, grueso):
        _, etiquetas, st, _ = cv2.connectedComponentsWithStats(mascara.astype(np.uint8), connectivity=8)
        x0, y0 = st[:, 0:1], st[:, 1:2]
        x1, y1 = x0 + st[:, 2:3] - 1, y0 + st[:, 3:4] - 1
        dentro = ((x0 >= c[:, 0]) & (x1 <= c[:, 2]) & (y0 >= c[:, 1]) & (y1 <= c[:, 3])).any(1)
        dentro[0] = False
        _sin_encierros(dentro, etiquetas, st, rotulos, ppmm)
        if mascara is lineas:
            n = int(dentro.sum())
        salida.append(mascara & ~dentro[etiquetas] if dentro.any() else mascara)
    return salida[0], salida[1], n


def _sin_encierros(dentro: np.ndarray, etiquetas: np.ndarray, st: np.ndarray, rotulos, ppmm: float) -> None:
    """Quita de `dentro` los trazos que encierran un rótulo con un hueco de al menos
    CORE_MIN_MM2: son el deslinde de un lote chico aislado (un enclave), no su texto.
    Un círculo o recuadro de rótulo de menos de MIN_COMP_MM ya no llegó como línea.
    Modifica `dentro`."""
    puntos = np.asarray(rotulos, float)
    for k in np.nonzero(dentro)[0]:
        x, y, w, h = (int(v) for v in st[k, :4])
        en = ((puntos[:, 0] >= x) & (puntos[:, 0] < x + w) & (puntos[:, 1] >= y) & (puntos[:, 1] < y + h))
        if not en.any():
            continue
        trozo = (etiquetas[y:y + h, x:x + w] == k).astype(np.uint8)
        contornos, jerarquia = cv2.findContours(trozo, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if jerarquia is None:
            continue
        huecos = [cn for cn, j in zip(contornos, jerarquia[0])
                  if j[3] >= 0 and cv2.contourArea(cn) >= CORE_MIN_MM2 * ppmm * ppmm]
        if any(cv2.pointPolygonTest(cn, (float(px - x), float(py - y)), False) > 0
               for cn in huecos for px, py in puntos[en]):
            dentro[k] = False


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


def _fusionar_sin_tinta(ws: np.ndarray, firme: np.ndarray, ppmm: float,
                        rotulos=None) -> tuple[list[tuple[int, int]], list[int]]:
    """Une al lote vecino cada región sin número que no toca el borde y cuyo límite
    con ese lote casi no tiene tinta firme. Si hay varios, al del límite con menos
    tinta (mínimo 3 mm de límite común). La tinta del límite a menos de ±FUSION_ROTULO_MM
    del rótulo del lote no cuenta: es su texto, que en un lote angosto toca los
    deslindes y lo parte. `rotulos`: {i: (x, y)} del lote LOTE0 + i. Modifica `ws`.

    Una región del tamaño de un lote (`LOTE_FRAC`) no se une, salvo que el rótulo del
    lote esté a menos de CORTE_ROTULO_MM del límite común y su caja cubra la mitad o más
    de ese límite (el texto partió ese lote).
    Devuelve (fusiones [(región, i)], regiones de lote que no se unieron)."""
    tinta = cv2.dilate(firme.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    rotulos = rotulos or {}
    sx = np.full(LOTE0 + len(rotulos) + 1, np.nan)
    sy = sx.copy()
    for i, (x, y) in rotulos.items():
        sx[LOTE0 + i], sy[LOTE0 + i] = x, y
    # El tamaño de un lote: la mediana de las regiones con número, antes de unir nada.
    area0 = np.bincount(ws.ravel())
    con_numero = area0[LOTE0:][area0[LOTE0:] > 0] if len(area0) > LOTE0 else area0[:0]
    tope = LOTE_FRAC * float(np.median(con_numero)) if con_numero.size else np.inf
    retenidas = set()
    fusiones = []
    for _ in range(4):
        borde = set(np.unique(np.concatenate([ws[0], ws[-1], ws[:, 0], ws[:, -1]])).tolist())
        dv, dh = ws[1:, :] != ws[:-1, :], ws[:, 1:] != ws[:, :-1]
        a = np.concatenate([ws[1:, :][dv], ws[:, 1:][dh]]).astype(np.int64)
        b = np.concatenate([ws[:-1, :][dv], ws[:, :-1][dh]]).astype(np.int64)
        t = np.concatenate([(tinta[1:, :] | tinta[:-1, :])[dv], (tinta[:, 1:] | tinta[:, :-1])[dh]])
        if rotulos:
            yv, xv = np.nonzero(dv)
            yh, xh = np.nonzero(dh)
            px, py = np.concatenate([xv, xh + 0.5]), np.concatenate([yv + 0.5, yh])
            lote = np.where(a >= LOTE0, a, b)
            lote = np.where(lote < len(sx), lote, 0)
            cerca = ((np.abs(px - sx[lote]) <= FUSION_ROTULO_MM * ppmm)
                     & (np.abs(py - sy[lote]) <= FUSION_ROTULO_MM * ppmm))
            # Solo un trozo del lote: una región más grande que el doble del lote no es
            # una mitad que el texto separó (el exterior encerrado por otro marco).
            area = np.bincount(ws.ravel())
            region = np.where(a >= LOTE0, b, a)
            cerca &= area[region] <= 2 * area[np.where(a >= LOTE0, a, b)]
            t = t & ~cerca
        else:
            cerca = np.zeros(len(t), bool)
        lo, hi = np.minimum(a, b), np.maximum(a, b)
        unicos, inverso = np.unique(lo * 10 ** 7 + hi, return_inverse=True)
        total = np.bincount(inverso)
        con_tinta = np.bincount(inverso, weights=t)
        de_rotulo = np.bincount(inverso, weights=cerca)
        # Lo más cerca que pasa el límite del rótulo de su lote (inf sin rótulo).
        corte = np.full(len(unicos), np.inf)
        if rotulos:
            distancia = np.nan_to_num(np.hypot(px - sx[lote], py - sy[lote]), nan=np.inf)
            np.minimum.at(corte, inverso, distancia)
        mejor = {}
        for clave, n, k, c, d in zip(unicos.tolist(), total.tolist(), con_tinta.tolist(), de_rotulo.tolist(),
                                     corte.tolist()):
            p, q = clave // 10 ** 7, clave % 10 ** 7
            # Primero el lote cuyo rótulo es la mitad o más del límite común (el texto lo partió).
            orden = (c < n / 2, k / n)
            for r, lote in ((p, q), (q, p)):
                if (2 <= r < LOTE0 and lote >= LOTE0 and r not in borde and n >= 3 * ppmm
                        and k / n < MERGE_INK_FRAC and orden < mejor.get(r, (0, (True, 2.0)))[1]):
                    # Del tamaño de un lote y sin el rótulo encima del corte: un lote sin
                    # número, que no se une (None). "Encima del corte": el centro del
                    # rótulo a menos de CORTE_ROTULO_MM del límite Y el límite casi todo
                    # dentro de la caja del rótulo (c ≥ n/2, el mismo criterio de `orden`).
                    # Un lote vecino de verdad comparte un lado más largo que el texto.
                    texto_corta = d < CORTE_ROTULO_MM * ppmm and c >= n / 2
                    de_lote = area0[r] >= tope and not texto_corta
                    mejor[r] = (None if de_lote else lote, orden)
        for r in [r for r, (lote, _) in mejor.items() if lote is None or r in retenidas]:
            retenidas.add(r)
            del mejor[r]
        if not mejor:
            break
        tabla = np.arange(ws.max() + 1, dtype=np.int32)
        for r, (lote, _) in mejor.items():
            tabla[r] = lote
            fusiones.append((int(r), int(lote) - LOTE0))
        ws[...] = tabla[ws]
    return fusiones, sorted(int(r) for r in retenidas)


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
    interiores = _caras_interiores([(e, c) for e, fs in por_etiqueta.items() if e < LOTE0 for c in fs],
                                   list(lotes.values()), afuera, ancho, alto)
    sin_numero = [c for _, c in interiores]
    sin_numero_lote = [e in particion.de_lote for e, _ in interiores]

    estadisticas = dict(
        nodos=len(nodos), aristas=len(aristas), aristas_rectas=int(rectas), nodos_movidos=movidos,
        caras=len(caras), lotes_multicara=multicara,
        vertices_mediana=float(np.median([len(p.exterior.coords) - 1 for p in lotes.values()])) if lotes else 0.0,
    )
    return Red(lotes, sin_numero, [l for l, d in zip(lineas, de_lote) if d], estadisticas, sin_numero_lote)


def _caras_interiores(caras: list[tuple[int, Polygon]], lotes: list[Polygon], afuera: set[int],
                      ancho: int, alto: int) -> list[tuple[int, Polygon]]:
    """Las caras que no son de ningún lote pero quedan dentro del loteo: caminos,
    quebradas, lotes sin rótulo. Es exterior la cara de una región que toca el borde
    de la imagen (`afuera`) y la que toca el marco. Los islotes dentro de un lote
    (texto, achurado) son del lote."""
    marco = Polygon([(-0.5, -0.5), (ancho - 0.5, -0.5), (ancho - 0.5, alto - 0.5), (-0.5, alto - 0.5)]).exterior
    union = unary_union(lotes)
    return [(e, c) for e, c in caras
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
