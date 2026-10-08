"""La landing de tumasterplan.cl muestra un master publicado dentro de un iframe."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

LANDING = Path(__file__).resolve().parents[2] / "landing"
# La propiedad de GA4 de tumasterplan.cl.
MEDICION = "G-0BBZ42FZH8"


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


def test_el_unico_javascript_es_el_de_google_analytics():
    """La página no necesita script para funcionar: lo único que corre es la medición."""
    assert _politica_de_la_landing()["script-src"] == ["'self'", "https://www.googletagmanager.com"]
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", (LANDING / "index.html").read_text(), re.S)
    assert [contenido.strip() for _, contenido in scripts] == ["", ""], "nada de scripts en línea"
    fuentes = [re.search(r'src="([^"]+)"', atributos).group(1) for atributos, _ in scripts]
    assert fuentes == [f"https://www.googletagmanager.com/gtag/js?id={MEDICION}", "/analitica.js"]


def test_analitica_usa_el_mismo_id_que_carga_la_pagina():
    assert f"gtag('config', '{MEDICION}'" in (LANDING / "analitica.js").read_text()


def test_la_politica_deja_que_analytics_mande_sus_datos():
    politica = _politica_de_la_landing()
    for origen in ("https://*.google-analytics.com", "https://*.analytics.google.com",
                   "https://*.googletagmanager.com"):
        assert origen in politica["connect-src"], origen
    assert "https://*.google-analytics.com" in politica["img-src"]


def test_el_iframe_y_las_tarjetas_hablan_de_la_misma_parcela():
    """Cuando se vende la parcela de muestra se cambia en varios lugares: que no quede uno atrás."""
    html = (LANDING / "index.html").read_text()
    lote = re.search(r'<iframe[^>]*\ssrc="[^"]*[?&]lote=([^"&]+)"', html).group(1)
    assert re.search(rf'class="ficha__nombre">Parcela {re.escape(lote)}<', html), lote
    assert f"Me interesa la parcela {lote}»" in html, lote
