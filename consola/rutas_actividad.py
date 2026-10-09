"""Configuración → Actividad: el historial de la loteadora de quien pide.

Sale de la misma tabla de eventos que ve el equipo de CTP en el back-office, pero
solo lo de esta loteadora. Se pide por partes hacia atrás (`antes`), porque una
loteadora con años de uso no necesita bajar todo para ver lo de hoy.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from .acceso import Sesion
from .datos import Base

LIMITE_MAXIMO = 100


def rutas_de_actividad(base: Base, quien) -> APIRouter:
    rutas = APIRouter()

    @rutas.get("/api/actividad")
    def actividad(limite: int = Query(default=50, ge=1, le=LIMITE_MAXIMO),
                  antes: int | None = Query(default=None, ge=1),
                  sesion: Sesion = Depends(quien)) -> list[dict]:
        eventos = base.historial(sesion.cliente_id, limite=limite, antes=antes)
        personas: dict[int, dict | None] = {}
        for evento in eventos:
            if evento.usuario_id is not None and evento.usuario_id not in personas:
                usuario = base.usuario(evento.usuario_id)
                personas[evento.usuario_id] = (
                    {"nombre": usuario.nombre, "email": usuario.email, "rol": usuario.rol}
                    if usuario else None)
        return [{"id": e.id, "que": e.que, "detalle": e.detalle, "cuando": e.cuando.isoformat(),
                 "quien": personas.get(e.usuario_id) if e.usuario_id is not None else None}
                for e in eventos]

    return rutas
