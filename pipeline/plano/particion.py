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
   entre dos regiones es UNA arista, compartida por ambas. Las aristas que siguen
   derecho por un nodo (el borde del loteo que pasa por donde llega una divisoria, en
   T o en cruz) se enderezan juntas, como una sola línea: si no, cada trozo tiene su
   propia recta y la línea queda quebrada en cada nodo. Se endereza (recta si cabe en
   DP_MM, si no Douglas-Peucker con cada tramo ajustado por mínimos cuadrados) y los
   tramos cortos que se apartan poco de un deslinde recto que sigue a ambos lados (el
   eje del texto pegado a la línea, que el watershed reparte) se reemplazan por esa
   recta. Los nodos van a la intersección de sus rectas y `polygonize` da las caras.
   Como todas las caras salen de la misma red, no hay traslapes ni huecos por
   construcción.
5. Borde exterior: lo que no comparte ningún otro lote ni cara sin número, si un rótulo
   pegado lo dejó en dientes, se endereza entre sus vértices compartidos (BORDE_MM).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

import cv2
import numpy as np
import shapely
from shapely.geometry import LineString, Point, Polygon
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
# Deslindes torcidos por el texto pegado a la línea (Caminos de Rapel: el borde norte de
# los lotes 8-03 a 8-05 y el sur de 8-12 a 8-15 en dientes de varios metros). Un tramo
# recto de al menos ANCLA_MM es un apoyo; entre dos apoyos de la misma recta (o que se
# cortan en una esquina), o entre un apoyo y la punta de la línea, lo que se aparta a lo
# más EXCURSION_MM y menos de EXCURSION_FRAC de su propio largo se endereza: en el KMZ de
# Rapel los dientes se apartan del 4 al 7 % de su largo. Un ochavo (≥ 0,35) o un entrante
# de verdad (alto / (2 alto + ancho): 0,25 si es el doble de ancho que de hondo) se
# respetan; se pierde un entrante de menos de EXCURSION_MM que sea casi cinco veces más
# ancho que hondo.
ANCLA_MM = 8.0
EXCURSION_MM = 6.0
EXCURSION_FRAC = 0.15
PUENTE_GRADOS = 10.0   # dos apoyos así de paralelos, con un diente entre medio, se unen por una recta
SIGUE_DERECHO_GRADOS = 20.0  # en un nodo, dos aristas que siguen derecho son la misma línea
# El borde exterior del loteo (lo que no comparte ningún otro lote ni cara sin número)
# no tiene un vecino que lo sostenga: cuando un rótulo va pegado a él, como "Servidumbre
# de Tránsito 8m" bajo los lotes 8-01 y 8-10 de Caminos de Rapel, el watershed lo
# reparte entre las letras y el borde sale en dientes de hasta ~2 mm, sin un tramo
# recto de ANCLA_MM que sirva de apoyo para el enderezado de la red. Ahí, entre vértices
# compartidos (o una esquina), un tramo que zigzaguea y se aparta a lo más BORDE_MM de
# la recta entre sus puntas es esa recta. Que zigzaguee es lo que lo distingue de una
# curva del dibujo (gira siempre al mismo lado), que se respeta.
BORDE_MM = 2.5

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

    caminos = [np.array([(c[1] - 0.5, c[0] - 0.5) for c in cadena], float) for cadena, _ in aristas]
    grupo = _grupos_de_nodos(aristas, nodos)
    tramos, polilineas = [None] * len(aristas), [None] * len(aristas)
    puenteadas = defaultdict(int)
    cadenas = _encadenar(aristas, caminos, grupo, tolerancia, ppmm)

    en_diente = set()

    def enderezar(miembros, cerrada, puntas_libres=(False, False)):
        for i, rs, V, n, dientes in _enderezar_cadena(miembros, cerrada, caminos, tolerancia, ppmm,
                                                       puntas_libres):
            tramos[i], polilineas[i] = rs, V
            puenteadas[i] = n
            for c, d in zip((aristas[i][0][0], aristas[i][0][-1]), dientes):
                if d and c in grupo:
                    en_diente.add(grupo[c])

    def puntas(miembros):
        (i, d), (j, e) = miembros[0], miembros[-1]
        return (aristas[i][0][0 if d else -1], aristas[j][0][-1 if e else 0])

    for miembros, cerrada in cadenas:
        enderezar(miembros, cerrada)
    # Un nodo que quedó dentro de un diente enderezado de otra línea (la divisoria que
    # llega al borde por dentro del texto): la punta de la divisoria se endereza hasta él.
    for miembros, cerrada in cadenas:
        if cerrada:
            continue
        libres = tuple(c in grupo and grupo[c] in en_diente for c in puntas(miembros))
        if any(libres):
            enderezar(miembros, cerrada, libres)
    puenteadas = sum(puenteadas.values())
    rectas = sum(len(rs) == 1 for rs in tramos)

    # Nodos: a la intersección por mínimos cuadrados de las rectas incidentes. Un nodo
    # sobre un tramo enderezado puede estar hasta EXCURSION_MM fuera de su recta. Los
    # nodos de un mismo grupo (unidos por una arista de un par de píxeles: dos líneas que
    # se cruzan no siempre lo hacen en un solo punto de la grieta) van al mismo lugar.
    incidentes = defaultdict(list)
    holgura = defaultdict(lambda: mov_maximo)
    for (cadena, _), rs in zip(aristas, tramos):
        if cadena[0] == cadena[-1] and cadena[0] not in nodos:
            continue
        if cadena[0] in grupo and grupo.get(cadena[-1]) == grupo[cadena[0]] and cadena[0] != cadena[-1]:
            continue
        for c, r in ((cadena[0], rs[0]), (cadena[-1], rs[-1])):
            incidentes[grupo[c]].append(r[:2])
            if r[2]:
                holgura[grupo[c]] = max(mov_maximo, EXCURSION_MM * ppmm)
    miembros_de = defaultdict(list)
    for c in nodos:
        miembros_de[grupo[c]].append(c)
    nuevo = {}
    movidos = 0
    for g, cs in miembros_de.items():
        p0 = np.mean([(c[1] - 0.5, c[0] - 0.5) for c in cs], axis=0)
        ls = incidentes[g]
        if len(ls) >= 2:
            M = np.zeros((2, 2))
            b = np.zeros(2)
            for p, u in ls:
                nn = np.outer((-u[1], u[0]), (-u[1], u[0]))
                M += nn
                b += nn @ p
            if np.linalg.cond(M) < 1e3:
                x = np.linalg.solve(M, b)
                if math.hypot(*(x - p0)) <= holgura[g]:
                    nuevo.update((c, x) for c in cs)
                    movidos += len(cs)
                    continue
        nuevo.update((c, p0) for c in cs)

    lineas, de_lote = [], []
    for (cadena, par), V in zip(aristas, polilineas):
        V = V.copy()
        if cadena[0] in nuevo:
            V[0] = nuevo[cadena[0]]
        if cadena[-1] in nuevo:
            V[-1] = nuevo[cadena[-1]]
        if len(V) >= 2 and np.ptp(V, axis=0).max() > 1e-9:
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
    caras_finales, bordes = enderezar_borde_exterior(list(lotes.values()) + sin_numero, ppmm)
    lotes = dict(zip(lotes, caras_finales[:len(lotes)]))
    sin_numero = caras_finales[len(lotes):]

    estadisticas = dict(
        nodos=len(nodos), aristas=len(aristas), aristas_rectas=int(rectas), nodos_movidos=movidos,
        tramos_enderezados=int(puenteadas), bordes_enderezados=bordes,
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


def enderezar_borde_exterior(caras: list[Polygon], ppmm: float) -> tuple[list[Polygon], int]:
    """Endereza los tramos del borde exterior que torció un rótulo pegado a él (ver
    BORDE_MM). `caras`: los lotes y las caras sin número de una misma red, que comparten
    los vértices de sus deslindes comunes. Devuelve las caras y cuántos tramos enderezó.

    Lo que comparten dos caras no se toca: solo se quitan vértices de una sola cara. Un
    nodo en T (una divisoria que llega al borde) sí se puede correr a la recta del borde
    cuando el texto lo dejó dentro de un diente: si no, el borde enderezado a cada lado
    queda quebrado en él. Se corre en todas sus caras al mismo punto, así que la red sigue
    sin huecos ni traslapes. Cada cambio se revisa (cara válida, sin traslape nuevo con
    otra) y si no pasa se deja como estaba."""
    tol = BORDE_MM * ppmm
    clave = lambda p: (round(float(p[0]), 3), round(float(p[1]), 3))
    pos: dict = {}

    def anillo_de(coords) -> list:
        salida = []
        for p in list(coords)[:-1]:
            k = clave(p)
            pos.setdefault(k, np.array(p[:2], float))
            if not salida or salida[-1] != k:
                salida.append(k)
        if len(salida) > 1 and salida[0] == salida[-1]:
            salida.pop()
        return salida

    exteriores = [anillo_de(c.exterior.coords) for c in caras]
    interiores = [[anillo_de(h.coords) for h in c.interiors] for c in caras]
    pares = lambda a: zip(a, a[1:] + a[:1])
    usos, de = Counter(), defaultdict(set)
    for i, ext in enumerate(exteriores):
        for anillo in (ext, *interiores[i]):
            usos.update(frozenset(e) for e in pares(anillo))
            for k in anillo:
                de[k].add(i)
    poligonos = list(caras)

    def poligono(i):
        return Polygon([pos[k] for k in exteriores[i]], [[pos[k] for k in h] for h in interiores[i]])

    def aplicar(nuevos: dict) -> bool:
        """Acepta las caras nuevas si son válidas y no se meten en otra."""
        if not all(g.is_valid and g.area > 0 for g in nuevos.values()):
            return False
        for i, g in nuevos.items():
            for j, otra in enumerate(poligonos):
                if j == i:
                    continue
                otra_nueva = nuevos.get(j, otra)
                if not shapely.intersects(g, otra_nueva):
                    continue
                if g.intersection(otra_nueva).area > poligonos[i].intersection(otra).area + 1.0:
                    return False
        for i, g in nuevos.items():
            poligonos[i] = g
        return True

    # 1. Los tramos de cada cara, entre vértices compartidos.
    segmentos = []      # (punta, punta, puntos originales, enderezado)
    enderezados = 0
    for i, anillo in enumerate(exteriores):
        n = len(anillo)
        corte = [len(de[k]) >= 2 for k in anillo]
        afuera = [usos[frozenset(e)] == 1 for e in pares(anillo)]
        if not any(afuera) or not any(corte):
            continue        # una cara sola, sin vecinos que fijen las puntas de su borde
        s0 = corte.index(True)
        orden, corte, afuera = anillo[s0:] + anillo[:s0], corte[s0:] + corte[:s0], afuera[s0:] + afuera[:s0]
        tramos, j = [], 0
        while j < n:
            if not afuera[j]:
                j += 1
                continue
            m = j + 1
            while m < n and afuera[m] and not corte[m]:
                m += 1
            tramos.append([orden[t % n] for t in range(j, m + 1)])
            j = m
        for tramo in tramos:
            Q = np.array([pos[k] for k in tramo])
            quedan = _tramo_recto(Q, tol)
            if quedan is not None:
                quitar = set(tramo[1:-1]) - {tramo[t] for t in quedan}
                nuevo = [k for k in exteriores[i] if k not in quitar]
                previo, exteriores[i] = exteriores[i], nuevo
                if aplicar({i: poligono(i)}):
                    enderezados += 1
                    segmentos += [(tramo[a], tramo[b], Q[a:b + 1], b - a >= 2) for a, b in zip(quedan, quedan[1:])]
                    continue
                exteriores[i] = previo
            segmentos += [(a, b, Q[t:t + 2], False) for t, (a, b) in enumerate(zip(tramo, tramo[1:]))]

    # 2. Los nodos en T entre dos tramos que siguen derecho, uno al menos enderezado: a la
    # recta que une las otras puntas, por la dirección de la divisoria que llega.
    incidentes = defaultdict(list)
    for s in segmentos:
        incidentes[s[0]].append(s)
        incidentes[s[1]].append(s)
    vecinos = defaultdict(set)
    for i, ext in enumerate(exteriores):
        for anillo in (ext, *interiores[i]):
            for a, b in pares(anillo):
                vecinos[a].add(b)
                vecinos[b].add(a)

    def destino(v):
        """(cuánto se aparta, a dónde va) el nodo v, o None si no es un nodo en T del borde."""
        ss = incidentes[v]
        if len(ss) != 2 or len(de[v]) < 2 or len(vecinos[v]) != 3 or not (ss[0][3] or ss[1][3]):
            return None
        p, q = (s[1] if s[0] == v else s[0] for s in ss)
        w, = vecinos[v] - {p, q}
        P, Q, V = pos[p], pos[q], pos[v]
        u1, u2 = _unitario(V - P), _unitario(Q - V)
        if math.degrees(math.acos(max(-1.0, min(1.0, float(u1 @ u2))))) > SIGUE_DERECHO_GRADOS:
            return None
        recta = (P, _unitario(Q - P))
        if _distancia_recta(np.concatenate([ss[0][2], ss[1][2]]), recta).max() > tol:
            return None
        x, proyeccion = _cruce((V, _unitario(V - pos[w])), recta), _proyectar(V, recta)
        return float(_distancia_recta(V, recta)), (x if x is not None and math.hypot(*(x - proyeccion)) <= tol
                                                  else proyeccion)

    # El más apartado primero: la recta de un nodo vecino que ya está en el borde es la
    # buena; la de un nodo que va hacia un diente correría a este fuera de su lugar.
    pendientes = set(incidentes)
    while True:
        candidatos = [(d[0], v, d[1]) for v in pendientes if (d := destino(v)) is not None and d[0] > 0.5]
        if not candidatos:
            break
        _, v, x = max(candidatos, key=lambda c: c[0])
        pendientes.discard(v)
        V, pos[v] = pos[v], x
        if not aplicar({i: poligono(i) for i in de[v]}):
            pos[v] = V
    return poligonos, enderezados


def _tramo_recto(Q: np.ndarray, tol: float) -> list[int] | None:
    """Los índices de Q que quedan si el tramo se endereza: sus puntas, o sus puntas y
    una esquina; None si queda como está. Cada recta debe pasar a menos de `tol` de lo
    que reemplaza, y lo que reemplaza zigzaguear (los dientes del texto)."""
    def recto(R):
        if len(R) < 3:
            return True
        cuerda = (R[0], _unitario(R[-1] - R[0]))
        return float(_distancia_recta(R, cuerda).max()) <= tol and _zigzaguea(R)

    if len(Q) < 3:
        return None
    if recto(Q):
        return [0, len(Q) - 1]
    k = 1 + int(np.argmax(_distancia_recta(Q[1:-1], (Q[0], _unitario(Q[-1] - Q[0])))))
    if len(Q) > 3 and recto(Q[:k + 1]) and recto(Q[k:]):
        return [0, k, len(Q) - 1]
    return None


def _zigzaguea(R: np.ndarray) -> bool:
    """¿Gira a un lado y al otro? Una curva gira siempre al mismo."""
    u, v = np.diff(R, axis=0)[:-1], np.diff(R, axis=0)[1:]
    giros = np.degrees(np.arctan2(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0], (u * v).sum(1)))
    return bool(giros.size) and giros.max() > 5 and giros.min() < -5


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


