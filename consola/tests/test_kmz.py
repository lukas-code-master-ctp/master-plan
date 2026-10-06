"""Mis KMZ: crear un KMZ desde el plano aprobado, sin master, y descargarlo."""
import io
import json
import sys
from urllib.parse import unquote

import numpy as np
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


# --- corregir a mano en Revisar ----------------------------------------------------------

# Tres lotes con la topología de la red de deslindes: cada vértice compartido está en
# todos los lotes que lo tocan. (400, 150) va sobre el lado común de 1 y 2; (400, 690),
# un diente solo de 3.
LOTES_RED = [
    dict(numero="1", poligono=[[0, 0], [400, 0], [400, 150], [400, 300], [0, 300], [0, 0]], huecos=[],
         area_px=120000, vertices=5),
    dict(numero="2", poligono=[[400, 0], [800, 0], [800, 300], [400, 300], [400, 150], [400, 0]], huecos=[],
         area_px=120000, vertices=5),
    dict(numero="3", poligono=[[0, 300], [400, 300], [800, 300], [800, 700], [400, 690], [0, 700], [0, 300]],
         huecos=[], area_px=316000, vertices=6),
]


def _ubicado(web, slug, carpeta):
    listo_para_ubicar(web, slug, carpeta)
    digitalizado_a_mano(carpeta / slug, json.loads(json.dumps(LOTES_RED)))
    assert web.post(f"/api/kmz/{slug}/georreferenciar").status_code == 200
    from pipeline.plano.georreferencia import Transformacion
    t = Transformacion.desde_dict(json.loads((carpeta / slug / "georreferencia.json").read_text()))
    return lambda x, y: [float(v) for v in t.a_lonlat(x, y)]


def _anillos(carpeta, slug):
    d = json.loads((carpeta / slug / "digitalizado.json").read_text())
    return {l["numero"]: [tuple(round(v, 1) for v in p) for p in l["poligono"]] for l in d["lotes"]}


def test_mover_un_vertice_compartido_lo_mueve_en_los_dos_lotes_y_se_puede_deshacer(ana):
    web, slug, carpeta, _ = ana
    ll = _ubicado(web, slug, carpeta)
    assert web.post(f"/api/kmz/{slug}/crear").status_code == 201
    antes = _anillos(carpeta, slug)

    r = web.post(f"/api/kmz/{slug}/corregir", json={"accion": "mover", "punto": ll(400, 300), "a": ll(420, 310)})

    assert r.status_code == 200, r.text
    assert r.json() == {"deshacer": 1}
    ahora = _anillos(carpeta, slug)
    for n in ("1", "2", "3"):
        assert (420.0, 310.0) in ahora[n] and (400.0, 300.0) not in ahora[n]
    d = json.loads((carpeta / slug / "digitalizado.json").read_text())
    assert d["lotes"][0]["area_px"] != 120000
    # El KMZ creado quedó atrasado, y la pantalla ve los lotes nuevos.
    assert web.get(f"/api/kmz/{slug}").json()["paso"] == "crear"
    rasgos = web.get(f"/api/kmz/{slug}/lotes", params={"en": "px"}).json()["features"]
    assert [420, 310] in rasgos[0]["geometry"]["coordinates"][0]
    geo = json.loads((carpeta / slug / "lotes.geojson").read_text())
    assert len(geo["features"]) == 3

    assert web.post(f"/api/kmz/{slug}/corregir", json={"accion": "deshacer"}).json() == {"deshacer": 0}
    assert _anillos(carpeta, slug) == antes
    assert web.post(f"/api/kmz/{slug}/corregir", json={"accion": "deshacer"}).status_code == 409


def test_borrar_un_vertice_sobre_el_lado_comun_o_un_diente(ana):
    web, slug, carpeta, _ = ana
    ll = _ubicado(web, slug, carpeta)

    assert web.post(f"/api/kmz/{slug}/corregir", json={"accion": "borrar", "punto": ll(400, 150)}).status_code == 200
    assert web.post(f"/api/kmz/{slug}/corregir", json={"accion": "borrar", "punto": ll(400, 690)}).status_code == 200

    ahora = _anillos(carpeta, slug)
    assert all((400.0, 150.0) not in a for a in ahora.values())
    assert ahora["3"] == [(0, 300), (400, 300), (800, 300), (800, 700), (0, 700), (0, 300)]
    assert web.post(f"/api/kmz/{slug}/corregir", json={"accion": "deshacer"}).json() == {"deshacer": 1}


