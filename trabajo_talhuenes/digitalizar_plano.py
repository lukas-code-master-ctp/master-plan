"""Reconstruye los polígonos de las 62 parcelas de Talhuenes desde el plano escaneado.

Contexto: el KMZ del proyecto trae solo el perímetro del predio (un polígono), y el
único trazado de la subdivisión está en un plano de papel firmado y escaneado, sin
vectores y "sin escala". Este script lo digitaliza y emite un KMZ con el formato que
espera `pipeline/kmz.py`: un polígono y un punto rotulado por lote.

Es un rescate, no parte del sistema. Si el topógrafo entrega el DWG o el KMZ de la
subdivisión, este script sobra: se reemplaza el KMZ y el pipeline regenera solo.

Cómo funciona
-------------
1.  El escaneo sale del PDF como JPEG (300 DPI), no se rerasteriza.
2.  Se aísla la tinta *negra*: las servidumbres están dibujadas en azul y naranjo
    sobre las mismas aristas y ensucian la segmentación.
3.  Las líneas se dilatan para sellar los cortes del escaneo; cada lote queda como
    una región de fondo cerrada. Con 3 iteraciones salen exactamente 62.
4.  Cada región se asocia a su número por cercanía a una tabla de centroides
    verificada a mano contra las etiquetas impresas (ver CENTROS_LOTE).
5.  El plano se lleva a coordenadas con una homografía ajustada entre las 6 esquinas
    del predio en el dibujo y las 6 del perímetro del KMZ.

Precisión
---------
El ajuste da del orden de 4-5 m RMS contra el perímetro de referencia. Ese perímetro
fue trazado a mano en Google Earth y declara 30,39 ha donde el plano dice 32,22, así
que el error real está acotado por la referencia, no por el dibujo.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import cv2
import numpy as np

AQUI = Path(__file__).resolve().parent

# Recorte del escaneo que contiene el dibujo, ya rotado a horizontal.
RECORTE = (1005, 2400, 275, 3500)          # y0, y1, x0, x1
TAPAR = ((0, 235, 0, 1100),                # cuadro de superficies
         (0, 150, 2050, 2550))             # rosa de los vientos

UMBRAL_OSCURO = 175       # un píxel es tinta si su canal máximo baja de esto
UMBRAL_SATURACION = 60    # ...y si es acromático: descarta el azul y el naranjo
DILATACIONES = 3          # sella los cortes del escaneo sin fusionar lotes vecinos
AREA_CELDA = (9000, 90000)

# Centroide aproximado de cada lote en el recorte, verificado contra las etiquetas
# impresas del plano. Sirve para nombrar las regiones sin depender del OCR, que en
# un escaneo de esta calidad solo acierta unas 50 de 62.
CENTROS_LOTE = {
    1: (166, 890), 2: (152, 1179), 3: (307, 886), 4: (295, 1168), 5: (449, 878),
    6: (441, 1158), 7: (592, 873), 8: (587, 1148), 9: (732, 868), 10: (736, 1140),
    11: (874, 862), 12: (887, 1130), 13: (1016, 855), 14: (1043, 1119), 15: (1158, 849),
    16: (1199, 1111), 17: (1303, 857), 18: (1356, 1095), 19: (1467, 829), 20: (1512, 1079),
    21: (1617, 815), 22: (1665, 1066), 23: (1769, 801), 24: (1815, 1053), 25: (1926, 787),
    26: (1963, 1040), 27: (2084, 773), 28: (2111, 1024), 29: (2246, 757), 30: (2259, 1008),
    31: (2410, 742), 32: (2409, 992), 33: (2576, 725), 34: (2560, 975), 35: (2741, 710),
    36: (2715, 956), 37: (2897, 978), 38: (2928, 803), 39: (2948, 626), 40: (2971, 448),
    41: (2761, 501), 42: (2583, 512), 43: (2411, 521), 44: (2242, 533), 45: (2080, 543),
    46: (1921, 553), 47: (1766, 562), 48: (1615, 571), 49: (1471, 581), 50: (1319, 608),
    51: (1330, 334), 52: (1476, 319), 53: (1629, 316), 54: (1785, 311), 55: (1941, 306),
    56: (2104, 302), 57: (2269, 299), 58: (2439, 296), 59: (2612, 290), 60: (2790, 283),
    61: (2989, 268), 62: (3095, 624),
}


# --- lectura de las fuentes --------------------------------------------------

def escaneo_del_pdf(ruta: Path) -> np.ndarray:
    """Devuelve el escaneo del plano, rotado a horizontal.

    El PDF es una hoja carta vertical con el dibujo apaisado adentro. La imagen va
    embebida como JPEG, así que se extrae tal cual en vez de rasterizar la página.
    """
    from pypdf import PdfReader

    for pagina in PdfReader(str(ruta)).pages:
        recursos = pagina.get("/Resources").get_object()
        for objeto in recursos.get("/XObject", {}).get_object().values():
            objeto = objeto.get_object()
            if objeto.get("/Subtype") == "/Image" and "DCT" in str(objeto.get("/Filter")):
                datos = np.frombuffer(objeto.get_data(), np.uint8)
                imagen = cv2.imdecode(datos, cv2.IMREAD_COLOR)
                return cv2.rotate(imagen, cv2.ROTATE_90_CLOCKWISE)
    raise ValueError(f"{ruta.name}: no encontré el escaneo embebido")


def perimetro_del_kmz(ruta: Path) -> list[tuple[float, float]]:
    """Los vértices (lon, lat) del único polígono del KMZ: el borde del predio."""
    with zipfile.ZipFile(ruta) as archivo:
        nombre = next(n for n in archivo.namelist() if n.lower().endswith(".kml"))
        kml = archivo.read(nombre).decode("utf-8", "ignore")
    crudo = re.search(r"<coordinates>(.*?)</coordinates>", kml, re.S).group(1)
    puntos = [tuple(float(v) for v in t.split(",")[:2]) for t in crudo.split()]
    if len(puntos) > 2 and puntos[0] == puntos[-1]:
        puntos.pop()
    return puntos


# --- segmentación del dibujo -------------------------------------------------

def mascara_de_tinta(escaneo: np.ndarray) -> np.ndarray:
    """Solo la tinta negra del recorte: las líneas de lote y el borde del predio."""
    canales = escaneo.astype(int)
    maximo = canales.max(axis=2)
    rango = maximo - canales.min(axis=2)
    tinta = ((maximo < UMBRAL_OSCURO) & (rango < UMBRAL_SATURACION)).astype(np.uint8) * 255

    y0, y1, x0, x1 = RECORTE
    tinta = tinta[y0:y1, x0:x1].copy()
    for ty0, ty1, tx0, tx1 in TAPAR:
        tinta[ty0:ty1, tx0:tx1] = 0
    return tinta


def celdas_de_lote(tinta: np.ndarray) -> tuple[np.ndarray, list[dict]]:
    """Cada lote es una región de fondo encerrada por las líneas ya selladas."""
    sellada = cv2.dilate(tinta, np.ones((3, 3), np.uint8), iterations=DILATACIONES)
    cantidad, etiquetas, stats, centros = cv2.connectedComponentsWithStats(255 - sellada, 4)

    minima, maxima = AREA_CELDA
    celdas = [{"etiqueta": i, "cx": float(centros[i][0]), "cy": float(centros[i][1]),
               "area_px": int(stats[i, cv2.CC_STAT_AREA])}
              for i in range(1, cantidad)
              if minima <= stats[i, cv2.CC_STAT_AREA] <= maxima]
    return etiquetas, celdas


def asignar_lotes(celdas: list[dict]) -> dict[int, dict]:
    """Empareja cada región con su número de lote por cercanía al centroide conocido.

    Se resuelve como asignación mutua: cada lote se queda con la región más cercana
    que no haya sido tomada. Si algo no calza, es que la segmentación cambió y hay
    que revisarla, no seguir de largo.
    """
    pares = sorted(
        ((math.dist((c["cx"], c["cy"]), centro), lote, k)
         for lote, centro in CENTROS_LOTE.items()
         for k, c in enumerate(celdas)),
        key=lambda t: t[0])

    por_lote: dict[int, dict] = {}
    usadas: set[int] = set()
    for distancia, lote, k in pares:
        if lote in por_lote or k in usadas or distancia > 90:
            continue
        por_lote[lote] = celdas[k]
        usadas.add(k)

    faltan = sorted(set(CENTROS_LOTE) - set(por_lote))
    if faltan:
        raise ValueError(f"no encontré región para los lotes {faltan}; revisa la segmentación")
    return por_lote


def esquinas_del_predio(etiquetas: np.ndarray, celdas: list[dict]) -> np.ndarray:
    """Las 6 esquinas del predio en el dibujo, desde la unión de todos los lotes.

    Cerrar la unión salva los caminos interiores, y el contorno resultante simplifica
    de forma estable a 6 vértices: los mismos 6 del perímetro del KMZ.
    """
    union = np.zeros(etiquetas.shape, np.uint8)
    for celda in celdas:
        union[etiquetas == celda["etiqueta"]] = 255
    union = cv2.morphologyEx(union, cv2.MORPH_CLOSE, np.ones((80, 80), np.uint8))

    contornos, _ = cv2.findContours(union, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contorno = max(contornos, key=cv2.contourArea)
    aprox = cv2.approxPolyDP(contorno, 0.008 * cv2.arcLength(contorno, True), True)
    if len(aprox) != 6:
        raise ValueError(f"esperaba 6 esquinas del predio, salieron {len(aprox)}")
    return aprox.reshape(-1, 2).astype(float)


# --- georreferencia ----------------------------------------------------------

class Marco:
    """Plano local en metros centrado en el predio. Evita trabajar en grados."""

    def __init__(self, perimetro: list[tuple[float, float]]):
        self.lon0 = sum(p[0] for p in perimetro) / len(perimetro)
        self.lat0 = sum(p[1] for p in perimetro) / len(perimetro)
        radianes = math.radians(self.lat0)
        self.m_lat = 111132.92 - 559.82 * math.cos(2 * radianes) + 1.175 * math.cos(4 * radianes)
        self.m_lon = 111412.84 * math.cos(radianes) - 93.5 * math.cos(3 * radianes)

    def a_metros(self, lon: float, lat: float) -> tuple[float, float]:
        return (lon - self.lon0) * self.m_lon, (lat - self.lat0) * self.m_lat

    def a_grados(self, x: float, y: float) -> tuple[float, float]:
        return self.lon0 + x / self.m_lon, self.lat0 + y / self.m_lat


def ajustar_homografia(esquinas: np.ndarray, perimetro_m: np.ndarray) -> tuple[np.ndarray, float]:
    """Homografía dibujo → terreno, probando todas las correspondencias posibles.

    No se sabe de antemano con qué vértice del perímetro arranca el contorno ni en
    qué sentido lo recorre, así que se prueban los 12 emparejamientos y se elige el
    de menor residual. Con la correspondencia correcta el residual cae a metros; con
    cualquier otra queda en cientos.
    """
    mejor = None
    for invertir in (False, True):
        base = esquinas[::-1] if invertir else esquinas
        for giro in range(6):
            candidato = np.roll(base, giro, axis=0)
            homografia, _ = cv2.findHomography(
                candidato.reshape(-1, 1, 2), perimetro_m.reshape(-1, 1, 2), 0)
            if homografia is None:
                continue
            proyectado = cv2.perspectiveTransform(
                candidato.reshape(-1, 1, 2), homografia).reshape(-1, 2)
            rms = math.sqrt((np.hypot(*(proyectado - perimetro_m).T) ** 2).mean())
            if mejor is None or rms < mejor[1]:
                mejor = (homografia, rms)
    return mejor


# Al recortar los extremos de cada lado se deja fuera el redondeo de las esquinas,
# que es donde el trazo del plano y la dilatación ensucian más la recta.
RECORTE_LADO = 0.18


def _cuatro_esquinas(contorno: np.ndarray) -> np.ndarray:
    """Reduce el contorno de una celda a las 4 esquinas del lote.

    Los lotes son cuadriláteros: el contorno crudo del raster traía hasta 11
    vértices, con muescas de las líneas de servidumbre y el dentado del escaneo.

    No basta con simplificar hasta que queden 4 puntos, porque esos 4 salen de
    píxeles concretos del borde y arrastran su ruido. Se ajusta una recta a cada
    lado usando todos sus píxeles y se intersectan de a pares: cada esquina queda
    determinada por cientos de puntos en vez de uno, y con precisión sub-píxel.
    """
    casco = cv2.convexHull(contorno)          # los lotes son convexos
    puntos = casco.reshape(-1, 2).astype(float)

    # Semilla: simplificar hasta quedarse justo con 4 vértices.
    perimetro = cv2.arcLength(casco, True)
    bajo, alto = 0.0, 0.25
    semilla = None
    for _ in range(40):
        medio = (bajo + alto) / 2
        aprox = cv2.approxPolyDP(casco, medio * perimetro, True)
        if len(aprox) > 4:
            bajo = medio
        else:
            alto = medio
            if len(aprox) == 4:
                semilla = aprox.reshape(-1, 2).astype(float)
    if semilla is None:
        return cv2.boxPoints(cv2.minAreaRect(casco)).astype(float)

    # Cada lado se queda con los puntos del casco que caen entre sus dos esquinas.
    indices = [int(np.argmin(np.hypot(*(puntos - esquina).T))) for esquina in semilla]
    rectas = []
    total = len(puntos)
    for i in range(4):
        desde, hasta = indices[i], indices[(i + 1) % 4]
        largo = (hasta - desde) % total or total
        lado = np.array([puntos[(desde + k) % total] for k in range(largo + 1)])
        recorte = int(len(lado) * RECORTE_LADO)
        if len(lado) - 2 * recorte >= 2:
            lado = lado[recorte:len(lado) - recorte]
        if len(lado) >= 2:
            vx, vy, x0, y0 = cv2.fitLine(lado.astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).ravel()
        else:
            (x0, y0), (x1, y1) = semilla[i], semilla[(i + 1) % 4]
            vx, vy = x1 - x0, y1 - y0
        rectas.append((float(vx), float(vy), float(x0), float(y0)))

    esquinas = []
    for i in range(4):
        vx1, vy1, x1, y1 = rectas[i - 1]
        vx2, vy2, x2, y2 = rectas[i]
        denominador = vx1 * vy2 - vy1 * vx2
        if abs(denominador) < 1e-9:          # lados paralelos: no hay intersección
            esquinas.append(semilla[i])
            continue
        t = ((x2 - x1) * vy2 - (y2 - y1) * vx2) / denominador
        esquinas.append([x1 + t * vx1, y1 + t * vy1])
    return np.array(esquinas, float)


def poligonos_en_metros(etiquetas: np.ndarray, por_lote: dict[int, dict],
                        homografia: np.ndarray) -> dict[int, np.ndarray]:
    """Los 4 vértices de cada lote, llevados al plano local en metros.

    Se dilata cada región para recuperar el ancho de la línea que la separa de su
    vecina; si no, los lotes quedan con una franja muerta entre medio.
    """
    poligonos = {}
    for lote, celda in sorted(por_lote.items()):
        mascara = (etiquetas == celda["etiqueta"]).astype(np.uint8) * 255
        mascara = cv2.dilate(mascara, np.ones((3, 3), np.uint8), iterations=2)
        contornos, _ = cv2.findContours(mascara, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        esquinas = _cuatro_esquinas(max(contornos, key=cv2.contourArea))
        poligonos[lote] = cv2.perspectiveTransform(
            esquinas.reshape(-1, 1, 2), homografia).reshape(-1, 2)
    return poligonos


def area_m2(anillo: np.ndarray) -> float:
    x, y = anillo[:, 0], anillo[:, 1]
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2


# --- salida ------------------------------------------------------------------

def escribir_kmz(destino: Path, poligonos: dict[int, np.ndarray], marco: Marco) -> None:
    """KMZ con un polígono y un punto rotulado por lote, como lo espera kmz.py."""
    partes = ['<?xml version="1.0" encoding="UTF-8"?>',
              '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
              '<name>Talhuenes Quella - 62 lotes</name>']
    for lote, anillo in sorted(poligonos.items()):
        grados = [marco.a_grados(x, y) for x, y in anillo]
        cerrado = grados + [grados[0]]
        coordenadas = " ".join(f"{lon:.7f},{lat:.7f},0" for lon, lat in cerrado)
        centro = (sum(p[0] for p in grados) / len(grados), sum(p[1] for p in grados) / len(grados))
        nombre = escape(f"LOTE {lote}")
        partes.append(
            f"<Placemark><name>{nombre}</name><Polygon><outerBoundaryIs><LinearRing>"
            f"<coordinates>{coordenadas}</coordinates></LinearRing></outerBoundaryIs>"
            f"</Polygon></Placemark>")
        partes.append(
            f"<Placemark><name>{nombre}</name><Point>"
            f"<coordinates>{centro[0]:.7f},{centro[1]:.7f},0</coordinates></Point></Placemark>")
    partes.append("</Document></kml>")

    kml = "\n".join(partes)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as archivo:
        archivo.writestr("doc.kml", kml)


def main() -> None:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--plano", type=Path,
                            default=Path.home() / "Downloads/Plano Talhuenes servicios firmado.pdf")
    analizador.add_argument("--perimetro", type=Path,
                            default=Path.home() / "Downloads/Talhuenes Quella Subdividido 30 Ha (1).kmz")
    analizador.add_argument("--salida", type=Path, default=AQUI / "talhuenes_lotes.kmz")
    args = analizador.parse_args()

    escaneo = escaneo_del_pdf(args.plano)
    tinta = mascara_de_tinta(escaneo)
    etiquetas, celdas = celdas_de_lote(tinta)
    print(f"regiones de lote encontradas: {len(celdas)}")

    por_lote = asignar_lotes(celdas)
    print(f"lotes identificados: {len(por_lote)}")

    perimetro = perimetro_del_kmz(args.perimetro)
    marco = Marco(perimetro)
    perimetro_m = np.array([marco.a_metros(lon, lat) for lon, lat in perimetro])
    esquinas = esquinas_del_predio(etiquetas, celdas)
    homografia, rms = ajustar_homografia(esquinas, perimetro_m)
    print(f"homografia ajustada: RMS {rms:.2f} m en las 6 esquinas")

    poligonos = poligonos_en_metros(etiquetas, por_lote, homografia)
    areas = {lote: area_m2(anillo) for lote, anillo in poligonos.items()}
    total = sum(areas.values())
    print(f"superficie de los 62 lotes: {total / 10000:.2f} ha  "
          f"(perimetro del KMZ: {area_m2(perimetro_m) / 10000:.2f} ha)")
    print(f"por lote: minimo {min(areas.values()):.0f} m2, "
          f"mediana {sorted(areas.values())[len(areas) // 2]:.0f} m2, "
          f"maximo {max(areas.values()):.0f} m2")

    escribir_kmz(args.salida, poligonos, marco)
    print(f"KMZ escrito en {args.salida}")

    resumen = {str(lote): {"area_m2": round(areas[lote]), "vertices": len(poligonos[lote])}
               for lote in sorted(poligonos)}
    (args.salida.parent / "resumen_lotes.json").write_text(
        json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
