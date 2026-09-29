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
