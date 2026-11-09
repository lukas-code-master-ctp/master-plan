"""Las estadísticas de un loteo publicado: cuánta gente lo mira y qué parcelas.

El visor cuenta cuatro cosas y se las manda a la consola: una visita al sitio, una
parcela abierta, un clic en WhatsApp y un clic en Reservar. Se guardan sumadas por
día y por parcela, sin IP ni nada que diga quién fue: son cifras para la loteadora,
no un registro de personas. Los interesados y las solicitudes de reserva ya están
en sus tablas y se cuentan de ahí.

El porqué y las decisiones: docs/specs/2026-11-09-interesados-y-estadisticas.md.
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, insert, select, update
from sqlalchemy.exc import IntegrityError

from .datos import Base, estadisticas, solicitudes_reserva
from .proyectos import Proyecto

VISITA, FICHA, WHATSAPP, RESERVAR = "visita", "ficha", "whatsapp", "reservar"
TIPOS = (VISITA, FICHA, WHATSAPP, RESERVAR)
# Lo que es de una parcela; una visita es del loteo entero.
DE_PARCELA = (FICHA, WHATSAPP, RESERVAR)

# Lo que el visor junta antes de mandar: más que esto en un pedido es un robot.
EVENTOS_POR_PEDIDO = 30
# Las parcelas que muestra la consola, de la más mirada para abajo.
PARCELAS_A_LA_VISTA = 50
DIAS_POSIBLES = (7, 30, 90)


def _zona():
    try:
        return ZoneInfo("America/Santiago")
    except ZoneInfoNotFoundError:
        return timezone.utc


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _utc(momento: datetime) -> datetime:
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


class EventoInvalido(ValueError):
    """Lo que mandó el visor no tiene la forma esperada."""


def leer_eventos(datos: dict, parcelas_del_sitio: set[str]) -> list[tuple[str, str]]:
    """Los eventos del pedido como (tipo, parcela). Se descartan los de una parcela
    que no está en el sitio: así nadie llena la tabla con parcelas inventadas."""
    lista = datos.get("eventos")
    if not isinstance(lista, list) or len(lista) > EVENTOS_POR_PEDIDO:
        raise EventoInvalido("eventos")
    eventos = []
    for evento in lista:
        if not isinstance(evento, dict) or evento.get("tipo") not in TIPOS:
            continue
        tipo = evento["tipo"]
        parcela = str(evento.get("parcela") or "")[:40] if tipo in DE_PARCELA else ""
        if tipo in DE_PARCELA and parcela not in parcelas_del_sitio:
            continue
        eventos.append((tipo, parcela))
    return eventos


class Estadisticas:
    def __init__(self, base: Base, *, ahora=_ahora):
        self.base = base
        self.ahora = ahora
        # Sumar es leer y escribir: con un candado, dos pedidos a la vez no pierden
        # una cuenta. Basta uno porque la consola corre en una sola instancia.
        self._candado = threading.Lock()
        self._sitios: dict[str, tuple[float, dict[str, str]]] = {}

    def hoy(self) -> date:
        """El día en Chile: una visita a las 23:00 cuenta en ese día y no en el siguiente."""
        return self.ahora().astimezone(_zona()).date()

    # --- lo que manda el sitio publicado ----------------------------------------------

    def parcelas_del_sitio(self, proyecto: Proyecto) -> dict[str, str]:
        """id → estado, del parcelas.json publicado. Se relee solo si el archivo cambió:
        cada visita al sitio manda eventos y no hace falta abrirlo cada vez."""
        archivo = proyecto.salida.datos / "parcelas.json"
        try:
            marca = archivo.stat().st_mtime
        except OSError:
            return {}
        guardado = self._sitios.get(proyecto.slug)
        if guardado and guardado[0] == marca:
            return guardado[1]
        try:
            lista = json.loads(archivo.read_text(encoding="utf-8")).get("parcelas", [])
        except (OSError, ValueError):
            return {}
        parcelas = {str(p.get("id")): str(p.get("estado")) for p in lista if isinstance(p, dict)}
        self._sitios[proyecto.slug] = (marca, parcelas)
        return parcelas

    def sumar(self, proyecto: Proyecto, eventos: list[tuple[str, str]]) -> None:
        if not eventos:
            return
        cuentas: dict[tuple[str, str], int] = {}
        for evento in eventos:
            cuentas[evento] = cuentas.get(evento, 0) + 1
        proyecto_id = self.base.proyecto(proyecto.slug).id
        dia = self.hoy()
        with self._candado:
            for (tipo, parcela), cantidad in cuentas.items():
                self._sumar_uno(proyecto_id, dia, tipo, parcela, cantidad)

    def _sumar_uno(self, proyecto_id: int, dia: date, tipo: str, parcela: str, cantidad: int) -> None:
        condicion = and_(estadisticas.c.proyecto_id == proyecto_id, estadisticas.c.dia == dia,
                         estadisticas.c.tipo == tipo, estadisticas.c.parcela == parcela)
        with self.base.motor.begin() as con:
            fila = con.execute(select(estadisticas.c.id, estadisticas.c.cantidad).where(condicion)).first()
            if fila:
                con.execute(update(estadisticas).where(estadisticas.c.id == fila.id)
                            .values(cantidad=fila.cantidad + cantidad))
                return
        try:
            with self.base.motor.begin() as con:
                con.execute(insert(estadisticas).values(proyecto_id=proyecto_id, dia=dia, tipo=tipo,
                                                        parcela=parcela, cantidad=cantidad))
        except IntegrityError:
            # Otro proceso la creó entre medio: se suma a esa.
            with self.base.motor.begin() as con:
                con.execute(update(estadisticas).where(condicion)
                            .values(cantidad=estadisticas.c.cantidad + cantidad))

    # --- lo que ve la loteadora -------------------------------------------------------

    def resumen(self, proyecto: Proyecto, dias: int, interesados_por_parcela) -> dict:
        """Los últimos `dias` días, hoy incluido. `interesados_por_parcela(desde)`
        cuenta los interesados: viven en su propia tabla."""
        hasta = self.hoy()
        desde = hasta - timedelta(days=dias - 1)
        desde_utc = datetime.combine(desde, time(0), tzinfo=_zona()).astimezone(timezone.utc)
        proyecto_id = self.base.proyecto(proyecto.slug).id

        por_dia = {desde + timedelta(days=n): 0 for n in range(dias)}
        por_parcela: dict[str, dict[str, int]] = {}
        totales = {tipo: 0 for tipo in TIPOS}
        with self.base.motor.connect() as con:
            for fila in con.execute(select(estadisticas).where(and_(
                    estadisticas.c.proyecto_id == proyecto_id, estadisticas.c.dia >= desde))):
                totales[fila.tipo] = totales.get(fila.tipo, 0) + fila.cantidad
                if fila.tipo == VISITA:
                    por_dia[fila.dia] = por_dia.get(fila.dia, 0) + fila.cantidad
                elif fila.parcela:
                    cuenta = por_parcela.setdefault(fila.parcela, {})
                    cuenta[fila.tipo] = cuenta.get(fila.tipo, 0) + fila.cantidad
            reservas: dict[str, int] = {}
            for fila in con.execute(select(solicitudes_reserva.c.parcela, solicitudes_reserva.c.creada_en)
                                    .where(solicitudes_reserva.c.proyecto_id == proyecto_id)):
                if _utc(fila.creada_en) >= desde_utc:
                    reservas[fila.parcela] = reservas.get(fila.parcela, 0) + 1
        interesa = interesados_por_parcela(desde_utc)
        for parcela, cantidad in interesa.items():
            por_parcela.setdefault(parcela, {})["interesa"] = cantidad
        for parcela, cantidad in reservas.items():
            por_parcela.setdefault(parcela, {})["reservas"] = cantidad
        totales["interesa"] = sum(interesa.values())
        totales["reservas"] = sum(reservas.values())

        estados = self.parcelas_del_sitio(proyecto)
        filas = [{"parcela": parcela, "estado": estados.get(parcela),
                  **{clave: cuenta.get(clave, 0)
                     for clave in (FICHA, WHATSAPP, RESERVAR, "interesa", "reservas")}}
                 for parcela, cuenta in por_parcela.items()]
        filas.sort(key=lambda f: (-f[FICHA], -f["interesa"], -f[WHATSAPP], f["parcela"]))
        return {
            "dias": dias, "desde": desde.isoformat(), "hasta": hasta.isoformat(),
            "totales": totales,
            "por_dia": [{"dia": dia.isoformat(), "visitas": cantidad}
                        for dia, cantidad in sorted(por_dia.items())],
            "parcelas": filas[:PARCELAS_A_LA_VISTA],
        }
