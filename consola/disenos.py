"""Mis diseños: la marca con que una loteadora publica sus loteos.

Un diseño es un color, un logo, una tipografía y los textos de los dos botones
que convierten una mirada en un contacto. Nada más a propósito: el visor tiene
que seguir leyéndose igual en todos los sitios, y el color de cada estado
(disponible, vendido…) significa lo mismo en todos.

El diseño no pasa por el pipeline. Se escribe en `sitio/datos/diseno.json`
—y el logo al lado— al construir y al publicar, así que cambiarlo no obliga a
reconstruir: basta con volver a publicar. Sin ese archivo el visor se ve como
siempre.

Aislamiento: igual que los loteos. Las rutas piden `disenos.para(sesion)` y
reciben una vista que solo alcanza los de esa loteadora; uno ajeno da 404.
"""
from __future__ import annotations

import json
import re
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from pipeline import config

from .acceso import Sesion
from .datos import Base, Diseno

CARPETA_DISENOS = config.DATOS / "disenos"

# Lo que puede elegirse, y con qué se dibuja en el visor (`web/js/marca.js`).
# Solo tipografías que no hay que bajar de ningún lado: la del producto y dos
# familias del sistema.
TIPOGRAFIAS = {
    "jakarta": "Plus Jakarta Sans",
    "serif": "Serif clásica",
    "sistema": "La del sistema",
}
COLOR_POR_DEFECTO = "#27272a"
LARGO_NOMBRE = 120
LARGO_CONTACTO = 60
LARGO_PAGO = 40

# El logo se muestra en una barra de 4 rem: no hace falta más que esto.
TOPE_LOGO = 512 * 1024
FIRMAS_LOGO = {
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",),
}
# Un SVG es un documento que puede traer código. Se sirve como imagen, donde no
# corre, pero abierto directo en el sitio publicado sí correría. Buscar lo
# peligroso con una expresión regular no alcanza (`<a:script>` con prefijo de
# namespace se le pasa), así que se lee como XML y solo se acepta lo que es
# dibujo: una lista de elementos permitidos, ningún atributo `on…`, y
# referencias solo internas (`#algo`).
SVG_ELEMENTOS = frozenset({
    "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "defs", "lineargradient", "radialgradient", "stop", "clippath", "mask", "use",
    "symbol", "title", "desc", "text", "tspan", "style", "pattern", "metadata",
})
# Lo que en un valor de atributo o en un <style> trae algo de afuera o ejecuta.
SVG_VALOR_PELIGROSO = re.compile(r"javascript:|@import|url\(\s*['\"]?\s*(?!#)|expression\(",
                                 re.IGNORECASE)

HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class DisenoInvalido(ValueError):
    """Lo que llegó no sirve como diseño. El mensaje es para la persona."""


def limpiar(campos: dict, *, parcial: bool = False) -> dict:
    """Los campos de un diseño, validados. Con `parcial`, solo los que vinieron."""
    limpios: dict = {}
    if "nombre" in campos or not parcial:
        nombre = str(campos.get("nombre") or "").strip()
        if not nombre:
            raise DisenoInvalido("ponle un nombre al diseño")
        limpios["nombre"] = nombre[:LARGO_NOMBRE]
    if "color" in campos or not parcial:
        color = str(campos.get("color") or COLOR_POR_DEFECTO).strip()
        if not HEX.match(color):
            raise DisenoInvalido("el color va como #RRGGBB, por ejemplo #1f5132")
        limpios["color"] = color.lower()
    if "tipografia" in campos or not parcial:
        tipografia = str(campos.get("tipografia") or "jakarta")
        if tipografia not in TIPOGRAFIAS:
            raise DisenoInvalido("esa tipografía no está entre las que se pueden elegir")
        limpios["tipografia"] = tipografia
    for campo, largo in (("texto_contacto", LARGO_CONTACTO), ("texto_pago", LARGO_PAGO)):
        if campo in campos or not parcial:
            valor = str(campos.get(campo) or "").strip()
            limpios[campo] = valor[:largo] or None
    return limpios


def revisar_logo(nombre: str, contenido: bytes) -> str:
    """La extensión con que se guarda el logo, o `DisenoInvalido`."""
    extension = Path(nombre).suffix.lower()
    if len(contenido) > TOPE_LOGO:
        raise DisenoInvalido(f"el logo pesa más de {TOPE_LOGO // 1024} KB")
    if extension == ".svg":
        if not svg_es_solo_dibujo(contenido):
            raise DisenoInvalido("ese SVG trae algo más que un dibujo; súbelo como PNG")
        return ".svg"
    firmas = FIRMAS_LOGO.get(extension)
    if not firmas:
        raise DisenoInvalido("el logo va en PNG, JPG, WebP o SVG")
    if not any(contenido.startswith(f) for f in firmas):
        raise DisenoInvalido(f"ese archivo no es un {extension[1:].upper()} de verdad")
    if extension == ".webp" and contenido[8:12] != b"WEBP":
        raise DisenoInvalido("ese archivo no es un WEBP de verdad")
    return ".jpg" if extension == ".jpeg" else extension


