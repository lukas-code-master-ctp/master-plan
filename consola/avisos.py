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
import os
import threading

from .cuentas import Correo
from .planes import PLANES
from .datos import Base, Usuario

registro = logging.getLogger("consola.avisos")

# Los correos salen de una dirección que no recibe respuestas: para coordinar un
# pago hay que decir a quién escribir. El mismo de la landing.
CONTACTO = os.environ.get("CONSOLA_CONTACTO", "eduardo@impulseai.cl")


class Avisos:
    def __init__(self, base: Base, correo: Correo, *, en_segundo_plano: bool = True):
        self.base = base
        self.correo = correo
        self.en_segundo_plano = en_segundo_plano

    def cuenta_nueva(self, usuario: Usuario, url_consola: str = "") -> None:
        """Al equipo de CTP, cuando alguien confirma una cuenta que se creó solo."""
        cliente = self.base.cliente(usuario.cliente_id)
        loteadora = cliente.nombre
        interes = PLANES.get(cliente.plan_interes or "")
        self._al_equipo(
            f"Cuenta nueva: {loteadora}",
            "\n".join([
                "Alguien se registró en la consola y confirmó su correo.",
                "",
                f"Loteadora: {loteadora}",
                f"Nombre: {usuario.nombre}",
                f"Correo: {usuario.email}",
                "(Datos escritos al registrarse.)",
                *([f"Llegó desde la landing eligiendo el plan {interes.nombre}."] if interes else []),
                "",
                _donde(url_consola, "Míralo en Loteadoras, en el menú de tu cuenta."),
            ]))

    def habilitacion_pedida(self, *, loteo: str, slug: str, cliente_id: int,
                            quien: str, plan: str | None = None, url_consola: str = "") -> None:
        """Al equipo de CTP, cuando una loteadora pide un plan para publicar un loteo."""
        loteadora = self.base.cliente(cliente_id).nombre
        self._al_equipo(
            f"Pide el plan {plan}: {loteadora}" if plan
            else f"Pide habilitar un loteo: {loteo} ({loteadora})",
            "\n".join([
                f"{loteadora} quiere publicar \"{loteo}\""
                + (f" y eligió el plan {plan}." if plan else " y pidió que se lo habiliten."),
                "",
                f"Lo pidió: {quien}",
                "",
                "Cuando esté pagado, asígnale el plan en su ficha (Loteadoras) y a la "
                "loteadora le llega un correo para que publique.",
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

    def plan_activo(self, *, cliente_id: int, plan: str, loteos: int | None, hasta=None,
                    url_consola: str = "") -> None:
        """A la loteadora, cuando CTP le asigna o le renueva un plan."""
        cupo = f"{loteos} {'loteo' if loteos == 1 else 'loteos'} en línea a la vez"
        texto = "\n".join([
            "Hola:",
            "",
            f"Tu plan {plan} ya está activo"
            + (f" y pagado hasta el {_dia(hasta)}" if hasta else "") + f": puedes tener {cupo}.",
            "",
            f"Abre tu master y aprieta Publicar: {url_consola.rstrip('/')}/#/planos" if url_consola
            else "Abre tu master en Mis 360° y aprieta Publicar.",
        ])
        self._a_la_loteadora(cliente_id, f"Tu plan {plan} está activo", texto)

    def plan_por_vencer(self, *, cliente_id: int, plan: str, hasta, url_consola: str = "") -> None:
        """5 días antes del último día pagado (consola/vencimientos.py)."""
        loteadora = self.base.cliente(cliente_id).nombre
        dia = _dia(hasta)
        self._a_la_loteadora(cliente_id, f"Tu plan {plan} vence el {dia}", "\n".join([
            "Hola:",
            "",
            f"Tu plan {plan} está pagado hasta el {dia}. Para que tus loteos sigan en "
            f"línea, escríbenos a {CONTACTO} y coordinamos la renovación.",
            "",
            "Si no se renueva, 7 días después del vencimiento los sitios se bajan del aire. "
            "Tus masters quedan guardados y los puedes volver a publicar cuando renueves.",
        ]))
        self._al_equipo(f"Vence el plan {plan}: {loteadora}", "\n".join([
            f"El plan {plan} de {loteadora} está pagado hasta el {dia}. Ya le avisamos.",
            "",
            "Cuando pague, renuévalo en su ficha (Loteadoras) con la nueva fecha.",
            _donde(url_consola, "Búscala en Loteadoras, en el menú de tu cuenta."),
        ]))

    def plan_vencido(self, *, cliente_id: int, plan: str, hasta, bajada,
                     url_consola: str = "") -> None:
        """Al día siguiente del último pagado: cuándo se bajan los sitios."""
        loteadora = self.base.cliente(cliente_id).nombre
        self._a_la_loteadora(cliente_id, f"Venció tu plan {plan}", "\n".join([
            "Hola:",
            "",
            f"Tu plan {plan} estaba pagado hasta el {_dia(hasta)}. Tus loteos siguen en "
            f"línea hasta el {_dia(bajada)}; ese día se bajan del aire si no se renueva.",
            "",
            f"Para renovar, escríbenos a {CONTACTO} y coordinamos el pago.",
        ]))
        self._al_equipo(f"Venció el plan {plan}: {loteadora}", "\n".join([
            f"El plan {plan} de {loteadora} venció (pagado hasta el {_dia(hasta)}).",
            f"Sus sitios se bajan solos el {_dia(bajada)} si no lo renuevas en su ficha.",
            _donde(url_consola, "Búscala en Loteadoras, en el menú de tu cuenta."),
        ]))

    def plan_bajado(self, *, cliente_id: int, plan: str, url_consola: str = "") -> None:
        """Cuando ya se bajaron sus sitios y se le quitó el plan."""
        loteadora = self.base.cliente(cliente_id).nombre
        self._a_la_loteadora(cliente_id, "Tus loteos se bajaron del aire", "\n".join([
            "Hola:",
            "",
            f"Tu plan {plan} venció hace una semana y no se renovó, así que tus loteos "
            "ya no están en línea. Tus masters siguen guardados en la consola.",
            "",
            "Para volver a publicarlos, elige un plan desde cualquiera de ellos: "
            + (f"{url_consola.rstrip('/')}/#/planos" if url_consola else "Mis 360°."),
        ]))
        self._al_equipo(f"Sitios bajados: {loteadora}", "\n".join([
            f"El plan {plan} de {loteadora} llevaba 7 días vencido: sus sitios se "
            "bajaron y quedó sin plan.",
            _donde(url_consola, "Búscala en Loteadoras, en el menú de tu cuenta."),
        ]))

    def _a_la_loteadora(self, cliente_id: int, asunto: str, texto: str) -> None:
        for usuario in self.base.usuarios_de(cliente_id):
            if usuario.activo and usuario.email_verificado:
                self._enviar(usuario.email, asunto, texto)

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


def _dia(fecha) -> str:
    return fecha.strftime("%d/%m/%Y")


def _donde(url_consola: str, sin_enlace: str) -> str:
    return f"La consola: {url_consola.rstrip('/')}/" if url_consola else sin_enlace
