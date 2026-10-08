"""La landing de tumasterplan.cl muestra un master publicado dentro de un iframe."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

LANDING = Path(__file__).resolve().parents[2] / "landing"


def _politica_de_la_landing() -> dict[str, list[str]]:
    plantilla = json.loads((LANDING / "vercel.json").read_text())
    regla = next(r for r in plantilla["headers"] if r["source"] == "/(.*)")
    csp = next(e["value"] for e in regla["headers"] if e["key"] == "Content-Security-Policy")
    directivas = (d.split() for d in csp.split(";") if d.strip())
    return {d[0]: d[1:] for d in directivas}


def _iframes() -> list[str]:
    return re.findall(r'<iframe[^>]*\ssrc="([^"]+)"', (LANDING / "index.html").read_text())


def test_la_landing_inserta_al_menos_un_master():
    assert _iframes(), "la landing ya no muestra ningún master en vivo"


def test_cada_iframe_de_la_landing_esta_permitido_por_su_politica():
    """Sin su origen en frame-src el navegador deja el marco en blanco, sin avisar."""
    permitidos = _politica_de_la_landing()["frame-src"]
    for src in _iframes():
        partes = urlsplit(src)
        assert partes.scheme == "https", src
        assert f"https://{partes.netloc}" in permitidos, f"{src} no está en frame-src"


def test_la_landing_sigue_sin_javascript():
    assert _politica_de_la_landing()["script-src"] == ["'none'"]
    assert "<script" not in (LANDING / "index.html").read_text()
