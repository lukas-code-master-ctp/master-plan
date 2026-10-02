"""Mis KMZ: crear un KMZ desde el plano aprobado, sin master, y descargarlo."""
import io
import json
import sys
from urllib.parse import unquote

import pytest

from consola.proyectos import Limites
from consola.tests.test_app import entrar, esperar_trabajo, montar
from consola.tests.test_plano import ENTRADAS, ancla, digitalizado_a_mano, pdf_del_plano
from pipeline.kmz import leer_kmz
from pipeline.plano.digitalizar import digitalizar
from pipeline.tests.plano_sintetico import dibujar


@pytest.fixture
def consola(tmp_path):
    app, base, registro, comandos = montar(tmp_path)
    return app, tmp_path / "kmz", registro, comandos


@pytest.fixture
def ana(consola):
    """Ana, con un KMZ recién creado."""
    app, carpeta, registro, comandos = consola
    web = entrar(app, "ana@losrobles.cl")
    respuesta = web.post("/api/kmz", json={"nombre": "Los Robles"})
    assert respuesta.status_code == 201, respuesta.text
    return web, respuesta.json()["slug"], carpeta, comandos


def subir(web, slug, contenido=None):
    contenido = pdf_del_plano() if contenido is None else contenido
    return web.post(f"/api/kmz/{slug}/plano", files={"archivo": ("plano.pdf", contenido, "application/pdf")})


def listo_para_ubicar(web, slug, carpeta, entradas=ENTRADAS):
    assert subir(web, slug).status_code == 201
    assert web.put(f"/api/kmz/{slug}/entradas", json=entradas).status_code == 200
    digitalizado_a_mano(carpeta / slug)


def lento(comandos, monkeypatch, segundos=2):
    monkeypatch.setattr(comandos, "digitalizar_carpeta",
                        lambda c: [sys.executable, "-c", f"import time; time.sleep({segundos})"])


# --- la entidad ------------------------------------------------------------------------

def test_crear_listar_renombrar_y_borrar(ana):
    web, slug, carpeta, _ = ana

    assert slug == "los-robles"
    assert (carpeta / slug).is_dir()
    tarjeta = web.get("/api/kmz").json()
    assert [(k["slug"], k["nombre"], k["paso"], k["lotes"], k["terminado"], k["trabajo"]) for k in tarjeta] == [
        ("los-robles", "Los Robles", "subir", None, False, None)]
    assert tarjeta[0]["creado_en"]

    renombrado = web.patch(f"/api/kmz/{slug}", json={"nombre": "  Robles Norte "})
    assert renombrado.status_code == 200, renombrado.text
    assert (renombrado.json()["slug"], renombrado.json()["nombre"]) == ("los-robles", "Robles Norte")
    assert web.get(f"/api/kmz/{slug}").json()["nombre"] == "Robles Norte"

    assert web.delete(f"/api/kmz/{slug}").status_code == 204
    assert not (carpeta / slug).exists()
    assert web.get("/api/kmz").json() == []
    assert web.get(f"/api/kmz/{slug}").status_code == 404


def test_el_nombre_es_unico_por_loteadora_y_el_slug_en_todo_el_sistema(consola):
    app, _, _, _ = consola
    ana, luis = entrar(app, "ana@losrobles.cl"), entrar(app, "luis@delvalle.cl")
    assert ana.post("/api/kmz", json={"nombre": "Lomas"}).status_code == 201

    repetido = ana.post("/api/kmz", json={"nombre": "Lomas"})
    assert repetido.status_code == 409 and "Lomas" in repetido.json()["detail"]
    # Otra loteadora puede llamarlo igual: su slug lleva sufijo.
    assert luis.post("/api/kmz", json={"nombre": "Lomas"}).json()["slug"] == "lomas-2"
    ana.post("/api/kmz", json={"nombre": "Otro"})
    assert ana.patch("/api/kmz/otro", json={"nombre": "Lomas"}).status_code == 409


