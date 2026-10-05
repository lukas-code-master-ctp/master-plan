"""El lector del buzón de QA contra los correos que escribe la consola de verdad."""
import json

import pytest

from consola.cuentas import CorreoEnCarpeta
from qa import correos


@pytest.fixture
def buzon(tmp_path, monkeypatch):
    carpeta = tmp_path / "buzon"
    monkeypatch.setenv("QA_BUZON", str(carpeta))
    return carpeta


def test_sin_correos_avisa_y_sale_bien(buzon, capsys):
    assert correos.main([]) == 0
    assert "No hay correos" in capsys.readouterr().out


def test_ultimo_sin_correos_sale_con_error(buzon, capsys):
    assert correos.main(["--ultimo"]) == 1
    assert capsys.readouterr().out == ""


def test_lista_del_mas_nuevo_al_mas_viejo(buzon, capsys):
    carpeta = CorreoEnCarpeta(buzon)
    carpeta.enviar("ana@qa.test", "Confirma tu correo", "Entra a http://127.0.0.1:8780/confirmar?t=1.")
    carpeta.enviar("beto@qa.test", "Cambia tu clave", "Aquí: http://127.0.0.1:8780/clave?t=2")
    assert correos.main([]) == 0
    salida = capsys.readouterr().out
    assert salida.index("beto@qa.test") < salida.index("ana@qa.test")
    # El punto que cierra la frase no es parte del enlace.
    assert "→ http://127.0.0.1:8780/confirmar?t=1\n" in salida + "\n"
    assert "Cambia tu clave" in salida


def test_ultimo_imprime_solo_el_enlace_del_mas_nuevo(buzon, capsys):
    carpeta = CorreoEnCarpeta(buzon)
    carpeta.enviar("ana@qa.test", "Uno", "http://a.test/viejo")
    carpeta.enviar("ana@qa.test", "Dos", "http://a.test/nuevo y http://a.test/otro")
    assert correos.main(["--ultimo"]) == 0
    assert capsys.readouterr().out == "http://a.test/nuevo\n"


def test_para_filtra_por_destinatario(buzon, capsys):
    carpeta = CorreoEnCarpeta(buzon)
    carpeta.enviar("ana@qa.test", "Para Ana", "http://a.test/ana")
    carpeta.enviar("beto@qa.test", "Para Beto", "http://a.test/beto")
    assert correos.main(["--para", "ANA@qa.test", "--ultimo"]) == 0
    assert capsys.readouterr().out == "http://a.test/ana\n"
    assert correos.main(["--para", "nadie@qa.test"]) == 0
    assert "No hay correos para nadie@qa.test" in capsys.readouterr().out


def test_ignora_temporales_y_json_rotos(buzon, capsys):
    buzon.mkdir()
    (buzon / ".00000000000000000009-abc.json.tmp").write_text("{", encoding="utf-8")
    (buzon / "00000000000000000008-rot.json").write_text("{roto", encoding="utf-8")
    (buzon / "00000000000000000007-lis.json").write_text("[1]", encoding="utf-8")
    (buzon / "00000000000000000001-bue.json").write_text(json.dumps({
        "para": "ana@qa.test", "asunto": "Hola", "texto": "x",
        "enlaces": ["http://a.test/bueno"], "enviado_en": "2026-10-05T12:00:00+00:00",
    }), encoding="utf-8")
    assert correos.main(["--ultimo"]) == 0
    captura = capsys.readouterr()
    assert captura.out == "http://a.test/bueno\n"
    assert "rot.json" in captura.err
    assert "lis.json" in captura.err


def test_ultimo_sin_enlaces_sale_con_error(buzon, capsys):
    CorreoEnCarpeta(buzon).enviar("ana@qa.test", "Sin enlace", "Nada que abrir.")
    assert correos.main(["--ultimo"]) == 1


def test_por_defecto_usa_la_carpeta_del_repo(monkeypatch):
    monkeypatch.delenv("QA_BUZON", raising=False)
    assert correos.carpeta_del_buzon() == correos.REPO / ".qa" / "buzon"
