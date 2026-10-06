"""Estados y precios al día sin reconstruir, y la revisión periódica de Cierra.

`poner_al_dia` reescribe solo los datos comerciales de un loteo construido
(`pipeline.inventario`): segundos, en vez de la construcción entera. Si el
inventario trae una parcela que el sitio no tiene, lo dice y no toca nada.

`revisar_cierra` es lo que corre cada 15 minutos (Cloud Scheduler llama a
`POST /api/tareas/cierra`): a cada loteo conectado y publicado le trae lo de
Cierra y, solo si algo cambió, lo vuelve a publicar. No reconstruye nunca por su
cuenta: un lote que no está en el plano seguiría ahí en la próxima vuelta, y
reconstruir cada 15 minutos sería quemar la máquina para nada.
"""
from __future__ import annotations

import io
import logging
import os
from contextlib import redirect_stdout
from dataclasses import dataclass, replace

from pipeline import config
from pipeline import inventario as pipeline_inventario
from pipeline.inventario import Resultado

from .cierra import Cierra, CierraNoResponde, ClaveRechazada, Conexiones, sincronizar
from .proyectos import Proyecto, Vista

registro = logging.getLogger("consola.inventario")


def poner_al_dia(proyecto: Proyecto) -> Resultado:
    """Los estados y precios del inventario, sobre el sitio ya construido."""
    if not proyecto.construido:
        raise ValueError("todavía no está construido")
    try:
        fuentes = config.descubrir_fuentes(proyecto.fuentes, crm=proyecto.crm,
                                           sin_crm=proyecto.crm is None)
    except FileNotFoundError as error:
        raise ValueError(str(error)) from error
    datos = config.cargar_proyecto(proyecto.fuentes)
    # El pipeline dice lo que hace por pantalla; acá no hay nadie mirando.
    with redirect_stdout(io.StringIO()):
        return pipeline_inventario.actualizar(fuentes, datos, proyecto.salida)


def poner_datos_del_loteo(proyecto: Proyecto) -> None:
    """El nombre, la etapa, el WhatsApp y la reserva de la consola, en el sitio construido.

    Se llama justo antes de publicar, como el diseño: cambiar el número de
    contacto no obliga a reconstruir, que tarda y vuelve a bajar el relieve.
    """
    if proyecto.construido:
        # El slug lo emite la consola: el de proyecto.json podría no estar en una carpeta vinculada.
        datos = replace(config.cargar_proyecto(proyecto.fuentes), slug_guardado=proyecto.slug)
        # La dirección de la consola es adonde el sitio publicado manda las reservas.
        # Sin CONSOLA_URL queda vacía y el visor va directo al link de pago, como antes.
        pipeline_inventario.poner_datos_del_loteo(datos, proyecto.salida,
                                                  consola=os.environ.get("CONSOLA_URL", "").strip())


@dataclass(frozen=True)
class Revision:
    slug: str
    resultado: str          # "sin cambios" | "publicando" | "al día (sin publicar)" | lo que falló
    cambiadas: int = 0


def revisar_cierra(todos: Vista, cierra: Cierra, conexiones: Conexiones, ocupado,
                   publicar_en_linea) -> list[Revision]:
    """Una vuelta por los loteos conectados a Cierra. `publicar_en_linea(proyecto)`
    lanza la publicación y devuelve el id del trabajo."""
    revisiones = []
    for slug in conexiones.loteos_conectados():
        revisiones.append(_revisar(todos, cierra, conexiones, ocupado, publicar_en_linea, slug))
    for revision in revisiones:
        registro.info("[cierra] %s: %s", revision.slug, revision.resultado)
    return revisiones


def _revisar(todos, cierra, conexiones, ocupado, publicar_en_linea, slug) -> Revision:
    proyecto = todos.ver(slug)
    if not proyecto.construido:
        return Revision(slug, "sin construir")
    if ocupado(slug):
        return Revision(slug, "ocupado: se revisa en la próxima vuelta")
    clave = conexiones.clave(proyecto.cliente_id)
    conexion = conexiones.del_loteo(slug)
    if not clave or conexion is None:
        return Revision(slug, "sin clave de Cierra")
    try:
        sincronizar(cierra, clave, conexion, proyecto.fuentes)
    except (ClaveRechazada, CierraNoResponde) as error:
        return Revision(slug, f"Cierra: {error}")
    conexiones.anotar_sincronizacion(slug)
    try:
        resultado = poner_al_dia(proyecto)
    except ValueError as error:
        return Revision(slug, f"inventario: {error}")
    if resultado.requiere_reconstruir:
        return Revision(slug, f"hay que reconstruir: {', '.join(resultado.faltan[:10])}")
    if not resultado.cambiadas:
        return Revision(slug, "sin cambios")
    if proyecto.publicado and proyecto.pagado:
        publicar_en_linea(proyecto)
        return Revision(slug, "publicando", len(resultado.cambiadas))
    return Revision(slug, "al día (sin publicar)", len(resultado.cambiadas))


__all__ = ["Revision", "poner_al_dia", "revisar_cierra"]
