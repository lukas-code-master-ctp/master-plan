"""Calibrar una vista contra otra que ya calza.

La calibración con los caminos (calibracion.py) necesita que en la foto los caminos
del KMZ se vean claros. Cuando no se ven, o cuando hay muchas otras cosas claras
cerca (techos, invernaderos), la búsqueda se va al tope y la vista queda sin ajustar.
En el punto II de Lomas de Quillón eso dejaba el dibujo 60 m corrido.

Las vistas del mismo loteo ven el mismo suelo. Así que se proyecta cada foto sobre
el suelo como una ortofoto (la de referencia con su pose ya calibrada, la otra con
la pose que se está probando) y se buscan en una los trozos de la otra. Cada trozo
que coincide dice en qué dirección la vista ve un punto del suelo que la referencia
ya ubicó, y de eso salen la altura del dron, el giro y el error de su GPS. En el
punto II de Quillón deja el dibujo a 3-4 m de Google Earth, que es lo que da la
comparación misma.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Mapping

import cv2
import numpy as np
from PIL import Image
from scipy.optimize import least_squares

from . import geo
from .calibracion import DISTANCIA_MINIMA_M, Ajuste, _proyectar, aplicar
from .proyeccion import ModeloTerreno, Vista

ANCHO_PANORAMA = 7200
RESOLUCION_M = 0.5
# Más lejos, la referencia misma ya está corrida unos metros y el suelo se ve tan de
# lado que un trozo apenas dice algo del desnivel.
ALCANCE_M = 1000.0
# Cada cuántos metros se calcula la cota; entre medio se interpola.
PASO_COTA_M = 10.0
MARGEN_ZONA_M = 50.0
# Los trozos: medio lado del molde, cuánto se lo deja correr y cada cuánto se toma uno.
MEDIO_MOLDE_PX = 48
BUSQUEDA_PX = 160
PASO_MOLDES_PX = 40
CORRELACION_MINIMA = 0.5
# El mejor calce tiene que ganarle al segundo por esto, o el trozo es ambiguo.
VENTAJA_MINIMA = 0.05
COINCIDENCIAS_MINIMAS = 40
# Con más error mediano que esto el cruce no se cree: mejor el otro camino.
ERROR_MAXIMO_M = 15.0
PASADAS = 3
# El GPS del dron se equivoca unos metros; más que esto sería otra cosa.
CORRIMIENTO_MAXIMO_M = 40.0
GIROS = np.round(np.arange(-3.0, 3.0001, 0.1), 3)


@dataclass(frozen=True)
class Cruce:
    ajuste: Ajuste | None
    coincidencias: int = 0
    error_antes_m: float = math.nan
    error_despues_m: float = math.nan
    motivo: str = ""
    # Cuánto se corre la posición del dron, en metros al este y al norte.
    corrimiento: tuple[float, float] = (0.0, 0.0)

    def aplicar(self, vista: Vista) -> Vista:
        """La vista con el ajuste y el corrimiento."""
        lon, lat = geo.desde_metros(self.corrimiento, vista.origen)
        return replace(aplicar(vista, self.ajuste), lon=round(lon, 7), lat=round(lat, 7))


def cargar_panorama(ruta: Path, ancho: int = ANCHO_PANORAMA) -> np.ndarray:
    with Image.open(ruta) as imagen:
        imagen.draft("RGB", (ancho, ancho // 2))
        return np.asarray(imagen.convert("RGB").resize((ancho, ancho // 2), Image.BILINEAR))


def calibrar_contra(vista: Vista, panorama: np.ndarray, cota: ModeloTerreno | None,
                    referencia: Vista, panorama_ref: np.ndarray, cota_ref: ModeloTerreno | None,
                    zona: tuple[float, float, float, float],
                    inclinaciones: Mapping[float, tuple[float, float]]) -> Cruce:
    """El giro, el desnivel y el corrimiento de `vista` que la hacen ver el suelo donde
    lo ve `referencia`.

    El corrimiento es el error del GPS del dron: unos metros que ni el giro ni la
    altura arreglan, porque descalzan más lo cercano que lo lejano. En el punto II de
    Quillón eran ~20 m; sin corregirlos, el mejor ajuste quedaba a 11 m y con ellos
    queda a 2 m.

    `zona` es (oeste, sur, este, norte) en grados: dónde está el loteo. Las
    inclinaciones van atadas al desnivel como en `calibracion.calibrar_altura`.
    """
    este, norte = _rejilla(zona, vista)
    if este.size == 0:
        return Cruce(None, motivo="la zona queda fuera de alcance")
    c_vista = _cotas(este, norte, vista, cota)
    desfase = geo.a_metros(vista.origen, referencia.origen)
    c_ref = _cotas(este, norte, vista, cota_ref, referencia)
    orto_ref = _orto(panorama_ref, referencia, este + desfase[0], norte + desfase[1], c_ref)
    tabla = np.array([(d, *inclinaciones[d]) for d in sorted(inclinaciones)])
    minimo, maximo = float(tabla[0, 0]), float(tabla[-1, 0])

    def con_pose(giro: float, desnivel: float) -> Vista:
        return replace(vista, giro=vista.giro + giro, desnivel=desnivel,
                       inclinacion_este=float(np.interp(desnivel, tabla[:, 0], tabla[:, 1])),
                       inclinacion_norte=float(np.interp(desnivel, tabla[:, 0], tabla[:, 2])))

    # Varias pasadas: la búsqueda de trozos alcanza unas decenas de metros y la vista
    # puede partir más lejos que eso. Cada una parte de lo que encontró la anterior.
    pose = np.array([0.0, vista.desnivel, 0.0, 0.0])   # giro, desnivel, corrimiento E, N
    antes = None
    for pasada in range(PASADAS):
        probada = con_pose(pose[0], pose[1])
        pares = _coincidencias(orto_ref, _orto(panorama, probada, este - pose[2], norte - pose[3], c_vista))
        if len(pares) < COINCIDENCIAS_MINIMAS:
            return Cruce(None, len(pares), motivo=f"solo {len(pares)} coincidencias")
        x, y, dx, dy = pares.T
        # El punto del suelo según la referencia, y en qué dirección lo ve la foto.
        e1, n1, c1 = _en(este, norte, c_vista, x, y)
        e2, n2, c2 = _en(este, norte, c_vista, x + dx, y + dy)
        az_visto, el_visto = _direcciones(probada, e2 - pose[2], n2 - pose[3], c2)

        def residuos(p: np.ndarray) -> np.ndarray:
            giro, desnivel, de, dn = p
            ee, nn = e1 - de, n1 - dn
            az, el = _direcciones(con_pose(giro, desnivel), ee, nn, c1)
            return _residuos_m(az, el, az_visto, el_visto, np.hypot(ee, nn),
                               vista.altura_absoluta - c1 - desnivel)

        def error(p) -> float:
            return float(np.median(np.hypot(*residuos(np.asarray(p, float)).reshape(2, -1))))

        if antes is None:
            antes = error([0.0, vista.desnivel, 0.0, 0.0])
        if pasada == 0:
            # Primero a lo bruto, sin corrimiento: la pose puede partir lejos.
            _, g, d = min((error([g, d, 0.0, 0.0]), float(g), float(d))
                          for d in np.arange(minimo, maximo + 1e-9, 5.0) for g in GIROS[::3])
            pose = np.array([g, d, 0.0, 0.0])
        ajuste = least_squares(residuos, pose, loss="soft_l1", f_scale=5.0,
                               x_scale=[0.5, 10.0, 5.0, 5.0],
                               bounds=([GIROS[0], minimo, -CORRIMIENTO_MAXIMO_M, -CORRIMIENTO_MAXIMO_M],
                                       [GIROS[-1], maximo, CORRIMIENTO_MAXIMO_M, CORRIMIENTO_MAXIMO_M]))
        pose = ajuste.x
    mejor = error(pose)
    giro, desnivel, de, dn = (float(v) for v in pose)

    holgura = 0.05
    if (abs(giro) >= GIROS[-1] - holgura or desnivel <= minimo + 1 or desnivel >= maximo - 1
            or max(abs(de), abs(dn)) >= CORRIMIENTO_MAXIMO_M - 1):
        return Cruce(None, len(pares), antes, mejor, motivo="quedó en el borde de lo probado")
    if mejor > ERROR_MAXIMO_M or mejor >= antes:
        return Cruce(None, len(pares), antes, mejor, motivo=f"queda a {mejor:.0f} m")
    final = con_pose(giro, desnivel)
    ajuste = Ajuste(giro=round(giro, 3),
                    inclinacion_este=round(final.inclinacion_este - vista.inclinacion_este, 3),
                    inclinacion_norte=round(final.inclinacion_norte - vista.inclinacion_norte, 3),
                    desnivel=round(desnivel - vista.desnivel, 1))
    return Cruce(ajuste, len(pares), antes, mejor, corrimiento=(round(de, 1), round(dn, 1)))


def _rejilla(zona, vista: Vista) -> tuple[np.ndarray, np.ndarray]:
    """Los puntos del suelo, en metros respecto de la vista, cada RESOLUCION_M.
    Solo lo que la vista alcanza a ver: el resto de la zona no aporta."""
    oeste, sur, este, norte = zona
    e0, n0 = geo.a_metros((oeste, sur), vista.origen)
    e1, n1 = geo.a_metros((este, norte), vista.origen)
    limite = ALCANCE_M
    e0, e1 = max(e0 - MARGEN_ZONA_M, -limite), min(e1 + MARGEN_ZONA_M, limite)
    n0, n1 = max(n0 - MARGEN_ZONA_M, -limite), min(n1 + MARGEN_ZONA_M, limite)
    if e1 <= e0 or n1 <= n0:
        return np.empty((0, 0)), np.empty((0, 0))
    # Filas de norte a sur, como una imagen.
    return np.meshgrid(np.arange(e0, e1, RESOLUCION_M), np.arange(n1, n0, -RESOLUCION_M))


def _cotas(este, norte, vista: Vista, cota: ModeloTerreno | None, de: Vista | None = None) -> np.ndarray:
    """La cota de cada punto de la rejilla según el modelo de `de` (por omisión, la
    vista). El DEM se consulta cada PASO_COTA_M y entre medio se interpola."""
    if cota is None:
        return np.full(este.shape, (de or vista).terreno_plano(), dtype=np.float32)
    paso = max(1, int(round(PASO_COTA_M / RESOLUCION_M)))
    filas = list(range(0, este.shape[0], paso)) + [este.shape[0] - 1]
    columnas = list(range(0, este.shape[1], paso)) + [este.shape[1] - 1]
    gruesa = np.array([[cota(geo.desde_metros((este[f, c], norte[f, c]), vista.origen))
                        for c in columnas] for f in filas], dtype=np.float32)
    return cv2.resize(gruesa, (este.shape[1], este.shape[0]), interpolation=cv2.INTER_LINEAR)


def _direcciones(vista: Vista, este, norte, cotas):
    return _proyectar(np.arctan2(este, norte), vista.altura_absoluta - cotas - vista.desnivel,
                      np.hypot(este, norte), vista.giro, vista.inclinacion_este, vista.inclinacion_norte)


def _orto(panorama: np.ndarray, vista: Vista, este, norte, cotas) -> np.ndarray:
    """La foto proyectada sobre el suelo; en negro lo que la vista no alcanza."""
    az, el = _direcciones(vista, este, norte, cotas)
    alto, ancho = panorama.shape[:2]
    px = (((az - vista.rumbo0) % 360.0) / 360.0 * ancho).astype(np.float32)
    py = ((90.0 - el) / 180.0 * alto).astype(np.float32)
    gris = cv2.cvtColor(np.ascontiguousarray(panorama), cv2.COLOR_RGB2GRAY)
    gris = cv2.remap(gris, px, py, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP).astype(np.float32)
    gris[gris == 0] = 1.0   # el negro queda para "fuera de alcance"
    distancia = np.hypot(este, norte)
    gris[(distancia < DISTANCIA_MINIMA_M) | (distancia > ALCANCE_M)] = 0.0
    return gris


def _bordes(gris: np.ndarray) -> np.ndarray:
    """Cuánto cambia la imagen en cada punto: se compara eso y no el color, que entre
    dos fotos cambia con el ángulo del sol."""
    suave = cv2.GaussianBlur(gris, (0, 0), 1.5)
    return np.hypot(cv2.Sobel(suave, cv2.CV_32F, 1, 0), cv2.Sobel(suave, cv2.CV_32F, 0, 1))


def _coincidencias(referencia: np.ndarray, objetivo: np.ndarray) -> np.ndarray:
    """(x, y, dx, dy) de cada trozo de la referencia que aparece sin ambigüedad en el
    objetivo, corrido en (dx, dy) píxeles."""
    ga, gb = _bordes(referencia), _bordes(objetivo)
    m, s = MEDIO_MOLDE_PX, BUSQUEDA_PX
    alto, ancho = ga.shape
    pares = []
    for y in range(s + m, alto - s - m, PASO_MOLDES_PX):
        for x in range(s + m, ancho - s - m, PASO_MOLDES_PX):
            if (referencia[y - m:y + m, x - m:x + m] == 0).mean() > 0.05:
                continue
            molde = ga[y - m:y + m, x - m:x + m]
            if molde.std() < 5.0:
                continue
            zona = gb[y - m - s:y + m + s, x - m - s:x + m + s]
            if (objetivo[y - m - s:y + m + s, x - m - s:x + m + s] == 0).mean() > 0.3:
                continue
            mapa = cv2.matchTemplate(zona, molde, cv2.TM_CCOEFF_NORMED)
            j, i = np.unravel_index(np.argmax(mapa), mapa.shape)
            pico = mapa[j, i]
            if pico < CORRELACION_MINIMA:
                continue
            otro = mapa.copy()
            otro[max(0, j - 8):j + 9, max(0, i - 8):i + 9] = -1.0
            if pico - otro.max() < VENTAJA_MINIMA:
                continue
            pares.append((x, y, i - s, j - s))
    return np.array(pares, dtype=np.float64).reshape(-1, 4)


def _en(este, norte, cotas, x, y):
    """Coordenadas del suelo de posiciones (fraccionarias) de la rejilla."""
    paso_e = este[0, 1] - este[0, 0]
    paso_n = norte[1, 0] - norte[0, 0]
    e = este[0, 0] + x * paso_e
    n = norte[0, 0] + y * paso_n
    f = np.clip(np.round(y).astype(int), 0, cotas.shape[0] - 1)
    c = np.clip(np.round(x).astype(int), 0, cotas.shape[1] - 1)
    return e, n, cotas[f, c]


def _residuos_m(az, el, az_visto, el_visto, distancia, caida) -> np.ndarray:
    """Cuánto se corre, en metros sobre el suelo, cada punto entre dónde lo pone la
    pose y dónde lo ve la foto: de lado y a lo largo, uno tras otro."""
    lateral = np.radians((az - az_visto + 180.0) % 360.0 - 180.0) * distancia
    con = np.tan(np.radians(-np.minimum(el, -0.05)))
    visto = np.tan(np.radians(-np.minimum(el_visto, -0.05)))
    return np.concatenate([lateral, caida / con - caida / visto])
