"""Mis KMZ: el KMZ que una loteadora arma desde el plano aprobado, sin master.

Un KMZ tiene nombre y dueña (la base) y una carpeta `kmz/<slug>/` con lo mismo que
Crea tu KMZ guarda para un plano (ver `consola/plano.py`) más el resultado,
`<slug>.kmz`. Si está terminado lo dice el disco: existe ese archivo.

Aislamiento: igual que los masters y los diseños. Las rutas piden
`kmzs.para(sesion)` y reciben una vista que solo alcanza los de esa loteadora; uno
ajeno da `NoEncontrado` (404). El equipo de CTP los ve todos.

Sus trabajos de fondo van con la clave `kmz:<slug>`, que no choca con el slug de un
master (un slug no lleva ":").
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from pipeline import config
from pipeline.plano.digitalizar import SALIDA as DIGITALIZADO

from .acceso import Sesion
from .datos import Base, KmzGuardado
from .plano import PDF, Plano
from .proyectos import MEGA, LimiteAlcanzado, Limites, Subida

CARPETA_KMZ = config.DATOS / "kmz"
LARGO_NOMBRE = 160
PREFIJO = "kmz:"
# Lo que da `datos._slug`: nunca vacío, sin "/", ".." ni ":".
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class NombreInvalido(ValueError):
    """El nombre no sirve (400). El mensaje es para la persona."""


def clave(slug: str) -> str:
    """La clave de sus trabajos en `Trabajos`."""
    return f"{PREFIJO}{slug}"


def slug_de_clave(clave_trabajo: str) -> str | None:
    """El slug del KMZ si la clave es de un KMZ; None si es de un master."""
    return clave_trabajo[len(PREFIJO):] if clave_trabajo.startswith(PREFIJO) else None


def _limpiar(nombre) -> str:
    nombre = str(nombre or "").strip()[:LARGO_NOMBRE].strip()
    if not nombre:
        raise NombreInvalido("ponle un nombre al KMZ")
    return nombre


class RegistroKmz:
    """Todos los KMZ y dónde viven. Las rutas no lo usan directo: piden `para(sesion)`."""

    def __init__(self, base: Base, carpeta: Path = CARPETA_KMZ, limites: Limites | None = None):
        self.base = base
        self.carpeta = Path(carpeta)
        self.limites = limites or Limites()

    def para(self, sesion: Sesion) -> VistaKmz:
        return VistaKmz(registro=self, duenio=sesion.cliente_id,
                        filtro=None if sesion.es_plataforma else sesion.cliente_id)

    def carpeta_de(self, slug: str) -> Path:
        """`kmz/<slug>/`. Se crea vacía y se borra entera: un slug que no sea de los que
        da la base (vacío, con "/" o "..") apuntaría a `kmz/` mismo o fuera de ella."""
        if not SLUG.fullmatch(slug or ""):
            raise ValueError(f"slug de KMZ inválido: {slug!r}")
        return self.carpeta / slug

    def plano_de(self, guardado: KmzGuardado) -> Plano:
        carpeta = self.carpeta_de(guardado.slug)
        return Plano(carpeta, destino_kmz=carpeta / f"{guardado.slug}.kmz", nombre=guardado.nombre)


@dataclass(frozen=True)
class VistaKmz:
    """Los KMZ que alguien puede ver y tocar. Como `Vista` para los masters."""
    registro: RegistroKmz
    duenio: int
    filtro: int | None

    @property
    def es_equipo(self) -> bool:
        return self.filtro is None

    def listar(self) -> list[KmzGuardado]:
        return self.registro.base.kmzs(cliente_id=self.filtro)

    def ver(self, slug: str) -> KmzGuardado:
        """El KMZ, o `NoEncontrado` si no existe o no es suyo. No se distingue."""
        return self.registro.base.kmz(slug, cliente_id=self.filtro)

    def crear(self, nombre) -> KmzGuardado:
        guardado = self.registro.base.crear_kmz(self.duenio, _limpiar(nombre))
        carpeta = self.registro.carpeta_de(guardado.slug)
        # El slug estaba libre en la base: lo que hubiera en su carpeta es de uno
        # borrado a medias, y no puede aparecer en este.
        shutil.rmtree(carpeta, ignore_errors=True)
        carpeta.mkdir(parents=True, exist_ok=True)
        return guardado

    def renombrar(self, slug: str, nombre) -> KmzGuardado:
        self.ver(slug)
        return self.registro.base.renombrar_kmz(slug, _limpiar(nombre))

    def borrar(self, slug: str) -> None:
        """Con su carpeta. Que no corra nada sobre él lo mira la ruta."""
        self.ver(slug)
        shutil.rmtree(self.registro.carpeta_de(slug), ignore_errors=True)
        self.registro.base.borrar_kmz(slug)

    def plano(self, slug: str) -> Plano:
        return self.registro.plano_de(self.ver(slug))

    def subir_plano(self, slug: str, archivo: Subida) -> list[dict]:
        """Guarda el PDF y extrae sus páginas. Tiene el mismo tope de disco que un master."""
        plano = self.plano(slug)
        if not self.es_equipo:
            tope = self.registro.limites.megas_por_loteo * MEGA
            pisado = plano.carpeta / PDF
            ya = sum(p.stat().st_size for p in plano.carpeta.rglob("*")
                     if p.is_file() and p != pisado) if plano.carpeta.is_dir() else 0
            if ya + archivo.bytes > tope:
                raise LimiteAlcanzado(
                    f"el plano quedaría en {round((ya + archivo.bytes) / MEGA)} MB y el máximo es "
                    f"{self.registro.limites.megas_por_loteo} MB")
        return plano.subir_pdf(archivo.contenido)

    def resumen(self, guardado: KmzGuardado) -> dict:
        """Lo de la tarjeta en Mis KMZ: en qué paso va, cuántos lotes y si está listo.

        `paso` es el del plano actual y `terminado`, que hay un `.kmz` para bajar o usar.
        Pueden no coincidir a propósito: subir otro PDF reinicia los pasos pero no se
        lleva el KMZ ya hecho, que sigue sirviendo hasta que se cree el nuevo. La
        pantalla muestra el paso; `terminado` solo habilita Descargar y Usar."""
        plano = self.registro.plano_de(guardado)
        lotes = None
        try:
            paso = plano.paso()
            digitalizado = plano.carpeta / DIGITALIZADO
            if digitalizado.is_file():
                lotes = len(json.loads(digitalizado.read_text(encoding="utf-8")).get("lotes") or [])
        except (OSError, ValueError):
            # Un plano a medio escribir no puede tumbar la lista.
            paso = "subir"
        return {"slug": guardado.slug, "nombre": guardado.nombre, "paso": paso, "lotes": lotes,
                "terminado": plano.terminado(), "creado_en": guardado.creado_en.isoformat()}
