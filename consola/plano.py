"""Crea tu KMZ en la consola: el plano aprobado y lo que sale de él.

Un plano vive en la carpeta de un KMZ de Mis KMZ (`kmz/<slug>/`):

    plano.pdf            el PDF tal como llegó
    paginas/<n>.jpg      la imagen de cada página, sin rotar: sus píxeles son los
                         "píxeles de página" de `entradas.json`
    paginas/<n>_mini.jpg la miniatura para elegir página
    entradas.json        lo que marca la loteadora (formato en pipeline/plano/digitalizar.py)
    digitalizado.json    los lotes en píxeles (lo escribe el trabajo de fondo)
    georreferencia.json  la ubicación en el mapa, con residuo por ancla
    lotes.geojson        los lotes en lon/lat
    huellas.json         con qué entradas se hizo cada paso: dice qué quedó atrasado

El KMZ que sale de acá va a `destino_kmz` (`kmz/<slug>/<slug>.kmz`), que se rehace
sin preguntar porque es su propio archivo. Llevarlo a un master es otra cosa:
`proyectos.poner_kmz`.

Escrituras: aparte y `os.replace` al final, sin copystat ni chmod (`/datos` puede ser
un bucket montado con gcsfuse).

Los números de lote salen del lector de rótulos (`pipeline/plano/rotulos.py`, lo
llama `digitalizar`) y de los clics de la loteadora (`semillas`), que mandan. Con
lector se puede digitalizar sin ningún clic; sin él (no hay Tesseract en el servidor,
o la loteadora lo apagó) hace falta al menos un número marcado.
"""
from __future__ import annotations

import contextlib
import functools
import hashlib
import io
import json
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import BinaryIO

import numpy as np
import pymupdf
from PIL import Image
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from pipeline.kmz import normalizar_id
from pipeline.plano import pagina as pag
from pipeline.plano import rotulos
from pipeline.plano.digitalizar import ENTRADAS, SALIDA as DIGITALIZADO, escribir_json, leer_entradas
from pipeline.plano.georreferencia import GEOJSON, SALIDA as GEORREFERENCIA, Transformacion, georreferenciar
from pipeline.plano.salida import escribir_kmz, lotes_utm

PDF = "plano.pdf"
PAGINAS = "paginas"
HUELLAS = "huellas.json"

# Un plano del CBR trae una o dos láminas; más es otro documento.
MAX_PAGINAS = 12
# Un A0 escaneado a 300 dpi son ~140 MP. Más que esto, una página decodificada no
# cabe junto a lo demás en la memoria del servidor (y un PDF chico puede declarar
# una imagen enorme).
MAX_MEGAPIXELES = 200
LADO_MINI = 480
CALIDAD = 90

# Lo que cambia los lotes en píxeles. De la cuadrícula, solo dónde están las
# líneas: su valor impreso se puede corregir sin volver a digitalizar.
CLAVES_DIGITALIZAR = ("pdf", "pagina", "rotacion", "rectangulo", "mascaras", "esquinas", "marco_mm",
                      "semillas", "lector", "lector_apoyo_min", "cuadro")
CLAVES_UBICAR = ("anclas", "ajuste", "cuadricula")

# Topes de lo que se marca a mano: muy por sobre un loteo real, y lejos de lo que
# atora la revisión (las semillas repetidas se buscan de a pares).
TOPES = dict(semillas=2000, mascaras=200, anclas=50)
TOPE_CUADRICULA = 200

# Error de área contra el cuadro de superficies: verde ±2 %, ámbar ±5 %, rojo más.
VERDE, AMBAR = 0.02, 0.05


_CANDADOS: dict[str, threading.RLock] = {}
_CANDADO = threading.Lock()


def _a_solas(metodo):
    """Una escritura a la vez por plano: los temporales de `escribir_json` llevan el
    pid, que es el mismo para todos los hilos de la consola."""
    @functools.wraps(metodo)
    def envuelto(self, *args, **kwargs):
        with _CANDADO:
            candado = _CANDADOS.setdefault(str(self.carpeta), threading.RLock())
        with candado:
            return metodo(self, *args, **kwargs)
    return envuelto


class PlanoInvalido(Exception):
    """Lo que mandó la loteadora no sirve (400). El mensaje es para ella."""


class PlanoNoListo(Exception):
    """Falta un paso anterior (409)."""