def _grupos_de_nodos(aristas, nodos) -> dict:
    """nodo -> su representante: los nodos unidos por una arista de a lo más dos
    pasos de grieta son el mismo cruce."""
    padre = {c: c for c in nodos}

    def raiz(c):
        while padre[c] != c:
            padre[c] = padre[padre[c]]
            c = padre[c]
        return c

    for cadena, _ in aristas:
        a, b = cadena[0], cadena[-1]
        if len(cadena) <= 3 and a != b and a in padre and b in padre:
            padre[raiz(a)] = raiz(b)
    return {c: raiz(c) for c in nodos}


def _encadenar(aristas, caminos, grupo: dict, tolerancia: float, ppmm: float):
    """Las aristas en cadenas: [(miembros, cerrada)], con miembros = [(i, al_derecho)] en
    orden. En cada nodo se unen, de a pares, las puntas de arista que siguen derecho (a
    menos de SIGUE_DERECHO_GRADOS, y la recta de una pasa por la otra): el borde del
    loteo pasa entero por los nodos en T donde llegan las divisorias; los nodos de un
    mismo `grupo` cuentan como uno. Una arista sola es una cadena de un miembro."""
    ancla = ANCLA_MM * ppmm
    excursion = EXCURSION_MM * ppmm

    def apoyo(P, desde_el_final):
        """La recta (punto, dirección hacia afuera del nodo) de la punta: el primer tramo
        de Douglas-Peucker de al menos ANCLA_MM desde esa punta, o el más largo. Una
        arista de puros dientes cortos (el texto sobre el borde, de nodo a nodo) sigue su
        cuerda si mide al menos la mitad de ANCLA_MM."""
        Q = P[::-1] if desde_el_final else P
        idx = _douglas_peucker(Q, tolerancia)
        pares = list(zip(idx[:-1], idx[1:]))
        largos = [math.hypot(*(Q[e] - Q[s])) for s, e in pares]
        cuerda = math.hypot(*(Q[-1] - Q[0]))
        if len(pares) >= 3 and max(largos) < ancla and cuerda >= ancla / 2:
            return Q[0], _unitario(Q[-1] - Q[0]), cuerda
        k = next((k for k, l in enumerate(largos) if l >= ancla), int(np.argmax(largos)))
        s, e = pares[k]
        punto, u = _recta(Q[s:e + 1]) if e - s >= 2 else (Q[s:e + 1].mean(0), _unitario(Q[e] - Q[s]))
        if np.dot(u, Q[e] - Q[0]) < 0:
            u = -u
        return punto, u, largos[k]

    puntas = defaultdict(list)      # nodo -> [(i, 0 = inicio | 1 = final, punto, dirección)]
    for i, (cadena, _) in enumerate(aristas):
        if cadena[0] == cadena[-1] or len(caminos[i]) < 3:
            continue
        for lado, c in ((0, cadena[0]), (1, cadena[-1])):
            if c in grupo:
                punto, u, _ = apoyo(caminos[i], lado == 1)
                puntas[grupo[c]].append((i, lado, punto, u))
    pareja = {}
    for c, ps in puntas.items():
        nodo = np.array((c[1] - 0.5, c[0] - 0.5))
        candidatos = []
        for a in range(len(ps)):
            for b in range(a + 1, len(ps)):
                (i, li, pi, ui), (j, lj, pj, uj) = ps[a], ps[b]
                if i == j:
                    continue
                angulo = math.degrees(math.acos(max(-1.0, min(1.0, -float(np.dot(ui, uj))))))
                if angulo > SIGUE_DERECHO_GRADOS:
                    continue
                if max(_distancia_recta(nodo, (pi, ui)), _distancia_recta(nodo, (pj, uj))) > excursion:
                    continue
                candidatos.append((angulo, (i, li), (j, lj)))
        for _, x, y in sorted(candidatos):
            if x not in pareja and y not in pareja:
                pareja[x], pareja[y] = y, x

    vistas = set()
    cadenas = []

    def recorrer(i, al_derecho):
        miembros = []
        while True:
            vistas.add(i)
            miembros.append((i, al_derecho))
            siguiente = pareja.get((i, 1 if al_derecho else 0))
            if siguiente is None or siguiente[0] in vistas:
                return miembros, siguiente is not None and siguiente[0] == miembros[0][0]
            i, al_derecho = siguiente[0], siguiente[1] == 0

    # Primero las que tienen una punta libre; lo que queda son anillos.
    for i in range(len(aristas)):
        for lado in (0, 1):
            if i not in vistas and (i, lado) not in pareja:
                miembros, _ = recorrer(i, lado == 0)
                cadenas.append((miembros, False))
    for i, (cadena, _) in enumerate(aristas):
        if i not in vistas:
            if cadena[0] == cadena[-1] and cadena[0] not in grupo:
                vistas.add(i)
                cadenas.append(([(i, True)], True))
            else:
                miembros, cerrada = recorrer(i, True)
                cadenas.append((miembros, cerrada))
    return cadenas


