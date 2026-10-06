"""Poner al día los estados y precios de un sitio ya construido, sin reconstruirlo.

Cuando en Cierra (o en la planilla) cambia el estado o el precio de una parcela,
lo único que cambia del sitio son sus datos comerciales en `parcelas.json`: la
forma de los lotes, dónde caen en cada foto y las imágenes siguen iguales. Este
módulo reescribe solo eso, en segundos, con la misma regla que usa la
construcción (`construir.comerciales`).

Si la planilla trae una parcela que el sitio no tiene —un lote nuevo en el plano,
o uno escrito distinto—, no se adivina: se devuelve en `faltan` y no se escribe
nada. Eso pide una construcción completa, que vuelve a leer el KMZ.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config
from .construir import (
    CAMPOS_COMERCIALES,
    Avisos,
    _leer_fichas,
    _orden_lote,
    _resumen,
    comerciales,
)


@dataclass(frozen=True)
class Resultado:
    """Qué parcelas cambiaron, y las que no se pueden poner al día sin reconstruir."""
    cambiadas: tuple[str, ...] = ()
    faltan: tuple[str, ...] = ()
    avisos: tuple[str, ...] = field(default=())

    @property
    def requiere_reconstruir(self) -> bool:
        return bool(self.faltan)


# Lo que del loteo entero (no de cada parcela) se edita en la consola y el visor
# muestra: el nombre, la etapa, el WhatsApp y la reserva. La construcción lo
# escribe; esto lo pone al día sin reconstruir, igual que los estados y precios.
DATOS_DEL_LOTEO = ("proyecto", "etapa", "whatsapp", "link_reserva", "monto_reserva")


def _datos_del_loteo(proyecto: config.Proyecto) -> dict:
    return dict(zip(DATOS_DEL_LOTEO, (proyecto.nombre, proyecto.etapa, proyecto.whatsapp,
                                      proyecto.link_reserva, proyecto.monto_reserva)))


def poner_datos_del_loteo(proyecto: config.Proyecto, salida: config.Salida) -> bool:
    """Escribe los datos del loteo (nombre, etapa, WhatsApp, reserva) en el sitio. Dice si cambió algo."""
    archivo = salida.datos / "parcelas.json"
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    nuevos = _datos_del_loteo(proyecto)
    if all(datos.get(campo) == valor for campo, valor in nuevos.items()):
        return False
    _escribir(archivo, {**datos, **nuevos})
    return True


def actualizar(fuentes: config.Fuentes, proyecto: config.Proyecto,
               salida: config.Salida) -> Resultado:
    archivo = salida.datos / "parcelas.json"
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    avisos = Avisos([])
    fichas = _leer_fichas(fuentes, proyecto, avisos)

    parcelas = datos["parcelas"]
    en_el_sitio = {p["id"] for p in parcelas}
    faltan = sorted(set(fichas) - en_el_sitio, key=_orden_lote)
    # Una parcela que solo existía por la planilla (sin polígono) y ya no está en
    # ella tampoco se puede resolver acá: la construcción la sacaría del sitio.
    sobran = [p["id"] for p in parcelas if not p.get("poligono") and p["id"] not in fichas]
    if faltan or sobran:
        return Resultado(faltan=tuple(faltan + sobran), avisos=tuple(avisos.lineas))

    cambiadas = []
    for parcela in parcelas:
        # El dibujo decide "no en venta" cuando no hay ficha: se recupera de lo que
        # la construcción dejó escrito, porque acá no se vuelve a leer el KMZ.
        en_venta = not (parcela.get("estado") == "no_en_venta" and not parcela.get("en_planilla"))
        nuevo = comerciales(fichas.get(parcela["id"]), en_venta=en_venta,
                            area_m2=parcela.get("area_kmz_m2"))
        if any(parcela.get(campo) != nuevo[campo] for campo in CAMPOS_COMERCIALES):
            parcela.update(nuevo)
            cambiadas.append(parcela["id"])

    # Los datos del loteo viajan con los estados: si se cambiaron en la consola,
    # la próxima publicación ya los lleva.
    nuevos = _datos_del_loteo(proyecto)
    cambia_el_loteo = any(datos.get(campo) != valor for campo, valor in nuevos.items())
    if cambiadas or cambia_el_loteo:
        datos.update(nuevos)
        datos["resumen"] = _resumen(parcelas)
        datos["actualizado"] = datetime.now().astimezone().isoformat(timespec="seconds")
        _escribir(archivo, datos)
    return Resultado(cambiadas=tuple(cambiadas), avisos=tuple(avisos.lineas))


def _escribir(archivo: Path, datos: dict) -> None:
    """Todo o nada: el visor publicado nunca ve un parcelas.json a medio escribir."""
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=archivo.parent,
                                     prefix=".parcelas-", suffix=".tmp", delete=False) as temporal:
        json.dump(datos, temporal, ensure_ascii=False, separators=(",", ":"))
    os.replace(temporal.name, archivo)


__all__ = ["DATOS_DEL_LOTEO", "Resultado", "actualizar", "poner_datos_del_loteo"]