@dataclass(frozen=True)
class Plano:
    """El plano en `carpeta` y el KMZ que sale de él en `destino_kmz`."""
    carpeta: Path
    destino_kmz: Path
    # El nombre que lleva el KMZ por dentro. Vacío = el de la carpeta.
    nombre: str | None = None

    @property
    def kmz(self) -> Path:
        """Dónde queda el KMZ que sale de este plano."""
        return self.destino_kmz

    def terminado(self) -> bool:
        return self.kmz.is_file()

    def hay(self) -> bool:
        return (self.carpeta / PDF).is_file()

    # --- páginas ------------------------------------------------------------------

    @_a_solas
    def subir_pdf(self, contenido: bytes | BinaryIO) -> list[dict]:
        """Guarda el PDF y extrae la imagen de cada página tal como viene (sin
        rerasterizar). Un PDF nuevo es otro plano: lo marcado sobre el anterior se borra,
        porque sus coordenadas eran de otras páginas."""
        flujo = io.BytesIO(contenido) if isinstance(contenido, (bytes, bytearray)) else contenido
        flujo.seek(0)
        # La cabecera puede venir tras basura, pero dentro del primer KB (ISO 32000).
        if b"%PDF-" not in flujo.read(1024):
            raise PlanoInvalido("el plano tiene que ser un PDF")
        flujo.seek(0)
        self.carpeta.mkdir(parents=True, exist_ok=True)
        temporal = self.carpeta / f".plano.{os.getpid()}.{threading.get_ident()}.pdf"
        listas = None
        try:
            with temporal.open("wb") as salida:
                shutil.copyfileobj(flujo, salida, length=4 * 1024 * 1024)
            total = _paginas_del_pdf(temporal)
            if total is None:
                raise PlanoInvalido("no se pudo abrir el PDF: ¿está dañado?")
            if not 1 <= total <= MAX_PAGINAS:
                raise PlanoInvalido(f"el PDF tiene {total} páginas; el plano trae a lo más {MAX_PAGINAS}")
            try:
                tamanos = _megapixeles(temporal)
            except Exception:               # noqa: BLE001 - ver `_paginas_del_pdf`
                tamanos = None
            if tamanos is None:
                raise PlanoInvalido("no se pudo abrir el PDF: ¿está dañado?")
            for n, megas in enumerate(tamanos, start=1):
                if megas > MAX_MEGAPIXELES:
                    raise PlanoInvalido(f"la página {n} es demasiado grande ({megas:.0f} megapíxeles;"
                                        f" el máximo es {MAX_MEGAPIXELES}): escanéala a menos resolución")
            # Las páginas se sacan aparte y el plano anterior se reemplaza recién al
            # final: un PDF que falla a medias no se lleva el que estaba. Archivo por
            # archivo, porque gcsfuse no deja renombrar carpetas.
            listas = self.carpeta / f".{PAGINAS}.{os.getpid()}.{threading.get_ident()}"
            listas.mkdir(exist_ok=True)
            hechas = []
            for n in range(1, total + 1):
                try:
                    hoja = pag.extraer(temporal, n)
                except (ValueError, RuntimeError) as error:
                    raise PlanoInvalido(f"no se pudo leer la página {n} del PDF") from error
                imagen = Image.fromarray(hoja.imagen)
                hoja.imagen = None
                (listas / f"{n}.jpg").write_bytes(_jpeg(imagen))
                ancho, alto = imagen.size
                imagen.thumbnail((LADO_MINI, LADO_MINI))
                (listas / f"{n}_mini.jpg").write_bytes(_jpeg(imagen, 80))
                del imagen
                hechas.append(dict(n=n, ancho=ancho, alto=alto))
            self._borrar_lo_derivado()
            paginas = self.carpeta / PAGINAS
            paginas.mkdir()
            for ruta in listas.iterdir():
                os.replace(ruta, paginas / ruta.name)
            os.replace(temporal, self.carpeta / PDF)
        finally:
            with contextlib.suppress(OSError):
                temporal.unlink(missing_ok=True)
            if listas is not None:
                shutil.rmtree(listas, ignore_errors=True)
        return hechas

    def _borrar_lo_derivado(self) -> None:
        for nombre in (PDF, ENTRADAS, DIGITALIZADO, GEORREFERENCIA, GEOJSON, HUELLAS):
            (self.carpeta / nombre).unlink(missing_ok=True)
        shutil.rmtree(self.carpeta / PAGINAS, ignore_errors=True)

    def paginas(self) -> list[dict]:
        carpeta = self.carpeta / PAGINAS
        if not self.hay() or not carpeta.is_dir():
            return []
        salida = []
        for ruta in carpeta.glob("*.jpg"):
            if ruta.stem.isdigit():
                with Image.open(ruta) as imagen:        # solo la cabecera
                    ancho, alto = imagen.size
                salida.append(dict(n=int(ruta.stem), ancho=ancho, alto=alto))
        return sorted(salida, key=lambda p: p["n"])

    def imagen(self, n: int, mini: bool = False) -> Path | None:
        ruta = self.carpeta / PAGINAS / (f"{n}_mini.jpg" if mini else f"{n}.jpg")
        return ruta if self.hay() and n >= 1 and ruta.is_file() else None

    # --- entradas -----------------------------------------------------------------

    def entradas(self) -> dict | None:
        if not (self.carpeta / ENTRADAS).is_file():
            return None
        return leer_entradas(self.carpeta)

    @_a_solas
    def guardar_entradas(self, entradas) -> dict:
        """Revisa con el mismo lector que usa el pipeline y guarda lo normalizado."""
        if not self.hay():
            raise PlanoNoListo("primero sube el PDF del plano")
        if not isinstance(entradas, dict):
            raise PlanoInvalido("las entradas son un objeto JSON")
        pdf = entradas.get("pdf")
        if pdf not in (None, "", PDF):
            if not isinstance(pdf, str) or _fuera(pdf):
                raise PlanoInvalido(f"«pdf» es un nombre dentro de la carpeta del plano, no {pdf!r}")
        for clave, tope in TOPES.items():
            if isinstance(entradas.get(clave), list) and len(entradas[clave]) > tope:
                raise PlanoInvalido(f"«{clave}» trae {len(entradas[clave])}; el máximo es {tope}")
        cuadricula = entradas.get("cuadricula")
        if isinstance(cuadricula, dict) and any(
                isinstance(cuadricula.get(f), list) and len(cuadricula[f]) > TOPE_CUADRICULA
                for f in ("verticales", "horizontales")):
            raise PlanoInvalido(f"la cuadrícula trae más de {TOPE_CUADRICULA} líneas por eje")
        # La consola guarda el plano siempre con el mismo nombre.
        entradas = dict(entradas, pdf=PDF)
        with tempfile.TemporaryDirectory() as prueba:
            (Path(prueba) / ENTRADAS).write_text(json.dumps(entradas, ensure_ascii=False), encoding="utf-8")
            try:
                normalizadas = leer_entradas(Path(prueba))
            except (ValueError, TypeError) as error:
                raise PlanoInvalido(str(error)) from error
        total = len(self.paginas())
        if not 1 <= normalizadas["pagina"] <= total:
            raise PlanoInvalido(f"el PDF tiene {total} páginas; no existe la {normalizadas['pagina']}")
        if normalizadas["rotacion"] % 90:
            raise PlanoInvalido(f"la rotación es 0, 90, 180 o 270 grados, no {normalizadas['rotacion']}")
        escribir_json(self.carpeta / ENTRADAS, normalizadas)
        return normalizadas

    # --- pasos ----------------------------------------------------------------------

    def para_digitalizar(self) -> str:
        """Revisa que se pueda digitalizar y devuelve la huella de las entradas, que
        se anota si el trabajo termina bien."""
        if not self.hay():
            raise PlanoNoListo("primero sube el PDF del plano")
        entradas = self._entradas_o_409()
        if not entradas["semillas"] and not _con_lector(entradas):
            raise PlanoNoListo("marca el número de al menos un lote antes de digitalizar"
                               + ("" if not entradas["lector"] else
                                  " (no hay lector de rótulos en este servidor)"))
        return huella_digitalizar(entradas)

    @_a_solas
    def anotar(self, paso: str, huella: str) -> None:
        huellas = self._huellas()
        huellas[paso] = huella
        escribir_json(self.carpeta / HUELLAS, huellas)

    @_a_solas
    def georreferenciar(self) -> dict:
        """Ubica los lotes (anclas o cuadrícula) y escribe georreferencia.json y
        lotes.geojson. Es rápido: corre en la petición."""
        entradas = self._entradas_o_409()
        if not (self.carpeta / DIGITALIZADO).is_file():
            raise PlanoNoListo("primero hay que digitalizar el plano")
        if not self._digitalizado_vigente(entradas):
            raise PlanoNoListo("cambiaste el dibujo o los números desde la última digitalización:"
                               " digitaliza de nuevo antes de ubicarlo")
        lineas: list[str] = []
        try:
            georreferenciar(self.carpeta, avance=lineas.append)
        except (ValueError, KeyError) as error:
            raise PlanoInvalido(str(error).strip("'\"")) from error
        except FileNotFoundError as error:
            raise PlanoNoListo(str(error)) from error
        self.anotar("georreferencia", huella_ubicar(entradas, self._huella_digitalizado(entradas)))
        return dict(resumen_georreferencia(self._leer(GEORREFERENCIA)), vigente=True, lineas=lineas)

    @_a_solas
    def crear_kmz(self) -> dict:
        """Escribe el KMZ. Es su propio archivo: se rehace sin preguntar."""
        entradas = self._entradas_o_409()
        if not (self.carpeta / GEORREFERENCIA).is_file():
            raise PlanoNoListo("primero hay que ubicar el plano en el mapa")
        if not self._georreferencia_vigente(entradas):
            raise PlanoNoListo("cambiaron las entradas desde que se ubicó el plano: digitaliza o ubica de nuevo")
        digitalizado = self._leer(DIGITALIZADO)
        t = Transformacion.desde_dict(self._leer(GEORREFERENCIA))
        try:
            # Aparte y `os.replace` al final: un error no se lleva el anterior.
            n = escribir_kmz(self.kmz, digitalizado, t, nombre=self.nombre or self.carpeta.name)
        except ValueError as error:
            raise PlanoInvalido(str(error)) from error
        self.anotar("kmz", self._huellas().get("georreferencia") or huella_ubicar(
            entradas, self._huella_digitalizado(entradas)))
        return dict(kmz=self.kmz.name, lotes=n)

    # --- lectura ----------------------------------------------------------------------

    def estado(self) -> dict:
        entradas, error = None, None
        try:
            entradas = self.entradas()
        except ValueError as e:
            error = str(e)
        digitalizado = georreferencia = None
        if (self.carpeta / DIGITALIZADO).is_file():
            d = self._leer(DIGITALIZADO)
            digitalizado = dict(
                lotes=len(d.get("lotes") or []), faltantes=d.get("faltantes") or [],
                sin_numero=len(d.get("sin_numero") or []), pagina=d.get("pagina"),
                cuadricula=d.get("cuadricula") is not None,
                segundos=(d.get("estadisticas") or {}).get("segundos"),
                lector=_resumen_lector(d.get("lector")),
                vigente=entradas is not None and self._digitalizado_vigente(entradas))
        if (self.carpeta / GEORREFERENCIA).is_file():
            georreferencia = dict(resumen_georreferencia(self._leer(GEORREFERENCIA)),
                                  vigente=entradas is not None and self._georreferencia_vigente(entradas))
        return dict(paso=self.paso(), pdf=self.hay(), paginas=self.paginas(), entradas=entradas,
                    error_entradas=error, digitalizado=digitalizado, georreferencia=georreferencia,
                    lector=rotulos.disponible(), kmz=[self.kmz.name] if self.terminado() else [])

    def paso(self) -> str:
        """El paso que sigue: subir, marcar, digitalizar, ubicar, crear o listo."""
        if not self.hay():
            return "subir"
        try:
            entradas = self.entradas()
        except ValueError:
            entradas = None
        if not entradas or (not entradas["semillas"] and not _con_lector(entradas)):
            return "marcar"
        if not (self.carpeta / DIGITALIZADO).is_file() or not self._digitalizado_vigente(entradas):
            return "digitalizar"
        if not (self.carpeta / GEORREFERENCIA).is_file() or not self._georreferencia_vigente(entradas):
            return "ubicar"
        huellas = self._huellas()
        if not self.kmz.is_file() or huellas.get("kmz") != huellas.get("georreferencia"):
            return "crear"
        return "listo"

    def lotes(self, en: str = "px") -> dict:
        """Los lotes como GeoJSON, en píxeles de página o en lon/lat. Si está ubicado,
        con el área en m² y, si hay área oficial, el error contra ella."""
        if en not in ("px", "lonlat"):
            raise PlanoInvalido("«en» es px o lonlat")
        if not (self.carpeta / DIGITALIZADO).is_file():
            raise PlanoNoListo("primero hay que digitalizar el plano")
        d = self._leer(DIGITALIZADO)
        t = (Transformacion.desde_dict(self._leer(GEORREFERENCIA))
             if (self.carpeta / GEORREFERENCIA).is_file() else None)
        if en == "lonlat" and t is None:
            raise PlanoNoListo("primero hay que ubicar el plano en el mapa")
        areas = dict(lotes_utm(d, t)) if t is not None else {}
        ids = [normalizar_id(f"LOTE {l['numero']}") for l in d.get("lotes") or []]
        rasgos = []
        for lote, id_ in zip(d.get("lotes") or [], ids):
            numero = str(lote["numero"])
            banderas = []
            if id_ is None:
                banderas.append("sin_numero")
            elif ids.count(id_) > 1:
                banderas.append("duplicado")
            propiedades = dict(numero=numero, area_px=lote.get("area_px"), banderas=banderas,
                               # De dónde salió el número: la pantalla pinta distinto lo
                               # que leyó el lector (y cuán seguro) de lo que marcó ella.
                               origen=lote.get("origen") or "usuario", confianza=lote.get("confianza"),
                               apoyo=lote.get("apoyo"), semilla=lote.get("semilla"))
            if numero in areas:
                propiedades["area_m2"] = round(areas[numero].area, 1)
                oficial = lote.get("area_oficial")
                if oficial:
                    error = areas[numero].area / float(oficial) - 1
                    propiedades.update(area_oficial_m2=float(oficial), error_area=round(error, 4),
                                       nivel="verde" if abs(error) <= VERDE else
                                       "ambar" if abs(error) <= AMBAR else "rojo")
            rasgos.append(_rasgo(lote["poligono"], lote.get("huecos") or [], propiedades, en, t))
        for cara in d.get("sin_numero") or []:
            propiedades = dict(numero=None, area_px=cara.get("area_px"), banderas=["sin_numero"])
            if t is not None:
                utm = Polygon(np.c_[t.a_utm(*np.asarray(cara["poligono"], float).T)])
                propiedades["area_m2"] = round(utm.area, 1)
            rasgos.append(_rasgo(cara["poligono"], [], propiedades, en, t))
        return dict(type="FeatureCollection", en=en, features=rasgos)

    # --- interno ----------------------------------------------------------------------

    def _leer(self, nombre: str) -> dict:
        return json.loads((self.carpeta / nombre).read_text(encoding="utf-8"))

    def _huellas(self) -> dict:
        ruta = self.carpeta / HUELLAS
        return json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else {}

    def _entradas_o_409(self) -> dict:
        try:
            entradas = self.entradas()
        except ValueError as error:
            raise PlanoInvalido(str(error)) from error
        if entradas is None:
            raise PlanoNoListo("primero marca el dibujo y los lotes en el plano")
        return entradas

    def _huella_digitalizado(self, entradas: dict) -> str:
        # Sin huella anotada (lo digitalizó otro, a mano) se da por vigente.
        return self._huellas().get("digitalizado") or huella_digitalizar(entradas)

    def _digitalizado_vigente(self, entradas: dict) -> bool:
        return self._huella_digitalizado(entradas) == huella_digitalizar(entradas)

    def _georreferencia_vigente(self, entradas: dict) -> bool:
        if not self._digitalizado_vigente(entradas):
            return False
        anotada = self._huellas().get("georreferencia")
        return anotada is None or anotada == huella_ubicar(entradas, self._huella_digitalizado(entradas))


