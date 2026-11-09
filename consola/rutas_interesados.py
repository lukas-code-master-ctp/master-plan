"""Las rutas de los interesados y de las estadísticas de un loteo.

Dos son públicas y las llama el sitio publicado, desde otro dominio, igual que las
de reservas (`consola/rutas_reservas.py`): dejar un "Me interesa" y mandar las
cifras de lo que pasa en el sitio. Sin sesión se cuidan solas: solo aceptan el
origen del sitio de ese loteo, tienen tope por IP y revisan lo que llega.

Las otras son de la consola, con sesión: la loteadora ve y sigue a los interesados
de sus loteos y mira sus cifras. Las de otra loteadora le contestan 404.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import Response

from .cuentas import Limitador
from .datos import NoEncontrado
from .estadisticas import DIAS_POSIBLES, Estadisticas, EventoInvalido, leer_eventos
from .interesados import Interesados, leer_datos
from .proyectos import Proyecto, Registro, Vista
from .reservas import SolicitudInvalida
from .rutas_cuentas import ip_de
from .rutas_reservas import (
    leer_cuerpo, leer_json, loteo_publicado, origen_valido, respuesta, url_de_la_consola,
)

PUBLICAS = ("/api/publico/interesados", "/api/publico/eventos")


def rutas_de_interesados(interesados: Interesados, estadisticas: Estadisticas, registro: Registro,
                         vista, *, local: bool, interesados_por_ip: Limitador | None = None,
                         eventos_por_ip: Limitador | None = None) -> APIRouter:
    rutas = APIRouter()
    # Dejar los datos, como pedir una reserva: pocas veces por hora. Los eventos los
    # manda cada visita mientras mira, así que el tope es por minuto y holgado.
    interesados_por_ip = interesados_por_ip or Limitador(maximo=5, segundos=3600)
    eventos_por_ip = eventos_por_ip or Limitador(maximo=60, segundos=60)

    async def del_sitio(peticion: Request) -> tuple[dict, Proyecto, str] | Response:
        """El cuerpo, el loteo y el origen; o la respuesta de error si algo no calza.
        Hasta saber que el origen es el sitio del loteo, los errores salen sin
        permiso para leerlos desde otro dominio."""
        origen = peticion.headers.get("origin", "")
        cuerpo = await leer_cuerpo(peticion)
        if cuerpo is None:
            return respuesta(413, {"detail": "El pedido es demasiado grande."})
        datos = leer_json(cuerpo)
        if datos is None:
            return respuesta(400, {"detail": "El pedido llegó incompleto."})
        try:
            proyecto = loteo_publicado(registro, str(datos.get("loteo") or "")[:80])
        except NoEncontrado:
            return respuesta(404, {"detail": "Este loteo no está publicado."})
        if not origen_valido(origen, proyecto, local):
            return respuesta(403, {"detail": "El pedido tiene que venir del sitio del loteo."})
        return datos, proyecto, origen

    @rutas.post("/api/publico/interesados")
    async def me_interesa(peticion: Request) -> Response:
        if not interesados_por_ip.permitir(ip_de(peticion, local)):
            return respuesta(429, {"detail": "Demasiados envíos seguidos."})
        leido = await del_sitio(peticion)
        if isinstance(leido, Response):
            return leido
        datos, proyecto, origen = leido
        parcela = str(datos.get("parcela") or "")[:40]
        # El campo trampa: se le contesta como si hubiera funcionado.
        if datos.get("sitio"):
            return respuesta(201, {"ok": True}, origen)
        try:
            interesados.registrar(proyecto, parcela, leer_datos(datos), url_de_la_consola(peticion, local))
        except SolicitudInvalida as error:
            return respuesta(400, {"detail": str(error)}, origen)
        except NoEncontrado:
            return respuesta(404, {"detail": "Esa parcela no existe en este loteo."}, origen)
        return respuesta(201, {"ok": True}, origen)

    @rutas.post("/api/publico/eventos")
    async def eventos(peticion: Request) -> Response:
        """Lo que pasó en el sitio. Contesta 204 aunque descarte eventos: el visor no
        espera la respuesta y no hay nada que decirle."""
        if not eventos_por_ip.permitir(ip_de(peticion, local)):
            return respuesta(429, {"detail": "Demasiados eventos."})
        leido = await del_sitio(peticion)
        if isinstance(leido, Response):
            return leido
        datos, proyecto, origen = leido
        try:
            lista = leer_eventos(datos, set(estadisticas.parcelas_del_sitio(proyecto)))
        except EventoInvalido:
            return respuesta(400, {"detail": "Los eventos llegaron mal."}, origen)
        estadisticas.sumar(proyecto, lista)
        return respuesta(204, None, origen)

    # --- en la consola, con sesión ------------------------------------------------------

    @rutas.get("/api/interesados")
    def de_todos(mios: Vista = Depends(vista)) -> list[dict]:
        """La bandeja entera, con el loteo de cada uno: un pedido en vez de uno por loteo."""
        return [{**i.como_json(), "slug": slug, "loteo": nombre}
                for i, slug, nombre in interesados.de_todos(mios.filtro)]

    @rutas.get("/api/proyectos/{slug}/interesados")
    def del_loteo(slug: str, mios: Vista = Depends(vista)) -> list[dict]:
        return [i.como_json() for i in interesados.del_loteo(mios.ver(slug))]

    @rutas.patch("/api/proyectos/{slug}/interesados/{identificador}")
    def seguir(slug: str, identificador: int, peticion: Request, cambios: dict = Body(...),
               mios: Vista = Depends(vista)) -> dict:
        """Estado, responsable o nota de un interesado."""
        proyecto = mios.ver(slug)
        try:
            interesado = interesados.actualizar(proyecto, identificador, cambios)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        if "estado" in cambios:
            registro.base.anotar(f"interesado: {interesado.estado}", cliente_id=proyecto.cliente_id,
                                 usuario_id=peticion.state.sesion.usuario_id,
                                 detalle=f"Parcela {interesado.parcela} · {proyecto.nombre}")
        return interesado.como_json()

    @rutas.get("/api/proyectos/{slug}/estadisticas")
    def cifras(slug: str, dias: int = 30, mios: Vista = Depends(vista)) -> dict:
        proyecto = mios.ver(slug)
        if dias not in DIAS_POSIBLES:
            raise HTTPException(400, f"dias tiene que ser uno de {DIAS_POSIBLES}")
        return estadisticas.resumen(proyecto, dias,
                                    lambda desde: interesados.por_parcela(proyecto, desde))

    return rutas