@pytest.mark.parametrize("nombre", [None, "", "   "])
def test_sin_nombre_no_hay_kmz(consola, nombre):
    app, carpeta, _, _ = consola
    web = entrar(app, "ana@losrobles.cl")

    respuesta = web.post("/api/kmz", json={"nombre": nombre})

    assert respuesta.status_code == 400
    assert web.get("/api/kmz").json() == []
    assert web.patch("/api/kmz/x", json={"nombre": ""}).status_code == 404


def test_un_kmz_nuevo_no_hereda_una_carpeta_vieja(consola):
    """Si un borrado dejó archivos, el siguiente con ese slug no los muestra."""
    app, carpeta, _, _ = consola
    (carpeta / "lomas").mkdir(parents=True)
    (carpeta / "lomas" / "plano.pdf").write_bytes(b"%PDF-1.7 de otro")
    web = entrar(app, "ana@losrobles.cl")

    web.post("/api/kmz", json={"nombre": "Lomas"})

    assert list((carpeta / "lomas").iterdir()) == []
    assert web.get("/api/kmz/lomas").json()["paso"] == "subir"


# --- de punta a punta ------------------------------------------------------------------

def test_del_pdf_al_kmz_descargado_con_el_plano_sintetico(ana):
    web, slug, carpeta, comandos = ana
    plano = dibujar()
    alto, ancho = plano.imagen.shape[:2]
    assert subir(web, slug, pdf_del_plano(imagen=plano.imagen)).status_code == 201
    entradas = dict(pagina=1, rotacion=0, rectangulo=[100, 100, ancho - 20, alto - 5],
                    semillas=[dict(numero=n, x=x, y=y) for n, x, y in plano.semillas],
                    anclas=[ancla("a", 150, 150), ancla("b", ancho - 150, 150),
                            ancla("c", ancho - 150, alto - 150), ancla("d", 150, alto - 150)])
    assert web.put(f"/api/kmz/{slug}/entradas", json=entradas).status_code == 200
    assert web.get(f"/api/kmz/{slug}/paginas/1").headers["content-type"] == "image/jpeg"
    assert web.get(f"/api/kmz/{slug}/descargar").status_code == 409

    lanzado = web.post(f"/api/kmz/{slug}/digitalizar")
    assert lanzado.status_code == 202, lanzado.text
    trabajo = esperar_trabajo(web, lanzado.json()["id"])
    assert trabajo["estado"] == "listo" and trabajo["proyecto"] == f"kmz:{slug}"
    assert comandos.pedidos == [("digitalizar-kmz", slug, None)]
    assert web.get(f"/api/kmz/{slug}").json()["trabajo"]["id"] == lanzado.json()["id"]
    # El método de verdad, en el proceso (el guion de prueba solo imprime).
    digitalizar(carpeta / slug, avance=lambda _: None)

    assert web.post(f"/api/kmz/{slug}/georreferenciar").status_code == 200
    assert web.get(f"/api/kmz/{slug}/lotes", params={"en": "lonlat"}).status_code == 200
    creado = web.post(f"/api/kmz/{slug}/crear")

    assert creado.status_code == 201, creado.text
    total = len(plano.semillas)
    assert creado.json() == {"kmz": f"{slug}.kmz", "lotes": total}
    estado = web.get(f"/api/kmz/{slug}").json()
    assert estado["paso"] == "listo" and estado["kmz"] == [f"{slug}.kmz"]
    assert estado["nombre"] == "Los Robles" and estado["slug"] == slug
    tarjeta = web.get("/api/kmz").json()[0]
    assert tarjeta["terminado"] is True and tarjeta["paso"] == "listo" and tarjeta["lotes"] == total

    descarga = web.get(f"/api/kmz/{slug}/descargar")
    assert descarga.status_code == 200
    assert descarga.headers["content-type"] == "application/vnd.google-earth.kmz"
    assert descarga.headers["cache-control"].startswith("private")
    assert descarga.headers["content-disposition"] == (
        "attachment; filename=\"Los Robles.kmz\"; filename*=UTF-8''Los%20Robles.kmz")
    bajado = carpeta.parent / "bajado.kmz"
    bajado.write_bytes(descarga.content)
    assert sorted(p.id for p in leer_kmz(bajado)) == sorted(n for n, _, _ in plano.semillas)

    # Es su propio archivo: rehacerlo no pide confirmar ni deja anteriores.
    assert web.post(f"/api/kmz/{slug}/crear").status_code == 201
    assert sorted(p.name for p in (carpeta / slug).glob("*.kmz*")) == [f"{slug}.kmz"]


