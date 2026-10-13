"""La versión HTML de los correos de la consola.

Los correos se escriben como texto plano (así se leen en el registro, en el buzón
del QA y en las pruebas) y esta plantilla los viste al enviarlos: la marca arriba,
los párrafos con aire y el enlace principal como botón, en vez de una URL larga
que nadie quiere copiar. El texto plano viaja igual, para quien no ve HTML.

Va en tablas y con estilos en línea porque Gmail y Outlook ignoran casi todo lo
demás. Sin imágenes: muchos clientes las bloquean de entrada, y un logo que no
carga se ve peor que ninguno.
"""
from __future__ import annotations

import html
import re
from urllib.parse import urlsplit

URL = re.compile(r"https?://[^\s<>\"']+")
# Una línea que termina en un enlace: "Ábrelo y aprieta Publicar: https://…" o
# "Entra en https://…".
TERMINA_EN_URL = re.compile(
    r"^(?P<antes>.*?)(?P<union>\s*:\s*|\s+en\s+|\s*)(?P<url>https?://[^\s<>\"']+?)[.,;)]?$")

# El texto del botón según adónde lleva. Lo que no está acá abre la consola.
BOTONES = [
    ("/verificar", "Confirmar mi correo"),
    ("/restablecer", "Elegir contraseña nueva"),
    ("/invitacion", "Aceptar la invitación"),
    ("/olvide", "Pedir contraseña nueva"),
    ("/entrar", "Entrar"),
    ("#/planos/", "Abrir el loteo"),
    ("#/reservas", "Ver las reservas"),
    ("#/contactos", "Ver los contactos"),
]

TINTA = "#18181b"
SUAVE = "#52525b"
TENUE = "#a1a1aa"
FONDO = "#f4f4f5"
BORDE = "#e4e4e7"
VERDE = "#22c55e"
LETRA = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"


def texto_del_boton(url: str) -> str:
    partes = urlsplit(url)
    ruta = partes.path + (f"#{partes.fragment}" if partes.fragment else "")
    for clave, texto in BOTONES:
        if clave in ruta:
            return texto
    return "Abrir la consola"


def html_del_correo(asunto: str, texto: str) -> str:
    bloques: list[str] = []
    principal: str | None = None

    for parrafo in re.split(r"\n\s*\n", texto.strip()):
        lineas = [l.strip() for l in parrafo.splitlines() if l.strip()]
        if not lineas:
            continue
        sueltas: list[str] = []
        for linea in lineas:
            final = TERMINA_EN_URL.match(linea)
            if not final:
                sueltas.append(_con_enlaces(linea))
                continue
            # El enlace sale de la frase y queda como botón; la frase se queda.
            if sueltas:
                bloques.append(_parrafo(sueltas))
                sueltas = []
            antes, url = final["antes"].strip(), final["url"]
            # "Entra en <url>": la frase misma es el botón. "Ábrelo: <url>": la frase
            # presenta el botón y queda como párrafo.
            rotulo = antes if antes and "en" in final["union"].split() else None
            # "El loteo: <url>" sobra al lado de un botón que dice "Abrir el loteo".
            if antes and not rotulo and len(antes.split()) > 2:
                bloques.append(_parrafo([html.escape(antes)]))
            if principal is None:
                principal = url
                bloques.append(_boton(url, rotulo))
            else:
                bloques.append(_enlace_secundario(url, rotulo))
        if sueltas:
            bloques.append(_parrafo(sueltas))

    respaldo = ""
    if principal:
        respaldo = (
            f'<p style="margin:24px 0 0;font-size:12px;line-height:18px;color:{TENUE};">'
            "¿El botón no funciona? Copia este enlace en el navegador:<br>"
            f'<a href="{html.escape(principal)}" style="color:{SUAVE};word-break:break-all;">'
            f"{html.escape(principal)}</a></p>")

    cuerpo = "\n".join(bloques)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<title>{html.escape(asunto)}</title>
</head>
<body style="margin:0;padding:0;background:{FONDO};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{FONDO};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px;">
<tr><td style="padding:0 4px 20px;font-family:{LETRA};font-size:17px;font-weight:700;color:{TINTA};letter-spacing:-0.2px;">
Tu Masterplan<span style="color:{VERDE};">&#9679;</span>
</td></tr>
<tr><td style="background:#ffffff;border:1px solid {BORDE};border-radius:16px;padding:36px 32px;font-family:{LETRA};">
<h1 style="margin:0 0 20px;font-size:22px;line-height:30px;font-weight:700;color:{TINTA};letter-spacing:-0.3px;">{html.escape(asunto)}</h1>
{cuerpo}
{respaldo}
</td></tr>
<tr><td style="padding:20px 4px 0;font-family:{LETRA};font-size:12px;line-height:18px;color:{TENUE};">
Te escribimos desde la consola de Tu Masterplan. Esta casilla no recibe respuestas.<br>
<a href="https://www.tumasterplan.cl" style="color:{TENUE};">tumasterplan.cl</a>
</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def _parrafo(lineas: list[str]) -> str:
    return (f'<p style="margin:0 0 16px;font-size:15px;line-height:24px;color:{SUAVE};">'
            + "<br>".join(lineas) + "</p>")


def _boton(url: str, rotulo: str | None = None) -> str:
    destino = html.escape(url)
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 24px;">'
        f'<tr><td style="background:{TINTA};border-radius:10px;">'
        f'<a href="{destino}" style="display:inline-block;padding:14px 26px;font-family:{LETRA};'
        f'font-size:15px;font-weight:600;color:#ffffff;text-decoration:none;border-radius:10px;">'
        f"{html.escape(rotulo or texto_del_boton(url))}</a></td></tr></table>")


def _enlace_secundario(url: str, rotulo: str | None = None) -> str:
    return (f'<p style="margin:-8px 0 16px;font-size:15px;line-height:24px;">'
            f'<a href="{html.escape(url)}" style="color:{TINTA};font-weight:600;">'
            f"{html.escape(rotulo or texto_del_boton(url))} &rarr;</a></p>")


def _con_enlaces(linea: str) -> str:
    """Escapa la línea y deja como enlace cualquier URL que vaya en medio."""
    partes, ultimo = [], 0
    for encontrado in URL.finditer(linea):
        url = encontrado.group().rstrip(".,;:)")
        fin = encontrado.start() + len(url)
        partes.append(html.escape(linea[ultimo:encontrado.start()]))
        partes.append(f'<a href="{html.escape(url)}" style="color:{TINTA};">{html.escape(url)}</a>')
        ultimo = fin
    partes.append(html.escape(linea[ultimo:]))
    return "".join(partes)
