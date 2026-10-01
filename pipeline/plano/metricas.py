"""Medir lotes candidatos contra los reales (el KMZ del topógrafo), lote a lote.

Portado de las pruebas de concepto (`poc_kmz/medir.py`, `ronda3_evaluacion/medir_r3.py`
y `reales.py`), con las mismas definiciones para que los números se comparen:

- Por lote (pareados por número): IoU, desplazamiento del centroide (real − candidato)
  y Hausdorff simétrico de los bordes (densificado a 0,05).
- Global: mediana, p10, p90 y máximo; error de área contra el real; traslapes entre
  lotes y huecos dentro del contorno de cada lado.
- Similitud de mejor ajuste candidato → real (Umeyama sobre los centroides pareados):
  giro, escala y traslación del centro. Las mismas métricas con el candidato movido
  por esa similitud son el "what-if": el techo del digitalizado si la georreferencia
  fuera perfecta.

Todo en metros, en el UTM WGS84 del huso del KMZ real.

`lotes_kmz` lee cualquiera de los dos lados. Un KMZ de lotes trae polígonos con nombre
("LOTE 12") o polígonos sin nombre y puntos numerados (punto en polígono). Un KMZ de
CAD trae solo líneas: se cierran (`polygonize`, más el borde de los polígonos que
haya, que suele ser el perímetro) y cada cara toma el punto numerado que cae dentro.
Las capas (la `<description>` del Placemark, que trae la capa CAD) de
`capas_excluidas` no se leen: bordes de camino, polígonos de caminos.
"""
from __future__ import annotations

import math
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import shapely
from shapely import STRtree
from shapely.affinity import affine_transform
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, polygonize, unary_union

from .georreferencia import _transformador, huso

NS = "{http://www.opengis.net/kml/2.2}"

# Un extremo de línea a menos de esto de otra línea se pega a ella: en los KMZ del set
# los huecos del CAD miden < 1 cm, salvo uno de 0,8 m en Algarrobo (sin el conector
# dos lotes salen en una sola cara).
TOLERANCIA_CONECTOR_M = 1.0

# Grilla con que se anudan las líneas antes de cerrar las caras.
PRECISION_M = 0.001

# Densificación del Hausdorff (fracción de cada segmento), como en las pruebas.
DENSIFICAR = 0.05


def numero(nombre: str | None) -> str | None:
    """"LOTE 12", "LOTE-12", " 12", "12." → "12"; lo demás no es un número de lote."""
    if nombre is None:
        return None
    t = re.sub(r"\bLOTES?\b", " ", nombre.strip().upper())
    m = re.fullmatch(r"[\s\-_.#]*(\d+)[\s.]*", t)
    return str(int(m.group(1))) if m else None


def _coordenadas(texto: str) -> list[tuple[float, float]]:
    salida = []
    for trozo in (texto or "").split():
        p = trozo.split(",")
        if len(p) >= 2:
            salida.append((float(p[0]), float(p[1])))
    return salida


def _rasgos(ruta: Path) -> list[dict]:
    """[{tipo: L|A|P, lonlat, capa, nombre}] de todos los Placemark."""
    with zipfile.ZipFile(ruta) as z:
        kml = z.read([n for n in z.namelist() if n.lower().endswith(".kml")][0]).decode("utf-8", "ignore")
    raiz = ET.fromstring(kml)
    salida = []
    for marca in raiz.iter(NS + "Placemark"):
        capa, nombre = marca.findtext(NS + "description"), marca.findtext(NS + "name")
        base = dict(capa=(capa or "").strip(), nombre=nombre)
        for e in marca.iter(NS + "LineString"):
            salida.append(dict(base, tipo="L", lonlat=_coordenadas(e.findtext(NS + "coordinates"))))
        for e in marca.iter(NS + "Polygon"):
            c = e.find(f"{NS}outerBoundaryIs//{NS}coordinates")
            if c is not None:
                salida.append(dict(base, tipo="A", lonlat=_coordenadas(c.text)))
        for e in marca.iter(NS + "Point"):
            c = _coordenadas(e.findtext(NS + "coordinates"))
            if c:
                salida.append(dict(base, tipo="P", lonlat=c[:1]))
    return [r for r in salida if r["lonlat"]]


def epsg_de_kmz(ruta: Path) -> int:
    """El UTM WGS84 del huso donde cae el KMZ."""
    lonlat = np.array([q for r in _rasgos(ruta) for q in r["lonlat"]])
    return huso(*lonlat.mean(0))


