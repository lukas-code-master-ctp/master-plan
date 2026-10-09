"""Pone la huella de cada imagen y de la fuente en las referencias de index.html.

Vercel las sirve con `immutable` por un año: el navegador no vuelve a preguntar.
Cambiar una imagen dejándole el mismo nombre deja a quien ya entró viendo la vieja.
Con `?v=<huella>` la dirección cambia cuando cambia el archivo, y solo entonces.

    python3 landing/versionar.py

Correrlo después de cambiar cualquier .webp o la fuente. La prueba
`test_cada_imagen_y_la_fuente_llevan_la_huella_de_su_archivo` avisa si se olvida.
No se publica (`.vercelignore`).
"""
import hashlib
import re
from pathlib import Path

LANDING = Path(__file__).resolve().parent
PAGINA = LANDING / "index.html"
ESTATICOS = re.compile(r"/([\w-]+\.(?:webp|woff2))(?:\?v=[0-9a-f]+)?")


def huella(archivo: str) -> str:
    return hashlib.sha256((LANDING / archivo).read_bytes()).hexdigest()[:8]


def versionar(html: str) -> str:
    return ESTATICOS.sub(lambda m: f"/{m.group(1)}?v={huella(m.group(1))}", html)


if __name__ == "__main__":
    antes = PAGINA.read_text(encoding="utf-8")
    despues = versionar(antes)
    PAGINA.write_text(despues, encoding="utf-8")
    cambios = sum(a != d for a, d in zip(antes.splitlines(), despues.splitlines()))
    print(f"index.html: {cambios} líneas con huellas nuevas" if cambios else "index.html: las huellas ya estaban al día")
