"""Trabajos en un Cloud Run Job: la consola anota, el obrero corre y anota el avance."""
import json
import sys
import threading
from datetime import timedelta

import pytest
from sqlalchemy import update

from consola import obrero
from consola.datos import Base, trabajos as tabla
from consola.trabajos_remotos import (
    AVISO_CAIDO,
    ENCENDIENDO,
    TrabajosRemotos,
    _ahora,
    remotos_del_entorno,
)


def guion(codigo):
    return [sys.executable, "-c", codigo]


def con_cierre(funcion, **descriptor):
    funcion.cierres = [descriptor]
    return funcion


@pytest.fixture
def base(tmp_path):
    return Base(f"sqlite:///{tmp_path / 'consola.db'}")


class EnHilo:
    """Hace de Cloud Run: corre el obrero en un hilo, con la misma base."""

    def __init__(self, base, cierres=None):
        self.base, self.cierres, self.lanzados, self.hilos = base, cierres or {}, [], []

    def armar(self, descriptores):
        avisos = [self.cierres[d["tipo"]](d) for d in descriptores]

        def todos(trabajo):
            for aviso in avisos:
                aviso(trabajo)
        return todos

    def __call__(self, identificador, pesado):
        self.lanzados.append((identificador, pesado))
        hilo = threading.Thread(target=obrero.correr, args=(identificador, self.base),
                                kwargs={"armar_cierre": self.armar, "latido": 0.05})
        hilo.start()
        self.hilos.append(hilo)
        return f"ejecuciones/{identificador}"


def test_corre_en_el_obrero_y_la_consola_ve_el_avance(base):
    lanzador = EnHilo(base)
    remotos = TrabajosRemotos(base, lanzador)

    identificador = remotos.lanzar("loteo", "construir", guion("print('hola')"),
                                   lineas=["Preparando."])
    trabajo = remotos.esperar(identificador, tope=20)

    assert lanzador.lanzados == [(identificador, True)]
    assert trabajo.estado == "listo" and trabajo.codigo == 0
    assert trabajo.lineas == ["Preparando.", ENCENDIENDO, "hola"]
    assert remotos.ultimo("loteo").id == identificador
    assert not remotos.corriendo("loteo")


def test_un_trabajo_que_falla_queda_fallido(base):
    remotos = TrabajosRemotos(base, EnHilo(base))

    identificador = remotos.lanzar("loteo", "publicar", guion("import sys; sys.exit(4)"),
                                   pesado=False)
    trabajo = remotos.esperar(identificador, tope=20)

    assert trabajo.estado == "falló" and trabajo.codigo == 4


def test_el_cierre_viaja_como_descriptor_y_corre_en_el_obrero(base):
    vistos = []
    lanzador = EnHilo(base, {"anotar": lambda d: lambda t: vistos.append((d["slug"], t.estado, t.id))})
    remotos = TrabajosRemotos(base, lanzador)

    def al_terminar(trabajo):
        raise AssertionError("la función no viaja: se arma de nuevo en el obrero")

    identificador = remotos.lanzar("loteo", "construir", guion("pass"),
                                   al_terminar=con_cierre(al_terminar, tipo="anotar", slug="loteo"))
    remotos.esperar(identificador, tope=20)

    # Con el mismo id: lo que el trabajo anotó al lanzarse (lectura.json) tiene que calzar.
    assert vistos == [("loteo", "listo", identificador)]


def test_un_al_terminar_sin_descriptor_no_se_lanza(base):
    remotos = TrabajosRemotos(base, EnHilo(base))

    with pytest.raises(TypeError):
        remotos.lanzar("loteo", "construir", guion("pass"), al_terminar=lambda t: None)
    assert remotos.ultimo("loteo") is None


def test_no_lanza_dos_sobre_el_mismo_loteo(base):
    remotos = TrabajosRemotos(base, lambda identificador, pesado: None)   # nunca parte

    remotos.lanzar("loteo", "construir", guion("pass"))

    assert remotos.corriendo("loteo")
    with pytest.raises(RuntimeError):
        remotos.lanzar("loteo", "publicar", guion("pass"), pesado=False)
    assert not remotos.corriendo("otro")


def test_si_no_enciende_la_maquina_queda_fallido_y_suelta_el_loteo(base):
    def sin_permiso(identificador, pesado):
        raise PermissionError("403")
    remotos = TrabajosRemotos(base, sin_permiso)

    trabajo = remotos.ver(remotos.lanzar("loteo", "construir", guion("pass")))

    assert trabajo.estado == "falló"
    assert "no pude encender la máquina" in trabajo.lineas[-1]
    assert not remotos.corriendo("loteo")


