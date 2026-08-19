"""Rutas y parámetros del pipeline.

Todo lo configurable vive aquí. Si mueves las fuentes de lugar, este es el único
archivo que hay que tocar.
"""
from dataclasses import dataclass
from pathlib import Path

# --- Rutas -------------------------------------------------------------------

RAIZ = Path(__file__).resolve().parent.parent

# Por defecto las fuentes se buscan en la carpeta que contiene a masterplan360.
# Para otro proyecto: python -m pipeline.construir --proyecto "ruta/a/la/carpeta"
PROYECTO = RAIZ.parent


@dataclass(frozen=True)
class Fuentes:
    kmz: Path
    excel: Path
    panoramas: Path


def descubrir_fuentes(carpeta: Path) -> Fuentes:
    """Encuentra el KMZ, la planilla y las panorámicas dentro de una carpeta.

    Se descubren por tipo y no por nombre: cada proyecto llega con los archivos
    llamados como los haya dejado el topógrafo o el piloto, y no tiene sentido
    editar código para eso.
    """
    carpeta = Path(carpeta)
    if not carpeta.is_dir():
        raise FileNotFoundError(f"no existe la carpeta del proyecto: {carpeta}")

    return Fuentes(
        kmz=_unico(carpeta, "*.kmz", "el KMZ del loteo"),
        excel=_unico(carpeta, "*.xlsx", "la planilla de parcelas"),
        panoramas=_carpeta_de_panoramas(carpeta),
    )


def _es_nuestro(ruta: Path) -> bool:
    """¿La ruta está dentro de masterplan360? Ahí vive lo que genera el propio
    pipeline, y si no se excluye se confunde con las fuentes."""
    return RAIZ == ruta or RAIZ in ruta.parents


def _unico(carpeta: Path, patron: str, que: str) -> Path:
    # Se ignoran los temporales que Excel deja abiertos (~$archivo.xlsx).
    encontrados = sorted(p for p in carpeta.rglob(patron)
                         if not p.name.startswith("~$") and not _es_nuestro(p))
    if not encontrados:
        raise FileNotFoundError(f"no encontré {que} ({patron}) dentro de {carpeta}")
    return encontrados[0]


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

# El pipeline escribe dentro de web/ a propósito: así esa carpeta queda
# autocontenida y se sube al hosting tal cual, sin pasos intermedios.
SALIDA_WEB = RAIZ / "web"
SALIDA_DATOS = SALIDA_WEB / "datos"
SALIDA_VISTAS = SALIDA_DATOS / "vistas"
SALIDA_PANORAMAS = SALIDA_WEB / "panoramas"

# El control de calce es para revisar antes de publicar, no se sube.
SALIDA_QA = RAIZ / "control-calce"

# --- Proyecto ----------------------------------------------------------------

NOMBRE_PROYECTO = "Hacienda Vichuquén"
NOMBRE_ETAPA = "Etapa 1"

# Teléfono de contacto para el botón de WhatsApp (formato internacional, sin +).
WHATSAPP = "56912345678"

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
ESTADOS = {
    "disponible": {"etiqueta": "Disponible", "color": "#ffffff", "vendible": True},
    "reservado": {"etiqueta": "Reservado", "color": "#f2d024", "vendible": False},
    "vendido": {"etiqueta": "Vendido", "color": "#c2352b", "vendible": False},
    "no_disponible": {"etiqueta": "No disponible", "color": "#8d8d8d", "vendible": False},
    "no_en_venta": {"etiqueta": "No en venta", "color": "#5f5a52", "vendible": False},
}
ESTADO_POR_DEFECTO = "no_disponible"
