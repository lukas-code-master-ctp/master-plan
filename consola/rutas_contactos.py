"""Las rutas del formulario de contacto de la landing.

Una es pública y la llama la landing (tumasterplan.cl), desde otro dominio, con un
formulario HTML común: la landing funciona sin JavaScript y el formulario también.
Por eso no contesta JSON sino una redirección de vuelta a la landing, a
`#contacto-enviado` o `#contacto-error`, que la landing muestra con `:target`.

Sin sesión, se cuida sola, como las reservas:
- solo acepta la landing como origen (y localhost en el computador);
- vuelve siempre a la landing, nunca a una dirección que traiga la petición;
- tiene tope por IP y de tamaño;
- un campo trampa para robots;
- y cada campo se revisa antes de guardar (`consola/contactos.py`).

Las otras dos son del equipo de CTP: ver los mensajes y marcarlos atendidos.
"""
from __future__ import annotations

import os
from urllib.parse import parse_qsl

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .contactos import ESTADOS, ContactoInvalido, Contactos, leer_contacto
from .cuentas import Limitador
from .datos import NoEncontrado
from .rutas_cuentas import ip_de
from .rutas_reservas import LOCALHOST

PUBLICAS = ("/api/publico/contacto",)

LANDING = "https://www.tumasterplan.cl"
ORIGENES_DE_LA_LANDING = (LANDING, "https://tumasterplan.cl")

# El mensaje llega a 2.000 caracteres; con eñes y tildes codificadas en el
# formulario son varias veces eso. 16 KB sobra, y sin tope un cuerpo enorme se
# leería entero en la memoria de la única instancia.
CUERPO_MAXIMO = 16_384


def rutas_de_contactos(contactos: Contactos, solo_plataforma, *, local: bool,
                       envios_por_ip: Limitador | None = None) -> APIRouter:
    rutas = APIRouter()
    # Como pedir una reserva: pocos por hora. Una persona escribe una vez.
    envios_por_ip = envios_por_ip or Limitador(maximo=5, segundos=3600)

    def origen_valido(origen: str) -> bool:
        return origen in ORIGENES_DE_LA_LANDING or (local and bool(LOCALHOST.fullmatch(origen)))

    def volver(origen: str, enviado: bool) -> RedirectResponse:
        # A la landing de donde vino, si es una de las nuestras; si no, a la de siempre.
        destino = origen if origen_valido(origen) else LANDING
        ancla = "contacto-enviado" if enviado else "contacto-error"
        return RedirectResponse(f"{destino}/#{ancla}", status_code=303)

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

    def url_de_la_consola(peticion: Request) -> str:
        return os.environ.get("CONSOLA_URL", "").strip() or (str(peticion.base_url) if local else "")

    @rutas.post("/api/publico/contacto")
    async def recibir(peticion: Request):
        origen = peticion.headers.get("origin", "")
        # Un navegador siempre manda el origen al enviar un formulario a otro
        # dominio. Si viene y no es la landing, es otro sitio usando este formulario.
        if origen and not origen_valido(origen):
            return JSONResponse(status_code=403, content={"detail": "El formulario es el de tumasterplan.cl."})
        if not envios_por_ip.permitir(ip_de(peticion, local)):
            return volver(origen, enviado=False)
        cuerpo = await leer_cuerpo(peticion)
        if cuerpo is None:
            return volver(origen, enviado=False)
        campos = dict(parse_qsl(cuerpo.decode("utf-8", errors="replace"), keep_blank_values=True))
        # El campo trampa: una persona no lo ve, un robot lo llena. Se le contesta
        # como si hubiera funcionado, para que no aprenda a esquivarlo.
        if campos.get("sitio"):
            return volver(origen, enviado=True)
        try:
            datos = leer_contacto(campos)
        except ContactoInvalido:
            return volver(origen, enviado=False)
        contactos.guardar(datos, url_de_la_consola(peticion))
        return volver(origen, enviado=True)

    # --- en la consola, solo el equipo de CTP -------------------------------------------

    @rutas.get("/api/plataforma/contactos")
    def listar(_=Depends(solo_plataforma)) -> list[dict]:
        return [c.como_json() for c in contactos.listar()]

    @rutas.post("/api/plataforma/contactos/{identificador}/estado")
    def marcar(identificador: int, estado: str = Body(..., embed=True), _=Depends(solo_plataforma)) -> dict:
        if estado not in ESTADOS:
            raise HTTPException(400, f"el estado tiene que ser uno de: {', '.join(ESTADOS)}")
        try:
            return contactos.marcar(identificador, estado).como_json()
        except NoEncontrado as error:
            raise HTTPException(404, "ese mensaje no existe") from error

    return rutas
