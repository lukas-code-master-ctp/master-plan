"""Lectura del KMZ del loteo.

Llega de dos formas. La cómoda: un polígono por lote y, aparte, un punto con el
nombre ("LOTE A123"), como exporta Global Mapper cuando el topógrafo ya cerró los
lotes. La otra es el dibujo CAD tal cual: los lotes no son polígonos sino una red
de líneas —cada arista una LineString suelta— que hay que cerrar para encontrar
cada lote. En las dos, emparejar cada etiqueta con su polígono es trabajo de este
módulo.

Si el loteo tiene etapas, cada etapa repite la numeración desde 1 y el dibujo las
distingue por color. La leyenda —un cuadrito de cada color junto a un rótulo
"ETAPA n"— dice qué color es cada etapa, y el id del lote queda como "etapa-número"
("2-7"). Sin leyenda, dos lotes con el mismo nombre son un error, no una adivinanza.
"""
from __future__ import annotations

import re
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from shapely import STRtree, prepare
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import nearest_points, polygonize, unary_union

from . import geo

NS = "{http://www.opengis.net/kml/2.2}"
DISTANCIA_MAXIMA_ETIQUETA_M = 150.0

# Las divisorias del CAD suelen quedar a centímetros del borde sin tocarlo. Hasta
# esta distancia el extremo se pega a la línea vecina; más allá es un hueco real y
# los lotes quedan fusionados.
TOLERANCIA_RED_M = 0.5

# Franja alrededor del contorno de un lote dentro de la cual una línea cuenta como
# borde suyo, para decidir de qué color (etapa) es.
FRANJA_BORDE_M = 0.3

# El cuadrito de la leyenda está a pocos metros de su rótulo "ETAPA n".
DISTANCIA_MAXIMA_LEYENDA_M = 100.0


@dataclass
class ParcelaGeometrica:
    id: str | None
    anillo: geo.Anillo
    en_venta: bool = True
    etapa: int | None = None
    color: str | None = field(default=None, repr=False)
    centroide: geo.Punto = field(init=False)
    area_m2: float = field(init=False)

    def __post_init__(self):
        self.centroide = geo.centroide(self.anillo)
        self.area_m2 = geo.area_m2(self.anillo)


@dataclass
class _Dibujo:
    """Lo que trae el KML, separado según lo que es."""
    etiquetas: list[tuple[str, geo.Punto]]
    rotulos_etapa: list[tuple[int, geo.Punto]]
    poligonos: list[ParcelaGeometrica]
    lineas: list[tuple[list[geo.Punto], str | None]]


def normalizar_id(texto: str | None) -> str | None:
    """"LOTE A 420" → "A420".  "LOTE 42" → "42".  "7-1" → "7-1".  Basura → None.

    Conviven tres formas de numerar: con letra de sector ("A214"), solo con el
    número ("LOTE 42") y como par sector-lote ("7-1"). Un loteo usa una sola, pero
    el pipeline sirve a varios, así que las reconoce todas.
    """
    if texto is None:
        return None
    if isinstance(texto, float) and texto.is_integer():
        texto = int(texto)
    limpio = re.sub(r"\bLOTES?\b", " ", str(texto).strip().upper())

    con_letra = re.search(r"([A-Z])\s*0*(\d+)", limpio)
    if con_letra:
        return f"{con_letra.group(1)}{int(con_letra.group(2))}"

    # Sin letra solo se acepta un número limpio: cualquier otra cosa con dígitos
    # sueltos (una fecha, un rol, una superficie) no es el nombre de un lote.
    solo_numeros = re.fullmatch(r"[\s.]*(\d+(?:\s*-\s*\d+)*)[\s.]*", limpio)
    if solo_numeros:
        partes = solo_numeros.group(1).replace(" ", "").split("-")
        return "-".join(str(int(p)) for p in partes)
    return None


def numero_de_etapa(texto: str | None) -> int | None:
    """"ROL 409-37 ETAPA 1" → 1. Un lote no lleva la palabra ETAPA en el nombre."""
    if not texto:
        return None
    coincidencia = re.search(r"\bETAPA\s*0*(\d+)\b", str(texto).upper())
    return int(coincidencia.group(1)) if coincidencia else None


