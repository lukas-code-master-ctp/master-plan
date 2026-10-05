"""Panorámicas sintéticas con la misma metadata DJI que lee `pipeline.panoramas`.

Las usan las pruebas del pipeline y el QA local (`qa/ficticios.py`): una imagen
equirectangular gris lisa, con el sol dibujado donde se pida, y el XMP de un vuelo
real (posición GPS, alturas, hora de captura y yaw del gimbal). No depende de pytest.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

XMP_PLANTILLA = """<?xpacket begin=""?>
<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF
 xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
 <rdf:Description rdf:about=""
   xmlns:drone-dji="http://www.uav.com/drone-dji/1.0/"
   xmlns:GPano="http://ns.google.com/photos/1.0/panorama/"
   xmlns:xmp="http://ns.adobe.com/xap/1.0/"
   xmp:CreateDate="{momento}"
   drone-dji:GpsLatitude="{lat}"
   drone-dji:GpsLongitude="{lon}"
   drone-dji:AbsoluteAltitude="{absoluta}"
   drone-dji:RelativeAltitude="{relativa}"
   drone-dji:GimbalYawDegree="{gimbal}"
   GPano:ProjectionType="equirectangular"/>
 </rdf:RDF></x:xmpmeta><?xpacket end="w"?>"""


def escribir_panorama(ruta, *, lat=-34.7969, lon=-72.0025, relativa=100.281,
                      absoluta=185.170, momento="2026-03-05T19:05:15-03:00",
                      gimbal=67.7, ancho=720, sol_x=None, sol_elevacion=None):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    alto = ancho // 2
    lienzo = np.full((alto, ancho), 110, dtype=np.uint8)
    if sol_x is not None:
        y = int((90 - sol_elevacion) / 180 * alto)
        ys, xs = np.mgrid[0:alto, 0:ancho]
        dx = np.minimum(np.abs(xs - sol_x), ancho - np.abs(xs - sol_x))
        lienzo[(dx ** 2 + (ys - y) ** 2) < 36] = 255
    imagen = Image.fromarray(lienzo).convert("RGB")
    xmp = XMP_PLANTILLA.format(lat=lat, lon=lon, relativa=relativa,
                               absoluta=absoluta, momento=momento, gimbal=gimbal)
    imagen.save(ruta, "JPEG", xmp=xmp.encode("utf-8"), quality=95)
    return ruta
