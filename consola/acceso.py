"""Entrar a la consola: quién es cada quien, y hasta cuándo.

La galleta va firmada con HMAC y lleva lo mínimo: el id del usuario y desde
cuándo. El correo, el rol y de qué loteadora es se vuelven a leer de la base en
cada petición. Cuesta dos consultas y compra algo que una galleta autocontenida
no puede dar: que una cuenta desactivada, degradada, con la clave recién
cambiada o de un cliente suspendido pierda el acceso en la petición siguiente y
no doce horas después.

No hay tabla de sesiones. La revocación es una fecha por usuario
(`sesiones_validas_desde`): una galleta firmada antes de esa marca no vale.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .datos import Base, Usuario

GALLETA = "consola"
HORAS_POR_DEFECTO = 12

# Dónde queda el secreto de firma cuando nadie lo indica: solo en este computador.
# Desplegada, la consola lo exige por variable de entorno.
ARCHIVO_SECRETO = ".secreto-consola"


@dataclass(frozen=True)
class Sesion:
    """Quién está pidiendo. Se arma desde la base, nunca desde la galleta."""
    usuario_id: int
    cliente_id: int
    rol: str
    quien: str                        # el correo: para mostrarlo y para el registro
    debe_cambiar_clave: bool = False
    desde: float = field(default_factory=time.time)

    @property
    def es_plataforma(self) -> bool:
        """El equipo de CTP, que opera todas las loteadoras."""
        return self.rol == "plataforma"


class Acceso:
    def __init__(self, base: Base, secreto: str | None = None,
                 horas: int = HORAS_POR_DEFECTO, local: bool = False):
        self.base = base
        self.secreto = (secreto or "").encode()
        self.horas = horas
        self.local = local

    @property
    def desprotegida(self) -> bool:
        """Sin secreto de firma cualquiera se fabrica una galleta. Que no arranque."""
        return not self.secreto

    def entrar(self, email: str, clave: str) -> Sesion | None:
        usuario = self.base.usuario_por_email(email) if email else None
        if usuario is None or not usuario.activo:
            # Se gasta el tiempo igual: contestar al instante cuando el correo no
            # existe convierte el formulario en un buscador de cuentas.
            self.base.verificar_en_vano()
            return None
        if not self.base.clave_valida(usuario, clave):
            return None
        if self.base.cliente(usuario.cliente_id).estado != "activo":
            return None
        return _sesion_de(usuario)

    def firmar(self, sesion: Sesion) -> str:
        cuerpo = _a_base64(json.dumps({"u": sesion.usuario_id, "d": sesion.desde}).encode())
        return f"{cuerpo}.{self._firma(cuerpo)}"

    def leer(self, galleta: str | None) -> Sesion | None:
        if not galleta or "." not in galleta:
            return None
        cuerpo, _, firma = galleta.rpartition(".")
        if not hmac.compare_digest(firma, self._firma(cuerpo)):
            return None
        try:
            datos = json.loads(_de_base64(cuerpo))
            usuario_id, desde = int(datos["u"]), float(datos["d"])
        except (ValueError, KeyError, TypeError):
            return None
        if time.time() - desde > self.horas * 3600:
            return None

        usuario = self.base.usuario(usuario_id)
        if usuario is None or not usuario.activo:
            return None
        if desde < _marca(usuario.sesiones_validas_desde):
            return None
        if self.base.cliente(usuario.cliente_id).estado != "activo":
            return None
        return _sesion_de(usuario, desde)

    def _firma(self, cuerpo: str) -> str:
        return _a_base64(hmac.new(self.secreto, cuerpo.encode(), hashlib.sha256).digest())


def desde_el_entorno(base: Base | None = None) -> Acceso:
    """La configuración de acceso, de variables de entorno.

    `CONSOLA_ENTORNO=local` (o nada) es este computador, y ahí el secreto de firma
    se genera solo en un archivo al lado de los datos. Desplegada, se exige por
    variable: un secreto en el volumen de datos viaja en cada respaldo, junto a los
    archivos de los clientes.
    """
    from pipeline import config

    local = os.environ.get("CONSOLA_ENTORNO", "local") == "local"
    secreto = os.environ.get("CONSOLA_SECRETO") or (_secreto_local(config.DATOS) if local else "")
    return Acceso(
        base=base if base is not None else Base(),
        secreto=secreto,
        horas=int(os.environ.get("CONSOLA_HORAS", HORAS_POR_DEFECTO)),
        local=local,
    )


def _secreto_local(carpeta: Path) -> str:
    archivo = Path(carpeta) / ARCHIVO_SECRETO
    if archivo.is_file():
        return archivo.read_text(encoding="utf-8").strip()
    archivo.parent.mkdir(parents=True, exist_ok=True)
    secreto = secrets.token_urlsafe(32)
    archivo.write_text(secreto, encoding="utf-8")
    archivo.chmod(0o600)
    return secreto


def _sesion_de(usuario: Usuario, desde: float | None = None) -> Sesion:
    return Sesion(usuario_id=usuario.id, cliente_id=usuario.cliente_id, rol=usuario.rol,
                  quien=usuario.email, debe_cambiar_clave=usuario.debe_cambiar_clave,
                  desde=desde if desde is not None else time.time())


def _marca(momento: datetime) -> float:
    """La fecha en segundos, leyéndola en UTC aunque venga sin zona.

    SQLite no guarda la zona: devuelve la hora en UTC pero sin decirlo, y tomarla
    como hora local la correría varias horas hacia el futuro. Toda galleta quedaría
    firmada 'antes' de la marca de revocación y nadie podría entrar.
    """
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.timestamp()


def _a_base64(crudo: bytes) -> str:
    return base64.urlsafe_b64encode(crudo).decode().rstrip("=")


def _de_base64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))
