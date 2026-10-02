"""Set de regresión de Crea tu KMZ: el método completo sobre planos reales, medido
contra sus KMZ reales.

    python -m pipeline.plano.regresion [--plano X] [--carpeta regresion] [--actualizar-linea-base]
    python -m pipeline.plano.regresion --con-lector [--salida resultados_con_lector.json]

`<carpeta>/planos/<id>/` trae `plano.pdf`, `entradas.json` y, si hay, `real.kmz`. Fuera
de git: los planos traen nombres y RUT de propietarios (ver `regresion/README.md`).

Por plano, en una carpeta temporal: digitalizar → georreferenciar → kmz, y se mide el
KMZ contra el real con `metricas.comparar`. Sin real (o sin anclas ni cuadrícula) se
informa solo cuántos lotes salieron.

`entradas.json` puede traer `"regresion": {"capas_excluidas": [...]}`: capas del KMZ
real que no son deslindes (bordes de camino, el polígono de caminos).

La tabla se compara con `<carpeta>/linea_base.json` y la salida es 1 si algún plano
empeora más que la tolerancia (`TOLERANCIAS`). `--actualizar-linea-base` guarda los
números de esta corrida (solo los planos corridos). Esta corrida es con las semillas
a mano y el lector apagado: no depende de que haya Tesseract.

`--con-lector` simula a la loteadora que todavía no marcó nada: se borran las semillas
y se enciende el lector de rótulos (`rotulos.py`; necesita Tesseract, o sea, correr en
la imagen de Docker). Las semillas borradas son la verdad de la numeración: un lote
está bien numerado si contiene la semilla real de su número. Además del recall de la
numeración se informan las mismas métricas de geometría (pareadas por número: un
número errado empareja mal y, si queda lejos, desarma la similitud del what-if; el
"tal cual", con la georreferencia de las anclas o la cuadrícula, no se contamina), las áreas del cuadro contra el KMZ real y la cuadrícula
leída contra la de `entradas.json`. Es informativa: no se compara con la línea base.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
from shapely.geometry import Point, Polygon

from .digitalizar import ENTRADAS, digitalizar, leer_entradas
from .georreferencia import georreferenciar
from .metricas import comparar, epsg_de_kmz, lotes_kmz
from .numeros import buscar, mismo_lote
from .salida import kmz

LINEA_BASE = "linea_base.json"
RESULTADOS = "resultados.json"
RESULTADOS_CON_LECTOR = "resultados_con_lector.json"

# Cuánto puede empeorar un plano contra la línea base.
TOLERANCIAS = dict(
    iou_what_if_mediana=0.01,         # no puede bajar más que esto
    centroide_what_if_mediana_m=0.25,  # no puede subir más que esto
    pareados=0,                        # no puede bajar
)


def correr_plano(carpeta: Path, avance=lambda texto: None, con_lector: bool = False) -> dict:
    """El método completo sobre `carpeta` (sin escribir en ella) y sus métricas. Con
    `con_lector`, sin las semillas a mano y con el lector de rótulos."""
    carpeta = Path(carpeta)
    entradas = leer_entradas(carpeta)
    fila = dict(plano=carpeta.name, semillas=len(entradas["semillas"]))
    with tempfile.TemporaryDirectory(prefix="regresion_") as tmp:
        trabajo = Path(tmp)
        crudas = json.loads((carpeta / ENTRADAS).read_text(encoding="utf-8"))
        crudas.update(semillas=[], lector=True) if con_lector else crudas.update(lector=False)
        (trabajo / ENTRADAS).write_text(json.dumps(crudas, ensure_ascii=False), encoding="utf-8")
        shutil.copyfile(carpeta / entradas["pdf"], trabajo / entradas["pdf"])
        inicio = time.time()
        digitalizado = digitalizar(trabajo, avance=avance)
        fila["segundos_digitalizar"] = round(time.time() - inicio, 1)
        if con_lector:
            fila["numeracion"] = numeracion(digitalizado, entradas["semillas"])
            fila["cuadricula_leida"] = cuadricula_leida((digitalizado.get("lector") or {}).get("cuadricula"),
                                                        entradas.get("cuadricula"))
        fila["lotes"] = len(digitalizado["lotes"])
        fila["faltantes"] = digitalizado["faltantes"]
        fila["sin_numero"] = len(digitalizado["sin_numero"])
        # Caras del tamaño de un lote que quedaron sin número (no se pegaron a un vecino).
        fila["sin_numero_lote"] = sum(bool(c.get("de_lote")) for c in digitalizado["sin_numero"])
        fila["sugerencias"] = [c["sugerencia"]["numero"] for c in digitalizado["sin_numero"] if c.get("sugerencia")]
        fila["huecos"] = digitalizado.get("huecos") or []
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
    if con_lector:
        fila["cuadro"] = cuadro_contra_real(digitalizado, lotes_real)
    return fila


def numeracion(digitalizado: dict, verdad: list[dict]) -> dict:
    """Qué tan bien numeró el lector: cada semilla real (número y posición, px de
    página) cae en un lote con su número (correcto), con otro (errado) o en ninguno.
    El número se compara con `numeros.mismo_lote`: "8-01" = "8-1", y "10-6" = "6"
    (las semillas de Hidango se leyeron sin el sector)."""
    lotes = [(l["numero"], Polygon(l["poligono"], l.get("huecos") or [])) for l in digitalizado["lotes"]]
    correctos = errados = sin_lote = 0
    for s in verdad:
        punto = Point(s["x"], s["y"])
        dentro = [n for n, g in lotes if g.contains(punto)]
        if any(mismo_lote(n, s["numero"]) for n in dentro):
            correctos += 1
        elif dentro:
            errados += 1
        else:
            sin_lote += 1
    reales = [str(s["numero"]) for s in verdad]
    lector = digitalizado.get("lector") or {}
    return dict(verdad=len(verdad), correctos=correctos, errados=errados, sin_lote=sin_lote,
                recall=correctos / len(verdad) if verdad else None,
                lotes_numero_ajeno=sum(1 for n, _ in lotes if not any(mismo_lote(n, r) for r in reales)),
                rotulos_leidos=len(lector.get("rotulos") or []), semillas_lector=lector.get("semillas"),
                segundos_lector=lector.get("segundos"), areas_leidas=len(lector.get("cuadro") or {}),
                motivo=lector.get("motivo"))


def cuadricula_leida(leida: dict | None, verdad: dict | None) -> dict | None:
    """La cuadrícula que propone el lector contra la de entradas.json: valores que
    coinciden y distancia (px) a la línea marcada."""
    if not leida:
        return dict(leidas=0)
    salida = dict(leidas=len(leida.get("verticales") or []) + len(leida.get("horizontales") or []))
    if verdad:
        bien, distancias, total = 0, [], 0
        for familia, eje in (("verticales", "x"), ("horizontales", "y")):
            reales = {m.get("valor"): m[eje] for m in verdad.get(familia) or [] if m.get("valor") is not None}
            total += len(reales)
            for m in leida.get(familia) or []:
                if m["valor"] in reales:
                    bien += 1
                    distancias.append(abs(m[eje] - reales[m["valor"]]))
        salida.update(reales=total, coinciden=bien,
                      distancia_mediana_px=round(float(np.median(distancias)), 1) if distancias else None)
    return salida


def cuadro_contra_real(digitalizado: dict, lotes_real: dict) -> dict:
    """Las áreas leídas del cuadro contra las del KMZ real (por número normalizado)."""
    cuadro = (digitalizado.get("lector") or {}).get("cuadro") or {}
    pares = [(a, buscar(lotes_real, n)) for n, a in cuadro.items()]
    errores = [abs(a / p.area - 1) for a, p in pares if p is not None and p.area]
    return dict(leidas=len(cuadro), comparadas=len(errores),
                dentro_2pct=sum(e <= 0.02 for e in errores),
                error_mediano_pct=round(100 * float(np.median(errores)), 2) if errores else None)


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


def tabla_con_lector(filas: list[dict]) -> str:
    n = lambda v, f="{:.3f}": "—" if v is None else f.format(v)
    lineas = ["| Plano | Rótulos leídos / semillas del lector | Lotes (+ de lote sin número) | Numeración correcta (recall)"
              " | Errados / sin lote | Lotes con número ajeno | Pareados / real | IoU tal cual → what-if (mediana)"
              " | Centroide tal cual → what-if (m) | Cuadro: áreas (±2 % del real) | Cuadrícula: coinciden / reales"
              " | Segundos (lector) |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for f in filas:
        u = f.get("numeracion")
        if not u:
            lineas.append(f"| {f['plano']} | {f.get('medicion', '—')} |" + " |" * 10)
            continue
        w, c = f.get("what_if") or {}, f.get("tal_cual") or {}
        cuadro = f.get("cuadro") or {}
        cuad = f.get("cuadricula_leida") or {}
        lineas.append(
            f"| {f['plano']} | {u['rotulos_leidos']} / {u['semillas_lector']}"
            f" | {f.get('lotes')} + {f.get('sin_numero_lote', 0)} sin número"
            f" | {u['correctos']} / {u['verdad']} ({n(u['recall'], '{:.0%}')})"
            f" | {u['errados']} / {u['sin_lote']} | {u['lotes_numero_ajeno']}"
            f" | {f.get('pareados', '—')} / {f.get('lotes_real', '—')}"
            f" | {n(c.get('iou_mediana'))} → {n(w.get('iou_mediana'))}"
            f" | {n(c.get('centroide_mediana_m'), '{:.2f}')} → {n(w.get('centroide_mediana_m'), '{:.2f}')}"
            f" | {cuadro.get('leidas', u['areas_leidas'])} ({cuadro.get('dentro_2pct', '—')})"
            f" | {cuad.get('coinciden', '—')} / {cuad.get('reales', '—')}"
            f" | {f['segundos_digitalizar']} ({u['segundos_lector']}) |")
    return "\n".join(lineas)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m pipeline.plano.regresion",
                                     description="Corre el set de regresión y lo compara con la línea base.")
    parser.add_argument("--plano", action="append", help="solo este plano (se puede repetir)")
    parser.add_argument("--carpeta", type=Path, default=Path("regresion"))
    parser.add_argument("--actualizar-linea-base", action="store_true")
    parser.add_argument("--detalle", action="store_true", help="imprime el avance de cada etapa")
    parser.add_argument("--con-lector", action="store_true",
                        help="sin semillas a mano y con el lector de rótulos (necesita Tesseract)")
    parser.add_argument("--salida", type=Path, help="dónde escribir los resultados (por omisión, en la carpeta)")
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
            filas.append(correr_plano(p, avance, con_lector=args.con_lector))
        except (ValueError, KeyError, FileNotFoundError) as e:
            print(f"  Error: {e}", file=sys.stderr)
            filas.append(dict(plano=p.name, semillas=0, medicion=f"error: {e}"))
    print()
    print(tabla_con_lector(filas) if args.con_lector else tabla(filas))
    salida = args.salida or args.carpeta / (RESULTADOS_CON_LECTOR if args.con_lector else RESULTADOS)
    salida.write_text(json.dumps(filas, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if args.con_lector:
        return 0

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
