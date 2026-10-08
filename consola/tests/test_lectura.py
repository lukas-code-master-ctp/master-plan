"""La lectura del plano sobrevive a que se caiga la instancia: la consola deja anotado
en `lectura.json` qué está leyendo y, al arrancar, la relanza (hasta 3 intentos)."""
import json
import os
import sys
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from consola.acceso import Acceso
from consola.app import INTENTOS_LECTURA, LECTURA, crear_app
from consola.datos import Base
from consola.disenos import Disenos
from consola.kmzs import RegistroKmz
from consola.proyectos import Registro
from consola.tests.test_app import CLAVE, ComandosDePrueba
from consola.tests.test_kmz import subir
from consola.tests.test_plano import ENTRADAS
from consola.trabajos import Trabajos

RETOMA = "Se retoma la lectura del plano donde quedó (intento {} de 3)."


@pytest.fixture
def mundo(tmp_path):
    """La base y las carpetas, que sobreviven al cambio de instancia; cada `consola()`
    es una instancia nueva, con sus trabajos en memoria desde cero."""
    base = Base(f"sqlite:///{tmp_path / 'consola.db'}")
    base.crear_cliente("Los Robles", "ana@losrobles.cl", "Los Robles")
    base.cambiar_clave("ana@losrobles.cl", CLAVE)
    registro = Registro(base=base, subidas=tmp_path / "proyectos", salidas=tmp_path / "salidas")
    comandos = ComandosDePrueba()

    def consola(**opciones):
        trabajos = Trabajos()
        app = crear_app(registro=registro, trabajos=trabajos, comandos=comandos,
                        acceso=Acceso(base=base, secreto="un-secreto", local=True), base=base,
                        disenos=Disenos(base=base, carpeta=tmp_path / "disenos"), google=None,
                        kmzs=RegistroKmz(base=base, carpeta=tmp_path / "kmz",
                                         limites=registro.limites), **opciones)
        return app, trabajos

    return SimpleNamespace(consola=consola, comandos=comandos, kmz=tmp_path / "kmz")


def entrar(web):
    assert web.post("/entrar", data={"email": "ana@losrobles.cl", "clave": CLAVE}).status_code == 303
    return web


def kmz_para_leer(web, nombre="Los Robles"):
    slug = web.post("/api/kmz", json={"nombre": nombre}).json()["slug"]
    assert subir(web, slug).status_code == 201
    assert web.put(f"/api/kmz/{slug}/entradas", json=ENTRADAS).status_code == 200
    return slug


def guion(comandos, monkeypatch, codigo):
    monkeypatch.setattr(comandos, "digitalizar_carpeta", lambda c: [sys.executable, "-c", codigo])


def leer(archivo):
    return json.loads(archivo.read_text(encoding="utf-8"))


# --- al lanzar --------------------------------------------------------------------------

@pytest.mark.parametrize("codigo", ["import time; time.sleep(1)", "import sys, time; time.sleep(1); sys.exit(3)"],
                         ids=["listo", "falló"])
def test_lanzar_anota_la_lectura_y_terminar_la_borra(mundo, monkeypatch, codigo):
    app, trabajos = mundo.consola()
    web = entrar(TestClient(app, follow_redirects=False))
    slug = kmz_para_leer(web)
    guion(mundo.comandos, monkeypatch, codigo)

    identificador = web.post(f"/api/kmz/{slug}/digitalizar").json()["id"]

    anotada = leer(mundo.kmz / slug / LECTURA)
    assert anotada["intento"] == 1 and anotada["trabajo"] == identificador and anotada["comenzo"]
    trabajo = trabajos.esperar(identificador, tope=15)
    assert not (mundo.kmz / slug / LECTURA).exists()
    # La primera lectura no avisa nada: la línea es solo para las retomadas.
    assert not any("Se retoma" in linea for linea in trabajo.lineas)


def test_un_409_no_pisa_la_lectura_en_curso(mundo, monkeypatch):
    app, trabajos = mundo.consola()
    web = entrar(TestClient(app, follow_redirects=False))
    slug = kmz_para_leer(web)
    guion(mundo.comandos, monkeypatch, "import time; time.sleep(2)")
    identificador = web.post(f"/api/kmz/{slug}/digitalizar").json()["id"]
    antes = (mundo.kmz / slug / LECTURA).read_text(encoding="utf-8")

    assert web.post(f"/api/kmz/{slug}/digitalizar").status_code == 409

    assert (mundo.kmz / slug / LECTURA).read_text(encoding="utf-8") == antes
    trabajos.esperar(identificador, tope=15)
    assert not (mundo.kmz / slug / LECTURA).exists()


def test_lo_anotado_al_lanzar_no_queda_si_el_trabajo_no_parte(tmp_path):
    trabajos = Trabajos()
    trabajos.lanzar("kmz:a", "digitalizar-plano", [sys.executable, "-c", "import time; time.sleep(1)"])
    anotados = []

    with pytest.raises(RuntimeError):
        trabajos.lanzar("kmz:a", "digitalizar-plano", [sys.executable, "-c", ""],
                        al_lanzar=anotados.append)

    assert anotados == []


# --- al arrancar ------------------------------------------------------------------------

def caida(mundo, intento=1, contenido=None):
    """Una instancia que lanzó la lectura y murió antes de terminarla."""
    app, _ = mundo.consola()
    web = entrar(TestClient(app, follow_redirects=False))
    slug = kmz_para_leer(web)
    texto = contenido if contenido is not None else json.dumps(
        {"intento": intento, "trabajo": "de-la-muerta", "comenzo": "2026-10-08T14:01:08+00:00"})
    (mundo.kmz / slug / LECTURA).write_text(texto, encoding="utf-8")
    return slug


