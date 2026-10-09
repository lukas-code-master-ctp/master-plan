"""Las páginas y rutas de cuentas: entrar, Regístrate, olvidé mi contraseña, Google.

Son páginas del servidor y no de la app: se ven sin haber entrado, así que no
cargan el guion de la consola. Todo valor que venga de afuera y se pinte en una
de ellas pasa por `escape`.
"""
from __future__ import annotations

import os
import secrets
from html import escape
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from .acceso import GALLETA, Acceso, Sesion
from .cuentas import (
    CuentaInvalida,
    Cuentas,
    Google,
    Limitador,
    validar_clave,
    validar_registro,
)
from .datos import EmailYaExiste

WEB = Path(__file__).resolve().parent / "web"

# Lo que se puede pedir sin haber entrado. Se suma a LIBRES en `app.py`.
LIBRES_DE_CUENTAS = ("/registro", "/verificar", "/olvide", "/restablecer",
                     "/entrar/google", "/entrar/google/vuelta", "/registro/google")

GALLETA_ESTADO = "google-estado"
GALLETA_ALTA = "google-alta"

LOGO_GOOGLE = (
    '<svg viewBox="0 0 48 48" aria-hidden="true"><path fill="#EA4335" d="M24 9.5c3.5 0 6.6 1.2 9 '
    '3.6l6.7-6.7C35.6 2.4 30.2 0 24 0 14.6 0 6.6 5.4 2.6 13.2l7.8 6.1C12.3 13.6 17.6 9.5 24 9.5z"/>'
    '<path fill="#4285F4" d="M46.1 24.5c0-1.6-.1-3.1-.4-4.5H24v9h12.4c-.5 2.9-2.2 5.3-4.6 6.9l7.4 '
    '5.8c4.3-4 6.9-9.9 6.9-17.2z"/><path fill="#FBBC05" d="M10.4 28.7c-.5-1.4-.8-3-.8-4.7s.3-3.3.8-4.7'
    'l-7.8-6.1C.9 16.5 0 20.1 0 24s.9 7.5 2.6 10.8l7.8-6.1z"/><path fill="#34A853" d="M24 48c6.5 0 '
    '11.9-2.1 15.9-5.8l-7.4-5.8c-2.1 1.4-4.8 2.3-8.5 2.3-6.4 0-11.7-4.1-13.6-9.7l-7.8 6.1C6.6 42.6 '
    '14.6 48 24 48z"/></svg>')


# --- páginas -----------------------------------------------------------------------

def pagina(titulo: str, contenido: str, estado: int = 200) -> HTMLResponse:
    plantilla = (WEB / "pagina.html").read_text(encoding="utf-8")
    html = plantilla.replace("<!--TITULO-->", escape(titulo)).replace("<!--CONTENIDO-->", contenido)
    return HTMLResponse(html, status_code=estado)


def _aviso(texto: str | None, tono: str = "") -> str:
    if not texto:
        return ""
    clase = f"aviso aviso--{tono}" if tono else "aviso"
    return f'<p class="{clase}" role="alert">{escape(texto)}</p>'


CONTACTO = "mailto:e.ruiz@compratuparcela.cl?subject=Quiero%20una%20cuenta%20en%20Tu%20Masterplan"


def pagina_de_entrada(error: str | None = None, *, con_google: bool, con_registro: bool = True,
                      aviso: str | None = None, estado: int = 200) -> HTMLResponse:
    google = (f'<a class="boton boton--google" href="/entrar/google">{LOGO_GOOGLE}'
              'Continuar con Google</a><p class="separador">o</p>') if con_google else ""
    # Sin correo que llegue, registrarse y recuperar la clave no se pueden
    # terminar: no se ofrecen, y se manda a pedirle la cuenta al equipo.
    # Con Google, la cuenta nueva se crea igual: el correo ya viene verificado.
    if con_registro:
        enlaces = ('<a href="/olvide">¿Olvidaste tu contraseña?</a>'
                   '<a href="/registro">¿No tienes cuenta? Regístrate</a>')
    elif con_google:
        enlaces = ('<a href="/entrar/google">¿No tienes cuenta? Créala con Google</a>'
                   f'<a href="{CONTACTO}">¿Olvidaste tu contraseña? Escríbenos</a>')
    else:
        enlaces = f'<a href="{CONTACTO}">¿No tienes cuenta u olvidaste la contraseña? Escríbenos</a>'
    return pagina("Entrar", f"""
  <h1>Entra a tu consola</h1>
  <p>Tus loteos, tus planos y tus reservas, en un solo lugar.</p>
  {_aviso(error)}{_aviso(aviso, "ok")}
  {google}
  <form method="post" action="/entrar">
    <label class="campo"><span>Correo</span>
      <input name="email" type="email" autocomplete="username" autofocus required></label>
    <label class="campo"><span>Contraseña</span>
      <input name="clave" type="password" autocomplete="current-password" required></label>
    <button class="boton" type="submit">Iniciar sesión</button>
  </form>
  <nav class="entrada__enlaces">{enlaces}</nav>""", estado)


