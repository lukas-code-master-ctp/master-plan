"""Las rutas de las solicitudes de reserva.

Dos son públicas y las llama el sitio publicado de un loteo, desde otro dominio:
pedir una reserva y saber qué parcelas están apartadas. No tienen sesión, así que
se cuidan solas:
- solo aceptan el origen del sitio de ese loteo;
- tienen tope por IP;
- y los datos del comprador se revisan antes de guardar nada.

El visor manda el cuerpo como texto plano a propósito: así el navegador no pide
permiso antes con un OPTIONS, que no sabría de qué loteo es.

Las otras tres son de la consola, con sesión: la loteadora ve y resuelve las
solicitudes de sus loteos, y las de otra loteadora le contestan 404.
"""
from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .cuentas import Limitador
from .datos import NoEncontrado
from .proyectos import Proyecto, Registro, Vista
from .reservas import (
    CONFIRMADA, LIBERADA, NoSePuedeApartar, Reservas, SolicitudInvalida, leer_comprador,
    link_con_parcela,
)
from .rutas_cuentas import ip_de

PUBLICAS = ("/api/publico/reservas", "/api/publico/apartadas")

# Una solicitud son cinco campos cortos: 4 KB sobra. Sin tope, un cuerpo de cientos
# de megas se leería entero en la memoria de la única instancia.
CUERPO_MAXIMO = 4096

LOCALHOST = re.compile(r"https?://(localhost|127\.0\.0\.1|\[::1\]|[\w.-]+\.localhost)(:\d+)?")


