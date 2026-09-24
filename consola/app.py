"""La consola de Tu Masterplan: subir un loteo, construirlo, revisarlo y publicarlo.

Corre en la máquina donde están las fotos —una carpeta de panorámicas pesa unos
200 MB y no tiene sentido subirlas a ningún lado para procesarlas acá al lado—, así
que el servidor escucha en localhost y sirve una sola página.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from pipeline import config

from .acceso import GALLETA, Acceso, Sesion, desde_el_entorno
from .comandos import Comandos, encadenar
from .proyectos import Proyecto, Registro, Subida
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
              comandos=None, acceso: Acceso | None = None) -> FastAPI:
    registro = registro or Registro(crm_por_defecto=config.csv_del_crm())
    trabajos = trabajos or Trabajos(directorio=config.RAIZ)
    comandos = comandos or Comandos()
    acceso = acceso if acceso is not None else desde_el_entorno()

    app = FastAPI(title="Tu Masterplan — consola", docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def puerta(peticion: Request, seguir):
        """Una sola puerta para todo: una ruta nueva no puede olvidarse de cerrarla."""
        if acceso.desprotegida:
            return JSONResponse(status_code=503, content={"detail":
                "La consola está desplegada sin contraseña. Define CONSOLA_CLAVE "
                "(y CONSOLA_SECRETO) antes de abrirla."})
        ruta = peticion.url.path
        if not acceso.exigida or ruta in LIBRES or acceso.leer(peticion.cookies.get(GALLETA)):
            return await seguir(peticion)
        if ruta.startswith("/api/"):
            return JSONResponse(status_code=401, content={"detail": "hay que entrar primero"})
        return RedirectResponse("/entrar", status_code=307)

    # --- entrar y salir ------------------------------------------------------

    @app.get("/entrar", response_class=HTMLResponse)
    def formulario(mal: bool = False) -> HTMLResponse:
        return HTMLResponse(_pagina_de_entrada(mal), status_code=401 if mal else 200)

    @app.post("/entrar")
    def entrar(peticion: Request, clave: str = Form(default="")) -> Response:
        if not acceso.es_valida(clave):
            return HTMLResponse(_pagina_de_entrada(mal=True), status_code=401)
        respuesta = RedirectResponse("/", status_code=303)
        respuesta.set_cookie(
            GALLETA, acceso.firmar(Sesion(quien="equipo")),
            max_age=acceso.horas * 3600, httponly=True, samesite="lax",
            secure=peticion.url.scheme == "https", path="/")
        return respuesta

    @app.post("/salir")
    def salir() -> Response:
        respuesta = RedirectResponse("/entrar", status_code=303)
        respuesta.delete_cookie(GALLETA, path="/")
        return respuesta

    def buscar(slug: str) -> Proyecto:
        try:
            return registro.ver(slug)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

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
    def sesion() -> dict:
        return {"exigida": acceso.exigida}

    # --- proyectos -----------------------------------------------------------

    @app.get("/api/proyectos")
    def listar() -> list[dict]:
        return [_como_json(p, trabajos) for p in registro.listar()]

    @app.post("/api/proyectos", status_code=201)
    async def crear(nombre: str = Form(...), archivos: list[UploadFile] = File(...)) -> dict:
        subidas = [Subida(ruta=a.filename or "", contenido=await a.read()) for a in archivos]
        try:
            proyecto = registro.crear(nombre, subidas)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return _como_json(proyecto, trabajos)

    @app.post("/api/proyectos/vincular", status_code=201)
    def vincular(ruta: str = Body(..., embed=True)) -> dict:
        try:
            proyecto = registro.vincular(Path(ruta))
        except FileNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return _como_json(proyecto, trabajos)

    @app.patch("/api/proyectos/{slug}")
    def ajustar(slug: str, campos: dict = Body(...)) -> dict:
        buscar(slug)
        permitidos = ("nombre", "etapa", "whatsapp", "parcelacion", "despegue", "referencias")
        return _como_json(registro.ajustar(slug, {c: campos.get(c) for c in permitidos}), trabajos)

    @app.delete("/api/proyectos/{slug}", status_code=204)
    def olvidar(slug: str) -> None:
        buscar(slug)
        registro.olvidar(slug)

    # --- acciones ------------------------------------------------------------

    @app.post("/api/proyectos/{slug}/construir", status_code=202)
    def construir(slug: str, opciones: dict = Body(default={})) -> dict:
        proyecto = buscar(slug)
        sin_imagenes = bool(opciones.get("sin_imagenes"))
        # El control de calce va pegado a la construcción: es lo que hay que mirar
        # antes de publicar, y pedirlo aparte se olvida.
        return lanzar(proyecto, "construir", encadenar(
            comandos.construir(proyecto, sin_imagenes=sin_imagenes),
            comandos.control_de_calce(proyecto),
        ))

    @app.post("/api/proyectos/{slug}/publicar", status_code=202)
    def publicar(slug: str, opciones: dict = Body(default={})) -> dict:
        proyecto = buscar(slug)
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
                      al_terminar=_anotar_publicacion(registro, proyecto, nombre))

    @app.get("/api/trabajos/{identificador}")
    def ver_trabajo(identificador: str, desde: int = 0) -> dict:
        try:
            return trabajos.ver(identificador).como_json(desde)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    # --- archivos generados --------------------------------------------------

    @app.get("/calce/{slug}/{archivo}")
    def calce(slug: str, archivo: str) -> FileResponse:
        proyecto = buscar(slug)
        if archivo not in proyecto.control_de_calce():
            raise HTTPException(404, "esa imagen de control no existe")
        return FileResponse(proyecto.salida.qa / archivo, media_type="image/jpeg")

    return app


def _anotar_publicacion(registro: Registro, proyecto: Proyecto, nombre: str):
    """Guarda el nombre y la URL que devolvió el hosting, no los que supusimos."""
    rastro = proyecto.salida.base / "publicacion.json"

    def guardar(trabajo) -> None:
        if trabajo.estado != "listo":
            return
        datos = json.loads(rastro.read_text(encoding="utf-8")) if rastro.is_file() else {}
        registro.anotar_publicacion(
            proyecto.slug,
            vercel_proyecto=datos.get("proyecto") or nombre,
            url=datos.get("url") or url_propuesta(proyecto.slug))

    return guardar


def _pagina_de_entrada(mal: bool = False) -> str:
    plantilla = (WEB / "entrar.html").read_text(encoding="utf-8")
    error = ('<p class="aviso">La contraseña no es esa.</p>' if mal else "")
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


app = crear_app()