@pytest.mark.parametrize("campos, texto", [
    # Una esquina donde llega una divisoria: cada lote la tiene entre otros vecinos.
    (lambda ll: {"accion": "borrar", "punto": ll(400, 300)}, "esquina"),
    (lambda ll: {"accion": "borrar", "punto": ll(800, 0)}, "tres vértices"),
    (lambda ll: {"accion": "mover", "punto": ll(600, 150), "a": ll(0, 0)}, "no hay un vértice"),
    (lambda ll: {"accion": "mover", "punto": ll(400, 150), "a": ll(900, 150)}, "se cruza"),
    (lambda ll: {"accion": "mover", "punto": ll(400, 150)}, "lon, lat"),
    (lambda ll: {"accion": "mover", "punto": "12", "a": ll(0, 0)}, "lon, lat"),
    (lambda ll: {"accion": "estirar"}, "mover, borrar o deshacer"),
])
def test_lo_que_no_se_puede_corregir_es_400_y_no_cambia_nada(ana, campos, texto):
    web, slug, carpeta, _ = ana
    ll = _ubicado(web, slug, carpeta)
    # El 2 con solo tres vértices propios no existe en la red: se arma uno para probarlo.
    if texto == "tres vértices":
        d = json.loads((carpeta / slug / "digitalizado.json").read_text())
        d["sin_numero"] = [dict(poligono=[[800, 0], [900, 0], [900, 100], [800, 0]], area_px=5000)]
        d["lotes"] = [l for l in d["lotes"] if l["numero"] != "2"]
        (carpeta / slug / "digitalizado.json").write_text(json.dumps(d))
    antes = (carpeta / slug / "digitalizado.json").read_text()

    r = web.post(f"/api/kmz/{slug}/corregir", json=campos(ll))

    assert r.status_code == 400 and texto in r.json()["detail"], r.text
    assert (carpeta / slug / "digitalizado.json").read_text() == antes
    assert not (carpeta / slug / "ediciones.json").exists()


def test_corregir_sin_ubicar_es_409_y_digitalizar_de_nuevo_olvida_las_correcciones(ana):
    web, slug, carpeta, _ = ana
    listo_para_ubicar(web, slug, carpeta)
    assert web.post(f"/api/kmz/{slug}/corregir", json={"accion": "deshacer"}).status_code == 409

    ll = _ubicado(web, slug, carpeta)
    web.post(f"/api/kmz/{slug}/corregir", json={"accion": "borrar", "punto": ll(400, 690)})
    assert (carpeta / slug / "ediciones.json").exists()
    from consola.plano import Plano
    Plano(carpeta / slug, carpeta / slug / f"{slug}.kmz").anotar("digitalizado", "otra")
    assert not (carpeta / slug / "ediciones.json").exists()


def test_mover_un_vertice_de_un_hueco_pone_al_dia_al_lote_que_lo_tiene():
    from consola.plano import PlanoInvalido, _mover_vertice
    afuera = dict(poligono=[[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]],
                  huecos=[[[40, 40], [60, 40], [60, 60], [40, 60], [40, 40]]], area_px=9600, vertices=4)
    adentro = dict(poligono=[[40, 40], [60, 40], [60, 60], [40, 60], [40, 40]], huecos=[], area_px=400, vertices=4)
    d = dict(lotes=[afuera, adentro], sin_numero=[])

    _mover_vertice(d, np.array([60.0, 60.0]), np.array([70.0, 70.0]))

    assert afuera["huecos"][0][2] == [70, 70] and adentro["poligono"][2] == [70, 70]
    assert afuera["area_px"] + adentro["area_px"] == 10000
    # Fuera del lote de afuera, el hueco se sale: no se acepta.
    with pytest.raises(PlanoInvalido):
        _mover_vertice(d, np.array([70.0, 70.0]), np.array([120.0, 70.0]))


def test_mover_no_deja_un_lote_encima_de_otro_que_no_comparte_el_vertice():
    from consola.plano import PlanoInvalido, _mover_vertice
    # Dos lotes con un camino entre medio (el camino no es cara).
    uno = dict(poligono=[[0, 0], [400, 0], [400, 300], [0, 300], [0, 0]], huecos=[], area_px=120000)
    dos = dict(poligono=[[0, 350], [400, 350], [400, 650], [0, 650], [0, 350]], huecos=[], area_px=120000)
    d = dict(lotes=[uno, dos], sin_numero=[])
    antes = json.dumps(d)

    with pytest.raises(PlanoInvalido, match="se monta"):
        _mover_vertice(d, np.array([400.0, 300.0]), np.array([400.0, 500.0]))
    # Hasta el borde del camino sí.
    d = json.loads(antes)
    _mover_vertice(d, np.array([400.0, 300.0]), np.array([400.0, 350.0]))


