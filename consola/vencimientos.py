"""Qué pasa cuando un plan llega a su fecha sin renovarse.

CTP cobra fuera del sistema y anota hasta qué día está pagado el plan. Sin
pasarela, nadie más se entera de que llegó el día: esta revisión es la que avisa
y, si nadie renueva, baja los sitios. Lo decidió Eduardo el 27/10/2026:

- 5 días antes del último día pagado, un recordatorio a la loteadora y a CTP;
- al día siguiente del último pagado, otro: venció, y cuándo se bajan los sitios;
- 7 días después de vencer, los sitios en línea con el plan se bajan solos y el
  plan se quita. Los loteos pagados de a uno (el modelo anterior) no se tocan.

Renovar es asignar de nuevo el plan con otra fecha: vuelve a armar los avisos.
Corre con la tarea de cada 15 minutos; cada paso se anota en el cliente
(`plan_avisado`) para que no se repita.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

from . import planes

registro = logging.getLogger("consola.vencimientos")

DIAS_DE_AVISO = 5
DIAS_DE_GRACIA = 7


def dia_de_bajada(hasta: date) -> date:
    """El primer día en que los sitios ya no tienen que estar en línea."""
    return hasta + timedelta(days=DIAS_DE_GRACIA + 1)


@dataclass
class Revision:
    cliente_id: int
    loteadora: str
    que: str                      # "recordatorio", "vencido", "bajando" o "plan quitado"
    loteos: list[str] = field(default_factory=list)


def revisar(base, avisos, *, bajar, ocupado, hoy: date | None = None,
            url_consola: str = "") -> list[Revision]:
    """Recorre las loteadoras con plan y fecha, y hace lo que toque a cada una.

    `bajar(slug)` lanza la bajada de un loteo; `ocupado(slug)` dice si ya hay un
    trabajo corriendo en él (por ejemplo, la bajada de la vuelta anterior).
    """
    dia = hoy or planes.hoy()
    hechas: list[Revision] = []
    for cliente in base.clientes():
        if not cliente.plan or not cliente.plan_hasta:
            continue
        hasta = cliente.plan_hasta
        nombre = planes.PLANES[cliente.plan].nombre if cliente.plan in planes.PLANES else cliente.plan
        if dia >= dia_de_bajada(hasta):
            en_linea = [g for g in base.proyectos(cliente_id=cliente.id) if planes.ocupa_cupo(g)]
            if en_linea:
                # Uno que ya se está bajando (o publicando) espera a la próxima vuelta.
                libres = [g.slug for g in en_linea if not ocupado(g.slug)]
                for slug in libres:
                    try:
                        bajar(slug)
                    except Exception:  # noqa: BLE001 — uno que falla no frena a los demás
                        registro.exception("no pude bajar %s", slug)
                hechas.append(Revision(cliente.id, cliente.nombre, "bajando", libres))
                continue
            # Recién con todo abajo se quita el plan: si una bajada falla, la
            # próxima vuelta la reintenta en vez de dejar un sitio sin plan en línea.
            base.asignar_plan(cliente.id, None)
            base.anotar("plan vencido", cliente_id=cliente.id,
                        detalle=f"{nombre} · pagado hasta {hasta.strftime('%d/%m/%Y')}")
            avisos.plan_bajado(cliente_id=cliente.id, plan=nombre, url_consola=url_consola)
            hechas.append(Revision(cliente.id, cliente.nombre, "plan quitado"))
        elif dia > hasta:
            if cliente.plan_avisado != "vencido":
                base.anotar_aviso_de_plan(cliente.id, "vencido")
                avisos.plan_vencido(cliente_id=cliente.id, plan=nombre, hasta=hasta,
                                    bajada=dia_de_bajada(hasta), url_consola=url_consola)
                hechas.append(Revision(cliente.id, cliente.nombre, "vencido"))
        elif (hasta - dia).days <= DIAS_DE_AVISO:
            if cliente.plan_avisado is None:
                base.anotar_aviso_de_plan(cliente.id, "previo")
                avisos.plan_por_vencer(cliente_id=cliente.id, plan=nombre, hasta=hasta,
                                       url_consola=url_consola)
                hechas.append(Revision(cliente.id, cliente.nombre, "recordatorio"))
    return hechas
