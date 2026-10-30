"""Los trabajos pesados en un Cloud Run Job, y su avance en la base.

Antes, la consola construía en su propia instancia, que por eso tenía 8 GB, 2 CPU y la
CPU asignada siempre (`--no-cpu-throttling`). Google cobra esa instancia por cada
segundo que está prendida, se use o no, y casi nunca alcanzaba a apagarse: costaba
unos CLP 150.000 al mes. Ahora la consola es una instancia que solo cobra mientras
atiende, y cada trabajo (construir, leer un plano, publicar) enciende su propia
máquina, que se paga solo mientras corre.

Esta clase tiene la misma cara que `Trabajos` para que las rutas no cambien: lanzar,
ver, esperar, último, corriendo. Lo que corría en un hilo de la consola corre ahora en
`consola.obrero`, que anota el avance acá cada pocos segundos. El `al_terminar` no
puede viajar como función a otra máquina: viaja como descriptor (`cierres`, ver
`_con_cierre` en `consola/app.py`) y el obrero lo vuelve a armar.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, insert, select, update

from .datos import Base, trabajos as tabla
from .trabajos import Trabajo

# Lo que puede demorar Google en encender la máquina de un trabajo. Pasado eso sin
# que el obrero lo tome, se da por perdido: si no, el loteo quedaría "en algo" para
# siempre y no se podría volver a lanzar.
ABANDONO_EN_COLA = timedelta(minutes=10)
# El obrero late cada `LATIDO` segundos. Una máquina que muere por memoria no avisa:
# deja de latir, y a los tres minutos sin latido el trabajo se da por caído.
ABANDONO_CORRIENDO = timedelta(minutes=3)
ESPERA_SONDEO = 2.0

ENCENDIENDO = "Encendiendo la máquina que corre este trabajo (tarda menos de un minuto)…"
AVISO_CAIDO = ("la máquina que corría este trabajo se apagó sin terminar (puede ser "
               "falta de memoria): vuelve a lanzarlo, y si se repite, avísanos")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _utc(momento: datetime | None) -> datetime | None:
    # SQLite devuelve las fechas sin zona aunque se guarden con ella.
    if momento is not None and momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)
    return momento


class TrabajosRemotos:
    """`lanzador(id, pesado)` enciende la máquina que corre `consola.obrero <id>`.
    En el servidor es `LanzadorCloudRun`; en las pruebas, uno que corre el obrero en
    un hilo o un subproceso."""

    remoto = True

    def __init__(self, base: Base, lanzador):
        self.base = base
        self.lanzador = lanzador
        self._candado = threading.Lock()

    # --- lo que usan las rutas -------------------------------------------------------

    def lanzar(self, proyecto: str, accion: str, comando: list[str],
               al_terminar=None, lineas: list[str] | None = None, al_lanzar=None,
               pesado: bool = True) -> str:
        cierres = [] if al_terminar is None else getattr(al_terminar, "cierres", None)
        if cierres is None:
            # Un error de programación: una función suelta no se puede mandar a otra
            # máquina, y correr el trabajo sin guardar su resultado sería peor.
            raise TypeError("este al_terminar no dice cómo armarlo en el obrero (_con_cierre)")
        with self._candado:
            if self.corriendo(proyecto):
                raise RuntimeError(f"{proyecto} ya está en algo; espera a que termine")
            # Google tarda unos segundos en encender la máquina: que la pantalla no
            # parezca pegada mientras tanto.
            trabajo = Trabajo(id=uuid.uuid4().hex[:12], proyecto=proyecto, accion=accion,
                              estado="en_cola", lineas=list(lineas or []) + [ENCENDIENDO],
                              pesado=pesado, comenzo=_ahora())
            if al_lanzar is not None:
                al_lanzar(trabajo)
            with self.base.motor.begin() as con:
                con.execute(insert(tabla).values(
                    id=trabajo.id, proyecto=proyecto, accion=accion, estado="en_cola",
                    pesado=pesado, vencido=False, comando=json.dumps(comando),
                    cierres=json.dumps(cierres), lineas=json.dumps(trabajo.lineas),
                    comenzo=trabajo.comenzo))
        try:
            self.lanzador(trabajo.id, pesado)
        except Exception as error:          # noqa: BLE001 - lo ve la pantalla
            self.anotar(trabajo.id, estado="falló", codigo=-1,
                        lineas=trabajo.lineas + [f"no pude encender la máquina del trabajo: {error}"])
        return trabajo.id

    def ver(self, identificador: str) -> Trabajo:
        with self.base.motor.connect() as con:
            fila = con.execute(select(tabla).where(tabla.c.id == identificador)).first()
        if fila is None:
            raise KeyError(f"no existe el trabajo {identificador!r}")
        return self._vigente(fila)

    def esperar(self, identificador: str, tope: float | None = None) -> Trabajo:
        fin = None if tope is None else time.monotonic() + tope
        while True:
            trabajo = self.ver(identificador)
            if trabajo.terminado or (fin is not None and time.monotonic() >= fin):
                return trabajo
            time.sleep(ESPERA_SONDEO)

    def ultimo(self, proyecto: str) -> Trabajo | None:
        with self.base.motor.connect() as con:
            fila = con.execute(select(tabla).where(tabla.c.proyecto == proyecto)
                               .order_by(tabla.c.comenzo.desc()).limit(1)).first()
        return None if fila is None else self._vigente(fila)

    def corriendo(self, proyecto: str) -> bool:
        with self.base.motor.connect() as con:
            filas = con.execute(select(tabla).where(
                tabla.c.proyecto == proyecto,
                tabla.c.estado.in_(("en_cola", "corriendo")))).all()
        return any(not self._vigente(fila).terminado for fila in filas)

    def olvidar(self, proyecto: str) -> None:
        with self.base.motor.begin() as con:
            con.execute(delete(tabla).where(tabla.c.proyecto == proyecto,
                                            tabla.c.estado.not_in(("en_cola", "corriendo"))))

    def cortar_todo(self) -> None:
        """Nada: cada trabajo corre en su propia máquina, y que la consola se apague
        (lo hace sola cuando nadie la usa, o en un despliegue) no lo corta."""

    # --- lo que usa el obrero ----------------------------------------------------------

    def fila(self, identificador: str):
        with self.base.motor.connect() as con:
            return con.execute(select(tabla).where(tabla.c.id == identificador)).first()

    def tomar(self, identificador: str) -> bool:
        """El obrero lo marca como suyo. False si ya no estaba esperando (Google
        reintentó la ejecución, o se dio por perdido): entonces no se corre dos veces."""
        with self.base.motor.begin() as con:
            hecho = con.execute(update(tabla).where(
                tabla.c.id == identificador, tabla.c.estado == "en_cola").values(
                estado="corriendo", latido=_ahora()))
        return hecho.rowcount == 1

    def anotar(self, identificador: str, **campos) -> None:
        if "lineas" in campos:
            campos["lineas"] = json.dumps(campos["lineas"])
        with self.base.motor.begin() as con:
            con.execute(update(tabla).where(tabla.c.id == identificador)
                        .values(latido=_ahora(), **campos))

    # --- por dentro -----------------------------------------------------------------

    def _vigente(self, fila) -> Trabajo:
        """La fila como `Trabajo`, y si su máquina murió sin avisar, ya como fallido."""
        trabajo = _trabajo(fila)
        if trabajo.terminado:
            return trabajo
        if trabajo.estado == "en_cola":
            perdido = _ahora() - trabajo.comenzo > ABANDONO_EN_COLA
        else:
            perdido = _ahora() - (_utc(fila.latido) or trabajo.comenzo) > ABANDONO_CORRIENDO
        if perdido:
            trabajo.lineas.append(AVISO_CAIDO)
            # Solo si sigue como se leyó: si el obrero alcanzó a cerrarlo, gana él.
            with self.base.motor.begin() as con:
                con.execute(update(tabla).where(tabla.c.id == trabajo.id,
                                                tabla.c.estado == fila.estado).values(
                    estado="falló", codigo=-1, lineas=json.dumps(trabajo.lineas)))
            trabajo.estado, trabajo.codigo = "falló", -1
        return trabajo


def _trabajo(fila) -> Trabajo:
    trabajo = Trabajo(id=fila.id, proyecto=fila.proyecto, accion=fila.accion,
                      estado=fila.estado, codigo=fila.codigo,
                      lineas=json.loads(fila.lineas), comenzo=_utc(fila.comenzo),
                      pesado=bool(fila.pesado), vencido=bool(fila.vencido))
    if trabajo.terminado:
        trabajo.fin.set()
    return trabajo


class LanzadorCloudRun:
    """Ejecuta el Cloud Run Job que corresponde, con el id del trabajo como argumento.

    Sin librería de Google: es un POST a la API de Cloud Run con el token de la cuenta
    de servicio que da el servidor de metadatos. La cuenta de la consola necesita poder
    ejecutar jobs con argumentos propios (`roles/run.developer`, ver el README)."""

    METADATOS = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"

    def __init__(self, proyecto: str, region: str, job_pesado: str, job_liviano: str):
        self.proyecto, self.region = proyecto, region
        self.job_pesado, self.job_liviano = job_pesado, job_liviano

    def __call__(self, identificador: str, pesado: bool) -> str:
        job = self.job_pesado if pesado else self.job_liviano
        url = (f"https://run.googleapis.com/v2/projects/{self.proyecto}/locations/"
               f"{self.region}/jobs/{job}:run")
        cuerpo = {"overrides": {"containerOverrides": [
            {"args": ["--", "python", "-m", "consola.obrero", identificador]}]}}
        pedido = urllib.request.Request(
            url, data=json.dumps(cuerpo).encode(), method="POST",
            headers={"Authorization": f"Bearer {self._token()}",
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(pedido, timeout=30) as respuesta:
            return json.loads(respuesta.read()).get("name", "")

    def _token(self) -> str:
        pedido = urllib.request.Request(self.METADATOS, headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(pedido, timeout=10) as respuesta:
            return json.loads(respuesta.read())["access_token"]


def remotos_del_entorno(base: Base) -> TrabajosRemotos | None:
    """Con `CONSOLA_TRABAJOS=cloudrun` (lo pone `cloudbuild.yaml`), los trabajos van a
    Cloud Run Jobs. Sin eso, None: en el computador y en las pruebas siguen corriendo
    en la misma consola, como siempre."""
    if os.environ.get("CONSOLA_TRABAJOS") != "cloudrun":
        return None
    faltan = [v for v in ("CONSOLA_GCP_PROYECTO", "CONSOLA_GCP_REGION",
                          "CONSOLA_JOB_PESADO", "CONSOLA_JOB_LIVIANO") if not os.environ.get(v)]
    if faltan:
        raise RuntimeError(f"CONSOLA_TRABAJOS=cloudrun pide también {', '.join(faltan)}")
    return TrabajosRemotos(base, LanzadorCloudRun(
        os.environ["CONSOLA_GCP_PROYECTO"], os.environ["CONSOLA_GCP_REGION"],
        os.environ["CONSOLA_JOB_PESADO"], os.environ["CONSOLA_JOB_LIVIANO"]))
