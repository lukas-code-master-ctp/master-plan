"""Las fuentes de un loteo de mentira, hechas con código.

"Praderas Demo" tiene dos etapas de seis lotes de 70 × 70 m, cerca de Cauquenes.
Nada de esto vive en el repo como binario: el KMZ, la planilla y las panorámicas se
escriben al sembrar, con la misma forma que usan las pruebas del pipeline.

- El KMZ trae un polígono por lote con su punto "LOTE n" adentro, y cada etapa con
  su color. La leyenda (un cuadrito de cada color junto a su rótulo "ETAPA n") es lo
  que le dice a `pipeline.kmz` qué color es cada etapa, así que los ids quedan
  "1-1".."1-6" y "2-1".."2-6", como en un loteo real con etapas.
- La planilla es el `inventario.csv` que deja la consola al sincronizar con Cierra,
  con los mismos estados y precios de `qa.cierra_falsa`: sembrar y sincronizar dan
  el mismo loteo.
- Las panorámicas son grises lisas con el sol donde corresponde, para que el rumbo
  se resuelva igual que en un vuelo de verdad.
"""
from __future__ import annotations

import csv
import zipfile
from datetime import datetime
from pathlib import Path

from consola.cierra import COLUMNAS, ETIQUETAS
from pipeline import geo
from pipeline.sintetico import escribir_panorama
from pipeline.solar import posicion_solar

from .cierra_falsa import PARCELAS

LAT, LON = -34.7975, -72.0030
LADO_M = 70
COLUMNAS_POR_ETAPA = 3
FILAS_POR_ETAPA = 2
# Entre una etapa y la otra queda un camino.
CAMINO_M = 12
# Colores KML (aabbggrr): verde la etapa 1, naranjo la 2.
COLORES = {1: "FF3C9F2E", 2: "FF1E7FF0"}
PARCELACION = "PRADERAS DEMO"

ANCHO_PANORAMA = 2048
MOMENTO_VUELO = "2026-03-05T19:05:15-03:00"
# Hacia dónde mira el borde izquierdo de la foto: el sol se dibuja según esto.
RUMBO_FOTO = 137.0
# Distintas a propósito, además de ser lo esperable en dos puntos del vuelo: la
# consola cuenta las fotos por nombre y tamaño, y dos JPEG iguales en todo menos en
# la posición del sol pueden pesar lo mismo y contarse como una.
ALTURAS_ABSOLUTAS = {1: 185.2, 2: 185.35}


# --- KMZ ------------------------------------------------------------------------

def _desplazar(este_m: float, norte_m: float) -> geo.Punto:
    """(lon, lat) a tantos metros del centro del loteo."""
    return (LON + este_m / geo.metros_por_grado_lon(LAT),
            LAT + norte_m / geo.METROS_POR_GRADO_LAT)


def _cuadrado(este: float, norte: float, lado: float) -> list[geo.Punto]:
    return [_desplazar(este, norte), _desplazar(este + lado, norte),
            _desplazar(este + lado, norte + lado), _desplazar(este, norte + lado)]


def _coordenadas(puntos: list[geo.Punto]) -> str:
    cerrado = puntos + puntos[:1]
    return " ".join(f"{lon:.10f},{lat:.10f},0" for lon, lat in cerrado)


def _poligono(puntos: list[geo.Punto], etapa: int) -> str:
    return (f"<Placemark><styleUrl>#etapa{etapa}</styleUrl><Polygon><outerBoundaryIs>"
            f"<LinearRing><coordinates>{_coordenadas(puntos)}</coordinates></LinearRing>"
            f"</outerBoundaryIs></Polygon></Placemark>")


def _punto(nombre: str, lonlat: geo.Punto) -> str:
    return (f"<Placemark><name>{nombre}</name><Point><coordinates>"
            f"{lonlat[0]:.10f},{lonlat[1]:.10f},0</coordinates></Point></Placemark>")


