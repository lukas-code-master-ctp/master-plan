"""El cobro mensual con tarjeta: qué hace la consola con lo que dice Flow.

El recorrido de una loteadora que paga sola:

1. Elige un plan. Si todavía no tiene tarjeta en Flow, se crea su cliente en Flow y
   se la manda a registrarla (`empezar`).
2. Flow la devuelve a `/api/flow/tarjeta` con un token. Con la tarjeta registrada se
   la suscribe al plan, y Flow le cobra el primer mes en ese momento (`tarjeta_lista`).
3. Desde ahí Flow cobra solo cada mes y avisa cada pago a `/api/flow/pago`.

Quien decide si el plan está activo es siempre Flow, nunca lo que diga un aviso:
`sincronizar` le pregunta por la suscripción y deja el plan de la loteadora igual a
lo que contesta. Lo llaman el aviso de pago, la vuelta de la tarjeta y la tarea
diaria (`/api/tareas/flow`), así que un aviso perdido se arregla solo al día
siguiente.

Un plan está activo si la suscripción está activa (o en trial), no está morosa y
ya se pagó al menos un mes. Si Flow la cancela o queda morosa después de sus
reintentos, la loteadora queda sin plan: sus sitios siguen en línea, pero no puede
publicar loteos nuevos ni volver a publicar los que tiene.

El plan a la medida (Enterprise) y los pagos por transferencia siguen anotándose a
mano en la ficha de la loteadora.
"""
from __future__ import annotations

import logging

from .datos import Base, Cliente
from .flow import DESDE_FLOW, ID_EN_FLOW, Flow, FlowNoResponde
from .planes import PLANES

registro = logging.getLogger("consola.cobros")

# Los estados de una suscripción en Flow.
ACTIVA, EN_TRIAL, CANCELADA = 1, 2, 4
# `morose`: 1 = tiene importes vencidos (Flow ya agotó sus reintentos).
MOROSA = 1
# Estado de un importe (invoice) pagado.
PAGADO = 1


class CobroInvalido(Exception):
    """Lo pedido no se puede hacer así. El mensaje es para la persona."""


