"""La vista previa: el sitio construido, servido por la consola antes de publicar."""
import json

import pytest

from .test_app import entrar, montar

SITIO = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
</head>
<body data-plano="cerrado">
<script type="module" src="js/app.js"></script>
</body>
</html>
"""


@pytest.fixture
def ana_construida(tmp_path):
    """Ana con un loteo propio, sin pagar, construido (con un sitio de mentira), y Luis."""
    app, _, registro, _ = montar(tmp_path)
    ana, luis = entrar(app, "ana@losrobles.cl"), entrar(app, "luis@delvalle.cl")
    slug = ana.post("/api/proyectos", json={"nombre": "Praderas"}).json()["slug"]
    sitio = registro.salidas / slug / "sitio"
    (sitio / "datos").mkdir(parents=True)
    (sitio / "js").mkdir()
    (sitio / "index.html").write_text(SITIO, encoding="utf-8")
    (sitio / "js" / "app.js").write_text("export {};", encoding="utf-8")
    (sitio / "vercel.json").write_text("{}", encoding="utf-8")
    (sitio / "datos" / "diseno.json").write_text("null", encoding="utf-8")
    (sitio / "datos" / "parcelas.json").write_text(json.dumps({
        "proyecto": "Nombre viejo", "parcelas": [{"id": "1"}],
        "resumen": {"total": 1, "por_estado": {"disponible": 1}},
        # Lo que dejó una publicación anterior: con esto el visor ofrecería reservar.
        "link_reserva": "https://pago.cl/x", "consola": "https://consola.cl", "loteo": slug,
    }), encoding="utf-8")
    (sitio / "datos" / "vistas.json").write_text('{"vistas": []}', encoding="utf-8")
    (registro.salidas / slug / "secreto.txt").write_text("fuera del sitio", encoding="utf-8")
    return ana, luis, slug


def test_sirve_el_sitio_con_la_marca_y_sin_indexar(ana_construida):
    ana, _, slug = ana_construida

    respuesta = ana.get(f"/vista-previa/{slug}/")

    assert respuesta.status_code == 200
    assert 'class="vista-previa-consola"' in respuesta.text
    assert '<meta name="robots" content="noindex, nofollow">' in respuesta.text
    assert respuesta.headers["x-robots-tag"] == "noindex, nofollow"
    assert "script-src 'self'" in respuesta.headers["content-security-policy"]
    assert ana.get(f"/vista-previa/{slug}/js/app.js").headers["content-type"].startswith("text/javascript")


def test_sin_la_barra_final_lleva_a_la_carpeta(ana_construida):
    ana, _, slug = ana_construida

    respuesta = ana.get(f"/vista-previa/{slug}")

    assert respuesta.status_code == 307
    assert respuesta.headers["location"] == f"/vista-previa/{slug}/"


def test_las_parcelas_traen_los_datos_de_hoy_y_no_dejan_reservar(ana_construida):
    ana, _, slug = ana_construida
    ana.patch(f"/api/proyectos/{slug}", json={
        "nombre": "Praderas del Sur", "whatsapp": "+56 9 1234 5678",
        "link_reserva": "https://pago.cl/nuevo", "monto_reserva": "250000"})

    for ruta in ("datos/parcelas.json", "./datos//parcelas.json"):
        datos = ana.get(f"/vista-previa/{slug}/{ruta}").json()
        assert datos["proyecto"] == "Praderas del Sur"
        assert datos["whatsapp"]
        assert datos["parcelas"] == [{"id": "1"}]
        for campo in ("link_reserva", "monto_reserva", "consola", "loteo"):
            assert campo not in datos


def test_no_cambia_el_sitio_construido(ana_construida, tmp_path):
    ana, _, slug = ana_construida
    archivo = tmp_path / "salidas" / slug / "sitio" / "datos" / "parcelas.json"
    antes = archivo.read_text(encoding="utf-8")

    ana.get(f"/vista-previa/{slug}/datos/parcelas.json")
    ana.get(f"/vista-previa/{slug}/datos/diseno.json")

    assert archivo.read_text(encoding="utf-8") == antes


def test_el_diseno_es_el_que_tiene_elegido_hoy(ana_construida):
    ana, _, slug = ana_construida
    diseno = ana.post("/api/disenos", json={"nombre": "Robles", "color": "#225533"}).json()
    ana.patch(f"/api/proyectos/{slug}", json={"diseno_id": diseno["id"]})

    assert ana.get(f"/vista-previa/{slug}/datos/diseno.json").json()["color"] == "#225533"


def test_no_sale_de_la_carpeta_del_sitio(ana_construida):
    ana, _, slug = ana_construida

    for ruta in ("..%2Fsecreto.txt", "../secreto.txt", "vercel.json", "datos/logo.png", "no-existe.js"):
        assert ana.get(f"/vista-previa/{slug}/{ruta}").status_code == 404, ruta


def test_la_vista_previa_de_otra_es_404(ana_construida):
    _, luis, slug = ana_construida

    assert luis.get(f"/vista-previa/{slug}").status_code == 404
    assert luis.get(f"/vista-previa/{slug}/").status_code == 404
    assert luis.get(f"/vista-previa/{slug}/datos/parcelas.json").status_code == 404


def test_sin_sesion_manda_a_entrar(tmp_path, ana_construida):
    from fastapi.testclient import TestClient
    ana, _, slug = ana_construida

    anonimo = TestClient(ana.app, follow_redirects=False)

    assert anonimo.get(f"/vista-previa/{slug}/").headers["location"] == "/entrar"


def test_sin_construir_no_hay_vista_previa(tmp_path):
    app, _, _, _ = montar(tmp_path)
    ana = entrar(app, "ana@losrobles.cl")
    slug = ana.post("/api/proyectos", json={"nombre": "Vacío"}).json()["slug"]

    assert ana.get(f"/vista-previa/{slug}/").status_code == 404
