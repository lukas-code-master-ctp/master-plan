import json

import pytest

from pipeline import config, visor


@pytest.fixture
def plantilla(tmp_path, monkeypatch):
    """Un visor mínimo, con lo que hay que copiar y lo que no."""
    raiz = tmp_path / "web"
    (raiz / "js").mkdir(parents=True)
    (raiz / "index.html").write_text("<html></html>", encoding="utf-8")
    (raiz / "js" / "visor.js").write_text("export const a = 1;", encoding="utf-8")
    (raiz / "datos").mkdir()
    (raiz / "datos" / "parcelas.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(config, "PLANTILLA_WEB", raiz)
    return raiz


# --- huella ------------------------------------------------------------------

def test_la_huella_cambia_al_cambiar_un_archivo(plantilla):
    antes = visor.huella(plantilla)
    (plantilla / "js" / "visor.js").write_text("export const a = 2;", encoding="utf-8")

    assert visor.huella(plantilla) != antes


def test_la_huella_cambia_al_agregar_un_archivo(plantilla):
    antes = visor.huella(plantilla)
    (plantilla / "css").mkdir()
    (plantilla / "css" / "estilo.css").write_text("", encoding="utf-8")

    assert visor.huella(plantilla) != antes


def test_la_huella_cambia_al_mover_un_archivo(plantilla):
    """Mismo contenido en otra ruta es otro visor."""
    antes = visor.huella(plantilla)
    (plantilla / "js" / "visor.js").rename(plantilla / "js" / "otro.js")

    assert visor.huella(plantilla) != antes


def test_la_huella_no_mira_lo_que_no_se_copia(plantilla):
    antes = visor.huella(plantilla)
    (plantilla / "js" / "visor.test.js").write_text("test()", encoding="utf-8")
    (plantilla / ".DS_Store").write_bytes(b"\0")
    (plantilla / "js" / ".DS_Store").write_bytes(b"\0")
    (plantilla / "datos" / "parcelas.json").write_text("[1]", encoding="utf-8")
    (plantilla / "datos" / "vistas").mkdir()
    (plantilla / "datos" / "vistas" / "v1.json").write_text("{}", encoding="utf-8")
    (plantilla / "panoramas" / "v1").mkdir(parents=True)
    (plantilla / "panoramas" / "v1" / "0.jpg").write_bytes(b"jpg")

    assert visor.huella(plantilla) == antes


def test_la_huella_es_estable(plantilla):
    huella = visor.huella(plantilla)

    assert huella == visor.huella(plantilla)
    assert len(huella) == 64


def test_el_limite_entre_ruta_y_contenido_no_se_confunde(tmp_path):
    uno, otro = tmp_path / "uno", tmp_path / "otro"
    uno.mkdir(), otro.mkdir()
    (uno / "a").write_text("bc", encoding="utf-8")
    (otro / "ab").write_text("c", encoding="utf-8")

    assert visor.huella(uno) != visor.huella(otro)


def test_la_huella_del_visor_real_calza_con_lo_copiado(tmp_path):
    """Lo que copytree deja en el sitio tiene la misma huella que la plantilla."""
    visor.copiar(tmp_path / "sitio")

    assert visor.huella(tmp_path / "sitio") == visor.huella()


# --- copiar ------------------------------------------------------------------

def test_copiar_deja_el_visor_sin_lo_ignorado(plantilla, tmp_path):
    (plantilla / "js" / "visor.test.js").write_text("test()", encoding="utf-8")
    sitio = tmp_path / "sitio"

    visor.copiar(sitio)

    assert (sitio / "index.html").is_file()
    assert (sitio / "js" / "visor.js").is_file()
    assert not (sitio / "js" / "visor.test.js").exists()
    assert not (sitio / "datos").exists()


def test_copiar_no_toca_los_datos_del_sitio(plantilla, tmp_path):
    sitio = tmp_path / "sitio"
    (sitio / "datos" / "vistas").mkdir(parents=True)
    (sitio / "datos" / "parcelas.json").write_text('[{"id": "A1"}]', encoding="utf-8")
    (sitio / "datos" / "vistas" / "v1.json").write_text("{}", encoding="utf-8")
    (sitio / "js").mkdir()
    (sitio / "js" / "visor.js").write_text("viejo", encoding="utf-8")

    visor.copiar(sitio)

    assert (sitio / "datos" / "parcelas.json").read_text(encoding="utf-8") == '[{"id": "A1"}]'
    assert (sitio / "datos" / "vistas" / "v1.json").is_file()
    assert (sitio / "js" / "visor.js").read_text(encoding="utf-8") == "export const a = 1;"


# --- línea de comandos -------------------------------------------------------

def test_el_cli_se_niega_con_un_sitio_sin_construir(plantilla, tmp_path, capsys):
    sitio = tmp_path / "sitio"
    sitio.mkdir()

    assert visor.main(["--sitio", str(sitio)]) != 0
    assert "datos/parcelas.json" in capsys.readouterr().err
    assert not (sitio / "index.html").exists()


def test_el_cli_copia_sobre_un_sitio_construido(plantilla, tmp_path, capsys):
    sitio = tmp_path / "sitio"
    (sitio / "datos").mkdir(parents=True)
    (sitio / "datos" / "parcelas.json").write_text("[]", encoding="utf-8")

    assert visor.main(["--sitio", str(sitio)]) == 0
    assert (sitio / "index.html").is_file()
    assert visor.huella(plantilla) in capsys.readouterr().out


def test_copiar_funciona_donde_no_se_pueden_cambiar_permisos(plantilla, tmp_path, monkeypatch):
    """En Cloud Run el sitio vive en un bucket montado (gcsfuse): cambiar permisos o
    fechas da "Operation not permitted", y copytree lo hace siempre."""
    import os
    import shutil

    def prohibido(*_argumentos, **_nombrados):
        raise PermissionError(1, "Operation not permitted")

    for modulo, nombre in ((os, "chmod"), (os, "utime"), (shutil, "copystat"), (shutil, "copymode")):
        monkeypatch.setattr(modulo, nombre, prohibido)
    sitio = tmp_path / "sitio"

    visor.copiar(sitio)
    visor.copiar(sitio)   # y encima de un sitio que ya lo tiene, como al republicar

    assert (sitio / "js" / "visor.js").read_text(encoding="utf-8") == "export const a = 1;"


# --- conexión con la consola -------------------------------------------------

POLITICA = "default-src 'self'; connect-src 'self'; worker-src 'self' blob:"


def _con_politica(raiz):
    (raiz / "vercel.json").write_text(json.dumps({"headers": [{"source": "/(.*)", "headers": [
        {"key": "Content-Security-Policy", "value": POLITICA}]}]}), encoding="utf-8")


def _politica(sitio):
    return json.loads((sitio / "vercel.json").read_text())["headers"][0]["headers"][0]["value"]


def test_copiar_el_visor_no_le_quita_al_sitio_la_conexion_con_su_consola(plantilla, tmp_path):
    """Publicar anota la consola y después copia el visor encima: la copia trae el
    vercel.json de la plantilla, que solo deja conectar con el propio sitio. Sin
    volver a abrirla, el formulario de reserva no llegaba nunca a la consola."""
    _con_politica(plantilla)
    sitio = tmp_path / "sitio"
    (sitio / "datos").mkdir(parents=True)
    (sitio / "datos" / "parcelas.json").write_text(
        json.dumps({"parcelas": [], "consola": "https://consola.tumasterplan.cl/"}), encoding="utf-8")

    visor.copiar(sitio)
    visor.copiar(sitio)

    assert _politica(sitio) == ("default-src 'self'; connect-src 'self' https://consola.tumasterplan.cl; "
                                "worker-src 'self' blob:")


def test_un_sitio_sin_consola_solo_se_conecta_consigo_mismo(plantilla, tmp_path):
    _con_politica(plantilla)
    sitio = tmp_path / "sitio"
    (sitio / "datos").mkdir(parents=True)
    (sitio / "datos" / "parcelas.json").write_text(json.dumps({"parcelas": [], "consola": ""}),
                                                   encoding="utf-8")

    visor.copiar(sitio)

    assert _politica(sitio) == POLITICA
