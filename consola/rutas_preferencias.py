"""Configuración → Reservas y contacto.

Lo que la loteadora deja fijado una vez: el WhatsApp con que nacen sus masters, el
diseño que Nuevo master ofrece primero y cuántas horas queda apartada una parcela
mientras el comprador paga. Lo cambia el dueño, como el resto de lo que vale para
toda la loteadora (rutas_equipo.py); el equipo lo ve.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from pipeline import config

from .acceso import Sesion
from .datos import Base, NoEncontrado
from .reservas import HORAS_APARTADO, HORAS_APARTADO_MAXIMO
from .rutas_equipo import ADMINISTRAN

# wa.me pide el número con el código del país: menos de 8 dígitos no es un teléfono.
DIGITOS_WHATSAPP = range(8, 16)


def preferencias_de(base: Base, sesion: Sesion) -> dict:
    cliente = base.cliente(sesion.cliente_id)
    return {"whatsapp": cliente.whatsapp or "", "diseno_id": cliente.diseno_id,
            "horas_apartado": cliente.horas_apartado or HORAS_APARTADO,
            "administra": sesion.rol in ADMINISTRAN}


def rutas_de_preferencias(base: Base, quien) -> APIRouter:
    rutas = APIRouter()

    @rutas.get("/api/preferencias")
    def ver(sesion: Sesion = Depends(quien)) -> dict:
        return preferencias_de(base, sesion)

    @rutas.patch("/api/preferencias")
    def cambiar(campos: dict = Body(...), sesion: Sesion = Depends(quien)) -> dict:
        if sesion.rol not in ADMINISTRAN:
            raise HTTPException(403, "esto lo cambia quien es dueño de la loteadora")
        limpios = {}
        if "whatsapp" in campos:
            limpios["whatsapp"] = _whatsapp(campos["whatsapp"])
        if "horas_apartado" in campos:
            limpios["horas_apartado"] = _horas(campos["horas_apartado"])
        if "diseno_id" in campos:
            limpios["diseno_id"] = _diseno(base, campos["diseno_id"], sesion)
        base.guardar_preferencias(sesion.cliente_id, **limpios)
        base.anotar("preferencias cambiadas", cliente_id=sesion.cliente_id,
                    usuario_id=sesion.usuario_id, detalle=", ".join(sorted(limpios)) or None)
        return preferencias_de(base, sesion)

    return rutas


def _whatsapp(valor) -> str | None:
    numero = config.normalizar_whatsapp(str(valor or ""))
    if not numero:
        return None
    if len(numero) not in DIGITOS_WHATSAPP:
        raise HTTPException(400, "Ese WhatsApp no parece un número: escríbelo con el código del país.")
    return numero


def _horas(valor) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or not 1 <= valor <= HORAS_APARTADO_MAXIMO:
        raise HTTPException(400, f"Las horas de apartado van de 1 a {HORAS_APARTADO_MAXIMO}.")
    return valor


def _diseno(base: Base, valor, sesion: Sesion) -> int | None:
    if valor in (None, ""):
        return None
    try:
        return base.diseno(int(valor), cliente_id=sesion.cliente_id).id
    except (NoEncontrado, ValueError, TypeError) as error:
        raise HTTPException(404, "ese diseño no es tuyo") from error