def lotes_kmz(ruta: Path, epsg: int | None = None, capas_excluidas=()) -> tuple[dict[str, Polygon], dict]:
    """({número: Polygon en `epsg`}, informe). Ver el docstring del módulo."""
    rasgos = _rasgos(ruta)
    if epsg is None:
        epsg = huso(*np.array([q for r in rasgos for q in r["lonlat"]]).mean(0))
    excluidas = set(capas_excluidas)
    a_utm = _transformador(4326, epsg)
    proyectar = lambda ll: list(zip(*a_utm.transform(*np.asarray(ll, float).T)))
    lineas, poligonos, puntos = [], [], []
    for r in rasgos:
        if r["capa"] in excluidas:
            continue
        if r["tipo"] == "L" and len(r["lonlat"]) >= 2:
            lineas.append(LineString(proyectar(r["lonlat"])))
        elif r["tipo"] == "A" and len(r["lonlat"]) >= 3:
            p = Polygon(proyectar(r["lonlat"]))
            poligonos.append((numero(r["nombre"]), p if p.is_valid else p.buffer(0)))
        elif r["tipo"] == "P" and numero(r["nombre"]) is not None:
            puntos.append((numero(r["nombre"]), Point(proyectar(r["lonlat"])[0])))
    informe = dict(epsg=epsg, lineas=len(lineas), poligonos=len(poligonos), puntos_numerados=len(puntos),
                   capas_excluidas=sorted(Counter(r["capa"] for r in rasgos if r["capa"] in excluidas).items()))

    # Polígonos con nombre o con un solo punto numerado adentro.
    rotulos = _rotular([p for _, p in poligonos], puntos)
    lotes_poligono = [(n if n is not None else (rotulos[i][0] if len(rotulos[i]) == 1 else None), p)
                      for i, (n, p) in enumerate(poligonos)]
    con_numero = [(n, p) for n, p in lotes_poligono if n is not None]
    if con_numero and (not lineas or len(con_numero) >= 0.5 * len({n for n, _ in puntos})):
        informe["modo"] = "poligonos"
        caras = [p for _, p in lotes_poligono]
        numeradas = lotes_poligono
    else:
        # Red de líneas: más el borde de los polígonos (el perímetro).
        informe["modo"] = "lineas"
        bordes = lineas + [LineString(p.exterior.coords) for _, p in poligonos]
        extra = _conectores(bordes, TOLERANCIA_CONECTOR_M)
        # Con grilla de 1 mm: un extremo que cae sobre otra línea por redondeo (lon/lat ida
        # y vuelta) queda anudado a ella.
        caras = list(polygonize(shapely.union_all(bordes + extra, grid_size=PRECISION_M)))
        informe["conectores"] = len(extra)
        rotulos = _rotular(caras, puntos)
        numeradas = [(v[0] if len(v) == 1 else None, c) for c, v in zip(caras, rotulos)]
        informe["caras_multi_rotulo"] = [v for v in rotulos if len(v) > 1]
    informe["caras"] = len(caras)
    informe["caras_sin_numero"] = sum(n is None for n, _ in numeradas)
    lotes, repetidos = {}, []
    for n, p in numeradas:
        if n is None:
            continue
        if n in lotes:
            repetidos.append(n)
        lotes[n] = p
    informe["repetidos"] = sorted(set(repetidos), key=_orden)
    informe["lotes"] = len(lotes)
    return lotes, informe


def _rotular(caras: list[Polygon], puntos) -> list[list[str]]:
    dentro = [[] for _ in caras]
    if not caras:
        return dentro
    arbol = STRtree(caras)
    for n, p in puntos:
        for i in arbol.query(p):
            if caras[i].contains(p):
                dentro[i].append(n)
    return [sorted(set(v), key=_orden) for v in dentro]


def _conectores(lineas: list[LineString], tolerancia: float) -> list[LineString]:
    """Cada extremo colgante se une al punto más cercano de otra línea, si está a ≤
    `tolerancia`."""
    arbol = STRtree(lineas)
    extra = []
    for i, g in enumerate(lineas):
        for c in (g.coords[0], g.coords[-1]):
            p = Point(c)
            mejor, distancia = None, math.inf
            for j in arbol.query(p.buffer(max(tolerancia, 5.0))):
                if j != i:
                    d = lineas[j].distance(p)
                    if d < distancia:
                        mejor, distancia = j, d
            if 1e-9 < distancia <= tolerancia:
                q = nearest_points(p, lineas[mejor])[1]
                extra.append(LineString([c, (q.x, q.y)]))
    return extra


def _orden(n: str):
    return (0, int(n), "") if n.isdigit() else (1, 0, n)


# --- métricas ------------------------------------------------------------------

def por_lote(candidato: dict[str, Polygon], real: dict[str, Polygon]) -> list[dict]:
    filas = []
    for n in sorted(set(candidato) & set(real), key=_orden):
        a, b = candidato[n], real[n]
        ca, cb = a.centroid, b.centroid
        dx, dy = cb.x - ca.x, cb.y - ca.y
        filas.append(dict(lote=n, iou=a.intersection(b).area / a.union(b).area, dx=dx, dy=dy,
                          d=math.hypot(dx, dy),
                          hd=shapely.hausdorff_distance(a.exterior, b.exterior, densify=DENSIFICAR),
                          vertices=len(a.exterior.coords) - 1, vertices_real=len(b.exterior.coords) - 1,
                          area=a.area, area_real=b.area))
    return filas


