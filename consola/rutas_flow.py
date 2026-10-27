"""Las rutas del pago con tarjeta en Flow (la lógica está en `consola/cobros.py`).

Dos son de la loteadora, con sesión y solo para quien es dueño: elegir o cambiar
el plan, y cancelarlo. Dos las llama Flow, sin sesión:

- `/api/flow/tarjeta`: el navegador vuelve de registrar la tarjeta. Llega como un
  POST desde flow.cl, así que la galleta de sesión (SameSite=Lax) no viene; tampoco
  hace falta: con el token se le pregunta a Flow de quién es. Termina siempre en una
  redirección a la consola, que sí abre con la sesión.
- `/api/flow/pago`: Flow avisa un pago. Con el token se verifica en Flow y se
  revisan las suscripciones.

Ninguna de las dos cree lo que trae el pedido: solo el token, y el token se
consulta firmado. Un POST inventado da un error de Flow y no cambia nada.
"""
from __future__ import annotations

import hmac
import os

from fastapi import APIRouter, Body, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .acceso import Sesion
from .cobros import CobroInvalido, Cobros
from .cuentas import Limitador
from .flow import LARGO_MAXIMO_TOKEN, FlowNoResponde
from .rutas_cuentas import ip_de, url_base
from .rutas_equipo import ADMINISTRAN

PUBLICAS = ("/api/flow/tarjeta", "/api/flow/pago")
TAREAS = ("/api/tareas/flow",)


def rutas_de_flow(cobros: Cobros | None, quien, *, local: bool,
                  avisos_por_ip: Limitador | None = None) -> APIRouter:
    rutas = APIRouter()
    # Flow manda un aviso por pago y una vuelta por tarjeta: esto sobra y frena a
    # quien pruebe tokens al azar contra Flow usando nuestra apiKey.
    avisos_por_ip = avisos_por_ip or Limitador(maximo=60, segundos=3600)

    def con_flow() -> Cobros:
        if cobros is None:
            raise HTTPException(503, "el pago con tarjeta todavía no está activo: pide tu "
                                     "plan y te escribimos")
        return cobros

    def duenio(sesion: Sesion) -> None:
        if sesion.rol not in ADMINISTRAN:
            raise HTTPException(403, "el plan lo elige quien es dueño de la loteadora")

    def token_valido(peticion: Request, token: str) -> str:
        if not avisos_por_ip.permitir(ip_de(peticion, local)):
            raise HTTPException(429, "demasiados avisos")
        token = (token or "").strip()
        if not token or len(token) > LARGO_MAXIMO_TOKEN:
            raise HTTPException(400, "falta el token")
        return token

    @rutas.post("/api/plan/flow")
    def elegir(peticion: Request, campos: dict = Body(...),
               sesion: Sesion = Depends(quien)) -> dict:
        """Devuelve `url` para registrar la tarjeta, o `cambiado` si ya la tenía."""
        duenio(sesion)
        try:
            url = con_flow().empezar(sesion.cliente_id, str(campos.get("plan") or ""),
                                     email=sesion.quien, usuario_id=sesion.usuario_id,
                                     url_vuelta=f"{url_base(peticion, local)}/api/flow/tarjeta")
        except CobroInvalido as error:
            raise HTTPException(409, str(error)) from error
        except FlowNoResponde as error:
            raise HTTPException(502, str(error)) from error
        return {"url": url} if url else {"cambiado": True}

    @rutas.post("/api/plan/flow/cancelar")
    def cancelar(sesion: Sesion = Depends(quien)) -> dict:
        duenio(sesion)
        try:
            return {"hasta": con_flow().cancelar(sesion.cliente_id, usuario_id=sesion.usuario_id)}
        except CobroInvalido as error:
            raise HTTPException(409, str(error)) from error
        except FlowNoResponde as error:
            raise HTTPException(502, str(error)) from error

    @rutas.post("/api/flow/tarjeta")
    def tarjeta(peticion: Request, token: str = Form("")) -> RedirectResponse:
        token = token_valido(peticion, token)
        resultado = "error"
        try:
            cliente, suscrito = con_flow().tarjeta_lista(token)
            if cliente is not None:
                resultado = "listo" if suscrito else "sin-tarjeta"
        except (FlowNoResponde, CobroInvalido):
            pass
        # A una dirección fija de la consola, nunca a una que traiga el pedido.
        return RedirectResponse(f"{url_base(peticion, local)}/?plan={resultado}#/configuracion",
                                status_code=303)

    @rutas.post("/api/flow/pago")
    def pago(peticion: Request, token: str = Form("")) -> dict:
        token = token_valido(peticion, token)
        try:
            return {"revisadas": con_flow().pago_avisado(token)}
        except FlowNoResponde as error:
            # Flow reintenta los avisos que no reciben 200; uno inventado no merece más.
            raise HTTPException(400, "token desconocido") from error

    @rutas.post("/api/tareas/flow")
    def tarea(peticion: Request) -> dict:
        """Una vez al día (Cloud Scheduler): por si se perdió algún aviso de Flow.
        Sin `CONSOLA_TAREAS_CLAVE` la ruta no existe, como la de Cierra."""
        esperada = os.environ.get("CONSOLA_TAREAS_CLAVE", "")
        if not esperada or cobros is None:
            raise HTTPException(404, "no existe")
        dada = peticion.headers.get("x-tarea-clave", "")
        if not hmac.compare_digest(dada.encode(), esperada.encode()):
            raise HTTPException(401, "clave de tarea inválida")
        return {"revisadas": cobros.sincronizar_todas()}

    return rutas
