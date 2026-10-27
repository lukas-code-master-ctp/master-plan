"""Un Flow de mentira para probar el pago con tarjeta sin cobrar nada.

Habla el contrato que usa `consola/flow.py`: la firma `s` (HMAC-SHA256 con la
secretKey), customer/create, customer/register, customer/getRegisterStatus,
subscription/create|get|cancel, payment/getStatus y plans/get|create. Una firma mala
da 401, como el de verdad.

Registrar la tarjeta abre una página con dos botones: tarjeta aprobada o
rechazada. La aprobada cobra al tiro el primer mes al suscribir; la rechazada deja
el importe impago. Al cobrar, avisa al `urlCallback` del plan con un token, como
Flow.

Para QA hay además dos atajos sin firma, solo en este falso:
    POST /falsa/cobrar  subscriptionId=…   un mes más pagado (y el aviso)
    POST /falsa/vencer  subscriptionId=…   la suscripción queda morosa

    python -m qa.flow_falsa --puerto 8793
"""
from __future__ import annotations

import argparse
import html
import itertools
import json
import secrets
import threading
import urllib.parse
import urllib.request
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from consola.flow import firmar

CLAVE = "qa-flow-apikey-0001"
SECRETO = "qa-flow-secreto-0001"
HOST = "127.0.0.1"
PUERTO = 8793
PRECIOS = {"tumasterplan-fly": 30000, "tumasterplan-pro": 80000, "tumasterplan-master": 150000}


class Estado:
    """Lo que Flow guarda, en memoria."""

    def __init__(self):
        self.candado = threading.Lock()
        self.numeros = itertools.count(1)
        self.clientes: dict[str, dict] = {}
        self.registros: dict[str, dict] = {}       # token → {customerId, url_return, status}
        self.suscripciones: dict[str, dict] = {}
        self.pagos: dict[str, dict] = {}           # token → PaymentStatus
        # Los tres planes ya creados, con su aviso apuntando a la consola de QA.
        self.planes: dict[str, dict] = {p: {"planId": p, "amount": m, "urlCallback": ""}
                                        for p, m in PRECIOS.items()}
        self.aviso = ""                            # url de avisos si un plan no tiene

    def nuevo(self, prefijo: str) -> str:
        return f"{prefijo}_{next(self.numeros)}"


def _hoy(dias=0) -> str:
    return (date.today() + timedelta(days=dias)).isoformat() + " 00:00:00"


class Falsa:
    def __init__(self, clave=CLAVE, secreto=SECRETO, aviso_consola=""):
        self.clave, self.secreto = clave, secreto
        self.estado = Estado()
        self.estado.aviso = aviso_consola
        self.base_url = ""
        self.avisos_mandados: list[str] = []

    # --- los servicios --------------------------------------------------------------

    def atender(self, servicio: str, p: dict) -> tuple[int, dict]:
        e = self.estado
        with e.candado:
            if servicio == "customer/create":
                cid = e.nuevo("cus")
                e.clientes[cid] = {"customerId": cid, "name": p["name"], "email": p["email"],
                                   "externalId": p["externalId"], "tarjeta": None}
                return 200, e.clientes[cid]
            if servicio == "customer/register":
                if p["customerId"] not in e.clientes:
                    return 401, {"code": 1, "message": "customer not found"}
                token = secrets.token_hex(16).upper()
                e.registros[token] = {"customerId": p["customerId"], "url_return": p["url_return"],
                                      "status": 0}
                return 200, {"url": f"{self.base_url}/registrar", "token": token}
            if servicio == "customer/getRegisterStatus":
                r = e.registros.get(p["token"])
                if not r:
                    return 401, {"code": 2, "message": "token not found"}
                tarjeta = e.clientes[r["customerId"]]["tarjeta"] or {}
                return 200, {"status": r["status"], "customerId": r["customerId"],
                             "creditCardType": tarjeta.get("marca"),
                             "last4CardDigits": tarjeta.get("ultimos")}
            if servicio == "subscription/create":
                cliente = e.clientes.get(p["customerId"])
                plan = e.planes.get(p["planId"])
                if not cliente or not plan:
                    return 401, {"code": 3, "message": "customer or plan not found"}
                sid = e.nuevo("sus")
                e.suscripciones[sid] = {
                    "subscriptionId": sid, "planId": p["planId"], "customerId": p["customerId"],
                    "status": 1, "morose": 0, "cancel_at_period_end": 0, "cancel_at": None,
                    "period_start": _hoy(), "period_end": _hoy(30), "invoices": []}
                self._cobrar(sid)
                return 200, e.suscripciones[sid]
            if servicio == "subscription/get":
                s = e.suscripciones.get(p["subscriptionId"])
                return (200, s) if s else (401, {"code": 4, "message": "subscription not found"})
            if servicio == "subscription/cancel":
                s = e.suscripciones.get(p["subscriptionId"])
                if not s or s["status"] == 4:
                    return 401, {"code": 5, "message": "subscription not active"}
                if str(p.get("at_period_end")) == "1":
                    s.update(cancel_at_period_end=1, cancel_at=s["period_end"])
                else:
                    s.update(status=4, cancel_at=_hoy())
                return 200, s
            if servicio == "payment/getStatus":
                pago = e.pagos.get(p["token"])
                return (200, pago) if pago else (401, {"code": 6, "message": "token not found"})
            if servicio == "plans/get":
                plan = e.planes.get(p["planId"])
                return (200, plan) if plan else (401, {"code": 7, "message": "plan not found"})
            if servicio == "plans/create":
                e.planes[p["planId"]] = {"planId": p["planId"], "amount": int(p["amount"]),
                                         "urlCallback": p.get("urlCallback", "")}
                return 200, e.planes[p["planId"]]
        return 404, {"code": 404, "message": f"no existe {servicio}"}

    def _cobrar(self, sid: str) -> None:
        """Un importe del mes: pagado si la tarjeta está aprobada. Avisa como Flow."""
        e = self.estado
        s = e.suscripciones[sid]
        tarjeta = e.clientes[s["customerId"]]["tarjeta"] or {}
        pagado = bool(tarjeta.get("aprobada"))
        s["invoices"].append({"id": next(e.numeros), "status": 1 if pagado else 0,
                              "amount": e.planes[s["planId"]]["amount"]})
        if not pagado:
            return
        token = secrets.token_hex(16).upper()
        e.pagos[token] = {"flowOrder": next(e.numeros), "status": 2,
                          "amount": e.planes[s["planId"]]["amount"], "subject": s["planId"]}
        aviso = e.planes[s["planId"]].get("urlCallback") or e.aviso
        if aviso:
            threading.Thread(target=self._avisar, args=(aviso, token), daemon=True).start()

    def _avisar(self, url: str, token: str) -> None:
        self.avisos_mandados.append(token)
        try:
            datos = urllib.parse.urlencode({"token": token}).encode()
            urllib.request.urlopen(urllib.request.Request(url, data=datos), timeout=10).read()
        except OSError:
            pass   # Flow reintenta; acá basta con la tarea diaria

    # --- la página de registrar tarjeta (lo que ve el navegador) --------------------

    def registrar(self, token: str, aprobada: bool) -> str:
        """Marca la tarjeta y devuelve adónde vuelve el navegador."""
        e = self.estado
        with e.candado:
            r = e.registros[token]
            r["status"] = 1 if aprobada else 0
            if aprobada:
                e.clientes[r["customerId"]]["tarjeta"] = {"marca": "Visa", "ultimos": "4242",
                                                          "aprobada": True}
            return r["url_return"]

    def vencer(self, sid: str) -> None:
        with self.estado.candado:
            self.estado.suscripciones[sid]["morose"] = 1

    def cobrar_mes(self, sid: str) -> None:
        with self.estado.candado:
            self._cobrar(sid)


