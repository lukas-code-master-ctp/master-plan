"""Poner al día el visor de los loteos publicados al arrancar la consola."""
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import consola.app as app_de_la_consola
from consola.acceso import Acceso
from consola.app import _anotar_publicacion, _republicar_en_segundo_plano, crear_app
from consola.datos import Base
from consola.disenos import Disenos
from consola.proyectos import Registro
from consola.republicar import pendientes, republicar
from consola.trabajos import Trabajos
from pipeline import config, visor

VIEJA = "0" * 64
NUEVA = "f" * 64


def guion(codigo):
    return [sys.executable, "-c", codigo]


class ComandosDePrueba:
    """En vez de copiar el visor y subirlo, un guion que deja el rastro que deja
    `publicar.sh` —o que falla, para los loteos que se le pidan."""

    def __init__(self, fallan=()):
        self.pedidos = []
        self.fallan = set(fallan)

    def actualizar_visor(self, proyecto, vercel_proyecto):
        self.pedidos.append((proyecto.slug, vercel_proyecto))
        if proyecto.slug in self.fallan:
            return guion("import sys; print('no existe ese proyecto en el hosting'); sys.exit(1)")
        rastro = str(proyecto.salida.base / "publicacion.json")
        url = f"https://{vercel_proyecto}-nueva.vercel.app"
        return guion("import json, pathlib; pathlib.Path(%r).write_text(json.dumps("
                     "{'proyecto': %r, 'url': %r}))" % (rastro, vercel_proyecto, url))


@pytest.fixture
def mundo(tmp_path):
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    cliente, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")
    registro = Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas")
    disenos = Disenos(base=base, carpeta=tmp_path / "disenos")
    return SimpleNamespace(base=base, cliente_id=cliente.id, registro=registro,
                           disenos=disenos, tmp_path=tmp_path)


def loteo(mundo, nombre, *, pagado=True, construido=True, publicado=True, huella=VIEJA,
          vercel=True):
    """Un loteo en el estado pedido, sin pasar por el pipeline ni por el hosting."""
    registro, base = mundo.registro, mundo.base
    proyecto = (registro.habilitar(mundo.cliente_id, nombre, nota_cobro="ok") if pagado
                else registro.crear(mundo.cliente_id, nombre))
    slug = proyecto.slug
    if construido:
        salida = config.Salida(registro.salidas / slug)
        salida.datos.mkdir(parents=True, exist_ok=True)
        (salida.datos / "parcelas.json").write_text('{"resumen": {}}', encoding="utf-8")
    if publicado:
        base.anotar_publicacion(slug, f"masterplan-{slug}" if vercel else None,
                                f"https://masterplan-{slug}.vercel.app")
    if huella is not None:
        base.anotar_visor(slug, huella)
    return slug


def recorrer(mundo, comandos, trabajos=None, huella=NUEVA):
    avisos = []
    cuenta = republicar(mundo.registro.todos(), trabajos or Trabajos(), comandos,
                        mundo.disenos, huella, avisar=avisos.append)
    return cuenta, avisos


# --- quiénes están pendientes ---------------------------------------------------

def test_solo_los_publicados_pagados_y_construidos_con_otro_visor(mundo):
    atrasado = loteo(mundo, "Atrasado")
    sin_anotar = loteo(mundo, "Sin Anotar", huella=None)
    loteo(mundo, "Al Dia", huella=NUEVA)
    loteo(mundo, "Sin Publicar", publicado=False)
    loteo(mundo, "Sin Pagar", pagado=False)
    loteo(mundo, "Sin Construir", construido=False)

    slugs = [p.slug for p in pendientes(mundo.registro.todos(), NUEVA)]

    assert slugs == sorted([atrasado, sin_anotar])


# --- el recorrido ---------------------------------------------------------------

def test_un_loteo_con_el_visor_viejo_queda_al_dia(mundo):
    slug = loteo(mundo, "Las Araucarias")
    comandos = ComandosDePrueba()

    cuenta, avisos = recorrer(mundo, comandos)

    assert cuenta == {"hechos": 1, "fallidos": 0, "saltados": 0}
    assert comandos.pedidos == [(slug, f"masterplan-{slug}")]
    guardado = mundo.base.proyecto(slug)
    assert guardado.visor_publicado == NUEVA
    # La URL es la que devolvió el hosting, leída de publicacion.json.
    assert guardado.url_publicada == f"https://masterplan-{slug}-nueva.vercel.app"
    # El diseño quedó escrito en el sitio antes de subirlo.
    assert (mundo.registro.salidas / slug / "sitio" / "datos" / "diseno.json").is_file()
    assert all(a.startswith("[republicar]") for a in avisos)
    assert NUEVA[:12] in avisos[0]


