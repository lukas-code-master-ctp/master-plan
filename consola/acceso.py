"""Entrar a la consola.

Una contraseña compartida y una galleta firmada. Suena poco, y para tres o cuatro
personas de la casa lo es a propósito: la consola construye y publica loteos, no
guarda datos de clientes, y una cuenta por persona sería ceremonia sin beneficio.
Lo que sí importa es que no quede abierta, y de eso se ocupan dos cosas: la galleta
va firmada con HMAC —así nadie se la fabrica— y la aplicación **se niega a
funcionar** si la despliegan sin contraseña.

Si algún día hace falta saber quién hizo qué, el lugar es `Sesion.quien`: hoy lo
llena la contraseña, mañana lo puede llenar Google.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field

GALLETA = "consola"
HORAS_POR_DEFECTO = 12


@dataclass
class Sesion:
    quien: str
    desde: float = field(default_factory=time.time)


class Acceso:
    def __init__(self, clave: str | None, secreto: str | None, horas: int = HORAS_POR_DEFECTO,
                 local: bool = False):
        self.clave = clave or ""
        # Sin secreto propio, la firma se deriva de la contraseña: cambiarla también
        # invalida las sesiones abiertas, que es lo que uno espera.
        self.secreto = (secreto or f"derivado-de-{self.clave}").encode()
        self.horas = horas
        self.local = local

    @property
    def exigida(self) -> bool:
        return bool(self.clave)

    @property
    def desprotegida(self) -> bool:
        """Sin contraseña y fuera de este computador: no debe funcionar así."""
        return not self.clave and not self.local

    def es_valida(self, intento: str | None) -> bool:
        # compare_digest y no ==: comparar de a un carácter delata la contraseña
        # por el tiempo que tarda en fallar.
        return bool(intento) and hmac.compare_digest(intento or "", self.clave)

    def firmar(self, sesion: Sesion) -> str:
        cuerpo = _a_base64(json.dumps({"quien": sesion.quien, "desde": sesion.desde}).encode())
        return f"{cuerpo}.{self._firma(cuerpo)}"

    def leer(self, galleta: str | None) -> Sesion | None:
        if not galleta or "." not in galleta:
            return None
        cuerpo, _, firma = galleta.rpartition(".")
        if not hmac.compare_digest(firma, self._firma(cuerpo)):
            return None
        try:
            datos = json.loads(_de_base64(cuerpo))
            sesion = Sesion(quien=str(datos["quien"]), desde=float(datos["desde"]))
        except (ValueError, KeyError, TypeError):
            return None
        if time.time() - sesion.desde > self.horas * 3600:
            return None
        return sesion

    def _firma(self, cuerpo: str) -> str:
        return _a_base64(hmac.new(self.secreto, cuerpo.encode(), hashlib.sha256).digest())


def desde_el_entorno() -> Acceso:
    """La configuración de acceso, de variables de entorno.

    `CONSOLA_ENTORNO=local` (o nada) es este computador; cualquier otra cosa se
    considera desplegada y ahí la contraseña no es opcional.
    """
    return Acceso(
        clave=os.environ.get("CONSOLA_CLAVE"),
        secreto=os.environ.get("CONSOLA_SECRETO"),
        horas=int(os.environ.get("CONSOLA_HORAS", HORAS_POR_DEFECTO)),
        local=os.environ.get("CONSOLA_ENTORNO", "local") == "local",
    )


def _a_base64(crudo: bytes) -> str:
    return base64.urlsafe_b64encode(crudo).decode().rstrip("=")


def _de_base64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))
