"""Los mensajes del formulario de contacto de la landing (tumasterplan.cl).

Alguien que quiere su masterplan escribe en la landing; la consola guarda el
mensaje y le avisa al equipo de CTP, que lo ve en la pestaña Contactos y lo marca
atendido. No es de ninguna loteadora: todavía no hay loteadora, es quien quiere ser
una. Las rutas están en `consola/rutas_contactos.py`.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import insert, select, update

from .cuentas import Correo, limpiar_texto
from .datos import Base, NoEncontrado, contactos
from .reservas import CORREO

registro = logging.getLogger("consola.contactos")

PLANES = ("fly", "pro", "master", "enterprise", "no-se")
NOMBRE_DEL_PLAN = {"fly": "Fly", "pro": "Pro", "master": "Master", "enterprise": "Enterprise",
                   "no-se": "Aún no sabe"}
NUEVO, ATENDIDO = "nuevo", "atendido"
ESTADOS = (NUEVO, ATENDIDO)

MENSAJE_MAXIMO = 2000
PARCELAS_MAXIMO = 100_000
# Lo que se muestra en la consola. Más que eso ya no se mira; queda en la base.
A_LA_VISTA = 300

# Todo lo de control menos el salto de línea: el mensaje conserva sus párrafos,
# pero no una secuencia de escape o un byte nulo que alguien pegó.
CONTROL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")


class ContactoInvalido(ValueError):
    """Lo escrito no sirve. El mensaje se le puede mostrar a quien lo escribió."""


@dataclass(frozen=True)
class Contacto:
    id: int
    nombre: str
    email: str
    telefono: str
    loteadora: str
    plan: str
    vuelo: bool
    parcelas: int | None
    mensaje: str
    estado: str
    creado_en: datetime
    atendido_en: datetime | None

    def como_json(self) -> dict:
        return {"id": self.id, "nombre": self.nombre, "email": self.email, "telefono": self.telefono,
                "loteadora": self.loteadora, "plan": self.plan, "vuelo": self.vuelo,
                "parcelas": self.parcelas, "mensaje": self.mensaje, "estado": self.estado,
                "creado_en": self.creado_en.isoformat(),
                "atendido_en": self.atendido_en.isoformat() if self.atendido_en else None}


def leer_contacto(campos: dict) -> dict:
    """Lo que llegó del formulario, revisado. Solo el nombre y el correo son obligatorios.

    Los textos cortos quedan en una línea: van al asunto y al cuerpo de un correo, y
    un salto serviría para colar un renglón inventado. El mensaje sí guarda sus
    párrafos, que para eso es largo.
    """
    nombre = limpiar_texto(str(campos.get("nombre") or ""), 120)
    if len(nombre) < 2:
        raise ContactoInvalido("Escribe tu nombre.")
    email = limpiar_texto(str(campos.get("email") or ""), 160)
    if not CORREO.fullmatch(email):
        raise ContactoInvalido("Escribe un correo válido.")
    telefono = re.sub(r"\D", "", str(campos.get("telefono") or ""))
    if len(telefono) == 9 and telefono.startswith("9"):
        telefono = "56" + telefono   # un celular chileno escrito sin el 56
    if telefono and not 8 <= len(telefono) <= 15:
        raise ContactoInvalido("Revisa el teléfono.")
    plan = str(campos.get("plan") or "")
    return {
        "nombre": nombre,
        "email": email,
        "telefono": telefono,
        "loteadora": limpiar_texto(str(campos.get("loteadora") or ""), 120),
        "plan": plan if plan in PLANES else "no-se",
        "vuelo": str(campos.get("vuelo") or "") in ("si", "on", "1"),
        "parcelas": _parcelas(campos.get("parcelas")),
        "mensaje": _mensaje(str(campos.get("mensaje") or "")),
    }


def _parcelas(valor) -> int | None:
    texto = str(valor or "").strip().replace(".", "")
    if not texto:
        return None
    if not texto.isdigit() or not 1 <= int(texto) <= PARCELAS_MAXIMO:
        raise ContactoInvalido("Revisa cuántas parcelas son.")
    return int(texto)


def _mensaje(texto: str) -> str:
    texto = CONTROL.sub("", texto.replace("\r\n", "\n").replace("\r", "\n"))
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    return texto[:MENSAJE_MAXIMO]


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _utc(momento: datetime | None) -> datetime | None:
    """SQLite devuelve las fechas sin zona, aunque se guardaron en UTC."""
    if momento is None:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


class Contactos:
    def __init__(self, base: Base, correo: Correo, *, ahora=_ahora, en_segundo_plano: bool = True):
        self.base = base
        self.correo = correo
        self.ahora = ahora
        self.en_segundo_plano = en_segundo_plano

    def guardar(self, datos: dict, url_consola: str = "") -> Contacto:
        """Un mensaje nuevo, ya revisado con `leer_contacto`. Avisa al equipo de CTP."""
        ahora = self.ahora()
        with self.base.motor.begin() as con:
            nuevo = con.execute(insert(contactos).values(**datos, estado=NUEVO, creado_en=ahora))
            identificador = nuevo.inserted_primary_key[0]
        contacto = Contacto(id=identificador, **datos, estado=NUEVO, creado_en=ahora, atendido_en=None)
        # Sin los datos de la persona: el historial lo ve todo el equipo y el
        # mensaje está en Contactos, que es donde se atiende.
        self.base.anotar("contacto recibido", detalle=NOMBRE_DEL_PLAN[contacto.plan])
        self._avisar(contacto, url_consola)
        return contacto

    def listar(self) -> list[Contacto]:
        with self.base.motor.connect() as con:
            return [_contacto(f) for f in con.execute(
                select(contactos).order_by(contactos.c.creado_en.desc(), contactos.c.id.desc())
                .limit(A_LA_VISTA))]

    def marcar(self, identificador: int, estado: str) -> Contacto:
        """Atendido, o de vuelta a nuevo si se marcó por error. NoEncontrado si no existe."""
        if estado not in ESTADOS:
            raise ValueError(estado)
        condicion = contactos.c.id == identificador
        with self.base.motor.begin() as con:
            cambio = con.execute(update(contactos).where(condicion).values(
                estado=estado, atendido_en=self.ahora() if estado == ATENDIDO else None))
            if cambio.rowcount == 0:
                raise NoEncontrado(f"no existe el contacto {identificador}")
            return _contacto(con.execute(select(contactos).where(condicion)).one())

    def _avisar(self, contacto: Contacto, url_consola: str) -> None:
        """Un correo a cada cuenta activa y confirmada del equipo de CTP. Que falle no
        tumba el mensaje: queda en Contactos igual."""
        destinos = [u.email for u in self.base.usuarios_de_plataforma() if u.activo and u.email_verificado]
        quien = f"{contacto.nombre} ({contacto.loteadora})" if contacto.loteadora else contacto.nombre
        asunto = f"Contacto desde la landing: {quien} · {NOMBRE_DEL_PLAN[contacto.plan]}"
        texto = "\n".join([
            "Alguien escribió en el formulario de tumasterplan.cl.",
            "",
            f"Nombre: {contacto.nombre}",
            f"Correo: {contacto.email}",
            f"Teléfono: {contacto.telefono or '—'}",
            f"Loteadora: {contacto.loteadora or '—'}",
            f"Plan: {NOMBRE_DEL_PLAN[contacto.plan]}",
            f"Parcelas: {contacto.parcelas or '—'}",
            f"Necesita que lo vuelen: {'sí' if contacto.vuelo else 'no'}",
            "(Datos escritos en la landing, sin verificar.)",
            "",
            "Mensaje:",
            contacto.mensaje or "—",
            "",
            f"Atiéndelo en la consola: {url_consola.rstrip('/')}/#/contactos"
            if url_consola else "Atiéndelo en la sección Contactos de la consola.",
        ])
        for destino in destinos:
            if self.en_segundo_plano:
                threading.Thread(target=self._mandar, args=(destino, asunto, texto), daemon=True).start()
            else:
                self._mandar(destino, asunto, texto)

    def _mandar(self, para: str, asunto: str, texto: str) -> None:
        try:
            self.correo.enviar(para, asunto, texto)
        except Exception:   # noqa: BLE001 — un correo caído no se lleva el mensaje
            registro.exception("no pude avisar el contacto a %s", para)


def _contacto(fila) -> Contacto:
    return Contacto(id=fila.id, nombre=fila.nombre, email=fila.email, telefono=fila.telefono,
                    loteadora=fila.loteadora, plan=fila.plan, vuelo=bool(fila.vuelo),
                    parcelas=fila.parcelas, mensaje=fila.mensaje, estado=fila.estado,
                    creado_en=_utc(fila.creado_en), atendido_en=_utc(fila.atendido_en))