def test_soltar_un_vertice_sobre_su_vecino_no_deja_un_punto_doble():
    from consola.plano import _borrar_vertice, _mover_vertice
    lote = dict(poligono=[[0, 0], [100, 0], [100, 50], [100, 100], [0, 100], [0, 0]], huecos=[],
                area_px=10000, vertices=5)
    d = dict(lotes=[lote], sin_numero=[])

    _mover_vertice(d, np.array([100.0, 50.0]), np.array([100.0, 100.0]))

    assert lote["poligono"] == [[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]]
    assert lote["vertices"] == 4
    # Y lo que queda se sigue pudiendo corregir.
    _borrar_vertice(d, np.array([100.0, 0.0]))
    assert lote["poligono"] == [[0, 0], [100, 100], [0, 100], [0, 0]]


def test_corregir_deja_el_kmz_atrasado_aunque_la_georreferencia_no_tenga_huella(ana):
    web, slug, carpeta, _ = ana
    ll = _ubicado(web, slug, carpeta)
    assert web.post(f"/api/kmz/{slug}/crear").status_code == 201
    huellas = json.loads((carpeta / slug / "huellas.json").read_text())
    huellas.pop("georreferencia", None)
    huellas.pop("kmz", None)
    (carpeta / slug / "huellas.json").write_text(json.dumps(huellas))
    assert web.get(f"/api/kmz/{slug}").json()["paso"] != "crear"

    assert web.post(f"/api/kmz/{slug}/corregir", json={"accion": "borrar", "punto": ll(400, 690)}).status_code == 200

    estado = web.get(f"/api/kmz/{slug}").json()
    assert estado["paso"] == "crear"
    assert estado["digitalizado"]["correcciones"] == 1


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
    lambda web, slug: web.post(f"/api/kmz/{slug}/corregir", json={"accion": "deshacer"}),
    lambda web, slug: web.post(f"/api/kmz/{slug}/crear"),
    lambda web, slug: web.get(f"/api/kmz/{slug}/descargar"),
], ids=["ver", "renombrar", "borrar", "plano", "pagina", "entradas", "digitalizar",
        "georreferenciar", "lotes", "corregir", "crear", "descargar"])
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


# --- usar un KMZ en un master ------------------------------------------------------------
#
# "Solo KMZ propios": los que alcanza la `VistaKmz` de quien pide. Para una loteadora,
# los suyos; para el equipo, todos (los ve todos, igual que los masters).

def kmz_terminado(web, carpeta, nombre="Mi KMZ"):
    slug = web.post("/api/kmz", json={"nombre": nombre}).json()["slug"]
    listo_para_ubicar(web, slug, carpeta)
    assert web.post(f"/api/kmz/{slug}/georreferenciar").status_code == 200
    assert web.post(f"/api/kmz/{slug}/crear").status_code == 201
    return slug


def master_vacio(web, nombre="Los Robles"):
    respuesta = web.post("/api/proyectos", json={"nombre": nombre})
    assert respuesta.status_code == 201, respuesta.text
    return respuesta.json()["slug"]


def usar(web, master, kmz, confirmar=False):
    return web.post(f"/api/proyectos/{master}/kmz", json={"kmz": kmz, "confirmar_reemplazo": confirmar})


def test_usar_un_kmz_propio_lo_copia_a_las_fuentes_del_master(consola):
    app, carpeta, registro, _ = consola
    ana = entrar(app, "ana@losrobles.cl")
    kmz = kmz_terminado(ana, carpeta)
    master = master_vacio(ana)
    respuesta = ana.post(f"/api/proyectos/{master}/construir", json={})
    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "falta el KMZ: súbelo o elige uno de Mis KMZ"

    respuesta = usar(ana, master, kmz)

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json() == {"kmz": "subdivision.kmz", "origen": kmz, "lotes": 3, "anteriores": []}
    fuentes = registro.subidas / master
    copiado = fuentes / "subdivision.kmz"
    assert copiado.read_bytes() == (carpeta / kmz / f"{kmz}.kmz").read_bytes()
    assert sorted(p.id for p in leer_kmz(copiado)) == ["1", "2", "A3"]
    assert not [p.name for p in fuentes.iterdir() if p.name.startswith(".")]      # sin temporales
    del_master = ana.get("/api/proyectos").json()[0]
    assert del_master["fuentes_encontradas"]["kmz"] == "subdivision.kmz"
    assert "plano" not in del_master
    assert ana.post(f"/api/proyectos/{master}/construir", json={}).status_code == 202