def _formulario_de_registro(error: str | None = None, campos: dict | None = None,
                            *, con_google: bool, estado: int = 200) -> HTMLResponse:
    campos = campos or {}
    valor = lambda clave: escape(str(campos.get(clave) or ""), quote=True)
    google = (f'<a class="boton boton--google" href="/entrar/google">{LOGO_GOOGLE}'
              'Registrarse con Google</a><p class="separador">o</p>') if con_google else ""
    return pagina("Crear cuenta", f"""
  <h1>Crea tu cuenta</h1>
  <p>Arma y revisa tus planos gratis. Pagas recién cuando publicas un loteo.</p>
  {_aviso(error)}
  {google}
  <form method="post" action="/registro">
    <label class="campo"><span>Tu loteadora</span>
      <input name="loteadora" value="{valor('loteadora')}" autocomplete="organization" required></label>
    <label class="campo"><span>Tu nombre</span>
      <input name="nombre" value="{valor('nombre')}" autocomplete="name" required></label>
    <label class="campo"><span>Correo</span>
      <input name="email" type="email" value="{valor('email')}" autocomplete="email" required></label>
    <label class="campo"><span>Contraseña <i>al menos 10 caracteres</i></span>
      <input name="clave" type="password" autocomplete="new-password" minlength="10" required></label>
    <label class="trampa" aria-hidden="true">No llenar
      <input name="sitio" tabindex="-1" autocomplete="off"></label>
    <button class="boton" type="submit">Crear cuenta</button>
  </form>
  <nav class="entrada__enlaces"><a href="/entrar">¿Ya tienes cuenta? Entra</a></nav>""", estado)


def _revisa_tu_correo(texto: str) -> HTMLResponse:
    return pagina("Revisa tu correo", f"""
  <h1>Revisa tu correo</h1>
  <p>{escape(texto)}</p>
  <p>Si no llega en unos minutos, mira en spam.</p>
  <nav class="entrada__enlaces"><a href="/entrar">Volver a entrar</a></nav>""")


def _enlace_vencido(que: str) -> HTMLResponse:
    return pagina("Enlace vencido", f"""
  <h1>Ese enlace ya no sirve</h1>
  <p>Los enlaces sirven una sola vez y vencen. {escape(que)}</p>
  <nav class="entrada__enlaces"><a href="/entrar">Entrar</a><a href="/olvide">Pedir otro enlace</a></nav>""",
                  400)


def _confirmar_correo(token: str) -> HTMLResponse:
    return pagina("Confirmar correo", f"""
  <h1>Confirma tu correo</h1>
  <p>Con esto terminas de crear tu cuenta y entras.</p>
  <form method="post" action="/verificar">
    <input type="hidden" name="t" value="{escape(token, quote=True)}">
    <button class="boton" type="submit">Confirmar y entrar</button>
  </form>""")


def _formulario_de_clave(token: str, error: str | None = None, estado: int = 200) -> HTMLResponse:
    return pagina("Nueva contraseña", f"""
  <h1>Elige una contraseña nueva</h1>
  {_aviso(error)}
  <form method="post" action="/restablecer">
    <input type="hidden" name="t" value="{escape(token, quote=True)}">
    <label class="campo"><span>Contraseña nueva <i>al menos 10 caracteres</i></span>
      <input name="clave" type="password" autocomplete="new-password" minlength="10" autofocus required></label>
    <button class="boton" type="submit">Guardar y entrar</button>
  </form>""", estado)


def _formulario_de_alta_google(email: str, error: str | None = None, estado: int = 200) -> HTMLResponse:
    return pagina("Crear cuenta", f"""
  <h1>Un paso más</h1>
  <p>Vas a entrar como <strong>{escape(email)}</strong>. ¿Cómo se llama tu loteadora?</p>
  {_aviso(error)}
  <form method="post" action="/registro/google">
    <label class="campo"><span>Tu loteadora</span>
      <input name="loteadora" autocomplete="organization" autofocus required></label>
    <button class="boton" type="submit">Crear cuenta</button>
  </form>""", estado)


