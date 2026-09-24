"""Control de calce: dibuja los polígonos proyectados sobre cada panorámica.

    python -m pipeline.qa_overlay --proyecto "ruta/a/la/carpeta"

Deja una imagen por vista en salidas/<proyecto>/control-calce/. Sirve para revisar
de un vistazo, antes de publicar, que los polígonos caen sobre el terreno que
corresponde. Si algo se ve corrido, lo más probable es el rumbo (revisa el error de
elevación del sol) o el supuesto de terreno plano en las parcelas lejanas.
"""
from __future__ import annotations

import argparse
import json
import sys

from PIL import Image, ImageDraw

from . import config

Image.MAX_IMAGE_PIXELS = None

ANCHO = 3200
ALTO = ANCHO // 2
COLOR_LINEA = (255, 45, 45)
COLOR_ETIQUETA = (255, 235, 120)


def generar(salida: config.Salida, solo: str | None = None) -> list:
    vistas = json.loads((salida.datos / "vistas.json").read_text(encoding="utf-8"))
    parcelas = json.loads((salida.datos / "parcelas.json").read_text(encoding="utf-8"))
    estados = {p["id"]: p["estado"] for p in parcelas["parcelas"]}
    rotulos = {p["id"]: p.get("rotulo", p["id"]) for p in parcelas["parcelas"]}

    salida.qa.mkdir(parents=True, exist_ok=True)
    generadas = []

    for vista in vistas["vistas"]:
        if solo and vista["id"] != solo:
            continue
        origen = salida.panoramas / vista["id"] / "alta.jpg"
        if not origen.exists():
            origen = salida.panoramas / vista["id"] / "media.jpg"
        if not origen.exists():
            print(f"  {vista['id']}: falta la panorámica, corre primero el pipeline")
            continue

        overlay = json.loads(
            (salida.vistas / f"{vista['id']}.json").read_text(encoding="utf-8"))
        destino = salida.qa / f"{vista['id']}.jpg"
        _dibujar(origen, destino, vista, overlay["parcelas"], estados, rotulos,
                 overlay.get("referencias", []))
        generadas.append(destino)
        print(f"  {destino.name}  ({len(overlay['parcelas'])} parcelas, "
              f"rumbo {vista['rumbo0']}°, error sol {vista['diagnostico']['error_elevacion']}°)")

    return generadas


def _dibujar(origen, destino, vista, parcelas, estados, rotulos, referencias=()) -> None:
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
                        rotulos.get(parcela["id"], parcela["id"]) + marca, fill=COLOR_ETIQUETA)

    for referencia in referencias:
        x, y = _a_pixel(referencia["az"], referencia["el"], vista["rumbo0"])
        dibujo.line([(x, y), (x, y - 18)], fill=COLOR_ETIQUETA, width=2)
        dibujo.text((x + 4, y - 30), f"{referencia['nombre']} · {referencia['distancia_km']} km",
                    fill=COLOR_ETIQUETA)

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
    from .construir import agregar_argumentos_de_proyecto, resolver

    parser = argparse.ArgumentParser(description=__doc__)
    agregar_argumentos_de_proyecto(parser)
    parser.add_argument("--solo", help="genera una sola vista, por ejemplo p03-300")
    argumentos = parser.parse_args(argv)

    try:
        _, _, salida = resolver(argumentos)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1

    print("Generando control de calce...")
    generadas = generar(salida, argumentos.solo)
    print(f"\n{len(generadas)} imágenes en {salida.qa}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