def test_un_kmz_que_ya_estaba_pide_confirmar_y_queda_como_anterior(consola):
    app, carpeta, registro, _ = consola
    ana = entrar(app, "ana@losrobles.cl")
    kmz = kmz_terminado(ana, carpeta)
    master = master_vacio(ana)
    ana.post(f"/api/proyectos/{master}/archivos",
             files=[("archivos", ("vuelo/Loteo Final.kmz", b"el del topografo", "application/octet-stream"))])
    fuentes = registro.subidas / master

    sin_confirmar = usar(ana, master, kmz)

    assert sin_confirmar.status_code == 409
    assert sin_confirmar.json()["existentes"] == ["vuelo/Loteo Final.kmz"]
    assert "vuelo/Loteo Final.kmz" in sin_confirmar.json()["detail"]
    assert not (fuentes / "subdivision.kmz").exists()

    confirmado = usar(ana, master, kmz, confirmar=True)

    assert confirmado.status_code == 201, confirmado.text
    assert confirmado.json()["anteriores"] == ["vuelo/Loteo Final.kmz.anterior"]
    assert (fuentes / "vuelo" / "Loteo Final.kmz.anterior").read_bytes() == b"el del topografo"
    assert not (fuentes / "vuelo" / "Loteo Final.kmz").exists()
    # Construir encuentra uno solo: el nuevo.
    assert ana.get("/api/proyectos").json()[0]["fuentes_encontradas"]["kmz"] == "subdivision.kmz"

    # Volver a usarlo también pide confirmar: el que hay ahora es el de Mis KMZ.
    assert usar(ana, master, kmz).status_code == 409
    otra = usar(ana, master, kmz, confirmar=True)
    assert otra.json()["anteriores"] == ["subdivision.kmz.anterior"]
    assert (fuentes / "subdivision.kmz").is_file() and (fuentes / "subdivision.kmz.anterior").is_file()


def test_un_kmz_sin_terminar_no_se_usa(consola):
    app, carpeta, registro, _ = consola
    ana = entrar(app, "ana@losrobles.cl")
    kmz = ana.post("/api/kmz", json={"nombre": "A medias"}).json()["slug"]
    listo_para_ubicar(ana, kmz, carpeta)
    master = master_vacio(ana)

    respuesta = usar(ana, master, kmz, confirmar=True)

    assert respuesta.status_code == 409
    assert respuesta.json()["detail"] == "ese KMZ todavía no está creado"
    assert not list((registro.subidas / master).glob("*.kmz*"))


@pytest.mark.parametrize("kmz", [None, "", "no-existe", "../kmz"])
def test_un_kmz_que_no_existe_da_404(consola, kmz):
    app, _, _, _ = consola
    ana = entrar(app, "ana@losrobles.cl")
    master = master_vacio(ana)

    assert usar(ana, master, kmz).status_code == 404


def test_el_kmz_de_otra_no_se_usa_ni_sabiendo_su_slug(consola):
    app, carpeta, registro, _ = consola
    ana, luis = entrar(app, "ana@losrobles.cl"), entrar(app, "luis@delvalle.cl")
    de_luis = kmz_terminado(luis, carpeta, "De Luis")
    master = master_vacio(ana)

    respuesta = usar(ana, master, de_luis, confirmar=True)

    assert respuesta.status_code == 404
    assert not list((registro.subidas / master).glob("*.kmz*"))


def test_en_el_master_de_otra_da_404(consola):
    app, carpeta, registro, _ = consola
    ana, luis = entrar(app, "ana@losrobles.cl"), entrar(app, "luis@delvalle.cl")
    master = master_vacio(ana)
    de_luis = kmz_terminado(luis, carpeta, "De Luis")

    assert usar(luis, master, de_luis, confirmar=True).status_code == 404
    assert not list((registro.subidas / master).glob("*.kmz*"))


def test_el_equipo_usa_el_kmz_de_cualquiera(consola):
    app, carpeta, _, _ = consola
    ctp, ana = entrar(app, "ctp@ctp.cl"), entrar(app, "ana@losrobles.cl")
    de_ana = kmz_terminado(ana, carpeta, "De Ana")
    master = master_vacio(ctp, "Del equipo")

    respuesta = usar(ctp, master, de_ana)

    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["origen"] == de_ana


