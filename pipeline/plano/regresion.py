"""Set de regresión de Crea tu KMZ: el método completo sobre planos reales, medido
contra sus KMZ reales.

    python -m pipeline.plano.regresion [--plano X] [--carpeta regresion] [--actualizar-linea-base]

`<carpeta>/planos/<id>/` trae `plano.pdf`, `entradas.json` y, si hay, `real.kmz`. Fuera
de git: los planos traen nombres y RUT de propietarios (ver `regresion/README.md`).

Por plano, en una carpeta temporal: digitalizar → georreferenciar → kmz, y se mide el
KMZ contra el real con `metricas.comparar`. Sin real (o sin anclas ni cuadrícula) se
informa solo cuántos lotes salieron.

`entradas.json` puede traer `"regresion": {"capas_excluidas": [...]}`: capas del KMZ
real que no son deslindes (bordes de camino, el polígono de caminos).

La tabla se compara con `<carpeta>/linea_base.json` y la salida es 1 si algún plano
empeora más que la tolerancia (`TOLERANCIAS`). `--actualizar-linea-base` guarda los
números de esta corrida (solo los planos corridos).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

from .digitalizar import ENTRADAS, digitalizar, leer_entradas
from .georreferencia import georreferenciar
from .metricas import comparar, epsg_de_kmz, lotes_kmz
from .salida import kmz

LINEA_BASE = "linea_base.json"
RESULTADOS = "resultados.json"

# Cuánto puede empeorar un plano contra la línea base.
TOLERANCIAS = dict(
    iou_what_if_mediana=0.01,         # no puede bajar más que esto
    centroide_what_if_mediana_m=0.25,  # no puede subir más que esto
    pareados=0,                        # no puede bajar
)


def correr_plano(carpeta: Path, avance=lambda texto: None) -> dict:
    """El método completo sobre `carpeta` (sin escribir en ella) y sus métricas."""
    carpeta = Path(carpeta)
    entradas = leer_entradas(carpeta)
    fila = dict(plano=carpeta.name, semillas=len(entradas["semillas"]))
    with tempfile.TemporaryDirectory(prefix="regresion_") as tmp:
        trabajo = Path(tmp)
        shutil.copyfile(carpeta / ENTRADAS, trabajo / ENTRADAS)
        shutil.copyfile(carpeta / entradas["pdf"], trabajo / entradas["pdf"])
        inicio = time.time()
        digitalizado = digitalizar(trabajo, avance=avance)
        fila["segundos_digitalizar"] = round(time.time() - inicio, 1)
        fila["lotes"] = len(digitalizado["lotes"])
        fila["faltantes"] = digitalizado["faltantes"]
        fila["sin_numero"] = len(digitalizado["sin_numero"])
        fila["trabajo_ppmm"] = round(digitalizado["trabajo"]["ppmm"], 3)
        fila["trabajo_mpx"] = round(digitalizado["trabajo"]["ancho"] * digitalizado["trabajo"]["alto"] / 1e6, 1)
        if not entradas["anclas"] and not entradas.get("cuadricula"):
            fila["medicion"] = "sin anclas ni cuadrícula: no se ubica"
            return fila
        t = georreferenciar(trabajo, avance=avance)
        fila["georreferencia"] = dict(metodo=t.metodo, epsg=t.epsg, rms_m=t.parametros.get("rms_m"))
        candidato = trabajo / "candidato.kmz"
        kmz(trabajo, candidato, avance=avance)
        real = carpeta / "real.kmz"
        if not real.is_file():
            fila["medicion"] = "sin KMZ real"
            return fila
        excluidas = (entradas.get("regresion") or {}).get("capas_excluidas") or []
        epsg = epsg_de_kmz(real)
        lotes_real, informe_real = lotes_kmz(real, epsg, excluidas)
        lotes_candidato, _ = lotes_kmz(candidato, epsg)
    m = comparar(lotes_candidato, lotes_real)
    m.pop("por_lote", None)
    fila.update(m, epsg_medicion=epsg, real=informe_real)
    return fila


def resumen_base(fila: dict) -> dict:
    """Lo que se guarda en la línea base y se compara."""
    salida = dict(lotes=fila.get("lotes"))
    if "what_if" in fila and fila["what_if"].get("n"):
        w, c = fila["what_if"], fila["tal_cual"]
        salida.update(pareados=fila["pareados"], iou_what_if_mediana=round(w["iou_mediana"], 4),
                      centroide_what_if_mediana_m=round(w["centroide_mediana_m"], 3),
                      iou_tal_cual_mediana=round(c["iou_mediana"], 4),
                      centroide_tal_cual_mediana_m=round(c["centroide_mediana_m"], 3),
                      hausdorff_what_if_mediana_m=round(w["hausdorff_mediana_m"], 3))
    return salida


def regresiones(fila: dict, base: dict) -> list[str]:
    """Qué empeoró más que la tolerancia (vacío si nada)."""
    actual = resumen_base(fila)
    malos = []
    if base.get("lotes") is not None and (actual.get("lotes") or 0) < base["lotes"]:
        malos.append(f"lotes {actual.get('lotes')} < {base['lotes']}")
    if base.get("pareados") is not None:
        if actual.get("pareados") is None:
            return malos + ["no se pudo medir"]
        if actual["pareados"] < base["pareados"] - TOLERANCIAS["pareados"]:
            malos.append(f"pareados {actual['pareados']} < {base['pareados']}")
        if actual["iou_what_if_mediana"] < base["iou_what_if_mediana"] - TOLERANCIAS["iou_what_if_mediana"]:
            malos.append(f"IoU what-if {actual['iou_what_if_mediana']:.3f} < {base['iou_what_if_mediana']:.3f}")
        tope = base["centroide_what_if_mediana_m"] + TOLERANCIAS["centroide_what_if_mediana_m"]
        if actual["centroide_what_if_mediana_m"] > tope:
            malos.append(f"centroide what-if {actual['centroide_what_if_mediana_m']:.2f} m"
                         f" > {base['centroide_what_if_mediana_m']:.2f} m")
    return malos


def tabla(filas: list[dict]) -> str:
    n = lambda v, f="{:.3f}": "—" if v is None else f.format(v)
    lineas = ["| Plano | Lotes / semillas | Pareados / real | IoU tal cual → what-if (mediana) | IoU what-if p10"
              " | Centroide tal cual → what-if (m) | Hausdorff what-if mediana / p10 / p90 (m)"
              " | Similitud: giro, escala, dE / dN | Error de área | Traslapes / huecos (m²) | Segundos |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in filas:
        lotes = f"{f.get('lotes', '—')} / {f['semillas']}"
        if not f.get("what_if", {}).get("n"):
            lineas.append(f"| {f['plano']} | {lotes} | {f.get('medicion', '—')} | | | | | | | |"
                          f" {f.get('segundos_digitalizar', '')} |")
            continue
        c, w, s, t = f["tal_cual"], f["what_if"], f["similitud"], f["topologia"]
        lineas.append(
            f"| {f['plano']} | {lotes} | {f['pareados']} / {f['lotes_real']}"
            f" | {n(c['iou_mediana'])} → {n(w['iou_mediana'])} | {n(w['iou_p10'])}"
            f" | {n(c['centroide_mediana_m'], '{:.2f}')} → {n(w['centroide_mediana_m'], '{:.2f}')}"
            f" | {w['hausdorff_mediana_m']:.2f} / {w['hausdorff_p10_m']:.2f} / {w['hausdorff_p90_m']:.2f}"
            f" | {s['rotacion_grados']:+.3f}°, {s['escala_pct']:+.3f} %, {s['de_m']:+.2f} / {s['dn_m']:+.2f} m"
            f" | {c['error_area_mediana_pct']:.2f} % → {w['error_area_mediana_pct']:.2f} %"
            f" | {t['traslapes_m2']:.0f} / {t['huecos_m2']:.0f} | {f['segundos_digitalizar']} |")
    return "\n".join(lineas)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline.plano.regresion",
                                     description="Corre el set de regresión y lo compara con la línea base.")
    parser.add_argument("--plano", action="append", help="solo este plano (se puede repetir)")
    parser.add_argument("--carpeta", type=Path, default=Path("regresion"))
    parser.add_argument("--actualizar-linea-base", action="store_true")
    parser.add_argument("--detalle", action="store_true", help="imprime el avance de cada etapa")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        # La consola de Windows (cp1252) no tiene «→»: mejor un «?» que una traza.
        sys.stdout.reconfigure(errors="replace")
    raiz = args.carpeta / "planos"
    if not raiz.is_dir():
        print(f"No está {raiz}: el set de regresión vive fuera de git (ver pipeline/plano/regresion.py)",
              file=sys.stderr)
        return 2
    planos = sorted(p for p in raiz.iterdir() if (p / ENTRADAS).is_file())
    if args.plano:
        faltan = set(args.plano) - {p.name for p in planos}
        if faltan:
            print(f"No están en {raiz}: {', '.join(sorted(faltan))}", file=sys.stderr)
            return 2
        planos = [p for p in planos if p.name in args.plano]
    avance = (lambda texto: print(f"    {texto}", flush=True)) if args.detalle else (lambda texto: None)
    filas = []
    for p in planos:
        print(f"{p.name}…", flush=True)
        try:
            filas.append(correr_plano(p, avance))
        except (ValueError, KeyError, FileNotFoundError) as e:
            print(f"  Error: {e}", file=sys.stderr)
            filas.append(dict(plano=p.name, semillas=0, medicion=f"error: {e}"))
    print()
    print(tabla(filas))
    (args.carpeta / RESULTADOS).write_text(json.dumps(filas, ensure_ascii=False, indent=1, default=str),
                                           encoding="utf-8")

    ruta_base = args.carpeta / LINEA_BASE
    base = json.loads(ruta_base.read_text(encoding="utf-8")) if ruta_base.is_file() else {}
    if args.actualizar_linea_base:
        base.update({f["plano"]: resumen_base(f) for f in filas})
        ruta_base.write_text(json.dumps(base, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nLínea base actualizada: {ruta_base}")
        return 0
    if not base:
        print(f"\nSin {LINEA_BASE}: nada que comparar (créala con --actualizar-linea-base).")
        return 0
    peor = False
    print()
    for f in filas:
        if f["plano"] not in base:
            print(f"{f['plano']}: sin línea base")
            continue
        malos = regresiones(f, base[f["plano"]])
        peor |= bool(malos)
        print(f"{f['plano']}: " + ("EMPEORA: " + "; ".join(malos) if malos else "ok"))
    return 1 if peor else 0


if __name__ == "__main__":
    sys.exit(main())
