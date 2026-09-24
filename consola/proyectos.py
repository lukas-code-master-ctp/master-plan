"""Los proyectos que conoce la consola.

Un proyecto es una carpeta con el KMZ, las panorámicas y un `proyecto.json`. Puede
venir de dos lados: subida desde el navegador (se guarda en `proyectos/<slug>/`) o
una carpeta que ya está en el disco, que se vincula sin copiar nada —las
panorámicas pesan cientos de megas y no tiene sentido duplicarlas.

El estado del proyecto no se guarda acá: se deduce mirando sus archivos y su
salida. Así la consola nunca miente sobre lo que hay construido.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pipeline import config

ARCHIVO_REGISTRO = config.DATOS / "proyectos.json"
CARPETA_SUBIDAS = config.DATOS / "proyectos"

EXTENSIONES_FOTO = (".jpg", ".jpeg")


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
    """Las carpetas que la consola tiene a la vista, en un JSON al lado del código."""

    def __init__(self, archivo: Path = ARCHIVO_REGISTRO, subidas: Path = CARPETA_SUBIDAS,
                 salidas: Path = config.SALIDAS, crm_por_defecto: Path | None = None):
        self.archivo = Path(archivo)
        self.subidas = Path(subidas)
        self.salidas = Path(salidas)
        # Un export comercial para los loteos que no traen el suyo. Tiene sentido
        # en el computador del dueño, donde hay un solo dueño; en el servidor se
        # deja en None para que nadie herede los precios de otro.
        self.crm_por_defecto = Path(crm_por_defecto) if crm_por_defecto else None

    # --- lectura -------------------------------------------------------------

    def listar(self) -> list[Proyecto]:
        return [self._leer(ruta) for ruta in self._rutas() if ruta.is_dir()]

    def ver(self, slug: str) -> Proyecto:
        for proyecto in self.listar():
            if proyecto.slug == slug:
                return proyecto
        raise KeyError(f"no tengo registrado el proyecto {slug!r}")

    # --- alta ----------------------------------------------------------------

    def vincular(self, carpeta: Path) -> Proyecto:
        """Registra una carpeta que ya está en el disco, sin copiar nada."""
        carpeta = Path(carpeta).expanduser().resolve()
        if not carpeta.is_dir():
            raise FileNotFoundError(f"no existe la carpeta {carpeta}")
        if not any(carpeta.rglob("*.kmz")):
            raise ValueError(f"no encontré el KMZ del loteo dentro de {carpeta.name}")

        rutas = self._rutas()
        if carpeta not in rutas:
            self._guardar(rutas + [carpeta])
        return self._leer(carpeta)

    def crear(self, nombre: str, archivos: list[Subida]) -> Proyecto:
        """Guarda los archivos subidos en una carpeta nueva y la registra."""
        if not any(a.ruta.lower().endswith(".kmz") for a in archivos):
            raise ValueError("falta el KMZ del loteo entre los archivos")

        carpeta = self.subidas / config.Proyecto(nombre=nombre).slug
        carpeta.mkdir(parents=True, exist_ok=True)
        for archivo in archivos:
            destino = self._destino_seguro(carpeta, archivo.ruta)
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(archivo.contenido)

        archivo_json = carpeta / "proyecto.json"
        if not archivo_json.is_file():
            archivo_json.write_text(json.dumps({"nombre": nombre}, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        return self.vincular(carpeta)

    # --- edición -------------------------------------------------------------

    def ajustar(self, slug: str, campos: dict) -> Proyecto:
        """Reescribe `proyecto.json` con lo que venga, dejando el resto como estaba.

        El slug no cambia aunque cambie el nombre: es la carpeta de salida y la URL
        publicada, y renombrarlo dejaría el sitio anterior colgando.
        """
        return self._escribir(slug, {c: v for c, v in campos.items() if v is not None})

    def _escribir(self, slug: str, campos: dict) -> Proyecto:
        """Reescribe `proyecto.json` dejando intacto lo que no se toca."""
        proyecto = self.ver(slug)
        archivo = proyecto.fuentes / "proyecto.json"
        datos = _leer_json(archivo)
        datos.update(campos)
        datos["slug"] = slug
        archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
        return self._leer(proyecto.fuentes)

    def anotar_publicacion(self, slug: str, *, vercel_proyecto: str, url: str) -> Proyecto:
        """Guarda con qué nombre y en qué URL quedó publicado el loteo."""
        return self._escribir(slug, {"vercel_proyecto": vercel_proyecto, "url_publicada": url})

    def olvidar(self, slug: str) -> None:
        """Saca el proyecto de la lista. No borra archivos: no son nuestros."""
        proyecto = self.ver(slug)
        self._guardar([r for r in self._rutas() if r != proyecto.fuentes])

    # --- interno -------------------------------------------------------------

    def _rutas(self) -> list[Path]:
        if not self.archivo.is_file():
            return []
        return [Path(r) for r in json.loads(self.archivo.read_text(encoding="utf-8"))]

    def _guardar(self, rutas: list[Path]) -> None:
        self.archivo.parent.mkdir(parents=True, exist_ok=True)
        self.archivo.write_text(json.dumps([str(r) for r in rutas], ensure_ascii=False, indent=1),
                                encoding="utf-8")

    def _leer(self, carpeta: Path) -> Proyecto:
        # `cargar_proyecto` ya honra el slug guardado en proyecto.json: un loteo
        # renombrado conserva el slug con el que se construyó y publicó.
        datos = config.cargar_proyecto(carpeta)
        slug = datos.slug
        guardado = _leer_json(carpeta / "proyecto.json")
        return Proyecto(
            slug=slug,
            nombre=datos.nombre,
            etapa=datos.etapa,
            whatsapp=datos.whatsapp,
            despegue=datos.despegue,
            referencias=datos.referencias,
            fuentes=carpeta,
            salida=config.Salida(self.salidas / slug),
            crm=self._crm_de(carpeta),
            vercel_proyecto=guardado.get("vercel_proyecto") or None,
            url_publicada=guardado.get("url_publicada") or None,
        )

    def _crm_de(self, carpeta: Path) -> Path | None:
        propio = carpeta / "crm.csv"
        if propio.is_file():
            return propio
        return self.crm_por_defecto if self.crm_por_defecto and self.crm_por_defecto.is_file() else None

    @staticmethod
    def _destino_seguro(carpeta: Path, relativa: str) -> Path:
        """Impide que un nombre con `..` escriba fuera de la carpeta del proyecto."""
        destino = (carpeta / relativa).resolve()
        if carpeta.resolve() not in destino.parents:
            raise ValueError(f"ruta inválida en la subida: {relativa!r}")
        return destino


def _leer_json(archivo: Path) -> dict:
    return json.loads(archivo.read_text(encoding="utf-8")) if archivo.is_file() else {}


def fecha_legible(iso: str | None) -> str:
    if not iso:
        return ""
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")