def _manejador(falsa: Falsa):
    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *argumentos):
            pass

        def _json(self, codigo: int, cuerpo: dict) -> None:
            datos = json.dumps(cuerpo).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def _html(self, cuerpo: str) -> None:
            datos = cuerpo.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(datos)))
            self.end_headers()
            self.wfile.write(datos)

        def _servicio(self, ruta: str, p: dict) -> None:
            servicio = ruta.removeprefix("/api/").strip("/")
            firma = p.pop("s", "")
            if p.get("apiKey") != falsa.clave or firma != firmar(p, falsa.secreto):
                return self._json(401, {"code": 108, "message": "invalid signature"})
            self._json(*falsa.atender(servicio, p))

        def do_GET(self):
            partes = urllib.parse.urlsplit(self.path)
            p = dict(urllib.parse.parse_qsl(partes.query))
            if partes.path == "/registrar":
                token = html.escape(p.get("token", ""))
                return self._html(f"""<!doctype html><meta charset="utf-8">
<title>Flow falso · Registrar tarjeta</title>
<body style="font-family:system-ui;max-width:28rem;margin:4rem auto">
<h1>Flow (de prueba)</h1><p>Registrar tarjeta para cargos automáticos.</p>
<form method="post" action="/registrar"><input type="hidden" name="token" value="{token}">
<button name="tarjeta" value="aprobada">Usar tarjeta aprobada (Visa 4242)</button>
<button name="tarjeta" value="rechazada">Tarjeta rechazada</button></form>""")
            self._servicio(partes.path, p)

        def do_POST(self):
            largo = int(self.headers.get("Content-Length") or 0)
            p = dict(urllib.parse.parse_qsl(self.rfile.read(largo).decode()))
            if self.path == "/registrar":
                vuelta = falsa.registrar(p["token"], p.get("tarjeta") == "aprobada")
                # Como Flow: el navegador vuelve al comercio con un POST que trae el token.
                return self._html(f"""<!doctype html><meta charset="utf-8"><body onload="document.forms[0].submit()">
<form method="post" action="{html.escape(vuelta)}"><input type="hidden" name="token" value="{html.escape(p['token'])}">
<noscript><button>Volver al comercio</button></noscript></form>""")
            if self.path == "/falsa/cobrar":
                falsa.cobrar_mes(p["subscriptionId"])
                return self._json(200, {"ok": True})
            if self.path == "/falsa/vencer":
                falsa.vencer(p["subscriptionId"])
                return self._json(200, {"ok": True})
            self._servicio(self.path, p)

    return Manejador


def levantar(falsa: Falsa, host=HOST, puerto=0) -> ThreadingHTTPServer:
    """En un hilo; con puerto 0 elige uno libre. Deja `falsa.base_url` lista."""
    servidor = ThreadingHTTPServer((host, puerto), _manejador(falsa))
    falsa.base_url = f"http://{host}:{servidor.server_address[1]}"
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--puerto", type=int, default=PUERTO)
    parser.add_argument("--aviso", default="", help="url de avisos de pago de la consola")
    argumentos = parser.parse_args()
    falsa = Falsa(aviso_consola=argumentos.aviso)
    servidor = ThreadingHTTPServer((HOST, argumentos.puerto), _manejador(falsa))
    falsa.base_url = f"http://{HOST}:{argumentos.puerto}"
    print(f"Flow falso en {falsa.base_url}/api (apiKey {CLAVE})", flush=True)
    servidor.serve_forever()


if __name__ == "__main__":
    main()