def leer_kmz(ruta: Path) -> list[ParcelaGeometrica]:
    with zipfile.ZipFile(ruta) as archivo:
        nombres = [n for n in archivo.namelist() if n.lower().endswith(".kml")]
        if not nombres:
            raise ValueError(f"{ruta.name} no contiene ningún .kml")
        kml = archivo.read(nombres[0]).decode("utf-8", "ignore")
    return _parsear(kml)


def leer_lineas(ruta: Path) -> list[geo.Anillo]:
    """Todas las líneas del dibujo —deslindes y caminos— para calibrar la pose contra
    la foto. Los polígonos entran como su contorno; la leyenda se deja afuera."""
    with zipfile.ZipFile(ruta) as archivo:
        nombres = [n for n in archivo.namelist() if n.lower().endswith(".kml")]
        if not nombres:
            raise ValueError(f"{ruta.name} no contiene ningún .kml")
        kml = archivo.read(nombres[0]).decode("utf-8", "ignore")
    raiz = ET.fromstring(kml)
    dibujo = _leer_dibujo(raiz, _colores_de_estilo(raiz))
    _, muestras = _leyenda(dibujo)
    ajenos = {id(m) for m in muestras}
    rotulos = [punto for _, punto in dibujo.rotulos_etapa]
    lineas = [puntos for puntos, _ in dibujo.lineas if len(puntos) >= 2]
    for poligono in dibujo.poligonos:
        if id(poligono) in ajenos or any(geo.contiene(poligono.anillo, r) for r in rotulos):
            continue
        if len(poligono.anillo) >= 3:
            lineas.append(poligono.anillo + poligono.anillo[:1])
    return lineas


def _parsear(kml: str) -> list[ParcelaGeometrica]:
    raiz = ET.fromstring(kml)
    dibujo = _leer_dibujo(raiz, _colores_de_estilo(raiz))
    leyenda, muestras = _leyenda(dibujo)

    if dibujo.lineas:
        parcelas = _cerrar_red(dibujo)
    else:
        ajenos = {id(m) for m in muestras}
        parcelas = [p for p in dibujo.poligonos if id(p) not in ajenos]
        _asignar_etiquetas(dibujo.etiquetas, parcelas)

    _asignar_etapas(parcelas, leyenda)
    _revisar_repetidos(parcelas)
    return parcelas


# --- lectura del KML ---------------------------------------------------------

def _leer_dibujo(raiz: ET.Element, colores: dict[str, str]) -> _Dibujo:
    dibujo = _Dibujo([], [], [], [])
    for marca in raiz.iter(NS + "Placemark"):
        nombre = _texto(marca.find(NS + "name"))
        descripcion = _texto(marca.find(NS + "description"))
        color = _color_de(marca, colores)
        etapa = numero_de_etapa(nombre)

        punto = marca.find(f".//{NS}Point/{NS}coordinates")
        if punto is not None and punto.text:
            if etapa is not None:
                dibujo.rotulos_etapa.append((etapa, _coordenadas(punto.text)[0]))
            else:
                identificador = normalizar_id(nombre)
                if identificador:
                    dibujo.etiquetas.append((identificador, _coordenadas(punto.text)[0]))

        anillo = marca.find(f".//{NS}Polygon/{NS}outerBoundaryIs//{NS}coordinates")
        if anillo is not None and anillo.text:
            dibujo.poligonos.append(ParcelaGeometrica(
                id=normalizar_id(nombre) if etapa is None else None,
                anillo=_coordenadas(anillo.text, cerrado=True),
                en_venta="NO EN VENTA" not in descripcion.upper(),
                color=color,
            ))

        for linea in marca.iter(NS + "LineString"):
            coordenadas = linea.find(NS + "coordinates")
            if coordenadas is not None and coordenadas.text:
                dibujo.lineas.append((_coordenadas(coordenadas.text), color))
    return dibujo


