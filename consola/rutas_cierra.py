"""Las rutas de "Conectar con Cierra", todas colgando de un loteo.

La clave es de la loteadora dueña del loteo, no de quien pide: así el equipo de CTP
puede dejar conectado el loteo de un cliente con la clave de ese cliente. Un loteo
ajeno da 404 como en el resto de la consola, porque todo pasa por `Vista.ver`.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Response
from fastapi.concurrency import run_in_threadpool

from .cierra import (
    Cierra,
    CierraNoResponde,
    ClaveRechazada,
    Conexiones,
    EleccionInvalida,
    etapa_sugerida,
    limpiar_clave,
    revisar_eleccion,
    sincronizar,
)
from .proyectos import Proyecto, Vista

SIN_CLAVE = ("La clave de Cierra de esta loteadora no está, o ya no se puede leer. "
             "Pégala de nuevo.")


def rutas_de_cierra(cierra: Cierra | None, conexiones: Conexiones | None, vista,
                    ocupado=lambda slug: False) -> APIRouter:
    """`ocupado(slug)`: si ese loteo tiene una construcción o publicación en curso."""
    rutas = APIRouter()

    def configurado() -> tuple[Cierra, Conexiones]:
        if cierra is None or conexiones is None:
            raise HTTPException(404, "la conexión con Cierra no está configurada")
        return cierra, conexiones

    def clave_de(proyecto: Proyecto) -> str:
        _, guardadas = configurado()
        clave = guardadas.clave(proyecto.cliente_id)
        if not clave:
            raise HTTPException(409, SIN_CLAVE)
        return clave

    @rutas.get("/api/proyectos/{slug}/cierra")
    def estado(slug: str, mios: Vista = Depends(vista)) -> dict:
        proyecto = mios.ver(slug)
        if cierra is None or conexiones is None:
            return {"disponible": False}
        conexion = conexiones.del_loteo(proyecto.slug)
        return {
            "disponible": True,
            "pista": conexiones.pista(proyecto.cliente_id),
            "conectado": conexion is not None,
            "proyectos": [e.__dict__ for e in conexion.elecciones] if conexion else [],
            "sincronizado_en": (conexion.sincronizado_en.isoformat()
                                if conexion and conexion.sincronizado_en else None),
        }

    @rutas.put("/api/proyectos/{slug}/cierra/clave")
    async def guardar_clave(slug: str, campos: dict = Body(...), mios: Vista = Depends(vista)) -> dict:
        api, guardadas = configurado()
        proyecto = mios.ver(slug)
        try:
            clave = limpiar_clave(campos.get("clave"))
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        # Se prueba antes de guardarla: una clave que Cierra no acepta, guardada,
        # solo aparece como error el día que alguien construye.
        await _pedir(api.proyectos, clave)
        return {"pista": guardadas.guardar_clave(proyecto.cliente_id, clave)}

    @rutas.delete("/api/proyectos/{slug}/cierra/clave", status_code=204)
    def olvidar_clave(slug: str, mios: Vista = Depends(vista)) -> Response:
        _, guardadas = configurado()
        guardadas.olvidar_clave(mios.ver(slug).cliente_id)
        return Response(status_code=204)

    @rutas.get("/api/proyectos/{slug}/cierra/opciones")
    async def opciones(slug: str, mios: Vista = Depends(vista)) -> dict:
        api, _ = configurado()
        clave = clave_de(mios.ver(slug))
        disponibles = await _pedir(api.proyectos, clave)
        return {"proyectos": [{**p.__dict__, "etapa_sugerida": etapa_sugerida(p.nombre)}
                              for p in disponibles]}

    @rutas.put("/api/proyectos/{slug}/cierra")
    async def conectar(slug: str, campos: dict = Body(...), mios: Vista = Depends(vista)) -> dict:
        api, guardadas = configurado()
        proyecto = mios.ver(slug)
        clave = clave_de(proyecto)
        pedidas = campos.get("proyectos")
        if not isinstance(pedidas, list):
            raise HTTPException(400, "Elige al menos un proyecto de Cierra.")
        try:
            elecciones = revisar_eleccion(pedidas, await _pedir(api.proyectos, clave))
        except EleccionInvalida as error:
            raise HTTPException(400, str(error)) from error
        if ocupado(proyecto.slug):
            raise HTTPException(409, "espera a que termine la construcción en curso")
        guardadas.conectar_loteo(proyecto.slug, elecciones)
        return await _traer(api, guardadas, proyecto, clave)

    @rutas.post("/api/proyectos/{slug}/cierra/actualizar")
    async def actualizar(slug: str, mios: Vista = Depends(vista)) -> dict:
        api, guardadas = configurado()
        proyecto = mios.ver(slug)
        if guardadas.del_loteo(proyecto.slug) is None:
            raise HTTPException(409, "este loteo no está conectado con Cierra")
        if ocupado(proyecto.slug):
            raise HTTPException(409, "espera a que termine la construcción en curso")
        return await _traer(api, guardadas, proyecto, clave_de(proyecto))

    @rutas.delete("/api/proyectos/{slug}/cierra", status_code=204)
    def desconectar(slug: str, mios: Vista = Depends(vista)) -> Response:
        """El último inventario que llegó se queda: desconectar no borra precios."""
        _, guardadas = configurado()
        guardadas.desconectar_loteo(mios.ver(slug).slug)
        return Response(status_code=204)

    return rutas


async def _traer(api: Cierra, guardadas: Conexiones, proyecto: Proyecto, clave: str) -> dict:
    conexion = guardadas.del_loteo(proyecto.slug)
    cuantas = await _pedir(sincronizar, api, clave, conexion, proyecto.fuentes)
    momento = guardadas.anotar_sincronizacion(proyecto.slug)
    return {"parcelas": cuantas, "sincronizado_en": momento.isoformat()}


async def _pedir(funcion, *argumentos):
    """Una llamada a Cierra, fuera del bucle de eventos y con errores de la consola."""
    try:
        return await run_in_threadpool(funcion, *argumentos)
    except ClaveRechazada as error:
        raise HTTPException(400, "Cierra no aceptó esa clave. Revisa que esté activa y "
                                 "que tenga el permiso parcelas:read.") from error
    except CierraNoResponde as error:
        raise HTTPException(502, str(error)) from error


def sincronizar_antes_de_construir(cierra: Cierra | None, conexiones: Conexiones | None,
                                   proyecto: Proyecto) -> str | None:
    """Al construir, un loteo conectado trae lo último de Cierra.

    Si Cierra no contesta se construye igual con el último inventario que llegó, y se
    avisa: frenar la construcción porque otro sistema está caído sería peor.
    """
    if cierra is None or conexiones is None:
        return None
    conexion = conexiones.del_loteo(proyecto.slug)
    if conexion is None:
        return None
    clave = conexiones.clave(proyecto.cliente_id)
    if not clave:
        return SIN_CLAVE
    try:
        sincronizar(cierra, clave, conexion, proyecto.fuentes)
    except ClaveRechazada:
        return "Cierra no aceptó la clave: se construye con el último inventario que llegó."
    except CierraNoResponde:
        return "Cierra no contestó: se construye con el último inventario que llegó."
    conexiones.anotar_sincronizacion(proyecto.slug)
    return None


__all__ = ["rutas_de_cierra", "sincronizar_antes_de_construir"]
