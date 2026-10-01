"""El KMZ de la subdivisión y el GeoJSON del mapa, desde los lotes ya ubicados.

    python -m pipeline.plano kmz <carpeta-del-plano> <destino.kmz>

Un Placemark por lote, con nombre `LOTE <n>` y un Polygon (con sus huecos, si los
tiene), en KML 2.2. Sin LineStrings ni Points: así `pipeline/kmz.py` lo lee en modo
polígonos y saca el id del nombre. El área va en m² medidos en UTM, en la
descripción y en ExtendedData. Las caras sin número no salen.
"""
from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import numpy as np
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from ..kmz import normalizar_id
from .georreferencia import SALIDA as GEORREFERENCIA, Transformacion

KML_NS = "http://www.opengis.net/kml/2.2"


def lotes_utm(digitalizado: dict, t: Transformacion) -> list[tuple[str, Polygon]]:
    """[(numero, Polygon en el EPSG de `t`)], en el orden del digitalizado."""
    salida = []
    for lote in digitalizado["lotes"]:
        anillos = [lote["poligono"]] + list(lote.get("huecos") or [])
        utm = [np.c_[t.a_utm(*np.asarray(a, float).T)] for a in anillos]
        salida.append((str(lote["numero"]), Polygon(utm[0], utm[1:])))
    return salida


def _lonlat(anillo, t: Transformacion) -> list[tuple[float, float]]:
    lon, lat = t.a_lonlat(*np.asarray(anillo, float).T)
    return list(zip(np.atleast_1d(lon).tolist(), np.atleast_1d(lat).tolist()))


def _poligono_lonlat(lote: dict, t: Transformacion) -> Polygon:
    # Exterior antihorario y huecos horarios, como pide la convención (KML y GeoJSON).
    return orient(Polygon(_lonlat(lote["poligono"], t), [_lonlat(h, t) for h in lote.get("huecos") or []]))


def _revisar_ids(digitalizado: dict) -> None:
    ids = [normalizar_id(f"LOTE {l['numero']}") for l in digitalizado["lotes"]]
    malos = [str(l["numero"]) for l, i in zip(digitalizado["lotes"], ids) if i is None]
    if malos:
        raise ValueError(f"números de lote que el lector de KMZ no reconoce: {', '.join(malos)}")
    repetidos = sorted({i for i in ids if ids.count(i) > 1})
    if repetidos:
        raise ValueError(f"números de lote repetidos: {', '.join(repetidos)}")


def kml(digitalizado: dict, t: Transformacion, nombre: str = "Subdivisión") -> str:
    _revisar_ids(digitalizado)
    areas = dict(lotes_utm(digitalizado, t))
    partes = ['<?xml version="1.0" encoding="UTF-8"?>',
              f'<kml xmlns="{KML_NS}"><Document>',
              f"<name>{escape(nombre)}</name>",
              '<Style id="lote"><LineStyle><color>ff0000ff</color><width>1.5</width></LineStyle>'
              "<PolyStyle><color>220000ff</color></PolyStyle></Style>"]
    for lote in digitalizado["lotes"]:
        numero = str(lote["numero"])
        area = areas[numero].area
        p = _poligono_lonlat(lote, t)
        anillo = lambda a: " ".join(f"{lon:.8f},{lat:.8f},0" for lon, lat in a.coords)
        huecos = "".join(f"<innerBoundaryIs><LinearRing><coordinates>{anillo(h)}</coordinates></LinearRing>"
                         "</innerBoundaryIs>" for h in p.interiors)
        datos = f'<Data name="area_m2"><value>{area:.1f}</value></Data>'
        descripcion = f"Superficie {area:,.0f} m²".replace(",", ".")
        if lote.get("area_oficial") is not None:
            datos += f'<Data name="area_oficial_m2"><value>{float(lote["area_oficial"]):.1f}</value></Data>'
            descripcion += f"; cuadro de superficies {float(lote['area_oficial']):,.0f} m²".replace(",", ".")
        partes.append(f"<Placemark><name>LOTE {escape(numero)}</name>"
                      f"<description>{escape(descripcion)}</description>"
                      f"<styleUrl>#lote</styleUrl><ExtendedData>{datos}</ExtendedData>"
                      f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{anillo(p.exterior)}</coordinates>"
                      f"</LinearRing></outerBoundaryIs>{huecos}</Polygon></Placemark>")
    partes.append("</Document></kml>")
    return "\n".join(partes)


def geojson(digitalizado: dict, t: Transformacion) -> dict:
    """Los lotes en lon/lat, con su número y área, para el mapa de la consola."""
    areas = dict(lotes_utm(digitalizado, t))
    rasgos = []
    for lote in digitalizado["lotes"]:
        numero = str(lote["numero"])
        p = _poligono_lonlat(lote, t)
        rasgos.append(dict(
            type="Feature",
            properties=dict(numero=numero, area_m2=round(areas[numero].area, 1),
                            area_oficial_m2=lote.get("area_oficial")),
            geometry=dict(type="Polygon", coordinates=[[list(c) for c in p.exterior.coords]]
                          + [[list(c) for c in h.coords] for h in p.interiors])))
    return dict(type="FeatureCollection", features=rasgos)


def escribir_kmz(destino: Path, digitalizado: dict, t: Transformacion, nombre: str | None = None) -> int:
    """Escribe el KMZ aparte y lo cambia de nombre al final (sin copystat: puede ser un
    bucket montado con gcsfuse). Devuelve cuántos lotes lleva."""
    destino = Path(destino)
    texto = kml(digitalizado, t, nombre or destino.stem)
    temporal = destino.with_name(f".{destino.name}.{os.getpid()}")
    try:
        with zipfile.ZipFile(temporal, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("doc.kml", texto)
        os.replace(temporal, destino)
    finally:
        temporal.unlink(missing_ok=True)
    return len(digitalizado["lotes"])


def kmz(carpeta: Path, destino: Path, avance=print) -> int:
    from .digitalizar import SALIDA as DIGITALIZADO

    carpeta = Path(carpeta)
    faltan = [n for n in (DIGITALIZADO, GEORREFERENCIA) if not (carpeta / n).is_file()]
    if faltan:
        raise FileNotFoundError(f"faltan {', '.join(faltan)} en {carpeta}")
    digitalizado = json.loads((carpeta / DIGITALIZADO).read_text(encoding="utf-8"))
    t = Transformacion.desde_dict(json.loads((carpeta / GEORREFERENCIA).read_text(encoding="utf-8")))
    n = escribir_kmz(destino, digitalizado, t)
    total = sum(p.area for _, p in lotes_utm(digitalizado, t))
    hectareas = f"{total / 10000:,.2f}".replace(",", " ").replace(".", ",").replace(" ", ".")
    avance(f"KMZ: {n} lotes, {hectareas} ha, EPSG:{t.epsg}, en {destino}")
    return n
