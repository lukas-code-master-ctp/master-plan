"""Los loteos que conoce la consola.

Un loteo es una carpeta con el KMZ, las panorámicas y un `proyecto.json`. Puede
venir de dos lados: subida desde el navegador (se guarda en `proyectos/<slug>/`) o
una carpeta que ya está en el disco, que se vincula sin copiar nada —las
panorámicas pesan cientos de megas y no tiene sentido duplicarlas.

De quién es cada loteo lo dice la base; qué hay construido lo dicen sus archivos.
Esa división importa: el avance nunca se guarda, se mira, y así la consola no
puede mentir sobre lo que existe.

**Las rutas no usan `Registro` directo.** Piden `registro.para(sesion)` y reciben
una `Vista` que solo alcanza los loteos de esa loteadora. El cliente no es un
argumento que se pueda olvidar: es parte de quién creó la vista.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pipeline import config

from .acceso import Sesion
from .datos import Base, NoEncontrado, ProyectoGuardado

CARPETA_SUBIDAS = config.DATOS / "proyectos"

EXTENSIONES_FOTO = (".jpg", ".jpeg")

# Lo que se guarda en `proyecto.json`, que es lo que lee el pipeline. El resto
# —de quién es, dónde quedó publicado— vive en la base y no se duplica acá.
CAMPOS_DEL_PIPELINE = ("nombre", "etapa", "whatsapp", "parcelacion", "despegue", "referencias")


@dataclass(frozen=True)
class Subida:
    """Un archivo que llega del navegador, con su ruta relativa dentro de la carpeta."""
    ruta: str
    contenido: bytes


@dataclass(frozen=True)
class Proyecto:
    slug: str
    nombre: str
    etapa: str
    whatsapp: str
    despegue: tuple[float, float] | None
    referencias: tuple
    fuentes: Path
    salida: config.Salida
    # El export comercial de ESTE cliente, si lo tiene. Nunca uno global: un
    # cliente sin planilla no puede terminar leyendo los precios de otro.
    crm: Path | None = None
    # Cómo se llama el loteo en el hosting y dónde quedó. Se guardan al publicar
    # por primera vez, leídos de lo que respondió el hosting: adivinarlos era lo
    # que hacía que dos clientes con el mismo nombre se pisaran el sitio.
    vercel_proyecto: str | None = None
    url_publicada: str | None = None

    @property
    def publicado(self) -> bool:
        return bool(self.url_publicada)

    @property
    def construido(self) -> bool:
        return (self.salida.datos / "parcelas.json").is_file()

    def resumen(self) -> dict:
        """Lo que quedó de la última construcción, leído de su propia salida."""
        archivo = self.salida.datos / "parcelas.json"
        if not archivo.is_file():
            return {}
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        vistas = json.loads((self.salida.datos / "vistas.json").read_text(encoding="utf-8"))
        return {
            "generado": datos.get("generado"),
            "parcelas": datos["resumen"]["total"],
            "por_estado": datos["resumen"]["por_estado"],
            "vistas": len(vistas["vistas"]),
            "calce": [
                {"vista": v["id"], "error_sol": v["diagnostico"]["error_elevacion"],
                 "mejora": v["diagnostico"].get("calibracion", {}).get("mejora", 0)}
                for v in vistas["vistas"]
            ],
        }

    def control_de_calce(self) -> list[str]:
        if not self.salida.qa.is_dir():
            return []
        return sorted(p.name for p in self.salida.qa.glob("*.jpg"))

    def fuentes_encontradas(self) -> dict:
        """Qué hay en la carpeta, para mostrarlo antes de construir.

        Las fotos repetidas se cuentan una vez: el volcado de la tarjeta suele dejar
        la misma toma en dos carpetas y el pipeline también la toma una sola vez.
        Acá alcanza con mirar nombre y tamaño; el pipeline, que sí tiene que acertar,
        compara la hora, el GPS y la altura del XMP.
        """
        if not self.fuentes.is_dir():
            return {"kmz": None, "panoramicas": 0, "megas": 0, "planilla": None}
        kmz = sorted(p.name for p in self.fuentes.rglob("*.kmz"))
        planillas = sorted(p.name for p in self.fuentes.rglob("*.xlsx") if not p.name.startswith("~$"))
        fotos: dict[tuple[str, int], int] = {}
        for ruta in self.fuentes.rglob("*"):
            if ruta.suffix.lower() in EXTENSIONES_FOTO:
                tamano = ruta.stat().st_size
                fotos[(ruta.name, tamano)] = tamano
        return {
            "kmz": kmz[0] if kmz else None,
            "panoramicas": len(fotos),
            "megas": round(sum(fotos.values()) / 1048576),
            "planilla": planillas[0] if planillas else None,
        }


class Registro:
    """Todos los loteos del sistema, y dónde viven sus archivos.

    No se usa directo desde las rutas: se pide `para(sesion)`.
    """

    def __init__(self, base: Base, subidas: Path = CARPETA_SUBIDAS,
                 salidas: Path = config.SALIDAS, crm_por_defecto: Path | None = None):
        self.base = base
        self.subidas = Path(subidas)
        self.salidas = Path(salidas)
        # Un export comercial para los loteos que no traen el suyo. Tiene sentido
        # en el computador del dueño, donde hay un solo dueño; en el servidor se
        # deja en None para que nadie herede los precios de otro.
        self.crm_por_defecto = Path(crm_por_defecto) if crm_por_defecto else None

    def para(self, sesion: Sesion) -> Vista:
        """Los loteos que esta sesión puede tocar. Plataforma los ve todos."""
        return Vista(registro=self, duenio=sesion.cliente_id,
                     filtro=None if sesion.es_plataforma else sesion.cliente_id)


@dataclass(frozen=True)
class Vista:
    """El registro visto por alguien.

    `filtro` es de quién puede ver (None = todos, para el equipo de CTP) y `duenio`
    de quién queda lo que cree. Son distintos a propósito: un operador de CTP mira
    los loteos de cualquiera, pero los que sube quedan a nombre de CTP.
    """
    registro: Registro
    duenio: int
    filtro: int | None

    # --- lectura -------------------------------------------------------------

    def listar(self) -> list[Proyecto]:
        return [self._leer(g) for g in self.registro.base.proyectos(cliente_id=self.filtro)]

    def ver(self, slug: str) -> Proyecto:
        """El loteo, o `NoEncontrado` si no existe o no es suyo. No se distingue:
        decir "existe pero no es tuyo" ya es contar algo."""
        return self._leer(self.registro.base.proyecto(slug, cliente_id=self.filtro))

    # --- alta ----------------------------------------------------------------

    def crear(self, nombre: str, archivos: list[Subida]) -> Proyecto:
        """Guarda los archivos subidos en una carpeta nueva y registra el loteo."""
        if not any(a.ruta.lower().endswith(".kmz") for a in archivos):
            raise ValueError("falta el KMZ del loteo entre los archivos")

        guardado = self.registro.base.crear_proyecto(self.duenio, nombre)
        carpeta = self.registro.subidas / guardado.slug
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            for archivo in archivos:
                destino = _destino_seguro(carpeta, archivo.ruta)
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_bytes(archivo.contenido)
            self._escribir_json(carpeta, guardado.slug, {"nombre": nombre})
        except Exception:
            # Sin esto el loteo quedaría anotado y vacío, y el nombre bloqueado
            # para volver a intentarlo.
            self.registro.base.olvidar_proyecto(guardado.slug)
            shutil.rmtree(carpeta, ignore_errors=True)
            raise
        return self._leer(self.registro.base.proyecto(guardado.slug, cliente_id=self.filtro))

    def vincular(self, carpeta: Path) -> Proyecto:
        """Registra una carpeta que ya está en el disco, sin copiar nada.

        Solo tiene sentido en el computador donde están las fotos; la consola
        desplegada no la ofrece, porque sería leer cualquier ruta del servidor.
        """
        carpeta = Path(carpeta).expanduser().resolve()
        if not carpeta.is_dir():
            raise FileNotFoundError(f"no existe la carpeta {carpeta}")
        if not any(carpeta.rglob("*.kmz")):
            raise ValueError(f"no encontré el KMZ del loteo dentro de {carpeta.name}")

        ya = self._por_carpeta(carpeta)
        if ya is not None:
            return self._leer(ya)

        datos = config.cargar_proyecto(carpeta)
        # Si la carpeta ya trae slug, se respeta: es un loteo construido y quizá
        # publicado, y cambiárselo dejaría su sitio colgando. Lo mismo con dónde
        # quedó publicado: la carpeta se describe a sí misma, así que adoptarla
        # devuelve el loteo entero aunque la base se hubiera perdido.
        suyo = _leer_json(carpeta / "proyecto.json")
        guardado = self.registro.base.crear_proyecto(
            self.duenio, datos.nombre, slug=datos.slug_guardado or None, carpeta=str(carpeta),
            vercel_proyecto=suyo.get("vercel_proyecto") or None,
            url_publicada=suyo.get("url_publicada") or None)
        self._escribir_json(carpeta, guardado.slug, {})
        return self._leer(guardado)

    # --- edición -------------------------------------------------------------

    def ajustar(self, slug: str, campos: dict) -> Proyecto:
        """Reescribe `proyecto.json` con lo que venga, dejando el resto como estaba.

        El slug no cambia aunque cambie el nombre: es la carpeta de salida y la URL
        publicada, y renombrarlo dejaría el sitio anterior colgando.
        """
        proyecto = self.ver(slug)
        limpios = {c: v for c, v in campos.items() if v is not None and c in CAMPOS_DEL_PIPELINE}
        if "nombre" in limpios:
            self.registro.base.renombrar_proyecto(slug, str(limpios["nombre"]))
        self._escribir_json(proyecto.fuentes, slug, limpios)
        return self.ver(slug)

    def anotar_publicacion(self, slug: str, *, vercel_proyecto: str, url: str) -> Proyecto:
        """Guarda con qué nombre y en qué URL quedó publicado el loteo.

        Se escribe en los dos lados: la base es de donde se lee, y la copia en la
        carpeta es lo que permite volver a adoptar el loteo con su identidad si
        algún día hay que rehacer la base.
        """
        proyecto = self.ver(slug)
        self.registro.base.anotar_publicacion(slug, vercel_proyecto, url)
        self._escribir_json(proyecto.fuentes, slug,
                            {"vercel_proyecto": vercel_proyecto, "url_publicada": url})
        return self.ver(slug)

    def olvidar(self, slug: str) -> None:
        """Saca el loteo de la lista. No borra archivos: no son nuestros."""
        self.ver(slug)
        self.registro.base.olvidar_proyecto(slug)

    # --- interno -------------------------------------------------------------

    def _por_carpeta(self, carpeta: Path) -> ProyectoGuardado | None:
        for guardado in self.registro.base.proyectos(cliente_id=self.filtro):
            if guardado.carpeta and Path(guardado.carpeta) == carpeta:
                return guardado
        return None

    def _leer(self, guardado: ProyectoGuardado) -> Proyecto:
        carpeta = (Path(guardado.carpeta) if guardado.carpeta
                   else self.registro.subidas / guardado.slug)
        datos = config.cargar_proyecto(carpeta)
        return Proyecto(
            slug=guardado.slug,
            nombre=guardado.nombre,
            etapa=datos.etapa,
            whatsapp=datos.whatsapp,
            despegue=datos.despegue,
            referencias=datos.referencias,
            fuentes=carpeta,
            salida=config.Salida(self.registro.salidas / guardado.slug),
            crm=self._crm_de(carpeta),
            vercel_proyecto=guardado.vercel_proyecto,
            url_publicada=guardado.url_publicada,
        )

    def _escribir_json(self, carpeta: Path, slug: str, campos: dict) -> None:
        """Deja en la carpeta lo que el pipeline necesita leer, sin tocar lo demás."""
        archivo = carpeta / "proyecto.json"
        datos = _leer_json(archivo)
        datos.update(campos)
        datos["slug"] = slug
        archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")

    def _crm_de(self, carpeta: Path) -> Path | None:
        propio = carpeta / "crm.csv"
        if propio.is_file():
            return propio
        por_defecto = self.registro.crm_por_defecto
        return por_defecto if por_defecto and por_defecto.is_file() else None


def _leer_json(archivo: Path) -> dict:
    return json.loads(archivo.read_text(encoding="utf-8")) if archivo.is_file() else {}


def _destino_seguro(carpeta: Path, relativa: str) -> Path:
    """Impide que un nombre con `..` escriba fuera de la carpeta del proyecto."""
    destino = (carpeta / relativa).resolve()
    if carpeta.resolve() not in destino.parents:
        raise ValueError(f"ruta inválida en la subida: {relativa!r}")
    return destino


def fecha_legible(iso: str | None) -> str:
    if not iso:
        return ""
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")


__all__ = ["CARPETA_SUBIDAS", "NoEncontrado", "Proyecto", "Registro", "Subida", "Vista",
           "fecha_legible"]
