"""El geo del loteo: un PDF con el satélite, los lotes y las disponibles pintadas.

Es la lámina que las loteadoras mandan a sus vendedores y corredores, y que hasta
ahora alguien pintaba a mano cada vez que se vendía algo: todos los lotes con borde
amarillo y su nombre, y los disponibles rellenos en celeste. Acá sale del mismo
`parcelas.json` que lee el visor, así que dice lo mismo que el sitio y queda al día
cada vez que cambia el inventario (a mano o desde Cierra).

El satélite va como imagen y lo demás como dibujo vectorial: los rótulos de los lotes
chicos se leen acercando el PDF, como en el geo hecho a mano.

    python -m pipeline.geo_pintado <carpeta-del-sitio>   →  <sitio>/geo.pdf
"""
from __future__ import annotations

import argparse
import io
import math
import os
import sys
import tempfile
import urllib.request
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import pymupdf
from PIL import Image
from shapely.geometry import Polygon

from . import config
from .terreno import a_pixel_global

ARCHIVO = "geo.pdf"
URL_SATELITE = ("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/"
                "MapServer/tile/{z}/{y}/{x}")
ATRIBUCION = "Imágenes © Esri, Maxar, Earthstar Geographics"
LADO_TESELA = 256
ZOOM_MAXIMO = 19
# Más píxeles no se notan impresos en A3 y engordan el PDF que se manda por WhatsApp.
LADO_MAXIMO_PX = 4096
MARGEN = 0.05

# A3 apaisado, en puntos: el formato del geo que ya usan.
ANCHO_PAGINA = 1190.55
ALTO_ENCABEZADO = 58.0
ALTO_PIE = 16.0

AMARILLO = (1.0, 0.92, 0.0)
DORADO = (0.72, 0.56, 0.0)
CELESTE = (0.0, 0.9, 1.0)
AZUL_AGUA = (0.23, 0.61, 1.0)
TINTA = (0.11, 0.10, 0.09)
TINTA_SUAVE = (0.42, 0.40, 0.35)
TEXTO_SOBRE_CELESTE = (0.05, 0.13, 0.25)
# Rótulos de los lotes: a lo más 5 pt, y holgados dentro del lote (la mitad del largo
# y un tercio del ancho) para que no tapen bordes ni satélite.
TAMANO_ROTULO_MAX = 5.0
PROPORCION_LARGO = 0.5
PROPORCION_ANCHO = 0.33

Teselas = Callable[[int, int, int], bytes | None]


