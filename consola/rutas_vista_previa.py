"""La vista previa: el visor de un loteo construido, servido por la propia consola.

Antes de pagar, la loteadora solo veía una imagen fija del control de calce, y el
visor 360, que es lo que compra, recién aparecía publicado. Acá se sirve el mismo
sitio que se subiría al hosting, con lo que el loteo tiene hoy en la consola
(nombre, WhatsApp, diseño) y sin escribir nada en él: publicar sigue siendo lo único
que lo cambia.

Tres diferencias con el sitio publicado, a propósito:
- Pide sesión y el loteo tiene que ser de quien lo pide (si no, 404), como todo.
- No ofrece reservar: sin publicar no hay sitio que acepte reservas, y un comprador
  de prueba que paga en el link real sería un cobro de verdad.
- Lleva una marca "Vista previa" y `noindex`, y la política de seguridad del sitio:
  el visor corre en el origen de la consola, con su cookie, y no tiene por qué
  poder cargar nada de afuera.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from pipeline import config
from pipeline.inventario import DATOS_DEL_LOTEO, datos_del_loteo

from .disenos import Disenos
from .proyectos import Proyecto, Vista
from .trabajos import Trabajos

# Lo que dice dónde mandar las reservas. Sin ninguno, el visor no dibuja el botón.
SIN_RESERVAS = ("link_reserva", "monto_reserva", "consola", "loteo")

# La del sitio publicado (`web/vercel.json`), con `connect-src 'self'`: acá el
# visor le habla solo a la consola que lo sirve.
POLITICA = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob: https://server.arcgisonline.com https://*.arcgisonline.com; "
            "font-src 'self'; connect-src 'self'; worker-src 'self' blob:; frame-ancestors 'self'; "
            "base-uri 'self'; form-action 'self'")
ENCABEZADOS = {
    "Content-Security-Policy": POLITICA,
    "X-Robots-Tag": "noindex, nofollow",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    # Cambia con cada construcción y con cada dato que se guarda en la consola.
    "Cache-Control": "private, no-cache",
}
# Los que `mimetypes` no conoce en todos los sistemas; con `nosniff` un tipo mal
# puesto deja la página sin fuente o sin módulos.
TIPOS = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
         ".json": "application/json", ".woff2": "font/woff2", ".svg": "image/svg+xml",
         ".webp": "image/webp"}

MARCA = """<style>
.vista-previa-consola {
  position: fixed; z-index: 2147483647; left: 50%; top: calc(76px + env(safe-area-inset-top));
  transform: translateX(-50%); pointer-events: none; padding: 6px 12px; border-radius: 999px;
  background: rgb(24 24 27 / 0.86); color: #fff; font: 600 12px/1.2 system-ui, sans-serif;
  letter-spacing: 0.02em; white-space: nowrap; box-shadow: 0 2px 10px rgb(0 0 0 / 0.25);
}
/* Abajo está la leyenda y arriba, en el celular, los botones: en pantalla ancha
   cabe entre el nombre y el buscador. */
