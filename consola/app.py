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

import hmac
import json
import logging
import os
import re
import sys
import threading
import traceback
import unicodedata
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import (
    Body,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from pipeline import config, visor
from pipeline.kmz import leer_kmz
from pipeline.plano.digitalizar import SALIDA as DIGITALIZADO, escribir_json

from .acceso import GALLETA, Acceso, Sesion, desde_el_entorno
from .cierra import Cierra, Cifrador, Conexiones, cierra_del_entorno
from .comandos import Comandos, encadenar
from .cuentas import Cuentas, Google, correo_del_entorno, google_del_entorno
from .datos import (
    Base,
    ClienteYaExiste,
    DisenoYaExiste,
    EmailYaExiste,
    KmzYaExiste,
    NoEncontrado,
    ProyectoYaExiste,
)
from .disenos import DisenoInvalido, Disenos, VistaDisenos
from .disenos import como_json as diseno_json
from .inventario import poner_al_dia, poner_datos_del_loteo, revisar_cierra
from .kmzs import NombreInvalido, RegistroKmz, VistaKmz, slug_de_clave
from .kmzs import clave as clave_kmz
from .plano import LotesSinNumero, Plano, PlanoInvalido, PlanoNoListo
from .plantilla import MIME_XLSX, plantilla
from .proyectos import KMZ as KMZ_DEL_MASTER
from .proyectos import KmzExistente, LimiteAlcanzado, Limites, Proyecto, Registro, Subida, Vista
from .republicar import republicar
from .reservas import Reservas
from .rutas_cierra import rutas_de_cierra, sincronizar_antes_de_construir
from .rutas_cuentas import (
    LIBRES_DE_CUENTAS,
    pagina_de_entrada,
    poner_sesion,
    rutas_de_cuentas,
    url_base,
)
from .rutas_reservas import PUBLICAS as PUBLICAS_DE_RESERVAS
from .rutas_reservas import rutas_de_reservas
from .trabajos import Trabajos

WEB = Path(__file__).resolve().parent / "web"

# Los módulos de la página. Se sirven por nombre de una lista cerrada, no
# cualquier archivo de la carpeta: una ruta que arma rutas de disco con lo que
# llega en la URL es una ruta para leer el disco.
MODULOS = ("app.js", "comun.js", "planos.js", "nuevo.js", "plano.js", "subida.js",
           "cuenta.js", "backoffice.js", "disenos.js", "inventario.js", "cierra.js",
           "vuelo.js", "configuracion.js", "kmz.js", "kmzs.js", "kmz_geometria.js", "kmz_union.js", "lienzo_plano.js",
           "mapa_kmz.js", "sondeo.js", "reservas.js")
# Los que la página toma prestados del visor publicado: la vista previa de un
# diseño se pinta con el mismo código que después lo aplica en el sitio.
MODULOS_DEL_VISOR = ("marca.js",)
# Y las librerías del visor que usa Crea tu KMZ (el mapa para ubicar el plano). Igual
# que los módulos: por nombre, de una lista cerrada.
VENDOR_DEL_VISOR = {"leaflet.js": "text/javascript", "leaflet.css": "text/css"}

TIPOS_LOGO = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
              ".svg": "image/svg+xml"}

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
# La revisión periódica de Cierra la llama Cloud Scheduler, sin sesión: la ruta
# exige su propia clave (`CONSOLA_TAREAS_CLAVE`) y sin ella no existe.
TAREAS = ("/api/tareas/cierra",)
# Lo que pide el sitio publicado de un loteo (reservas): se cuida solo, con origen,
# tope por IP y validación (`consola/rutas_reservas.py`).
LIBRES = ("/entrar", "/salir", "/consola.css", "/fuente.woff2", *LIBRES_DE_CUENTAS, *TAREAS,
          *PUBLICAS_DE_RESERVAS)


def mostrar_registro() -> None:
    """Los avisos de `consola.*` llegan a la salida estándar, desde INFO.

    Sin esto Python solo deja pasar WARNING o más (hypercorn configura sus propios
    registros, no los nuestros), y la línea `[cierra] <slug>: …` de cada revisión
    periódica nunca llegaba a los logs de Cloud Run: el job respondía 200 y no había
    forma de saber qué masters revisó ni si publicó alguno. Se llama en cada
    `crear_app`, así que no agrega un segundo manejador si ya tiene uno.
    """
    consola = logging.getLogger("consola")
    consola.setLevel(logging.INFO)
    if not any(getattr(m, "_de_la_consola", False) for m in consola.handlers):
        manejador = logging.StreamHandler(sys.stdout)
        manejador.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        manejador._de_la_consola = True
        consola.addHandler(manejador)