def test_sin_rastro_del_hosting_conserva_la_url_que_tenia(mundo):
    slug = loteo(mundo, "Las Araucarias")

    class SinRastro(ComandosDePrueba):
        def actualizar_visor(self, proyecto, vercel_proyecto):
            self.pedidos.append((proyecto.slug, vercel_proyecto))
            return guion("print('subido')")

    recorrer(mundo, SinRastro())

    guardado = mundo.base.proyecto(slug)
    assert guardado.url_publicada == f"https://masterplan-{slug}.vercel.app"
    assert guardado.visor_publicado == NUEVA


def test_los_que_no_corresponden_no_se_tocan(mundo):
    intocables = [loteo(mundo, "Al Dia", huella=NUEVA),
                  loteo(mundo, "Sin Publicar", publicado=False),
                  loteo(mundo, "Sin Pagar", pagado=False),
                  loteo(mundo, "Sin Construir", construido=False)]
    antes = {s: mundo.base.proyecto(s) for s in intocables}
    comandos = ComandosDePrueba()

    cuenta, _ = recorrer(mundo, comandos)

    assert comandos.pedidos == []
    assert cuenta == {"hechos": 0, "fallidos": 0, "saltados": 0}
    for slug in intocables:
        assert mundo.base.proyecto(slug) == antes[slug]


def test_uno_con_un_trabajo_en_curso_se_salta(mundo):
    ocupado = loteo(mundo, "Ocupado")
    trabajos = Trabajos()
    trabajos.lanzar(ocupado, "construir", guion("import time; time.sleep(3)"))
    comandos = ComandosDePrueba()

    cuenta, avisos = recorrer(mundo, comandos, trabajos)

    assert comandos.pedidos == []
    assert cuenta["saltados"] == 1
    assert mundo.base.proyecto(ocupado).visor_publicado == VIEJA
    assert any(ocupado in a and "en curso" in a for a in avisos)


def test_si_otro_le_gana_el_loteo_se_salta(mundo):
    """Entre preguntar si está libre y lanzar, alguien pudo lanzar otra cosa."""
    slug = loteo(mundo, "Carrera")

    class Ganados(Trabajos):
        def lanzar(self, *args, **kwargs):
            raise RuntimeError("ya está en algo")

    cuenta, _ = recorrer(mundo, ComandosDePrueba(), Ganados())

    assert cuenta == {"hechos": 0, "fallidos": 0, "saltados": 1}
    assert mundo.base.proyecto(slug).visor_publicado == VIEJA


def test_un_fallo_no_detiene_a_los_demas(mundo):
    primero = loteo(mundo, "Aaa Falla")
    segundo = loteo(mundo, "Bbb Sale Bien")
    comandos = ComandosDePrueba(fallan={primero})

    cuenta, avisos = recorrer(mundo, comandos)

    assert [s for s, _ in comandos.pedidos] == [primero, segundo]
    assert cuenta == {"hechos": 1, "fallidos": 1, "saltados": 0}
    assert mundo.base.proyecto(primero).visor_publicado == VIEJA
    assert mundo.base.proyecto(segundo).visor_publicado == NUEVA
    assert any(primero in a and "no existe ese proyecto" in a for a in avisos)


def test_una_excepcion_en_un_loteo_no_detiene_a_los_demas(mundo):
    primero = loteo(mundo, "Aaa Revienta")
    segundo = loteo(mundo, "Bbb Sale Bien")

    class Revienta(ComandosDePrueba):
        def actualizar_visor(self, proyecto, vercel_proyecto):
            if proyecto.slug == primero:
                raise OSError("disco lleno")
            return super().actualizar_visor(proyecto, vercel_proyecto)

    cuenta, avisos = recorrer(mundo, Revienta())

    assert cuenta == {"hechos": 1, "fallidos": 1, "saltados": 0}
    assert mundo.base.proyecto(segundo).visor_publicado == NUEVA
    assert any(primero in a and "disco lleno" in a for a in avisos)


def test_sin_nombre_en_el_hosting_se_salta_y_nunca_se_crea(mundo):
    slug = loteo(mundo, "Huerfano", vercel=False)
    comandos = ComandosDePrueba()

    cuenta, avisos = recorrer(mundo, comandos)

    assert comandos.pedidos == []
    assert cuenta["saltados"] == 1
    assert any(slug in a for a in avisos)