class Cobros:
    def __init__(self, base: Base, flow: Flow):
        self.base = base
        self.flow = flow

    # --- lo que pide la loteadora -------------------------------------------------

    def empezar(self, cliente_id: int, plan: str, *, email: str, url_vuelta: str,
                usuario_id: int | None = None) -> str | None:
        """Elegir o cambiar de plan. Devuelve adónde mandar el navegador a registrar la
        tarjeta, o None si ya tenía tarjeta y el cambio quedó hecho."""
        if plan not in ID_EN_FLOW:
            raise CobroInvalido("ese plan no se paga con tarjeta: escríbenos y lo armamos contigo")
        cliente = self.base.cliente(cliente_id)
        if cliente.flow_suscripcion and cliente.plan == plan and not cliente.flow_hasta:
            raise CobroInvalido(f"ya tienes el plan {PLANES[plan].nombre}")
        self.base.pedir_plan(cliente_id, plan)
        if cliente.flow_cliente and cliente.flow_tarjeta:
            self.suscribir(self.base.cliente(cliente_id), plan, usuario_id=usuario_id)
            return None
        flow_cliente = cliente.flow_cliente
        if not flow_cliente:
            # El id de la loteadora como identificador externo: el nombre puede
            # cambiar, y dos loteadoras pueden tener el mismo correo de facturación
            # en el futuro.
            flow_cliente = self.flow.crear_cliente(nombre=cliente.nombre, email=email,
                                                   externo=f"loteadora-{cliente.id}")
            self.base.guardar_flow(cliente_id, flow_cliente=flow_cliente)
        return self.flow.registrar_tarjeta(flow_cliente, url_vuelta)

    def tarjeta_lista(self, token: str) -> tuple[Cliente | None, bool]:
        """La vuelta de Flow después de registrar la tarjeta. Devuelve la loteadora
        (None si el token no es de nadie nuestro) y si quedó suscrita."""
        resultado = self.flow.estado_registro(token)
        cliente = self.base.cliente_de_flow(str(resultado.get("customerId") or ""))
        if cliente is None:
            return None, False
        if str(resultado.get("status")) != "1":
            return cliente, False
        marca = str(resultado.get("creditCardType") or "Tarjeta")
        ultimos = str(resultado.get("last4CardDigits") or "")
        self.base.guardar_flow(cliente.id, flow_tarjeta=f"{marca} ···· {ultimos}".strip(" ·"))
        if not cliente.plan_pedido:
            return cliente, False
        self.suscribir(self.base.cliente(cliente.id), cliente.plan_pedido)
        return self.base.cliente(cliente.id), True

    def suscribir(self, cliente: Cliente, plan: str, *, usuario_id: int | None = None) -> None:
        """Suscribe al plan. Si ya tenía otro, primero se cancela el anterior al tiro.

        Así un cambio de plan cobra el mes completo del nuevo desde hoy, sin
        descontar lo que quedaba del anterior.
        """
        if cliente.flow_suscripcion:
            try:
                self.flow.cancelar(cliente.flow_suscripcion, al_final=False)
            except FlowNoResponde:
                # Si ya estaba cancelada en Flow, no hay nada que cancelar; si Flow
                # está caído, la nueva tampoco se va a crear.
                registro.warning("no se pudo cancelar %s antes del cambio", cliente.flow_suscripcion)
        nueva = self.flow.suscribir(cliente.flow_cliente, plan)
        self.base.guardar_flow(cliente.id, flow_suscripcion=str(nueva["subscriptionId"]),
                               flow_hasta=None)
        self.base.anotar("suscripción en Flow", cliente_id=cliente.id, usuario_id=usuario_id,
                         detalle=PLANES[plan].nombre)
        self._aplicar(self.base.cliente(cliente.id), nueva)

    def cancelar(self, cliente_id: int, *, usuario_id: int | None = None) -> str | None:
        """Cancela al final del período pagado. Devuelve hasta cuándo sigue el plan."""
        cliente = self.base.cliente(cliente_id)
        if not cliente.flow_suscripcion:
            raise CobroInvalido("no tienes una suscripción con tarjeta")
        suscripcion = self.flow.cancelar(cliente.flow_suscripcion, al_final=True)
        hasta = _dia(suscripcion.get("period_end") or suscripcion.get("cancel_at"))
        self.base.guardar_flow(cliente_id, flow_hasta=hasta)
        self.base.anotar("suscripción cancelada", cliente_id=cliente_id, usuario_id=usuario_id,
                         detalle=f"sigue hasta el {hasta}" if hasta else None)
        return hasta

    # --- lo que dice Flow ---------------------------------------------------------

    def pago_avisado(self, token: str) -> int:
        """Un aviso de pago de Flow. Solo sirve de campanazo: se comprueba que el token
        sea de Flow y se sincronizan las suscripciones. El aviso no dice de qué
        loteadora es, y con pocas decenas de suscripciones revisarlas todas es más
        simple y más seguro que adivinarlo."""
        self.flow.estado_pago(token)
        return self.sincronizar_todas()

    def sincronizar_todas(self) -> int:
        revisadas = 0
        for cliente in self.base.clientes():
            if cliente.flow_suscripcion:
                try:
                    self.sincronizar(cliente)
                    revisadas += 1
                except FlowNoResponde:
                    registro.warning("no se pudo revisar la suscripción de %s", cliente.slug)
        return revisadas

    def sincronizar(self, cliente: Cliente) -> None:
        self._aplicar(cliente, self.flow.suscripcion(cliente.flow_suscripcion))

    def _aplicar(self, cliente: Cliente, suscripcion: dict) -> None:
        """Deja el plan de la loteadora como dice la suscripción de Flow.

        Solo si sigue siendo su suscripción: un aviso de pago puede llegar mientras
        cambia de plan, y la respuesta sobre la anterior (ya cancelada) no puede
        quitarle el plan nuevo."""
        cliente = self.base.cliente(cliente.id)
        if str(suscripcion.get("subscriptionId") or "") != (cliente.flow_suscripcion or ""):
            return
        plan = DESDE_FLOW.get(str(suscripcion.get("planId") or ""))
        estado = _entero(suscripcion.get("status"))
        if estado == CANCELADA:
            self.base.guardar_flow(cliente.id, flow_suscripcion=None, flow_hasta=None)
        if plan and activa(suscripcion):
            if cliente.plan != plan:
                self.base.asignar_plan(cliente.id, plan,
                                       nota=f"Flow · suscripción {suscripcion.get('subscriptionId')}")
                self.base.anotar("plan asignado", cliente_id=cliente.id,
                                 detalle=f"{PLANES[plan].nombre} · pagado con tarjeta en Flow")
            return
        # Solo se quita un plan que vino de Flow: uno anotado a mano (Enterprise, una
        # transferencia) no lo toca una suscripción vieja.
        if cliente.plan in ID_EN_FLOW and (cliente.plan_nota or "").startswith("Flow"):
            if estado == CANCELADA or _entero(suscripcion.get("morose")) == MOROSA:
                self.base.asignar_plan(cliente.id, None)
                self.base.anotar("plan quitado", cliente_id=cliente.id,
                                 detalle=f"{PLANES[cliente.plan].nombre} · "
                                         + ("cancelado en Flow" if estado == CANCELADA
                                            else "pago vencido en Flow"))


def activa(suscripcion: dict) -> bool:
    """Activa (o en trial), sin importes vencidos y con algún mes ya pagado: una tarjeta
    rechazada en el primer cobro no deja tres días de plan gratis."""
    estado = _entero(suscripcion.get("status"))
    if estado not in (ACTIVA, EN_TRIAL) or _entero(suscripcion.get("morose")) == MOROSA:
        return False
    if estado == EN_TRIAL:
        return True
    return any(_entero(i.get("status")) == PAGADO for i in suscripcion.get("invoices") or [])


def _entero(valor) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _dia(valor) -> str | None:
    """"2026-11-27 00:00:00" → "2026-11-27"."""
    return str(valor)[:10] if valor else None