def svg_es_solo_dibujo(contenido: bytes) -> bool:
    """¿El SVG es solo dibujo? Ver `SVG_ELEMENTOS`."""
    # Sin DTD no hay entidades que expandir: se corta antes de parsear, que es
    # de lo que protege defusedxml sin tener que sumarlo como dependencia.
    if re.search(rb"<!\s*(DOCTYPE|ENTITY)", contenido, re.IGNORECASE):
        return False
    try:
        raiz = ET.fromstring(contenido)
    except ET.ParseError:
        return False
    if _local(raiz.tag) != "svg":
        return False
    for elemento in raiz.iter():
        if not isinstance(elemento.tag, str) or _local(elemento.tag) not in SVG_ELEMENTOS:
            return False
        for nombre, valor in elemento.attrib.items():
            local = _local(nombre)
            if local.startswith("on") or SVG_VALOR_PELIGROSO.search(valor):
                return False
            if local == "href" and not valor.strip().startswith("#"):
                return False
        if _local(elemento.tag) == "style" and SVG_VALOR_PELIGROSO.search(elemento.text or ""):
            return False
    return True


def _local(nombre: str) -> str:
    """El nombre sin namespace, en minúsculas: `{http://…}script` → `script`."""
    return nombre.rsplit("}", 1)[-1].split(":")[-1].lower()


def como_json(diseno: Diseno) -> dict:
    return {
        "id": diseno.id,
        "nombre": diseno.nombre,
        "color": diseno.color,
        "tipografia": diseno.tipografia,
        "logo": bool(diseno.logo),
        "texto_contacto": diseno.texto_contacto,
        "texto_pago": diseno.texto_pago,
    }


@dataclass(frozen=True)
class Disenos:
    """Todos los diseños, y dónde viven sus logos."""
    base: Base
    carpeta: Path = CARPETA_DISENOS

    def para(self, sesion: Sesion) -> VistaDisenos:
        return VistaDisenos(self, duenio=sesion.cliente_id,
                            filtro=None if sesion.es_plataforma else sesion.cliente_id)

    def carpeta_de(self, diseno_id: int) -> Path:
        return self.carpeta / str(diseno_id)

    def logo_de(self, diseno: Diseno) -> Path | None:
        if not diseno.logo:
            return None
        archivo = self.carpeta_de(diseno.id) / diseno.logo
        return archivo if archivo.is_file() else None

    def escribir_en_sitio(self, diseno_id: int | None, datos: Path) -> None:
        """Deja el diseño junto a los datos del sitio.

        `datos` es `sitio/datos` de un loteo construido. Se reescribe entero
        cada vez: un logo o un diseño viejo que quedara ahí se publicaría. Sin
        diseño se escribe `null` y no se borra el archivo: el visor lo pide
        siempre, y un 404 en cada visita ensucia la consola del navegador de
        quien mira el sitio.
        """
        for viejo in datos.glob("logo.*"):
            viejo.unlink()
        destino = datos / "diseno.json"
        if diseno_id is None:
            destino.write_text("null", encoding="utf-8")
            return
        diseno = self.base.diseno(diseno_id)
        contenido = {
            "color": diseno.color,
            "tipografia": diseno.tipografia,
            "texto_contacto": diseno.texto_contacto,
            "texto_pago": diseno.texto_pago,
            "logo": None,
        }
        logo = self.logo_de(diseno)
        if logo is not None:
            nombre = f"logo{logo.suffix}"
            shutil.copyfile(logo, datos / nombre)
            contenido["logo"] = nombre
        destino.write_text(json.dumps(contenido, ensure_ascii=False, indent=1), encoding="utf-8")


@dataclass(frozen=True)
class VistaDisenos:
    """Los diseños que alguien puede ver y tocar. Como `Vista` para los loteos."""
    disenos: Disenos
    duenio: int
    filtro: int | None

    def listar(self) -> list[Diseno]:
        return self.disenos.base.disenos(cliente_id=self.filtro)

    def ver(self, diseno_id: int) -> Diseno:
        return self.disenos.base.diseno(diseno_id, cliente_id=self.filtro)

    def crear(self, campos: dict) -> Diseno:
        return self.disenos.base.crear_diseno(self.duenio, limpiar(campos))

    def ajustar(self, diseno_id: int, campos: dict) -> Diseno:
        self.ver(diseno_id)
        limpios = limpiar(campos, parcial=True)
        if not limpios:
            return self.ver(diseno_id)
        return self.disenos.base.actualizar_diseno(diseno_id, limpios)

    def borrar(self, diseno_id: int) -> None:
        self.ver(diseno_id)
        self.disenos.base.borrar_diseno(diseno_id)
        shutil.rmtree(self.disenos.carpeta_de(diseno_id), ignore_errors=True)

    def subir_logo(self, diseno_id: int, nombre: str, contenido: bytes) -> Diseno:
        diseno = self.ver(diseno_id)
        extension = revisar_logo(nombre, contenido)
        carpeta = self.disenos.carpeta_de(diseno.id)
        carpeta.mkdir(parents=True, exist_ok=True)
        for viejo in carpeta.glob("logo.*"):
            viejo.unlink()
        (carpeta / f"logo{extension}").write_bytes(contenido)
        return self.disenos.base.actualizar_diseno(diseno.id, {"logo": f"logo{extension}"})

    def quitar_logo(self, diseno_id: int) -> Diseno:
        diseno = self.ver(diseno_id)
        for viejo in self.disenos.carpeta_de(diseno.id).glob("logo.*"):
            viejo.unlink()
        return self.disenos.base.actualizar_diseno(diseno.id, {"logo": None})

    def para_el_loteo(self, diseno_id: int | None, cliente_del_loteo: int) -> int | None:
        """El diseño que se le puede poner a un loteo: visible para quien pide y
        de la misma loteadora que el loteo. Un operador de CTP no puede ponerle
        a un cliente la marca de otro."""
        if diseno_id is None:
            return None
        diseno = self.ver(int(diseno_id))
        if diseno.cliente_id != cliente_del_loteo:
            raise DisenoInvalido("ese diseño es de otra loteadora")
        return diseno.id