def rutas_de_reservas(reservas: Reservas, registro: Registro, vista, *, local: bool,
                      solicitudes_por_ip: Limitador | None = None,
                      consultas_por_ip: Limitador | None = None) -> APIRouter:
    rutas = APIRouter()
    # Pedir reservas, como registrarse: pocas por hora. Consultar las apartadas lo
    # hace cada visita al sitio, así que el tope es por minuto y holgado.
    solicitudes_por_ip = solicitudes_por_ip or Limitador(maximo=5, segundos=3600)
    consultas_por_ip = consultas_por_ip or Limitador(maximo=120, segundos=60)

    def publicado(slug: str) -> Proyecto:
        # Sin sesión no hay `registro.para`: el loteo se busca entre todos, y solo
        # vale si está publicado, que es cuando su sitio puede estar pidiendo.
        proyecto = registro.todos().ver(str(slug or ""))
        if not proyecto.publicado:
            raise NoEncontrado(f"el loteo {slug} no está publicado")
        return proyecto

    def origen_valido(origen: str, proyecto: Proyecto) -> bool:
        validos = set()
        if proyecto.url_publicada:
            partes = urlsplit(proyecto.url_publicada)
            validos.add(f"{partes.scheme}://{partes.netloc}")
        if proyecto.vercel_proyecto:
            validos.add(f"https://{proyecto.vercel_proyecto}.vercel.app")
        return origen in validos or (local and bool(LOCALHOST.fullmatch(origen)))

    async def leer_cuerpo(peticion: Request) -> bytes | None:
        """El cuerpo, si no pasa del tope. Se lee por partes: Content-Length puede faltar o mentir."""
        if int(peticion.headers.get("content-length") or 0) > CUERPO_MAXIMO:
            return None
        cuerpo = b""
        async for parte in peticion.stream():
            cuerpo += parte
            if len(cuerpo) > CUERPO_MAXIMO:
                return None
        return cuerpo

    def respuesta(estado: int, contenido, origen: str | None = None) -> JSONResponse:
        encabezados = {"Vary": "Origin"}
        if origen:
            encabezados["Access-Control-Allow-Origin"] = origen
        return JSONResponse(status_code=estado, content=contenido, headers=encabezados)

    def url_de_la_consola(peticion: Request) -> str:
        return os.environ.get("CONSOLA_URL", "").strip() or (str(peticion.base_url) if local else "")

    @rutas.post("/api/publico/reservas")
    async def pedir_reserva(peticion: Request) -> JSONResponse:
        # Hasta saber de qué loteo es y que el origen es su sitio, los errores salen
        # sin permiso para leerlos desde otro dominio: el visor muestra uno genérico.
        origen = peticion.headers.get("origin", "")
        if not solicitudes_por_ip.permitir(ip_de(peticion, local)):
            return respuesta(429, {"detail": "Demasiadas solicitudes seguidas."})
        cuerpo = await leer_cuerpo(peticion)
        if cuerpo is None:
            return respuesta(413, {"detail": "La solicitud es demasiado grande."})
        try:
            datos = json.loads(cuerpo or b"{}")
            if not isinstance(datos, dict):
                raise ValueError
        except ValueError:
            return respuesta(400, {"detail": "La solicitud llegó incompleta."})
        try:
            proyecto = publicado(str(datos.get("loteo") or "")[:80])
        except NoEncontrado:
            return respuesta(404, {"detail": "Este loteo no recibe reservas."})
        if not origen_valido(origen, proyecto):
            return respuesta(403, {"detail": "La solicitud tiene que venir del sitio del loteo."})
        parcela = str(datos.get("parcela") or "")[:40]
        # El campo trampa: una persona no lo ve, un robot lo llena. Se le contesta
        # como si hubiera funcionado, para que no aprenda a esquivarlo.
        if datos.get("sitio"):
            return respuesta(201, {"link": link_con_parcela(proyecto.link_reserva, parcela),
                                   "apartada_hasta": None}, origen)
        try:
            comprador = leer_comprador(datos)
            solicitud = reservas.solicitar(proyecto, parcela, comprador, url_de_la_consola(peticion))
        except SolicitudInvalida as error:
            return respuesta(400, {"detail": str(error)}, origen)
        except NoEncontrado:
            return respuesta(404, {"detail": "Esa parcela no existe en este loteo."}, origen)
        except NoSePuedeApartar as error:
            return respuesta(409, {"detail": str(error)}, origen)
        return respuesta(201, {"link": link_con_parcela(proyecto.link_reserva, parcela),
                               "apartada_hasta": solicitud.vence_en.isoformat()}, origen)

    @rutas.get("/api/publico/apartadas")
    def apartadas(loteo: str, peticion: Request) -> JSONResponse:
        """Qué parcelas pinta el visor como "Reserva en proceso". Sin datos de nadie."""
        origen = peticion.headers.get("origin", "")
        if not consultas_por_ip.permitir(ip_de(peticion, local)):
            return respuesta(429, {"detail": "Demasiadas consultas."})
        try:
            proyecto = publicado(loteo[:80])
        except NoEncontrado:
            return respuesta(404, {"detail": "Este loteo no está publicado."})
        if origen and not origen_valido(origen, proyecto):
            return respuesta(403, {"detail": "Solo para el sitio del loteo."})
        hasta = reservas.apartadas(proyecto)
        return respuesta(200, {parcela: (momento.isoformat() if momento else None)
                               for parcela, momento in hasta.items()}, origen or None)

    # --- en la consola, con sesión ------------------------------------------------------

    @rutas.get("/api/proyectos/{slug}/reservas")
    def solicitudes(slug: str, mios: Vista = Depends(vista)) -> list[dict]:
        proyecto = mios.ver(slug)
        ahora = reservas.ahora()
        return [s.como_json(ahora) for s in reservas.del_loteo(proyecto)]

    @rutas.post("/api/proyectos/{slug}/reservas/{identificador}/confirmar")
    def confirmar(slug: str, identificador: int, mios: Vista = Depends(vista)) -> dict:
        """Se vio el pago: la parcela queda apartada hasta que el inventario la marque."""
        proyecto = mios.ver(slug)
        try:
            return reservas.resolver(proyecto, identificador, CONFIRMADA).como_json(reservas.ahora())
        except NoSePuedeApartar as error:
            raise HTTPException(409, str(error)) from error

    @rutas.post("/api/proyectos/{slug}/reservas/{identificador}/liberar")
    def liberar(slug: str, identificador: int, mios: Vista = Depends(vista)) -> dict:
        """No hubo pago (o se arrepintió): la parcela vuelve a estar disponible."""
        proyecto = mios.ver(slug)
        return reservas.resolver(proyecto, identificador, LIBERADA).como_json(reservas.ahora())

    return rutas
