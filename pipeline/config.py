"""Rutas y parámetros del pipeline.

Todo lo configurable vive aquí. Lo que cambia de un loteo a otro (nombre, teléfono,
parcelación en el CRM) va en un `proyecto.json` dentro de la carpeta del proyecto o
por línea de comandos; el código no se toca.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# --- Rutas -------------------------------------------------------------------

RAIZ = Path(__file__).resolve().parent.parent

# Dónde vive todo lo que el pipeline escribe y recuerda. En este computador es el
# propio repo; en un contenedor es un volumen, porque el disco de la imagen se
# pierde al reiniciar.
DATOS = Path(os.environ.get("MASTERPLAN_DATOS", RAIZ))

# Por defecto las fuentes se buscan en la carpeta que contiene a masterplan360.
# Para otro proyecto: python -m pipeline.construir --proyecto "ruta/a/la/carpeta"
PROYECTO = RAIZ.parent

# El sitio (html, css, js) del que se copia cada salida.
PLANTILLA_WEB = RAIZ / "web"

# Cada proyecto construido queda en salidas/<proyecto>/sitio, listo para subir.
SALIDAS = DATOS / "salidas"

# Teselas del modelo de elevación y coordenadas ya geocodificadas, compartidas
# entre proyectos y corridas.
_CACHE = DATOS / ".cache" if DATOS == RAIZ else DATOS / "cache"
CACHE_TERRENO = _CACHE / "terreno"
CACHE_REFERENCIAS = _CACHE / "referencias.json"

# Export del CRM del que sale la planilla cuando el proyecto no trae xlsx.
CRM_CSV_JUNTO_AL_REPO = RAIZ.parent / "agente_reporteria" / "data" / "output" / "ctp_parcelas_latest.csv"


def csv_del_crm() -> Path | None:
    """El export del CRM, si está.

    Se busca cada vez y no al importar: en un contenedor el archivo llega al
    volumen mucho después de que el proceso arrancó, y mirarlo una sola vez
    dejaría todas las parcelas como "no disponible" hasta el próximo reinicio.
    """
    indicado = os.environ.get("MASTERPLAN_CRM_CSV")
    if indicado:
        ruta = Path(indicado)
        return ruta if ruta.is_file() else None
    # Solo el repo de reportería al lado, que existe en el computador del dueño.
    # NO se busca un CSV en la carpeta de datos: ahí conviven varios clientes y
    # un archivo global significaría que quien no trae planilla hereda precios
    # ajenos. Quien tenga export propio lo recibe por --crm.
    return CRM_CSV_JUNTO_AL_REPO if CRM_CSV_JUNTO_AL_REPO.is_file() else None


@dataclass(frozen=True)
class Fuentes:
    kmz: Path
    panoramas: Path
    excel: Path | None = None
    crm: Path | None = None


def descubrir_fuentes(carpeta: Path, crm: Path | None = None,
                      sin_crm: bool = False) -> Fuentes:
    """Encuentra el KMZ, la planilla y las panorámicas dentro de una carpeta.

    Se descubren por tipo y no por nombre: cada proyecto llega con los archivos
    llamados como los haya dejado el topógrafo o el piloto, y no tiene sentido
    editar código para eso. La planilla es opcional: sin ella los datos comerciales
    salen del CRM, y sin CRM las parcelas quedan como no disponibles.
    """
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        raise FileNotFoundError(f"no existe la carpeta del proyecto: {carpeta}")

    # `sin_crm` es cómo la consola dice "este loteo no tiene export". Sin eso, un
    # loteo de otro cliente caería al export por defecto de este computador.
    csv_crm = None if sin_crm else (Path(crm) if crm else csv_del_crm())
    return Fuentes(
        kmz=_unico(carpeta, "*.kmz", "el KMZ del loteo"),
        panoramas=_carpeta_de_panoramas(carpeta),
        excel=_opcional(carpeta, "*.xlsx"),
        crm=csv_crm if csv_crm and Path(csv_crm).is_file() else None,
    )


def _es_nuestro(ruta: Path) -> bool:
    """¿La ruta está dentro de masterplan360? Ahí vive lo que genera el propio
    pipeline, y si no se excluye se confunde con las fuentes."""
    return RAIZ == ruta or RAIZ in ruta.parents


def _candidatos(carpeta: Path, patron: str) -> list[Path]:
    # Se ignoran los temporales que Excel deja abiertos (~$archivo.xlsx).
    return sorted(p for p in carpeta.rglob(patron)
                  if not p.name.startswith("~$") and not _es_nuestro(p))


def _unico(carpeta: Path, patron: str, que: str) -> Path:
    encontrados = _candidatos(carpeta, patron)
    if not encontrados:
        raise FileNotFoundError(f"no encontré {que} ({patron}) dentro de {carpeta}")
    return encontrados[0]


def _opcional(carpeta: Path, patron: str) -> Path | None:
    encontrados = _candidatos(carpeta, patron)
    return encontrados[0] if encontrados else None


def _carpeta_de_panoramas(carpeta: Path) -> Path:
    """La carpeta que contiene las fotos. Las panorámicas suelen venir separadas
    por posición de vuelo, así que se toma el ancestro común de todas."""
    fotos = [p for p in carpeta.rglob("*")
             if p.suffix.lower() in (".jpg", ".jpeg") and not _es_nuestro(p)]
    if not fotos:
        raise FileNotFoundError(f"no encontré panorámicas (.jpg) dentro de {carpeta}")

    comun = fotos[0].parent
    for foto in fotos[1:]:
        while comun not in foto.parents:
            comun = comun.parent
    return comun


# --- Proyecto ----------------------------------------------------------------

@dataclass(frozen=True)
class Proyecto:
    nombre: str
    etapa: str = ""
    # Teléfono de contacto para el botón de WhatsApp (formato internacional, sin +).
    # Vacío esconde el botón. Mejor eso que un número que no contesta.
    whatsapp: str = ""
    # Nombre del loteo en el CRM. Por defecto, el nombre del proyecto en mayúsculas.
    parcelacion: str | None = None
    # (lon, lat) desde donde despegó el dron. Ancla las alturas al terreno; sin él
    # se asume que despegó bajo la primera toma.
    despegue: tuple[float, float] | None = None
    # Pueblos u otros hitos que se rotulan en el horizonte: nombres a geocodificar
    # ("Cauquenes") o dicts con nombre, lon y lat.
    referencias: tuple = ()

    # El slug se ASIGNA, no se deriva. Es la identidad del loteo: su carpeta de
    # salida, su proyecto en el hosting y su URL. Dos clientes pueden llamar igual
    # a su loteo, así que quien lo emite es la consola (que garantiza unicidad),
    # y una vez emitido no cambia aunque cambie el nombre. Sin slug guardado
    # —el caso de una carpeta suelta en este computador— se sugiere del nombre.
    slug_guardado: str = ""

    @property
    def slug(self) -> str:
        return self.slug_guardado or sugerir_slug(self.nombre)


def sugerir_slug(nombre: str) -> str:
    """Un slug a partir del nombre. Es una sugerencia: la unicidad la da quien lo asigna."""
    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plano.lower()).strip("-") or "proyecto"


def cargar_proyecto(carpeta: Path, **valores) -> Proyecto:
    """Los datos del proyecto: `proyecto.json` en la carpeta, pisado por lo que
    venga por línea de comandos. Sin nada, el nombre es el de la carpeta."""
    carpeta = Path(carpeta)
    datos: dict = {}
    archivo = carpeta / "proyecto.json"
    if archivo.is_file():
        datos = json.loads(archivo.read_text(encoding="utf-8"))
    datos.update({clave: valor for clave, valor in valores.items() if valor is not None})

    nombre = str(datos.get("nombre") or carpeta.name).strip()
    despegue = datos.get("despegue")
    return Proyecto(
        nombre=nombre,
        etapa=str(datos.get("etapa") or ""),
        whatsapp=str(datos.get("whatsapp") or ""),
        parcelacion=str(datos.get("parcelacion") or nombre.upper()),
        despegue=(float(despegue[0]), float(despegue[1])) if despegue else None,
        referencias=tuple(datos.get("referencias") or ()),
        slug_guardado=str(datos.get("slug") or ""),
    )


# --- Salida ------------------------------------------------------------------

@dataclass(frozen=True)
class Salida:
    """Dónde queda todo lo que produce el pipeline para un proyecto."""
    base: Path

    @property
    def web(self) -> Path:
        # El sitio completo, autocontenido: se sube tal cual al hosting.
        return self.base / "sitio"

    @property
    def datos(self) -> Path:
        return self.web / "datos"

    @property
    def vistas(self) -> Path:
        return self.datos / "vistas"

    @property
    def panoramas(self) -> Path:
        return self.web / "panoramas"

    @property
    def qa(self) -> Path:
        # El control de calce es para revisar antes de publicar, no se sube.
        return self.base / "control-calce"


def salida_para(proyecto: Proyecto | None, base: Path | None = None) -> Salida:
    if base is not None:
        return Salida(Path(base))
    if proyecto is None:
        raise ValueError("hace falta el proyecto o una carpeta de salida")
    return Salida(SALIDAS / proyecto.slug)


# --- Niveles de imagen -------------------------------------------------------
# Ancho en píxeles de la panorámica equirectangular servida. El alto es la mitad.
# "previa" carga al instante; "media" es el nivel de trabajo; "alta" se pide solo
# al hacer zoom en pantallas grandes.

NIVELES_IMAGEN = {
    "previa": 2048,
    "media": 4096,
    "alta": 8192,
}
CALIDAD_JPEG = 84

# --- Proyección --------------------------------------------------------------

# Distancia máxima a la que una parcela se incluye en el overlay de una vista.
DISTANCIA_MAXIMA_M = 2000.0

# Una parcela se descarta de la vista si su ancho angular es menor a esto.
# Por debajo de ~0.8° el polígono es demasiado chico para hacerle clic.
ANCHO_ANGULAR_MINIMO_GRADOS = 0.8

# Y también si ocupa muy poco del campo visual. Una parcela lejana puede ser ancha
# y aun así ser una astilla: la profundidad se aplasta contra el horizonte.
# 0.6 grados² es aproximadamente un parche de 0.8° × 0.8°.
AREA_ANGULAR_MINIMA_GRADOS2 = 0.6

# Elevación mínima por debajo del horizonte. Las parcelas casi al ras del
# horizonte son ruido: están tan lejos que se ven como una línea.
DEPRESION_MINIMA_GRADOS = 1.5

# Largo máximo de un segmento del overlay, en grados. Las aristas se subdividen
# hasta cumplirlo para que las rectas del suelo se curven correctamente.
SEGMENTO_MAXIMO_GRADOS = 1.5

# Decimales con que se guardan azimut y elevación. 0.01° ≈ 0.4 px a 14400 de ancho.
DECIMALES_ANGULO = 2
DECIMALES_COORD = 7

# --- Estados -----------------------------------------------------------------

# El estado lo lleva la pastilla del número, no el contorno de la parcela. Como la
# pastilla es un disco sólido, el color se lee igual de bien sobre bosque que sobre
# tierra o cielo, y el contorno queda blanco y limpio para todas.
# Los tonos son los de las pills de estado de Cierra: verde disponible, ámbar en
# proceso, azul inscrita, oscuro no disponible. Un disco sólido de ese color se
# lee igual sobre bosque, tierra o cielo.
ESTADOS = {
    "disponible": {"etiqueta": "Disponible", "color": "#007c10", "vendible": True},
    "reservado": {"etiqueta": "Reservado", "color": "#f59e0b", "vendible": False},
    "vendido": {"etiqueta": "Vendido", "color": "#2563eb", "vendible": False},
    "no_disponible": {"etiqueta": "No disponible", "color": "#18181b", "vendible": False},
    "no_en_venta": {"etiqueta": "No en venta", "color": "#71717a", "vendible": False},
}
ESTADO_POR_DEFECTO = "no_disponible"
