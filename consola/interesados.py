"""Los interesados: quien toca "Me interesa esta parcela" en el sitio publicado.

A diferencia de una reserva, no aparta nada ni lleva a pagar. Es un contacto: el
comprador deja nombre y teléfono, la loteadora recibe un correo y lo sigue en la
consola (estado, quién lo atiende y una nota) hasta que reserva o se descarta.

El porqué y las decisiones: docs/specs/2026-11-09-interesados-y-estadisticas.md.
"""
from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, insert, select, update

from .cuentas import Correo, limpiar_texto
from .datos import Base, NoEncontrado, interesados
from .proyectos import Proyecto
from .reservas import CORREO, SolicitudInvalida, _estado_en_el_sitio

registro = logging.getLogger("consola.interesados")

NUEVO, CONTACTADO, VISITA, RESERVO, DESCARTADO = "nuevo", "contactado", "visita", "reservo", "descartado"
ESTADOS = (NUEVO, CONTACTADO, VISITA, RESERVO, DESCARTADO)
HORARIOS = ("manana", "tarde", "")
TEXTO_HORARIO = {"manana": "en la mañana", "tarde": "en la tarde", "": "a cualquier hora"}

# El mismo teléfono por la misma parcela dentro de este plazo no es un interesado
# nuevo: es alguien que apretó dos veces o volvió a mirar. No se duplica ni se avisa.
REPETIDO = timedelta(hours=24)

# Lo que la consola muestra: los más recientes. Un loteo con más que esto ya
# necesita filtros, y para eso está la planilla.
A_LA_VISTA = 500


@dataclass(frozen=True)
class Datos:
    nombre: str
    telefono: str
    email: str
    horario: str


@dataclass(frozen=True)
class Interesado:
    id: int
    parcela: str
    nombre: str
    telefono: str
    email: str
    horario: str
    estado: str
    responsable: str
    nota: str
    creado_en: datetime
    actualizado_en: datetime

    def como_json(self) -> dict:
        return {"id": self.id, "parcela": self.parcela, "nombre": self.nombre,
                "telefono": self.telefono, "email": self.email, "horario": self.horario,
                "estado": self.estado, "responsable": self.responsable, "nota": self.nota,
                "creado_en": self.creado_en.isoformat(),
                "actualizado_en": self.actualizado_en.isoformat()}


def leer_datos(datos: dict) -> Datos:
    """Lo que escribió el comprador, revisado. El correo es opcional: lo que la
    loteadora necesita para seguirlo es el teléfono."""
    nombre = limpiar_texto(str(datos.get("nombre") or ""), 120)
    if len(nombre) < 2:
        raise SolicitudInvalida("Escribe tu nombre.")
    telefono = re.sub(r"\D", "", str(datos.get("telefono") or ""))
    if len(telefono) == 9 and telefono.startswith("9"):
        telefono = "56" + telefono   # un celular chileno escrito sin el 56
    if not 8 <= len(telefono) <= 15:
        raise SolicitudInvalida("Escribe un teléfono donde podamos llamarte.")
    email = limpiar_texto(str(datos.get("email") or ""), 160)
    if email and not CORREO.fullmatch(email):
        raise SolicitudInvalida("Revisa el correo, o déjalo en blanco.")
    horario = str(datos.get("horario") or "")
    if horario not in HORARIOS:
        horario = ""
    return Datos(nombre=nombre, telefono=telefono, email=email, horario=horario)


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _utc(momento: datetime) -> datetime:
    """SQLite devuelve las fechas sin zona, aunque se guardaron en UTC."""
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