def _con_lector(entradas: dict) -> bool:
    """¿Digitalizar va a leer los números solo? (lector encendido y Tesseract instalado)."""
    return bool(entradas.get("lector", True)) and rotulos.disponible()


def _resumen_lector(lector: dict | None) -> dict | None:
    """Lo que la pantalla muestra del lector: cuánto leyó y qué propone."""
    if not lector or not lector.get("activo"):
        return None
    return dict(disponible=lector.get("disponible"), motivo=lector.get("motivo"),
                rotulos=len(lector.get("rotulos") or []), semillas=lector.get("semillas"),
                apoyo_min=lector.get("apoyo_min"), sin_poligono=lector.get("sin_poligono") or [],
                cuadricula=lector.get("cuadricula"), areas=len(lector.get("cuadro") or {}))


def huella_digitalizar(entradas: dict) -> str:
    datos = {k: entradas.get(k) for k in CLAVES_DIGITALIZAR}
    cuadricula = entradas.get("cuadricula") or {}
    datos["cuadricula"] = {f: [m.get(eje) for m in cuadricula.get(f) or []]
                           for f, eje in (("verticales", "x"), ("horizontales", "y"))}
    return _huella(datos)


def huella_ubicar(entradas: dict, huella_digitalizado: str) -> str:
    return _huella(dict({k: entradas.get(k) for k in CLAVES_UBICAR}, digitalizado=huella_digitalizado))