# --- ayudas -----------------------------------------------------------------------

def poner_sesion(respuesta: Response, acceso: Acceso, sesion: Sesion, peticion: Request) -> Response:
    respuesta.set_cookie(
        GALLETA, acceso.firmar(sesion), max_age=acceso.horas * 3600, httponly=True,
        samesite="lax", secure=peticion.url.scheme == "https", path="/")
    return respuesta


def url_base(peticion: Request, local: bool) -> str:
    """Dónde vive la consola, para los enlaces de los correos y la vuelta de Google.

    Desplegada sale **solo** de `CONSOLA_URL`. Armarla con la petición dejaría que
    cualquiera, cambiando la cabecera Host, pidiera un enlace de restablecer para
    otro y lo hiciera llegar apuntando a su propio dominio, con el token adentro.
    En este computador no hay a quién engañar y se usa la de la petición.
    """
    fija = os.environ.get("CONSOLA_URL", "").strip()
    if fija:
        return fija.rstrip("/")
    if local:
        return str(peticion.base_url).rstrip("/")
    raise HTTPException(503, "Falta CONSOLA_URL: sin ella no se pueden mandar enlaces por correo.")


def ip_de(peticion: Request, local: bool) -> str:
    """La IP de quien pide.

    Desplegada, Cloud Run agrega la IP real **al final** de `X-Forwarded-For`; lo
    de antes lo escribe quien pide, así que tomar la primera dejaría saltarse
    los topes inventando una por petición.
    """
    reenviada = peticion.headers.get("x-forwarded-for", "")
    if reenviada and not local:
        return reenviada.split(",")[-1].strip()
    return peticion.client.host if peticion.client else "?"


# --- rutas ------------------------------------------------------------------------