class Interesados:
    def __init__(self, base: Base, correo: Correo, *, ahora=_ahora, en_segundo_plano: bool = True):
        self.base = base
        self.correo = correo
        self.ahora = ahora
        self.en_segundo_plano = en_segundo_plano

    def registrar(self, proyecto: Proyecto, parcela: str, datos: Datos,
                  url_consola: str = "") -> tuple[Interesado, bool]:
        """Guarda al interesado y avisa a la loteadora. Devuelve (interesado, nuevo):
        si el mismo teléfono ya pidió esa parcela hace poco, el de antes y False.
        NoEncontrado si la parcela no existe en el sitio."""
        _estado_en_el_sitio(proyecto, parcela)   # que exista; el estado no importa
        ahora = self.ahora()
        proyecto_id = self._id(proyecto)
        with self.base.motor.connect() as con:
            anteriores = [_interesado(f) for f in con.execute(select(interesados).where(and_(
                interesados.c.proyecto_id == proyecto_id, interesados.c.parcela == parcela,
                interesados.c.telefono == datos.telefono)))]
        reciente = next((i for i in anteriores if ahora - i.creado_en < REPETIDO), None)
        if reciente:
            return reciente, False
        with self.base.motor.begin() as con:
            nuevo = con.execute(insert(interesados).values(
                proyecto_id=proyecto_id, parcela=parcela, nombre=datos.nombre,
                telefono=datos.telefono, email=datos.email, horario=datos.horario,
                estado=NUEVO, responsable="", nota="", creado_en=ahora, actualizado_en=ahora))
            identificador = nuevo.inserted_primary_key[0]
        interesado = Interesado(id=identificador, parcela=parcela, nombre=datos.nombre,
                                telefono=datos.telefono, email=datos.email, horario=datos.horario,
                                estado=NUEVO, responsable="", nota="", creado_en=ahora,
                                actualizado_en=ahora)
        # Sin los datos del comprador: el historial lo ve todo el equipo.
        self.base.anotar("interesado nuevo", cliente_id=proyecto.cliente_id,
                         detalle=f"Parcela {parcela} · {proyecto.nombre}")
        self._avisar(proyecto, interesado, url_consola)
        return interesado, True

    def del_loteo(self, proyecto: Proyecto) -> list[Interesado]:
        with self.base.motor.connect() as con:
            return [_interesado(f) for f in con.execute(
                select(interesados).where(interesados.c.proyecto_id == self._id(proyecto))
                .order_by(interesados.c.creado_en.desc()).limit(A_LA_VISTA))]

    def por_parcela(self, proyecto: Proyecto, desde: datetime) -> dict[str, int]:
        """Cuántos interesados llegaron por cada parcela desde `desde`."""
        cuenta: dict[str, int] = {}
        with self.base.motor.connect() as con:
            for fila in con.execute(select(interesados.c.parcela, interesados.c.creado_en)
                                    .where(interesados.c.proyecto_id == self._id(proyecto))):
                if _utc(fila.creado_en) >= desde:
                    cuenta[fila.parcela] = cuenta.get(fila.parcela, 0) + 1
        return cuenta

    def actualizar(self, proyecto: Proyecto, identificador: int, cambios: dict) -> Interesado:
        """Estado, responsable o nota: los que vengan. Uno de otro loteo: NoEncontrado."""
        valores = {}
        if "estado" in cambios:
            if cambios["estado"] not in ESTADOS:
                raise ValueError("ese estado no existe")
            valores["estado"] = cambios["estado"]
        if "responsable" in cambios:
            valores["responsable"] = limpiar_texto(str(cambios["responsable"] or ""), 60)
        if "nota" in cambios:
            # La nota sí puede tener saltos de línea: la escribe la loteadora y no va a un correo.
            valores["nota"] = str(cambios["nota"] or "").strip()[:2000]
        condicion = and_(interesados.c.id == identificador,
                         interesados.c.proyecto_id == self._id(proyecto))
        with self.base.motor.begin() as con:
            if con.execute(select(interesados.c.id).where(condicion)).first() is None:
                raise NoEncontrado(f"no existe el interesado {identificador}")
            if valores:
                con.execute(update(interesados).where(condicion)
                            .values(**valores, actualizado_en=self.ahora()))
            return _interesado(con.execute(select(interesados).where(condicion)).one())

    # --- interno ----------------------------------------------------------------------

    def _id(self, proyecto: Proyecto) -> int:
        return self.base.proyecto(proyecto.slug).id

    def _avisar(self, proyecto: Proyecto, interesado: Interesado, url_consola: str) -> None:
        """Un correo a cada cuenta activa y confirmada de la loteadora. Que el correo
        falle no puede tumbar al interesado: queda en la consola igual."""
        destinos = [u.email for u in self.base.usuarios_de(proyecto.cliente_id)
                    if u.activo and u.email_verificado]
        asunto = f"Interesado en la parcela {interesado.parcela} · {proyecto.nombre}"
        texto = "\n".join([
            f"Alguien se interesó en la parcela {interesado.parcela} de {proyecto.nombre}"
            " desde el Masterplan y pidió que lo contacten.",
            "",
            f"Nombre: {interesado.nombre}",
            f"Teléfono: {interesado.telefono}",
            *([f"Correo: {interesado.email}"] if interesado.email else []),
            f"Prefiere que lo llamen {TEXTO_HORARIO[interesado.horario]}.",
            "(Datos escritos por el comprador en el sitio, sin verificar.)",
            "",
            f"Síguelo en la consola: {url_consola.rstrip('/')}/#/interesados"
            if url_consola else "Síguelo en la sección Interesados de la consola.",
        ])
        for destino in destinos:
            if self.en_segundo_plano:
                threading.Thread(target=self._mandar, args=(destino, asunto, texto), daemon=True).start()
            else:
                self._mandar(destino, asunto, texto)

    def _mandar(self, para: str, asunto: str, texto: str) -> None:
        try:
            self.correo.enviar(para, asunto, texto)
        except Exception:   # noqa: BLE001 — un correo caído no se lleva al interesado
            registro.exception("no pude avisar del interesado a %s", para)


def _interesado(fila) -> Interesado:
    return Interesado(id=fila.id, parcela=fila.parcela, nombre=fila.nombre, telefono=fila.telefono,
                      email=fila.email, horario=fila.horario, estado=fila.estado,
                      responsable=fila.responsable, nota=fila.nota,
                      creado_en=_utc(fila.creado_en), actualizado_en=_utc(fila.actualizado_en))
