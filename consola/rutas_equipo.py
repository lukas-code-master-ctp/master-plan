"""Configuración → Tu cuenta y Equipo.

Todo habla de la loteadora de quien pide: nunca llega un `cliente_id` de afuera.
Una persona de otra loteadora responde 404, como un loteo ajeno.

Invitar (y anular una invitación), desactivar y renombrar la loteadora es del dueño (y del equipo de CTP en la
suya). El resto del equipo ve la lista, pero no la cambia: si cualquiera pudiera
desactivar a cualquiera, el primero que se enoja deja afuera al dueño.
"""
from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from .acceso import GALLETA, Sesion
from .cuentas import EMAIL_VALIDO, Cuentas, limpiar_texto
from .datos import Base, EmailYaExiste, Invitacion, Usuario
from .rutas_cuentas import url_base

ADMINISTRAN = ("dueño", "plataforma")
LARGO_NOMBRE = 160


def rutas_de_equipo(base: Base, cuentas: Cuentas, quien, *, local: bool) -> APIRouter:
    rutas = APIRouter()

    def administrador(sesion: Sesion = Depends(quien)) -> Sesion:
        if sesion.rol not in ADMINISTRAN:
            raise HTTPException(403, "esto lo hace quien es dueño de la loteadora")
        return sesion

    def del_equipo(usuario_id: int, sesion: Sesion) -> Usuario:
        usuario = base.usuario(usuario_id)
        if usuario is None or usuario.cliente_id != sesion.cliente_id:
            raise HTTPException(404, "esa persona no está en tu equipo")
        return usuario

    @rutas.get("/api/cuenta")
    def cuenta(sesion: Sesion = Depends(quien)) -> dict:
        yo = base.usuario(sesion.usuario_id)
        return {
            "nombre": yo.nombre, "email": yo.email, "rol": yo.rol,
            "google": base.tiene_identidad(yo.id, "google"),
            "loteadora": base.cliente(sesion.cliente_id).nombre,
            "administra": sesion.rol in ADMINISTRAN,
            "equipo": [_miembro(u, yo) for u in base.usuarios_de(sesion.cliente_id)],
            "invitaciones": [_invitacion(i) for i in base.invitaciones_de(sesion.cliente_id)],
        }

    @rutas.patch("/api/cuenta")
    def cambiar_cuenta(campos: dict = Body(...), sesion: Sesion = Depends(quien)) -> dict:
        if "loteadora" in campos and sesion.rol not in ADMINISTRAN:
            raise HTTPException(403, "el nombre de la loteadora lo cambia su dueño")
        if "nombre" in campos:
            base.renombrar_usuario(sesion.usuario_id, _nombre(campos["nombre"], "Tu nombre"))
        if "loteadora" in campos:
            base.renombrar_cliente(sesion.cliente_id, _nombre(campos["loteadora"], "El nombre de la loteadora"))
            base.anotar("loteadora renombrada", cliente_id=sesion.cliente_id,
                        usuario_id=sesion.usuario_id, detalle=str(campos["loteadora"]).strip())
        return cuenta(sesion)

    @rutas.post("/api/cuenta/sesiones/cerrar")
    def cerrar_sesiones(sesion: Sesion = Depends(quien)) -> JSONResponse:
        """Para cuando se dejó la sesión abierta en otro computador. Esta también
        se cierra: es la forma de que no quede ninguna dudosa."""
        base.cortar_sesiones(sesion.usuario_id)
        base.anotar("sesiones cerradas", cliente_id=sesion.cliente_id, usuario_id=sesion.usuario_id)
        respuesta = JSONResponse({"listo": True})
        respuesta.delete_cookie(GALLETA, path="/")
        return respuesta

    @rutas.post("/api/equipo", status_code=201)
    def invitar(peticion: Request, campos: dict = Body(...),
                sesion: Sesion = Depends(administrador)) -> dict:
        """Deja una invitación y manda el enlace. La cuenta no existe hasta que la
        persona acepta: invitar un correo no lo ata a esta loteadora."""
        nombre = _nombre(campos.get("nombre"), "El nombre")
        email = str(campos.get("email") or "").strip().lower()
        if not EMAIL_VALIDO.match(email):
            raise HTTPException(400, "Ese correo no parece un correo.")
        try:
            token = cuentas.invitar(sesion.cliente_id, email, nombre, invitado_por=sesion.usuario_id)
        except EmailYaExiste as error:
            raise HTTPException(409, "Ese correo ya tiene una cuenta en Tu Masterplan.") from error
        base.anotar("invitación al equipo", cliente_id=sesion.cliente_id,
                    usuario_id=sesion.usuario_id, detalle=email)
        if not cuentas.registro_abierto:
            # Sin correo que llegue, el enlace lo entrega el dueño. Va sin dominio:
            # la página lo completa con el suyo, y así no depende de CONSOLA_URL.
            return {"email": email, "invitacion": "enlace", "enlace": f"/invitacion?t={token}"}
        quien_invita = base.usuario(sesion.usuario_id)
        cuentas.mandar_invitacion(email, token,
                                  quien_invita=quien_invita.nombre or quien_invita.email,
                                  loteadora=base.cliente(sesion.cliente_id).nombre,
                                  url_base=url_base(peticion, local))
        return {"email": email, "invitacion": "correo"}

    @rutas.delete("/api/equipo/invitaciones/{invitacion_id}")
    def anular_invitacion(invitacion_id: int, sesion: Sesion = Depends(quien)) -> dict:
        # Como con las personas: primero si es de su loteadora (404) y después si puede.
        if not any(i.id == invitacion_id for i in base.invitaciones_de(sesion.cliente_id)):
            raise HTTPException(404, "esa invitación no está en tu equipo")
        administrador(sesion)
        anulada = base.anular_invitacion(invitacion_id, sesion.cliente_id)
        if anulada is None:
            raise HTTPException(404, "esa invitación no está en tu equipo")
        base.anotar("invitación anulada", cliente_id=sesion.cliente_id,
                    usuario_id=sesion.usuario_id, detalle=anulada.email)
        return {"listo": True}

    @rutas.post("/api/equipo/{usuario_id}/estado")
    def cambiar_estado(usuario_id: int, campos: dict = Body(...),
                       sesion: Sesion = Depends(quien)) -> dict:
        # Primero si es de su equipo y después si puede: a otra loteadora no se le
        # cuenta, ni con un 403, qué números de usuario existen.
        usuario = del_equipo(usuario_id, sesion)
        administrador(sesion)
        if usuario.id == sesion.usuario_id:
            raise HTTPException(400, "No puedes desactivar tu propia cuenta.")
        activo = campos.get("activo")
        if not isinstance(activo, bool):
            raise HTTPException(400, "«activo» es true o false")
        if activo:
            base.reactivar_usuario(usuario.id)
        else:
            base.desactivar_usuario(usuario.email)
        base.anotar("cuenta reactivada" if activo else "cuenta desactivada",
                    cliente_id=sesion.cliente_id, usuario_id=sesion.usuario_id, detalle=usuario.email)
        return _miembro(base.usuario(usuario.id), base.usuario(sesion.usuario_id))

    return rutas


def _miembro(usuario: Usuario, yo: Usuario) -> dict:
    return {
        "id": usuario.id, "nombre": usuario.nombre, "email": usuario.email, "rol": usuario.rol,
        "activo": usuario.activo, "yo": usuario.id == yo.id,
        # Con la clave provisional todavía: lo creó el equipo de CTP (o una invitación
        # de antes de que hubiera que aceptarlas) y no ha entrado.
        "pendiente": usuario.debe_cambiar_clave,
    }


def _invitacion(invitacion: Invitacion) -> dict:
    return {"id": invitacion.id, "nombre": invitacion.nombre, "email": invitacion.email,
            "vencida": invitacion.vencida}


def _nombre(valor, que: str) -> str:
    nombre = limpiar_texto(str(valor or ""), LARGO_NOMBRE)
    if not nombre:
        raise HTTPException(400, f"{que} no puede quedar vacío.")
    return nombre