# --- publicar a mano ------------------------------------------------------------

def test_publicar_a_mano_anota_la_huella_del_visor(mundo):
    slug = loteo(mundo, "A Mano", publicado=False, huella=None)
    mios = mundo.registro.todos()

    guardar = _anotar_publicacion(mios, mios.ver(slug), f"masterplan-{slug}")
    guardar(SimpleNamespace(estado="listo"))

    assert mundo.base.proyecto(slug).visor_publicado == visor.huella()


def test_una_publicacion_fallida_no_anota_la_huella(mundo):
    slug = loteo(mundo, "A Mano", publicado=False, huella=None)
    mios = mundo.registro.todos()

    _anotar_publicacion(mios, mios.ver(slug), f"masterplan-{slug}")(
        SimpleNamespace(estado="falló"))

    assert mundo.base.proyecto(slug).visor_publicado is None


# --- el gancho al arrancar ------------------------------------------------------

def consola(mundo, comandos, **opciones):
    return crear_app(registro=mundo.registro, trabajos=Trabajos(), comandos=comandos,
                     acceso=Acceso(base=mundo.base, secreto="un-secreto", local=True),
                     base=mundo.base, disenos=mundo.disenos, google=None, **opciones)


@pytest.fixture
def lanzamientos(monkeypatch):
    """Cuántas veces el arranque lanzó el recorrido, sin lanzarlo de verdad."""
    llamadas = []
    monkeypatch.setattr(app_de_la_consola, "_republicar_en_segundo_plano",
                        lambda *args: llamadas.append(args))
    return llamadas


def test_con_el_interruptor_apagado_arrancar_no_lanza_nada(mundo, lanzamientos):
    with TestClient(consola(mundo, ComandosDePrueba(), republicar_al_arrancar=False)):
        pass

    assert lanzamientos == []


def test_sin_la_variable_de_entorno_arrancar_no_lanza_nada(mundo, lanzamientos, monkeypatch):
    monkeypatch.delenv("CONSOLA_REPUBLICAR_AL_ARRANCAR", raising=False)

    with TestClient(consola(mundo, ComandosDePrueba())):
        pass

    assert lanzamientos == []


def test_la_variable_de_entorno_enciende_el_recorrido(mundo, lanzamientos, monkeypatch):
    monkeypatch.setenv("CONSOLA_REPUBLICAR_AL_ARRANCAR", "1")

    with TestClient(consola(mundo, ComandosDePrueba())):
        pass

    assert len(lanzamientos) == 1


def test_con_el_interruptor_encendido_arrancar_pone_al_dia_los_atrasados(mundo):
    atrasado = loteo(mundo, "Atrasado")
    al_dia = loteo(mundo, "Al Dia", huella=visor.huella())
    comandos = ComandosDePrueba()

    with TestClient(consola(mundo, comandos, republicar_al_arrancar=True)):
        fin = time.monotonic() + 15
        while (mundo.base.proyecto(atrasado).visor_publicado != visor.huella()
               and time.monotonic() < fin):
            time.sleep(0.05)

    assert mundo.base.proyecto(atrasado).visor_publicado == visor.huella()
    assert [s for s, _ in comandos.pedidos] == [atrasado]
    assert al_dia not in [s for s, _ in comandos.pedidos]


def test_un_error_en_el_recorrido_no_bota_la_consola(mundo, monkeypatch, capsys):
    def revienta(*args, **kwargs):
        raise RuntimeError("la base no contesta")

    monkeypatch.setattr(app_de_la_consola, "republicar", revienta)

    hilo = _republicar_en_segundo_plano(mundo.registro, Trabajos(), ComandosDePrueba(),
                                        mundo.disenos)
    hilo.join(10)

    assert not hilo.is_alive()
    assert hilo.daemon
    salida = capsys.readouterr().out
    assert "[republicar]" in salida and "la base no contesta" in salida


def test_el_recorrido_corre_en_un_hilo_aparte(mundo, monkeypatch):
    listo = threading.Event()
    hilos = []

    def anotar(*args, **kwargs):
        hilos.append(threading.current_thread())
        listo.set()

    monkeypatch.setattr(app_de_la_consola, "republicar", anotar)

    _republicar_en_segundo_plano(mundo.registro, Trabajos(), ComandosDePrueba(), mundo.disenos)

    assert listo.wait(10)
    assert hilos[0] is not threading.main_thread()
