"""La consola de Tu Masterplan: subir un loteo, construirlo, revisarlo y publicarlo.

Corre donde están las fotos —una carpeta de panorámicas pesa unos 200 MB y no tiene
sentido moverlas para procesarlas acá al lado— y sirve una sola página.

**Cómo se evita que un cliente vea lo de otro.** El middleware `puerta` es la única
entrada: resuelve quién pide y deja la sesión en la petición. Las rutas no reciben
un `cliente_id` que se pueda olvidar de filtrar: reciben `registro.para(sesion)`, una
vista que solo alcanza los loteos de esa loteadora. Pedir uno ajeno da 404, no 403:
contestar "existe pero no es tuyo" ya es contar algo.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from pipeline import config

from .acceso import GALLETA, Acceso, Sesion, desde_el_entorno
from .comandos import Comandos, encadenar
from .datos import Base, NoEncontrado, ProyectoYaExiste
from .proyectos import Proyecto, Registro, Subida, Vista
from .trabajos import Trabajos

WEB = Path(__file__).resolve().parent / "web"

# Cada loteo se publica como un proyecto propio en el hosting, llamado
# `masterplan-<slug>`. Ese nombre y la URL resultante se GUARDAN al publicar por
# primera vez (`Proyecto.vercel_proyecto` / `url_publicada`); lo de acá abajo es
# solo la propuesta para un loteo que todavía no se publicó. Adivinar la URL era
# lo que hacía que la consola mostrara enlaces rotos.
PREFIJO_VERCEL = "masterplan"


def nombre_propuesto(slug: str) -> str:
    return f"{PREFIJO_VERCEL}-{slug}"


def url_propuesta(slug: str) -> str:
    dominio = os.environ.get("MASTERPLAN_DOMINIO", "").strip().lstrip(".")
    if dominio:
        return f"https://{slug}.{dominio}"
    return f"https://{nombre_propuesto(slug)}.vercel.app"


# Lo único que se puede pedir sin haber entrado: la propia página de entrada y lo
# que necesita para verse.
LIBRES = ("/entrar", "/salir", "/consola.css", "/fuente.woff2")


def crear_app(registro: Registro | None = None, trabajos: Trabajos | None = None,
              comandos=None, acceso: Acceso | None = None, base: Base | None = None) -> FastAPI:
    acceso = acceso if acceso is not None else desde_el_entorno(base)
    base = base if base is not None else acceso.base
    registro = registro or Registro(base=base, crm_por_defecto=config.csv_del_crm())
    trabajos = trabajos or Trabajos(directorio=config.RAIZ)
    comandos = comandos or Comandos()

    # Sin documentación automática ni esquema: la consola tiene una sola página que
    # la usa, y el inventario de rutas lo vigila una prueba, no un JSON público.
    app = FastAPI(title="Tu Masterplan — consola", docs_url=None, redoc_url=None,
                  openapi_url=None)

    @app.middleware("http")
    async def puerta(peticion: Request, seguir):
        """Una sola puerta para todo: una ruta nueva no puede olvidarse de cerrarla."""
        if acceso.desprotegida:
            return JSONResponse(status_code=503, content={"detail":
                "La consola no tiene secreto de firma. Define CONSOLA_SECRETO "
                "antes de desplegarla."})
        ruta = peticion.url.path
        if ruta in LIBRES:
            return await seguir(peticion)
        sesion = acceso.leer(peticion.cookies.get(GALLETA))
        if sesion is None:
            if ruta.startswith("/api/"):
                return JSONResponse(status_code=401, content={"detail": "hay que entrar primero"})
            return RedirectResponse("/entrar", status_code=307)
        peticion.state.sesion = sesion
        return await seguir(peticion)

    def quien(peticion: Request) -> Sesion:
        return peticion.state.sesion

    def vista(sesion: Sesion = Depends(quien)) -> Vista:
        """Los loteos de quien pide, y ningún otro."""
        return registro.para(sesion)

    # --- entrar y salir ------------------------------------------------------

    @app.get("/entrar", response_class=HTMLResponse)
    def formulario(mal: bool = False) -> HTMLResponse:
        return HTMLResponse(_pagina_de_entrada(mal), status_code=401 if mal else 200)

    @app.post("/entrar")
    def entrar(peticion: Request, email: str = Form(default=""),
               clave: str = Form(default="")) -> Response:
        sesion = acceso.entrar(email, clave)
        if sesion is None:
            # Un solo mensaje para clave mala, correo inexistente y cuenta
            # desactivada: distinguirlos convierte el formulario en un buscador.
            return HTMLResponse(_pagina_de_entrada(mal=True), status_code=401)
        respuesta = RedirectResponse("/", status_code=303)
        respuesta.set_cookie(
            GALLETA, acceso.firmar(sesion),
            max_age=acceso.horas * 3600, httponly=True, samesite="lax",
            secure=peticion.url.scheme == "https", path="/")
        return respuesta

    @app.post("/salir")
    def salir() -> Response:
        respuesta = RedirectResponse("/entrar", status_code=303)
        respuesta.delete_cookie(GALLETA, path="/")
        return respuesta

    @app.post("/api/clave")
    def cambiar_clave(campos: dict = Body(...), sesion: Sesion = Depends(quien)) -> Response:
        """Cambiar la propia clave. Corta también las sesiones abiertas, la de acá
        incluida: es lo que uno espera al cambiarla porque sospecha de alguien."""
        if acceso.entrar(sesion.quien, str(campos.get("actual") or "")) is None:
            raise HTTPException(403, "la clave actual no es esa")
        nueva = str(campos.get("nueva") or "")
        if len(nueva) < 10:
            raise HTTPException(400, "la clave nueva tiene que tener al menos 10 caracteres")
        base.cambiar_clave(sesion.quien, nueva)
        respuesta = JSONResponse({"listo": True})
        respuesta.delete_cookie(GALLETA, path="/")
        return respuesta

    def lanzar(proyecto: Proyecto, accion: str, comando: list[str], al_terminar=None) -> dict:
        try:
            identificador = trabajos.lanzar(proyecto.slug, accion, comando,
                                            al_terminar=al_terminar)
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error
        return {"id": identificador}

    # --- página --------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def pagina() -> str:
        return (WEB / "index.html").read_text(encoding="utf-8")

    @app.get("/consola.css")
    def hoja() -> FileResponse:
        return FileResponse(WEB / "consola.css", media_type="text/css")

    @app.get("/consola.js")
    def guion() -> FileResponse:
        return FileResponse(WEB / "consola.js", media_type="text/javascript")

    @app.get("/fuente.woff2")
    def fuente() -> FileResponse:
        """La misma tipografía que el sitio publicado, servida desde el repo."""
        return FileResponse(config.PLANTILLA_WEB / "vendor" / "fuentes" / "plus-jakarta-sans-latin.woff2",
                            media_type="font/woff2")

    @app.get("/api/sesion")
    def sesion(quien_es: Sesion = Depends(quien)) -> dict:
        return {
            "quien": quien_es.quien,
            "rol": quien_es.rol,
            "cliente": base.cliente(quien_es.cliente_id).nombre,
            "debe_cambiar_clave": quien_es.debe_cambiar_clave,
            # La carpeta del disco solo se puede vincular donde está el disco.
            "puede_vincular": acceso.local,
        }

    # --- proyectos -----------------------------------------------------------

    @app.get("/api/proyectos")
    def listar(mios: Vista = Depends(vista)) -> list[dict]:
        return [_como_json(p, trabajos) for p in mios.listar()]

    @app.post("/api/proyectos", status_code=201)
    async def crear(peticion: Request, nombre: str = Form(...),
                    archivos: list[UploadFile] = File(...)) -> dict:
        mios = registro.para(peticion.state.sesion)
        subidas = [Subida(ruta=a.filename or "", contenido=await a.read()) for a in archivos]
        try:
            proyecto = mios.crear(nombre, subidas)
        except (ValueError, ProyectoYaExiste) as error:
            raise HTTPException(400, str(error)) from error
        return _como_json(proyecto, trabajos)

    @app.post("/api/proyectos/vincular", status_code=201)
    def vincular(ruta: str = Body(..., embed=True), mios: Vista = Depends(vista)) -> dict:
        # Registrar una ruta cualquiera del servidor sería leer su disco. Tiene
        # sentido en el computador donde están las fotos y en ningún otro lado.
        if not acceso.local:
            raise HTTPException(403, "vincular carpetas solo funciona en el computador "
                                     "donde están las fotos")
        try:
            proyecto = mios.vincular(Path(ruta))
        except FileNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except (ValueError, ProyectoYaExiste) as error:
            raise HTTPException(400, str(error)) from error
        return _como_json(proyecto, trabajos)

    @app.patch("/api/proyectos/{slug}")
    def ajustar(slug: str, campos: dict = Body(...), mios: Vista = Depends(vista)) -> dict:
        try:
            return _como_json(mios.ajustar(slug, campos), trabajos)
        except ProyectoYaExiste as error:
            raise HTTPException(400, str(error)) from error

    @app.delete("/api/proyectos/{slug}", status_code=204)
    def olvidar(slug: str, mios: Vista = Depends(vista)) -> None:
        mios.olvidar(slug)

    # --- acciones ------------------------------------------------------------

    @app.post("/api/proyectos/{slug}/construir", status_code=202)
    def construir(slug: str, opciones: dict = Body(default={}),
                  mios: Vista = Depends(vista)) -> dict:
        proyecto = mios.ver(slug)
        sin_imagenes = bool(opciones.get("sin_imagenes"))
        # El control de calce va pegado a la construcción: es lo que hay que mirar
        # antes de publicar, y pedirlo aparte se olvida.
        return lanzar(proyecto, "construir", encadenar(
            comandos.construir(proyecto, sin_imagenes=sin_imagenes),
            comandos.control_de_calce(proyecto),
        ))

    @app.post("/api/proyectos/{slug}/publicar", status_code=202)
    def publicar(slug: str, opciones: dict = Body(default={}),
                 mios: Vista = Depends(vista)) -> dict:
        proyecto = mios.ver(slug)
        if not proyecto.construido:
            raise HTTPException(409, "todavía no está construido")
        # Publicar deja el loteo a la vista de cualquiera con el enlace, con sus
        # precios y sus estados. Que no baste un clic ni un POST suelto.
        if not opciones.get("confirmado"):
            raise HTTPException(428, "hay que confirmar la publicación")

        # La primera vez hay que crear el proyecto en el hosting; después no, y
        # pedirlo de nuevo sería intentar pisar uno existente.
        primera_vez = proyecto.vercel_proyecto is None
        nombre = proyecto.vercel_proyecto or nombre_propuesto(proyecto.slug)
        return lanzar(proyecto, "publicar",
                      comandos.publicar(proyecto, vercel_proyecto=nombre, crear=primera_vez),
                      al_terminar=_anotar_publicacion(mios, proyecto, nombre))

    @app.get("/api/trabajos/{identificador}")
    def ver_trabajo(identificador: str, desde: int = 0,
                    mios: Vista = Depends(vista)) -> dict:
        try:
            trabajo = trabajos.ver(identificador)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        # El avance de una construcción dice de qué loteo es y qué está pasando:
        # se pide como se pide el loteo.
        mios.ver(trabajo.proyecto)
        return trabajo.como_json(desde)

    # --- archivos generados --------------------------------------------------

    @app.get("/calce/{slug}/{archivo}")
    def calce(slug: str, archivo: str, mios: Vista = Depends(vista)) -> FileResponse:
        proyecto = mios.ver(slug)
        if archivo not in proyecto.control_de_calce():
            raise HTTPException(404, "esa imagen de control no existe")
        return FileResponse(proyecto.salida.qa / archivo, media_type="image/jpeg")

    @app.exception_handler(NoEncontrado)
    async def no_encontrado(peticion: Request, error: NoEncontrado):
        """Lo que no existe y lo que es de otro se contestan igual."""
        return JSONResponse(status_code=404, content={"detail": str(error)})

    return app


def _anotar_publicacion(mios: Vista, proyecto: Proyecto, nombre: str):
    """Guarda el nombre y la URL que devolvió el hosting, no los que supusimos."""
    rastro = proyecto.salida.base / "publicacion.json"

    def guardar(trabajo) -> None:
        if trabajo.estado != "listo":
            return
        datos = json.loads(rastro.read_text(encoding="utf-8")) if rastro.is_file() else {}
        mios.anotar_publicacion(
            proyecto.slug,
            vercel_proyecto=datos.get("proyecto") or nombre,
            url=datos.get("url") or url_propuesta(proyecto.slug))

    return guardar


def _pagina_de_entrada(mal: bool = False) -> str:
    plantilla = (WEB / "entrar.html").read_text(encoding="utf-8")
    error = ('<p class="aviso">El correo o la contraseña no son esos.</p>' if mal else "")
    return plantilla.replace("<!--ERROR-->", error)


def _como_json(proyecto: Proyecto, trabajos: Trabajos) -> dict:
    ultimo = trabajos.ultimo(proyecto.slug)
    return {
        "slug": proyecto.slug,
        "nombre": proyecto.nombre,
        "etapa": proyecto.etapa,
        "whatsapp": proyecto.whatsapp,
        "despegue": list(proyecto.despegue) if proyecto.despegue else None,
        "referencias": list(proyecto.referencias),
        "fuentes": str(proyecto.fuentes),
        "fuentes_encontradas": proyecto.fuentes_encontradas(),
        "construido": proyecto.construido,
        "resumen": proyecto.resumen(),
        "calce": proyecto.control_de_calce(),
        "url": proyecto.url_publicada or url_propuesta(proyecto.slug),
        "publicado": proyecto.publicado,
        "trabajo": ultimo.como_json() if ultimo and not ultimo.terminado else None,
    }

