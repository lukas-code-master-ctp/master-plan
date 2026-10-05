"""Ubicar en el mapa los lotes digitalizados: de píxeles de página a UTM.

    python -m pipeline.plano georreferenciar <carpeta-del-plano>

Dos caminos, como en el spec:
- **Cuadrícula impresa** (`por_cuadricula`): las líneas UTM del plano con su valor
  (E-…, N-…). Se descartan las que no siguen la progresión regular y se ajusta una
  afín con las intersecciones. Los números impresos pueden estar en WGS84 o en PSAD56:
  `comparar_datum` decide con las anclas.
- **Anclas** (`por_anclas`): pares punto del plano ↔ lon/lat. Similitud (escala,
  giro y traslación) por mínimos cuadrados, con residuo por ancla y marca de las
  atípicas.

Más una traslación de ajuste fino (`ajuste_fino`), en metros.

El huso UTM sale de las anclas (o del EPSG de la cuadrícula): no queda fijo en 19S.

Una `Transformacion` lleva px de página a coordenadas del EPSG con una matriz 3×3
(proyectiva: si el plano es una foto rectificada, incluye la homografía página →
trabajo, y la similitud se ajusta en el plano ya rectificado).

`<carpeta>/georreferencia.json`: `Transformacion.a_dict()` más `datum` (la comparación
WGS84/PSAD56, si hubo cuadrícula y anclas). `<carpeta>/lotes.geojson`: los lotes en
lon/lat, para el mapa de la consola. Las claves de entrada (`anclas`, `cuadricula`,
`ajuste`) están en `pipeline/plano/digitalizar.py`.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, replace
from functools import lru_cache
from itertools import combinations
from pathlib import Path

import numpy as np
from pyproj import Transformer

SALIDA = "georreferencia.json"
GEOJSON = "lotes.geojson"

# Un ancla es atípica si su residuo sin ella (leave-one-out) supera FACTOR_ATIPICA
# veces el residuo mediano de las demás en ese ajuste, y nunca por menos de
# PISO_ATIPICA_M (las anclas de Google Earth se desvían 1–19 m: bajo 4 m es ruido).
FACTOR_ATIPICA = 3.0
PISO_ATIPICA_M = 4.0

# Un valor de cuadrícula fuera de la progresión regular por más de esta fracción del
# paso entre líneas es una lectura equivocada.
TOLERANCIA_PASO = 0.25
# Las dos familias de líneas deben dar la misma escala (px cuadrados).
DIFERENCIA_ESCALA_MAX = 0.03
# Desde aquí un valor de cuadrícula es una N (las E van de 160 000 a 840 000).
NORTE_MINIMO = 1_000_000

WGS84 = 4326

# Las áreas del cuadro de superficies son una escala que no depende de la ubicación: si
# los lotes ubicados miden en mediana otra cosa, la escala de las anclas (o de la
# cuadrícula) está corrida. Se avisa desde ESCALA_CUADRO_MAX de escala (el doble en
# área), con al menos ESCALA_CUADRO_LOTES lotes con área oficial. En el set de
# regresión, con la escala corregida (el what-if) el área mediana de los lotes queda a
# ±0,9 % de la real; en Caminos de Rapel las 4 anclas dan una escala 2,8 % menor que la
# del plano (todas sus combinaciones, entre −2,5 y −3,3 %) y los lotes salen ~5,6 % chicos.
ESCALA_CUADRO_MAX = 0.015
ESCALA_CUADRO_LOTES = 3


# --- husos y datums ------------------------------------------------------------

def huso(lon: float, lat: float) -> int:
    """EPSG del huso UTM WGS84 que contiene el punto (32719 en Chile central)."""
    zona = min(60, max(1, int(math.floor((lon + 180.0) / 6.0)) + 1))
    return (32700 if lat < 0 else 32600) + zona


def zona_de(epsg: int) -> tuple[int, bool, str]:
    """(zona, sur, datum) de un EPSG UTM WGS84 o PSAD56."""
    if 32601 <= epsg <= 32660:
        return epsg - 32600, False, "WGS84"
    if 32701 <= epsg <= 32760:
        return epsg - 32700, True, "WGS84"
    if 24877 <= epsg <= 24882:
        return epsg - 24860, True, "PSAD56"
    if 24817 <= epsg <= 24821:
        return epsg - 24800, False, "PSAD56"
    raise ValueError(f"EPSG {epsg} no es un UTM WGS84 ni PSAD56")


def epsg_de(zona: int, sur: bool, datum: str) -> int | None:
    if datum == "WGS84":
        return (32700 if sur else 32600) + zona
    if sur and 17 <= zona <= 22:
        return 24860 + zona
    if not sur and 17 <= zona <= 21:
        return 24800 + zona
    return None


@lru_cache(maxsize=None)
def _transformador(origen: int, destino: int) -> Transformer:
    return Transformer.from_crs(origen, destino, always_xy=True)


def a_utm(lon, lat, epsg: int):
    return _transformador(WGS84, epsg).transform(np.asarray(lon, float), np.asarray(lat, float))


# --- la transformación ---------------------------------------------------------

@dataclass
class Transformacion:
    metodo: str                 # "anclas" o "cuadricula"
    tipo: str                   # "similitud" o "afin"
    epsg: int
    matriz: np.ndarray          # 3×3: (x, y, 1) de página → (E, N, w) en el EPSG
    parametros: dict = field(default_factory=dict)
    anclas: list = field(default_factory=list)      # residuo por ancla
    cuadricula: dict = field(default_factory=dict)  # líneas usadas y descartadas
    ajuste: tuple = (0.0, 0.0)                      # traslación fina (dE, dN) en m
    avisos: list = field(default_factory=list)

    def a_utm(self, x, y):
        """(E, N) en el EPSG de la transformación. Acepta escalares o arreglos."""
        x, y = np.asarray(x, float), np.asarray(y, float)
        m = self.matriz
        w = m[2, 0] * x + m[2, 1] * y + m[2, 2]
        return (m[0, 0] * x + m[0, 1] * y + m[0, 2]) / w, (m[1, 0] * x + m[1, 1] * y + m[1, 2]) / w

    def a_lonlat(self, x, y):
        return _transformador(self.epsg, WGS84).transform(*self.a_utm(x, y))

    def con_epsg(self, epsg: int) -> "Transformacion":
        """Los mismos números leídos en otro datum (la cuadrícula impresa dice E y N,
        no en qué datum)."""
        return replace(self, epsg=int(epsg), avisos=list(self.avisos))

    def a_dict(self) -> dict:
        return dict(metodo=self.metodo, tipo=self.tipo, epsg=self.epsg,
                    matriz=[[float(v) for v in fila] for fila in self.matriz],
                    parametros=self.parametros, anclas=self.anclas, cuadricula=self.cuadricula,
                    ajuste=dict(de=float(self.ajuste[0]), dn=float(self.ajuste[1])), avisos=list(self.avisos))

    @classmethod
    def desde_dict(cls, d: dict) -> "Transformacion":
        ajuste = d.get("ajuste") or {}
        return cls(metodo=d["metodo"], tipo=d["tipo"], epsg=int(d["epsg"]),
                   matriz=np.array(d["matriz"], float), parametros=d.get("parametros") or {},
                   anclas=d.get("anclas") or [], cuadricula=d.get("cuadricula") or {},
                   ajuste=(float(ajuste.get("de", 0.0)), float(ajuste.get("dn", 0.0))),
                   avisos=list(d.get("avisos") or []))


def ajuste_fino(t: Transformacion, de_m: float, dn_m: float) -> Transformacion:
    """Traslada el resultado (dE, dN) metros: para calzar caminos con la imagen."""
    mover = np.array([[1.0, 0, de_m], [0, 1.0, dn_m], [0, 0, 1.0]])
    return replace(t, matriz=mover @ t.matriz, ajuste=(t.ajuste[0] + de_m, t.ajuste[1] + dn_m),
                   avisos=list(t.avisos))


def _homografia(h) -> np.ndarray:
    return np.eye(3) if h is None else np.asarray(h, float).reshape(3, 3)


def _aplicar(h: np.ndarray, puntos) -> np.ndarray:
    p = np.asarray(puntos, float).reshape(-1, 2)
    q = np.c_[p, np.ones(len(p))] @ h.T
    return q[:, :2] / q[:, 2:3]


# --- anclas --------------------------------------------------------------------

def _similitud(src: np.ndarray, dst: np.ndarray):
    """Mínimos cuadrados w = a·z + b (complejos). `src` con el eje y ya hacia arriba."""
    z = src[:, 0] + 1j * src[:, 1]
    w = dst[:, 0] + 1j * dst[:, 1]
    zm, wm = z.mean(), w.mean()
    a = np.sum(np.conj(z - zm) * (w - wm)) / np.sum(np.abs(z - zm) ** 2)
    b = wm - a * zm
    resto = w - (a * z + b)
    return a, b, np.c_[resto.real, resto.imag]


def por_anclas(anclas, homografia=None, epsg: int | None = None) -> Transformacion:
    """Similitud por mínimos cuadrados desde ≥2 anclas {"x", "y", "lon", "lat"}.

    `x, y` en px de página; `homografia` (página → trabajo) si el plano es una foto
    rectificada: la similitud vale en el plano enderezado, no en la foto.
    """
    anclas = list(anclas)
    if len(anclas) < 2:
        raise ValueError("hacen falta al menos 2 anclas")
    lon = np.array([float(a["lon"]) for a in anclas])
    lat = np.array([float(a["lat"]) for a in anclas])
    epsg = int(epsg or huso(float(lon.mean()), float(lat.mean())))
    h = _homografia(homografia)
    trabajo = _aplicar(h, [(float(a["x"]), float(a["y"])) for a in anclas])
    src = np.c_[trabajo[:, 0], -trabajo[:, 1]]          # y hacia arriba: sin reflejo
    dst = np.c_[a_utm(lon, lat, epsg)]
    if np.ptp(src, axis=0).max() < 1e-9:
        raise ValueError("las anclas están todas en el mismo punto del plano")
    a, b, resto = _similitud(src, dst)
    n = len(anclas)

    residuos = np.hypot(resto[:, 0], resto[:, 1])
    loo, umbral = _sin_cada_una(src, dst, np.arange(n))
    atipicas = np.zeros(n, bool)
    if n == 3:
        atipicas = loo > umbral
    elif n >= 4:
        # De a una: se saca la que, al quitarla, deja a las demás más de acuerdo (la
        # que más contamina); se marca si su residuo sin ella supera el umbral, y se
        # sigue con las que quedan mientras alcancen para controlarse (≥ 4).
        vivas = np.arange(n)
        while len(vivas) >= 4:
            l, u, rms = _sin_cada_una(src, dst, vivas, con_rms=True)
            k = int(np.argmin(rms))
            if l[k] <= u[k]:
                break
            atipicas[vivas[k]] = True
            vivas = np.delete(vivas, k)

    avisos = []
    if n == 2:
        control = "sin control"
        avisos.append("Con 2 anclas no hay control: un ancla mal marcada no se nota. Marca una tercera y una cuarta.")
    elif n == 3 and atipicas.any():
        # Con 3 anclas, dos de ellas fijan la similitud exacta y la tercera es el único
        # control: un error en cualquiera reparte el desacuerdo entre las tres.
        control = "inconsistente"
        avisos.append("Las 3 anclas no calzan entre sí y con 3 no se sabe cuál está mal:"
                      " revisa las marcadas o marca una cuarta.")
    else:
        control = "atipicas" if atipicas.any() else "ok"
        if atipicas.any():
            avisos.append("Anclas atípicas (quítalas o vuelve a marcarlas): "
                          + ", ".join(_nombre(anclas[i], i) for i in np.flatnonzero(atipicas)))

    filas = []
    for i, ancla in enumerate(anclas):
        fila = dict(nombre=_nombre(ancla, i), x=float(ancla["x"]), y=float(ancla["y"]),
                    lon=float(lon[i]), lat=float(lat[i]),
                    de=round(float(resto[i, 0]), 3), dn=round(float(resto[i, 1]), 3),
                    residuo_m=round(float(residuos[i]), 3))
        if n >= 3:
            fila.update(residuo_sin_ella_m=round(float(loo[i]), 3), umbral_m=round(float(umbral[i]), 3),
                        atipica=bool(atipicas[i]))
        filas.append(fila)

    s = np.array([[a.real, a.imag, b.real], [a.imag, -a.real, b.imag], [0.0, 0.0, 1.0]])
    parametros = dict(escala_m_px=float(abs(a)), rotacion_grados=float(math.degrees(math.atan2(a.imag, a.real))),
                      n_anclas=n, control=control,
                      rms_m=float(np.sqrt(np.mean(residuos ** 2))) if n >= 3 else None)
    return Transformacion("anclas", "similitud", epsg, s @ h, parametros, filas, avisos=avisos)


def _sin_cada_una(src, dst, indices, con_rms=False):
    """Para cada ancla de `indices`: su residuo con la similitud ajustada sin ella
    (leave-one-out) y el umbral de atípica (FACTOR × residuo mediano de las demás en
    ese ajuste, con piso). Con `con_rms`, también el RMS de las demás."""
    n = len(indices)
    loo, umbral, rms = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan)
    if n < 3:
        return (loo, umbral, rms) if con_rms else (loo, umbral)
    for j, i in enumerate(indices):
        otras = indices[indices != i]
        a, b, r = _similitud(src[otras], dst[otras])
        loo[j] = abs(complex(*dst[i]) - (a * complex(*src[i]) + b))
        distancias = np.hypot(r[:, 0], r[:, 1])
        umbral[j] = max(FACTOR_ATIPICA * float(np.median(distancias)), PISO_ATIPICA_M)
        rms[j] = float(np.sqrt(np.mean(distancias ** 2)))
    return (loo, umbral, rms) if con_rms else (loo, umbral)


def _nombre(ancla: dict, i: int) -> str:
    return str(ancla.get("nombre") or f"ancla {i + 1}")


# --- cuadrícula ----------------------------------------------------------------

@dataclass
class _Linea:
    familia: str                 # "verticales" u "horizontales"
    valor: float
    posicion: float              # x de la vertical / y de la horizontal, al medio de la hoja
    segmento: tuple | None       # ((x, y), (x, y)) si se detectó la línea
    valida: bool = True
    usada: bool = False
    motivo: str = ""


def _lineas(marcas: dict) -> list[_Linea]:
    salida = []
    for familia, eje in (("verticales", 0), ("horizontales", 1)):
        for m in marcas.get(familia) or []:
            if m.get("valor") is None:
                continue
            if m.get("p") is not None and m.get("q") is not None:
                p, q = (float(m["p"][0]), float(m["p"][1])), (float(m["q"][0]), float(m["q"][1]))
                salida.append(_Linea(familia, float(m["valor"]), (p[eje] + q[eje]) / 2, (p, q),
                                     bool(m.get("valida", True))))
            else:
                salida.append(_Linea(familia, float(m["valor"]), float(m["x" if eje == 0 else "y"]), None))
    return salida


def _modelos(lineas: list[_Linea]):
    """Candidatos valor = s·posición + t, uno por par de líneas, con sus inliers."""
    pos = np.array([l.posicion for l in lineas])
    val = np.array([l.valor for l in lineas])
    difs = np.diff(np.unique(val))
    tolerancia = max(TOLERANCIA_PASO * float(np.median(difs)), 1.0) if len(difs) else 1.0
    modelos = []
    for i, j in combinations(range(len(lineas)), 2):
        if abs(pos[j] - pos[i]) < 1e-6 or val[j] == val[i]:
            continue
        s = (val[j] - val[i]) / (pos[j] - pos[i])
        dentro = np.abs(val - (s * pos + val[i] - s * pos[i])) < tolerancia
        # se reajusta con los inliers y se vuelve a contar
        s, t = np.polyfit(pos[dentro], val[dentro], 1)
        dentro = np.abs(val - (s * pos + t)) < tolerancia
        modelos.append((int(dentro.sum()), float(s), dentro))
    return modelos


def _progresion(v: list[_Linea], h: list[_Linea]):
    """Los inliers de cada familia. Gana el par de modelos con más líneas; a igualdad,
    el que da la misma escala en las dos direcciones (px cuadrados)."""
    mv, mh = _modelos(v), _modelos(h)
    if not mv or not mh:
        raise ValueError("la cuadrícula necesita al menos 2 líneas con valores distintos en cada dirección")
    mejor = max(((a, b) for a in mv for b in mh),
                key=lambda par: (par[0][0] + par[1][0], -abs(math.log(abs(par[0][1]) / abs(par[1][1])))))
    return mejor[0][2], mejor[1][2]


def _interseccion(s1, s2):
    (x1, y1), (x2, y2) = s1
    (x3, y3), (x4, y4) = s2
    d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    a, b = x1 * y2 - y1 * x2, x3 * y4 - y3 * x4
    return (a * (x3 - x4) - (x1 - x2) * b) / d, (a * (y3 - y4) - (y1 - y2) * b) / d


def por_cuadricula(marcas: dict, epsg: int = 32719, homografia=None) -> Transformacion:
    """Afín desde la cuadrícula UTM impresa.

    `marcas`: {"verticales": [...], "horizontales": [...]}, cada línea con "valor" y,
    o bien su posición aproximada ("x" las verticales, "y" las horizontales), o bien
    la recta detectada ("p", "q": extremos en px de página, "valida"). Qué familia
    lleva E y cuál N se deduce de los valores (en un plano girado las verticales
    pueden ser N). Con las rectas, la afín se ajusta en sus intersecciones y mide el
    giro de la hoja; con solo posiciones, se supone la hoja sin giro.
    """
    lineas = _lineas(marcas)
    avisos = []
    for l in lineas:
        if not l.valida:
            l.motivo = "la línea no se encontró bien en la imagen"
    buenas = [l for l in lineas if l.valida]
    v = [l for l in buenas if l.familia == "verticales"]
    h = [l for l in buenas if l.familia == "horizontales"]
    dentro_v, dentro_h = _progresion(v, h)
    for familia, dentro in ((v, dentro_v), (h, dentro_h)):
        for l, ok in zip(familia, dentro):
            l.usada = bool(ok)
            if not ok:
                l.motivo = "el valor no sigue la progresión de las demás líneas"
    v = [l for l in v if l.usada]
    h = [l for l in h if l.usada]
    if len(v) < 2 or len(h) < 2:
        raise ValueError("quedan menos de 2 líneas válidas en una dirección de la cuadrícula")
    descartadas = [l for l in lineas if not l.usada]
    if descartadas:
        avisos.append("Líneas de cuadrícula descartadas: "
                      + ", ".join(f"{l.familia[:-2]} {l.valor:.0f} ({l.motivo})" for l in descartadas))

    ejes = {}
    for nombre, familia in (("verticales", v), ("horizontales", h)):
        ejes[nombre] = "N" if np.median([l.valor for l in familia]) >= NORTE_MINIMO else "E"
    if ejes["verticales"] == ejes["horizontales"]:
        raise ValueError(f"las dos direcciones de la cuadrícula traen valores {ejes['verticales']}:"
                         " una debe ser E y la otra N")

    hm = _homografia(homografia)
    con_rectas = all(l.segmento is not None for l in v + h)
    if con_rectas:
        puntos, destino = [], []
        for lv in v:
            for lh in h:
                puntos.append(_interseccion(lv.segmento, lh.segmento))
                valores = {ejes["verticales"]: lv.valor, ejes["horizontales"]: lh.valor}
                destino.append((valores["E"], valores["N"]))
        src = _aplicar(hm, puntos)
        dst = np.array(destino)
        a = np.c_[src, np.ones(len(src))]
        m, *_ = np.linalg.lstsq(a, dst, rcond=None)          # 3×2
        resto = dst - a @ m
        afin = np.r_[m.T, [[0.0, 0.0, 1.0]]]
        residuos = np.hypot(resto[:, 0], resto[:, 1])
        n_puntos = len(src)
    else:
        if homografia is not None:
            avisos.append("Con solo la posición de las líneas no se corrige la perspectiva de la foto.")
        hm = np.eye(3)
        afin = np.zeros((3, 3))
        afin[2, 2] = 1.0
        resto_lineas = []
        for nombre, familia, coord in (("verticales", v, 0), ("horizontales", h, 1)):
            pos = np.array([l.posicion for l in familia])
            val = np.array([l.valor for l in familia])
            s, t = np.polyfit(pos, val, 1)
            fila = 0 if ejes[nombre] == "E" else 1
            afin[fila, coord], afin[fila, 2] = s, t
            resto_lineas.extend(val - (s * pos + t))
        residuos = np.abs(np.array(resto_lineas))
        n_puntos = len(residuos)
        avisos.append("Sin las líneas detectadas no se mide el giro de la hoja: se supone derecha.")

    parametros = dict(_parametros_afin(afin[:2, :2]), n_lineas=len(v) + len(h), n_puntos=n_puntos,
                      rms_m=float(np.sqrt(np.mean(residuos ** 2))), maximo_m=float(residuos.max()),
                      ejes=ejes)
    if abs(parametros["escala_x_m_px"] / parametros["escala_y_m_px"] - 1) > DIFERENCIA_ESCALA_MAX:
        avisos.append(f"Las dos direcciones de la cuadrícula dan escalas distintas"
                      f" ({parametros['escala_x_m_px']:.4f} y {parametros['escala_y_m_px']:.4f} m/px):"
                      " revisa los valores leídos.")
    informe = dict(lineas=[dict(familia=l.familia, valor=l.valor, posicion=round(l.posicion, 2), usada=l.usada,
                                motivo=l.motivo) for l in lineas])
    return Transformacion("cuadricula", "afin", int(epsg), afin @ hm, parametros, cuadricula=informe, avisos=avisos)


def _parametros_afin(l: np.ndarray) -> dict:
    """Escala por eje, giro y cizalle de la parte lineal (x, y de página → E, N),
    leída con el eje y hacia arriba."""
    f = l @ np.diag([1.0, -1.0])
    sx, sy = math.hypot(f[0, 0], f[1, 0]), math.hypot(f[0, 1], f[1, 1])
    rx = math.degrees(math.atan2(f[1, 0], f[0, 0]))
    ry = math.degrees(math.atan2(-f[0, 1], f[1, 1]))
    return dict(escala_x_m_px=sx, escala_y_m_px=sy, rotacion_grados=rx, cizalle_grados=ry - rx)


def comparar_datum(t: Transformacion, anclas) -> dict:
    """¿En qué datum y huso están los números de la cuadrícula? Se prueban WGS84 y PSAD56
    en el huso de `t` y en los vecinos (un predio junto a los 72° O puede venir impreso
    en el huso del otro lado), y gana el que deja las anclas más cerca. Concluyente si
    el segundo queda al menos 3 veces más lejos: el corrimiento entre datums (~400 m en
    Chile) y el de huso (cientos de km) son mucho mayores que el error de un ancla
    (1–19 m)."""
    anclas = list(anclas)
    zona, sur, _ = zona_de(t.epsg)
    referencia = epsg_de(zona, sur, "WGS84")
    lon = np.array([float(a["lon"]) for a in anclas])
    lat = np.array([float(a["lat"]) for a in anclas])
    real = np.c_[a_utm(lon, lat, referencia)]
    x = np.array([float(a["x"]) for a in anclas])
    y = np.array([float(a["y"]) for a in anclas])
    candidatos = []
    for z, datum in ((z, datum) for z in (zona, zona - 1, zona + 1) for datum in ("WGS84", "PSAD56")):
        epsg = epsg_de(z, sur, datum) if 1 <= z <= 60 else None
        if epsg is None:
            continue
        plo, pla = t.con_epsg(epsg).a_lonlat(x, y)
        d = real - np.c_[a_utm(plo, pla, referencia)]          # ancla − cuadrícula
        media = d.mean(axis=0)
        candidatos.append(dict(datum=datum, epsg=epsg, huso=f"{z}{'S' if sur else 'N'}",
                               distancia_rms_m=float(np.sqrt(np.mean((d ** 2).sum(1)))),
                               desplazamiento_medio_m=dict(de=float(media[0]), dn=float(media[1]),
                                                           d=float(np.hypot(*media))),
                               dispersion_m=float(np.sqrt(np.mean(((d - media) ** 2).sum(1))))))
    candidatos.sort(key=lambda c: c["distancia_rms_m"])
    concluyente = len(candidatos) < 2 or candidatos[1]["distancia_rms_m"] >= 3 * candidatos[0]["distancia_rms_m"]
    return dict(elegido=candidatos[0]["epsg"], datum=candidatos[0]["datum"], huso=candidatos[0]["huso"],
                concluyente=bool(concluyente),
                n_anclas=len(anclas), candidatos=candidatos)


# --- la escala contra el cuadro de superficies -----------------------------------

def escala_contra_cuadro(digitalizado: dict, t: Transformacion) -> dict | None:
    """Los lotes ubicados con `t` contra su área del cuadro de superficies
    (`area_oficial`): {lotes, area_pct, escala_pct}, con la mediana del cociente de
    áreas y la escala que implica (su raíz). None si hay menos de ESCALA_CUADRO_LOTES
    lotes con área oficial."""
    from .salida import lotes_utm

    oficiales = {str(l["numero"]): float(l["area_oficial"]) for l in digitalizado.get("lotes") or []
                 if l.get("area_oficial")}
    if len(oficiales) < ESCALA_CUADRO_LOTES:
        return None
    cocientes = [p.area / oficiales[n] for n, p in lotes_utm(digitalizado, t) if n in oficiales]
    mediana = float(np.median(cocientes))
    return dict(lotes=len(cocientes), area_pct=round(100 * (mediana - 1), 2),
                escala_pct=round(100 * (math.sqrt(mediana) - 1), 2))


def _aviso_escala(escala: dict, metodo: str) -> str:
    coma = lambda v: f"{abs(v):.1f}".replace(".", ",")
    area, factor = escala["area_pct"], escala["escala_pct"]
    origen = "las anclas" if metodo == "anclas" else "la cuadrícula"
    revisar = ("Revisa las anclas: márcalas en puntos que se vean igual en el plano y en la imagen"
               " (esquinas de deslinde, cruces de caminos), lo más separadas posible."
               if metodo == "anclas" else "Revisa los valores de la cuadrícula.")
    return (f"Los lotes miden un {coma(area)} % {'menos' if area < 0 else 'más'} que en el cuadro de superficies"
            f" (mediana de {escala['lotes']} lotes): la escala de {origen} parece {coma(factor)} %"
            f" {'menor' if factor < 0 else 'mayor'} que la del plano. {revisar}")


# --- el paso completo ----------------------------------------------------------

def _marcas(entradas: dict, detectada: dict | None, avisos: list) -> dict:
    """Las rectas que detectó `digitalizar`, con los valores de `entradas.json` (la
    loteadora puede corregir un valor leído sin volver a digitalizar). Si cambiaron
    las líneas, se usan las posiciones aproximadas."""
    if not entradas:
        return {}
    familias = ("verticales", "horizontales")
    if detectada and all(len(detectada.get(f) or []) == len(entradas.get(f) or []) for f in familias):
        return {f: [dict(d, valor=e.get("valor")) for d, e in zip(detectada[f], entradas[f])] for f in familias}
    if detectada:
        avisos.append("Las líneas de la cuadrícula cambiaron desde la digitalización: se usa su posición"
                      " aproximada. Digitaliza de nuevo para medir el giro de la hoja.")
    return {f: list(entradas.get(f) or []) for f in familias}


def georreferenciar(carpeta: Path, avance=print) -> Transformacion:
    from .digitalizar import SALIDA as DIGITALIZADO, escribir_json, leer_entradas
    from .salida import geojson

    carpeta = Path(carpeta)
    entradas = leer_entradas(carpeta)
    ruta = carpeta / DIGITALIZADO
    if not ruta.is_file():
        raise FileNotFoundError(f"falta {DIGITALIZADO}: primero hay que digitalizar el plano")
    digitalizado = json.loads(ruta.read_text(encoding="utf-8"))
    trabajo = digitalizado.get("trabajo") or {}
    # La homografía solo cambia algo si la foto se rectificó; en un recorte es una
    # escala y una traslación, que la similitud absorbe igual.
    homografia = trabajo.get("homografia") if trabajo.get("modo") == "perspectiva" else None
    anclas = entradas.get("anclas") or []
    cuadricula = entradas.get("cuadricula") or {}
    avisos = []

    t = None
    datum = None
    error_cuadricula = ""
    marcas = _marcas(cuadricula, digitalizado.get("cuadricula"), avisos)
    if cuadricula and any(m.get("valor") is not None for f in ("verticales", "horizontales")
                          for m in marcas.get(f) or []):
        epsg = cuadricula.get("epsg") or (huso(np.mean([a["lon"] for a in anclas]), np.mean([a["lat"] for a in anclas]))
                                          if anclas else 32719)
        zona_de(epsg)           # un EPSG que no es UTM WGS84 ni PSAD56 es un error de la entrada
        try:
            t = por_cuadricula(marcas, epsg, homografia)
        except ValueError as e:
            error_cuadricula = str(e)
            avisos.append(f"No se pudo usar la cuadrícula ({e}); se usan las anclas.")
            avance(f"Cuadrícula: no sirve ({e})")
        else:
            p = t.parametros
            avance(f"Cuadrícula: {p['n_lineas']} líneas, {p['n_puntos']} puntos, residuo {p['rms_m']:.2f} m"
                   f" (máx. {p['maximo_m']:.2f} m), giro {p['rotacion_grados']:.3f}°, EPSG:{t.epsg}")
            if anclas:
                datum = comparar_datum(t, anclas)
                for c in datum["candidatos"][:3]:
                    avance(f"Datum {c['datum']} {c['huso']}: anclas a {c['distancia_rms_m']:.1f} m de la cuadrícula")
                if datum["elegido"] != t.epsg and datum["concluyente"] and not cuadricula.get("epsg"):
                    t = t.con_epsg(datum["elegido"])
                    t.avisos.append(f"Las anclas indican que la cuadrícula está en {datum['datum']} huso"
                                    f" {datum['huso']} (EPSG:{datum['elegido']}).")
                elif not datum["concluyente"]:
                    t.avisos.append("Las anclas no distinguen el datum de la cuadrícula: se queda"
                                    f" EPSG:{t.epsg}. Revisa las anclas.")
            elif not cuadricula.get("epsg"):
                t.avisos.append(f"Sin anclas no se comprueba el datum: se supone EPSG:{t.epsg} (WGS84).")
    if t is None:
        if len(anclas) < 2:
            raise ValueError("para ubicar el plano hacen falta al menos 2 anclas o la cuadrícula con sus valores"
                             + (f" (la cuadrícula no sirve: {error_cuadricula})" if error_cuadricula else ""))
        t = por_anclas(anclas, homografia)
        p = t.parametros
        avance(f"Anclas: {p['n_anclas']}, similitud {p['escala_m_px']:.4f} m/px, giro {p['rotacion_grados']:.2f}°,"
               f" EPSG:{t.epsg}" + (f", residuo {p['rms_m']:.1f} m" if p["rms_m"] is not None else ", sin control"))
        for a in t.anclas:
            if "residuo_sin_ella_m" in a:
                avance(f"  {a['nombre']}: residuo {a['residuo_m']:.1f} m, sin ella {a['residuo_sin_ella_m']:.1f} m"
                       + (" ATÍPICA" if a["atipica"] else ""))
    escala = escala_contra_cuadro(digitalizado, t)
    if escala:
        t.parametros["escala_cuadro"] = escala
        avance(f"Cuadro de superficies: {escala['lotes']} lotes, área mediana {escala['area_pct']:+.1f} %,"
               f" escala {escala['escala_pct']:+.1f} %")
        if abs(escala["escala_pct"]) > 100 * ESCALA_CUADRO_MAX:
            t.avisos.append(_aviso_escala(escala, t.metodo))
    ajuste = entradas.get("ajuste") or {}
    if ajuste.get("de") or ajuste.get("dn"):
        t = ajuste_fino(t, ajuste.get("de", 0.0), ajuste.get("dn", 0.0))
        avance(f"Ajuste fino: {t.ajuste[0]:+.1f} m E, {t.ajuste[1]:+.1f} m N")
    t.avisos[:0] = avisos
    for aviso in t.avisos:
        avance(f"Aviso: {aviso}")

    escribir_json(carpeta / SALIDA, dict(t.a_dict(), datum=datum))
    escribir_json(carpeta / GEOJSON, geojson(digitalizado, t))
    avance(f"Listo: {carpeta / SALIDA}")
    return t