def _huella(datos) -> str:
    texto = json.dumps(datos, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:16]


def resumen_georreferencia(g: dict) -> dict:
    """Lo que la pantalla muestra de la ubicación: método, residuo por ancla y avisos."""
    return dict(metodo=g.get("metodo"), tipo=g.get("tipo"), epsg=g.get("epsg"),
                parametros=g.get("parametros") or {}, anclas=g.get("anclas") or [],
                atipicas=[a["nombre"] for a in g.get("anclas") or [] if a.get("atipica")],
                cuadricula=g.get("cuadricula") or {}, ajuste=g.get("ajuste"),
                avisos=g.get("avisos") or [], datum=g.get("datum"))


def _rasgo(exterior, huecos, propiedades: dict, en: str, t: Transformacion | None) -> dict:
    if en == "lonlat":
        def anillo(a):
            lon, lat = t.a_lonlat(*np.asarray(a, float).T)
            return list(zip(np.atleast_1d(lon).tolist(), np.atleast_1d(lat).tolist()))
        p = orient(Polygon(anillo(exterior), [anillo(h) for h in huecos]))
        coordenadas = ([[list(c) for c in p.exterior.coords]]
                       + [[list(c) for c in h.coords] for h in p.interiors])
    else:
        coordenadas = [exterior] + list(huecos)
    return dict(type="Feature", properties=propiedades, geometry=dict(type="Polygon", coordinates=coordenadas))


