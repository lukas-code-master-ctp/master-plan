"""Una Cierra de mentira para probar la consola en este computador.

Habla el mismo contrato que lee `consola/cierra.py`: GET /integrations/proyectos y
GET /integrations/parcelas?proyecto_id=1,2, con la clave en `X-API-Key`. Acepta solo
`CLAVE` y contesta 401 a cualquier otra, para que el error de clave se pueda probar.

Los datos son ficticios y calzan con el KMZ sintético de "Praderas Demo": dos etapas
de seis lotes. En Cierra cada etapa es un proyecto y el número va sin etapa; es la
consola la que arma "CIERRA ET1" y "CIERRA ET2" al escribir el inventario.

    python -m qa.cierra_falsa --puerto 8791
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLAVE = "qa-cierra-clave-demo-0001"
HOST = "127.0.0.1"
PUERTO = 8791


def _parcela(proyecto_id, numero, estado, precio, moneda, superficie, servidumbre=None):
    return {"proyecto_id": proyecto_id, "numero": str(numero), "estado": estado,
            "precio": precio, "moneda": moneda, "superficie_m2": superficie,
            "servidumbre_m2": servidumbre}


# Los cuatro estados, precios en pesos y algunos en UF, superficies cerca de media hectárea.
PARCELAS = [
    _parcela(1, 1, "disponible", 24_900_000, "CLP", 5000),
    _parcela(1, 2, "disponible", 25_500_000, "CLP", 5120.5),
    _parcela(1, 3, "reservado", 24_900_000, "CLP", 5000, 312.25),
    _parcela(1, 4, "vendido", 26_000_000, "CLP", 5340),
    _parcela(1, 5, "no_disponible", None, "CLP", 5000),
    _parcela(1, 6, "disponible", 27_900_000, "CLP", 5610, 480),
    _parcela(2, 1, "disponible", 690, "UF", 5000),
    _parcela(2, 2, "reservado", 705.5, "UF", 5080),
    _parcela(2, 3, "disponible", 29_900_000, "CLP", 5250),
    _parcela(2, 4, "vendido", 720, "UF", 5400, 150.75),
    _parcela(2, 5, "disponible", 31_500_000, "CLP", 5900),
    _parcela(2, 6, "no_disponible", None, "CLP", 5000),
]

NOMBRES = {1: "Praderas Demo Etapa 1", 2: "Praderas Demo Etapa 2"}


def _proyectos() -> list[dict]:
    """Los totales salen de las parcelas: así no pueden quedar descuadrados."""
    return [{"id": id_, "nombre": nombre,
             "parcelas_total": sum(p["proyecto_id"] == id_ for p in PARCELAS),
             "parcelas_disponibles": sum(p["proyecto_id"] == id_ and p["estado"] == "disponible"
                                         for p in PARCELAS)}
            for id_, nombre in NOMBRES.items()]


class _Atencion(BaseHTTPRequestHandler):
    server_version = "CierraFalsa/1"

    def do_GET(self):
        partes = urllib.parse.urlsplit(self.path)
        if self.headers.get("X-API-Key") != CLAVE:
            return self._contestar(401, {"error": "clave de API inválida"})
        if partes.path == "/integrations/proyectos":
            return self._contestar(200, {"proyectos": _proyectos()})
        if partes.path == "/integrations/parcelas":
            return self._parcelas(urllib.parse.parse_qs(partes.query))
        return self._contestar(404, {"error": "no existe"})

    def _parcelas(self, consulta: dict):
        texto = ",".join(consulta.get("proyecto_id", []))
        try:
            ids = [int(i) for i in texto.split(",") if i.strip()]
        except ValueError:
            return self._contestar(400, {"error": "proyecto_id tiene que ser números"})
        if not ids:
            return self._contestar(400, {"error": "falta proyecto_id"})
        desconocidos = [i for i in ids if i not in NOMBRES]
        if desconocidos:
            return self._contestar(404, {"error": f"proyecto {desconocidos[0]} no existe"})
        return self._contestar(200, {"parcelas": [dict(p, proyecto=NOMBRES[p["proyecto_id"]])
                                                   for p in PARCELAS if p["proyecto_id"] in ids]})

    def _contestar(self, estado: int, cuerpo: dict):
        datos = json.dumps(cuerpo, ensure_ascii=False).encode("utf-8")
        self.send_response(estado)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        self.wfile.write(datos)

    def log_request(self, codigo="-", tamano="-"):
        # Una línea corta por petición, sin la consulta: basta para seguir qué pidió la consola.
        # Una petición mal formada se contesta antes de tener ruta: de ahí el getattr.
        ruta = getattr(self, "path", "").split("?")[0]
        self.log_message("%s %s %s", self.command or "", ruta, getattr(codigo, "value", codigo))

    def log_message(self, formato, *argumentos):
        sys.stderr.write(f"cierra falsa: {formato % argumentos}\n")


class _Silenciosa(_Atencion):
    def log_message(self, formato, *argumentos):
        pass


def servir(puerto: int = 0, host: str = HOST, silencio: bool = True):
    """La levanta en un hilo y devuelve `(servidor, url)`; `servidor.shutdown()` la baja.

    Con puerto 0 el sistema elige uno libre, que es lo que quieren las pruebas.
    """
    servidor = ThreadingHTTPServer((host, puerto), _Silenciosa if silencio else _Atencion)
    servidor.daemon_threads = True
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor, f"http://{host}:{servidor.server_address[1]}"


def main(argumentos: list[str] | None = None) -> None:
    lector = argparse.ArgumentParser(description="Cierra de mentira para la QA local.")
    lector.add_argument("--puerto", type=int, default=PUERTO)
    lector.add_argument("--host", default=HOST)
    opciones = lector.parse_args(argumentos)
    servidor = ThreadingHTTPServer((opciones.host, opciones.puerto), _Atencion)
    servidor.daemon_threads = True
    # Con --puerto 0 el sistema elige uno: se muestra el que quedó, no el pedido.
    print(f"Cierra falsa en http://{opciones.host}:{servidor.server_address[1]} (clave {CLAVE})",
          flush=True)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
