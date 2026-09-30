"""El inventario de un loteo, leído de Cierra.

Cierra es el CRM donde la loteadora ya lleva sus parcelas: si el estado y el precio
viven ahí, pedirle que además llene una planilla es pedirle que los lleve dos veces,
y la segunda siempre queda atrasada. La loteadora crea en Cierra una clave de API
con permiso `parcelas:read` (Admin → Integraciones), la pega acá una vez, y en cada
loteo elige qué proyectos de Cierra lo alimentan: en Cierra cada etapa es un
proyecto aparte.

Lo que llega se escribe como `inventario.csv` en la carpeta del loteo, con las
mismas columnas que la plantilla. Así el pipeline no sabe que Cierra existe, y lo
último que se trajo queda como respaldo si un día Cierra no contesta.

La clave se guarda cifrada con una llave derivada de `CONSOLA_SECRETO`: la base
sola no alcanza para leerla. Cambiar ese secreto obliga a pegar las claves de nuevo.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import delete, insert, select, update

from pipeline import config

from .datos import Base, cierra_claves, cierra_loteos, proyectos

registro = logging.getLogger("consola.cierra")

# Lo que responde Cierra → lo que entiende la planilla (pipeline/excel.py).
ETIQUETAS = {"disponible": "Disponible", "reservado": "Reservado",
             "vendido": "Vendido", "no_disponible": "No disponible"}
COLUMNAS = ("Parcela", "Parcelación", "Estado", "Precio", "Moneda",
            "Superficie m2", "Servidumbre m2")
# Una etapa más allá de esto no es una etapa: es un número mal escrito.
MAX_ETAPA = 50
# Con menos, la pista (los últimos 4) sería casi la clave entera.
LARGO_MINIMO_CLAVE = 16
LARGO_MAXIMO_CLAVE = 300
# Un loteo tiene cientos de parcelas, no millones: más que esto no es un inventario.
BYTES_MAXIMOS_RESPUESTA = 5_000_000
# Dos sincronizaciones del mismo loteo a la vez se pisarían el archivo.
_ESCRIBIENDO = threading.Lock()


class CierraNoResponde(Exception):
    """Cierra no contestó, o contestó algo que no se entiende."""


class ClaveRechazada(Exception):
    """Cierra no aceptó la clave: no existe, está revocada o le falta el permiso."""


class EleccionInvalida(ValueError):
    """Los proyectos elegidos no calzan con los que ve la clave."""


@dataclass(frozen=True)
class ProyectoCierra:
    id: int
    nombre: str
    parcelas_total: int
    parcelas_disponibles: int


@dataclass(frozen=True)
class Eleccion:
    """Un proyecto de Cierra conectado a un loteo, y la etapa del KMZ que es."""
    id: int
    nombre: str
    etapa: int


@dataclass(frozen=True)
class ConexionDelLoteo:
    elecciones: tuple[Eleccion, ...]
    sincronizado_en: datetime | None


# --- la API de Cierra ---------------------------------------------------------------

class Cierra:
    """Lo que Tu Masterplan le pide a Cierra: solo leer, con la clave de la loteadora."""

    def __init__(self, url: str, http=None):
        self.url = url.rstrip("/")
        self.http = http or _http

    def proyectos(self, clave: str) -> list[ProyectoCierra]:
        datos = self.http(f"{self.url}/integrations/proyectos", clave)
        try:
            return [ProyectoCierra(id=int(p["id"]), nombre=str(p["nombre"])[:160],
                                   parcelas_total=int(p.get("parcelas_total") or 0),
                                   parcelas_disponibles=int(p.get("parcelas_disponibles") or 0))
                    for p in datos["proyectos"]]
        except (AttributeError, KeyError, TypeError, ValueError, OverflowError) as error:
            raise CierraNoResponde("Cierra contestó algo inesperado.") from error

    def parcelas(self, clave: str, ids: list[int]) -> list[dict]:
        consulta = urllib.parse.urlencode({"proyecto_id": ",".join(str(i) for i in ids)})
        datos = self.http(f"{self.url}/integrations/parcelas?{consulta}", clave)
        parcelas = datos.get("parcelas") if isinstance(datos, dict) else None
        if not isinstance(parcelas, list) or not all(isinstance(p, dict) for p in parcelas):
            raise CierraNoResponde("Cierra no entregó las parcelas.")
        return parcelas


def cierra_del_entorno() -> Cierra | None:
    """Sin `CIERRA_API_URL` la conexión no se ofrece: no hay a quién pedirle.

    Solo https, salvo en este computador: la clave viaja en cada petición.
    """
    url = os.environ.get("CIERRA_API_URL", "").strip()
    if not url:
        return None
    partes = urllib.parse.urlparse(url)
    if partes.scheme != "https" and partes.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("CIERRA_API_URL tiene que ser https")
    return Cierra(url)


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    """Seguir una redirección reenviaría la clave a otro servidor."""

    def redirect_request(self, *argumentos, **nombrados):
        return None


_ABRIR = urllib.request.build_opener(_SinRedirecciones()).open


def _http(url: str, clave: str) -> dict:
    peticion = urllib.request.Request(url, headers={"Accept": "application/json",
                                                    "X-API-Key": clave})
    try:
        with _ABRIR(peticion, timeout=20) as respuesta:
            if respuesta.status != 200:
                raise CierraNoResponde(f"Cierra contestó con un error ({respuesta.status}).")
            cuerpo = respuesta.read(BYTES_MAXIMOS_RESPUESTA + 1)
            if len(cuerpo) > BYTES_MAXIMOS_RESPUESTA:
                raise CierraNoResponde("Cierra entregó más datos de los que cabe esperar.")
            return json.loads(cuerpo)
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise ClaveRechazada("Cierra no aceptó la clave.") from error
        if error.code == 404:
            raise CierraNoResponde("Cierra no encontró alguno de los proyectos elegidos.") from error
        registro.warning("Cierra contestó %s en %s", error.code, url.split("?")[0])
        raise CierraNoResponde(f"Cierra contestó con un error ({error.code}).") from error
    except (OSError, ValueError) as error:
        registro.warning("Cierra no contestó: %s", error)
        raise CierraNoResponde("Cierra no contestó. Vuelve a intentarlo en un rato.") from error


# --- la clave, cifrada ----------------------------------------------------------------

class Cifrador:
    def __init__(self, secreto: str | bytes):
        crudo = secreto.encode() if isinstance(secreto, str) else secreto
        if not crudo:
            raise ValueError("sin secreto no se puede cifrar la clave de Cierra")
        # Separada de la firma de las galletas: la misma llave para dos cosas
        # haría que un error en una comprometiera la otra.
        llave = hashlib.sha256(b"tumasterplan|cierra-claves|" + crudo).digest()
        self.fernet = Fernet(base64.urlsafe_b64encode(llave))

    def cifrar(self, cliente_id: int, texto: str) -> str:
        # El dueño va adentro: copiar la fila cifrada a otra loteadora no le sirve.
        return self.fernet.encrypt(f"{cliente_id}:{texto}".encode()).decode()

    def descifrar(self, cliente_id: int, cifrado: str) -> str | None:
        """None si no se puede leer (cambió `CONSOLA_SECRETO`) o no es de esta loteadora."""
        try:
            dueno, _, texto = self.fernet.decrypt(cifrado.encode()).decode().partition(":")
        except InvalidToken:
            return None
        return texto if dueno == str(cliente_id) and texto else None


def limpiar_clave(clave) -> str:
    texto = str(clave or "").strip()
    if (not LARGO_MINIMO_CLAVE <= len(texto) <= LARGO_MAXIMO_CLAVE
            or any(c.isspace() for c in texto)):
        raise ValueError("Pega la clave de API tal como la muestra Cierra.")
    return texto


# --- lo guardado ------------------------------------------------------------------------

class Conexiones:
    """Las claves de cada loteadora y qué proyectos de Cierra alimentan cada loteo."""

    def __init__(self, base: Base, cifrador: Cifrador):
        self.base = base
        self.cifrador = cifrador

    def guardar_clave(self, cliente_id: int, clave: str) -> str:
        """Una clave distinta puede ser de otra cuenta de Cierra, donde los mismos ids
        son otros proyectos: los loteos conectados con la anterior se desconectan."""
        if self.clave(cliente_id) not in (None, clave):
            self._desconectar_todos(cliente_id)
        pista = clave[-4:]
        valores = {"cifrada": self.cifrador.cifrar(cliente_id, clave), "pista": pista,
                   "creado_en": datetime.now(timezone.utc)}
        with self.base.motor.begin() as con:
            cambio = con.execute(update(cierra_claves)
                                 .where(cierra_claves.c.cliente_id == cliente_id).values(**valores))
            if cambio.rowcount == 0:
                con.execute(insert(cierra_claves).values(cliente_id=cliente_id, **valores))
        return pista

    def clave(self, cliente_id: int) -> str | None:
        fila = self._fila_clave(cliente_id)
        return self.cifrador.descifrar(cliente_id, fila.cifrada) if fila else None

    def pista(self, cliente_id: int) -> str | None:
        fila = self._fila_clave(cliente_id)
        return fila.pista if fila else None

    def olvidar_clave(self, cliente_id: int) -> None:
        """Sin clave no hay qué leer: los loteos de esa loteadora se desconectan."""
        self._desconectar_todos(cliente_id)
        with self.base.motor.begin() as con:
            con.execute(delete(cierra_claves).where(cierra_claves.c.cliente_id == cliente_id))

    def _desconectar_todos(self, cliente_id: int) -> None:
        suyos = select(proyectos.c.id).where(proyectos.c.cliente_id == cliente_id).scalar_subquery()
        with self.base.motor.begin() as con:
            con.execute(delete(cierra_loteos).where(cierra_loteos.c.proyecto_id.in_(suyos)))

    def del_loteo(self, slug: str) -> ConexionDelLoteo | None:
        with self.base.motor.connect() as con:
            fila = con.execute(select(cierra_loteos).where(
                cierra_loteos.c.proyecto_id == self._id(con, slug))).first()
        if fila is None:
            return None
        elecciones = tuple(Eleccion(**e) for e in json.loads(fila.proyectos))
        momento = fila.sincronizado_en
        if momento is not None and momento.tzinfo is None:
            momento = momento.replace(tzinfo=timezone.utc)
        return ConexionDelLoteo(elecciones=elecciones, sincronizado_en=momento)

    def conectar_loteo(self, slug: str, elecciones: list[Eleccion]) -> None:
        texto = json.dumps([e.__dict__ for e in elecciones], ensure_ascii=False)
        with self.base.motor.begin() as con:
            proyecto_id = self._id(con, slug)
            con.execute(delete(cierra_loteos).where(cierra_loteos.c.proyecto_id == proyecto_id))
            con.execute(insert(cierra_loteos).values(
                proyecto_id=proyecto_id, proyectos=texto, sincronizado_en=None,
                creado_en=datetime.now(timezone.utc)))

    def desconectar_loteo(self, slug: str) -> None:
        with self.base.motor.begin() as con:
            con.execute(delete(cierra_loteos).where(
                cierra_loteos.c.proyecto_id == self._id(con, slug)))

    def anotar_sincronizacion(self, slug: str) -> datetime:
        momento = datetime.now(timezone.utc)
        with self.base.motor.begin() as con:
            con.execute(update(cierra_loteos).where(cierra_loteos.c.proyecto_id == self._id(con, slug))
                        .values(sincronizado_en=momento))
        return momento

    def _fila_clave(self, cliente_id: int):
        with self.base.motor.connect() as con:
            return con.execute(select(cierra_claves)
                               .where(cierra_claves.c.cliente_id == cliente_id)).first()

    @staticmethod
    def _id(con, slug: str) -> int:
        return con.execute(select(proyectos.c.id).where(proyectos.c.slug == slug)).scalar_one()


# --- de Cierra al inventario ------------------------------------------------------------

def etapa_sugerida(nombre: str) -> int:
    """"PRADERAS DE CAUQUENES ET2" es la etapa 2; sin sufijo, la 1."""
    encontrado = re.search(r"\b(?:ET|ETAPA)\s*0*(\d+)\b", nombre.upper())
    return int(encontrado.group(1)) if encontrado else 1


def revisar_eleccion(pedidas: list, disponibles: list[ProyectoCierra]) -> list[Eleccion]:
    """Lo que eligió la persona, contra lo que la clave de verdad ve en Cierra.

    Los nombres salen de Cierra, no del navegador. Dos proyectos no pueden ser la
    misma etapa: sus parcelas 7 chocarían en el mismo lote del dibujo.
    """
    por_id = {p.id: p for p in disponibles}
    elecciones: list[Eleccion] = []
    try:
        for pedida in pedidas:
            proyecto = por_id[int(pedida["id"])]
            pedida_etapa = pedida.get("etapa")
            etapa = etapa_sugerida(proyecto.nombre) if pedida_etapa in (None, "") else int(pedida_etapa)
            if not 1 <= etapa <= MAX_ETAPA:
                raise EleccionInvalida(f"La etapa de {proyecto.nombre} tiene que ser un número de 1 a {MAX_ETAPA}.")
            elecciones.append(Eleccion(id=proyecto.id, nombre=proyecto.nombre, etapa=etapa))
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, EleccionInvalida):
            raise
        raise EleccionInvalida("Elige proyectos de la lista de Cierra.") from error
    if not elecciones:
        raise EleccionInvalida("Elige al menos un proyecto de Cierra.")
    if len({e.id for e in elecciones}) != len(elecciones):
        raise EleccionInvalida("Elegiste el mismo proyecto dos veces.")
    if len({e.etapa for e in elecciones}) != len(elecciones):
        raise EleccionInvalida("Dos proyectos no pueden ser la misma etapa.")
    return elecciones


def inventario_csv(parcelas: list[dict], elecciones: tuple[Eleccion, ...] | list[Eleccion]) -> str:
    """Las parcelas de Cierra como la planilla que lee el pipeline.

    La etapa va como sufijo de la parcelación ("CIERRA ET2"), que es como
    `pipeline/excel.py` separa las etapas: con una sola etapa no lleva sufijo y la
    parcela queda con su número tal cual, como en un loteo sin etapas.
    """
    etapa_de = {e.id: e.etapa for e in elecciones}
    varias = len(set(etapa_de.values())) > 1
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(COLUMNAS)
    for parcela in parcelas:
        if not isinstance(parcela, dict):
            continue
        etapa = etapa_de.get(_entero(parcela.get("proyecto_id")))
        numero = str(parcela.get("numero") or "").strip()[:40]
        if etapa is None or not numero:
            continue   # de un proyecto que no se pidió, o sin número: no calza con nada
        escritor.writerow((
            numero,
            f"CIERRA ET{etapa}" if varias else "CIERRA",
            ETIQUETAS.get(str(parcela.get("estado")), ETIQUETAS["no_disponible"]),
            _texto_numero(parcela.get("precio")),
            str(parcela.get("moneda") or "CLP").strip()[:8],
            _texto_numero(parcela.get("superficie_m2")),
            _texto_numero(parcela.get("servidumbre_m2")),
        ))
    return salida.getvalue()


def sincronizar(cierra: Cierra, clave: str, conexion: ConexionDelLoteo, carpeta: Path) -> int:
    """Trae las parcelas y deja el inventario en la carpeta. Devuelve cuántas llegaron.

    Si Cierra falla, lo que había queda intacto: se escribe a un temporal y recién
    al final se reemplaza.
    """
    parcelas = cierra.parcelas(clave, [e.id for e in conexion.elecciones])
    texto = inventario_csv(parcelas, conexion.elecciones)
    cuantas = texto.count("\n") - 1
    # Cero parcelas no es un inventario: es una clave sin permiso o un Cierra con
    # problemas. Escribirlo dejaría todo el sitio "no disponible" al publicar.
    if cuantas <= 0:
        raise CierraNoResponde("Cierra no entregó parcelas de los proyectos elegidos; "
                               "se mantiene el inventario anterior.")
    carpeta.mkdir(parents=True, exist_ok=True)
    with _ESCRIBIENDO:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=carpeta, prefix=".cierra-",
                                         suffix=".tmp", delete=False) as temporal:
            temporal.write(texto)
        Path(temporal.name).replace(carpeta / "inventario.csv")
        # Un inventario.xlsx subido a mano le ganaría al que llegó de Cierra.
        for otro in config.INVENTARIOS:
            if otro != "inventario.csv":
                (carpeta / otro).unlink(missing_ok=True)
    return cuantas


def _entero(valor) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _texto_numero(valor) -> str:
    """Sin separador de miles y con coma decimal.

    Con punto, el lector de la planilla toma "5002.125" por 5.002.125 (puntos que
    agrupan de a tres son miles); con coma no hay dos lecturas posibles.
    """
    if valor is None or valor == "":
        return ""
    try:
        numero = float(valor)
    except (TypeError, ValueError, OverflowError):
        return ""
    if not math.isfinite(numero):
        return ""
    return str(int(numero)) if numero.is_integer() else repr(numero).replace(".", ",")


__all__ = ["Cierra", "CierraNoResponde", "Cifrador", "ClaveRechazada", "ConexionDelLoteo",
           "Conexiones", "Eleccion", "EleccionInvalida", "ProyectoCierra", "cierra_del_entorno",
           "etapa_sugerida", "inventario_csv", "limpiar_clave", "revisar_eleccion", "sincronizar"]
