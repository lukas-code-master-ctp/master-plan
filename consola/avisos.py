"""Los correos que mueven a una loteadora nueva hasta su primera publicación.

Una cuenta nueva, un pedido de habilitación y un loteo habilitado pasan sin que
nadie esté mirando la consola: CTP se entera de lo primero y lo segundo por
correo, y la loteadora de lo tercero. Sin estos avisos, quien se registra de
noche queda esperando un "escríbenos" que no lleva a ninguna parte.

Ninguno lleva datos que la persona no haya escrito ella misma, y que un correo
falle nunca tumba la acción que lo disparó: queda en el registro.
"""
from __future__ import annotations

import logging
import threading

from .cuentas import Correo
from .datos import Base, Usuario

registro = logging.getLogger("consola.avisos")


class Avisos:
    def __init__(self, base: Base, correo: Correo, *, en_segundo_plano: bool = True):
        self.base = base
        self.correo = correo
        self.en_segundo_plano = en_segundo_plano

    def cuenta_nueva(self, usuario: Usuario, url_consola: str = "") -> None:
        """Al equipo de CTP, cuando alguien confirma una cuenta que se creó solo."""
        loteadora = self.base.cliente(usuario.cliente_id).nombre
        self._al_equipo(
            f"Cuenta nueva: {loteadora}",
            "\n".join([
                "Alguien se registró en la consola y confirmó su correo.",
                "",
                f"Loteadora: {loteadora}",
                f"Nombre: {usuario.nombre}",
                f"Correo: {usuario.email}",
                "(Datos escritos al registrarse.)",
                "",
                _donde(url_consola, "Míralo en Loteadoras, en el menú de tu cuenta."),
            ]))

    def habilitacion_pedida(self, *, loteo: str, slug: str, cliente_id: int,
                            quien: str, url_consola: str = "") -> None:
        """Al equipo de CTP, cuando una loteadora pide que le dejen publicar un loteo."""
        loteadora = self.base.cliente(cliente_id).nombre
        self._al_equipo(
            f"Pide habilitar un loteo: {loteo} ({loteadora})",
            "\n".join([
                f"{loteadora} quiere publicar \"{loteo}\" y pidió que se lo habiliten.",
                "",
                f"Lo pidió: {quien}",
                "",
                "Cuando esté pagado, anota el pago en el loteo (Anotar pago) y a la "
                "loteadora le llega un correo para que lo publique.",
                "",
                f"El loteo: {url_consola.rstrip('/')}/#/planos/{slug}" if url_consola
                else f"Búscalo en la consola: {slug}",
            ]))

    def loteo_habilitado(self, *, loteo: str, slug: str, cliente_id: int,
                         url_consola: str = "") -> None:
        """A la loteadora, cuando CTP anota el pago y ya puede publicar."""
        texto = "\n".join([
            "Hola:",
            "",
            f"\"{loteo}\" ya está habilitado: puedes publicarlo cuando quieras.",
            "",
            f"Ábrelo y aprieta Publicar: {url_consola.rstrip('/')}/#/planos/{slug}" if url_consola
            else "Ábrelo en Mis 360° y aprieta Publicar.",
        ])
        # A toda la loteadora y no solo a quien lo pidió: el que publica puede ser otro.
        for usuario in self.base.usuarios_de(cliente_id):
            if usuario.activo and usuario.email_verificado:
                self._enviar(usuario.email, f"Ya puedes publicar {loteo}", texto)

    def _al_equipo(self, asunto: str, texto: str) -> None:
        for usuario in self.base.usuarios_de_plataforma():
            if usuario.activo and usuario.email_verificado:
                self._enviar(usuario.email, asunto, texto)

    def _enviar(self, para: str, asunto: str, texto: str) -> None:
        if self.en_segundo_plano:
            threading.Thread(target=self._mandar, args=(para, asunto, texto), daemon=True).start()
        else:
            self._mandar(para, asunto, texto)

    def _mandar(self, para: str, asunto: str, texto: str) -> None:
        try:
            self.correo.enviar(para, asunto, texto)
        except Exception:   # noqa: BLE001 — un correo caído no deshace lo que lo disparó
            registro.exception("no pude mandar el aviso a %s", para)


def _donde(url_consola: str, sin_enlace: str) -> str:
    return f"La consola: {url_consola.rstrip('/')}/" if url_consola else sin_enlace