def _fuera(nombre: str) -> bool:
    """¿El nombre sale de la carpeta del plano (ruta absoluta, `..`, subcarpetas)?"""
    for ruta in (PurePosixPath(nombre), PureWindowsPath(nombre)):
        if ruta.is_absolute() or ruta.anchor or len(ruta.parts) != 1 or ".." in ruta.parts:
            return True
    return False


def _paginas_del_pdf(ruta: Path) -> int | None:
    """Cuántas páginas tiene, o None si no se abre. El error no se encadena: su
    traza retiene el documento abierto y en Windows no se podría borrar el archivo."""
    try:
        with pymupdf.open(ruta, filetype="pdf") as documento:
            return documento.page_count
    except Exception:                       # noqa: BLE001 - pymupdf no usa los errores de Python
        return None


def _megapixeles(ruta: Path) -> list[float]:
    """Cuánto ocuparía cada página al extraerla, sin decodificarla: lo mismo que
    decide `pipeline.plano.pagina.extraer` (la imagen embebida o el render)."""
    salida = []
    with pymupdf.open(ruta, filetype="pdf") as documento:
        for hoja in documento:
            imagenes = hoja.get_images(full=True)
            pixeles = None
            if imagenes:
                xref, _, ancho, alto = max(imagenes, key=lambda im: im[2] * im[3])[:4]
                rectangulos = hoja.get_image_rects(xref)
                if len(rectangulos) == 1:
                    caja = rectangulos[0] & hoja.rect
                    if (not caja.is_empty and caja.width * caja.height
                            >= pag.COBERTURA_MINIMA * hoja.rect.width * hoja.rect.height):
                        pixeles = ancho * alto
            if pixeles is None:
                escala = pag.DPI_RENDER / 72
                pixeles = hoja.rect.width * escala * hoja.rect.height * escala
            salida.append(pixeles / 1e6)
    return salida


def _jpeg(imagen: Image.Image, calidad: int = CALIDAD) -> bytes:
    buf = io.BytesIO()
    imagen.convert("RGB").save(buf, "JPEG", quality=calidad)
    return buf.getvalue()
