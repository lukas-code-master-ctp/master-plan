"""Cuentas que se crea la propia gente: Regístrate, olvidé mi contraseña y Google.

Hasta la fase 3 las cuentas las creaba el equipo de CTP con una clave
provisional. Ahora cualquiera se registra, porque el cobro se controla al
publicar y no al entrar.

Tres cuidados que atraviesan todo el módulo:

- **No contar quién tiene cuenta.** Registrarse con un correo que ya existe y
  pedir restablecer uno que no existe contestan en pantalla lo mismo que el caso
  normal. La diferencia solo llega al buzón, que es de quien corresponde.
- **Los enlaces son de un solo uso y vencen.** Se guarda el hash del token, no
  el token: una copia de la base no abre ninguna cuenta.
- **Topes por IP** para registrarse y pedir enlaces: sin ellos, el formulario es
  una forma gratis de mandar correos a cualquiera.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from .datos import Base, EmailYaExiste, Usuario

registro = logging.getLogger("consola.cuentas")

LARGO_MINIMO_CLAVE = 10
VIGENCIA = {"verificar": timedelta(days=2), "clave": timedelta(hours=1)}
EMAIL_VALIDO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class CuentaInvalida(ValueError):
    """Lo que llegó no sirve para crear o cambiar una cuenta. Mensaje para la persona."""


# --- correo ----------------------------------------------------------------------

class Correo(Protocol):
    # Si los correos llegan a alguien. Sin eso no se abre el registro ni la
    # recuperación de contraseña: serían flujos que nadie puede terminar.
    puede_enviar: bool

    def enviar(self, para: str, asunto: str, texto: str) -> None: ...


class CorreoSendGrid:
    """El mismo proveedor que usan los reportes de CTP, por su API HTTP."""

    URL = "https://api.sendgrid.com/v3/mail/send"
    puede_enviar = True

    def __init__(self, clave: str, remitente: str, nombre: str = "Tu Masterplan"):
        self.clave = clave
        self.remitente = remitente
        self.nombre = nombre

    def enviar(self, para: str, asunto: str, texto: str) -> None:
        cuerpo = json.dumps({
            "personalizations": [{"to": [{"email": para}]}],
            "from": {"email": self.remitente, "name": self.nombre},
            "subject": asunto,
            "content": [{"type": "text/plain", "value": texto}],
        }).encode()
        peticion = urllib.request.Request(self.URL, data=cuerpo, method="POST", headers={
            "Authorization": f"Bearer {self.clave}", "Content-Type": "application/json"})
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            if respuesta.status >= 300:
                raise RuntimeError(f"SendGrid contestó {respuesta.status}")


class CorreoEnElRegistro:
    """Sin SendGrid configurado: el correo queda en el registro de la consola.

    Sirve en este computador para probar los enlaces. Desplegada, sin clave, los
    correos no salen y se avisa en el registro en cada intento.
    """

    def __init__(self, local: bool):
        self.local = local
        # En este computador el enlace se lee en el registro: sirve para probar.
        # Desplegada no llega a nadie, y el registro queda cerrado.
        self.puede_enviar = local
        self.enviados: list[tuple[str, str, str]] = []

    def enviar(self, para: str, asunto: str, texto: str) -> None:
        self.enviados.append((para, asunto, texto))
        if self.local:
            registro.warning("correo a %s — %s\n%s", para, asunto, texto)
        else:
            registro.error("no se envió el correo a %s (%s): falta SENDGRID_API_KEY", para, asunto)


class CorreoEnCarpeta:
    """Para probar en este computador: cada correo queda como un JSON en una carpeta.

    Así una prueba (o `npm run qa:correos`) lee el enlace sin buscarlo en el
    registro. El nombre del archivo empieza con la hora en nanosegundos, para
    ordenarlos, y lleva un token corto: dos correos en el mismo instante no se pisan.
    """

    puede_enviar = True
    ENLACE = re.compile(r"https?://[^\s<>\"']+")

    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)
        self.enviados: list[tuple[str, str, str]] = []

    def enviar(self, para: str, asunto: str, texto: str) -> None:
        self.enviados.append((para, asunto, texto))
        self.carpeta.mkdir(parents=True, exist_ok=True)
        correo = {
            "para": para, "asunto": asunto, "texto": texto,
            # Sin el punto o el paréntesis que cierra la frase.
            "enlaces": [e.rstrip(".,;:)") for e in self.ENLACE.findall(texto)],
            "enviado_en": datetime.now(timezone.utc).isoformat(),
        }
        nombre = f"{time.time_ns():020d}-{secrets.token_hex(3)}.json"
        # Primero a un temporal y después se renombra: quien lee la carpeta nunca
        # ve un correo a medio escribir.
        temporal = self.carpeta / f".{nombre}.tmp"
        temporal.write_text(json.dumps(correo, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporal, self.carpeta / nombre)
        registro.warning("correo a %s — %s (en %s)\n%s", para, asunto, self.carpeta / nombre, texto)


def correo_del_entorno(local: bool) -> Correo:
    clave = os.environ.get("SENDGRID_API_KEY", "").strip()
    if clave:
        return CorreoSendGrid(clave, os.environ.get("EMAIL_FROM", "no-responder@tumasterplan.cl"))
    # El buzón en disco, solo en este computador: desplegada serían correos que
    # nadie recibe con el registro abierto.
    buzon = os.environ.get("CONSOLA_BUZON", "").strip()
    if local and buzon:
        return CorreoEnCarpeta(Path(buzon))
    return CorreoEnElRegistro(local)


# --- topes -----------------------------------------------------------------------

class Limitador:
    """Cuántas veces puede algo pasar por clave (una IP, un correo) en una ventana.

    En memoria: la consola corre en una sola instancia (`--max-instances=1`),
    igual que los trabajos. Las claves viejas se descartan y hay un tope de
    claves: quien inventa una por petición no puede hacer crecer la memoria.
    """

    TOPE_DE_CLAVES = 10_000

    def __init__(self, maximo: int, segundos: int):
        self.maximo = maximo
        self.segundos = segundos
        self._marcas: dict[str, list[float]] = {}
        self._candado = threading.Lock()

    def permitir(self, clave: str) -> bool:
        ahora = time.monotonic()
        with self._candado:
            recientes = [m for m in self._marcas.get(clave, []) if ahora - m < self.segundos]
            if len(recientes) >= self.maximo:
                self._marcas[clave] = recientes
                return False
            self._marcas[clave] = [*recientes, ahora]
            if len(self._marcas) > self.TOPE_DE_CLAVES:
                self._podar(ahora)
            return True

    def _podar(self, ahora: float) -> None:
        self._marcas = {c: m for c, m in self._marcas.items() if ahora - m[-1] < self.segundos}
        if len(self._marcas) > self.TOPE_DE_CLAVES:
            # Siguen siendo demasiadas: se quedan las más recientes.
            orden = sorted(self._marcas.items(), key=lambda par: par[1][-1], reverse=True)
            self._marcas = dict(orden[: self.TOPE_DE_CLAVES // 2])


# --- cuentas ---------------------------------------------------------------------

def limpiar_texto(texto: str, largo: int) -> str:
    """Una línea de texto: sin saltos ni caracteres de control, que en un correo
    legítimo servirían para colar un párrafo inventado."""
    return " ".join("".join(c if c.isprintable() else " " for c in texto).split())[:largo]


@dataclass(frozen=True)
class Registro:
    loteadora: str
    nombre: str
    email: str
    clave: str


def validar_registro(campos: dict) -> Registro:
    loteadora = limpiar_texto(str(campos.get("loteadora") or ""), 160)
    nombre = limpiar_texto(str(campos.get("nombre") or ""), 160)
    email = str(campos.get("email") or "").strip().lower()
    clave = str(campos.get("clave") or "")
    if not loteadora:
        raise CuentaInvalida("Falta el nombre de tu loteadora.")
    if not nombre:
        raise CuentaInvalida("Falta tu nombre.")
    if not EMAIL_VALIDO.match(email):
        raise CuentaInvalida("Ese correo no parece un correo.")
    validar_clave(clave)
    return Registro(loteadora=loteadora, nombre=nombre, email=email[:200], clave=clave)


def validar_clave(clave: str) -> None:
    if len(clave) < LARGO_MINIMO_CLAVE:
        raise CuentaInvalida(f"La contraseña tiene que tener al menos {LARGO_MINIMO_CLAVE} caracteres.")


class Cuentas:
    """Los correos no llevan el nombre de nadie: quien se registra lo escribe, y
    podría ser otra persona usando tu correo."""

    def __init__(self, base: Base, correo: Correo, *, en_segundo_plano: bool = False):
        self.base = base
        self.correo = correo
        # Mandar el correo fuera de la petición: si no, "hay cuenta" (se manda,
        # segundos) y "no hay" (no se manda, al instante) se distinguen midiendo.
        self.en_segundo_plano = en_segundo_plano
        # Por buzón de destino, aparte del tope por IP: cambiar de IP no deja
        # llenar de correos el buzón de alguien.
        self.por_buzon = Limitador(maximo=3, segundos=3600)

    @property
    def registro_abierto(self) -> bool:
        """Registrarse y recuperar la contraseña piden un correo que llegue."""
        return getattr(self.correo, "puede_enviar", True)

    def registrar(self, datos: Registro, url_base: str) -> None:
        """Crea la cuenta sin verificar y manda el enlace. Si el correo ya tenía
        cuenta, no crea nada: si está sin confirmar le reenvía el enlace, y si no
        le avisa que ya tiene una. La pantalla es la misma en los tres casos."""
        try:
            usuario = self.base.crear_cuenta_propia(
                datos.loteadora, datos.email, datos.nombre, datos.clave, verificado=False)
        except EmailYaExiste:
            # Lo que tarda crear la cuenta (bcrypt), para no distinguir por tiempo.
            self.base.verificar_en_vano()
            existente = self.base.usuario_por_email(datos.email)
            if existente is not None and not existente.email_verificado:
                self.enviar_verificacion(existente, url_base)
                return
            self._enviar(datos.email, "Ya tienes una cuenta en Tu Masterplan",
                         "Alguien —probablemente tú— intentó crear una cuenta con este correo, "
                         "pero ya tienes una.\n\n"
                         f"Entra en {url_base}/entrar\n"
                         f"¿No recuerdas la contraseña? Pide una nueva en {url_base}/olvide\n\n"
                         "Si no fuiste tú, no tienes que hacer nada.")
            return
        self.enviar_verificacion(usuario, url_base)

    def enviar_verificacion(self, usuario: Usuario, url_base: str) -> None:
        if not self.por_buzon.permitir(usuario.email):
            return
        token = self._token(usuario.id, "verificar")
        self._enviar(usuario.email, "Confirma tu correo en Tu Masterplan",
                     "Hola:\n\n"
                     "Para entrar a Tu Masterplan, confirma que este correo es tuyo:\n\n"
                     f"{url_base}/verificar?t={token}\n\n"
                     "El enlace sirve una vez y vence en 2 días.\n"
                     "Si no creaste una cuenta, ignora este correo: sin confirmarla nadie "
                     "puede entrar con ella.", controlar=False)

    def verificar(self, token: str) -> Usuario | None:
        usuario_id = self.base.usar_token("verificar", _hash(token))
        if usuario_id is None:
            return None
        self.base.marcar_verificado(usuario_id)
        return self.base.usuario(usuario_id)

    def pedir_restablecer(self, email: str, url_base: str) -> None:
        """Manda el enlace si hay cuenta activa. Si no la hay, no manda nada y la
        pantalla es la misma."""
        usuario = self.base.usuario_por_email(email) if email else None
        if usuario is None or not usuario.activo or not self.por_buzon.permitir(usuario.email):
            return
        token = self._token(usuario.id, "clave")
        self._enviar(usuario.email, "Restablece tu contraseña de Tu Masterplan",
                     "Hola:\n\n"
                     "Pediste una contraseña nueva. Elígela acá:\n\n"
                     f"{url_base}/restablecer?t={token}\n\n"
                     "El enlace sirve una vez y vence en 1 hora.\n"
                     "Si no lo pediste, ignora este correo: tu contraseña sigue igual.",
                     controlar=False)

    def restablecer(self, token: str, clave: str) -> Usuario | None:
        """Cambia la clave con un enlace válido. Cambiarla corta las sesiones
        abiertas; y quien recibió el correo probó que el buzón es suyo."""
        validar_clave(clave)
        usuario_id = self.base.usar_token("clave", _hash(token))
        if usuario_id is None:
            return None
        usuario = self.base.usuario(usuario_id)
        if usuario is None:
            return None
        self.base.cambiar_clave(usuario.email, clave)
        self.base.marcar_verificado(usuario.id)
        return self.base.usuario(usuario.id)

    def _token(self, usuario_id: int, tipo: str) -> str:
        token = secrets.token_urlsafe(32)
        self.base.guardar_token(usuario_id, tipo, _hash(token),
                                datetime.now(timezone.utc) + VIGENCIA[tipo])
        return token

    def _enviar(self, para: str, asunto: str, texto: str, *, controlar: bool = True) -> None:
        """Manda un correo. `controlar` = pasa por el tope por buzón (lo que ya
        pasó por él, como la verificación, no se cuenta dos veces)."""
        if controlar and not self.por_buzon.permitir(para):
            return
        if self.en_segundo_plano:
            threading.Thread(target=self._mandar, args=(para, asunto, texto), daemon=True).start()
        else:
            self._mandar(para, asunto, texto)

    def _mandar(self, para: str, asunto: str, texto: str) -> None:
        # Un correo que no sale no puede tumbar la página: la persona ve lo mismo
        # y el error queda en el registro para el equipo.
        try:
            self.correo.enviar(para, asunto, texto)
        except Exception:                        # noqa: BLE001
            registro.exception("no se pudo enviar el correo a %s", para)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- Google ----------------------------------------------------------------------

@dataclass(frozen=True)
class IdentidadGoogle:
    sujeto: str
    email: str
    nombre: str


class Google:
    """Entrar con Google (OpenID Connect, flujo de código).

    El código se canjea directo con Google por TLS y con el secreto del cliente,
    y quién es la persona se le pregunta a Google con ese acceso: no hace falta
    validar la firma de un token a mano, que es donde suelen estar los errores.
    """

    AUTORIZAR = "https://accounts.google.com/o/oauth2/v2/auth"
    CANJEAR = "https://oauth2.googleapis.com/token"
    QUIEN = "https://openidconnect.googleapis.com/v1/userinfo"

    def __init__(self, cliente_id: str, secreto: str, http=None):
        self.cliente_id = cliente_id
        self.secreto = secreto
        self.http = http or _http

    def url_de_entrada(self, estado: str, vuelta: str) -> str:
        return self.AUTORIZAR + "?" + urllib.parse.urlencode({
            "client_id": self.cliente_id, "redirect_uri": vuelta, "response_type": "code",
            "scope": "openid email profile", "state": estado, "prompt": "select_account"})

    def identidad(self, codigo: str, vuelta: str) -> IdentidadGoogle:
        canje = self.http("POST", self.CANJEAR, formulario={
            "code": codigo, "client_id": self.cliente_id, "client_secret": self.secreto,
            "redirect_uri": vuelta, "grant_type": "authorization_code"})
        acceso = canje.get("access_token")
        if not acceso:
            raise CuentaInvalida("Google no confirmó la entrada. Vuelve a intentarlo.")
        datos = self.http("GET", self.QUIEN, token=acceso)
        if not datos.get("sub") or not datos.get("email"):
            raise CuentaInvalida("Google no entregó tu correo.")
        # Un correo sin verificar en Google no prueba nada: enlazarlo por correo
        # le daría a cualquiera la cuenta de otro.
        if datos.get("email_verified") is not True:
            raise CuentaInvalida("Tu correo de Google no está verificado.")
        return IdentidadGoogle(sujeto=str(datos["sub"]), email=str(datos["email"]).lower(),
                               nombre=limpiar_texto(str(datos.get("name") or datos["email"]), 160))


def google_del_entorno() -> Google | None:
    cliente = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
    secreto = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
    return Google(cliente, secreto) if cliente and secreto else None


def _http(metodo: str, url: str, formulario: dict | None = None, token: str | None = None) -> dict:
    datos = urllib.parse.urlencode(formulario).encode() if formulario else None
    cabeceras = {"Accept": "application/json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    peticion = urllib.request.Request(url, data=datos, method=metodo, headers=cabeceras)
    try:
        with urllib.request.urlopen(peticion, timeout=15) as respuesta:
            return json.loads(respuesta.read())
    except (OSError, ValueError) as error:
        registro.warning("Google no contestó bien: %s", error)
        return {}