def resumen(filas: list[dict]) -> dict:
    if not filas:
        return dict(n=0)
    q = lambda k, p: float(np.percentile([f[k] for f in filas], p))
    return dict(
        n=len(filas),
        iou_mediana=q("iou", 50), iou_p10=q("iou", 10), iou_min=q("iou", 0),
        centroide_mediana_m=q("d", 50), centroide_p90_m=q("d", 90), centroide_max_m=q("d", 100),
        hausdorff_mediana_m=q("hd", 50), hausdorff_p10_m=q("hd", 10), hausdorff_p90_m=q("hd", 90),
        hausdorff_max_m=q("hd", 100),
        dx_medio_m=float(np.mean([f["dx"] for f in filas])), dy_medio_m=float(np.mean([f["dy"] for f in filas])),
        vertices_mediana=q("vertices", 50), vertices_real_mediana=q("vertices_real", 50),
        error_area_mediana_pct=float(np.median([abs(f["area"] / f["area_real"] - 1) * 100 for f in filas])),
    )


def umeyama(origen: np.ndarray, destino: np.ndarray):
    """Similitud destino ≈ s·R·origen + t (2D), por mínimos cuadrados."""
    mo, md = origen.mean(0), destino.mean(0)
    O, D = origen - mo, destino - md
    U, sigma, Vt = np.linalg.svd(D.T @ O / len(origen))
    E = np.diag([1.0, np.sign(np.linalg.det(U @ Vt))])
    R = U @ E @ Vt
    s = np.trace(np.diag(sigma) @ E) / (O ** 2).sum(1).mean()
    return s, R, md - s * R @ mo


def topologia(poligonos) -> dict:
    """Traslapes entre pares, huecos dentro del contorno de la unión, partes y área."""
    ps = list(poligonos)
    if not ps:
        return dict(traslapes_m2=0.0, huecos_m2=0.0, partes=0, area_m2=0.0)
    arbol = STRtree(ps)
    traslape = 0.0
    for i, p in enumerate(ps):
        for j in arbol.query(p):
            if j > i and ps[j].intersects(p):
                traslape += p.intersection(ps[j]).area
    union = unary_union(ps)
    partes = list(getattr(union, "geoms", [union]))
    huecos = sum(Polygon(r).area for g in partes for r in g.interiors)
    return dict(traslapes_m2=float(traslape), huecos_m2=float(huecos), partes=len(partes), area_m2=float(union.area))


def comparar(candidato: dict[str, Polygon], real: dict[str, Polygon]) -> dict:
    """Todas las métricas, tal cual y what-if, más la similitud óptima y la topología."""
    comunes = sorted(set(candidato) & set(real), key=_orden)
    salida = dict(pareados=len(comunes), lotes=len(candidato), lotes_real=len(real),
                  solo_candidato=sorted(set(candidato) - set(real), key=_orden),
                  solo_real=sorted(set(real) - set(candidato), key=_orden),
                  topologia=topologia(candidato.values()), topologia_real=topologia(real.values()))
    filas = por_lote(candidato, real)
    salida["tal_cual"] = resumen(filas)
    if len(comunes) < 2:
        salida["what_if"] = dict(n=len(comunes))
        return salida
    origen = np.array([[candidato[n].centroid.x, candidato[n].centroid.y] for n in comunes])
    destino = np.array([[real[n].centroid.x, real[n].centroid.y] for n in comunes])
    s, R, t = umeyama(origen, destino)
    centro = origen.mean(0)
    mover = s * R @ centro + t - centro
    residuo = destino - (s * (R @ origen.T).T + t)
    salida["similitud"] = dict(rotacion_grados=math.degrees(math.atan2(R[1, 0], R[0, 0])), escala_pct=100 * (s - 1),
                               de_m=float(mover[0]), dn_m=float(mover[1]), desplazamiento_m=float(np.hypot(*mover)),
                               residuo_rms_m=float(np.sqrt((residuo ** 2).sum(1).mean())))
    m = [s * R[0, 0], s * R[0, 1], s * R[1, 0], s * R[1, 1], t[0], t[1]]
    filas_ajuste = por_lote({n: affine_transform(candidato[n], m) for n in comunes}, real)
    salida["what_if"] = resumen(filas_ajuste)
    ajuste = {f["lote"]: f for f in filas_ajuste}
    salida["por_lote"] = [dict(f, iou_what_if=ajuste[f["lote"]]["iou"], d_what_if=ajuste[f["lote"]]["d"],
                               hd_what_if=ajuste[f["lote"]]["hd"]) for f in filas]
    return salida