def test_el_nombre_con_tildes_va_en_filename_estrella(consola):
    app, carpeta, _, _ = consola
    web = entrar(app, "ana@losrobles.cl")
    slug = web.post("/api/kmz", json={"nombre": "Ñuble \"sur\""}).json()["slug"]
    listo_para_ubicar(web, slug, carpeta)
    web.post(f"/api/kmz/{slug}/georreferenciar")
    web.post(f"/api/kmz/{slug}/crear")

    disposicion = web.get(f"/api/kmz/{slug}/descargar").headers["content-disposition"]

    plano, estrella = disposicion.split("; filename*=UTF-8''")
    assert plano == 'attachment; filename="Nuble _sur_.kmz"'
    assert unquote(estrella) == "Ñuble \"sur\".kmz"


def test_numeros_que_chocan_no_dan_kmz(ana):
    web, slug, carpeta, _ = ana
    listo_para_ubicar(web, slug, carpeta)
    digitalizado_a_mano(carpeta / slug, [
        dict(numero="7", poligono=[[0, 0], [400, 0], [400, 300], [0, 300], [0, 0]], huecos=[]),
        dict(numero="07", poligono=[[400, 0], [800, 0], [800, 300], [400, 300], [400, 0]], huecos=[])])
    web.post(f"/api/kmz/{slug}/georreferenciar")

    assert web.post(f"/api/kmz/{slug}/crear").status_code == 400
    assert not list((carpeta / slug).glob("*.kmz"))


def test_crear_sin_ubicar_es_409(ana):
    web, slug, carpeta, _ = ana
    listo_para_ubicar(web, slug, carpeta)

    assert web.post(f"/api/kmz/{slug}/crear").status_code == 409


def test_el_plano_tiene_el_tope_de_disco(tmp_path):
    app, _, _, _ = montar(tmp_path, limites=Limites(megas_por_loteo=0))
    web = entrar(app, "ana@losrobles.cl")
    slug = web.post("/api/kmz", json={"nombre": "Chico"}).json()["slug"]

    respuesta = subir(web, slug)

    assert respuesta.status_code == 413
    assert not (tmp_path / "kmz" / slug / "plano.pdf").exists()


# --- trabajos ----------------------------------------------------------------------------

def test_mientras_digitaliza_no_se_toca_ni_se_borra(ana, monkeypatch):
    web, slug, carpeta, comandos = ana
    listo_para_ubicar(web, slug, carpeta)
    web.post(f"/api/kmz/{slug}/georreferenciar")
    lento(comandos, monkeypatch)
    identificador = web.post(f"/api/kmz/{slug}/digitalizar").json()["id"]
    assert web.get("/api/kmz").json()[0]["trabajo"]["id"] == identificador

    assert web.delete(f"/api/kmz/{slug}").status_code == 409
    assert web.post(f"/api/kmz/{slug}/crear").status_code == 409
    assert web.post(f"/api/kmz/{slug}/georreferenciar").status_code == 409
    assert subir(web, slug).status_code == 409
    assert web.post(f"/api/kmz/{slug}/digitalizar").status_code == 409
    assert (carpeta / slug / "plano.pdf").is_file()

    esperar_trabajo(web, identificador)
    assert web.delete(f"/api/kmz/{slug}").status_code == 204


def test_borrado_no_deja_su_avance_al_siguiente_con_ese_nombre(ana):
    web, slug, carpeta, _ = ana
    listo_para_ubicar(web, slug, carpeta)
    esperar_trabajo(web, web.post(f"/api/kmz/{slug}/digitalizar").json()["id"])
    web.delete(f"/api/kmz/{slug}")

    assert web.post("/api/kmz", json={"nombre": "Los Robles"}).json()["slug"] == slug
    assert web.get(f"/api/kmz/{slug}").json()["trabajo"] is None