def crear_app(registro: Registro | None = None, trabajos: Trabajos | None = None,
              comandos=None, acceso: Acceso | None = None, base: Base | None = None,
              disenos: Disenos | None = None, cuentas: Cuentas | None = None,
              google: Google | None | bool = True,
              republicar_al_arrancar: bool | None = None,
              retomar_lecturas_al_arrancar: bool = True,
              cierra: Cierra | None | bool = True, conexiones: Conexiones | None = None,
              kmzs: RegistroKmz | None = None, reservas: Reservas | None = None) -> FastAPI:
    mostrar_registro()
    acceso = acceso if acceso is not None else desde_el_entorno(base)
    base = base if base is not None else acceso.base
    cuentas = cuentas or Cuentas(base=base, correo=correo_del_entorno(acceso.local),
                                 en_segundo_plano=True)
    # Los avisos de reserva salen por el mismo correo que los de las cuentas.
    reservas = reservas or Reservas(base=base, correo=cuentas.correo)
    # `True` = lo que diga el entorno; las pruebas pasan uno propio o `None`.
    google = google_del_entorno() if google is True else (google or None)
    disenos = disenos or Disenos(base=base)
    cierra = cierra_del_entorno() if cierra is True else (cierra or None)
    if cierra is not None and conexiones is None:
        conexiones = Conexiones(base=base, cifrador=Cifrador(acceso.secreto))
    registro = registro or Registro(base=base, crm_por_defecto=config.csv_del_crm(),
                                    limites=Limites.desde_el_entorno())
    trabajos = trabajos or Trabajos(directorio=config.RAIZ)
    kmzs = kmzs or RegistroKmz(base=base, limites=registro.limites)
    comandos = comandos or Comandos()
    # Solo lo enciende el despliegue (cloudbuild.yaml): en el computador y en las
    # pruebas arrancar la consola no sube nada a ningún lado.
    if republicar_al_arrancar is None:
        republicar_al_arrancar = os.environ.get("CONSOLA_REPUBLICAR_AL_ARRANCAR") == "1"

    @asynccontextmanager
    async def al_arrancar(_app):
        """Las lecturas del plano que la instancia anterior dejó a medias se relanzan
        antes de atender: el primer sondeo que llega acá ya las ve. Solo parte
        subprocesos, así que no demora el arranque. Los loteos publicados con un visor
        viejo, en cambio, se ponen al día en un hilo aparte: la consola atiende desde el
        primer momento, no cuando termina."""
        if retomar_lecturas_al_arrancar:
            retomar_lecturas(kmzs, trabajos, comandos)
        if republicar_al_arrancar:
            _republicar_en_segundo_plano(registro, trabajos, comandos, disenos)
        yield

    # Sin documentación automática ni esquema: la consola tiene una sola página que
    # la usa, y el inventario de rutas lo vigila una prueba, no un JSON público.
    app = FastAPI(title="Tu Masterplan — consola", docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=al_arrancar)

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

    def mis_disenos(sesion: Sesion = Depends(quien)) -> VistaDisenos:
        """Los diseños de quien pide, y ningún otro."""
        return disenos.para(sesion)

    def mis_kmz(sesion: Sesion = Depends(quien)) -> VistaKmz:
        """Los KMZ de quien pide, y ningún otro."""
        return kmzs.para(sesion)

    def solo_plataforma(sesion: Sesion = Depends(quien)) -> Sesion:
        """Lo que puede hacer el equipo de CTP y ninguna loteadora."""
        if not sesion.es_plataforma:
            raise HTTPException(403, "esto lo hace el equipo de Tu Masterplan")
        return sesion

    # --- entrar y salir ------------------------------------------------------

    @app.get("/entrar", response_class=HTMLResponse)
    def formulario(mal: bool = False) -> HTMLResponse:
        return pagina_de_entrada("El correo o la contraseña no son esos." if mal else None,
                                 con_google=google is not None,
                                 con_registro=cuentas.registro_abierto, estado=401 if mal else 200)

    @app.post("/entrar")
    def entrar(peticion: Request, email: str = Form(default=""),
               clave: str = Form(default="")) -> Response:
        usuario = acceso.credenciales(email, clave)
        # La clave es la suya pero no confirmó el correo: decírselo solo le cuenta
        # algo a quien ya sabe la clave. Se le reenvía el enlace.
        if usuario is not None and not usuario.email_verificado:
            cuentas.enviar_verificacion(usuario, url_base(peticion, acceso.local))
            return pagina_de_entrada(
                aviso=f"Falta confirmar tu correo. Te mandamos el enlace a {usuario.email}.",
                con_google=google is not None, con_registro=cuentas.registro_abierto, estado=403)
        sesion = acceso.sesion_para(usuario)
        if sesion is None:
            # Un solo mensaje para clave mala, correo inexistente y cuenta
            # desactivada: distinguirlos convierte el formulario en un buscador.
            return pagina_de_entrada("El correo o la contraseña no son esos.",
                                     con_google=google is not None,
                                     con_registro=cuentas.registro_abierto, estado=401)
        return poner_sesion(RedirectResponse("/", status_code=303), acceso, sesion, peticion)

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

    def una_a_la_vez(sesion: Sesion, clave: str) -> None:
        """El servidor tiene pocas CPU: cada loteadora corre un trabajo pesado a la vez,
        y cuentan juntas las construcciones de sus masters y las digitalizaciones de sus
        KMZ. `clave` es la del trabajo que se quiere lanzar."""
        if sesion.es_plataforma:
            return
        claves = ([p.slug for p in registro.para(sesion).listar()]
                  + [clave_kmz(k.slug) for k in kmzs.para(sesion).listar()])
        otros = [c for c in claves if c != clave and trabajos.corriendo(c)]
        if len(otros) >= registro.limites.construcciones:
            raise HTTPException(429, "ya tienes otro master construyendo o un KMZ leyendo su plano;"
                                     " lanza este cuando termine ese")

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

    @app.get("/js/{modulo}")
    def guion(modulo: str) -> FileResponse:
        if modulo in MODULOS_DEL_VISOR:
            return FileResponse(config.PLANTILLA_WEB / "js" / modulo, media_type="text/javascript")
        if modulo not in MODULOS:
            raise HTTPException(404, "no existe ese módulo")
        return FileResponse(WEB / "js" / modulo, media_type="text/javascript")

    @app.get("/vendor/{archivo}")
    def libreria(archivo: str) -> FileResponse:
        if archivo not in VENDOR_DEL_VISOR:
            raise HTTPException(404, "no existe ese archivo")
        return FileResponse(config.PLANTILLA_WEB / "vendor" / archivo, media_type=VENDOR_DEL_VISOR[archivo])

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
            # Su propio cliente, que ya conoce: la página lo usa para no ofrecerle
            # suspender su propia loteadora, que es lo único que el back-office no
            # deja hacer.
            "cliente_id": quien_es.cliente_id,
            "cliente": base.cliente(quien_es.cliente_id).nombre,
            "debe_cambiar_clave": quien_es.debe_cambiar_clave,
            # La carpeta del disco solo se puede vincular donde está el disco.
            "puede_vincular": acceso.local,
            # Para avisar antes de subir, no después de mandar un giga. El equipo
            # no tiene topes.
            "limites": None if quien_es.es_plataforma else {
                "megas_por_loteo": registro.limites.megas_por_loteo,
                "sin_pagar": registro.limites.sin_pagar,
            },
        }

    # --- proyectos -----------------------------------------------------------

    @app.get("/api/proyectos")
    def listar(mios: Vista = Depends(vista)) -> list[dict]:
        return [_como_json(p, trabajos) for p in mios.listar()]

    @app.post("/api/proyectos", status_code=201)
    def crear(campos: dict = Body(...), mios: Vista = Depends(vista),
              marcas: VistaDisenos = Depends(mis_disenos)) -> dict:
        """Un master nuevo, a nombre de quien lo pide. Nace sin pagar: se puede
        subir y construir, y publicar espera a que CTP anote el cobro."""
        nombre = str(campos.get("nombre") or "").strip()
        if not nombre:
            raise HTTPException(400, "ponle un nombre al loteo")
        # El diseño se revisa antes de crear: si no sirve, no queda un loteo a medias.
        diseno_id = _diseno_para(marcas, campos.get("diseno_id"), mios.duenio)
        try:
            proyecto = mios.crear(nombre)
        except (ProyectoYaExiste, LimiteAlcanzado) as error:
            raise HTTPException(409, str(error)) from error
        if diseno_id is not None:
            proyecto = mios.asignar_diseno(proyecto.slug, diseno_id)
        return _como_json(proyecto, trabajos)

    @app.get("/api/proyectos/{slug}/portada")
    def ver_portada(slug: str, mios: Vista = Depends(vista)) -> FileResponse:
        archivo = mios.ver(slug).portada()
        if archivo is None:
            raise HTTPException(404, "todavía no hay portada: falta construirlo")
        return FileResponse(archivo, media_type="image/jpeg",
                            headers={"Cache-Control": "private, no-cache"})

    @app.get("/api/plantilla-inventario")
    def plantilla_en_blanco(_: Sesion = Depends(quien)) -> Response:
        return _descarga(plantilla(), "plantilla-inventario.xlsx")

    @app.get("/api/proyectos/{slug}/plantilla")
    def plantilla_del_loteo(slug: str, mios: Vista = Depends(vista)) -> Response:
        """La plantilla con una fila por parcela del KMZ y lo que muestra hoy."""
        proyecto = mios.ver(slug)
        return _descarga(plantilla(proyecto.parcelas() or None, proyecto.nombre),
                         f"inventario-{proyecto.slug}.xlsx")

    @app.post("/api/proyectos/{slug}/archivos", status_code=201)
    async def subir(slug: str, archivos: list[UploadFile] = File(...),
                    mios: Vista = Depends(vista)) -> dict:
        """Sube el vuelo a un loteo que ya existe. Se puede repetir para agregar
        lo que faltó."""
        # El archivo ya está en un temporal del servidor: se copia de ahí al
        # destino, sin cargar cientos de megas en memoria.
        subidas = [Subida(ruta=a.filename or "", contenido=a.file, tamano=a.size)
                   for a in archivos]
        try:
            # Copiar un vuelo entero toma segundos: fuera del bucle de eventos,
            # para no dejar la consola sorda mientras tanto.
            proyecto = await run_in_threadpool(mios.subir, slug, subidas)
        except LimiteAlcanzado as error:
            raise HTTPException(413, str(error)) from error
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        return _como_json(proyecto, trabajos)

    @app.post("/api/proyectos/vincular", status_code=201)
    def vincular(ruta: str = Body(..., embed=True),
                 yo: Sesion = Depends(solo_plataforma)) -> dict:
        # Registrar una ruta cualquiera del servidor sería leer su disco. Tiene
        # sentido en el computador donde están las fotos y en ningún otro lado.
        if not acceso.local:
            raise HTTPException(403, "vincular carpetas solo funciona en el computador "
                                     "donde están las fotos")
        mios = registro.para(yo)
        try:
            proyecto = mios.vincular(Path(ruta))
        except FileNotFoundError as error:
            raise HTTPException(404, str(error)) from error
        except (ValueError, ProyectoYaExiste) as error:
            raise HTTPException(400, str(error)) from error
        return _como_json(proyecto, trabajos)

    @app.patch("/api/proyectos/{slug}")
    def ajustar(slug: str, campos: dict = Body(...), mios: Vista = Depends(vista),
                marcas: VistaDisenos = Depends(mis_disenos)) -> dict:
        proyecto = mios.ver(slug)
        # `diseno_id: null` es volver al diseño por defecto: por eso se mira si
        # vino la clave, no si trae valor. Se revisa antes de escribir nada y se
        # anota al final, para que un error en lo demás no lo deje cambiado.
        cambia_diseno = "diseno_id" in campos
        diseno_id = (_diseno_para(marcas, campos["diseno_id"], proyecto.cliente_id)
                     if cambia_diseno else None)
        try:
            proyecto = mios.ajustar(slug, campos)
        except (ProyectoYaExiste, ValueError) as error:
            raise HTTPException(400, str(error)) from error
        if cambia_diseno:
            proyecto = mios.asignar_diseno(slug, diseno_id)
        return _como_json(proyecto, trabajos)

    @app.delete("/api/proyectos/{slug}", status_code=204)
    def olvidar(slug: str, mios: Vista = Depends(vista)) -> None:
        mios.ver(slug)
        # Quitar uno sin pagar borra sus archivos: no mientras el pipeline los lee.
        if trabajos.corriendo(slug):
            raise HTTPException(409, "está construyendo o publicando; espera a que termine")
        mios.olvidar(slug)

    # --- acciones ------------------------------------------------------------

    @app.post("/api/proyectos/{slug}/construir", status_code=202)
    def construir(slug: str, opciones: dict = Body(default={}),
                  mios: Vista = Depends(vista), yo: Sesion = Depends(quien)) -> dict:
        proyecto = mios.ver(slug)
        # Un master recién creado todavía no tiene KMZ.
        if not config.kmz_en(proyecto.fuentes):
            raise HTTPException(409, "falta el KMZ: súbelo o elige uno de Mis KMZ")
        una_a_la_vez(yo, slug)
        sin_imagenes = bool(opciones.get("sin_imagenes"))
        # Con una construcción en curso, `lanzar` contesta 409: no se le cambia el
        # inventario por debajo a la que está leyendo.
        aviso = (None if trabajos.corriendo(slug)
                 else sincronizar_antes_de_construir(cierra, conexiones, proyecto))
        pasos = [comandos.construir(proyecto, sin_imagenes=sin_imagenes),
                 # El control de calce va pegado a la construcción: es lo que hay
                 # que mirar antes de publicar, y pedirlo aparte se olvida.
                 comandos.control_de_calce(proyecto)]
        al_terminar = _aplicar_diseno(mios, disenos, slug)
        accion = "construir"
        # Con `publicar`, un loteo que ya está en línea queda al día en el sitio
        # también (lo pide "Actualizar desde Cierra"): si no, la consola muestra
        # los precios nuevos y el comprador sigue viendo los viejos. Solo si ya
        # estaba publicado y pagado: la primera publicación se confirma a mano.
        if opciones.get("publicar") and proyecto.publicado and proyecto.pagado and proyecto.vercel_proyecto:
            # El diseño se escribe antes: la construcción no lo toca y la
            # publicación tiene que salir con la marca puesta.
            disenos.escribir_en_sitio(proyecto.diseno_id, proyecto.salida.datos)
            pasos.append(comandos.publicar(proyecto, vercel_proyecto=proyecto.vercel_proyecto))
            al_terminar = _en_orden(al_terminar,
                                    _anotar_publicacion(mios, proyecto, proyecto.vercel_proyecto))
            accion = "actualizar"
        lanzado = lanzar(proyecto, accion, encadenar(*pasos), al_terminar=al_terminar)
        return {**lanzado, "aviso": aviso} if aviso else lanzado

    @app.post("/api/proyectos/{slug}/publicar", status_code=202)
    def publicar(slug: str, opciones: dict = Body(default={}),
                 mios: Vista = Depends(vista)) -> dict:
        proyecto = mios.ver(slug)
        if not proyecto.construido:
            raise HTTPException(409, "todavía no está construido")
        # El único control de cobro: un loteo se arma gratis, se publica pagado.
        if not proyecto.pagado:
            raise HTTPException(402, "este loteo todavía no está habilitado para "
                                     "publicarse: escríbenos y lo dejamos listo")
        # Publicar deja el loteo a la vista de cualquiera con el enlace, con sus
        # precios y sus estados. Que no baste un clic ni un POST suelto.
        if not opciones.get("confirmado"):
            raise HTTPException(428, "hay que confirmar la publicación")

        # El diseño, el nombre y el WhatsApp se escriben recién ahora, con los que
        # tenga el loteo en este momento: cambiarlos no obliga a reconstruir.
        disenos.escribir_en_sitio(proyecto.diseno_id, proyecto.salida.datos)
        poner_datos_del_loteo(proyecto)

        # La primera vez hay que crear el proyecto en el hosting; después no, y
        # pedirlo de nuevo sería intentar pisar uno existente.
        primera_vez = proyecto.vercel_proyecto is None
        nombre = proyecto.vercel_proyecto or nombre_propuesto(proyecto.slug)
        return lanzar(proyecto, "publicar",
                      comandos.publicar(proyecto, vercel_proyecto=nombre, crear=primera_vez),
                      al_terminar=_anotar_publicacion(mios, proyecto, nombre))

    # --- mis KMZ: del plano aprobado a un KMZ propio, sin master ---------------------
    #
    # Lo que hacen está en `consola/plano.py` y `consola/kmzs.py`; acá, quién puede y
    # cuándo. Todas resuelven el KMZ con `mis.ver`/`mis.plano`: el de otra es un 404.

    def kmz_libre(slug: str) -> None:
        """Lo que reescribe el plano o el KMZ, o lo borra, no se hace mientras se digitaliza."""
        if trabajos.corriendo(clave_kmz(slug)):
            raise HTTPException(409, "se está leyendo el plano de este KMZ; espera a que termine")

    def kmz_json(mis: VistaKmz, guardado) -> dict:
        ultimo = trabajos.ultimo(clave_kmz(guardado.slug))
        return {**mis.resumen(guardado),
                "trabajo": ultimo.como_json() if ultimo and not ultimo.terminado else None}

    @app.get("/api/kmz")
    def listar_kmz(mis: VistaKmz = Depends(mis_kmz)) -> list[dict]:
        return [kmz_json(mis, k) for k in mis.listar()]

    @app.post("/api/kmz", status_code=201)
    def crear_kmz(campos: dict = Body(...), mis: VistaKmz = Depends(mis_kmz)) -> dict:
        try:
            return kmz_json(mis, mis.crear(campos.get("nombre")))
        except NombreInvalido as error:
            raise HTTPException(400, str(error)) from error
        except KmzYaExiste as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/kmz/{slug}")
    def ver_kmz(slug: str, mis: VistaKmz = Depends(mis_kmz)) -> dict:
        guardado = mis.ver(slug)
        estado = mis.plano(slug).estado()
        ultimo = trabajos.ultimo(clave_kmz(slug))
        return {**estado, "slug": guardado.slug, "nombre": guardado.nombre,
                "trabajo": ultimo.como_json() if ultimo else None}

    @app.patch("/api/kmz/{slug}")
    def renombrar_kmz(slug: str, campos: dict = Body(...),
                      mis: VistaKmz = Depends(mis_kmz)) -> dict:
        try:
            return kmz_json(mis, mis.renombrar(slug, campos.get("nombre")))
        except NombreInvalido as error:
            raise HTTPException(400, str(error)) from error
        except KmzYaExiste as error:
            raise HTTPException(409, str(error)) from error

    @app.delete("/api/kmz/{slug}", status_code=204)
    def borrar_kmz(slug: str, mis: VistaKmz = Depends(mis_kmz)) -> None:
        mis.ver(slug)
        kmz_libre(slug)
        mis.borrar(slug)
        # Su avance no queda para quien cree después otro con el mismo nombre.
        trabajos.olvidar(clave_kmz(slug))

    @app.post("/api/kmz/{slug}/plano", status_code=201)
    async def subir_plano_kmz(slug: str, archivo: UploadFile = File(...),
                              mis: VistaKmz = Depends(mis_kmz)) -> dict:
        mis.ver(slug)
        kmz_libre(slug)
        subida = Subida(ruta=archivo.filename or "plano.pdf", contenido=archivo.file, tamano=archivo.size)
        try:
            # Sacar las páginas de un escaneo grande toma segundos.
            paginas = await run_in_threadpool(mis.subir_plano, slug, subida)
        except LimiteAlcanzado as error:
            raise HTTPException(413, str(error)) from error
        return {"paginas": paginas}

    @app.get("/api/kmz/{slug}/paginas/{n}")
    async def pagina_del_kmz(slug: str, n: int, mini: bool = False, medio: bool = False,
                             mis: VistaKmz = Depends(mis_kmz)) -> FileResponse:
        """`medio`: a lo más 2.400 px, para el editor de la unión. La página 0 es la unión
        de hojas guardada en las entradas; la primera vez se compone (segundos)."""
        plano = mis.plano(slug)
        archivo = await run_in_threadpool(plano.imagen, n, mini, medio)
        if archivo is None:
            raise HTTPException(404, "no hay hojas unidas: guarda la unión antes de pedir la página 0"
                                if n == 0 and plano.hay() else "esa página no existe")
        # Sin caché eterna: la página 0 cambia con la unión (la pantalla pide con `?v=`) y
        # cualquier página cambia si se sube otro PDF; el navegador revalida con el ETag.
        return FileResponse(archivo, media_type="image/jpeg",
                            headers={"Cache-Control": "private, no-cache"})

    @app.post("/api/kmz/{slug}/union/afinar")
    async def afinar_union_kmz(slug: str, union: dict = Body(...),
                               mis: VistaKmz = Depends(mis_kmz)) -> dict:
        """`{"hojas": [...]}` como están en pantalla → las mismas hojas con x, y y angulo
        calzados, más `calzada` y `residuo_mm` por hoja. No guarda nada."""
        plano = mis.plano(slug)
        return await run_in_threadpool(plano.afinar_union, union)

    @app.put("/api/kmz/{slug}/entradas")
    def entradas_del_kmz(slug: str, entradas: dict = Body(...),
                         mis: VistaKmz = Depends(mis_kmz)) -> dict:
        return mis.plano(slug).guardar_entradas(entradas)

    @app.post("/api/kmz/{slug}/digitalizar", status_code=202)
    def digitalizar_kmz(slug: str, mis: VistaKmz = Depends(mis_kmz),
                        yo: Sesion = Depends(quien)) -> dict:
        plano = mis.plano(slug)
        entradas = plano.para_digitalizar()
        una_a_la_vez(yo, clave_kmz(slug))
        try:
            identificador = _lanzar_lectura(plano, entradas, clave_kmz(slug), 1,
                                            trabajos, comandos)
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error
        return {"id": identificador}

    @app.post("/api/kmz/{slug}/georreferenciar")
    async def georreferenciar_kmz(slug: str, mis: VistaKmz = Depends(mis_kmz)) -> dict:
        plano = mis.plano(slug)
        if trabajos.corriendo(clave_kmz(slug)):
            raise HTTPException(409, "se está leyendo el plano; ubícalo cuando termine")
        return await run_in_threadpool(plano.georreferenciar)

    @app.get("/api/kmz/{slug}/lotes")
    def lotes_del_kmz(slug: str, en: str = "px", mis: VistaKmz = Depends(mis_kmz)) -> dict:
        return mis.plano(slug).lotes(en)

    @app.post("/api/kmz/{slug}/corregir")
    async def corregir_kmz(slug: str, campos: dict = Body(...), mis: VistaKmz = Depends(mis_kmz)) -> dict:
        """Corrección a mano de un vértice en Revisar: `{"accion": "mover", "punto": [lon, lat],
        "a": [lon, lat]}`, `{"accion": "borrar", "punto": [...]}` o `{"accion": "deshacer"}`."""
        plano = mis.plano(slug)
        kmz_libre(slug)
        return await run_in_threadpool(plano.corregir, campos.get("accion"), campos.get("punto"), campos.get("a"))

    @app.post("/api/kmz/{slug}/crear", status_code=201)
    async def escribir_kmz(slug: str, campos: dict | None = Body(None),
                           mis: VistaKmz = Depends(mis_kmz)) -> dict:
        """`{"omitir_sin_numero": true}`: crearlo aunque queden lotes sin número (sin ellos)."""
        plano = mis.plano(slug)
        kmz_libre(slug)
        omitir = (campos or {}).get("omitir_sin_numero") is True
        return await run_in_threadpool(plano.crear_kmz, omitir)

    @app.get("/api/kmz/{slug}/descargar")
    def descargar_kmz(slug: str, mis: VistaKmz = Depends(mis_kmz)) -> FileResponse:
        guardado = mis.ver(slug)
        plano = mis.plano(slug)
        if not plano.terminado():
            raise HTTPException(409, "todavía no está creado: termina los pasos y crea el KMZ")
        return FileResponse(plano.kmz, media_type="application/vnd.google-earth.kmz", headers={
            "Content-Disposition": _adjunto(f"{guardado.nombre}.kmz", f"{guardado.slug}.kmz"),
            "Cache-Control": "private, no-cache"})

    @app.post("/api/proyectos/{slug}/kmz", status_code=201)
    async def usar_kmz(slug: str, opciones: dict = Body(...), mios: Vista = Depends(vista),
                       mis: VistaKmz = Depends(mis_kmz)) -> dict:
        """Pone un KMZ de Mis KMZ en las fuentes del master como `subdivision.kmz`.
        El master y el KMZ se piden como siempre: el de otra es un 404, aunque se
        sepa su slug. El equipo puede usar cualquiera (los ve todos)."""
        mios.ver(slug)
        guardado = mis.ver(str(opciones.get("kmz") or ""))
        plano = mis.plano(guardado.slug)
        if not plano.terminado():
            raise HTTPException(409, "ese KMZ todavía no está creado")
        # No se le cambia el KMZ por debajo a una construcción.
        if trabajos.corriendo(slug):
            raise HTTPException(409, "este master está construyendo o publicando; espera a que termine")
        try:
            lotes = len(await run_in_threadpool(leer_kmz, plano.kmz))
            anteriores = await run_in_threadpool(mios.usar_kmz, slug, plano.kmz,
                                                 bool(opciones.get("confirmar_reemplazo")))
        except LimiteAlcanzado as error:
            raise HTTPException(413, str(error)) from error
        return {"kmz": KMZ_DEL_MASTER, "origen": guardado.slug, "lotes": lotes, "anteriores": anteriores}

    @app.get("/api/trabajos/{identificador}")
    def ver_trabajo(identificador: str, desde: int = 0, mios: Vista = Depends(vista),
                    mis: VistaKmz = Depends(mis_kmz)) -> dict:
        try:
            trabajo = trabajos.ver(identificador)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error
        # El avance de una construcción dice de qué loteo es y qué está pasando:
        # se pide como se pide el loteo (o el KMZ).
        kmz = slug_de_clave(trabajo.proyecto)
        if kmz is not None:
            mis.ver(kmz)
        else:
            mios.ver(trabajo.proyecto)
        return trabajo.como_json(desde)

    # --- mis diseños ------------------------------------------------------------

    @app.get("/api/disenos")
    def listar_disenos(marcas: VistaDisenos = Depends(mis_disenos)) -> list[dict]:
        return [diseno_json(d) for d in marcas.listar()]

    @app.post("/api/disenos", status_code=201)
    def crear_diseno(campos: dict = Body(...),
                     marcas: VistaDisenos = Depends(mis_disenos)) -> dict:
        try:
            return diseno_json(marcas.crear(campos))
        except DisenoYaExiste as error:
            raise HTTPException(409, str(error)) from error

    @app.patch("/api/disenos/{diseno_id}")
    def ajustar_diseno(diseno_id: int, campos: dict = Body(...),
                       marcas: VistaDisenos = Depends(mis_disenos)) -> dict:
        try:
            return diseno_json(marcas.ajustar(diseno_id, campos))
        except DisenoYaExiste as error:
            raise HTTPException(409, str(error)) from error

    @app.delete("/api/disenos/{diseno_id}", status_code=204)
    def borrar_diseno(diseno_id: int, marcas: VistaDisenos = Depends(mis_disenos)) -> None:
        marcas.borrar(diseno_id)

    @app.post("/api/disenos/{diseno_id}/logo")
    async def subir_logo(diseno_id: int, archivo: UploadFile = File(...),
                         marcas: VistaDisenos = Depends(mis_disenos)) -> dict:
        # El logo se lee entero: pesa como mucho medio mega, y se revisa antes
        # de escribir. Se lee uno más para saber si se pasó sin leerlo todo.
        contenido = await archivo.read(512 * 1024 + 1)
        return diseno_json(marcas.subir_logo(diseno_id, archivo.filename or "", contenido))

    @app.delete("/api/disenos/{diseno_id}/logo")
    def quitar_logo(diseno_id: int, marcas: VistaDisenos = Depends(mis_disenos)) -> dict:
        return diseno_json(marcas.quitar_logo(diseno_id))

    @app.get("/api/disenos/{diseno_id}/logo")
    def ver_logo(diseno_id: int, marcas: VistaDisenos = Depends(mis_disenos)) -> FileResponse:
        archivo = disenos.logo_de(marcas.ver(diseno_id))
        if archivo is None:
            raise HTTPException(404, "este diseño no tiene logo")
        # Un SVG abierto directo es un documento: que no pueda correr nada.
        return FileResponse(archivo, media_type=TIPOS_LOGO[archivo.suffix], headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-cache"})

    # --- back-office: solo el equipo de CTP ------------------------------------
    #
    # Todo lo de acá cuelga de /api/plataforma/ a propósito: la guardia se ve en
    # la ruta, así que una que se cuelgue del prefijo sin pedirla salta a la vista
    # leyendo, no solo corriendo las pruebas.

    @app.get("/api/plataforma/clientes")
    def loteadoras(_: Sesion = Depends(solo_plataforma)) -> list[dict]:
        return [_cliente_json(c, base) for c in base.clientes()]

    @app.post("/api/plataforma/clientes", status_code=201)
    def crear_loteadora(campos: dict = Body(...),
                        yo: Sesion = Depends(solo_plataforma)) -> dict:
        """Da de alta una loteadora con su dueño.

        Devuelve la clave provisional **una sola vez**: no se guarda en claro en
        ninguna parte, así que si se pierde hay que generar otra.
        """
        nombre = str(campos.get("nombre") or "").strip()
        email = str(campos.get("email") or "").strip()
        duenio = str(campos.get("duenio") or "").strip() or email
        if not nombre or not email:
            raise HTTPException(400, "hacen falta el nombre de la loteadora y el correo del dueño")
        try:
            cliente, clave = base.crear_cliente(nombre, email, duenio)
        except (ClienteYaExiste, EmailYaExiste) as error:
            raise HTTPException(409, str(error)) from error
        base.anotar("alta de loteadora", cliente_id=cliente.id,
                    usuario_id=yo.usuario_id, detalle=email)
        return {**_cliente_json(cliente, base), "clave_provisional": clave}

    @app.post("/api/plataforma/clientes/{cliente_id}/usuarios", status_code=201)
    def crear_cuenta(cliente_id: int, campos: dict = Body(...),
                     yo: Sesion = Depends(solo_plataforma)) -> dict:
        base.cliente(cliente_id)                       # 404 si no existe
        email = str(campos.get("email") or "").strip()
        nombre = str(campos.get("nombre") or "").strip() or email
        if not email:
            raise HTTPException(400, "falta el correo")
        try:
            usuario, clave = base.crear_usuario(cliente_id, email, nombre)
        except EmailYaExiste as error:
            raise HTTPException(409, str(error)) from error
        base.anotar("alta de cuenta", cliente_id=cliente_id,
                    usuario_id=yo.usuario_id, detalle=email)
        return {"email": usuario.email, "clave_provisional": clave}

    @app.post("/api/plataforma/usuarios/clave")
    def nueva_clave(campos: dict = Body(...), yo: Sesion = Depends(solo_plataforma)) -> dict:
        """Una clave provisional nueva para una cuenta que perdió la suya.

        Sin correo configurado es la única forma de recuperar una cuenta. Se
        muestra una sola vez, corta las sesiones de esa cuenta y queda anotado.
        """
        email = str(campos.get("email") or "").strip().lower()
        if not email:
            raise HTTPException(400, "falta el correo")
        clave = base.nueva_clave_provisional(email)          # 404 si no existe
        usuario = base.usuario_por_email(email)
        base.anotar("clave provisional nueva", cliente_id=usuario.cliente_id,
                    usuario_id=yo.usuario_id, detalle=email)
        return {"email": email, "clave_provisional": clave}

    @app.post("/api/plataforma/clientes/{cliente_id}/estado")
    def cambiar_estado(cliente_id: int, campos: dict = Body(...),
                       yo: Sesion = Depends(solo_plataforma)) -> dict:
        """Suspender corta las sesiones de toda su gente en la petición siguiente."""
        estado = str(campos.get("estado") or "")
        if estado not in ("activo", "suspendido"):
            raise HTTPException(400, "el estado es 'activo' o 'suspendido'")
        cliente = base.cliente(cliente_id)
        if cliente.id == yo.cliente_id:
            # Suspender la propia loteadora deja a CTP sin poder entrar a
            # reactivarla: no hay nadie por encima que lo arregle.
            raise HTTPException(409, "no puedes suspender tu propia loteadora")
        base.reactivar(cliente_id) if estado == "activo" else base.suspender(cliente_id)
        base.anotar(f"loteadora {estado}", cliente_id=cliente_id, usuario_id=yo.usuario_id)
        return _cliente_json(base.cliente(cliente_id), base)

    @app.post("/api/plataforma/clientes/{cliente_id}/proyectos", status_code=201)
    def habilitar_loteo(cliente_id: int, campos: dict = Body(...),
                        yo: Sesion = Depends(solo_plataforma)) -> dict:
        """Habilita un loteo ya pagado, a nombre de una loteadora.

        La nota de cobro es obligatoria y no por burocracia: es lo único que
        distingue un loteo cobrado de uno regalado, porque el cobro pasa fuera
        del sistema. Sin pasarela, esta línea de texto ES el control de pago.
        """
        base.cliente(cliente_id)                       # 404 si no existe
        nombre = str(campos.get("nombre") or "").strip()
        cobro = str(campos.get("nota_cobro") or "").strip()
        if not nombre:
            raise HTTPException(400, "falta el nombre del loteo")
        if not cobro:
            raise HTTPException(402, "falta la nota de cobro: un loteo se habilita cuando se pagó")
        try:
            proyecto = registro.habilitar(cliente_id, nombre, nota_cobro=cobro)
        except ProyectoYaExiste as error:
            raise HTTPException(409, str(error)) from error
        base.anotar("loteo habilitado", cliente_id=cliente_id, usuario_id=yo.usuario_id,
                    detalle=f"{proyecto.slug} · {cobro}")
        return _como_json(proyecto, trabajos)

    @app.post("/api/plataforma/proyectos/{slug}/pago")
    def anotar_pago(slug: str, campos: dict = Body(...),
                    yo: Sesion = Depends(solo_plataforma)) -> dict:
        """Deja publicar un loteo que el cliente se creó solo, porque ya pagó.

        La nota es obligatoria por lo mismo que al habilitar: sin pasarela, es el
        único registro de que se cobró.
        """
        cobro = str(campos.get("nota_cobro") or "").strip()
        if not cobro:
            raise HTTPException(400, "anota cómo se pagó")
        guardado = base.proyecto(slug)                 # 404 si no existe
        if not base.anotar_pago(slug, cobro):
            raise HTTPException(409, "este loteo ya tiene su pago anotado")
        base.anotar("loteo pagado", cliente_id=guardado.cliente_id,
                    usuario_id=yo.usuario_id, detalle=f"{slug} · {cobro}")
        return _como_json(registro.para(yo).ver(slug), trabajos)

    @app.get("/api/plataforma/historial")
    def historial(_: Sesion = Depends(solo_plataforma)) -> list[dict]:
        return [{"que": e.que, "cliente_id": e.cliente_id, "detalle": e.detalle,
                 "cuando": e.cuando.isoformat()} for e in base.historial()]

    # --- archivos generados --------------------------------------------------

    @app.get("/calce/{slug}/{archivo}")
    def calce(slug: str, archivo: str, mios: Vista = Depends(vista)) -> FileResponse:
        proyecto = mios.ver(slug)
        if archivo not in proyecto.control_de_calce():
            raise HTTPException(404, "esa imagen de control no existe")
        return FileResponse(proyecto.salida.qa / archivo, media_type="image/jpeg")

    app.include_router(rutas_de_cuentas(acceso, cuentas, google))
    app.include_router(rutas_de_reservas(reservas, registro, vista, local=acceso.local))
    def publicar_en_linea(proyecto: Proyecto) -> dict:
        """Vuelve a publicar un loteo que ya está en línea, sin preguntar: lo piden
        los estados y precios nuevos, no una persona que decide salir al mundo. La
        primera publicación sigue siendo la de la ruta, con su confirmación."""
        disenos.escribir_en_sitio(proyecto.diseno_id, proyecto.salida.datos)
        poner_datos_del_loteo(proyecto)
        return lanzar(proyecto, "publicar",
                      comandos.publicar(proyecto, vercel_proyecto=proyecto.vercel_proyecto),
                      al_terminar=_anotar_publicacion(registro.todos(), proyecto,
                                                      proyecto.vercel_proyecto))

    app.include_router(rutas_de_cierra(cierra, conexiones, vista, ocupado=trabajos.corriendo,
                                       publicar_en_linea=publicar_en_linea, quien=quien))

    @app.post("/api/proyectos/{slug}/inventario/actualizar")
    def actualizar_inventario(slug: str, mios: Vista = Depends(vista)) -> dict:
        """Los estados y precios del inventario recién subido, sin reconstruir. Si
        trae parcelas que el sitio no tiene, lo dice: eso sí pide reconstruir."""
        proyecto = mios.ver(slug)
        if trabajos.corriendo(slug):
            raise HTTPException(409, "espera a que termine el trabajo en curso")
        try:
            resultado = poner_al_dia(proyecto)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        if resultado.requiere_reconstruir:
            return {"requiere_reconstruir": list(resultado.faltan)}
        return {"cambiadas": len(resultado.cambiadas)}

    @app.post("/api/tareas/cierra")
    def tarea_cierra(peticion: Request) -> dict:
        """Cada 15 minutos (Cloud Scheduler): los loteos conectados a Cierra y en
        línea quedan al día. Sin `CONSOLA_TAREAS_CLAVE` la ruta no existe."""
        esperada = os.environ.get("CONSOLA_TAREAS_CLAVE", "")
        if not esperada or cierra is None or conexiones is None:
            raise HTTPException(404, "no existe")
        dada = peticion.headers.get("x-tarea-clave", "")
        if not hmac.compare_digest(dada.encode(), esperada.encode()):
            raise HTTPException(401, "clave de tarea inválida")
        revisiones = revisar_cierra(registro.todos(), cierra, conexiones, trabajos.corriendo,
                                    publicar_en_linea)
        return {"loteos": [r.__dict__ for r in revisiones]}

    @app.exception_handler(DisenoInvalido)
    async def diseno_invalido(peticion: Request, error: DisenoInvalido):
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(PlanoInvalido)
    async def plano_invalido(peticion: Request, error: PlanoInvalido):
        return JSONResponse(status_code=400, content={"detail": str(error)})

    @app.exception_handler(PlanoNoListo)
    async def plano_no_listo(peticion: Request, error: PlanoNoListo):
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(LotesSinNumero)
    async def lotes_sin_numero(peticion: Request, error: LotesSinNumero):
        """Dice cuántos, para que la pantalla ofrezca crearlo igual sin ellos."""
        return JSONResponse(status_code=409, content={"detail": str(error), "sin_numero": error.cuantos,
                                                      "resto": error.resto})

    @app.exception_handler(KmzExistente)
    async def kmz_existente(peticion: Request, error: KmzExistente):
        """Dice cuál hay, para que la pantalla pida confirmar nombrándolo."""
        return JSONResponse(status_code=409, content={"detail": str(error),
                                                      "existentes": error.existentes})

    @app.exception_handler(NoEncontrado)
    async def no_encontrado(peticion: Request, error: NoEncontrado):
        """Lo que no existe y lo que es de otro se contestan igual."""
        return JSONResponse(status_code=404, content={"detail": str(error)})

    return app


# Cuántas veces se lanza una lectura del plano, contando las que retoma el arranque:
# si es la lectura misma la que bota la instancia, no queda en un ciclo.
INTENTOS_LECTURA = 3
# En la carpeta del KMZ mientras se lee su plano. Si la instancia muere, queda.
LECTURA = "lectura.json"
# Entre ver de quién es `lectura.json` y borrarlo, un lanzamiento nuevo podría escribir
# el suyo (el trabajo ya figura terminado mientras corre su `al_terminar`).
_CANDADO_LECTURA = threading.Lock()


def _lanzar_lectura(plano: Plano, entradas: dict, clave: str, intento: int,
                    trabajos: Trabajos, comandos) -> str:
    """Lanza la lectura del plano dejando anotado en el disco que está corriendo, para
    que la consola que arranque después de una caída la retome (`retomar_lecturas`).
    El avance de la lectura misma lo guarda el lector en `lector-avance/`."""
    archivo = plano.carpeta / LECTURA

    def recordar(trabajo) -> None:
        # Bajo el candado de `lanzar`: un 409 no llega acá, así que no pisa el
        # archivo de la lectura en curso, y el proceso todavía no parte.
        with _CANDADO_LECTURA:
            escribir_json(archivo, {"intento": intento, "trabajo": trabajo.id,
                                    "comenzo": datetime.now(timezone.utc).isoformat()})

    def al_terminar(trabajo) -> None:
        # Listo o falló, ya no hay nada que retomar. Si el archivo es de un
        # lanzamiento posterior (este recién está cerrando), es de ese y se deja.
        try:
            with _CANDADO_LECTURA:
                if _lectura(archivo).get("trabajo") in (None, trabajo.id):
                    archivo.unlink(missing_ok=True)
        except OSError as error:
            trabajo.lineas.append(f"aviso: no pude borrar {LECTURA} ({error})")
        # Con qué entradas quedó: si cambian, el paso se ve atrasado. La huella se
        # saca al terminar porque depende de la cuadrícula que propuso el lector.
        if trabajo.estado == "listo":
            plano.anotar("digitalizado", plano.huella_al_terminar(entradas))

    lineas = ([f"Se retoma la lectura del plano donde quedó (intento {intento} de "
               f"{INTENTOS_LECTURA})."] if intento > 1 else None)
    return trabajos.lanzar(clave, "digitalizar-plano", comandos.digitalizar_carpeta(plano.carpeta),
                           al_terminar=al_terminar, lineas=lineas, al_lanzar=recordar)


def _lectura(archivo: Path) -> dict:
    """Lo anotado en `lectura.json`; {} si no está. Uno ilegible cuenta como el último
    intento: no se sabe cuántos lleva y relanzarlo podría no acabar nunca."""
    try:
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        if not isinstance(datos, dict) or not isinstance(datos.get("intento"), int):
            raise ValueError("sin intento")
        return datos
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return {"intento": INTENTOS_LECTURA}


def _ya_leido(carpeta: Path) -> bool:
    """¿Hay un `digitalizado.json` posterior a `lectura.json`? Entonces la lectura
    terminó y el archivo quedó por un borrado que falló o una caída justo al cerrar.
    Relanzarla pisaría los lotes, con las correcciones que se les hicieron después."""
    try:
        return (carpeta / DIGITALIZADO).stat().st_mtime > (carpeta / LECTURA).stat().st_mtime
    except OSError:
        return False


def retomar_lecturas(kmzs: RegistroKmz, trabajos: Trabajos, comandos) -> list[str]:
    """Al arrancar: relanza las lecturas del plano que quedaron a medias (hay un
    `lectura.json` y nada corriendo), hasta `INTENTOS_LECTURA` en total. Las que ya
    no se pueden retomar pierden el archivo y la pantalla las da por interrumpidas.
    Devuelve los slugs relanzados. Lo que falle queda en el log: nunca bota el arranque."""
    retomadas = []
    try:
        guardados = kmzs.base.kmzs()
    except Exception:                       # noqa: BLE001 - nunca botar la consola
        print("[lecturas] no pude listar los KMZ:\n" + traceback.format_exc(), flush=True)
        return retomadas
    for guardado in guardados:
        try:
            plano = kmzs.plano_de(guardado)
            archivo = plano.carpeta / LECTURA
            if not archivo.is_file() or trabajos.corriendo(clave_kmz(guardado.slug)):
                continue
            intento = _lectura(archivo)["intento"] + 1
            entradas = None
            if intento <= INTENTOS_LECTURA and not _ya_leido(plano.carpeta):
                try:
                    entradas = plano.para_digitalizar()
                except Exception:           # noqa: BLE001 - sin PDF o sin entradas válidas
                    pass
            if entradas is None:
                archivo.unlink(missing_ok=True)
                print(f"[lecturas] {guardado.slug}: no se retoma la lectura del plano", flush=True)
                continue
            _lanzar_lectura(plano, entradas, clave_kmz(guardado.slug), intento, trabajos, comandos)
            retomadas.append(guardado.slug)
            print(f"[lecturas] {guardado.slug}: se retoma la lectura del plano "
                  f"(intento {intento} de {INTENTOS_LECTURA})", flush=True)
        except Exception:                   # noqa: BLE001 - nunca botar la consola
            print(f"[lecturas] {guardado.slug}: no se pudo retomar:\n" + traceback.format_exc(),
                  flush=True)
    return retomadas


def _republicar_en_segundo_plano(registro: Registro, trabajos: Trabajos, comandos,
                                 disenos: Disenos) -> threading.Thread:
    """Lanza el recorrido en un hilo daemon. Lo que falle queda en el log y nada
    más: un visor sin poner al día no es razón para que la consola no arranque."""

    def correr() -> None:
        try:
            # La huella se saca acá y no antes: hashear el visor no tiene por qué
            # demorar el arranque.
            republicar(registro.todos(), trabajos, comandos, disenos, visor.huella())
        except Exception:                   # noqa: BLE001 - nunca botar la consola
            print("[republicar] se cortó el recorrido:\n" + traceback.format_exc(),
                  flush=True)

    hilo = threading.Thread(target=correr, name="republicar", daemon=True)
    hilo.start()
    return hilo


def _diseno_para(marcas: VistaDisenos, valor, cliente_del_loteo: int) -> int | None:
    """El diseño pedido para un loteo, ya revisado. None = el por defecto."""
    if valor in (None, ""):
        return None
    try:
        diseno_id = int(valor)
    except (TypeError, ValueError) as error:
        raise DisenoInvalido("ese diseño no existe") from error
    return marcas.para_el_loteo(diseno_id, cliente_del_loteo)


def _aplicar_diseno(mios: Vista, disenos: Disenos, slug: str):
    """Al terminar de construir, el sitio queda con su diseño: así lo que se
    publique después, o se mire desde el disco, ya tiene la marca puesta."""

    def aplicar(trabajo) -> None:
        if trabajo.estado != "listo":
            return
        proyecto = mios.ver(slug)
        if proyecto.construido:
            disenos.escribir_en_sitio(proyecto.diseno_id, proyecto.salida.datos)

    return aplicar


def _en_orden(*avisos):
    """Varios `al_terminar` para un mismo trabajo, uno tras otro."""
    def todos(trabajo) -> None:
        for aviso in avisos:
            aviso(trabajo)
    return todos


def _anotar_publicacion(mios: Vista, proyecto: Proyecto, nombre: str):
    """Guarda el nombre y la URL que devolvió el hosting, no los que supusimos.

    Y con qué visor salió: si no, el próximo arranque lo daría por atrasado y lo
    volvería a subir sin necesidad."""
    rastro = proyecto.salida.base / "publicacion.json"

    def guardar(trabajo) -> None:
        if trabajo.estado != "listo":
            return
        datos = json.loads(rastro.read_text(encoding="utf-8")) if rastro.is_file() else {}
        mios.anotar_publicacion(
            proyecto.slug,
            vercel_proyecto=datos.get("proyecto") or nombre,
            url=datos.get("url") or url_propuesta(proyecto.slug))
        # Es la del visor que acaba de subir: `comandos.publicar` lo copia antes.
        mios.anotar_visor(proyecto.slug, visor.huella())

    return guardar


def _descarga(contenido: bytes, nombre: str) -> Response:
    return Response(contenido, media_type=MIME_XLSX, headers={
        "Content-Disposition": f'attachment; filename="{nombre}"',
        "Cache-Control": "private, no-cache"})


def _adjunto(nombre: str, respaldo: str) -> str:
    """`Content-Disposition` de una descarga: un nombre ASCII para los navegadores
    viejos y el de verdad, con tildes, en `filename*` (RFC 5987)."""
    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    plano = re.sub(r"[^A-Za-z0-9 ._-]+", "_", plano).strip(" ._")
    if not plano.lower().endswith(".kmz") or plano.lower() == ".kmz":
        plano = respaldo
    return f"attachment; filename=\"{plano}\"; filename*=UTF-8''{quote(nombre, safe='')}"


def _cliente_json(cliente, base: Base) -> dict:
    return {
        "id": cliente.id,
        "slug": cliente.slug,
        "nombre": cliente.nombre,
        "estado": cliente.estado,
        "cuentas": [u.email for u in base.usuarios_de(cliente.id)],
        "loteos": len(base.proyectos(cliente_id=cliente.id)),
    }


def _como_json(proyecto: Proyecto, trabajos: Trabajos) -> dict:
    ultimo = trabajos.ultimo(proyecto.slug)
    return {
        "slug": proyecto.slug,
        "nombre": proyecto.nombre,
        "etapa": proyecto.etapa,
        "whatsapp": proyecto.whatsapp,
        "link_reserva": proyecto.link_reserva,
        "monto_reserva": proyecto.monto_reserva,
        "parcelacion": proyecto.parcelacion,
        "despegue": list(proyecto.despegue) if proyecto.despegue else None,
        "referencias": list(proyecto.referencias),
        "fuentes": str(proyecto.fuentes),
        "fuentes_encontradas": proyecto.fuentes_encontradas(),
        # Sin planilla, los estados y precios pueden salir del export del CRM.
        "con_crm": proyecto.crm is not None,
        # Un loteo publicado sin teléfono deja al comprador mirando sin a quién
        # escribirle: el visor esconde el botón de contacto si no hay número.
        "sin_contacto": not proyecto.whatsapp,
        "construido": proyecto.construido,
        "resumen": proyecto.resumen(),
        "calce": proyecto.control_de_calce(),
        "url": proyecto.url_publicada or url_propuesta(proyecto.slug),
        "publicado": proyecto.publicado,
        "pagado": proyecto.pagado,
        # Quitar de la lista uno subido y sin pagar borra sus archivos.
        "subido": proyecto.subido,
        "diseno_id": proyecto.diseno_id,
        "trabajo": ultimo.como_json() if ultimo and not ultimo.terminado else None,
    }

