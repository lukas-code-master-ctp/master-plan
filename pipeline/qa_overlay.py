"""Control de calce: dibuja los polígonos proyectados sobre cada panorámica.

    python -m pipeline.qa_overlay

Deja una imagen por vista en control-calce/. Sirve para revisar de un vistazo, antes
de publicar, que los polígonos caen sobre el terreno que corresponde. Si algo se ve
corrido, lo más probable es el rumbo (revisa el error de elevación del sol) o el
supuesto de terreno plano en las parcelas lejanas.
"""
from __future__ import annotations

import argparse
import json
import math

from PIL import Image, ImageDraw

from . import config

Image.MAX_IMAGE_PIXELS = None

ANCHO = 3200
ALTO = ANCHO // 2
COLOR_LINEA = (255, 45, 45)
COLOR_ETIQUETA = (255, 235, 120)


def generar(solo: str | None = None) -> list:
    vistas = json.loads((config.SALIDA_DATOS / "vistas.json").read_text(encoding="utf-8"))
    parcelas = json.loads((config.SALIDA_DATOS / "parcelas.json").read_text(encoding="utf-8"))
    estados = {p["id"]: p["estado"] for p in parcelas["parcelas"]}

    config.SALIDA_QA.mkdir(parents=True, exist_ok=True)
    generadas = []

    for vista in vistas["vistas"]:
        if solo and vista["id"] != solo:
            continue
        origen = config.SALIDA_PANORAMAS / vista["id"] / "alta.jpg"
        if not origen.exists():
            origen = config.SALIDA_PANORAMAS / vista["id"] / "media.jpg"
        if not origen.exists():
            print(f"  {vista['id']}: falta la panorámica, corre primero el pipeline")
            continue

        overlay = json.loads(
            (config.SALIDA_VISTAS / f"{vista['id']}.json").read_text(encoding="utf-8"))
        destino = config.SALIDA_QA / f"{vista['id']}.jpg"
        _dibujar(origen, destino, vista, overlay["parcelas"], estados)
        generadas.append(destino)
        print(f"  {destino.name}  ({len(overlay['parcelas'])} parcelas, "
              f"rumbo {vista['rumbo0']}°, error sol {vista['diagnostico']['error_elevacion']}°)")

    return generadas


def _dibujar(origen, destino, vista, parcelas, estados) -> None:
    with Image.open(origen) as imagen:
        lienzo = imagen.convert("RGB").resize((ANCHO, ALTO), Image.BILINEAR)

    dibujo = ImageDraw.Draw(lienzo)
    for parcela in parcelas:
        pixeles = [_a_pixel(azimut, elevacion, vista["rumbo0"])
                   for azimut, elevacion in parcela["anillo"]]
        for inicio, fin in zip(pixeles, pixeles[1:] + pixeles[:1]):
            # El meridiano de corte: un segmento que lo cruza se dibujaría como
            # una raya de lado a lado de la imagen.
            if abs(inicio[0] - fin[0]) > ANCHO / 2:
                continue
            dibujo.line([inicio, fin], fill=COLOR_LINEA, width=3)

        centro = _a_pixel(parcela["centro"][0], parcela["centro"][1], vista["rumbo0"])
        if parcela["area_angular"] > 2.0:
            marca = "" if estados.get(parcela["id"]) == "disponible" else "·"
            dibujo.text((centro[0] + 4, centro[1] - 6),
                        parcela["id"][1:] + marca, fill=COLOR_ETIQUETA)

    encabezado = (f"{vista['etiqueta']}   rumbo0 {vista['rumbo0']}°   "
                  f"sol {vista['diagnostico']['azimut_solar']}°/"
                  f"{vista['diagnostico']['elevacion_solar']}°   "
                  f"error elev {vista['diagnostico']['error_elevacion']}°   "
                  f"{len(parcelas)} parcelas")
    dibujo.rectangle([0, 0, ANCHO, 26], fill=(0, 0, 0))
    dibujo.text((8, 8), encabezado, fill=(120, 255, 220))

    # Solo la banda bajo el horizonte: arriba es cielo y no aporta al control.
    lienzo.crop((0, ALTO // 2 - 60, ANCHO, ALTO)).save(destino, quality=88)


def _a_pixel(azimut: float, elevacion: float, rumbo0: float) -> tuple[float, float]:
    x = ((azimut - rumbo0) % 360.0) / 360.0 * ANCHO
    y = (90.0 - elevacion) / 180.0 * ALTO
    return x, y


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solo", help="genera una sola vista, por ejemplo p03-300")
    argumentos = parser.parse_args(argv)

    print("Generando control de calce...")
    generadas = generar(argumentos.solo)
    print(f"\n{len(generadas)} imágenes en {config.SALIDA_QA}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
