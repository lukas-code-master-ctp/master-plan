"""Solicitudes de reserva desde el sitio publicado.

El botón "Reservar parcela" del visor lleva a un link de pago (Getnet, Webpay…) que
no le avisa al Masterplan. Antes de ir ahí, el comprador deja sus datos: la
consola guarda la solicitud, aparta la parcela por un rato —para que otro no pague
la misma— y le escribe a la loteadora. Ella la confirma cuando ve el pago, o la
libera. El inventario (Cierra o la planilla) sigue mandando: el apartado es solo
una capa encima, que el visor pinta como "Reserva en proceso".

El porqué y las decisiones: docs/specs/2026-10-06-solicitudes-de-reserva.md.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, insert, select, update

from .cuentas import Correo, limpiar_texto
from .datos import Base, NoEncontrado, solicitudes_reserva
from .proyectos import Proyecto

registro = logging.getLogger("consola.reservas")

# Lo que dura apartada una parcela sin confirmar. Lo eligió el usuario (2026-10-06):
# alcanza para pagar con calma y no deja una parcela bloqueada todo el día.
APARTADO = timedelta(hours=2)

# Cuántas solicitudes sin confirmar puede tener un loteo a la vez. Sin tope,
# alguien con datos inventados podría dejar el loteo entero como "Reserva en
# proceso" y que nadie pudiera comprar.
TOPE_PENDIENTES_POR_LOTEO = 10

PENDIENTE, CONFIRMADA, LIBERADA, VENCIDA = "pendiente", "confirmada", "liberada", "vencida"

# Estricto a propósito: el correo se le muestra a la loteadora, y una regex
# permisiva dejaba pasar comillas, etiquetas o una URL disfrazada de correo.
CORREO = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


class SolicitudInvalida(ValueError):
    """Los datos del comprador no sirven. El mensaje se le puede mostrar."""


class NoSePuedeApartar(Exception):
    """La parcela no está en venta o ya la apartó otra persona. El mensaje se le puede mostrar."""


@dataclass(frozen=True)
class Comprador:
    nombre: str
    telefono: str
    email: str


@dataclass(frozen=True)
class Solicitud:
    id: int
    parcela: str
    nombre: str
    telefono: str
    email: str
    estado: str
    creada_en: datetime
    vence_en: datetime

    def estado_a_las(self, ahora: datetime) -> str:
        return VENCIDA if self.estado == PENDIENTE and self.vence_en <= ahora else self.estado

    def como_json(self, ahora: datetime) -> dict:
        return {"id": self.id, "parcela": self.parcela, "nombre": self.nombre,
                "telefono": self.telefono, "email": self.email, "estado": self.estado_a_las(ahora),
                "creada_en": self.creada_en.isoformat(), "vence_en": self.vence_en.isoformat()}


def leer_comprador(datos: dict) -> Comprador:
    """Lo que escribió el comprador, revisado. Los textos quedan en una línea:
    van a un correo, y un salto de línea serviría para colar un párrafo inventado."""
    nombre = limpiar_texto(str(datos.get("nombre") or ""), 120)
    if len(nombre) < 2:
        raise SolicitudInvalida("Escribe tu nombre.")
    telefono = re.sub(r"\D", "", str(datos.get("telefono") or ""))
    if len(telefono) == 9 and telefono.startswith("9"):
        telefono = "56" + telefono   # un celular chileno escrito sin el 56
    if not 8 <= len(telefono) <= 15:
        raise SolicitudInvalida("Escribe un teléfono donde podamos llamarte.")
    email = limpiar_texto(str(datos.get("email") or ""), 160)
    if not CORREO.fullmatch(email):
        raise SolicitudInvalida("Escribe un correo válido.")
    return Comprador(nombre=nombre, telefono=telefono, email=email)


def link_con_parcela(link: str, parcela: str) -> str | None:
    """El link de reserva del loteo con `parcela=<id>`, sumado a lo que ya traía."""
    if not link:
        return None
    partes = urlsplit(link)
    consulta = [(c, v) for c, v in parse_qsl(partes.query, keep_blank_values=True) if c != "parcela"]
    return urlunsplit(partes._replace(query=urlencode([*consulta, ("parcela", parcela)])))


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _hora_de_chile(momento: datetime) -> str:
    try:
        return momento.astimezone(ZoneInfo("America/Santiago")).strftime("%H:%M")
    except ZoneInfoNotFoundError:
        return momento.strftime("%H:%M (UTC)")


def _utc(momento: datetime) -> datetime:
    """SQLite devuelve las fechas sin zona, aunque se guardaron en UTC."""
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


class Reservas:
    def __init__(self, base: Base, correo: Correo, *, ahora=_ahora, en_segundo_plano: bool = True):
        self.base = base
        self.correo = correo
        self.ahora = ahora
        self.en_segundo_plano = en_segundo_plano
        # Revisar que la parcela esté libre y apartarla tiene que ser un solo paso:
        # si no, dos pedidos simultáneos la apartan los dos. Basta un candado porque
        # la consola corre en una sola instancia (`--max-instances=1`).
        self._candado = threading.Lock()

    # --- lo que pide el sitio publicado ---------------------------------------------

    def apartadas(self, proyecto: Proyecto) -> dict[str, datetime | None]:
        """Las parcelas apartadas ahora: id → hasta cuándo (None si está confirmada)."""
        return {s.parcela: (None if s.estado == CONFIRMADA else s.vence_en)
                for s in self._activas(proyecto, self.ahora())}

    def _activas(self, proyecto: Proyecto, ahora: datetime) -> list[Solicitud]:
        """Las confirmadas y las pendientes que no han vencido."""
        with self.base.motor.connect() as con:
            filas = con.execute(select(solicitudes_reserva).where(and_(
                solicitudes_reserva.c.proyecto_id == self._id(proyecto),
                solicitudes_reserva.c.estado.in_((PENDIENTE, CONFIRMADA)))))
            solicitudes = [_solicitud(f) for f in filas]
        # El plazo se compara acá y no en la consulta: SQLite guarda las fechas sin
        # zona y la comparación en SQL dependería de cómo quedaron escritas.
        return [s for s in solicitudes if s.estado_a_las(ahora) != VENCIDA]

    def solicitar(self, proyecto: Proyecto, parcela: str, comprador: Comprador,
                  url_consola: str = "") -> Solicitud:
        """Aparta la parcela y avisa a la loteadora. NoEncontrado si la parcela no
        existe en el sitio; NoSePuedeApartar si no está en venta o ya está apartada."""
        estado = _estado_en_el_sitio(proyecto, parcela)
        if estado != "disponible":
            raise NoSePuedeApartar("Esta parcela ya no está disponible.")
        ahora = self.ahora()
        with self._candado:
            activas = self._activas(proyecto, ahora)
            if any(s.parcela == parcela for s in activas):
                raise NoSePuedeApartar("Esta parcela está apartada por otra persona mientras paga. "
                                       "Prueba en un rato o elige otra.")
            pendientes = [s for s in activas if s.estado == PENDIENTE]
            if any(s.email == comprador.email or s.telefono == comprador.telefono for s in pendientes):
                raise NoSePuedeApartar("Ya tienes una parcela apartada en este loteo. Termina ese "
                                       "pago o escríbenos por WhatsApp para cambiarla.")
            if len(pendientes) >= TOPE_PENDIENTES_POR_LOTEO:
                raise NoSePuedeApartar("Hay muchas reservas en proceso en este loteo. Escríbenos "
                                       "por WhatsApp y te ayudamos.")
            with self.base.motor.begin() as con:
                nueva = con.execute(insert(solicitudes_reserva).values(
                    proyecto_id=self._id(proyecto), parcela=parcela, nombre=comprador.nombre,
                    telefono=comprador.telefono, email=comprador.email, estado=PENDIENTE,
                    creada_en=ahora, vence_en=ahora + APARTADO))
                identificador = nueva.inserted_primary_key[0]
        solicitud = Solicitud(id=identificador, parcela=parcela, nombre=comprador.nombre,
                              telefono=comprador.telefono, email=comprador.email, estado=PENDIENTE,
                              creada_en=ahora, vence_en=ahora + APARTADO)
        self._avisar(proyecto, solicitud, url_consola)
        return solicitud

    # --- lo que hace la loteadora en la consola ---------------------------------------

    def del_loteo(self, proyecto: Proyecto) -> list[Solicitud]:
        with self.base.motor.connect() as con:
            return [_solicitud(f) for f in con.execute(
                select(solicitudes_reserva)
                .where(solicitudes_reserva.c.proyecto_id == self._id(proyecto))
                .order_by(solicitudes_reserva.c.creada_en.desc()).limit(200))]

    def resolver(self, proyecto: Proyecto, identificador: int, estado: str) -> Solicitud:
        """Confirmar (se pagó) o liberar (no se pagó). Una de otro loteo: NoEncontrado."""
        if estado not in (CONFIRMADA, LIBERADA):
            raise ValueError(estado)
        condicion = and_(solicitudes_reserva.c.id == identificador,
                         solicitudes_reserva.c.proyecto_id == self._id(proyecto))
        with self._candado:
            with self.base.motor.connect() as con:
                fila = con.execute(select(solicitudes_reserva).where(condicion)).first()
            if fila is None:
                raise NoEncontrado(f"no existe la solicitud {identificador}")
            actual = _solicitud(fila)
            # Confirmar una que venció o se liberó vuelve a apartar la parcela: solo
            # si mientras tanto no la apartó otra persona.
            if estado == CONFIRMADA and actual.estado_a_las(self.ahora()) != PENDIENTE:
                otra = [s for s in self._activas(proyecto, self.ahora())
                        if s.parcela == actual.parcela and s.id != actual.id]
                if otra:
                    raise NoSePuedeApartar("Otra persona apartó esta parcela después. "
                                           "Libera esa solicitud primero.")
            with self.base.motor.begin() as con:
                con.execute(update(solicitudes_reserva).where(condicion)
                            .values(estado=estado, resuelta_en=self.ahora()))
                return _solicitud(con.execute(select(solicitudes_reserva).where(condicion)).one())

    # --- interno ----------------------------------------------------------------------

    def _id(self, proyecto: Proyecto) -> int:
        return self.base.proyecto(proyecto.slug).id

    def _avisar(self, proyecto: Proyecto, solicitud: Solicitud, url_consola: str) -> None:
        """Un correo a cada cuenta activa y confirmada de la loteadora. Que el correo
        falle no puede tumbar la solicitud: queda en la consola igual."""
        destinos = [u.email for u in self.base.usuarios_de(proyecto.cliente_id)
                    if u.activo and u.email_verificado]
        asunto = f"Solicitud de reserva: Parcela {solicitud.parcela} · {proyecto.nombre}"
        texto = "\n".join([
            f"Alguien quiere reservar la parcela {solicitud.parcela} de {proyecto.nombre}"
            " desde el Masterplan.",
            "",
            f"Nombre: {solicitud.nombre}",
            f"Teléfono: {solicitud.telefono}",
            f"Correo: {solicitud.email}",
            "(Datos escritos por el comprador en el sitio, sin verificar.)",
            "",
            f"La parcela queda apartada hasta las {_hora_de_chile(solicitud.vence_en)}"
            f" ({int(APARTADO.total_seconds() // 3600)} horas) mientras paga. Si no confirmas el pago,"
            " vuelve sola a disponible.",
            "",
            f"Confírmala o libérala en la consola: {url_consola.rstrip('/')}/#/reservas"
            if url_consola else "Confírmala o libérala en la sección Reservas de la consola.",
        ])
        for destino in destinos:
            if self.en_segundo_plano:
                threading.Thread(target=self._mandar, args=(destino, asunto, texto), daemon=True).start()
            else:
                self._mandar(destino, asunto, texto)

    def _mandar(self, para: str, asunto: str, texto: str) -> None:
        try:
            self.correo.enviar(para, asunto, texto)
        except Exception:   # noqa: BLE001 — un correo caído no se lleva la solicitud
            registro.exception("no pude avisar la solicitud de reserva a %s", para)


def _estado_en_el_sitio(proyecto: Proyecto, parcela: str) -> str:
    """El estado de la parcela en el sitio publicado (su parcelas.json)."""
    archivo = proyecto.salida.datos / "parcelas.json"
    try:
        parcelas = json.loads(archivo.read_text(encoding="utf-8")).get("parcelas", [])
    except (OSError, ValueError) as error:
        raise NoEncontrado(f"el loteo {proyecto.slug} no tiene sitio") from error
    for candidata in parcelas:
        if str(candidata.get("id")) == parcela:
            return str(candidata.get("estado"))
    raise NoEncontrado(f"no existe la parcela {parcela}")


def _solicitud(fila) -> Solicitud:
    return Solicitud(id=fila.id, parcela=fila.parcela, nombre=fila.nombre, telefono=fila.telefono,
                     email=fila.email, estado=fila.estado, creada_en=_utc(fila.creada_en),
                     vence_en=_utc(fila.vence_en))
