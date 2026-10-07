"""Crea tu KMZ en la consola: el plano aprobado y lo que sale de él.

Un plano vive en la carpeta de un KMZ de Mis KMZ (`kmz/<slug>/`):

    plano.pdf            el PDF tal como llegó
    paginas/<n>.jpg      la imagen de cada página, sin rotar: sus píxeles son los
                         "píxeles de página" de `entradas.json`
    paginas/<n>_mini.jpg la miniatura para elegir página
    paginas/<n>_medio.jpg la página a lo más LADO_MEDIO px, para el editor de la unión
    paginas/info.json    ancho, alto y px por mm de cada página (la geometría de la
                         unión los necesita sin decodificar ninguna imagen)
    paginas/union-<huella>.jpg  la unión de hojas (la "página 0") para la pantalla,
                         en caché por la huella de sus hojas (`union.huella`)
    entradas.json        lo que marca la loteadora (formato en pipeline/plano/digitalizar.py)
    digitalizado.json    los lotes en píxeles (lo escribe el trabajo de fondo)
    georreferencia.json  la ubicación en el mapa, con residuo por ancla
    lotes.geojson        los lotes en lon/lat
    huellas.json         con qué entradas se hizo cada paso: dice qué quedó atrasado
    ediciones.json       los lotes antes de cada corrección a mano, para deshacer

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
from pipeline.plano import numeros as numeros_lote
from pipeline.plano import pagina as pag
from pipeline.plano import rotulos
from pipeline.plano import union as union_hojas
from pipeline.plano.digitalizar import ENTRADAS, SALIDA as DIGITALIZADO, escribir_json, leer_entradas
from pipeline.plano.georreferencia import (GEOJSON, SALIDA as GEORREFERENCIA, Transformacion, a_utm,
                                           cuadricula_suficiente, escala_del_cuadro, georreferenciar,
                                           ubicacion_completa)
from pipeline.plano.salida import escribir_kmz, geojson, lotes_utm

PDF = "plano.pdf"
PAGINAS = "paginas"
HUELLAS = "huellas.json"
EDICIONES = "ediciones.json"

# Un plano del CBR trae una o dos láminas; más es otro documento.
MAX_PAGINAS = 12
# Un A0 escaneado a 300 dpi son ~140 MP. Más que esto, una página decodificada no
# cabe junto a lo demás en la memoria del servidor (y un PDF chico puede declarar
# una imagen enorme).
MAX_MEGAPIXELES = 200
LADO_MINI = 480
# Para el editor de la unión: las hojas enteras de Constitución serían ~150 MP en el
# navegador; a 2.400 px se ven bien y se mueven con soltura.
LADO_MEDIO = 2400
# La unión que ve la pantalla. Más que esto se guarda reducida y el lienzo la estira
# a los px de página: el navegador no carga bien imágenes mucho más grandes.
MAX_MEGAPIXELES_PANTALLA = 60
# El lado más largo que admite un JPEG.
LADO_MAX_JPEG = 65000
INFO = "info.json"
CALIDAD = 90

# Lo que cambia los lotes en píxeles. De la cuadrícula, solo dónde están las
# líneas: su valor impreso se puede corregir sin volver a digitalizar.
CLAVES_DIGITALIZAR = ("pdf", "pagina", "rotacion", "rectangulo", "mascaras", "esquinas", "marco_mm",
                      "semillas", "lector", "lector_apoyo_min", "cuadro", "union")
CLAVES_UBICAR = ("anclas", "ajuste", "cuadricula", "ubicacion", "escala_cuadro")

# Topes de lo que se marca a mano: muy por sobre un loteo real, y lejos de lo que
# atora la revisión (las semillas repetidas se buscan de a pares).
TOPES = dict(semillas=2000, mascaras=200, anclas=50, fuera=50)
TOPE_CUADRICULA = 200

# Corrección a mano de los vértices en Revisar: cuántas versiones se guardan para
# deshacer, y a qué distancia (px de página) de un vértice cae el punto que se tocó.
# La pantalla manda el vértice tal como lo recibió en lon/lat: vuelve casi exacto.
TOPE_DESHACER = 20
TOLERANCIA_VERTICE_PX = 0.5

# Error de área contra el cuadro de superficies: verde ±2 %, ámbar ±5 %, rojo más.
VERDE, AMBAR = 0.02, 0.05

# El resto de la propiedad (el predio que queda tras sacar los lotes) aparece como una
# parte sin número enorme: en Caminos de Rapel, 76 há junto a lotes de media há. Sin
# fila de resto en el cuadro, es resto la parte sin número más grande si mide más de
# RESTO_VECES la mediana de los lotes; con la fila, basta RESTO_VECES_CUADRO (así no se
# pregunta por un lote al que no se le leyó el número).
RESTO_VECES = 5
RESTO_VECES_CUADRO = 2


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


class LotesSinNumero(PlanoNoListo):
    """Hay caras del tamaño de un lote sin número, o falta decidir si el resto de la
    propiedad va (409): no irían al KMZ. Se crea igual solo si la loteadora lo pide
    (`omitir_sin_numero`), y entonces el resto queda fuera.
    El resto sin decidir no es un lote sin número: Numerar lo muestra como una pregunta,
    y el aviso la nombra igual (no "1 lote sin número")."""

    def __init__(self, cuantos: int, resto: bool = False):
        self.cuantos = cuantos
        self.resto = resto
        lotes = ("Queda 1 lote sin número" if cuantos == 1
                 else f"Quedan {cuantos} lotes sin número") + " (en rojo)" if cuantos else ""
        if lotes and resto:
            texto = (f"{lotes} y falta decidir si el resto de la propiedad va en el KMZ. Ponles su"
                     " número y responde la pregunta del resto en \"Revisar los números\", o crea el KMZ"
                     " sin ellos (el resto queda fuera).")
        elif resto:
            texto = ("Falta decidir si el resto de la propiedad va en el KMZ: respóndelo en \"Revisar"
                     " los números\", o crea el KMZ sin él.")
        else:
            texto = (f"{lotes}: no irían al KMZ. Ponles su número en \"Revisar los números\", o crea el"
                     " KMZ sin ellos.")
        super().__init__(texto)


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
                tamanos = [megas for megas, _ in _medidas(temporal)]
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
                imagen.thumbnail((LADO_MEDIO, LADO_MEDIO))
                (listas / f"{n}_medio.jpg").write_bytes(_jpeg(imagen, 85))
                imagen.thumbnail((LADO_MINI, LADO_MINI))
                (listas / f"{n}_mini.jpg").write_bytes(_jpeg(imagen, 80))
                del imagen
                hechas.append(dict(n=n, ancho=ancho, alto=alto, ppmm=hoja.ppmm))
            (listas / INFO).write_text(json.dumps(dict(paginas=hechas)), encoding="utf-8")
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
        for nombre in (PDF, ENTRADAS, DIGITALIZADO, GEORREFERENCIA, GEOJSON, HUELLAS, EDICIONES):
            (self.carpeta / nombre).unlink(missing_ok=True)
        shutil.rmtree(self.carpeta / PAGINAS, ignore_errors=True)

    def paginas(self) -> list[dict]:
        """{n, ancho, alto, ppmm} de cada página (ancho y alto sin girar)."""
        info = self.info()
        return [dict(n=n, **info[n]) for n in sorted(info)]

    def _paginas_jpg(self) -> list[dict]:
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

    def imagen(self, n: int, mini: bool = False, medio: bool = False) -> Path | None:
        """El JPEG de la página `n` para la pantalla, o None si no hay. La página 0 es la
        unión de hojas (ver `imagen_union`); `medio` es la página a LADO_MEDIO px, que se
        hace al primer pedido en los PDF subidos antes de que existiera."""
        if not self.hay():
            return None
        if n == 0:
            return self.imagen_union(mini=mini, medio=medio)
        if n < 1:
            return None
        if mini:
            ruta = self.carpeta / PAGINAS / f"{n}_mini.jpg"
        elif medio:
            ruta = self.carpeta / PAGINAS / f"{n}_medio.jpg"
            if not ruta.is_file():
                ruta = self._medio(n)
        else:
            ruta = self.carpeta / PAGINAS / f"{n}.jpg"
        return ruta if ruta is not None and ruta.is_file() else None

    @_a_solas
    def _medio(self, n: int) -> Path | None:
        paginas = self.carpeta / PAGINAS
        ruta, grande = paginas / f"{n}_medio.jpg", paginas / f"{n}.jpg"
        if ruta.is_file() or not grande.is_file():
            return ruta if ruta.is_file() else None
        with Image.open(grande) as imagen:
            # `draft` decodifica el JPEG ya achicado (1/2, 1/4, 1/8): la página entera
            # no pasa por la memoria.
            imagen.draft("RGB", (LADO_MEDIO, LADO_MEDIO))
            imagen.thumbnail((LADO_MEDIO, LADO_MEDIO))
            _escribir(ruta, _jpeg(imagen, 85))
        return ruta

    def info(self) -> dict[int, dict]:
        """n → {ancho, alto, ppmm} de cada página (ancho y alto sin girar). Para los PDF
        subidos antes de `info.json`, se calcula una vez sin decodificar las páginas."""
        if not self.hay():
            return {}
        info = self._leer_info()
        return info if info is not None else self._calcular_info()

    def _leer_info(self) -> dict[int, dict] | None:
        ruta = self.carpeta / PAGINAS / INFO
        if ruta.is_file():
            with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
                return {int(p["n"]): dict(ancho=int(p["ancho"]), alto=int(p["alto"]),
                                          ppmm=None if p["ppmm"] is None else float(p["ppmm"]))
                        for p in json.loads(ruta.read_text(encoding="utf-8"))["paginas"]}
        return None

    @_a_solas
    def _calcular_info(self) -> dict[int, dict]:
        # Quien tenía el candado (otro pedido, o un PDF nuevo) pudo dejarlo escrito.
        info = self._leer_info()
        if info is not None:
            return info
        paginas = self._paginas_jpg()
        if not paginas:
            return {}
        try:
            ppmms = [ppmm for _, ppmm in _medidas(self.carpeta / PDF)]
        except Exception:                   # noqa: BLE001 - pymupdf no usa los errores de Python
            # El estado se muestra igual; sin resolución no se puede unir (lo dice
            # `_union_valida`). No se anota: se vuelve a intentar.
            return {p["n"]: dict(ancho=p["ancho"], alto=p["alto"], ppmm=None) for p in paginas}
        info = [dict(p, ppmm=ppmms[p["n"] - 1] if p["n"] <= len(ppmms) else None) for p in paginas]
        escribir_json(self.carpeta / PAGINAS / INFO, dict(paginas=info))
        return {p["n"]: dict(ancho=p["ancho"], alto=p["alto"], ppmm=p["ppmm"]) for p in info}

    # --- la unión de hojas (la página 0) -----------------------------------------------

    def _union_valida(self, dic) -> tuple[union_hojas.Union, union_hojas.Geometria, dict[int, dict]]:
        """La unión revisada contra las páginas del PDF y el tope de megapíxeles, con
        su geometría. Sin componer nada."""
        info = self.info()
        if any(p["ppmm"] is None for p in info.values()):
            raise PlanoInvalido("no se pudo leer la resolución de las páginas del PDF: súbelo de nuevo")
        try:
            union = union_hojas.leer(dic, paginas={n: (p["ancho"], p["alto"]) for n, p in info.items()})
            geo = union_hojas.geometria(union, {n: (p["ancho"], p["alto"]) for n, p in info.items()},
                                        {n: p["ppmm"] for n, p in info.items()})
        except ValueError as error:
            raise PlanoInvalido(str(error)) from error
        return union, geo, info

    def _union_guardada(self) -> dict | None:
        try:
            entradas = self.entradas()
        except ValueError:
            return None
        return (entradas or {}).get("union") or None

    def resumen_union(self, dic: dict | None) -> dict | None:
        """Lo que la pantalla necesita de la página 0 (su tamaño en px de página y la
        huella, que va en el `?v=` de su imagen), sin componerla. `dic`: la unión de las
        entradas guardadas."""
        if not dic:
            return None
        try:
            union, geo, _ = self._union_valida(dic)
        except PlanoInvalido:
            return None
        return dict(ancho=geo.ancho, alto=geo.alto, ppmm=geo.ppmm, hojas=dic["hojas"],
                    huella=union_hojas.huella(union))

    def imagen_union(self, mini: bool = False, medio: bool = False) -> Path | None:
        """La unión guardada en entradas, compuesta desde los JPEG de las páginas (no
        desde el PDF: es para mirar, y así no se decodifica el escaneo de nuevo). Queda en
        caché por su huella; None si no hay unión guardada."""
        sufijo = "_mini" if mini else "_medio" if medio else ""
        dic = self._union_guardada()
        if dic is None:
            return None
        ruta = self.carpeta / PAGINAS / f"union-{union_hojas.huella(union_hojas.leer(dic))}{sufijo}.jpg"
        return ruta if ruta.is_file() else self._componer_union(sufijo)

    @_a_solas
    def _componer_union(self, sufijo: str) -> Path | None:
        """Compone la unión guardada (si no está ya) y devuelve su imagen `sufijo`. La
        unión se relee con el candado: mientras se esperaba pudo guardarse otra, y
        componer la vieja borraría la caché de la nueva."""
        dic = self._union_guardada()
        if dic is None:
            return None
        huella = union_hojas.huella(union_hojas.leer(dic))
        paginas = self.carpeta / PAGINAS
        # Otro pedido pudo componerla mientras este esperaba el candado. Si falta la que
        # se pide (la consola se cayó a medio escribir), se compone de nuevo.
        ruta = paginas / f"union-{huella}{sufijo}.jpg"
        if ruta.is_file():
            return ruta
        union, geo, _ = self._union_valida(dic)
        # Se compone directo a la resolución de pantalla: a tamaño completo serían hasta
        # 250 MP en RGB (750 MB) solo para achicarlos después.
        s = min(1.0, (MAX_MEGAPIXELES_PANTALLA * 1e6 / (geo.ancho * geo.alto)) ** 0.5,
                LADO_MAX_JPEG / max(geo.ancho, geo.alto))
        ancho, alto = max(round(geo.ancho * s), 1), max(round(geo.alto * s), 1)
        a_reducida = _escalar(ancho / geo.ancho, alto / geo.alto)
        imagenes, hojas = {}, []
        for h, hg in zip(union.hojas, geo.hojas):
            # Una hoja de menos resolución que la unión (k > 1) no se achica tanto.
            girada = pag.rotar(_cargar(paginas / f"{h.n}.jpg", min(1.0, s * hg.k), "RGB"), h.rotacion)
            sx, sy = girada.shape[1] / hg.ancho, girada.shape[0] / hg.alto
            x0, y0, x1, y1 = hg.recorte
            recorte = (int(np.floor(x0 * sx)), int(np.floor(y0 * sy)),
                       max(int(np.ceil(x1 * sx)), int(np.floor(x0 * sx)) + 1),
                       max(int(np.ceil(y1 * sy)), int(np.floor(y0 * sy)) + 1))
            matriz = a_reducida @ hg.matriz @ np.linalg.inv(_escalar(sx, sy))
            hojas.append(union_hojas.HojaGeometria(hg.n, girada.shape[1], girada.shape[0], hg.ppmm,
                                                   hg.k * s, recorte, matriz))
            imagenes[h.n] = girada
        reducida = union_hojas.Geometria(ancho, alto, geo.ppmm * s, geo.origen, hojas)
        imagen = Image.fromarray(union_hojas.componer(imagenes, reducida))
        del imagenes
        # Las de otra huella ya no las pide nadie (la pantalla pide con `?v=<huella>`).
        for vieja in paginas.glob("union-*.jpg"):
            if not vieja.name.startswith(f"union-{huella}"):
                vieja.unlink(missing_ok=True)
        _escribir(paginas / f"union-{huella}.jpg", _jpeg(imagen))
        imagen.thumbnail((LADO_MEDIO, LADO_MEDIO))
        _escribir(paginas / f"union-{huella}_medio.jpg", _jpeg(imagen, 85))
        imagen.thumbnail((LADO_MINI, LADO_MINI))
        _escribir(paginas / f"union-{huella}_mini.jpg", _jpeg(imagen, 80))
        return ruta

    def afinar_union(self, dic) -> dict:
        """Lo que propone Afinar para las hojas como están en pantalla (`{"hojas": [...]}`):
        las mismas hojas con x, y y angulo corregidos, más `calzada` y `residuo_mm`. No
        guarda nada."""
        if not self.hay():
            raise PlanoNoListo("primero sube el PDF del plano")
        if not isinstance(dic, dict):
            raise PlanoInvalido("la unión de hojas no tiene la forma esperada")
        # El cuadro no cambia el calce: uno a medio marcar no debe impedir afinar.
        union, _, info = self._union_valida({"hojas": dic.get("hojas")})
        paginas = self.carpeta / PAGINAS
        imagenes = {}
        for h in union.hojas:
            # Afinar termina a PPMM_ECC (4 px/mm): la `_medio` (2.400 px) queda bajo eso en
            # una lámina grande (~1,9 px/mm en Constitución) y el calce perdería precisión.
            # La página en gris a esa resolución pesa menos que la `_medio` en color de más.
            s = min(1.0, union_hojas.PPMM_ECC / info[h.n]["ppmm"])
            try:
                imagenes[h.n] = pag.rotar(_cargar(paginas / f"{h.n}.jpg", s, "L"), h.rotacion)
            except FileNotFoundError as error:
                raise PlanoNoListo("primero sube el PDF del plano") from error
        hojas = union_hojas.afinar(imagenes, {n: p["ppmm"] for n, p in info.items()}, union,
                                   {n: (p["ancho"], p["alto"]) for n, p in info.items()})
        return dict(hojas=hojas)

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
        if normalizadas.get("union"):
            # `leer_entradas` ya exigió página 0 y rotación 0; acá, que cada hoja sea una
            # página de este PDF, que recortes y cuadro quepan y el tope de megapíxeles.
            # El cuadro de la unión va en px de su hoja: lo revisa `union.leer`.
            self._union_valida(normalizadas["union"])
        elif not 1 <= normalizadas["pagina"] <= total:
            raise PlanoInvalido(f"el PDF tiene {total} páginas; no existe la {normalizadas['pagina']}")
        if normalizadas["rotacion"] % 90:
            raise PlanoInvalido(f"la rotación es 0, 90, 180 o 270 grados, no {normalizadas['rotacion']}")
        if normalizadas.get("cuadro") and not normalizadas.get("union"):
            # Puede estar fuera del dibujo, pero no fuera de la página (px de página: la
            # imagen ya girada).
            hoja = next(p for p in self.paginas() if p["n"] == normalizadas["pagina"])
            ancho, alto = ((hoja["alto"], hoja["ancho"]) if normalizadas["rotacion"] % 180
                           else (hoja["ancho"], hoja["alto"]))
            x0, y0, x1, y1 = normalizadas["cuadro"]
            if x1 <= 0 or y1 <= 0 or x0 >= ancho or y0 >= alto:
                raise PlanoInvalido("el cuadro de superficies está fuera de la página: enciérralo de nuevo")
        escribir_json(self.carpeta / ENTRADAS, normalizadas)
        if not normalizadas.get("union"):
            # Sin unión, su imagen ya no la pide nadie; la de otra huella la borra
            # quien componga la nueva.
            for vieja in (self.carpeta / PAGINAS).glob("union-*.jpg"):
                vieja.unlink(missing_ok=True)
        return normalizadas

    # --- pasos ----------------------------------------------------------------------

    def para_digitalizar(self) -> dict:
        """Revisa que se pueda digitalizar y devuelve las entradas con que se lanza. Su
        huella se saca y se anota cuando el trabajo termina bien (`huella_al_terminar`)."""
        if not self.hay():
            raise PlanoNoListo("primero sube el PDF del plano")
        entradas = self._entradas_o_409()
        if not entradas["semillas"] and not _con_lector(entradas):
            raise PlanoNoListo("marca el número de al menos un lote antes de leer el plano"
                               + ("" if not entradas["lector"] else
                                  " (no hay lector de rótulos en este servidor)"))
        return entradas

    def huella_al_terminar(self, entradas: dict) -> str:
        """La huella de las entradas con que se digitalizó, contra la cuadrícula que
        propuso el lector en esta misma digitalización (no la de la anterior): si la
        loteadora ya había elegido la propuesta y el lector lee la misma, sigue sin contar."""
        return huella_digitalizar(entradas, self._propuesta())

    @_a_solas
    def anotar(self, paso: str, huella: str) -> None:
        huellas = self._huellas()
        huellas[paso] = huella
        escribir_json(self.carpeta / HUELLAS, huellas)
        if paso == "digitalizado":
            # Lotes nuevos: deshacer volvería a los de la digitalización anterior.
            (self.carpeta / EDICIONES).unlink(missing_ok=True)
            huellas.pop("correcciones", None)
            escribir_json(self.carpeta / HUELLAS, huellas)

    @_a_solas
    def corregir(self, accion: str, punto=None, a=None) -> dict:
        """Corrección a mano en Revisar, sobre el mapa (`punto` y `a` en [lon, lat]):

        - "mover": el vértice en `punto` va a `a`, en todos los lotes que lo tienen (un
          vértice compartido se mueve en los vecinos: no quedan traslapes ni huecos);
        - "borrar": se quita el vértice en `punto`, si cada lote que lo tiene lo tiene
          entre los mismos dos vecinos (un vértice sobre el lado común). Una esquina donde
          llega una divisoria no se borra: los dos lotes quedarían cortados distinto;
        - "deshacer": vuelve a los lotes de antes de la última corrección.

        Escribe digitalizado.json y lotes.geojson; el KMZ creado queda atrasado. Volver a
        digitalizar descarta las correcciones."""
        if accion not in ("mover", "borrar", "deshacer"):
            raise PlanoInvalido("la corrección es mover, borrar o deshacer")
        entradas = self._entradas_o_409()
        if not (self.carpeta / GEORREFERENCIA).is_file() or not self._georreferencia_vigente(entradas):
            raise PlanoNoListo("primero hay que ubicar el plano en el mapa")
        t = Transformacion.desde_dict(self._leer(GEORREFERENCIA))
        d = self._leer(DIGITALIZADO)
        ruta = self.carpeta / EDICIONES
        historia = json.loads(ruta.read_text(encoding="utf-8")) if ruta.is_file() else []
        if accion == "deshacer":
            if not historia:
                raise PlanoNoListo("no hay correcciones que deshacer")
            previo = historia.pop()
            d["lotes"], d["sin_numero"] = previo["lotes"], previo["sin_numero"]
        else:
            antes = dict(lotes=json.loads(json.dumps(d.get("lotes") or [])),
                         sin_numero=json.loads(json.dumps(d.get("sin_numero") or [])))
            p = self._a_pagina(t, punto)
            if accion == "mover":
                _mover_vertice(d, p, self._a_pagina(t, a))
            else:
                _borrar_vertice(d, p)
            historia = (historia + [antes])[-TOPE_DESHACER:]
        escribir_json(self.carpeta / DIGITALIZADO, d)
        escribir_json(ruta, historia)
        escribir_json(self.carpeta / GEOJSON, geojson(d, t))
        huellas = self._huellas()
        # Cualquier valor distinto de la huella de la georreferencia deja el KMZ atrasado,
        # también cuando la georreferencia no tiene huella anotada (la hizo otro, a mano).
        huellas["kmz"] = "corregido"
        # El conteo va acá para que el estado no lea el historial entero en cada consulta.
        huellas["correcciones"] = len(historia)
        escribir_json(self.carpeta / HUELLAS, huellas)
        return dict(deshacer=len(historia))

    @staticmethod
    def _a_pagina(t: Transformacion, lonlat) -> np.ndarray:
        if (not isinstance(lonlat, (list, tuple)) or len(lonlat) != 2
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in lonlat)):
            raise PlanoInvalido("el punto va como [lon, lat]")
        try:
            lon, lat = (float(v) for v in lonlat)
        except (TypeError, ValueError) as error:
            raise PlanoInvalido("el punto va como [lon, lat]") from error
        if not (np.isfinite(lon) and np.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
            raise PlanoInvalido("el punto va como [lon, lat]")
        e, n = a_utm(lon, lat, t.epsg)
        x, y, w = np.linalg.solve(t.matriz, np.array([float(e), float(n), 1.0]))
        return np.array([x / w, y / w])

    @_a_solas
    def georreferenciar(self) -> dict:
        """Ubica los lotes (cuadrícula, anclas o un punto) y escribe georreferencia.json y
        lotes.geojson. Es rápido: corre en la petición."""
        entradas = self._entradas_o_409()
        if not (self.carpeta / DIGITALIZADO).is_file():
            raise PlanoNoListo("primero hay que leer el plano")
        if not self._digitalizado_vigente(entradas):
            raise PlanoNoListo("cambiaste el dibujo o los números desde la última lectura:"
                               " lee el plano de nuevo antes de ubicarlo")
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
    def crear_kmz(self, omitir_sin_numero: bool = False) -> dict:
        """Escribe el KMZ. Es su propio archivo: se rehace sin preguntar. Si quedan caras
        del tamaño de un lote sin número, 409 (`LotesSinNumero`) salvo `omitir_sin_numero`:
        el KMZ lleva solo los lotes numerados."""
        entradas = self._entradas_o_409()
        if not (self.carpeta / GEORREFERENCIA).is_file():
            raise PlanoNoListo("primero hay que ubicar el plano en el mapa")
        if not self._georreferencia_vigente(entradas):
            raise PlanoNoListo("cambiaste el plano desde que se ubicó: léelo o ubícalo de nuevo")
        digitalizado = self._leer(DIGITALIZADO)
        # Lo que ella dejó fuera (el resto de la propiedad) no se pregunta de nuevo, y si
        # tenía número (lo leyó el lector) no va.
        fuera = _fuera_del_kmz(digitalizado.get("sin_numero"), entradas)
        resto = _resto(digitalizado)["cara"]
        resto_pendiente = resto is not None and not fuera[resto]
        sin_numero = sum(bool(c.get("de_lote")) and not f and i != resto
                         for i, (c, f) in enumerate(zip(digitalizado.get("sin_numero") or [], fuera)))
        if (sin_numero or resto_pendiente) and not omitir_sin_numero:
            raise LotesSinNumero(sin_numero, resto=resto_pendiente)
        lotes = digitalizado.get("lotes") or []
        digitalizado = dict(digitalizado, lotes=[l for l, f in zip(lotes, _fuera_del_kmz(lotes, entradas)) if not f])
        t = Transformacion.desde_dict(self._leer(GEORREFERENCIA))
        try:
            # Aparte y `os.replace` al final: un error no se lleva el anterior.
            n = escribir_kmz(self.kmz, digitalizado, t, nombre=self.nombre or self.carpeta.name)
        except ValueError as error:
            raise PlanoInvalido(str(error)) from error
        self.anotar("kmz", huella_kmz(self._huellas().get("georreferencia") or huella_ubicar(
            entradas, self._huella_digitalizado(entradas)), self._leer(DIGITALIZADO), entradas))
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
            # Las partes que ella dejó fuera del KMZ no se cuentan como sin número ni como lotes.
            fuera = _fuera_del_kmz(d.get("sin_numero"), entradas)
            caras = [c for c, f in zip(d.get("sin_numero") or [], fuera) if not f]
            # El resto sin decidir es una pregunta, no un lote sin número.
            resto = _resto(d)["cara"]
            resto_pendiente = resto is not None and not fuera[resto]
            fuera_lotes = _fuera_del_kmz(d.get("lotes"), entradas)
            digitalizado = dict(
                lotes=len(fuera_lotes) - sum(fuera_lotes), faltantes=d.get("faltantes") or [],
                sin_numero=len(caras), fuera=sum(fuera) + sum(fuera_lotes), pagina=d.get("pagina"),
                # Caras del tamaño de un lote sin número (y cuántas traen una lectura que
                # confirmar), y los números que faltan en la numeración.
                sin_numero_lote=sum(bool(c.get("de_lote")) for c in caras) - (
                    resto_pendiente and bool(d["sin_numero"][resto].get("de_lote"))),
                resto_pendiente=resto_pendiente,
                sugerencias=sum(bool(c.get("sugerencia")) for c in caras),
                huecos=d.get("huecos") or [],
                cuadricula=d.get("cuadricula") is not None,
                segundos=(d.get("estadisticas") or {}).get("segundos"),
                lector=_resumen_lector(d.get("lector")),
                # Cuántas correcciones a mano se pueden deshacer.
                correcciones=self._correcciones(),
                # Para la vista previa de Ubicar con un punto: la misma similitud que
                # `por_punto`, con la escala del cuadro (m por px de trabajo, o null), el
                # ppmm de trabajo (para la escala impresa) y la homografía página → trabajo.
                escala_m_px=escala_del_cuadro(d), ppmm=(d.get("trabajo") or {}).get("ppmm"),
                homografia=(d.get("trabajo") or {}).get("homografia"),
                # La vista previa con puntos usa la homografía solo en una foto rectificada,
                # como `georreferenciar` (en un recorte la similitud la absorbe).
                perspectiva=(d.get("trabajo") or {}).get("modo") == "perspectiva",
                vigente=entradas is not None and self._digitalizado_vigente(entradas))
        if (self.carpeta / GEORREFERENCIA).is_file():
            georreferencia = dict(resumen_georreferencia(self._leer(GEORREFERENCIA)),
                                  vigente=entradas is not None and self._georreferencia_vigente(entradas))
        return dict(paso=self.paso(), pdf=self.hay(), paginas=self.paginas(), entradas=entradas,
                    union=self.resumen_union((entradas or {}).get("union")),
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
        if not self.kmz.is_file() or huellas.get("kmz") != huella_kmz(
                huellas.get("georreferencia"), self._leer(DIGITALIZADO), entradas):
            return "crear"
        return "listo"

    def lotes(self, en: str = "px") -> dict:
        """Los lotes como GeoJSON, en píxeles de página o en lon/lat. Si está ubicado,
        con el área en m² y, si hay área oficial, el error contra ella."""
        if en not in ("px", "lonlat"):
            raise PlanoInvalido("«en» es px o lonlat")
        if not (self.carpeta / DIGITALIZADO).is_file():
            raise PlanoNoListo("primero hay que leer el plano")
        d = self._leer(DIGITALIZADO)
        t = (Transformacion.desde_dict(self._leer(GEORREFERENCIA))
             if (self.carpeta / GEORREFERENCIA).is_file() else None)
        if en == "lonlat" and t is None:
            raise PlanoNoListo("primero hay que ubicar el plano en el mapa")
        areas = dict(lotes_utm(d, t)) if t is not None else {}
        # El "Resto" no tiene id para el lector de KMZ: se compara por su nombre, como al
        # crear (`numeros.repetidos`). Si no, cualquier número inválido lo hacía "repetido".
        ids = [normalizar_id(f"LOTE {l['numero']}") or (f"resto:{numeros_lote.clave(l['numero'])}"
               if numeros_lote.es_resto(l["numero"]) else None) for l in d.get("lotes") or []]
        try:
            entradas = self.entradas()
        except ValueError:
            entradas = None
        resto = _resto(d)
        fuera = _fuera_del_kmz(d.get("sin_numero"), entradas)
        fuera_lotes = _fuera_del_kmz(d.get("lotes"), entradas)
        rasgos = []
        for i, (lote, id_) in enumerate(zip(d.get("lotes") or [], ids)):
            numero = str(lote["numero"])
            banderas = []
            # "Resto" es un nombre válido: es el resto de la propiedad, que ella incluyó.
            if id_ is None:
                banderas.append("sin_numero")
            elif ids.count(id_) > 1:
                banderas.append("duplicado")
            propiedades = dict(numero=numero, area_px=lote.get("area_px"), banderas=banderas,
                               # De dónde salió el número: la pantalla pinta distinto lo
                               # que leyó el lector (y cuán seguro) de lo que marcó ella.
                               origen=lote.get("origen") or "usuario", confianza=lote.get("confianza"),
                               apoyo=lote.get("apoyo"), semilla=lote.get("semilla"))
            if resto["lote"] == i:
                propiedades["resto"] = True
            if fuera_lotes[i]:
                # Tiene número (el lector leyó el del plano) pero ella lo dejó fuera del KMZ.
                propiedades["fuera"] = True
                banderas.append("fuera")
            if numero in areas:
                propiedades["area_m2"] = round(areas[numero].area, 1)
                oficial = lote.get("area_oficial")
                if oficial:
                    error = areas[numero].area / float(oficial) - 1
                    propiedades.update(area_oficial_m2=float(oficial), error_area=round(error, 4),
                                       nivel="verde" if abs(error) <= VERDE else
                                       "ambar" if abs(error) <= AMBAR else "rojo")
            rasgos.append(_rasgo(lote["poligono"], lote.get("huecos") or [], propiedades, en, t))
        for i, (cara, afuera) in enumerate(zip(d.get("sin_numero") or [], fuera)):
            # `de_lote`: del tamaño de un lote (no se pegó a su vecino); `sugerencia`: lo que
            # leyó el lector dentro, con poco apoyo, para confirmar con un clic. Lo que ella
            # dejó fuera del KMZ (`fuera`) ya no es un lote sin número: lo decidió.
            de_lote = bool(cara.get("de_lote")) and not afuera
            propiedades = dict(numero=None, area_px=cara.get("area_px"),
                               banderas=["sin_numero"] + (["de_lote"] if de_lote else [])
                               + (["fuera"] if afuera else []),
                               de_lote=de_lote, sugerencia=None if afuera else cara.get("sugerencia"),
                               fuera=afuera)
            if resto["cara"] == i:
                # Numerar pregunta si va al KMZ: con el número del cuadro, si lo trae, y un
                # punto que cae dentro (el centroide de una parte en "U" puede caer fuera).
                punto = Polygon(cara["poligono"]).representative_point()
                propiedades.update(resto=True, numero_resto=resto["numero"], area_resto_m2=resto["area"],
                                   punto=[round(punto.x, 2), round(punto.y, 2)])
            if t is not None:
                utm = Polygon(np.c_[t.a_utm(*np.asarray(cara["poligono"], float).T)])
                propiedades["area_m2"] = round(utm.area, 1)
            rasgos.append(_rasgo(cara["poligono"], [], propiedades, en, t))
        return dict(type="FeatureCollection", en=en, features=rasgos)

    # --- interno ----------------------------------------------------------------------

    def _leer(self, nombre: str) -> dict:
        return json.loads((self.carpeta / nombre).read_text(encoding="utf-8"))

    def _correcciones(self) -> int:
        return int(self._huellas().get("correcciones") or 0) if (self.carpeta / EDICIONES).is_file() else 0

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

    def _propuesta(self) -> dict | None:
        """La cuadrícula que leyó el lector en la última digitalización, tal cual."""
        try:
            return (self._leer(DIGITALIZADO).get("lector") or {}).get("cuadricula")
        except (OSError, ValueError, AttributeError):
            return None

    def _huella_digitalizado(self, entradas: dict) -> str:
        # Sin huella anotada (lo digitalizó otro, a mano) se da por vigente.
        return self._huellas().get("digitalizado") or huella_digitalizar(entradas, self._propuesta())

    def _digitalizado_vigente(self, entradas: dict) -> bool:
        # También vale la huella con la cuadrícula elegida tal cual (sin descontar la
        # propuesta): es como se anotaba antes, y si coincide se digitalizó justo con
        # esas líneas. Sin esto, un KMZ que eligió la propuesta y digitalizó antes del
        # cambio se vería atrasado sin que nada haya cambiado.
        anotada = self._huella_digitalizado(entradas)
        return anotada in (huella_digitalizar(entradas, self._propuesta()), huella_digitalizar(entradas))

    def _georreferencia_vigente(self, entradas: dict) -> bool:
        if not self._digitalizado_vigente(entradas):
            return False
        anotada = self._huellas().get("georreferencia")
        return anotada is None or anotada == huella_ubicar(entradas, self._huella_digitalizado(entradas))


def _anillos(d: dict):
    """Cada anillo de los lotes y de las caras sin número, con el dueño que hay que
    poner al día (área, vértices) si cambia: el de un hueco es el lote que lo tiene."""
    for duenio in [*(d.get("lotes") or []), *(d.get("sin_numero") or [])]:
        yield duenio, duenio["poligono"]
        for hueco in duenio.get("huecos") or []:
            yield duenio, hueco


def _vertices_en(d: dict, p: np.ndarray) -> list[tuple[dict, list, int]]:
    """Los (dueño, anillo, índice) del vértice más cercano a `p`. Un vértice
    compartido es el mismo punto en cada anillo (salen de la misma red)."""
    mejor, cerca = None, []
    for duenio, anillo in _anillos(d):
        # El último repite el primero: se mira hasta el penúltimo.
        for i, (x, y) in enumerate(anillo[:-1]):
            dist = float(np.hypot(x - p[0], y - p[1]))
            if dist <= TOLERANCIA_VERTICE_PX and (mejor is None or dist < mejor - 1e-9):
                mejor, cerca = dist, []
            if mejor is not None and dist <= TOLERANCIA_VERTICE_PX and abs(dist - mejor) <= 1e-6:
                cerca.append((duenio, anillo, i))
    if not cerca:
        raise PlanoInvalido("no hay un vértice en ese punto: vuelve a cargar los lotes")
    return cerca


def _poligono(duenio: dict) -> Polygon:
    return Polygon(duenio["poligono"], duenio.get("huecos") or [])


def _sin_repetidos(anillo: list) -> None:
    """Quita los puntos seguidos iguales (un vértice soltado sobre su vecino), cuidando
    que el anillo siga cerrado: si no, ese punto doble no se podría borrar después."""
    puntos = [q for k, q in enumerate(anillo[:-1]) if k == 0 or q != anillo[k - 1]]
    while len(puntos) > 1 and puntos[-1] == puntos[0]:
        puntos.pop()
    anillo[:] = puntos + [list(puntos[0])]


# Lo que dos lotes pueden encimarse por redondeo sin que sea un traslape (px²).
TRASLAPE_MAX_PX2 = 1.0


def _poner_al_dia(d: dict, tocados: list, error: str) -> None:
    """Revisa cada lote o cara que cambió (con sus huecos y contra los demás) y le pone
    al día el área y los vértices. Un vértice de un hueco cambia al lote que lo tiene."""
    duenios = list({id(t[0]): t[0] for t in tocados}.values())
    for duenio in duenios:
        for anillo in [duenio["poligono"], *(duenio.get("huecos") or [])]:
            _sin_repetidos(anillo)
            if len(anillo) - 1 < 3:
                raise PlanoInvalido("un lote necesita al menos tres vértices")
        if not _poligono(duenio).is_valid:
            raise PlanoInvalido(error)
    tocados_id = {id(x) for x in duenios}
    otros = [x for x in [*(d.get("lotes") or []), *(d.get("sin_numero") or [])] if id(x) not in tocados_id]
    for duenio in duenios:
        forma = _poligono(duenio)
        for otro in otros:
            if forma.intersection(_poligono(otro)).area > TRASLAPE_MAX_PX2:
                raise PlanoInvalido("así el lote se monta sobre otro: suelta el vértice más cerca")
        duenio["area_px"] = round(forma.area, 1)
        if "vertices" in duenio:
            duenio["vertices"] = len(duenio["poligono"]) - 1


def _mover_vertice(d: dict, p: np.ndarray, a: np.ndarray) -> None:
    nuevo = [round(float(a[0]), 2), round(float(a[1]), 2)]
    tocados = _vertices_en(d, p)
    for _, anillo, i in tocados:
        anillo[i] = list(nuevo)
        if i == 0:
            anillo[-1] = list(nuevo)
    _poner_al_dia(d, tocados, "así el lote se cruza consigo mismo: suelta el vértice más cerca")


def _borrar_vertice(d: dict, p: np.ndarray) -> None:
    tocados = _vertices_en(d, p)
    vecinos = []
    for _, anillo, i in tocados:
        n = len(anillo) - 1
        if n <= 3:
            raise PlanoInvalido("un lote necesita al menos tres vértices")
        vecinos.append({tuple(anillo[(i - 1) % n]), tuple(anillo[(i + 1) % n])})
    if any(v != vecinos[0] for v in vecinos):
        raise PlanoInvalido("ese vértice es una esquina entre lotes: muévelo en vez de borrarlo")
    for _, anillo, i in tocados:
        del anillo[i]
        if i == 0:
            anillo[-1] = list(anillo[0])
    _poner_al_dia(d, tocados, "sin ese vértice el lote se cruza consigo mismo")


def _area_px(parte: dict) -> float:
    return float(parte.get("area_px") or Polygon(parte["poligono"]).area)


def _resto(d: dict) -> dict:
    """El resto de la propiedad en el digitalizado: {"lote": índice del lote que lo lleva
    (ella lo incluyó con el número del cuadro o "Resto"), "cara": índice de la parte sin
    número que lo parece (falta decidir si va al KMZ), "numero": el del cuadro o None,
    "area": la suya en el cuadro, m²}.
    Se calcula al leer, no al digitalizar: así sirve también con lo ya digitalizado."""
    cuadro = (d.get("lector") or {}).get("cuadro") or {}
    numero = numeros_lote.resto(cuadro)
    base = dict(lote=None, cara=None, numero=numero, area=cuadro.get(numero) if numero else None)
    lotes = d.get("lotes") or []
    for i, lote in enumerate(lotes):
        if numeros_lote.es_resto(lote["numero"]) or (
                numero is not None and numeros_lote.clave(lote["numero"]) == numeros_lote.clave(numero)):
            return dict(base, lote=i)
    caras = d.get("sin_numero") or []
    if not lotes or not caras:
        return base
    mediana = float(np.median([_area_px(l) for l in lotes]))
    mayor = max(range(len(caras)), key=lambda k: _area_px(caras[k]))
    veces = _area_px(caras[mayor]) / mediana if mediana > 0 else 0.0
    es = veces > RESTO_VECES or (numero is not None and veces >= RESTO_VECES_CUADRO)
    return dict(base, cara=mayor if es else None)


def _fuera_del_kmz(partes: list | None, entradas: dict | None) -> list[bool]:
    """Por cada parte (lotes o caras sin número del digitalizado): ¿la dejó ella fuera del
    KMZ (un punto de `fuera` cae dentro)? Es una decisión sobre qué va al KMZ, no sobre
    cómo se parte el dibujo: por eso no entra en la huella de digitalizar y cambiarla no
    obliga a leer el plano. Vale también para una parte con número: el lector puede leer
    el "LOTE 8" del resto, y lo que ella decidió manda."""
    from shapely.geometry import Point
    partes = partes or []
    puntos = [Point(p) for p in (entradas or {}).get("fuera") or []]
    if not puntos:
        return [False] * len(partes)
    salida = []
    for parte in partes:
        forma = Polygon(parte["poligono"], parte.get("huecos") or [])
        if not forma.is_valid:
            forma = forma.buffer(0)
        salida.append(any(forma.contains(p) for p in puntos))
    return salida


def _con_lector(entradas: dict) -> bool:
    """¿Digitalizar va a leer los números solo? (lector encendido y Tesseract instalado)."""
    return bool(entradas.get("lector", True)) and rotulos.disponible()


def _resumen_lector(lector: dict | None) -> dict | None:
    """Lo que la pantalla muestra del lector: cuánto leyó y qué propone."""
    if not lector or not lector.get("activo"):
        return None
    # La cuadrícula se ofrece solo si alcanza para ubicar (el mismo criterio de
    # `por_cuadricula`): una a medias, al elegirla, no ubicaba nada y nadie decía por qué.
    cuadricula = lector.get("cuadricula")
    if not cuadricula_suficiente(cuadricula):
        cuadricula = None
    return dict(disponible=lector.get("disponible"), motivo=lector.get("motivo"),
                rotulos=len(lector.get("rotulos") or []), semillas=lector.get("semillas"),
                apoyo_min=lector.get("apoyo_min"), sin_poligono=lector.get("sin_poligono") or [],
                cuadricula=cuadricula, areas=len(lector.get("cuadro") or {}),
                # Los números tal como los dice el cuadro de superficies: la pantalla guarda
                # lo escrito con esa forma ("8-8" → "8-08") y ofrece los que faltan. Sin el
                # resto de la propiedad, que no es un lote que falte: va aparte.
                numeros_cuadro=numeros_lote.esperados(lector.get("cuadro") or {}),
                resto=numeros_lote.resto(lector.get("cuadro") or {}))


def _posiciones(cuadricula: dict | None) -> dict:
    """Dónde están las líneas de una cuadrícula, sin sus valores (se corrigen sin volver
    a digitalizar)."""
    cuadricula = cuadricula or {}
    return {f: [m.get(eje) for m in cuadricula.get(f) or []]
            for f, eje in (("verticales", "x"), ("horizontales", "y"))}


def _misma_posicion(a: dict, b: dict) -> bool:
    """¿Las mismas líneas en el mismo lugar? Con holgura de redondeo: la propuesta pasa
    por el navegador y vuelve."""
    return all(len(a[f]) == len(b[f]) and all(
        isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(x - y) < 0.05
        for x, y in zip(a[f], b[f])) for f in a)


def huella_digitalizar(entradas: dict, propuesta: dict | None = None) -> str:
    """Lo que, si cambia, deja atrasada la digitalización. `propuesta`: la cuadrícula que
    leyó el lector al digitalizar.

    Digitalizar sí usa la cuadrícula elegida: busca sus rectas en la imagen (para que
    ubicar mida el giro de la hoja) y borra su tinta antes de partir el dibujo en lotes.
    Pero si es la misma que propuso el lector, elegirla o quitarla no cuenta: la loteadora
    la elige en Ubicar para ubicar, con los lotes ya revisados, y no espera que eso los
    rehaga. Sus rectas igual quedan: digitalizar las busca también para la propuesta
    (sin borrar su tinta), así ubicar mide el giro de la hoja sin volver a digitalizar.
    Atrasar todo por eso hacía que "Usar la cuadrícula impresa" dejara los lotes
    desactualizados y "Seguir" trabado. La ubicación sí queda atrasada (`huella_ubicar`
    lleva la cuadrícula entera), que es lo que cambia."""
    # Sin unión de hojas la clave no entra: así la huella de los KMZ que ya existen no
    # cambia y lo que digitalizaron no queda atrasado.
    datos = {k: entradas.get(k) for k in CLAVES_DIGITALIZAR if k != "union" or entradas.get(k)}
    posiciones = _posiciones(entradas.get("cuadricula"))
    if propuesta and _misma_posicion(posiciones, _posiciones(propuesta)):
        posiciones = _posiciones(None)
    datos["cuadricula"] = posiciones
    return _huella(datos)


def huella_kmz(huella_georreferencia: str | None, digitalizado: dict, entradas: dict | None) -> str | None:
    """Con qué se hizo el KMZ: la ubicación y, si ella dejó fuera un lote con número, cuáles.
    Dejar fuera una parte sin número no cambia el KMZ y no lo deja atrasado."""
    lotes = digitalizado.get("lotes") or []
    fuera = sorted(str(l["numero"]) for l, f in zip(lotes, _fuera_del_kmz(lotes, entradas)) if f)
    return _huella(dict(ubicacion=huella_georreferencia, fuera=fuera)) if fuera else huella_georreferencia


def huella_ubicar(entradas: dict, huella_digitalizado: str) -> str:
    # `ubicacion` cuenta solo cuando `georreferenciar` la usa: completa y sin 2 puntos que
    # manden. Mientras ella la arma (solo la coordenada), o si ya ubicó con puntos, cambiarla
    # no cambia la ubicación y no debe dejarla atrasada. Sin ella, la huella es la de antes
    # de que existiera la clave: lo ya ubicado sigue al día.
    usa = ubicacion_completa(entradas.get("ubicacion")) and len(entradas.get("anclas") or []) < 2
    # `escala_cuadro` igual: solo con 2 o más puntos (y puesto) cambia la ubicación.
    ajusta = bool(entradas.get("escala_cuadro")) and len(entradas.get("anclas") or []) >= 2
    usadas = {"ubicacion": usa, "escala_cuadro": ajusta}
    datos = {k: entradas.get(k) for k in CLAVES_UBICAR if usadas.get(k, True)}
    return _huella(dict(datos, digitalizado=huella_digitalizado))


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


def _medidas(ruta: Path) -> list[tuple[float, float]]:
    """(megapíxeles, px por mm) de cada página al extraerla, sin decodificarla: lo
    mismo que decide `pipeline.plano.pagina.extraer` (la imagen embebida o el render)."""
    salida = []
    with pymupdf.open(ruta, filetype="pdf") as documento:
        for hoja in documento:
            imagenes = hoja.get_images(full=True)
            medida = None
            if imagenes:
                xref, _, ancho, alto = max(imagenes, key=lambda im: im[2] * im[3])[:4]
                rectangulos = hoja.get_image_rects(xref)
                if len(rectangulos) == 1:
                    caja = rectangulos[0] & hoja.rect
                    if (not caja.is_empty and caja.width * caja.height
                            >= pag.COBERTURA_MINIMA * hoja.rect.width * hoja.rect.height):
                        mm2 = (caja.width * pag.MM_POR_PUNTO) * (caja.height * pag.MM_POR_PUNTO)
                        medida = (ancho * alto / 1e6, float(np.sqrt(ancho * alto / mm2)))
            if medida is None:
                escala = pag.DPI_RENDER / 72
                medida = (hoja.rect.width * escala * hoja.rect.height * escala / 1e6, pag.DPI_RENDER / 25.4)
            salida.append(medida)
    return salida


def _escalar(sx: float, sy: float) -> np.ndarray:
    """De px de una imagen a px de la misma imagen escalada (sx, sy), con el centro del
    píxel en el entero: q = (p + ½)·s − ½."""
    return np.array([[sx, 0, 0.5 * sx - 0.5], [0, sy, 0.5 * sy - 0.5], [0, 0, 1]], float)


def _cargar(ruta: Path, s: float, modo: str) -> np.ndarray:
    """El JPEG de una página escalado a `s` (≤ 1) en `modo` ("RGB" o "L"). `draft`
    decodifica ya achicado, así la página entera no pasa por la memoria."""
    with Image.open(ruta) as imagen:
        ancho, alto = imagen.size
        destino = (max(round(ancho * s), 1), max(round(alto * s), 1))
        imagen.draft(modo, destino)
        imagen = imagen.convert(modo)
        if imagen.size != destino:
            imagen = imagen.resize(destino, Image.Resampling.BOX if s < 1 else Image.Resampling.BILINEAR)
        return np.asarray(imagen).copy()


def _escribir(destino: Path, datos: bytes) -> None:
    """Aparte y `os.replace`, como `escribir_json`: quien lo sirva mientras se escribe
    ve el anterior completo, o nada."""
    temporal = destino.with_name(f".{destino.name}.{os.getpid()}.{threading.get_ident()}")
    try:
        temporal.write_bytes(datos)
        os.replace(temporal, destino)
    finally:
        temporal.unlink(missing_ok=True)


def _jpeg(imagen: Image.Image, calidad: int = CALIDAD) -> bytes:
    buf = io.BytesIO()
    # Sin `convert` si ya es RGB: copiaría la unión entera (hasta 180 MB) para nada.
    (imagen if imagen.mode == "RGB" else imagen.convert("RGB")).save(buf, "JPEG", quality=calidad)
    return buf.getvalue()