def _colores_de_estilo(raiz: ET.Element) -> dict[str, str]:
    """id de estilo → color KML (aabbggrr). El color de línea manda; si no hay,
    el de relleno."""
    colores: dict[str, str] = {}
    for estilo in raiz.iter(NS + "Style"):
        identificador = estilo.get("id")
        color = estilo.find(f"{NS}LineStyle/{NS}color")
        if color is None:
            color = estilo.find(f"{NS}PolyStyle/{NS}color")
        if identificador and color is not None and color.text:
            colores[identificador] = color.text.strip().upper()

    for mapa in raiz.iter(NS + "StyleMap"):
        identificador = mapa.get("id")
        for par in mapa.findall(NS + "Pair"):
            clave, url = par.find(NS + "key"), par.find(NS + "styleUrl")
            if identificador and clave is not None and clave.text == "normal" \
                    and url is not None and url.text:
                colores[identificador] = colores.get(url.text.strip().lstrip("#"), "")
    return colores


def _color_de(marca: ET.Element, colores: dict[str, str]) -> str | None:
    url = _texto(marca.find(NS + "styleUrl"))
    if url:
        return colores.get(url.lstrip("#")) or None
    propio = marca.find(f".//{NS}Style/{NS}LineStyle/{NS}color")
    if propio is not None and propio.text:
        return propio.text.strip().upper()
    return None


def _texto(elemento: ET.Element | None) -> str:
    return (elemento.text or "").strip() if elemento is not None else ""


def _coordenadas(texto: str, cerrado: bool = False) -> geo.Anillo:
    puntos = []
    for trozo in texto.split():
        partes = trozo.split(",")
        if len(partes) >= 2:
            puntos.append((float(partes[0]), float(partes[1])))
    # El anillo KML cierra repitiendo el primer punto; lo dejamos abierto.
    if cerrado and len(puntos) > 2 and puntos[0] == puntos[-1]:
        puntos.pop()
    return puntos


# --- red de líneas -------------------------------------------------------------

def _cerrar_red(dibujo: _Dibujo) -> list[ParcelaGeometrica]:
    """Cierra la red de líneas y se queda con las caras que tienen una etiqueta.

    Las demás caras son caminos, franjas de servidumbre o el recuadro de la
    leyenda. Una cara con varias etiquetas son lotes que quedaron fusionados por un
    hueco en el dibujo: se conserva sin id, para que se note en el plano.
    """
    origen = _origen(dibujo)

    def metros(punto: geo.Punto) -> tuple[float, float]:
        return geo.a_metros(punto, origen)

    bordes: list[tuple[LineString, str | None]] = [
        (LineString([metros(p) for p in puntos]), color)
        for puntos, color in dibujo.lineas if len(puntos) >= 2]
    bordes += [(LineString([metros(p) for p in pg.anillo + pg.anillo[:1]]), pg.color)
               for pg in dibujo.poligonos if len(pg.anillo) >= 3]

    red = unary_union(_pegar_extremos([linea for linea, _ in bordes]))
    etiquetas = [(identificador, Point(metros(p))) for identificador, p in dibujo.etiquetas]

    parcelas = []
    for cara in polygonize(red):
        dentro = [identificador for identificador, punto in etiquetas if cara.contains(punto)]
        if not dentro:
            continue
        anillo = [geo.desde_metros(xy, origen) for xy in list(cara.exterior.coords)[:-1]]
        parcelas.append(ParcelaGeometrica(
            id=dentro[0] if len(dentro) == 1 else None,
            anillo=anillo,
            color=_color_dominante(cara, bordes),
        ))
    return parcelas


def _pegar_extremos(lineas: list[LineString]) -> list[LineString]:
    """Mueve cada extremo que casi toca otra línea hasta tocarla de verdad."""
    arbol = STRtree(lineas)
    pegadas = []
    for indice, linea in enumerate(lineas):
        puntos = list(linea.coords)
        for extremo in (0, -1):
            punta = Point(puntos[extremo])
            vecinas = [j for j in arbol.query(punta.buffer(TOLERANCIA_RED_M)) if j != indice]
            if not vecinas:
                continue
            cercana = min(vecinas, key=lambda j: lineas[j].distance(punta))
            distancia = lineas[cercana].distance(punta)
            if 0 < distancia <= TOLERANCIA_RED_M:
                puntos[extremo] = nearest_points(lineas[cercana], punta)[0].coords[0]
        pegadas.append(LineString(puntos))
    return pegadas