@media (min-width: 64rem) { .vista-previa-consola { top: 26px; } }
</style>
<div class="vista-previa-consola" role="note">Vista previa · todavía no está publicado</div>
"""

ESPERA = """<!doctype html><html lang="es"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vista previa</title>
<p style="font: 16px/1.5 system-ui, sans-serif; max-width: 32rem; margin: 20vh auto; padding: 0 16px">
{texto}</p></html>"""


def con_la_marca(pagina: str) -> str:
    """El `index.html` del sitio con `noindex` y la marca de vista previa."""
    pagina = pagina.replace("<head>", '<head>\n<meta name="robots" content="noindex, nofollow">', 1)
    return re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + "\n" + MARCA, pagina, count=1)


def parcelas_sin_reservas(proyecto: Proyecto) -> dict:
    """Las parcelas construidas con el nombre, la etapa y el WhatsApp que el loteo
    tiene hoy en la consola, como quedarían al publicar, y sin cómo reservar."""
    datos = json.loads((proyecto.salida.datos / "parcelas.json").read_text(encoding="utf-8"))
    actuales = datos_del_loteo(config.cargar_proyecto(proyecto.fuentes))
    datos.update({campo: actuales[campo] for campo in DATOS_DEL_LOTEO})
    for campo in SIN_RESERVAS:
        datos.pop(campo, None)
    return datos


def rutas_de_vista_previa(vista, disenos: Disenos, trabajos: Trabajos) -> APIRouter:
    rutas = APIRouter()

    def construido(slug: str, mios: Vista) -> Proyecto:
        proyecto = mios.ver(slug)
        if not proyecto.construido:
            raise HTTPException(404, "todavía no está construido")
        return proyecto

    def armandose(slug: str) -> bool:
        """Construir reescribe el sitio entero: a medio camino se vería roto. Publicar
        solo lo sube, y se puede mirar mientras tanto."""
        ultimo = trabajos.ultimo(slug)
        return ultimo is not None and not ultimo.terminado and ultimo.accion != "publicar"

    @rutas.get("/vista-previa/{slug}")
    def sin_barra(slug: str, mios: Vista = Depends(vista)) -> RedirectResponse:
        # El sitio pide todo con rutas relativas: sin la barra final, `datos/...`
        # saldría de /vista-previa/ y no de la carpeta del loteo.
        construido(slug, mios)
        return RedirectResponse(f"/vista-previa/{slug}/", status_code=307)

    @rutas.get("/vista-previa/{slug}/{ruta:path}")
    def archivo(slug: str, ruta: str, mios: Vista = Depends(vista)):
        proyecto = construido(slug, mios)
        # `datos//parcelas.json` o `./datos/...` también llegan al archivo: se comparan
        # sin eso, o se saltarían lo que se cambia acá abajo.
        ruta = "/".join(parte for parte in ruta.split("/") if parte not in ("", "."))
        if ruta in ("", "index.html"):
            if armandose(slug):
                texto = (f"Se está construyendo {html.escape(proyecto.nombre)}. Vuelve a abrir "
                         "la vista previa cuando termine.")
                return HTMLResponse(ESPERA.format(texto=texto), status_code=409, headers=ENCABEZADOS)
            pagina = (proyecto.salida.web / "index.html").read_text(encoding="utf-8")
            return HTMLResponse(con_la_marca(pagina), headers=ENCABEZADOS)
        if ruta == "datos/parcelas.json":
            return JSONResponse(parcelas_sin_reservas(proyecto), headers=ENCABEZADOS)
        # El diseño que el loteo tiene elegido hoy, no el que quedó de la última
        # publicación: se elige mirando la vista previa.
        contenido, logo = disenos.para_el_sitio(proyecto.diseno_id)
        if ruta == "datos/diseno.json":
            return JSONResponse(contenido, headers=ENCABEZADOS)
        if ruta.startswith("datos/logo."):
            if logo is None or ruta != f"datos/{contenido['logo']}":
                raise HTTPException(404, "no existe ese archivo")
            return FileResponse(logo, headers=ENCABEZADOS)
        return FileResponse(_dentro_del_sitio(proyecto.salida.web, ruta), headers=ENCABEZADOS,
                            media_type=TIPOS.get(Path(ruta).suffix.lower()))

    return rutas


def _dentro_del_sitio(sitio: Path, ruta: str) -> Path:
    """El archivo del sitio que nombra `ruta`, o 404. Nada de afuera de la carpeta del
    sitio, y tampoco su configuración del hosting, que no es parte de lo que se ve."""
    raiz = sitio.resolve()
    archivo = (raiz / ruta).resolve()
    if not archivo.is_relative_to(raiz) or not archivo.is_file() or archivo.name == "vercel.json":
        raise HTTPException(404, "no existe ese archivo")
    return archivo
