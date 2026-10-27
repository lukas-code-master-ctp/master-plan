"""El cliente de la API de Flow (flow.cl): tarjeta y cobro mensual de los planes.

Solo lo que usa la consola: crear el cliente, mandarlo a registrar su tarjeta,
suscribirlo a un plan, consultar y cancelar la suscripción, y verificar los avisos
de pago. La lógica de qué hacer con eso está en `consola/cobros.py`.

Cómo habla Flow (https://developers.flow.cl/api):
- Cada petición lleva `apiKey` y la firma `s`: HMAC-SHA256, con la secretKey, de
  los parámetros ordenados por nombre y pegados nombre+valor, sin separadores.
- Lo asíncrono (la tarjeta registrada, un pago) Flow lo avisa con un POST que trae
  solo un `token`. El aviso no se cree: con el token se le pregunta a Flow, firmado,
  qué pasó. Así nadie puede activarse un plan mandando un POST inventado.

Sin `FLOW_API_KEY` y `FLOW_SECRET_KEY` la consola no ofrece pagar con tarjeta y el
plan se sigue pidiendo y anotando a mano.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

registro = logging.getLogger("consola.flow")

SANDBOX = "https://sandbox.flow.cl/api"
PRODUCCION = "https://www.flow.cl/api"

# Cómo se llaman nuestros planes en Flow. Se crean una vez con
# `python -m consola.flow planes` y desde ahí Flow cobra solo cada mes.
ID_EN_FLOW = {"fly": "tumasterplan-fly", "pro": "tumasterplan-pro", "master": "tumasterplan-master"}
DESDE_FLOW = {v: k for k, v in ID_EN_FLOW.items()}

# Un token de Flow es un hash de unas decenas de caracteres; esto deja holgura sin
# aceptar cualquier cosa en una ruta pública.
LARGO_MAXIMO_TOKEN = 120


class FlowNoResponde(Exception):
    """Flow no contestó o contestó con un error. El mensaje es para la persona."""


def firmar(parametros: dict, secreto: str) -> str:
    texto = "".join(f"{nombre}{parametros[nombre]}" for nombre in sorted(parametros))
    return hmac.new(secreto.encode(), texto.encode(), hashlib.sha256).hexdigest()


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    """Seguir una redirección reenviaría la apiKey y la firma a otro servidor."""

    def redirect_request(self, *argumentos, **nombrados):
        return None


_ABRIR = urllib.request.build_opener(_SinRedirecciones()).open


class Flow:
    def __init__(self, url: str, clave: str, secreto: str):
        self.url = url.rstrip("/")
        self.clave = clave
        self.secreto = secreto

    # --- clientes y tarjeta -------------------------------------------------------

    def crear_cliente(self, *, nombre: str, email: str, externo: str) -> str:
        return str(self._post("customer/create", name=nombre, email=email,
                              externalId=externo)["customerId"])

    def registrar_tarjeta(self, cliente: str, url_vuelta: str) -> str:
        """La dirección a la que se manda el navegador a registrar la tarjeta."""
        respuesta = self._post("customer/register", customerId=cliente, url_return=url_vuelta)
        return f"{respuesta['url']}?token={urllib.parse.quote(str(respuesta['token']))}"

    def estado_registro(self, token: str) -> dict:
        """status 1 si quedó registrada; trae customerId, creditCardType y last4CardDigits."""
        return self._get("customer/getRegisterStatus", token=token)

    # --- suscripciones ------------------------------------------------------------

    def suscribir(self, cliente: str, plan: str) -> dict:
        return self._post("subscription/create", customerId=cliente, planId=ID_EN_FLOW[plan])

    def suscripcion(self, suscripcion: str) -> dict:
        return self._get("subscription/get", subscriptionId=suscripcion)

    def cancelar(self, suscripcion: str, *, al_final: bool) -> dict:
        return self._post("subscription/cancel", subscriptionId=suscripcion,
                          at_period_end=1 if al_final else 0)

    def estado_pago(self, token: str) -> dict:
        return self._get("payment/getStatus", token=token)

    # --- planes (una vez, al configurar) ------------------------------------------

    def plan(self, plan_id: str) -> dict | None:
        try:
            return self._get("plans/get", planId=plan_id)
        except FlowNoResponde:
            return None

    def crear_plan(self, plan_id: str, *, nombre: str, monto: int, url_aviso: str) -> dict:
        # interval 3 = mensual. Los reintentos y los días para vencer quedan los de
        # Flow (3 y 3): es lo que el comercio ya conoce de su panel.
        return self._post("plans/create", planId=plan_id, name=nombre, currency="CLP",
                          amount=monto, interval=3, urlCallback=url_aviso)

    # --- interno ------------------------------------------------------------------

    def _firmados(self, parametros: dict) -> dict:
        todos = {"apiKey": self.clave, **{k: v for k, v in parametros.items() if v is not None}}
        return {**todos, "s": firmar(todos, self.secreto)}

    def _get(self, servicio: str, **parametros) -> dict:
        consulta = urllib.parse.urlencode(self._firmados(parametros))
        return self._pedir(urllib.request.Request(f"{self.url}/{servicio}?{consulta}"), servicio)

    def _post(self, servicio: str, **parametros) -> dict:
        cuerpo = urllib.parse.urlencode(self._firmados(parametros)).encode()
        peticion = urllib.request.Request(
            f"{self.url}/{servicio}", data=cuerpo, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        return self._pedir(peticion, servicio)

    def _pedir(self, peticion: urllib.request.Request, servicio: str) -> dict:
        peticion.add_header("Accept", "application/json")
        try:
            with _ABRIR(peticion, timeout=20) as respuesta:
                return json.loads(respuesta.read(1_000_000))
        except urllib.error.HTTPError as error:
            # Flow explica el error en el cuerpo ({"code": 1620, "message": "..."}).
            try:
                detalle = json.loads(error.read(10_000)).get("message", "")
            except (ValueError, AttributeError):
                detalle = ""
            registro.warning("Flow contestó %s en %s: %s", error.code, servicio, detalle)
            raise FlowNoResponde(f"Flow contestó con un error: {detalle or error.code}") from error
        except (OSError, ValueError) as error:
            registro.warning("Flow no contestó en %s: %s", servicio, error)
            raise FlowNoResponde("Flow no contestó. Vuelve a intentarlo en un rato.") from error


def flow_del_entorno(local: bool) -> Flow | None:
    """Sin las dos claves no hay pago con tarjeta. Sin `FLOW_API_URL`, el sandbox en
    este computador y producción desplegada: así nadie cobra de verdad probando."""
    clave = os.environ.get("FLOW_API_KEY", "").strip()
    secreto = os.environ.get("FLOW_SECRET_KEY", "").strip()
    if not clave or not secreto:
        return None
    url = os.environ.get("FLOW_API_URL", "").strip() or (SANDBOX if local else PRODUCCION)
    partes = urllib.parse.urlparse(url)
    if partes.scheme != "https" and partes.hostname not in ("localhost", "127.0.0.1"):
        raise ValueError("FLOW_API_URL tiene que ser https")
    return Flow(url, clave, secreto)


def crear_planes(flow: Flow, url_consola: str, avisar=print) -> None:
    """Crea en Flow los planes que falten, con los precios de `consola/planes.py`.

    Los que ya existen no se tocan: Flow no deja cambiar el monto de un plan con
    suscripciones, y pisarlo a ciegas cambiaría lo que paga alguien a mitad de mes.
    """
    from .planes import PLANES
    aviso = f"{url_consola.rstrip('/')}/api/flow/pago"
    for clave, plan_id in ID_EN_FLOW.items():
        plan = PLANES[clave]
        if flow.plan(plan_id):
            avisar(f"= {plan_id}: ya existe, no se toca")
            continue
        flow.crear_plan(plan_id, nombre=f"Tu Masterplan {plan.nombre}",
                        monto=plan.precio_mensual, url_aviso=aviso)
        avisar(f"+ {plan_id}: ${plan.precio_mensual:,} al mes, avisos a {aviso}".replace(",", "."))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="python -m consola.flow",
                                     description="Deja listos los planes en Flow.")
    sub = parser.add_subparsers(dest="orden", required=True)
    planes = sub.add_parser("planes", help="crea en Flow los planes Fly, Pro y Master")
    planes.add_argument("--url-consola", required=True,
                        help="p. ej. https://consola.tumasterplan.cl (adonde Flow avisa los pagos)")
    argumentos = parser.parse_args(argv)
    flow = flow_del_entorno(local=os.environ.get("CONSOLA_ENTORNO", "local") == "local")
    if flow is None:
        parser.error("faltan FLOW_API_KEY y FLOW_SECRET_KEY")
    print(f"Flow: {flow.url}")
    crear_planes(flow, argumentos.url_consola)


if __name__ == "__main__":
    main()