def test_al_arrancar_se_retoma_la_lectura_que_quedo_a_medias(mundo, monkeypatch, capsys):
    slug = caida(mundo, intento=1)
    guion(mundo.comandos, monkeypatch, "import time; print('rótulos'); time.sleep(1)")
    app, trabajos = mundo.consola()

    with TestClient(app, follow_redirects=False) as web:
        # Recién arrancada, antes de cualquier otra cosa, ya se ve el trabajo.
        trabajo = entrar(web).get(f"/api/kmz/{slug}").json()["trabajo"]
        assert trabajo["proyecto"] == f"kmz:{slug}" and trabajo["accion"] == "digitalizar-plano"
        assert trabajo["lineas"][0] == RETOMA.format(2)
        assert leer(mundo.kmz / slug / LECTURA)["intento"] == 2
        trabajos.esperar(trabajo["id"], tope=15)

    assert not (mundo.kmz / slug / LECTURA).exists()
    assert f"{slug}: se retoma la lectura del plano (intento 2 de 3)" in capsys.readouterr().out


def test_la_tercera_caida_no_se_retoma(mundo):
    slug = caida(mundo, intento=INTENTOS_LECTURA)
    app, trabajos = mundo.consola()

    with TestClient(app, follow_redirects=False) as web:
        assert entrar(web).get(f"/api/kmz/{slug}").json()["trabajo"] is None

    assert not (mundo.kmz / slug / LECTURA).exists()


def test_un_lectura_json_ilegible_no_se_retoma(mundo):
    slug = caida(mundo, contenido="{roto")
    app, trabajos = mundo.consola()

    with TestClient(app, follow_redirects=False) as web:
        assert entrar(web).get(f"/api/kmz/{slug}").json()["trabajo"] is None

    assert not (mundo.kmz / slug / LECTURA).exists()


def test_un_kmz_que_ya_no_se_puede_leer_se_salta_y_los_demas_se_retoman(mundo):
    sin_pdf = caida(mundo)
    (mundo.kmz / sin_pdf / "plano.pdf").unlink()
    app, _ = mundo.consola()
    web = entrar(TestClient(app, follow_redirects=False))
    otro = kmz_para_leer(web, "Otro")
    (mundo.kmz / otro / LECTURA).write_text(json.dumps({"intento": 2}), encoding="utf-8")
    app, trabajos = mundo.consola()

    with TestClient(app, follow_redirects=False) as web:
        entrar(web)
        assert web.get(f"/api/kmz/{sin_pdf}").json()["trabajo"] is None
        trabajo = web.get(f"/api/kmz/{otro}").json()["trabajo"]
        assert trabajo["lineas"][0] == RETOMA.format(3)
        trabajos.esperar(trabajo["id"], tope=15)

    assert not (mundo.kmz / sin_pdf / LECTURA).exists()
    assert not (mundo.kmz / otro / LECTURA).exists()


def test_con_el_interruptor_apagado_no_se_retoma_nada(mundo):
    slug = caida(mundo)
    app, _ = mundo.consola(retomar_lecturas_al_arrancar=False)

    with TestClient(app, follow_redirects=False) as web:
        assert entrar(web).get(f"/api/kmz/{slug}").json()["trabajo"] is None

    assert (mundo.kmz / slug / LECTURA).exists()


def test_un_error_al_retomar_no_bota_el_arranque(mundo, monkeypatch, capsys):
    slug = caida(mundo)

    def revienta(carpeta):
        raise RuntimeError("sin pipeline")
    monkeypatch.setattr(mundo.comandos, "digitalizar_carpeta", revienta)
    app, _ = mundo.consola()

    with TestClient(app, follow_redirects=False) as web:
        assert entrar(web).get(f"/api/kmz/{slug}").status_code == 200

    assert "sin pipeline" in capsys.readouterr().out


def test_al_terminar_no_borra_la_lectura_de_otro_lanzamiento(mundo, monkeypatch):
    app, trabajos = mundo.consola()
    web = entrar(TestClient(app, follow_redirects=False))
    slug = kmz_para_leer(web)
    guion(mundo.comandos, monkeypatch, "import time; time.sleep(1)")
    identificador = web.post(f"/api/kmz/{slug}/digitalizar").json()["id"]
    # Lo que escribe un lanzamiento que entró mientras este cerraba.
    otra = {"intento": 1, "trabajo": "el-siguiente", "comenzo": "2026-10-08T14:01:08+00:00"}
    (mundo.kmz / slug / LECTURA).write_text(json.dumps(otra), encoding="utf-8")

    trabajos.esperar(identificador, tope=15)

    assert leer(mundo.kmz / slug / LECTURA) == otra


def test_una_lectura_que_ya_termino_no_se_relanza(mundo):
    """`lectura.json` quedó (no se pudo borrar) y después de la lectura se corrigieron
    los lotes: relanzarla los pisaría."""
    slug = caida(mundo)
    lectura = mundo.kmz / slug / LECTURA
    os.utime(lectura, (lectura.stat().st_atime, lectura.stat().st_mtime - 60))
    (mundo.kmz / slug / "digitalizado.json").write_text('{"corregido": true}', encoding="utf-8")
    app, _ = mundo.consola()

    with TestClient(app, follow_redirects=False) as web:
        assert entrar(web).get(f"/api/kmz/{slug}").json()["trabajo"] is None

    assert not lectura.exists()
    assert leer(mundo.kmz / slug / "digitalizado.json") == {"corregido": True}
