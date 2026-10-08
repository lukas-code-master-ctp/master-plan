"""Correr el pipeline desde la consola y ver el avance en vivo.

Cada construcción es un subproceso: el pipeline ya imprime un diagnóstico útil
línea por línea (rumbo resuelto, error del sol, calce, avisos) y esas mismas líneas
son lo que se muestra en pantalla. Correrlo aparte y no dentro del servidor también
evita que un error en el pipeline se lleve puesta la consola.
"""
from __future__ import annotations

import subprocess
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

LIMITE_LINEAS = 2000


@dataclass
class Trabajo:
    id: str
    proyecto: str                     # el slug del master, o "kmz:<slug>" para Mis KMZ
    accion: str                       # "construir" | "publicar" | "digitalizar-plano"
    estado: str = "corriendo"         # "corriendo" | "listo" | "falló"
    codigo: int | None = None
    lineas: list[str] = field(default_factory=list)
    comenzo: datetime = field(default_factory=datetime.now)
    # Se prende cuando ya no queda nada por hacer, lo de `al_terminar` incluido.
    fin: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    @property
    def terminado(self) -> bool:
        return self.estado != "corriendo"

    def como_json(self, desde: int = 0) -> dict:
        return {
            "id": self.id,
            "proyecto": self.proyecto,
            "accion": self.accion,
            "estado": self.estado,
            "codigo": self.codigo,
            "terminado": self.terminado,
            "desde": desde,
            "total": len(self.lineas),
            "lineas": self.lineas[desde:],
        }


class Trabajos:
    """Los trabajos en curso y los últimos terminados, en memoria."""

    def __init__(self, directorio: Path | None = None):
        self.directorio = Path(directorio) if directorio else None
        self._trabajos: dict[str, Trabajo] = {}
        self._candado = threading.Lock()

    def lanzar(self, proyecto: str, accion: str, comando: list[str],
               al_terminar=None, lineas: list[str] | None = None, al_lanzar=None) -> str:
        """`lineas`: las primeras del avance, antes de lo que imprima el comando.
        `al_lanzar(trabajo)` corre bajo el candado, ya visto que no hay otro en curso y
        antes de partir el proceso: lo que anote ahí no lo pisa otro lanzamiento ni lo
        adelanta el `al_terminar` de este. Si revienta, el trabajo no se lanza."""
        with self._candado:
            if self._corriendo(proyecto):
                raise RuntimeError(f"{proyecto} ya está en algo; espera a que termine")
            trabajo = Trabajo(id=uuid.uuid4().hex[:12], proyecto=proyecto, accion=accion,
                              lineas=list(lineas or []))
            if al_lanzar is not None:
                al_lanzar(trabajo)
            self._trabajos[trabajo.id] = trabajo

        hilo = threading.Thread(target=self._correr, args=(trabajo, comando, al_terminar),
                                daemon=True)
        hilo.start()
        return trabajo.id

    def ver(self, identificador: str) -> Trabajo:
        trabajo = self._trabajos.get(identificador)
        if trabajo is None:
            raise KeyError(f"no existe el trabajo {identificador!r}")
        return trabajo

    def esperar(self, identificador: str, tope: float | None = None) -> Trabajo:
        """Bloquea hasta que el trabajo termine y haya guardado lo suyo.

        Con `tope` (segundos) no espera más que eso: devuelve el trabajo igual,
        quizá todavía corriendo; quien llama mira `terminado`.
        """
        trabajo = self.ver(identificador)
        trabajo.fin.wait(tope)
        return trabajo

    def ultimo(self, proyecto: str) -> Trabajo | None:
        suyos = [t for t in self._trabajos.values() if t.proyecto == proyecto]
        return max(suyos, key=lambda t: t.comenzo) if suyos else None

    def olvidar(self, proyecto: str) -> None:
        """Suelta los trabajos terminados de esa clave: lo que se borra no deja su
        avance a quien tome después el mismo nombre."""
        with self._candado:
            for identificador, trabajo in list(self._trabajos.items()):
                if trabajo.proyecto == proyecto and trabajo.terminado:
                    del self._trabajos[identificador]

    def corriendo(self, proyecto: str) -> bool:
        """¿Hay algo en curso para ese loteo?"""
        return self._corriendo(proyecto)

    def _corriendo(self, proyecto: str) -> bool:
        return any(t.proyecto == proyecto and not t.terminado for t in self._trabajos.values())

    def _correr(self, trabajo: Trabajo, comando: list[str], al_terminar=None) -> None:
        try:
            self._seguir(trabajo, comando, al_terminar)
        finally:
            # Pase lo que pase, nadie queda esperando para siempre.
            trabajo.fin.set()

    def _seguir(self, trabajo: Trabajo, comando: list[str], al_terminar=None) -> None:
        try:
            proceso = subprocess.Popen(
                comando, cwd=self.directorio, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                # El pipeline escribe en UTF-8 (ver `_entorno_sin_bufer`): se lee igual,
                # no con la codificación del sistema (cp1252 en Windows).
                encoding="utf-8", errors="replace",
                # Sin esto Python almacena su salida en un búfer al no ver una
                # terminal, y el avance aparecería recién al terminar.
                env=_entorno_sin_bufer(),
            )
        except OSError as error:
            trabajo.lineas.append(f"no pude lanzar el comando: {error}")
            trabajo.estado, trabajo.codigo = "falló", -1
            return

        for linea in proceso.stdout:
            if len(trabajo.lineas) < LIMITE_LINEAS:
                trabajo.lineas.append(linea.rstrip("\n"))
        proceso.wait()

        trabajo.codigo = proceso.returncode
        trabajo.estado = "listo" if proceso.returncode == 0 else "falló"

        # Lo durable se guarda acá: el diccionario de trabajos vive en memoria y
        # se pierde al reiniciar, pero lo que dejó el trabajo tiene que quedar.
        if al_terminar is not None:
            try:
                al_terminar(trabajo)
            except Exception as error:      # noqa: BLE001 - nunca romper por esto
                trabajo.lineas.append(f"aviso: no pude guardar el resultado ({error})")


def _entorno_sin_bufer() -> dict:
    """Líneas enteras y en texto plano: se leen en la página, no en una terminal.

    Sin `PYTHON_COLORS=0`, un Python 3.13+ lanzado desde una terminal con color
    forzado pinta los tracebacks con códigos ANSI, que en la página salen como
    basura del tipo `[35m`.

    `PYTHONIOENCODING=utf-8`: sin él, un `print` con "°" o "×" (el avance de Crea tu
    KMZ) revienta con UnicodeEncodeError donde la consola del sistema no es UTF-8.
    """
    import os
    return {**os.environ, "PYTHONUNBUFFERED": "1", "PYTHON_COLORS": "0", "NO_COLOR": "1",
            "PYTHONIOENCODING": "utf-8"}