def generar(datos: dict, destino: Path, teselas: Teselas | None) -> Path:
    """Escribe el geo de `datos` (un parcelas.json ya leído) en `destino`.

    `teselas(z, x, y)` entrega el JPEG/PNG del satélite o None; sin teselas el geo
    sale sobre fondo liso, que sigue sirviendo para saber qué está disponible.
    """
    con_forma = [p for p in datos.get("parcelas", []) if p.get("poligono")]
    if not con_forma:
        raise ValueError("el loteo no tiene parcelas con polígono")
    anillos = [p["poligono"] for p in con_forma]
    anillos += [o["poligono"] for o in datos.get("otros_poligonos", []) if o.get("poligono")]

    zoom, caja = _encuadre(anillos)
    x0, y0, x1, y1 = caja
    escala = ANCHO_PAGINA / (x1 - x0)
    alto_mapa = (y1 - y0) * escala
    documento = pymupdf.open()
    pagina = documento.new_page(width=ANCHO_PAGINA, height=ALTO_ENCABEZADO + alto_mapa + ALTO_PIE)
    marco = pymupdf.Rect(0, ALTO_ENCABEZADO, ANCHO_PAGINA, ALTO_ENCABEZADO + alto_mapa)

    def a_pagina(punto) -> pymupdf.Point:
        x, y = a_pixel_global((punto[0], punto[1]), zoom)
        return pymupdf.Point((x - x0) * escala, ALTO_ENCABEZADO + (y - y0) * escala)

    satelite = _satelite(zoom, caja, teselas) if teselas else None
    if satelite is not None:
        pagina.insert_image(marco, stream=satelite)
        borde, rotulo = AMARILLO, AMARILLO
    else:
        # Sobre fondo claro el amarillo no se lee: el mismo dibujo, en tonos oscuros.
        pagina.draw_rect(marco, color=None, fill=(0.95, 0.94, 0.92))
        borde, rotulo = DORADO, TINTA

    forma = pagina.new_shape()
    for otro in datos.get("otros_poligonos", []):
        forma.draw_polyline([a_pagina(p) for p in otro["poligono"]] + [a_pagina(otro["poligono"][0])])
    forma.finish(color=borde, width=0.5, closePath=True, stroke_opacity=0.8)
    for agua in datos.get("aguas", []):
        if len(agua.get("linea", [])) > 1:
            forma.draw_polyline([a_pagina(p) for p in agua["linea"]])
            forma.finish(color=AZUL_AGUA, width=1.6, closePath=False)
    # Primero el relleno de las disponibles y después todos los bordes encima, para
    # que el amarillo no quede tapado por el celeste del lote vecino.
    disponibles = [p for p in con_forma if p.get("estado") == "disponible"]
    for parcela in disponibles:
        forma.draw_polyline(_cerrado([a_pagina(p) for p in parcela["poligono"]]))
        forma.finish(color=None, fill=CELESTE, fill_opacity=0.55, closePath=True)
    for parcela in con_forma:
        forma.draw_polyline(_cerrado([a_pagina(p) for p in parcela["poligono"]]))
        forma.finish(color=borde, width=0.6, closePath=True)
    forma.commit()

    rotulos = [(_ubicar([a_pagina(p) for p in parcela["poligono"]],
                        _nombre(parcela)), parcela) for parcela in con_forma]
    tamano = _tamano_comun([ubicacion for ubicacion, _ in rotulos if ubicacion])
    for ubicacion, parcela in rotulos:
        if ubicacion:
            _rotular(pagina, ubicacion, _nombre(parcela), tamano,
                     TEXTO_SOBRE_CELESTE if parcela.get("estado") == "disponible" else rotulo)

    _encabezado(pagina, datos, len(disponibles), len(con_forma) - len(disponibles))
    pagina.insert_text((12, pagina.rect.height - 4.5),
                       ATRIBUCION if satelite is not None else "Sin imagen satelital",
                       fontsize=6.5, fontname="helv", color=TINTA_SUAVE)

    documento.set_metadata({"title": f"Geo {datos.get('proyecto') or ''}".strip(),
                            "creator": "Tu Masterplan"})
    destino.parent.mkdir(parents=True, exist_ok=True)
    # Todo o nada: el sitio publicado y la consola nunca entregan un PDF a medias.
    with tempfile.NamedTemporaryFile(dir=destino.parent, prefix=".geo-", suffix=".tmp",
                                     delete=False) as temporal:
        temporal.write(documento.tobytes(garbage=3, deflate=True))
    os.replace(temporal.name, destino)
    return destino


def _cerrado(puntos: list) -> list:
    return puntos + puntos[:1]


def _nombre(parcela: dict) -> str:
    """"LOTE A42", como en el geo que ya circula: el id del inventario, que es como
    lo llaman Cierra y los vendedores."""
    identificador = str(parcela.get("id") or parcela.get("rotulo") or "").upper()
    return identificador if identificador.startswith("LOTE") else f"LOTE {identificador}"


def _encuadre(anillos: list[list]) -> tuple[int, tuple[float, float, float, float]]:
    """El zoom más fino en que el loteo cabe en LADO_MAXIMO_PX, y su caja en píxeles
    de ese zoom, con un margen alrededor."""
    lons = [p[0] for anillo in anillos for p in anillo]
    lats = [p[1] for anillo in anillos for p in anillo]
    for zoom in range(ZOOM_MAXIMO, 0, -1):
        xa, ya = a_pixel_global((min(lons), max(lats)), zoom)
        xb, yb = a_pixel_global((max(lons), min(lats)), zoom)
        margen = MARGEN * max(xb - xa, yb - ya, 1.0)
        caja = (xa - margen, ya - margen, xb + margen, yb + margen)
        if max(caja[2] - caja[0], caja[3] - caja[1]) <= LADO_MAXIMO_PX:
            return zoom, caja
    raise ValueError("el loteo es demasiado grande para un geo")


