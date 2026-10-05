"""Las cuentas y los loteos de prueba de la consola local.

    MASTERPLAN_DATOS=$PWD/.qa/datos PATH=$PWD/qa/bin:$PATH python -m qa.sembrar

Deja cinco cuentas (todas con la clave `CLAVE_QA`), dos loteadoras con sus loteos,
un diseño y un KMZ en Mis KMZ, y construye y publica "Praderas Demo" con los mismos
comandos que usa la consola, en el hosting falso de `qa/bin/vercel`. Con
`--sin-construir` se salta eso último, que es lo único que tarda.

**Solo siembra en una base de mentira.** Se niega si los datos no están dentro de
`.qa/` del repo, si hay `MASTERPLAN_BD` (eso es una base de verdad) o si la consola
no está en modo local. Lo mira antes de importar nada de la consola ni del
pipeline: `pipeline.config` fija la carpeta de datos al importarse, y para entonces
ya sería tarde para arrepentirse.

Corre una sola vez: si la base ya tiene loteadoras, no toca nada y lo dice.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
CARPETA_QA = REPO / ".qa"
VERCEL_FALSO = REPO / "qa" / "bin" / "vercel"

CLAVE_QA = "qa-clave-segura-1"

# Alias → correo. Los usan los otros scripts de QA (`qa:captura --como duenio`).
CUENTAS = {
    "plataforma": "plataforma@qa.test",
    "duenio": "duenio@loteadora-demo.test",
    "equipo": "equipo@loteadora-demo.test",
    "otra": "duenio@otra-loteadora.test",
    "sinconfirmar": "sinconfirmar@qa.test",
}

CASA = "CompraTuParcela"
DEMO = "Loteadora Demo"
OTRA = "Otra Loteadora"
SIN_CONFIRMAR = "Loteadora Sin Confirmar"

PRADERAS = "Praderas Demo"
SIN_CONSTRUIR = "Loteo sin construir"
VACIO = "Loteo vacío"
AJENO = "Loteo ajeno"
PLANO_DE_PRUEBA = "Plano de prueba"

# Sin el +: así lo guarda la consola (`wa.me/<número>`).
WHATSAPP_FICTICIO = "56900000000"
MARCA_DEMO = {
    "nombre": "Marca Demo",
    "color": "#1f5132",
    "tipografia": "serif",
    "texto_contacto": "Escríbenos por WhatsApp",
    "texto_pago": "Reservar",
}


# --- salvaguardas ------------------------------------------------------------------

def motivo_para_no_sembrar(entorno: dict | None = None, repo: Path = REPO) -> str | None:
    """Por qué no se puede sembrar acá, o None si se puede.

    No importa nada de la consola: tiene que poder contestar antes de que algo lea
    la configuración."""
    entorno = os.environ if entorno is None else entorno
    if entorno.get("MASTERPLAN_BD"):
        return ("MASTERPLAN_BD está definido: eso apunta a una base de verdad. "
                "Sembrar cuentas de prueba ahí no se hace; quítalo del entorno.")
    # Igual que `consola.datos.es_local`, sin perdonar espacios: " local" ahí es
    # desplegada. Solo el vacío cuenta como local (y `main` lo quita).
    entorno_consola = entorno.get("CONSOLA_ENTORNO") or ""
    if entorno_consola.strip() and entorno_consola != "local":
        return (f"CONSOLA_ENTORNO={entorno.get('CONSOLA_ENTORNO')!r}: la consola no está "
                "en modo local. Solo se siembra en la del computador.")
    datos = entorno.get("MASTERPLAN_DATOS")
    if not datos:
        return (f"falta MASTERPLAN_DATOS. Apúntalo a una carpeta dentro de {repo / '.qa'}, "
                f"por ejemplo MASTERPLAN_DATOS={repo / '.qa' / 'datos'}")
    ruta = Path(datos).expanduser().resolve()
    qa = (Path(repo) / ".qa").resolve()
    if ruta != qa and qa not in ruta.parents:
        return (f"MASTERPLAN_DATOS={datos} no está dentro de {qa}. Solo se siembra en "
                "los datos de QA, nunca en los de alguien.")
    return None


def vercel_es_el_falso() -> bool:
    """¿El `vercel` que encontraría `publicar.sh` es el de QA? Si no, podría ser el real."""
    encontrado = shutil.which("vercel")
    return bool(encontrado) and Path(encontrado).resolve() == VERCEL_FALSO.resolve()


# --- la siembra -------------------------------------------------------------------

@dataclass
class Siembra:
    """Lo que quedó, para mostrarlo. `hecha` es falso si la base ya tenía datos."""
    hecha: bool
    loteos: list[tuple[str, str, str]] = field(default_factory=list)  # loteadora, nombre, cómo quedó
    avisos: list[str] = field(default_factory=list)


def ejecutar(comando: list[str]) -> tuple[bool, str]:
    """Corre un comando de la consola desde la raíz del repo, como `Trabajos`."""
    proceso = subprocess.run(comando, cwd=REPO, capture_output=True, text=True)
    return proceso.returncode == 0, (proceso.stdout or "") + (proceso.stderr or "")


def sembrar(base, registro, disenos=None, kmzs=None, *, construir: bool = True,
            correr: Callable[[list[str]], tuple[bool, str]] = ejecutar,
            decir: Callable[[str], None] = print) -> Siembra:
    """Siembra la base y las carpetas de `registro`. Ver el docstring del módulo."""
    from consola.disenos import Disenos
    from consola.kmzs import RegistroKmz

    from . import ficticios

    if base.clientes():
        return Siembra(hecha=False)
    disenos = disenos or Disenos(base=base)
    kmzs = kmzs or RegistroKmz(base=base)

    # Cuentas y loteadoras.
    _loteadora(base, CASA, CUENTAS["plataforma"], "Plataforma QA")
    base.ascender_a_plataforma(CUENTAS["plataforma"])
    demo = _loteadora(base, DEMO, CUENTAS["duenio"], "Dueña Demo")
    base.crear_usuario(demo, CUENTAS["equipo"], "Equipo Demo", rol="equipo")
    base.cambiar_clave(CUENTAS["equipo"], CLAVE_QA)
    otra = _loteadora(base, OTRA, CUENTAS["otra"], "Dueño Otra")
    base.crear_cuenta_propia(SIN_CONFIRMAR, CUENTAS["sinconfirmar"], "Sin Confirmar",
                             CLAVE_QA, verificado=False)

    duenio = _sesion(base, CUENTAS["duenio"])
    mios = registro.para(duenio)
    siembra = Siembra(hecha=True)

    # El diseño y Mis KMZ de Loteadora Demo.
    marca = disenos.para(duenio).crear(MARCA_DEMO)
    kmzs.para(duenio).crear(PLANO_DE_PRUEBA)

    # Los loteos. Las fuentes se escriben donde las deja la subida de la consola.
    praderas = registro.habilitar(demo, PRADERAS, nota_cobro="QA: habilitado al sembrar")
    ficticios.escribir_fuentes(praderas.fuentes)
    mios.ajustar(praderas.slug, {"whatsapp": WHATSAPP_FICTICIO})
    mios.asignar_diseno(praderas.slug, marca.id)

    sin_construir = registro.crear(demo, SIN_CONSTRUIR)
    ficticios.escribir_fuentes(sin_construir.fuentes)
    mios.ajustar(sin_construir.slug, {"whatsapp": WHATSAPP_FICTICIO})

    registro.crear(demo, VACIO)
    registro.crear(otra, AJENO)

    estado_praderas = "habilitado, con fuentes, sin construir (--sin-construir)"
    if construir:
        estado_praderas = _construir_y_publicar(mios, disenos, praderas.slug, correr,
                                                decir, siembra.avisos)
    siembra.loteos = [
        (DEMO, PRADERAS, estado_praderas),
        (DEMO, SIN_CONSTRUIR, "sin pagar, con fuentes, sin construir"),
        (DEMO, VACIO, "sin pagar, sin archivos"),
        (OTRA, AJENO, "sin pagar, sin archivos (duenio no lo ve)"),
    ]
    return siembra


def _loteadora(base, nombre: str, correo: str, persona: str) -> int:
    """La loteadora y su dueño, ya con la clave de QA y sin tener que cambiarla."""
    cliente, _ = base.crear_cliente(nombre, correo, persona)
    base.cambiar_clave(correo, CLAVE_QA)
    return cliente.id


def _sesion(base, correo: str):
    from consola.acceso import Sesion
    usuario = base.usuario_por_email(correo)
    return Sesion(usuario_id=usuario.id, cliente_id=usuario.cliente_id,
                  rol=usuario.rol, quien=usuario.email)


def _construir_y_publicar(mios, disenos, slug: str, correr, decir,
                          avisos: list[str]) -> str:
    """Lo mismo que Construir y Publicar en la consola, incluido lo que hace al terminar
    cada uno (`_aplicar_diseno` y `_anotar_publicacion` en `consola/app.py`)."""
    from consola.app import nombre_propuesto, url_propuesta
    from consola.comandos import Comandos, encadenar
    from pipeline import visor

    comandos = Comandos()
    proyecto = mios.ver(slug)
    decir(f"▶ Construyendo {proyecto.nombre} (unos segundos)...")
    ok, salida = correr(encadenar(comandos.construir(proyecto),
                                  comandos.control_de_calce(proyecto)))
    proyecto = mios.ver(slug)
    if not ok or not proyecto.construido:
        avisos.append(f"no se pudo construir {proyecto.nombre}; el resto quedó sembrado. "
                      f"Lo último que dijo:\n{_cola(salida)}")
        return "habilitado, con fuentes, NO construido (falló)"
    disenos.escribir_en_sitio(proyecto.diseno_id, proyecto.salida.datos)

    if not vercel_es_el_falso():
        avisos.append("no publiqué Praderas Demo: el `vercel` del PATH no es el de qa/bin "
                      f"({shutil.which('vercel') or 'no hay ninguno'}) y podría ser el real. "
                      "Corre con PATH=$PWD/qa/bin:$PATH.")
        return "construido, sin publicar (vercel no es el de QA)"

    nombre = nombre_propuesto(proyecto.slug)
    decir(f"▶ Publicando {proyecto.nombre} en el hosting falso...")
    ok, salida = correr(comandos.publicar(proyecto, nombre, crear=True))
    if not ok:
        avisos.append(f"no se pudo publicar {proyecto.nombre}; quedó construido. "
                      f"Lo último que dijo:\n{_cola(salida)}")
        return "construido, sin publicar (falló)"
    rastro = proyecto.salida.base / "publicacion.json"
    datos = json.loads(rastro.read_text(encoding="utf-8")) if rastro.is_file() else {}
    mios.anotar_publicacion(slug, vercel_proyecto=datos.get("proyecto") or nombre,
                            url=datos.get("url") or url_propuesta(slug))
    mios.anotar_visor(slug, visor.huella())
    return f"construido y publicado en {mios.ver(slug).url_publicada}"


def _cola(salida: str, lineas: int = 15) -> str:
    return "\n".join("    " + linea for linea in salida.strip().splitlines()[-lineas:])


# --- por pantalla -----------------------------------------------------------------

def mostrar(siembra: Siembra, decir: Callable[[str], None] = print) -> None:
    if not siembra.hecha:
        decir("▶ La base ya tiene loteadoras: no sembré nada. Para empezar de cero, "
              "borra la carpeta de datos de QA y vuelve a correr esto.")
        return
    decir("")
    decir(f"▶ Cuentas (clave de todas: {CLAVE_QA})")
    ancho = max(len(a) for a in CUENTAS)
    for alias, correo in CUENTAS.items():
        nota = "  (sin confirmar el correo: no entra)" if alias == "sinconfirmar" else ""
        decir(f"  {alias.ljust(ancho)}  {correo}{nota}")
    decir("")
    decir("▶ Loteos")
    for loteadora, nombre, estado in siembra.loteos:
        decir(f"  {loteadora} / {nombre}: {estado}")
    decir(f"  {DEMO} / Mis KMZ: {PLANO_DE_PRUEBA} (vacío) · diseño {MARCA_DEMO['nombre']}")
    for aviso in siembra.avisos:
        decir("")
        decir(f"⚠ {aviso}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m qa.sembrar",
                                     description="Siembra la consola local de QA.")
    parser.add_argument("--sin-construir", action="store_true",
                        help="no construye ni publica Praderas Demo")
    argumentos = parser.parse_args(argv)

    motivo = motivo_para_no_sembrar()
    if motivo:
        print(f"No siembro: {motivo}", file=sys.stderr)
        return 2
    # Vacío cuenta como local, pero `consola.datos.es_local` solo lo da por local si
    # falta: se quita para que digan lo mismo.
    if not os.environ.get("CONSOLA_ENTORNO", "x").strip():
        os.environ.pop("CONSOLA_ENTORNO")

    Path(os.environ["MASTERPLAN_DATOS"]).expanduser().mkdir(parents=True, exist_ok=True)
    # Recién ahora: esto lee MASTERPLAN_DATOS al importarse.
    from consola.datos import Base
    from consola.proyectos import Registro

    base = Base()
    siembra = sembrar(base, Registro(base=base), construir=not argumentos.sin_construir)
    mostrar(siembra)
    return 0


if __name__ == "__main__":
    sys.exit(main())
