"""Los lotes de un geo en PDF georreferenciado (GeoPDF), como KMZ.

    python -m pipeline.geopdf <geo.pdf> <destino.kmz>

Muchas loteadoras no tienen el KMZ a mano pero sí el geo que les hizo el topógrafo
en ArcMap o QGIS: el satélite, los lotes con borde de color y su rótulo "LOTE 12".
Cuando ese PDF sale georreferenciado (ISO 32000, `/VP` con un `/Measure` `/GEO`:
ArcMap lo hace por defecto), el dibujo ya trae todo lo que hace falta. Los bordes
son vectores, los rótulos son texto y el PDF dice qué coordenada tiene cada punto
de la página. Este módulo arma con eso el mismo KMZ que Crea tu KMZ (un Placemark
"LOTE n" por lote), sin que nadie marque nada.

Los bordes llegan como trazos sueltos, no como polígonos: se cierran con
`polygonize`. El dibujo trae además otros trazos (el achurado de las disponibles,
los caminos, la flecha del acceso) que, mezclados con los deslindes, parten cada lote
en tiras. Por eso se agrupan por color y grosor y se elige el grupo (o la suma de
grupos) que deja más rótulos solos dentro de una cara: eso son los lotes.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

import numpy as np
import pymupdf
import shapely
from shapely.geometry import LineString, Point
from shapely.ops import polygonize

from .plano.georreferencia import Transformacion, a_utm, huso
from .plano.salida import escribir_kmz

# Por sobre esto (en metros) los puntos de control del PDF no calzan con una afín: el
# mapa no está en una proyección plana o el PDF está mal escrito.
RESIDUO_MAXIMO_M = 2.0
# Los extremos de dos trazos que deberían tocarse quedan a centésimas de punto.
GRILLA_PT = 0.01
# Una curva de Bézier se reemplaza por este número de tramos rectos.
TRAMOS_POR_CURVA = 8
# Un grupo de trazos con menos que esto no dibuja lotes.
TRAZOS_MINIMOS = 3
# Si las superficies escritas en el geo y las medidas difieren en mediana más que
# esto, el PDF dice estar en un lugar con otra escala: se avisa.
DIFERENCIA_AREA_AVISO = 0.05

ROTULO = re.compile(r"^\s*LOTE\s*[-:]?\s*([A-Z]?\s*-?\s*\d+(?:\s*-\s*\d+)?)\s*$", re.IGNORECASE)
SUPERFICIE = re.compile(r"^\s*([\d.,]+)\s*M\s*[2²]\s*$", re.IGNORECASE)


class NoEsGeoPdf(ValueError):
    """El PDF no trae coordenadas: es un plano común, que va por Crea tu KMZ."""


@dataclass
class Lectura:
    transformacion: Transformacion
    # [{"numero", "poligono" (en puntos de página), "area_oficial"}], como el
    # digitalizado de Crea tu KMZ, así sale por el mismo `escribir_kmz`.
    lotes: list[dict]
    avisos: list[str] = field(default_factory=list)

    @property
    def digitalizado(self) -> dict:
        return {"lotes": self.lotes}


def es_geopdf(origen: Path | bytes) -> bool:
    """¿El PDF trae coordenadas? Cualquier cosa que no se pueda abrir como PDF, no."""
    try:
        with _abrir(origen) as documento:
            return any(_marcos(pagina) for pagina in documento)
    except (RuntimeError, ValueError):
        return False


def leer(origen: Path | bytes) -> Lectura:
    """Los lotes del geo, en la primera página que trae coordenadas."""
    with _abrir(origen) as documento:
        for pagina in documento:
            marcos = _marcos(pagina)
            if marcos:
                return _leer_pagina(pagina, max(marcos, key=lambda m: m.area))
    raise NoEsGeoPdf("el PDF no trae coordenadas (no es un GeoPDF): súbelo en Crea tu KMZ")


def a_kmz(origen: Path | bytes, destino: Path, nombre: str | None = None) -> Lectura:
    """Escribe el KMZ de los lotes del geo y devuelve lo leído (con sus avisos)."""
    lectura = leer(origen)
    escribir_kmz(Path(destino), lectura.digitalizado, lectura.transformacion, nombre)
    return lectura


# --- el marco georreferenciado -----------------------------------------------------

@dataclass
class _Marco:
    rect: pymupdf.Rect        # en coordenadas de PyMuPDF (y hacia abajo)
    pagina: list[tuple[float, float]]   # puntos de control en la página
    lonlat: list[tuple[float, float]]

    @property
    def area(self) -> float:
        return abs(self.rect.width * self.rect.height)


def _abrir(origen: Path | bytes) -> pymupdf.Document:
    if isinstance(origen, (bytes, bytearray)):
        return pymupdf.open(stream=bytes(origen), filetype="pdf")
    return pymupdf.open(Path(origen), filetype="pdf")


def _numeros(texto: str) -> list[float]:
    return [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?", texto)]


def _marcos(pagina: pymupdf.Page) -> list[_Marco]:
    """Los marcos (viewports) de la página que dicen sus coordenadas.

    Cada uno trae su caja en el espacio del PDF, y puntos de control: LPTS (posición
    dentro de la caja, de 0 a 1) y GPTS (latitud y longitud de esos mismos puntos).
    """
    documento = pagina.parent
    tipo, valor = documento.xref_get_key(pagina.xref, "VP")
    if tipo == "null":
        return []
    if tipo == "xref":
        valor = documento.xref_object(int(valor.split()[0]))
    # Cada viewport es un diccionario dentro del arreglo: se separan por su /BBox.
    marcos = []
    for bloque in re.split(r"(?=/BBox)", valor)[1:]:
        caja = re.match(r"/BBox\s*\[([^\]]*)\]", bloque)
        medida = re.search(r"/Measure\s+(\d+)\s+0\s+R", bloque)
        if not caja or not medida:
            continue
        objeto = documento.xref_object(int(medida.group(1)))
        if "/GEO" not in objeto:
            continue
        gpts = re.search(r"/GPTS\s*\[([^\]]*)\]", objeto)
        lpts = re.search(r"/LPTS\s*\[([^\]]*)\]", objeto)
        if not gpts:
            continue
        g = _numeros(gpts.group(1))
        x0, y0, x1, y1 = _numeros(caja.group(1))[:4]
        # Sin LPTS, los GPTS son las esquinas de la caja en orden.
        l = _numeros(lpts.group(1)) if lpts else [0, 0, 0, 1, 1, 1, 1, 0][:len(g)]
        if len(g) < 6 or len(g) != len(l):
            continue
        a_pantalla = pagina.transformation_matrix
        puntos = [pymupdf.Point(x0 + u * (x1 - x0), y0 + v * (y1 - y0)) * a_pantalla
                  for u, v in zip(l[::2], l[1::2])]
        rect = pymupdf.Rect(pymupdf.Point(x0, y0) * a_pantalla, pymupdf.Point(x1, y1) * a_pantalla)
        rect.normalize()
        marcos.append(_Marco(rect, [(p.x, p.y) for p in puntos],
                             [(lon, lat) for lat, lon in zip(g[::2], g[1::2])]))
    return marcos


def _transformacion(marco: _Marco) -> Transformacion:
    """Afín de la página a UTM, ajustada a los puntos de control.

    El mapa de ArcMap está dibujado en una proyección plana (UTM casi siempre), así que
    de la página a UTM es una afín exacta: el residuo es solo el redondeo de los GPTS.
    """
    lon_c = float(np.mean([p[0] for p in marco.lonlat]))
    lat_c = float(np.mean([p[1] for p in marco.lonlat]))
    epsg = huso(lon_c, lat_c)
    este, norte = a_utm([p[0] for p in marco.lonlat], [p[1] for p in marco.lonlat], epsg)
    origen = np.array([[x, y, 1.0] for x, y in marco.pagina])
    destino = np.c_[este, norte]
    coeficientes, *_ = np.linalg.lstsq(origen, destino, rcond=None)
    residuo = float(np.abs(origen @ coeficientes - destino).max())
    if residuo > RESIDUO_MAXIMO_M:
        raise ValueError(f"las coordenadas del PDF no calzan entre sí ({residuo:.1f} m de error): "
                         "exporta el geo de nuevo desde ArcMap o súbelo en Crea tu KMZ")
    matriz = np.vstack([coeficientes.T, [0.0, 0.0, 1.0]])
    return Transformacion(metodo="geopdf", tipo="afin", epsg=epsg, matriz=matriz,
                          parametros={"residuo_m": round(residuo, 3)})


# --- los lotes -----------------------------------------------------------------------

@dataclass
class _Rotulo:
    numero: str
    punto: Point
    area: float | None


def _rotulos(pagina: pymupdf.Page, marco: pymupdf.Rect) -> list[_Rotulo]:
    """"LOTE 12" y, en la línea de abajo si la hay, su superficie ("5026M2")."""
    rotulos = []
    for bloque in pagina.get_text("dict")["blocks"]:
        if bloque.get("type") != 0:
            continue
        lineas = [("".join(s["text"] for s in l["spans"]), l["bbox"]) for l in bloque["lines"]]
        for i, (texto, caja) in enumerate(lineas):
            encontrado = ROTULO.match(texto)
            if not encontrado:
                continue
            centro = pymupdf.Point((caja[0] + caja[2]) / 2, (caja[1] + caja[3]) / 2)
            if not marco.contains(centro):
                continue
            area = None
            if i + 1 < len(lineas) and (superficie := SUPERFICIE.match(lineas[i + 1][0])):
                area = _numero_chileno(superficie.group(1))
            numero = re.sub(r"\s+", "", encontrado.group(1)).upper()
            rotulos.append(_Rotulo(numero, Point(centro.x, centro.y), area))
    return rotulos


def _numero_chileno(texto: str) -> float | None:
    """"5.026" y "5,026.5" y "5026" → número. El punto de miles es lo de acá."""
    limpio = texto.strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", limpio):
        limpio = limpio.replace(".", "").replace(",", ".")
    else:
        limpio = limpio.replace(",", "")
    try:
        return float(limpio)
    except ValueError:
        return None


def _trazos(pagina: pymupdf.Page) -> dict[tuple, list[LineString]]:
    """Los trazos de la página, agrupados por color y grosor."""
    grupos: dict[tuple, list[LineString]] = {}
    for dibujo in pagina.get_drawings():
        color = dibujo.get("color")
        if color is None:
            continue
        clave = (tuple(round(c, 2) for c in color), round(dibujo.get("width") or 0, 2))
        tramos = grupos.setdefault(clave, [])
        for item in dibujo["items"]:
            tramos.extend(_tramos(item))
    return grupos


def _tramos(item) -> list[LineString]:
    tipo = item[0]
    if tipo == "l":
        puntos = [item[1], item[2]]
    elif tipo == "c":
        p0, p1, p2, p3 = item[1:5]
        puntos = [_bezier(p0, p1, p2, p3, t / TRAMOS_POR_CURVA) for t in range(TRAMOS_POR_CURVA + 1)]
    elif tipo == "re":
        r = item[1]
        puntos = [r.tl, r.tr, r.br, r.bl, r.tl]
    elif tipo == "qu":
        q = item[1]
        puntos = [q.ul, q.ur, q.lr, q.ll, q.ul]
    else:
        return []
    coordenadas = [(p.x, p.y) for p in puntos]
    return [LineString(coordenadas[i:i + 2]) for i in range(len(coordenadas) - 1)
            if coordenadas[i] != coordenadas[i + 1]]


def _bezier(p0, p1, p2, p3, t: float):
    u = 1 - t
    return pymupdf.Point(u ** 3 * p0.x + 3 * u * u * t * p1.x + 3 * u * t * t * p2.x + t ** 3 * p3.x,
                         u ** 3 * p0.y + 3 * u * u * t * p1.y + 3 * u * t * t * p2.y + t ** 3 * p3.y)


def _caras(trazos: list[LineString]) -> list:
    return list(polygonize(shapely.union_all(trazos, grid_size=GRILLA_PT)))


def _asignar(caras: list, rotulos: list[_Rotulo]) -> dict[int, list[_Rotulo]]:
    """Qué rótulos caen en cada cara."""
    arbol = shapely.STRtree(caras)
    dentro: dict[int, list[_Rotulo]] = {}
    for rotulo in rotulos:
        for i in arbol.query(rotulo.punto, predicate="within"):
            dentro.setdefault(int(i), []).append(rotulo)
            break
    return dentro


def _solos(asignados: dict[int, list[_Rotulo]]) -> int:
    return sum(1 for r in asignados.values() if len(r) == 1)


def _mejores_trazos(grupos: dict[tuple, list[LineString]], rotulos: list[_Rotulo]):
    """Los grupos de trazos que mejor separan los rótulos: los deslindes.

    Se parte del grupo que solo deja más rótulos solos en su cara y se le suman los
    otros mientras mejore (un loteo dibujado en dos colores). El achurado o el eje de
    un camino parten los lotes, así que no mejoran y quedan fuera.
    """
    candidatos = [t for t in grupos.values() if len(t) >= TRAZOS_MINIMOS]
    if not candidatos:
        return [], {}
    puntaje = []
    for trazos in candidatos:
        caras = _caras(trazos)
        puntaje.append((_solos(_asignar(caras, rotulos)), trazos, caras))
    puntaje.sort(key=lambda p: -p[0])
    mejor, elegidos, caras = puntaje[0]
    for _, trazos, _ in puntaje[1:]:
        prueba = _caras(elegidos + trazos)
        cuantos = _solos(_asignar(prueba, rotulos))
        if cuantos > mejor:
            mejor, elegidos, caras = cuantos, elegidos + trazos, prueba
    return caras, _asignar(caras, rotulos)


def _leer_pagina(pagina: pymupdf.Page, marco: _Marco) -> Lectura:
    transformacion = _transformacion(marco)
    rotulos = _rotulos(pagina, marco.rect)
    if not rotulos:
        raise ValueError('el geo no trae rótulos "LOTE n" como texto: súbelo en Crea tu KMZ')
    caras, asignados = _mejores_trazos(_trazos(pagina), rotulos)

    avisos = []
    lotes, vistos = [], set()
    for i, en_cara in sorted(asignados.items(), key=lambda par: par[1][0].numero):
        if len(en_cara) > 1:
            avisos.append(f"los lotes {', '.join(r.numero for r in en_cara)} quedaron en un solo "
                          "polígono (el dibujo no los separa) y no salen en el KMZ")
            continue
        rotulo = en_cara[0]
        if rotulo.numero in vistos:
            avisos.append(f"el lote {rotulo.numero} aparece dos veces; sale el primero")
            continue
        vistos.add(rotulo.numero)
        cara = caras[i]
        lotes.append({"numero": rotulo.numero,
                      "poligono": [list(c) for c in cara.exterior.coords[:-1]],
                      "huecos": [[list(c) for c in h.coords[:-1]] for h in cara.interiors],
                      "area_oficial": rotulo.area})
    fuera = sorted({r.numero for r in rotulos} - {r.numero for en in asignados.values() for r in en})
    if fuera:
        avisos.append(f"{len(fuera)} rótulos no caen dentro de ningún lote cerrado: {', '.join(fuera[:10])}"
                      f"{'…' if len(fuera) > 10 else ''}")
    if not lotes:
        raise ValueError("no se pudo cerrar ningún lote con el dibujo del PDF: súbelo en Crea tu KMZ")
    avisos += _revisar_superficies(lotes, transformacion)
    lotes.sort(key=lambda l: _orden(l["numero"]))
    return Lectura(transformacion, lotes, avisos)


def _orden(numero: str) -> tuple:
    return tuple(int(n) if n.isdigit() else n for n in re.findall(r"\d+|\D+", numero))


def _revisar_superficies(lotes: list[dict], t: Transformacion) -> list[str]:
    """Las superficies medidas contra las escritas en el geo, si las trae."""
    diferencias = []
    for lote in lotes:
        if not lote.get("area_oficial"):
            continue
        este, norte = t.a_utm(*np.asarray(lote["poligono"], float).T)
        medida = shapely.Polygon(np.c_[este, norte]).area
        diferencias.append(medida / lote["area_oficial"] - 1)
    if diferencias and abs(median(diferencias)) > DIFERENCIA_AREA_AVISO:
        return [f"los lotes miden en mediana {100 * median(diferencias):+.0f}% respecto de la "
                "superficie escrita en el geo: revisa que el KMZ calce sobre el satélite"]
    return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("destino", type=Path)
    args = parser.parse_args(argv)
    try:
        lectura = a_kmz(args.pdf, args.destino)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"{len(lectura.lotes)} lotes → {args.destino}")
    for aviso in lectura.avisos:
        print(f"aviso: {aviso}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