def test_una_maquina_que_deja_de_latir_se_da_por_caida(base):
    remotos = TrabajosRemotos(base, lambda identificador, pesado: None)
    identificador = remotos.lanzar("loteo", "construir", guion("pass"))
    assert remotos.tomar(identificador)
    with base.motor.begin() as con:
        con.execute(update(tabla).where(tabla.c.id == identificador)
                    .values(latido=_ahora() - timedelta(minutes=10)))

    assert not remotos.corriendo("loteo")
    trabajo = remotos.ver(identificador)
    assert trabajo.estado == "falló" and trabajo.lineas[-1] == AVISO_CAIDO


def test_uno_que_nunca_parte_se_da_por_perdido(base):
    remotos = TrabajosRemotos(base, lambda identificador, pesado: None)
    identificador = remotos.lanzar("loteo", "construir", guion("pass"))
    with base.motor.begin() as con:
        con.execute(update(tabla).where(tabla.c.id == identificador)
                    .values(comenzo=_ahora() - timedelta(hours=1)))

    assert remotos.ver(identificador).estado == "falló"


def test_el_obrero_no_corre_dos_veces_el_mismo_trabajo(base):
    remotos = TrabajosRemotos(base, lambda identificador, pesado: None)
    identificador = remotos.lanzar("loteo", "construir", guion("print('una vez')"))

    assert obrero.correr(identificador, base, armar_cierre=lambda d: None, latido=0.05) == "listo"
    assert obrero.correr(identificador, base, armar_cierre=lambda d: None) == "saltado"
    assert remotos.ver(identificador).lineas == [ENCENDIENDO, "una vez"]


def test_olvidar_borra_solo_los_terminados(base):
    remotos = TrabajosRemotos(base, EnHilo(base))
    hecho = remotos.lanzar("loteo", "construir", guion("pass"))
    remotos.esperar(hecho, tope=20)

    remotos.olvidar("loteo")

    assert remotos.ultimo("loteo") is None


def test_el_entorno_elige(monkeypatch, base):
    monkeypatch.delenv("CONSOLA_TRABAJOS", raising=False)
    assert remotos_del_entorno(base) is None

    monkeypatch.setenv("CONSOLA_TRABAJOS", "cloudrun")
    with pytest.raises(RuntimeError, match="CONSOLA_GCP_PROYECTO"):
        remotos_del_entorno(base)

    for variable, valor in (("CONSOLA_GCP_PROYECTO", "p"), ("CONSOLA_GCP_REGION", "r"),
                            ("CONSOLA_JOB_PESADO", "pesado"), ("CONSOLA_JOB_LIVIANO", "liviano")):
        monkeypatch.setenv(variable, valor)
    remotos = remotos_del_entorno(base)
    assert remotos.lanzador.job_pesado == "pesado"


def test_el_lanzador_pide_el_job_con_el_id(monkeypatch):
    from consola import trabajos_remotos

    pedidos = []

    class Respuesta:
        def __init__(self, cuerpo):
            self.cuerpo = cuerpo

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return json.dumps(self.cuerpo).encode()

    def abrir(pedido, timeout):
        pedidos.append(pedido)
        if "metadata" in pedido.full_url:
            return Respuesta({"access_token": "tok"})
        return Respuesta({"name": "operaciones/1"})

    monkeypatch.setattr(trabajos_remotos.urllib.request, "urlopen", abrir)
    lanzador = trabajos_remotos.LanzadorCloudRun("proy", "southamerica-east1", "pesado", "liviano")

    assert lanzador("abc123", pesado=False) == "operaciones/1"
    pedido = pedidos[-1]
    assert pedido.full_url.endswith("/projects/proy/locations/southamerica-east1/jobs/liviano:run")
    assert pedido.headers["Authorization"] == "Bearer tok"
    assert json.loads(pedido.data)["overrides"]["containerOverrides"][0]["args"][-1] == "abc123"


def test_los_cierres_de_la_consola_viajan_y_se_vuelven_a_armar(base, tmp_path):
    from consola.app import _aplicar_diseno, _cerrar_lectura, _en_orden, cierre_desde

    class Vista:
        pass

    class Plano:
        carpeta = tmp_path

    junto = _en_orden(_aplicar_diseno(Vista(), None, "loteo"),
                      _cerrar_lectura(Plano(), "mi-kmz", {"semillas": [1]}))
    assert junto.cierres == [{"tipo": "diseno", "slug": "loteo"},
                             {"tipo": "lectura", "kmz": "mi-kmz", "entradas": {"semillas": [1]}}]
    # Lo que se manda a la base tiene que poder escribirse como JSON.
    assert json.loads(json.dumps(junto.cierres)) == junto.cierres

    class Registro:
        def todos(self):
            return Vista()

    armado = cierre_desde([{"tipo": "diseno", "slug": "loteo"}], Registro(), None, None)
    assert armado.cierres == [{"tipo": "diseno", "slug": "loteo"}]
    with pytest.raises(ValueError):
        cierre_desde([{"tipo": "otro"}], Registro(), None, None)