def _enderezar_cadena(miembros, cerrada: bool, caminos, tolerancia: float, ppmm: float,
                      puntas_libres=(False, False)):
    """Endereza una cadena entera y la reparte en sus aristas: [(i, rectas, vértices,
    tramos enderezados)]. Las rectas de cada arista son (punto, dirección, enderezado)
    en su propio sentido, y los vértices van de su primer punto al último."""
    P, rangos = [], []
    for i, al_derecho in miembros:
        Q = caminos[i] if al_derecho else caminos[i][::-1]
        inicio = max(0, len(P) - 1)
        P.extend(Q if not P else Q[1:])
        rangos.append((inicio, len(P) - 1))
    P = np.array(P)
    M = len(P) - 1
    rotacion = 0
    if cerrada and M >= 4:
        # Se parte el anillo al medio de su tramo recto más largo: la esquina queda donde
        # el dibujo la tiene y no donde empieza la grieta.
        idx = _douglas_peucker(P, tolerancia)
        s, e = max(zip(idx[:-1], idx[1:]), key=lambda se: math.hypot(*(P[se[1]] - P[se[0]])))
        rotacion = (s + e) // 2
        P = np.concatenate([P[rotacion:M], P[:rotacion + 1]])
    # Las uniones entre aristas (los nodos), en índices de la cadena girada.
    uniones = sorted({(a - rotacion) % M for a, _ in rangos[1:]} | ({(rangos[0][0] - rotacion) % M} if cerrada else set()))
    segmentos, fijos = _enderezar(P, tolerancia, ppmm, uniones, puntas_libres, anillo=cerrada)
    if cerrada and len(segmentos) >= 2:
        # Las dos mitades del tramo partido son la misma recta.
        a, b = segmentos[0], segmentos[-1]
        if not a[3] and not b[3]:
            recta = _recta(np.concatenate([P[b[0]:b[1] + 1], P[a[0]:a[1] + 1]]))
            segmentos[0] = (a[0], a[1], recta, a[3])
            segmentos[-1] = (b[0], b[1], recta, b[3])
    vertices = _vertices(P, segmentos, fijos, tolerancia, ppmm, cerrada)

    # Índices de la cadena girada, repetidos una vuelta más para las aristas que la cruzan.
    vueltas = 2 if cerrada else 1
    holgura = EXCURSION_MM * ppmm
    segs = [(s + k * M, e + k * M, r, p) for k in range(vueltas) for s, e, r, p in segmentos]
    verts = sorted(((j + k * M, v) for k in range(vueltas) for j, v in vertices), key=lambda jv: jv[0])
    salida = []
    for (i, al_derecho), (a, b) in zip(miembros, rangos):
        if cerrada:
            a, b = (a - rotacion) % M, (a - rotacion) % M + (b - a)
        rs = [(r[0], r[1], p) for s, e, r, p in segs if e > a and s < b]
        V = [v for j, v in verts if a < j < b]
        # ¿La punta cae en medio de un tramo enderezado, o a menos de EXCURSION_MM de una
        # de sus puntas? (un nodo dentro de un diente: el corte de Douglas-Peucker no
        # siempre cae justo en el nodo)
        en_diente = [any(p and s - holgura < x < e + holgura for s, e, _, p in segs) for x in (a, b)]
        if not al_derecho:
            rs, V, en_diente = rs[::-1], V[::-1], en_diente[::-1]
        Q = caminos[i]
        # Un lazo sin nodos cierra en su primer vértice, no en el punto de la grieta.
        V = np.array([*V, V[0]] if cerrada and len(miembros) == 1 and len(V) >= 3 else [Q[0], *V, Q[-1]])
        salida.append((i, rs, V, sum(p for *_, p in rs), en_diente))
    return salida