def rutas_de_cuentas(acceso: Acceso, cuentas: Cuentas, google: Google | None,
                     limitador: Limitador | None = None) -> APIRouter:
    rutas = APIRouter()
    # Registrarse y pedir enlaces por correo, juntos: 5 por hora por IP.
    limitador = limitador or Limitador(maximo=5, segundos=3600)
    con_google = google is not None

    def cerrado(que: str) -> HTMLResponse | None:
        """La página de "por ahora no", si no hay correo que llegue."""
        if cuentas.registro_abierto:
            return None
        if con_google:
            # Sin correo, Google es la puerta para quien no tiene cuenta.
            return pagina(que, f"""
  <h1>{escape(que)}</h1>
  <p>Por ahora las cuentas nuevas se crean con Google: no necesitas contraseña. Si ya
    tienes una y la olvidaste, entra con Google con ese mismo correo o escríbenos.</p>
  <a class="boton boton--google" href="/entrar/google">{LOGO_GOOGLE}Continuar con Google</a>
  <nav class="entrada__enlaces"><a href="{CONTACTO}">Escribir un correo</a>
    <a href="/entrar">Volver a entrar</a></nav>""")
        return pagina(que, f"""
  <h1>{escape(que)}</h1>
  <p>Por ahora las cuentas las crea el equipo de Tu Masterplan, y también te da una
    contraseña nueva si la olvidaste. Escríbenos y lo dejamos listo.</p>
  <a class="boton" href="{CONTACTO}">Escribir un correo</a>
  <nav class="entrada__enlaces"><a href="/entrar">Volver a entrar</a></nav>""")

    def demasiados() -> HTMLResponse:
        return pagina("Espera un momento", """
  <h1>Demasiados intentos</h1>
  <p>Probaste varias veces seguidas desde esta conexión. Espera una hora y vuelve a intentarlo.</p>
  <nav class="entrada__enlaces"><a href="/entrar">Volver a entrar</a></nav>""", 429)

    # --- Regístrate ----------------------------------------------------------

    @rutas.get("/registro", response_class=HTMLResponse)
    def formulario_de_registro() -> HTMLResponse:
        return cerrado("Crear cuenta") or _formulario_de_registro(con_google=con_google)

    @rutas.post("/registro", response_class=HTMLResponse)
    def registrarse(peticion: Request, loteadora: str = Form(default=""),
                    nombre: str = Form(default=""), email: str = Form(default=""),
                    clave: str = Form(default=""), sitio: str = Form(default="")) -> HTMLResponse:
        if (respuesta := cerrado("Crear cuenta")) is not None:
            return respuesta
        campos = {"loteadora": loteadora, "nombre": nombre, "email": email}
        listo = _revisa_tu_correo("Si el correo es válido, te mandamos un enlace para confirmarlo. "
                                  "Ábrelo y entras directo.")
        # Un robot llena el campo escondido: se le contesta como si hubiera
        # funcionado, para que no aprenda a esquivarlo.
        if sitio:
            return listo
        try:
            datos = validar_registro({**campos, "clave": clave})
        except CuentaInvalida as error:
            return _formulario_de_registro(str(error), campos, con_google=con_google, estado=400)
        if not limitador.permitir(ip_de(peticion, acceso.local)):
            return demasiados()
        cuentas.registrar(datos, url_base(peticion, acceso.local))
        return listo

    @rutas.get("/verificar", response_class=HTMLResponse)
    def confirmar(t: str = "") -> HTMLResponse:
        # Un botón y no el clic en el enlace: así un enlace ajeno no te mete en
        # la cuenta de otro, y los antivirus del correo que abren los enlaces
        # para revisarlos no lo gastan.
        if not t:
            return _enlace_vencido("Entra con tu correo y contraseña: te mandamos otro.")
        return _confirmar_correo(t)

    @rutas.post("/verificar")
    def verificar(peticion: Request, t: str = Form(default="")) -> Response:
        sesion = acceso.sesion_para(cuentas.verificar(t) if t else None)
        if sesion is None:
            return _enlace_vencido("Entra con tu correo y contraseña: te mandamos otro.")
        return poner_sesion(RedirectResponse("/#/planos", status_code=303), acceso, sesion, peticion)

    # --- olvidé mi contraseña ---------------------------------------------------

    @rutas.get("/olvide", response_class=HTMLResponse)
    def formulario_de_olvido() -> HTMLResponse:
        if (respuesta := cerrado("Recuperar contraseña")) is not None:
            return respuesta
        return pagina("Recuperar contraseña", """
  <h1>¿Olvidaste tu contraseña?</h1>
  <p>Escribe tu correo y te mandamos un enlace para elegir una nueva.</p>
  <form method="post" action="/olvide">
    <label class="campo"><span>Correo</span>
      <input name="email" type="email" autocomplete="email" autofocus required></label>
    <button class="boton" type="submit">Mandar enlace</button>
  </form>
  <nav class="entrada__enlaces"><a href="/entrar">Volver a entrar</a></nav>""")

    @rutas.post("/olvide", response_class=HTMLResponse)
    def olvide(peticion: Request, email: str = Form(default="")) -> HTMLResponse:
        if (respuesta := cerrado("Recuperar contraseña")) is not None:
            return respuesta
        if not limitador.permitir(ip_de(peticion, acceso.local)):
            return demasiados()
        cuentas.pedir_restablecer(email.strip().lower(), url_base(peticion, acceso.local))
        # Lo mismo exista o no la cuenta: si no, este formulario diría quién es cliente.
        return _revisa_tu_correo("Si hay una cuenta con ese correo, te llegó un enlace para "
                                 "elegir una contraseña nueva. Vence en 1 hora.")

    @rutas.get("/restablecer", response_class=HTMLResponse)
    def formulario_de_clave(t: str = "") -> HTMLResponse:
        if not t:
            return _enlace_vencido("Pide otro enlace.")
        return _formulario_de_clave(t)

    @rutas.post("/restablecer")
    def restablecer(peticion: Request, t: str = Form(default=""),
                    clave: str = Form(default="")) -> Response:
        try:
            validar_clave(clave)
        except CuentaInvalida as error:
            return _formulario_de_clave(t, str(error), 400)
        sesion = acceso.sesion_para(cuentas.restablecer(t, clave))
        if sesion is None:
            return _enlace_vencido("Pide otro enlace.")
        return poner_sesion(RedirectResponse("/#/planos", status_code=303), acceso, sesion, peticion)

    # --- Google -------------------------------------------------------------------

    @rutas.get("/entrar/google")
    def entrar_con_google(peticion: Request) -> Response:
        if google is None:
            raise HTTPException(404, "entrar con Google no está configurado")
        estado = secrets.token_urlsafe(24)
        respuesta = RedirectResponse(google.url_de_entrada(estado, _vuelta(peticion, acceso.local)), status_code=303)
        respuesta.set_cookie(GALLETA_ESTADO, acceso.sellar({"s": estado}, minutos=10), max_age=600,
                             httponly=True, samesite="lax", secure=peticion.url.scheme == "https",
                             path="/")
        return respuesta

    @rutas.get("/entrar/google/vuelta")
    def vuelta_de_google(peticion: Request, code: str = "", state: str = "") -> Response:
        if google is None:
            raise HTTPException(404, "entrar con Google no está configurado")
        # El estado prueba que esta vuelta es la de una ida que empezó acá, en
        # este navegador: sin eso, cualquiera podría meter a otro en su cuenta.
        guardado = acceso.abrir(peticion.cookies.get(GALLETA_ESTADO)) or {}
        if not code or not state or not secrets.compare_digest(str(guardado.get("s", "")), state):
            return pagina_de_entrada("No se pudo entrar con Google. Vuelve a intentarlo.",
                                     con_google=True, con_registro=cuentas.registro_abierto, estado=400)
        try:
            quien_es = google.identidad(code, _vuelta(peticion, acceso.local))
        except CuentaInvalida as error:
            return pagina_de_entrada(str(error), con_google=True, con_registro=cuentas.registro_abierto, estado=400)

        base = acceso.base
        usuario = base.usuario_por_identidad("google", quien_es.sujeto)
        if usuario is None:
            usuario = base.usuario_por_email(quien_es.email)
            if usuario is not None:
                # Mismo correo, verificado por Google: es la misma persona. Si la
                # cuenta estaba sin confirmar, la clave la puso otro —quizá quien
                # registró este correo sin ser su dueño—: se anula antes de entrar.
                if not usuario.email_verificado:
                    base.anular_credenciales(usuario.id)
                base.enlazar_identidad(usuario.id, "google", quien_es.sujeto)
                base.marcar_verificado(usuario.id)
                usuario = base.usuario(usuario.id)
        if usuario is None:
            respuesta = RedirectResponse("/registro/google", status_code=303)
            respuesta.set_cookie(GALLETA_ALTA, acceso.sellar(
                {"s": quien_es.sujeto, "e": quien_es.email, "n": quien_es.nombre}, minutos=15),
                max_age=900, httponly=True, samesite="lax",
                secure=peticion.url.scheme == "https", path="/")
            respuesta.delete_cookie(GALLETA_ESTADO, path="/")
            return respuesta
        sesion = acceso.sesion_para(usuario)
        if sesion is None:
            return pagina_de_entrada("Esa cuenta está desactivada.", con_google=True, con_registro=cuentas.registro_abierto, estado=403)
        respuesta = poner_sesion(RedirectResponse("/#/planos", status_code=303), acceso, sesion, peticion)
        respuesta.delete_cookie(GALLETA_ESTADO, path="/")
        return respuesta

    @rutas.get("/registro/google", response_class=HTMLResponse)
    def formulario_de_alta_google(peticion: Request) -> HTMLResponse:
        alta = acceso.abrir(peticion.cookies.get(GALLETA_ALTA))
        if not alta:
            return pagina_de_entrada("Se venció el paso por Google. Vuelve a intentarlo.",
                                     con_google=con_google, con_registro=cuentas.registro_abierto, estado=400)
        return _formulario_de_alta_google(alta["e"])

    @rutas.post("/registro/google")
    def alta_con_google(peticion: Request, loteadora: str = Form(default="")) -> Response:
        alta = acceso.abrir(peticion.cookies.get(GALLETA_ALTA))
        if not alta:
            return pagina_de_entrada("Se venció el paso por Google. Vuelve a intentarlo.",
                                     con_google=con_google, con_registro=cuentas.registro_abierto, estado=400)
        if not loteadora.strip():
            return _formulario_de_alta_google(alta["e"], "Falta el nombre de tu loteadora.", 400)
        base = acceso.base
        try:
            usuario = base.crear_cuenta_propia(loteadora.strip()[:160], alta["e"], alta["n"], None,
                                               verificado=True)
        except EmailYaExiste:
            # Alguien creó la cuenta entre la ida y la vuelta: que entre normal.
            return pagina_de_entrada("Ese correo ya tiene cuenta. Entra con Google de nuevo.",
                                     con_google=True, con_registro=cuentas.registro_abierto, estado=409)
        base.enlazar_identidad(usuario.id, "google", alta["s"])
        sesion = acceso.sesion_para(usuario)
        respuesta = poner_sesion(RedirectResponse("/#/planos", status_code=303), acceso, sesion, peticion)
        respuesta.delete_cookie(GALLETA_ALTA, path="/")
        return respuesta

    return rutas


def _vuelta(peticion: Request, local: bool) -> str:
    return f"{url_base(peticion, local)}/entrar/google/vuelta"


__all__ = ["LIBRES_DE_CUENTAS", "pagina_de_entrada", "poner_sesion", "rutas_de_cuentas"]