@pytest.fixture
def con_topes(tmp_path):
    app, _, _, comandos = montar(tmp_path, limites=Limites(construcciones=1))
    return entrar(app, "ctp@ctp.cl"), entrar(app, "ana@losrobles.cl"), tmp_path / "kmz", comandos


def master_con_kmz(web, nombre):
    slug = web.post("/api/proyectos", json={"nombre": nombre}).json()["slug"]
    web.post(f"/api/proyectos/{slug}/archivos",
             files=[("archivos", ("loteo.kmz", b"kmz", "application/octet-stream"))])
    return slug


def test_una_digitalizacion_cuenta_como_la_construccion_de_la_loteadora(con_topes, monkeypatch):
    ctp, ana, carpeta, comandos = con_topes
    master = master_con_kmz(ana, "Uno")
    kmz = ana.post("/api/kmz", json={"nombre": "Uno"}).json()["slug"]
    listo_para_ubicar(ana, kmz, carpeta)
    lento(comandos, monkeypatch)
    identificador = ana.post(f"/api/kmz/{kmz}/digitalizar").json()["id"]

    respuesta = ana.post(f"/api/proyectos/{master}/construir", json={})

    assert respuesta.status_code == 429
    assert "KMZ" in respuesta.json()["detail"]
    # El equipo no tiene ese tope.
    otro = ctp.post("/api/kmz", json={"nombre": "Del equipo"}).json()["slug"]
    listo_para_ubicar(ctp, otro, carpeta)
    lanzado = ctp.post(f"/api/kmz/{otro}/digitalizar")
    assert lanzado.status_code == 202
    esperar_trabajo(ana, identificador)
    esperar_trabajo(ctp, lanzado.json()["id"])


def test_una_construccion_frena_la_digitalizacion(con_topes, monkeypatch):
    _, ana, carpeta, comandos = con_topes
    master = master_con_kmz(ana, "Uno")
    monkeypatch.setattr(comandos, "construir",
                        lambda p, sin_imagenes=False: [sys.executable, "-c", "import time; time.sleep(2)"])
    # Sin /bin/sh (Windows): la construcción sola, sin el control de calce encadenado.
    monkeypatch.setattr("consola.app.encadenar", lambda *comandos: comandos[0])
    identificador = ana.post(f"/api/proyectos/{master}/construir", json={}).json()["id"]
    kmz = ana.post("/api/kmz", json={"nombre": "Uno"}).json()["slug"]
    listo_para_ubicar(ana, kmz, carpeta)

    assert ana.post(f"/api/kmz/{kmz}/digitalizar").status_code == 429

    esperar_trabajo(ana, identificador)
    assert ana.post(f"/api/kmz/{kmz}/digitalizar").status_code == 202


# --- de otra loteadora ---------------------------------------------------------------------

@pytest.mark.parametrize("pedir", [
    lambda web, slug: web.get(f"/api/kmz/{slug}"),
    lambda web, slug: web.patch(f"/api/kmz/{slug}", json={"nombre": "Mío"}),
    lambda web, slug: web.delete(f"/api/kmz/{slug}"),
    lambda web, slug: subir(web, slug),
    lambda web, slug: web.get(f"/api/kmz/{slug}/paginas/1"),
    lambda web, slug: web.put(f"/api/kmz/{slug}/entradas", json=ENTRADAS),
    lambda web, slug: web.post(f"/api/kmz/{slug}/digitalizar"),
    lambda web, slug: web.post(f"/api/kmz/{slug}/georreferenciar"),
    lambda web, slug: web.get(f"/api/kmz/{slug}/lotes"),
    lambda web, slug: web.post(f"/api/kmz/{slug}/crear"),
    lambda web, slug: web.get(f"/api/kmz/{slug}/descargar"),
], ids=["ver", "renombrar", "borrar", "plano", "pagina", "entradas", "digitalizar",
        "georreferenciar", "lotes", "crear", "descargar"])