def test_no_se_cambia_el_kmz_mientras_construye(consola, monkeypatch):
    app, carpeta, registro, comandos = consola
    ana = entrar(app, "ana@losrobles.cl")
    kmz = kmz_terminado(ana, carpeta)
    master = master_con_kmz(ana, "Uno")
    monkeypatch.setattr(comandos, "construir",
                        lambda p, sin_imagenes=False: [sys.executable, "-c", "import time; time.sleep(2)"])
    # Sin /bin/sh (Windows): la construcción sola, sin el control de calce encadenado.
    monkeypatch.setattr("consola.app.encadenar", lambda *comandos: comandos[0])
    identificador = ana.post(f"/api/proyectos/{master}/construir", json={}).json()["id"]

    respuesta = usar(ana, master, kmz, confirmar=True)

    assert respuesta.status_code == 409
    assert (registro.subidas / master / "loteo.kmz").read_bytes() == b"kmz"
    esperar_trabajo(ana, identificador)
    assert usar(ana, master, kmz, confirmar=True).status_code == 201


def test_usar_un_kmz_cuenta_para_el_tope_del_master(tmp_path):
    app, _, registro, _ = montar(tmp_path, limites=Limites(megas_por_loteo=1))
    ana = entrar(app, "ana@losrobles.cl")
    kmz = kmz_terminado(ana, tmp_path / "kmz")
    master = master_vacio(ana)
    (registro.subidas / master).mkdir(parents=True, exist_ok=True)
    (registro.subidas / master / "relleno.bin").write_bytes(b"x" * 1024 * 1024)

    respuesta = usar(ana, master, kmz)

    assert respuesta.status_code == 413
    assert not (registro.subidas / master / "subdivision.kmz").exists()


def test_una_carpeta_plano_vieja_no_libra_de_subir_el_kmz(consola):
    """Subir el vuelo vuelve a exigir el KMZ, aunque haya un plano de Crea tu KMZ."""
    app, _, registro, _ = consola
    ana = entrar(app, "ana@losrobles.cl")
    master = master_vacio(ana)
    (registro.subidas / master / "plano").mkdir(parents=True)
    (registro.subidas / master / "plano" / "plano.pdf").write_bytes(b"%PDF-1.7")

    respuesta = ana.post(f"/api/proyectos/{master}/archivos",
                         files=[("archivos", ("POSICION 01/a.JPG", b"jpg", "image/jpeg"))])

    assert respuesta.status_code == 400
    assert "KMZ" in respuesta.json()["detail"]


def test_poner_kmz_deja_uno_solo_aunque_el_viejo_este_en_una_subcarpeta(tmp_path):
    from consola.proyectos import poner_kmz
    from pipeline import config
    fuentes = tmp_path / "subidas" / "los-robles"
    (fuentes / "topografia").mkdir(parents=True)
    (fuentes / "topografia" / "a.kmz").write_bytes(b"viejo")
    (fuentes / "topografia" / "a.kmz.anterior").write_bytes(b"mas viejo")

    apartados = poner_kmz(fuentes, b"nuevo", confirmar_reemplazo=True)

    assert apartados == ["topografia/a.kmz.anterior"]
    assert config.kmz_en(fuentes) == [fuentes / "subdivision.kmz"]
    assert (fuentes / "subdivision.kmz").read_bytes() == b"nuevo"
    # Se guarda solo el último reemplazado.
    assert (fuentes / "topografia" / "a.kmz.anterior").read_bytes() == b"viejo"
    assert [p.name for p in fuentes.iterdir() if p.name.startswith(".")] == []


def test_poner_kmz_si_falla_al_final_devuelve_los_apartados(tmp_path, monkeypatch):
    import os

    from consola import proyectos
    fuentes = tmp_path / "los-robles"
    fuentes.mkdir()
    (fuentes / "subdivision.kmz").write_bytes(b"viejo")
    (fuentes / "b.kmz").write_bytes(b"otro")
    original = os.replace

    def falla_al_poner(origen, destino):
        if str(origen).endswith(f"{os.getpid()}.{proyectos.threading.get_ident()}"):
            raise OSError("disco lleno")
        original(origen, destino)

    monkeypatch.setattr(proyectos.os, "replace", falla_al_poner)

    with pytest.raises(OSError):
        proyectos.poner_kmz(fuentes, b"nuevo", confirmar_reemplazo=True)

    assert (fuentes / "subdivision.kmz").read_bytes() == b"viejo"
    assert (fuentes / "b.kmz").read_bytes() == b"otro"
    assert sorted(p.name for p in fuentes.iterdir()) == ["b.kmz", "subdivision.kmz"]
