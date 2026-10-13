"""Correr el pipeline desde la consola y ver el avance en vivo.

Cada construcción es un subproceso: el pipeline ya imprime un diagnóstico útil
línea por línea (rumbo resuelto, error del sol, calce, avisos) y esas mismas líneas
son lo que se muestra en pantalla. Correrlo aparte y no dentro del servidor también
evita que un error en el pipeline se lleve puesta la consola.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

LIMITE_LINEAS = 2000

# Lo más que puede correr un trabajo antes de cortarlo. La instancia corre los pesados
# de a uno: uno que se cuelga (una descarga que nunca vuelve, el lector pegado en una
# página) dejaba la cola tomada para todas las loteadoras hasta reiniciar. Una
# construcción grande toma unos 5 min de CPU y leer un plano grande ~5 min; los topes
# dejan harto margen a uno lento sin que uno trabado frene al resto la tarde entera.
TOPE_PESADO = 45 * 60
# Publicar y actualizar el visor solo suben archivos.
TOPE_LIVIANO = 20 * 60
# Terminado o cortado el proceso, cuánto se espera a que se cierre su salida. Un nieto
# que siguió vivo puede tenerla abierta para siempre; el turno no lo espera.
ESPERA_SALIDA = 5.0


@dataclass
class Trabajo:
    id: str
    proyecto: str                     # el slug del master, o "kmz:<slug>" para Mis KMZ
    accion: str                       # "construir" | "publicar" | "digitalizar-plano"
    estado: str = "corriendo"         # "en_cola" | "corriendo" | "listo" | "falló"
    codigo: int | None = None
    lineas: list[str] = field(default_factory=list)
    comenzo: datetime = field(default_factory=datetime.now)
    # Pasa por la cola de los pesados (construir, leer un plano); publicar no.
    pesado: bool = True
    # Reloj monótono: cuándo partió el proceso y cuándo soltó el turno.
    partio: float | None = None
    termino: float | None = None
    # Cuántos esperan antes que este en la cola (1 = el próximo); None si no espera.
    posicion: int | None = None
    # Se pasó del tope y se cortó.
    vencido: bool = False
    # Se prende cuando ya no queda nada por hacer, lo de `al_terminar` incluido.
    fin: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    @property
    def terminado(self) -> bool:
        return self.estado not in ("corriendo", "en_cola")

    def como_json(self, desde: int = 0) -> dict:
        return {
            "id": self.id,
            "proyecto": self.proyecto,
            "accion": self.accion,
            "estado": self.estado,
            "codigo": self.codigo,
            "terminado": self.terminado,
            "posicion": self.posicion,
            "vencido": self.vencido,
            "desde": desde,
            "total": len(self.lineas),
            "lineas": self.lineas[desde:],
        }


class Trabajos:
    """Los trabajos en curso y los últimos terminados, en memoria.

    `simultaneos`: cuántos trabajos pesados corren a la vez en la instancia. Los que
    llegan con el tope lleno esperan en cola, en orden de llegada, y parten solos al
    soltarse un turno. Una construcción grande pasa de 4 GB y la instancia tiene 8:
    dos a la vez la pueden matar, y con ella todo lo que corría. None = sin tope.

    `tope_pesado` / `tope_liviano`: segundos que puede correr un trabajo antes de
    cortarlo, con todo lo que haya lanzado, y soltar su turno.
    """

    def __init__(self, directorio: Path | None = None, simultaneos: int | None = None,
                 tope_pesado: float = TOPE_PESADO, tope_liviano: float = TOPE_LIVIANO):
        self.directorio = Path(directorio) if directorio else None
        self.simultaneos = simultaneos
        self.tope_pesado = tope_pesado
        self.tope_liviano = tope_liviano
        self._trabajos: dict[str, Trabajo] = {}
        self._cola: deque[tuple[Trabajo, list[str], object]] = deque()
        self._procesos: dict[str, subprocess.Popen] = {}
        self._candado = threading.Lock()

    def lanzar(self, proyecto: str, accion: str, comando: list[str],
               al_terminar=None, lineas: list[str] | None = None, al_lanzar=None,
               pesado: bool = True) -> str:
        """`lineas`: las primeras del avance, antes de lo que imprima el comando.
        `al_lanzar(trabajo)` corre bajo el candado, ya visto que no hay otro en curso y
        antes de partir el proceso: lo que anote ahí no lo pisa otro lanzamiento ni lo
        adelanta el `al_terminar` de este. Si revienta, el trabajo no se lanza.
        `pesado`: si pasa por la cola (construir, leer un plano). Publicar no: sube
        archivos y no come memoria."""
        with self._candado:
            if self._corriendo(proyecto):
                raise RuntimeError(f"{proyecto} ya está en algo; espera a que termine")
            # Nace esperando: no cuenta como uno que ya tiene turno hasta que lo toma.
            trabajo = Trabajo(id=uuid.uuid4().hex[:12], proyecto=proyecto, accion=accion,
                              estado="en_cola", lineas=list(lineas or []), pesado=pesado)
            if al_lanzar is not None:
                al_lanzar(trabajo)
            self._trabajos[trabajo.id] = trabajo
            if pesado and self._sin_turno():
                self._cola.append((trabajo, comando, al_terminar))
                self._numerar_cola()
                return trabajo.id
            self._partir(trabajo, comando, al_terminar)
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

    def cortar_todo(self) -> None:
        """Al apagar la consola: cada trabajo corre en su propio grupo de procesos (ver
        `_seguir`), así que apagar la consola ya no se los lleva solos."""
        for proceso in list(self._procesos.values()):
            _matar(proceso)

    def corriendo(self, proyecto: str) -> bool:
        """¿Hay algo en curso para ese loteo?"""
        return self._corriendo(proyecto)

    def _corriendo(self, proyecto: str) -> bool:
        return any(t.proyecto == proyecto and not t.terminado for t in self._trabajos.values())

    # --- la cola ------------------------------------------------------------------

    def _sin_turno(self) -> bool:
        """¿Uno nuevo tiene que esperar? Si hay cola, sí: nadie se salta la fila."""
        return self._turnos_llenos() or bool(self._cola)

    def _turnos_llenos(self) -> bool:
        if self.simultaneos is None:
            return False
        pesados = sum(1 for t in self._trabajos.values() if t.pesado and t.estado == "corriendo")
        return pesados >= self.simultaneos

    def _numerar_cola(self) -> None:
        for lugar, (trabajo, _, _) in enumerate(self._cola, start=1):
            trabajo.posicion = lugar

    def _partir(self, trabajo: Trabajo, comando: list[str], al_terminar) -> None:
        """Bajo el candado: el trabajo toma su turno y parte el hilo que lo corre."""
        trabajo.estado, trabajo.posicion, trabajo.partio = "corriendo", None, time.monotonic()
        hilo = threading.Thread(target=self._correr, args=(trabajo, comando, al_terminar),
                                daemon=True)
        hilo.start()

    def _soltar_turno(self, trabajo: Trabajo) -> None:
        with self._candado:
            trabajo.termino = time.monotonic()
            if not trabajo.pesado:
                return
            while self._cola and not self._turnos_llenos():
                siguiente, comando, al_terminar = self._cola.popleft()
                self._partir(siguiente, comando, al_terminar)
            self._numerar_cola()

    def _correr(self, trabajo: Trabajo, comando: list[str], al_terminar=None) -> None:
        try:
            self._seguir(trabajo, comando, al_terminar)
        finally:
            # El turno se suelta después de guardar lo suyo (`al_terminar`): el que
            # sigue puede leer lo que este dejó. Y pase lo que pase, nadie queda
            # esperando para siempre.
            self._soltar_turno(trabajo)
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
                # Su propio grupo: al vencer se corta el árbol entero (el lector del
                # plano, el `vercel` de publicar), no solo el proceso de arriba.
                start_new_session=os.name == "posix",
            )
        except OSError as error:
            trabajo.lineas.append(f"no pude lanzar el comando: {error}")
            trabajo.estado, trabajo.codigo = "falló", -1
            return

        self._procesos[trabajo.id] = proceso
        try:
            self._vigilar(trabajo, proceso)
        finally:
            self._procesos.pop(trabajo.id, None)

        trabajo.codigo = proceso.returncode
        trabajo.estado = "listo" if proceso.returncode == 0 and not trabajo.vencido else "falló"

        # Lo durable se guarda acá: el diccionario de trabajos vive en memoria y
        # se pierde al reiniciar, pero lo que dejó el trabajo tiene que quedar.
        if al_terminar is not None:
            try:
                al_terminar(trabajo)
            except Exception as error:      # noqa: BLE001 - nunca romper por esto
                trabajo.lineas.append(f"aviso: no pude guardar el resultado ({error})")

    def _vigilar(self, trabajo: Trabajo, proceso: subprocess.Popen) -> None:
        """Lee la salida en otro hilo y espera al proceso con tope. Leer acá mismo no
        sirve: un proceso colgado sin imprimir deja la lectura bloqueada y el tope
        nunca se mira."""
        def leer() -> None:
            try:
                for linea in proceso.stdout:
                    if len(trabajo.lineas) < LIMITE_LINEAS:
                        trabajo.lineas.append(linea.rstrip("\n"))
            except (OSError, ValueError):
                pass

        lector = threading.Thread(target=leer, daemon=True)
        lector.start()
        tope = self.tope_pesado if trabajo.pesado else self.tope_liviano
        try:
            proceso.wait(timeout=tope)
        except subprocess.TimeoutExpired:
            trabajo.vencido = True
            _matar(proceso)
            proceso.wait()
        # Muerto el proceso, lo que quede en la tubería se lee al tiro. Si la lectura
        # sigue, es que un nieto se quedó con la salida: el turno no lo espera.
        lector.join(ESPERA_SALIDA)
        if trabajo.vencido:
            trabajo.lineas.append(f"se pasó de {_minutos(tope)} y lo corté: "
                                  "vuelve a lanzarlo, y si se repite, avísanos")


def _matar(proceso: subprocess.Popen) -> None:
    """El grupo entero donde se puede; si no, al menos el proceso."""
    try:
        if os.name == "posix":
            os.killpg(proceso.pid, signal.SIGKILL)
        else:
            proceso.kill()
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _minutos(segundos: float) -> str:
    minutos = round(segundos / 60)
    return f"{minutos} min" if minutos >= 1 else f"{segundos:g} s"


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