def test_el_kmz_de_otra_contesta_404_en_todas_las_rutas(consola, pedir):
    app, carpeta, _, comandos = consola
    ana, luis = entrar(app, "ana@losrobles.cl"), entrar(app, "luis@delvalle.cl")
    slug = ana.post("/api/kmz", json={"nombre": "De Ana"}).json()["slug"]
    listo_para_ubicar(ana, slug, carpeta)
    ana.post(f"/api/kmz/{slug}/georreferenciar")
    assert ana.post(f"/api/kmz/{slug}/crear").status_code == 201
    antes = {p.name: p.stat().st_mtime_ns for p in (carpeta / slug).iterdir()}

    assert pedir(luis, slug).status_code == 404

    assert comandos.pedidos == []
    assert {p.name: p.stat().st_mtime_ns for p in (carpeta / slug).iterdir()} == antes
    assert [k["nombre"] for k in ana.get("/api/kmz").json()] == ["De Ana"]
    assert luis.get("/api/kmz").json() == []


def test_el_equipo_ve_los_de_todas(consola):
    app, carpeta, _, _ = consola
    ctp, ana, luis = (entrar(app, e) for e in ("ctp@ctp.cl", "ana@losrobles.cl", "luis@delvalle.cl"))
    ana.post("/api/kmz", json={"nombre": "De Ana"})
    luis.post("/api/kmz", json={"nombre": "De Luis"})

    assert sorted(k["slug"] for k in ctp.get("/api/kmz").json()) == ["de-ana", "de-luis"]
    assert ctp.get("/api/kmz/de-ana").status_code == 200
    assert [k["slug"] for k in ana.get("/api/kmz").json()] == ["de-ana"]


def test_el_avance_de_una_digitalizacion_ajena_no_se_ve(consola):
    app, carpeta, _, _ = consola
    ctp, ana, luis = (entrar(app, e) for e in ("ctp@ctp.cl", "ana@losrobles.cl", "luis@delvalle.cl"))
    slug = ana.post("/api/kmz", json={"nombre": "De Ana"}).json()["slug"]
    listo_para_ubicar(ana, slug, carpeta)
    identificador = ana.post(f"/api/kmz/{slug}/digitalizar").json()["id"]
    esperar_trabajo(ana, identificador)

    assert luis.get(f"/api/trabajos/{identificador}").status_code == 404
    assert ctp.get(f"/api/trabajos/{identificador}").status_code == 200
    # Un master de Luis con el mismo slug no le abre la puerta.
    luis.post("/api/proyectos", json={"nombre": slug})
    assert luis.get(f"/api/trabajos/{identificador}").status_code == 404


# --- la base -----------------------------------------------------------------------------

