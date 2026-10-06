"""El visor: el sitio (html, css, js, vendor) que acompaña a los datos de cada loteo.

    python -m pipeline.visor --sitio "salidas/<proyecto>/sitio"

Construir un loteo copia el visor junto a sus datos. Cuando solo cambia el visor,
no hace falta reconstruir: basta volver a copiarlo sobre un sitio ya construido.
La huella dice qué versión del visor lleva cada sitio publicado.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from urllib.parse import urlsplit

from . import config

# Lo que no es del visor: los datos y las panorámicas de prueba de la plantilla,
# las pruebas y la basura del Finder. Se aplica a cualquier nivel.
IGNORAR = shutil.ignore_patterns("datos", "panoramas", "*.test.js", ".DS_Store")


def copiar(sitio: Path) -> None:
    """Copia el visor sobre el sitio sin tocar sus datos: la carpeta queda
    autocontenida y se sube tal cual.

    Solo el contenido, no permisos ni fechas: en Cloud Run el sitio vive en un
    bucket montado (gcsfuse), que no deja cambiarlos, y `shutil.copytree` los
    copia siempre (copy2 y copystat) y falla con "Operation not permitted".
    """
    origen = config.PLANTILLA_WEB
    for carpeta, subcarpetas, nombres in os.walk(origen, followlinks=True):
        ignorados = IGNORAR(carpeta, subcarpetas + nombres)
        subcarpetas[:] = [n for n in subcarpetas if n not in ignorados]
        destino = Path(sitio) / Path(carpeta).relative_to(origen)
        destino.mkdir(parents=True, exist_ok=True)
        for nombre in nombres:
            if nombre not in ignorados:
                shutil.copyfile(Path(carpeta, nombre), destino / nombre)
    # La copia trae el vercel.json de la plantilla, que solo deja conectar con el
    # propio sitio: si el sitio ya sabe a qué consola pedir las reservas, se vuelve
    # a abrir. Publicar anota la consola antes de copiar el visor encima.
    consola = _consola_del_sitio(Path(sitio))
    if consola:
        permitir_conexion(Path(sitio), consola)


def _consola_del_sitio(sitio: Path) -> str:
    archivo = sitio / "datos" / "parcelas.json"
    if not archivo.is_file():
        return ""
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    return datos.get("consola", "") if isinstance(datos, dict) else ""


def permitir_conexion(sitio: Path, url: str) -> None:
    """Deja que el sitio publicado le hable a `url` (la consola), y a nada más.

    El visor pide ahí las parcelas apartadas y manda las solicitudes de reserva.
    La política de seguridad del sitio (`vercel.json`) solo deja conectar con el
    propio sitio: se le suma el origen de la consola, el que sea en cada despliegue.
    Escribirlo dos veces deja lo mismo.
    """
    archivo = sitio / "vercel.json"
    if not archivo.is_file():
        return
    partes = urlsplit(url)
    origen = f"{partes.scheme}://{partes.netloc}"
    datos = json.loads(archivo.read_text(encoding="utf-8"))
    for regla in datos.get("headers", []):
        for encabezado in regla.get("headers", []):
            if encabezado.get("key") == "Content-Security-Policy":
                directivas = [d.strip() for d in encabezado["value"].split(";")]
                encabezado["value"] = "; ".join(
                    f"connect-src 'self' {origen}" if d.startswith("connect-src") else d
                    for d in directivas)
    archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def huella(origen: Path | None = None) -> str:
    """SHA-256 de lo que `copiar` llevaría al sitio: rutas relativas y contenido.

    Mira exactamente lo que `copiar` copia, así que tocar una prueba o los datos de
    la plantilla no cambia la huella. Las rutas van en formato POSIX y ordenadas
    para que dé lo mismo en Windows que en el contenedor.
    """
    origen = origen or config.PLANTILLA_WEB
    archivos = []
    for carpeta, subcarpetas, nombres in os.walk(origen, followlinks=True):
        ignorados = IGNORAR(carpeta, subcarpetas + nombres)
        subcarpetas[:] = [n for n in subcarpetas if n not in ignorados]
        archivos += [Path(carpeta, n) for n in nombres if n not in ignorados]

    suma = hashlib.sha256()
    for relativa, ruta in sorted((a.relative_to(origen).as_posix(), a) for a in archivos):
        contenido = ruta.read_bytes()
        # Ruta y largo antes del contenido: ningún archivo puede hacerse pasar
        # por el final de otro.
        suma.update(f"{relativa}\0{len(contenido)}\0".encode("utf-8"))
        suma.update(contenido)
    return suma.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Copia el visor actual sobre un sitio ya construido.")
    parser.add_argument("--sitio", type=Path, required=True,
                        help="carpeta del sitio construido (la que tiene datos/parcelas.json)")
    argumentos = parser.parse_args(argv)

    sitio = argumentos.sitio
    if not (sitio / "datos" / "parcelas.json").is_file():
        print(f"{sitio} no es un sitio construido: falta datos/parcelas.json. "
              f"Constrúyelo primero con python -m pipeline.construir.", file=sys.stderr)
        return 1

    copiar(sitio)
    print(f"Visor copiado en {sitio} (huella {huella(config.PLANTILLA_WEB)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