def _color_dominante(cara: Polygon, bordes: list[tuple[LineString, str | None]]) -> str | None:
    """El color con más metros de línea sobre el contorno de la cara."""
    franja = cara.exterior.buffer(FRANJA_BORDE_M)
    prepare(franja)
    largo: Counter = Counter()
    for linea, color in bordes:
        if color and franja.intersects(linea):
            largo[color] += franja.intersection(linea).length
    return largo.most_common(1)[0][0] if largo else None


def _origen(dibujo: _Dibujo) -> geo.Punto:
    puntos = [p for puntos, _ in dibujo.lineas for p in puntos]
    puntos += [p for pg in dibujo.poligonos for p in pg.anillo]
    puntos += [p for _, p in dibujo.etiquetas]
    return (sum(p[0] for p in puntos) / len(puntos), sum(p[1] for p in puntos) / len(puntos))


# --- etiquetas y etapas --------------------------------------------------------

def _asignar_etiquetas(etiquetas: list[tuple[str, geo.Punto]],
                       parcelas: list[ParcelaGeometrica]) -> None:
    """Empareja cada etiqueta con su polígono.

    Primero por contención, que es inequívoca. Las etiquetas que quedan fuera de todo
    polígono (o dentro de varios) se resuelven por cercanía al centroide, y solo si
    hay un polígono libre razonablemente cerca.
    """
    sin_asignar = [p for p in parcelas if p.id is None]
    pendientes: list[tuple[str, geo.Punto]] = []

    for identificador, punto in etiquetas:
        contenedores = [p for p in sin_asignar if p.id is None and geo.contiene(p.anillo, punto)]
        if len(contenedores) == 1:
            contenedores[0].id = identificador
        else:
            pendientes.append((identificador, punto))

    for identificador, punto in pendientes:
        libres = [p for p in sin_asignar if p.id is None]
        if not libres:
            break
        cercano = min(libres, key=lambda p: geo.distancia(p.centroide, punto))
        if geo.distancia(cercano.centroide, punto) <= DISTANCIA_MAXIMA_ETIQUETA_M:
            cercano.id = identificador


def _leyenda(dibujo: _Dibujo) -> tuple[dict[str, int], list[ParcelaGeometrica]]:
    """Color → etapa, según el cuadrito de muestra junto a cada rótulo "ETAPA n".

    El cuadrito es un polígono chico sin lotes adentro y con el rótulo al lado, no
    adentro (eso descarta el recuadro que enmarca la leyenda completa). Devuelve
    también los cuadritos, que no son lotes.
    """
    if not dibujo.rotulos_etapa:
        return {}, []
    lotes = [punto for _, punto in dibujo.etiquetas]
    candidatas = [pg for pg in dibujo.poligonos
                  if pg.color and not any(geo.contiene(pg.anillo, p) for p in lotes)]

    leyenda: dict[str, int] = {}
    muestras: list[ParcelaGeometrica] = []
    for etapa, rotulo in dibujo.rotulos_etapa:
        al_lado = [pg for pg in candidatas if not geo.contiene(pg.anillo, rotulo)]
        cercana = min(al_lado, key=lambda pg: geo.distancia(pg.centroide, rotulo), default=None)
        if cercana is not None and geo.distancia(cercana.centroide, rotulo) <= DISTANCIA_MAXIMA_LEYENDA_M:
            leyenda[cercana.color] = etapa
            muestras.append(cercana)
    return leyenda, muestras


def _asignar_etapas(parcelas: list[ParcelaGeometrica], leyenda: dict[str, int]) -> None:
    if not leyenda:
        return
    for parcela in parcelas:
        parcela.etapa = leyenda.get(parcela.color) if parcela.color else None
        if parcela.id and parcela.etapa is not None:
            parcela.id = f"{parcela.etapa}-{parcela.id}"


def _revisar_repetidos(parcelas: list[ParcelaGeometrica]) -> None:
    conteo = Counter(p.id for p in parcelas if p.id)
    repetidos = sorted(identificador for identificador, veces in conteo.items() if veces > 1)
    if repetidos:
        raise ValueError(
            f"el KMZ tiene lotes repetidos ({', '.join(repetidos[:10])}"
            f"{', ...' if len(repetidos) > 10 else ''}). Si el loteo tiene etapas, la "
            f"leyenda necesita un cuadrito de cada color junto a su rótulo 'ETAPA n' "
            f"para poder separarlas.")