def test_una_base_de_antes_de_mis_kmz_se_pone_al_dia_sola(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from consola.datos import Base
    url = f"sqlite:///{tmp_path / 'vieja.db'}"
    with create_engine(url).begin() as con:
        con.execute(text("CREATE TABLE clientes (id INTEGER PRIMARY KEY, slug VARCHAR(60) NOT NULL UNIQUE, "
                         "nombre VARCHAR(160) NOT NULL, estado VARCHAR(20) NOT NULL, "
                         "creado_en DATETIME NOT NULL)"))
        con.execute(text("INSERT INTO clientes (slug, nombre, estado, creado_en) "
                         "VALUES ('robles', 'Los Robles', 'activo', '2026-09-24 10:00:00')"))
    assert "kmzs" not in inspect(create_engine(url)).get_table_names()

    base = Base(url)
    Base(url)                                   # y abrirla de nuevo no hace nada

    guardado = base.crear_kmz(1, "Lomas")
    assert (guardado.slug, guardado.nombre, guardado.cliente_id) == ("lomas", "Lomas", 1)
    assert base.cliente(1).nombre == "Los Robles"
    assert [k.slug for k in base.kmzs(cliente_id=1)] == ["lomas"]
    assert base.kmzs(cliente_id=2) == []


def test_un_nombre_largo_da_un_slug_que_cabe(tmp_path):
    from consola.datos import Base
    base = Base(f"sqlite:///{tmp_path / 'c.db'}")
    cliente, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    uno = base.crear_kmz(cliente.id, "x" * 160)
    dos = base.crear_kmz(cliente.id, "x" * 159)
    vacio = base.crear_kmz(cliente.id, "¿?")

    assert len(uno.slug) == 60 and dos.slug == "x" * 60 + "-2"
    assert vacio.slug == "kmz"


def test_lo_que_lee_el_kmz_bajado_es_un_zip(ana):
    """Sanidad del archivo: un KMZ es un zip con doc.kml adentro."""
    import zipfile
    web, slug, carpeta, _ = ana
    listo_para_ubicar(web, slug, carpeta)
    web.post(f"/api/kmz/{slug}/georreferenciar")
    web.post(f"/api/kmz/{slug}/crear")

    contenido = web.get(f"/api/kmz/{slug}/descargar").content

    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        assert "doc.kml" in z.namelist()
        assert "Los Robles" in z.read("doc.kml").decode("utf-8")
    assert json.loads((carpeta / slug / "huellas.json").read_text(encoding="utf-8"))["kmz"]


def test_un_nombre_con_saltos_de_linea_no_inyecta_cabeceras(ana):
    web, slug, carpeta, _ = ana
    listo_para_ubicar(web, slug, carpeta)
    web.post(f"/api/kmz/{slug}/georreferenciar")
    web.post(f"/api/kmz/{slug}/crear")
    assert web.patch(f"/api/kmz/{slug}", json={"nombre": "a\r\nSet-Cookie: x=1; \"b"}).status_code == 200

    descarga = web.get(f"/api/kmz/{slug}/descargar")

    assert descarga.status_code == 200 and "set-cookie" not in descarga.headers
    disposicion = descarga.headers["content-disposition"]
    assert "\r" not in disposicion and "\n" not in disposicion
    assert disposicion.startswith('attachment; filename="a_Set-Cookie_ x_1_ _b.kmz"; ')


def test_otro_pdf_reinicia_los_pasos_pero_deja_el_kmz_hecho(ana):
    """`paso` es el del plano nuevo; el KMZ anterior se sigue pudiendo bajar."""
    web, slug, carpeta, _ = ana
    listo_para_ubicar(web, slug, carpeta)
    web.post(f"/api/kmz/{slug}/georreferenciar")
    assert web.post(f"/api/kmz/{slug}/crear").status_code == 201

    assert subir(web, slug).status_code == 201

    tarjeta = web.get("/api/kmz").json()[0]
    assert tarjeta["paso"] == "marcar" and tarjeta["terminado"] is True
    assert web.get(f"/api/kmz/{slug}").json()["kmz"] == [f"{slug}.kmz"]
    assert web.get(f"/api/kmz/{slug}/descargar").status_code == 200


@pytest.mark.parametrize("slug", ["", ".", "..", "a/b", "kmz:x", "../otro", "A"])
def test_la_carpeta_de_un_slug_raro_no_se_arma(tmp_path, slug):
    """Se vacía al crear y se borra entera: nunca `kmz/` misma ni algo fuera."""
    from consola.datos import Base
    from consola.kmzs import RegistroKmz
    registro = RegistroKmz(base=Base(f"sqlite:///{tmp_path / 'c.db'}"), carpeta=tmp_path / "kmz")

    with pytest.raises(ValueError):
        registro.carpeta_de(slug)


def test_un_master_adoptado_no_puede_llamarse_como_la_clave_de_un_kmz(tmp_path):
    from consola.datos import Base
    base = Base(f"sqlite:///{tmp_path / 'c.db'}")
    cliente, _ = base.crear_cliente("Los Robles", "ana@losrobles.cl", "Ana")

    with pytest.raises(ValueError):
        base.crear_proyecto(cliente.id, "Robado", slug="kmz:de-ana")
    assert base.crear_proyecto(cliente.id, "Bien", slug="bien").slug == "bien"
