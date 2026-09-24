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
    proyecto: str
    accion: str                       # "construir" | "publicar"
    estado: str = "corriendo"         # "corriendo" | "listo" | "falló"
    codigo: int | None = None
    lineas: list[str] = field(default_factory=list)
    comenzo: datetime = field(default_factory=datetime.now)

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
               al_terminar=None) -> str:
        with self._candado:
            if self._corriendo(proyecto):
                raise RuntimeError(f"{proyecto} ya está en algo; espera a que termine")
            trabajo = Trabajo(id=uuid.uuid4().hex[:12], proyecto=proyecto, accion=accion)
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

    def ultimo(self, proyecto: str) -> Trabajo | None:
        suyos = [t for t in self._trabajos.values() if t.proyecto == proyecto]
        return max(suyos, key=lambda t: t.comenzo) if suyos else None

    def _corriendo(self, proyecto: str) -> bool:
        return any(t.proyecto == proyecto and not t.terminado for t in self._trabajos.values())

    def _correr(self, trabajo: Trabajo, comando: list[str], al_terminar=None) -> None:
        try:
            proceso = subprocess.Popen(
                comando, cwd=self.directorio, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
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
    import os
    return {**os.environ, "PYTHONUNBUFFERED": "1"}