def _enderezar(P: np.ndarray, tolerancia: float, ppmm: float, uniones=(), puntas_libres=(False, False),
               anillo: bool = False):
    """Douglas-Peucker y una recta por tramo; después, lo que se aparta poco entre apoyos
    rectos se reemplaza por la recta de los apoyos. Devuelve los tramos [(inicio, fin,
    recta, enderezado)] (índices de P, contiguos) y los vértices ya resueltos {índice:
    punto} (las esquinas entre dos apoyos). Un vértice a pocos píxeles de una de las
    `uniones` (índices de los nodos) va al nodo: si no, queda un codo de un píxel
    entre el vértice y el nodo, que se resuelve aparte.

    `puntas_libres` (inicio, fin): la punta llega a un nodo que quedó dentro de un diente
    enderezado de otra línea (el texto pegado al borde); ahí basta con que lo que va del
    último apoyo al nodo mida a lo más EXCURSION_MM. `anillo`: P es un anillo partido al
    medio de un tramo; sus dos mitades juntas cuentan para ser apoyo."""
    ancla = ANCLA_MM * ppmm
    excursion = EXCURSION_MM * ppmm
    uniones = np.asarray(uniones, int)

    def al_nodo(j):
        # Las puntas de P no se mueven: si una arista corta del final de la cadena cabe
        # entera en la distancia de ajuste, la punta saltaría al nodo y esa arista
        # quedaría sin tramos.
        if uniones.size and 0 < j < len(P) - 1:
            u = int(uniones[np.argmin(np.abs(uniones - j))])
            if 0 < u < len(P) - 1 and abs(u - j) <= 3 * tolerancia:
                return u
        return j

    idx = sorted({al_nodo(j) for j in _douglas_peucker(P, tolerancia)})
    segs = [(s, e, _recta_tramo(P[s:e + 1]), False) for s, e in zip(idx[:-1], idx[1:])]
    fijos = {}
    largo = lambda t: math.hypot(*(P[t[1]] - P[t[0]]))
    # 0. Un tramo de pocos píxeles en una esquina (el codo de una línea gruesa) no es un
    # lado: la esquina va al cruce de los dos lados.
    k = 1
    while k < len(segs) - 1:
        a, t, b = segs[k - 1], segs[k], segs[k + 1]
        esquina = abs(float(np.dot(a[2][1], b[2][1]))) < math.cos(math.radians(20))   # no una curva
        x = _cruce(a[2], b[2]) if largo(t) < ancla and esquina else None
        if x is not None and LineString(P[t[0]:t[1] + 1]).distance(Point(x)) < 3 * tolerancia:
            segs[k - 1:k + 1] = [(a[0], t[1], a[2], a[3])]
        else:
            k += 1
    extremos = largo(segs[0]) + largo(segs[-1]) if anillo and len(segs) >= 2 else 0.0

    def es_apoyo(k):
        t = segs[k]
        return t[3] or largo(t) >= ancla or (k in (0, len(segs) - 1) and extremos >= ancla)

    def zigzag(k0, k1):
        # Los dientes del texto giran a un lado y al otro; una curva, siempre al mismo.
        giros = []
        for a, b in zip(segs[k0:k1], segs[k0 + 1:k1 + 1]):
            u, v = P[a[1]] - P[a[0]], P[b[1]] - P[b[0]]
            giros.append(math.degrees(math.atan2(u[0] * v[1] - u[1] * v[0], float(u @ v))))
        return max(giros, default=0) > 5 and min(giros, default=0) < -5

    def se_aparta_poco(desde, hasta, distancias, punta=False):
        Q = P[desde:hasta + 1]
        if len(Q) < 3:
            return False
        recorrido = float(np.hypot(*np.diff(Q, axis=0).T).sum())
        hondo = float(distancias(Q).max())
        return hondo <= excursion and (hondo < EXCURSION_FRAC * recorrido or (punta and recorrido <= excursion))

    # 1. Dos apoyos seguidos de la misma recta, con solo tramos cortos entre medio y
    # cerca de ella. Un tramo largo entre medio (un escalón, la cuerda de una curva) es
    # del dibujo.
    k = 0
    while k < len(segs) - 2:
        if not es_apoyo(k):
            k += 1
            continue
        j = next((j for j in range(k + 1, len(segs)) if es_apoyo(j)), None)
        if j is None:
            break
        A, B = segs[k], segs[j]
        if j >= k + 2 and abs(float(np.dot(A[2][1], B[2][1]))) >= math.cos(math.radians(3)):
            puntos = np.concatenate([P[A[0]:A[1] + 1], P[B[0]:B[1] + 1]])
            recta = _recta(puntos)
            if (_distancia_recta(puntos, recta).max() <= 2 * tolerancia and zigzag(k, j)
                    and se_aparta_poco(A[1], B[0], lambda Q: _distancia_recta(Q, recta))):
                segs[k:j + 1] = [(A[0], B[1], recta, True)]
                continue                      # el tramo unido sigue siendo apoyo
        k = j

    # 2. Las puntas: de la punta al primer apoyo, la recta del apoyo.
    apoyos = [k for k in range(len(segs)) if es_apoyo(k)]
    if apoyos and not anillo:
        k = apoyos[-1]
        A = segs[k]
        if k < len(segs) - 1 and (puntas_libres[1] or zigzag(k, len(segs) - 1)) and se_aparta_poco(
                A[1], len(P) - 1, lambda Q: _distancia_recta(Q, A[2]), puntas_libres[1]):
            segs[k:] = [(A[0], len(P) - 1, A[2], True)]
        k = apoyos[0]
        A = segs[k]
        if k > 0 and (puntas_libres[0] or zigzag(0, k)) and se_aparta_poco(
                0, A[0], lambda Q: _distancia_recta(Q, A[2]), puntas_libres[0]):
            segs[:k + 1] = [(0, A[1], A[2], True)]

    # 3. Dos apoyos que se cortan, con al menos dos tramos cortos entre medio: la
    # esquina va al cruce de sus rectas.
    k = 0
    while k < len(segs) - 1:
        j = next((j for j in range(k + 1, len(segs)) if es_apoyo(j)), None)
        if j is None:
            break
        A, B = segs[k], segs[j]
        x = _cruce(A[2], B[2]) if es_apoyo(k) and j - k >= 3 else None
        if x is not None:
            Q = P[A[1]:B[0] + 1]
            guia = LineString([_proyectar(P[A[1]], A[2]), x, _proyectar(P[B[0]], B[2])])
            m = al_nodo(A[1] + int(np.argmin(np.hypot(*(Q - x).T))))
            if (A[1] < m < B[0] and zigzag(k, j) and LineString(Q).distance(Point(x)) <= excursion
                    and se_aparta_poco(A[1], B[0], lambda Q: shapely.distance(guia, shapely.points(Q)))):
                segs[k:j + 1] = [(A[0], m, A[2], True), (m, B[1], B[2], True)]
                fijos[m] = x
                k += 1
                continue
        k = j

    # 4. Dos apoyos casi paralelos que no son la misma recta ni se cortan cerca (el
    # deslinde cambia un poco de rumbo o se corre bajo el texto, como el borde de 8-04 en
    # Caminos de Rapel): el diente entre ellos va a la recta que une sus puntas.
    k = 0
    while k < len(segs) - 2:
        if not es_apoyo(k):
            k += 1
            continue
        j = next((j for j in range(k + 1, len(segs)) if es_apoyo(j)), None)
        if j is None:
            break
        A, B = segs[k], segs[j]
        if j >= k + 2 and float(np.dot(A[2][1], B[2][1])) >= math.cos(math.radians(PUENTE_GRADOS)):
            a, b = _proyectar(P[A[1]], A[2]), _proyectar(P[B[0]], B[2])
            puente = (a, _unitario(b - a)) if math.hypot(*(b - a)) > 1e-9 else None
            # De la misma recta, lo de entre medio es un escalón del dibujo (el paso 1 no lo
            # enderezó); y el puente sigue el rumbo de los apoyos, hacia adelante (una
            # punta en U no se corta).
            if (puente is not None and _distancia_recta(b, A[2]) > 2 * tolerancia
                    and float(np.dot(puente[1], A[2][1])) >= math.cos(math.radians(PUENTE_GRADOS))
                    and zigzag(k, j)
                    and se_aparta_poco(A[1], B[0], lambda Q: _distancia_recta(Q, puente))):
                segs[k:j + 1] = [A, (A[1], B[0], puente, True), B]
                k += 2
                continue
        k = j
    return segs, fijos