def _satelite(zoom: int, caja, teselas: Teselas) -> bytes | None:
    """El satélite recortado a la caja, en JPEG. None si no llegó ninguna tesela."""
    x0, y0, x1, y1 = caja
    tx0, ty0 = int(x0 // LADO_TESELA), int(y0 // LADO_TESELA)
    tx1, ty1 = int(x1 // LADO_TESELA), int(y1 // LADO_TESELA)
    mosaico = Image.new("RGB", ((tx1 - tx0 + 1) * LADO_TESELA, (ty1 - ty0 + 1) * LADO_TESELA),
                        (232, 230, 225))
    llegaron = 0
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            crudo = teselas(zoom, tx, ty)
            if not crudo:
                continue
            try:
                tesela = Image.open(io.BytesIO(crudo)).convert("RGB")
            except OSError:
                continue
            mosaico.paste(tesela, ((tx - tx0) * LADO_TESELA, (ty - ty0) * LADO_TESELA))
            llegaron += 1
    if not llegaron:
        return None
    desde_x, desde_y = x0 - tx0 * LADO_TESELA, y0 - ty0 * LADO_TESELA
    recorte = mosaico.crop((round(desde_x), round(desde_y),
                            round(desde_x + x1 - x0), round(desde_y + y1 - y0)))
    salida = io.BytesIO()
    recorte.save(salida, "JPEG", quality=82, optimize=True)
    return salida.getvalue()


def _ubicar(puntos: list, texto: str):
    """Dónde y cuánto cabe el nombre dentro del lote: (centro, ángulo, tamaño máximo).

    El tamaño máximo es lo que entra holgado, no lo que llena el lote: un rótulo que
    ocupa todo el lote tapa los bordes y el satélite, que es lo que se vino a mirar.
    """
    try:
        poligono = Polygon([(p.x, p.y) for p in puntos]).buffer(0)
    except ValueError:
        return None
    if poligono.is_empty or poligono.area <= 0:
        return None
    rect = list(poligono.minimum_rotated_rectangle.exterior.coords)[:4]
    lados = [(rect[i], rect[(i + 1) % 4]) for i in range(2)]
    largos = [math.dist(a, b) for a, b in lados]
    largo, corto = max(largos), min(largos)
    (ax, ay), (bx, by) = lados[largos.index(largo)]
    angulo = math.degrees(math.atan2(by - ay, bx - ax))
    # Siempre legible de izquierda a derecha, nunca de cabeza.
    if angulo > 90:
        angulo -= 180
    elif angulo <= -90:
        angulo += 180
    ancho_unitario = pymupdf.get_text_length(texto, fontname="helv", fontsize=1)
    maximo = min(corto * PROPORCION_ANCHO, largo * PROPORCION_LARGO / ancho_unitario)
    centro = poligono.representative_point() if not poligono.centroid.within(poligono) \
        else poligono.centroid
    return centro, angulo, maximo


def _tamano_comun(ubicaciones: list) -> float:
    """Un solo tamaño de letra para todo el loteo, como en un plano dibujado a mano.

    Sale de los lotes chicos (el percentil 25 de lo que cabe), así casi todos los
    rótulos quedan iguales y solo los lotes más angostos achican el suyo.
    """
    maximos = sorted(maximo for _, _, maximo in ubicaciones)
    if not maximos:
        return TAMANO_ROTULO_MAX
    return min(maximos[len(maximos) // 4], TAMANO_ROTULO_MAX)


def _rotular(pagina, ubicacion, texto: str, tamano_comun: float, color) -> None:
    """El nombre en el centro del lote, a lo largo de su lado largo.

    En los lotes angostos el texto queda chico, pero es vectorial: se lee acercando.
    """
    centro, angulo, maximo = ubicacion
    tamano = min(tamano_comun, maximo)
    if tamano < 0.6:
        return
    ancho_unitario = pymupdf.get_text_length(texto, fontname="helv", fontsize=1)
    fijo = pymupdf.Point(centro.x, centro.y)
    inicio = pymupdf.Point(centro.x - ancho_unitario * tamano / 2, centro.y + tamano * 0.35)
    # En la página la y crece hacia abajo, así que el giro va con el signo cambiado.
    pagina.insert_text(inicio, texto, fontsize=tamano, fontname="helv", color=color,
                       morph=(fijo, pymupdf.Matrix(-angulo)))


def _encabezado(pagina, datos: dict, disponibles: int, otras: int) -> None:
    pagina.draw_rect(pymupdf.Rect(0, 0, ANCHO_PAGINA, ALTO_ENCABEZADO), color=None, fill=(1, 1, 1))
    nombre = str(datos.get("proyecto") or "Loteo")
    etapa = datos.get("etapa")
    titulo = f"{nombre} · Etapa {etapa}" if etapa else nombre
    pagina.insert_text((16, 26), titulo, fontsize=17, fontname="hebo", color=TINTA)
    pagina.insert_text((16, 44), f"Disponibles al {fecha_legible(datos)}",
                       fontsize=9.5, fontname="helv", color=TINTA_SUAVE)

    # La leyenda, contra el borde derecho.
    entradas = [(f"Disponible ({disponibles})", CELESTE, 0.55),
                (f"Vendido, reservado o no disponible ({otras})", None, 0)]
    x = ANCHO_PAGINA - 16
    for texto, relleno, opacidad in reversed(entradas):
        ancho = pymupdf.get_text_length(texto, fontname="helv", fontsize=9.5)
        x -= ancho
        pagina.insert_text((x, 36), texto, fontsize=9.5, fontname="helv", color=TINTA)
        x -= 20
        muestra = pymupdf.Rect(x, 26, x + 14, 38)
        pagina.draw_rect(muestra, color=(0.75, 0.66, 0.0), fill=relleno,
                         fill_opacity=opacidad or 1, width=1.2)
        x -= 18
    pagina.draw_line((0, ALTO_ENCABEZADO), (ANCHO_PAGINA, ALTO_ENCABEZADO),
                     color=(0.85, 0.84, 0.81), width=0.8)


MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre")


def fecha_legible(datos: dict) -> str:
    """"27 de octubre de 2026, 14:05", en hora de Chile.

    La consola corre en UTC: sin convertir, el geo diría tres horas de diferencia.
    """
    crudo = datos.get("actualizado") or datos.get("generado")
    try:
        momento = datetime.fromisoformat(crudo) if crudo else datetime.now().astimezone()
    except ValueError:
        momento = datetime.now().astimezone()
    try:
        from zoneinfo import ZoneInfo
        momento = momento.astimezone(ZoneInfo("America/Santiago"))
    except Exception:  # sin la base de zonas horarias queda la hora con que se anotó
        pass
    return f"{momento.day} de {MESES[momento.month - 1]} de {momento.year}, {momento:%H:%M}"


def teselas_con_cache(cache: Path, url: str = URL_SATELITE, timeout: float = 20) -> Teselas:
    """Bajar del satélite solo lo que no está en `cache`: el geo se rehace cada vez que
    cambia un estado, pero el terreno no se mueve. Una tesela que no llega es None."""
    def tesela(z: int, x: int, y: int) -> bytes | None:
        ruta = cache / str(z) / f"{x}_{y}.jpg"
        if ruta.exists():
            return ruta.read_bytes()
        try:
            peticion = urllib.request.Request(url.format(z=z, x=x, y=y),
                                              headers={"User-Agent": "TuMasterplan/1.0"})
            with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
                datos = respuesta.read()
        except Exception:
            return None
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(datos)
        return datos
    return tesela


def cache_satelite() -> Path:
    return config._CACHE / "satelite"


def teselas_del_entorno() -> Teselas | None:
    """El satélite, salvo con `MASTERPLAN_SATELITE=0` (las pruebas, y donde no haya red)."""
    if os.environ.get("MASTERPLAN_SATELITE", "1").strip() == "0":
        return None
    return teselas_con_cache(cache_satelite())


def al_dia(sitio: Path, teselas: Teselas | None) -> Path:
    """El geo del sitio, rehecho solo si el inventario es más nuevo que él.

    Así el que se descarga desde la consola dice lo mismo que el sitio aunque los
    estados hayan cambiado con "Actualizar desde Cierra" o una planilla nueva.
    """
    import json
    archivo = sitio / "datos" / "parcelas.json"
    destino = sitio / ARCHIVO
    if destino.exists() and destino.stat().st_mtime >= archivo.stat().st_mtime:
        return destino
    return generar(json.loads(archivo.read_text(encoding="utf-8")), destino, teselas)


def main(argv: list[str] | None = None) -> int:
    import json
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sitio", type=Path, help="carpeta del sitio construido")
    parser.add_argument("--sin-satelite", action="store_true")
    args = parser.parse_args(argv)
    archivo = args.sitio / "datos" / "parcelas.json"
    if not archivo.is_file():
        print(f"{args.sitio} no es un sitio construido: falta datos/parcelas.json", file=sys.stderr)
        return 1
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    teselas = None if args.sin_satelite else teselas_del_entorno()
    try:
        print(generar(datos, args.sitio / ARCHIVO, teselas))
    except Exception as error:
        # Va encadenado antes de publicar: un geo que no sale no puede dejar el
        # sitio sin sus estados nuevos. Queda el geo anterior, si había.
        print(f"No se pudo hacer el geo: {type(error).__name__}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