def lotes() -> list[tuple[int, int, list[geo.Punto]]]:
    """(etapa, número, anillo) de los doce lotes. La etapa 1 al poniente, la 2 al
    oriente, cada una de 3 × 2 lotes numerados de poniente a oriente y de norte a sur."""
    ancho_etapa = COLUMNAS_POR_ETAPA * LADO_M
    total_este = 2 * ancho_etapa + CAMINO_M
    oeste, sur = -total_este / 2, -FILAS_POR_ETAPA * LADO_M / 2
    resultado = []
    for etapa in (1, 2):
        inicio = oeste + (etapa - 1) * (ancho_etapa + CAMINO_M)
        numero = 0
        for fila in range(FILAS_POR_ETAPA):
            norte = sur + (FILAS_POR_ETAPA - 1 - fila) * LADO_M
            for columna in range(COLUMNAS_POR_ETAPA):
                numero += 1
                resultado.append((etapa, numero,
                                  _cuadrado(inicio + columna * LADO_M, norte, LADO_M)))
    return resultado


def centro_de_etapa(etapa: int) -> geo.Punto:
    anillos = [anillo for e, _, anillo in lotes() if e == etapa]
    puntos = [p for anillo in anillos for p in anillo]
    return (sum(p[0] for p in puntos) / len(puntos), sum(p[1] for p in puntos) / len(puntos))


def kml() -> str:
    estilos = "".join(
        f'<Style id="etapa{etapa}"><LineStyle><color>{color}</color><width>2</width></LineStyle>'
        f'<PolyStyle><color>00000000</color><fill>0</fill></PolyStyle></Style>'
        for etapa, color in COLORES.items())
    cuerpo = []
    for etapa, numero, anillo in lotes():
        cuerpo.append(_poligono(anillo, etapa))
        cuerpo.append(_punto(f"LOTE {numero}", geo.centroide(anillo)))
    # La leyenda, al sur del loteo: un cuadrito de 15 m de cada color y su rótulo al lado.
    sur = -FILAS_POR_ETAPA * LADO_M / 2 - 60
    for etapa in COLORES:
        este = -60 + (etapa - 1) * 90
        cuerpo.append(_poligono(_cuadrado(este, sur, 15), etapa))
        cuerpo.append(_punto(f"ETAPA {etapa}", _desplazar(este + 35, sur + 7)))
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<name>Praderas Demo</name>{estilos}{''.join(cuerpo)}</Document></kml>")


def escribir_kmz(ruta: Path) -> Path:
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as archivo:
        archivo.writestr("doc.kml", kml())
    return ruta


# --- planilla ---------------------------------------------------------------------

def escribir_planilla(ruta: Path) -> Path:
    """El inventario con las columnas que escribe la consola al sincronizar con Cierra
    (`COLUMNAS`), una parcelación por etapa ("… ET1", "… ET2")."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(COLUMNAS)
        for parcela in PARCELAS:
            escritor.writerow((
                parcela["numero"],
                f"{PARCELACION} ET{parcela['proyecto_id']}",
                ETIQUETAS[parcela["estado"]],
                "" if parcela["precio"] is None else parcela["precio"],
                parcela["moneda"],
                parcela["superficie_m2"],
                "" if parcela["servidumbre_m2"] is None else parcela["servidumbre_m2"],
            ))
    return ruta


# --- panorámicas ------------------------------------------------------------------

def escribir_panoramas(carpeta: Path) -> list[Path]:
    """Una panorámica a 100 m sobre el centro de cada etapa, en
    `POSICION 0n/100 METROS.JPG` como las deja el piloto."""
    carpeta = Path(carpeta)
    momento = datetime.fromisoformat(MOMENTO_VUELO)
    rutas = []
    for etapa in (1, 2):
        lon, lat = centro_de_etapa(etapa)
        sol = posicion_solar(momento, lat, lon)
        sol_x = int(((sol.azimut - RUMBO_FOTO) % 360) / 360 * ANCHO_PANORAMA)
        rutas.append(escribir_panorama(
            carpeta / f"POSICION 0{etapa}" / "100 METROS.JPG",
            lat=lat, lon=lon, relativa=100.2, absoluta=ALTURAS_ABSOLUTAS[etapa],
            momento=MOMENTO_VUELO,
            ancho=ANCHO_PANORAMA, sol_x=sol_x, sol_elevacion=sol.elevacion))
    return rutas


def escribir_fuentes(carpeta: Path) -> Path:
    """KMZ, planilla y panorámicas juntos, como quedan después de subirlos por la consola."""
    carpeta = Path(carpeta)
    escribir_kmz(carpeta / "subdivision.kmz")
    escribir_planilla(carpeta / "inventario.csv")
    escribir_panoramas(carpeta)
    return carpeta