def _vertices(P, segs, fijos, tolerancia, ppmm, cerrada):
    """[(índice, punto)] entre tramos consecutivos: el cruce de sus rectas si queda
    cerca del punto de la grieta, su proyección si son la misma recta."""
    salida = []
    pares = list(zip(segs[:-1], segs[1:]))
    if cerrada and len(segs) >= 2:
        pares.append((segs[-1], segs[0]))
    for a, b in pares:
        j = b[0]
        if j in fijos:
            salida.append((j, fijos[j]))
            continue
        if a[2] is b[2]:
            salida.append((j, _proyectar(P[j], a[2])))
            continue
        cerca = (EXCURSION_MM * ppmm) if (a[3] or b[3]) else 3 * tolerancia
        x = _cruce(a[2], b[2])
        salida.append((j, x if x is not None and math.hypot(*(x - P[j])) < cerca else P[j]))
    return salida


def _recta_tramo(seg: np.ndarray):
    if len(seg) >= 3:
        return _recta(seg)
    return seg.mean(0), _unitario(seg[-1] - seg[0])


def _unitario(v: np.ndarray) -> np.ndarray:
    return v / max(1e-9, math.hypot(*v))


def _distancia_recta(q, recta):
    """Distancia de un punto (o de los puntos de un arreglo N×2) a la recta."""
    p, u = recta
    q = np.asarray(q, float)
    return np.abs(u[0] * (q[..., 1] - p[1]) - u[1] * (q[..., 0] - p[0]))


def _proyectar(q, recta) -> np.ndarray:
    p, u = recta
    return p + float(np.dot(q - p, u)) * u


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
