"""Digitalizar un plano: de `entradas.json` a `digitalizado.json`.

    python -m pipeline.plano digitalizar <carpeta-del-plano>

Imprime una línea por etapa: la consola muestra la salida en vivo.

`<carpeta>/entradas.json` (lo que aporta la loteadora; `anclas`, `ubicacion` y `ajuste` son de
`georreferenciar` y aquí solo se revisan):

    {
      "pdf": "plano.pdf",              ruta relativa a la carpeta
      "pagina": 1,                     desde 1; 0 es la unión de hojas (y solo con «union»)
      "rotacion": 0,                   grados en sentido horario: 0, 90, 180 o 270; con
                                       la unión, 0 (cada hoja lleva su giro)
      "union": null,                   varias páginas del PDF en un solo lienzo
                                       (`union.py`): {"hojas": [{"n", "rotacion",
                                       "angulo", "x", "y", "recorte"}], de abajo hacia
                                       arriba, "cuadro": {"hoja": n, "rect": [x0, y0,
                                       x1, y1]} | null}. El cuadro va en px de su hoja
                                       (girada), no de la unión
      "rectangulo": [x0, y0, x1, y1],  el dibujo de la "situación propuesta"
      "mascaras": [[x0, y0, x1, y1]],  lo que no es dibujo: cuadros, cajetín, timbres
      "esquinas": null,                foto: [[x, y] × 4] del marco impreso, en orden
                                       sup-izq, sup-der, inf-der, inf-izq
      "marco_mm": null,                foto: [ancho, alto] del marco en mm de papel;
                                       sin él se supone la escala de la hoja del PDF
      "cuadricula": null,              cuadrícula UTM impresa, posición aproximada de
                                       cada línea: {"verticales": [{"x": 680, "valor": 6306750}],
                                       "horizontales": [{"y": 288, "valor": 255750}],
                                       "epsg": null}
                                       aquí se borra la línea; "valor" (E o N impreso, se
                                       deduce cuál por la magnitud) y "epsg" (opcional: el
                                       datum y huso de los valores; sin él, WGS84 en el huso
                                       de las anclas, o PSAD56 si las anclas lo indican)
                                       son para georreferenciar
      "semillas": [{"numero": "12", "x": 1234.5, "y": 678.0}],   los números que marcó
                                       la loteadora: mandan sobre el lector
      "lector": true,                  leer los rótulos con el lector (`rotulos.py`);
                                       sin Tesseract instalado se sigue sin él
      "lector_apoyo_min": 2,           cuántas pasadas deben leer un número para
                                       que sea semilla
      "cuadro": null,                  [x0, y0, x1, y1] del cuadro de superficies (lo
                                       marca la loteadora); puede estar fuera de
                                       `rectangulo`: se lee igual. Dentro del dibujo
                                       tapa como una máscara. Sin él se prueba cada
                                       máscara. Con la unión es null: va en
                                       `union.cuadro`
      "anclas": [{"nombre": "roja", "x": 2533, "y": 8037,       punto del plano ↔ su lon/lat
                  "lon": -70.8240, "lat": -34.7240}],           WGS84 en grados decimales
      "ubicacion": {"x": 331.5, "y": 845.1,   ubicar con un punto: el punto del plano (px de
                    "lon": -71.5483, "lat": -34.1771,   página), su coordenada WGS84, el giro
                    "giro": 89.3,                   en grados (horario, como gira ella el plano
                    "escala_impresa": null},        en pantalla: 0 = el arriba es el norte) y la
                                       escala 1:N del plano, que se usa si no hay cuadro de
                                       superficies. Puede venir a medias (solo la coordenada)
                                       mientras la arma: entonces no ubica
      "escala_cuadro": true,           con 2 o más anclas: el tamaño sale del cuadro de
                                       superficies y de los puntos solo la posición y el
                                       giro ("Ajustar el tamaño con el cuadro")
      "ajuste": {"de": 0.0, "dn": 0.0}, traslación fina en metros (este, norte)
      "fuera": [[x, y]]                partes sin número que ella dejó fuera del KMZ (el
                                       resto de la propiedad): un punto dentro de cada una.
                                       No cambia los lotes; solo que la consola no las
                                       cuente como lotes sin número
    }

Todas las coordenadas van en **píxeles de página**: la imagen que trae el PDF, ya
girada según `rotacion` (lo que ve la loteadora), con el centro del píxel en el
entero. Si cambia la rotación, cambian las coordenadas. Con la unión (`pagina: 0`), la
página es la imagen compuesta de las hojas: sus px empiezan en (0, 0) como los de
cualquier página.

`<carpeta>/digitalizado.json`:

    {
      "pagina": {"numero", "rotacion", "ancho", "alto", "ppmm", "fuente",
                 "union"},                         huella de la unión (`union.huella`),
                                                   o null; con ella numero es 0 y
                                                   fuente "union"
      "trabajo": {"ancho", "alto", "ppmm", "modo", "homografia"},   página -> trabajo (3×3)
      "lotes": [{"numero", "semilla": [x, y], "poligono": [[x, y], ...],
                 "huecos": [[[x, y], ...]], "area_px", "vertices",
                 "origen": "usuario" | "lector",   de dónde salió el número
                 "confianza", "apoyo",             del lector (null si lo marcó ella)
                 "area_oficial"}],                 m² del cuadro de superficies (o null)
                                                   todo en px de página
      "sin_numero": [{"poligono", "area_px",       caras dentro del contorno sin lote
                      "de_lote",                   del tamaño de un lote: un lote cuyo número
                                                   no se leyó (no se unió a su vecino y no
                                                   es una franja como un camino); hay que
                                                   numerarlo o crear el KMZ sin él
                      "sugerencia"}],              {"numero", "confianza", "apoyo"} o null: lo
                                                   que leyó el lector dentro, con menos apoyo
                                                   que `lector_apoyo_min` (no es semilla)
      "faltantes": ["13"],                         semillas de la loteadora sin polígono
      "huecos": ["8-03"],                          números que faltan en la numeración, por
                                                   sector (`numeros.huecos`), junto a una cara
                                                   sin número del tamaño de un lote; y los del
                                                   cuadro (menos el resto de la propiedad,
                                                   `numeros.esperados`)
      "cuadricula": {"verticales": [{"x", "valor", "p": [x, y], "q": [x, y], "valida"}],
                     "horizontales": [{"y", ...}]},  las rectas detectadas (o null): las de
                                                   la cuadrícula elegida o, sin ella, las de
                                                   la que propone el lector (sin borrar su
                                                   tinta). "x"/"y": de dónde se partió
      "lector": {"activo", "disponible", "motivo",   motivo: por qué no hubo lector
                 "huella",                          con qué página, rectángulo y máscaras
                                                    se leyó: si no cambian, se reusa
                 "rotulos": [{"numero", "x", "y", "confianza", "apoyo", "alto"}],
                                                    todo lo leído (px de página)
                 "apoyo_min", "semillas",           cuántos rótulos fueron semilla
                 "sin_poligono": ["7"],             semillas del lector sin polígono
                 "cuadricula": {...} | null,        la cuadrícula leída, en el formato
                                                    de entradas: la consola la propone
                 "cuadro": {"12": 50000.0},         áreas oficiales leídas, m²
                 "segundos"},
      "estadisticas": {...}
    }

Semillas: las de la loteadora y, donde ella no marcó, los rótulos leídos con apoyo ≥
`lector_apoyo_min` (ver `rotulos.combinar`). La primera digitalización puede no tener
ninguna semilla suya: los números salen todos del lector.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

from . import pagina as pag
from . import numeros as numeros_lote
from . import particion, rotulos, tinta
from . import union as union_hojas
from .georreferencia import cuadricula_suficiente

ENTRADAS = "entradas.json"
SALIDA = "digitalizado.json"
# Las pasadas del lector ya leídas, por huella (`rotulos.leer(avance_en=…)`); se borra
# cuando digitalizado.json ya tiene el resultado.
AVANCE_LECTOR = "lector-avance"

# Un rótulo leído a menos de esto de una semilla de la loteadora es el que ella corrigió.
RADIO_CORRECCION_MM = 6.0


@dataclass
class Resultado:
    encuadre: pag.Encuadre
    lotes: dict[str, Polygon]          # px de página
    sin_numero: list[Polygon]          # px de página
    lotes_trabajo: dict[str, Polygon]  # px de trabajo
    estadisticas: dict = field(default_factory=dict)
    cuadricula: dict | None = None     # líneas detectadas, en px de página
    sin_numero_lote: list[bool] = field(default_factory=list)   # por cara sin número: ¿es un lote?


def digitalizar_imagen(imagen: np.ndarray, ppmm: float, semillas, rectangulo=None, mascaras=(),
                       esquinas=None, marco_mm=None, cuadricula=None, avance=print) -> Resultado:
    """El método completo sobre una imagen de página ya girada (RGB uint8).

    `ppmm`: px por mm de papel de la página. `semillas`: [(numero, x, y)] en px de
    página. `cuadricula`: {"verticales": [{"x": ...}], "horizontales": [{"y": ...}]}.
    """
    inicio = time.time()
    alto, ancho = imagen.shape[:2]
    rectangulo = rectangulo if rectangulo is not None else [0, 0, ancho, alto]

    segmentos = []
    detectada = None
    if cuadricula:
        detectada, segmentos = rectas_cuadricula(imagen, ppmm, cuadricula, avance)

    papel = pag.color_papel(imagen, rectangulo)
    tapada = pag.tapar(imagen, mascaras, papel)
    encuadre = pag.encuadrar(tapada, ppmm, rectangulo, esquinas, marco_mm, papel)
    del tapada
    trabajo = encuadre.imagen
    avance(f"Imagen de trabajo: {trabajo.shape[1]}×{trabajo.shape[0]} px a {encuadre.ppmm:.2f} px/mm"
           f" ({encuadre.modo})")

    banda = None
    if segmentos:
        extremos = encuadre.a_trabajo([p for s in segmentos for p in s]).reshape(-1, 2, 2)
        banda = tinta.banda_cuadricula(trabajo.shape, extremos, encuadre.ppmm)
    t = tinta.mascara(trabajo, encuadre.ppmm, banda)
    del banda
    avance(f"Tinta: {int(t.lineas.sum())} px de línea, {t.pliegues} tramos de pliegue borrados")

    semillas = list(semillas)
    if semillas:
        en_trabajo = encuadre.a_trabajo([(x, y) for _, x, y in semillas])
        semillas_trabajo = [(n, float(x), float(y)) for (n, _, _), (x, y) in zip(semillas, en_trabajo)]
    else:
        semillas_trabajo = []
    p = particion.particionar(t, encuadre.ppmm, semillas_trabajo)
    del t
    avance(f"Regiones: {p.estadisticas['nucleos']} núcleos, {len(semillas)} semillas,"
           f" {len(p.estadisticas['fusiones_sin_tinta'])} bolsillos unidos a su lote")

    red = particion.red_de_deslindes(p, encuadre.ppmm)
    estadisticas_particion = p.estadisticas
    del p
    avance(f"Red de deslindes: {red.estadisticas['aristas']} aristas"
           f" ({red.estadisticas['aristas_rectas']} rectas), {red.estadisticas['nodos']} nodos")

    a_pagina = lambda g: _transformar(g, encuadre)
    lotes = {n: a_pagina(g) for n, g in red.lotes.items()}
    sin_numero = [a_pagina(g) for g in red.sin_numero]
    # Una cara de una región de lote que el polígono dejó chica (un resto) no es un lote.
    mediana = float(np.median([g.area for g in lotes.values()])) if lotes else 0.0
    sin_numero_lote = [bool(es and g.area >= particion.LOTE_FRAC * mediana)
                       for es, g in zip(red.sin_numero_lote, sin_numero)]
    numeros = [str(n) for n, _, _ in semillas]
    faltantes = [n for n in numeros if n not in lotes]
    suma = sum(g.area for g in red.lotes.values())
    union = unary_union(list(red.lotes.values())) if red.lotes else Polygon()
    estadisticas = dict(
        particion=estadisticas_particion, red=red.estadisticas,
        lotes=len(lotes), semillas=len(semillas), faltantes=faltantes, sin_numero=len(sin_numero),
        sin_numero_lote=sum(sin_numero_lote),
        traslape_px=float(suma - union.area),
        segundos=round(time.time() - inicio, 1),
    )
    avance(f"Lotes: {len(lotes)} de {len(semillas)}"
           + (f"; sin polígono: {', '.join(faltantes)}" if faltantes else "")
           + (f"; {len(sin_numero)} caras sin número" if sin_numero else "")
           + (f", {sum(sin_numero_lote)} del tamaño de un lote" if any(sin_numero_lote) else ""))
    return Resultado(encuadre, lotes, sin_numero, red.lotes, estadisticas, detectada, sin_numero_lote)


def rectas_cuadricula(imagen: np.ndarray, ppmm: float, cuadricula: dict, avance=print):
    """Las rectas de la cuadrícula en la imagen, partiendo de la posición aproximada de
    cada línea. Devuelve (detectada, segmentos): `detectada` en el formato de
    `digitalizado.json` y los segmentos en px de página, para borrar su tinta.

    Cada recta guarda también la posición de la que se partió ("x" o "y"): así
    `georreferencia` sabe si son las rectas de la cuadrícula que se usa al ubicar."""
    gris = cv2.cvtColor(imagen, cv2.COLOR_RGB2GRAY)
    verticales, horizontales = cuadricula.get("verticales") or [], cuadricula.get("horizontales") or []
    xs = [float(v["x"]) for v in verticales]
    ys = [float(v["y"]) for v in horizontales]
    lineas = tinta.lineas_cuadricula(gris, ppmm, xs, ys)
    del gris
    # Las rectas detectadas (no la posición aproximada) son las que georreferencian.
    punto = lambda p: [round(float(p[0]), 3), round(float(p[1]), 3)]
    detectada = {familia: [{eje: posicion, "valor": m.get("valor"), "p": punto(p), "q": punto(q), "valida": bool(v)}
                           for posicion, m, (p, q, v) in zip(posiciones, marcas, trozo)]
                 for familia, eje, posiciones, marcas, trozo in (
                     ("verticales", "x", xs, verticales, lineas[:len(xs)]),
                     ("horizontales", "y", ys, horizontales, lineas[len(xs):]))}
    avance(f"Cuadrícula: {sum(v for *_, v in lineas)} de {len(lineas)} líneas bien ubicadas")
    return detectada, [(p, q) for p, q, _ in lineas]


def _transformar(g: Polygon, encuadre: pag.Encuadre) -> Polygon:
    exterior = encuadre.a_pagina(np.asarray(g.exterior.coords))
    huecos = [encuadre.a_pagina(np.asarray(h.coords)) for h in g.interiors]
    return Polygon(exterior, huecos)


def digitalizar(carpeta: Path, avance=print) -> dict:
    carpeta = Path(carpeta)
    entradas = leer_entradas(carpeta)
    numero, rotacion = entradas["pagina"], entradas["rotacion"]
    union = union_hojas.leer(entradas["union"]) if entradas["union"] else None
    if union is not None:
        imagen, ppmm = union_hojas.componer_desde_pdf(carpeta / entradas["pdf"], union)
        fuente = "union"
        avance(f"Hojas unidas {_lista([str(h.n) for h in union.hojas])}: {imagen.shape[1]}×{imagen.shape[0]} px,"
               f" {ppmm:.2f} px/mm")
    else:
        hoja = pag.extraer(carpeta / entradas["pdf"], numero)
        imagen = pag.rotar(hoja.imagen, rotacion)
        hoja.imagen = None
        ppmm, fuente = hoja.ppmm, hoja.fuente
        avance(f"Página {numero} de {hoja.paginas}: {imagen.shape[1]}×{imagen.shape[0]} px,"
               f" {ppmm:.2f} px/mm ({'imagen embebida' if fuente == 'embebida' else 'renderizada'}),"
               f" rotación {rotacion}°")
    huella_union = union_hojas.huella(union) if union is not None else None
    previo = _previo(carpeta, numero, rotacion, huella_union)
    usuario = [(s["numero"], s["x"], s["y"]) for s in entradas["semillas"]]
    lector = None
    if entradas["lector"]:
        lector = _leer_rotulos(carpeta, entradas, imagen, ppmm, previo, avance)
        poligonos = ([l["poligono"] for l in previo.get("lotes") or []]
                     + [c["poligono"] for c in previo.get("sin_numero") or []]) if previo else []
        cuadro = lector.get("cuadro") or {}
        # Sin el resto de la propiedad: su "8" haría pasar el "6-08" por un lote del cuadro.
        combinadas = rotulos.combinar(usuario, lector["rotulos"], RADIO_CORRECCION_MM * ppmm,
                                      entradas["lector_apoyo_min"], poligonos, numeros_lote.esperados(cuadro),
                                      [r for r in [numeros_lote.resto(cuadro)] if r])
    else:
        combinadas = rotulos.combinar(usuario, [], 0.0)
    del previo
    de_lector = sum(s["origen"] == "lector" for s in combinadas)
    avance(f"Semillas: {len(combinadas) - de_lector} de la loteadora y {de_lector} del lector"
           + (f" (apoyo ≥ {entradas['lector_apoyo_min']})" if lector else " (lector apagado)"))
    semillas = [(s["numero"], s["x"], s["y"]) for s in combinadas]
    r = digitalizar_imagen(imagen, ppmm, semillas, entradas.get("rectangulo"),
                           _mascaras(entradas), entradas.get("esquinas"),
                           entradas.get("marco_mm"), entradas.get("cuadricula"), avance)
    detectada = r.cuadricula
    propuesta = (lector or {}).get("cuadricula")
    if detectada is None and cuadricula_suficiente(propuesta):
        # La loteadora suele elegir la cuadrícula que propone el lector ya en Ubicar, sin
        # volver a digitalizar (no atrasa los lotes): se buscan sus rectas desde ya para
        # que ubicar mida el giro de la hoja. Su tinta no se borra: eso cambiaría los
        # lotes de una cuadrícula que nadie eligió.
        detectada, _ = rectas_cuadricula(imagen, ppmm, propuesta, avance)
    posicion = {s["numero"]: s for s in combinadas}
    cuadro = (lector or {}).get("cuadro") or {}
    # Faltantes son las semillas de la loteadora: un rótulo leído sin polígono suele
    # ser ruido (una cota, un número fuera del loteo) y va aparte.
    faltantes = [n for n in r.estadisticas["faltantes"] if posicion[n]["origen"] == "usuario"]
    sin_poligono = [n for n in r.estadisticas["faltantes"] if posicion[n]["origen"] == "lector"]
    r.estadisticas.update(faltantes=faltantes, semillas_lector=de_lector)
    sugerencias = _sugerencias(r.sin_numero, r.sin_numero_lote, (lector or {}).get("rotulos") or [],
                               entradas["lector_apoyo_min"], [s["numero"] for s in combinadas], cuadro)
    # Los números que hay: los lotes y lo que marcó ella (aunque no haya caído en un lote).
    # Un número del lector sin polígono suele ser ruido: no cuenta.
    presentes = list(r.lotes) + [s["numero"] for s in combinadas if s["origen"] == "usuario"]
    # Un hueco de la serie se dice solo junto a una cara sin número del tamaño de un lote
    # (sea "de lote" o tenga deslinde firme): ahí suele estar el que falta.
    mediana = float(np.median([g.area for g in r.lotes.values()])) if r.lotes else 0.0
    grandes = [c for c in r.sin_numero if c.area >= particion.LOTE_FRAC * mediana]
    junto = [n for n, g in r.lotes.items() if any(g.distance(c) <= 0.5 * ppmm for c in grandes)]
    huecos = numeros_lote.huecos(presentes, numeros_lote.esperados(cuadro), junto)
    if huecos:
        avance(f"Faltan en la numeración: {', '.join(huecos)}")
    datos = dict(
        pagina=dict(numero=numero, rotacion=rotacion, ancho=int(imagen.shape[1]), alto=int(imagen.shape[0]),
                    ppmm=ppmm, fuente=fuente, union=huella_union),
        trabajo=dict(ancho=int(r.encuadre.imagen.shape[1]), alto=int(r.encuadre.imagen.shape[0]),
                     ppmm=r.encuadre.ppmm, modo=r.encuadre.modo, homografia=r.encuadre.homografia.tolist()),
        lotes=[dict(numero=n, semilla=[posicion[n]["x"], posicion[n]["y"]], poligono=_anillo(g.exterior),
                    huecos=[_anillo(h) for h in g.interiors], area_px=round(g.area, 1),
                    vertices=len(g.exterior.coords) - 1, origen=posicion[n]["origen"],
                    confianza=posicion[n]["confianza"], apoyo=posicion[n]["apoyo"],
                    area_oficial=_area_oficial(cuadro, n))
               for n, g in r.lotes.items()],
        sin_numero=[dict(poligono=_anillo(g.exterior), area_px=round(g.area, 1), de_lote=es, sugerencia=sug)
                    for g, es, sug in zip(r.sin_numero, r.sin_numero_lote, sugerencias)],
        faltantes=faltantes,
        huecos=huecos,
        cuadricula=detectada,
        lector=_resumen_lector(lector, entradas, de_lector, sin_poligono),
        estadisticas=r.estadisticas,
    )
    escribir_json(carpeta / SALIDA, datos)
    # Recién ahora: si la instancia muere digitalizando los lotes (minutos en un plano
    # grande), la lectura se retoma entera del avance en vez de empezar de cero.
    shutil.rmtree(carpeta / AVANCE_LECTOR, ignore_errors=True)
    avance(f"Listo: {carpeta / SALIDA}")
    return datos


def _area_oficial(cuadro: dict, numero: str) -> float | None:
    """La del cuadro de superficies. El resto de la propiedad que ella llamó "Resto" (el
    cuadro no le daba número, o no se había leído) tiene la de la fila del resto."""
    if numeros_lote.es_resto(numero) and numeros_lote.resto(cuadro):
        return cuadro[numeros_lote.resto(cuadro)]
    return numeros_lote.buscar(cuadro, numero)


def _sugerencias(caras: list[Polygon], de_lote: list[bool], leidos, apoyo_min: int,
                 usados: list[str], cuadro=None) -> list[dict | None]:
    """Por cara sin número: lo que el lector leyó dentro con menos apoyo que `apoyo_min`
    (no alcanzó a ser semilla), si es un lote y el número no lo tiene ya otro. La mejor
    lectura (más apoyo, más confianza) va primero, y un número no se sugiere dos veces.
    La loteadora lo confirma con un clic.

    Con cuadro de superficies, el número se corrige con él (`numeros.segun_cuadro`) y lo
    que no está en el cuadro y es mayor que todos los suyos no se sugiere (la misma regla
    de `rotulos.combinar`): en Caminos de Rapel el lector leía "6-48" en 8-09."""
    from shapely.geometry import Point
    salida: list[dict | None] = [None] * len(caras)
    tomados = list(usados)
    oficiales = numeros_lote.esperados(cuadro or {})
    restos = [r for r in [numeros_lote.resto(cuadro or {})] if r]
    tope = max((numeros_lote.ultimo(n) or 0 for n in oficiales), default=None)
    for r in sorted((r for r in leidos if r.apoyo < apoyo_min), key=lambda r: (-r.apoyo, -r.confianza)):
        numero = numeros_lote.segun_cuadro(r.numero, oficiales)
        if (tope is not None and not any(numeros_lote.mismo_lote(numero, n) for n in oficiales)
                and (numeros_lote.ultimo(numero) or tope + 1) > tope):
            continue
        # El resto de la propiedad tampoco se sugiere: Numerar le pregunta si va al KMZ.
        if (numeros_lote.clave(numero) in map(numeros_lote.clave, restos)
                or any(numeros_lote.mismo_lote(numero, n, restos) for n in tomados)):
            continue
        for i, (cara, es) in enumerate(zip(caras, de_lote)):
            if es and salida[i] is None and cara.contains(Point(r.x, r.y)):
                salida[i] = dict(numero=numero, confianza=round(r.confianza, 4), apoyo=r.apoyo)
                tomados.append(numero)
                break
    return salida


def _mascaras(entradas: dict) -> list[list[float]]:
    """Lo que no es dibujo: las máscaras y el cuadro de superficies (si cae dentro del
    rectángulo del dibujo, sus números no son rótulos ni sus líneas deslindes). El de la
    unión (`union.cuadro`) no entra: está en px de su hoja, no de la unión, y lo que
    quede de él en la unión lo tapa el recorte o una máscara."""
    return list(entradas.get("mascaras") or []) + ([entradas["cuadro"]] if entradas.get("cuadro") else [])


def _lista(cosas: list[str]) -> str:
    return cosas[0] if len(cosas) == 1 else f"{', '.join(cosas[:-1])} y {cosas[-1]}"


def _previo(carpeta: Path, numero: int, rotacion: int, union: str | None = None) -> dict | None:
    """La digitalización anterior, si es de la misma página, rotación y unión de hojas
    (sus lotes dicen dónde corrigió la loteadora; sus lecturas se reusan). Con otra
    unión los px de página son otros: sus lotes caerían en cualquier parte."""
    try:
        d = json.loads((Path(carpeta) / SALIDA).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    p = d.get("pagina") or {}
    return d if (p.get("numero"), p.get("rotacion"), p.get("union")) == (numero, rotacion, union) else None


def huella_lector(carpeta: Path, entradas: dict) -> str:
    """Lo que cambia lo que lee el lector: el PDF, la página (o la unión de hojas y su
    cuadro), el dibujo y sus máscaras."""
    resumen = hashlib.sha1()
    with open(Path(carpeta) / entradas["pdf"], "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            resumen.update(trozo)
    datos = dict(pdf=resumen.hexdigest(), version=rotulos.VERSION,
                 **{k: entradas.get(k) for k in ("pagina", "rotacion", "rectangulo", "mascaras", "cuadro")})
    if entradas.get("union"):
        # Solo con unión: sin ella la huella queda la de siempre y los KMZ que ya
        # existen no vuelven a pasar por Tesseract. El cuadro va aparte porque
        # `union.huella` no lo incluye (no cambia la imagen, pero sí lo que se lee).
        u = union_hojas.leer(entradas["union"])
        datos["union"] = dict(huella=union_hojas.huella(u), cuadro=u.cuadro)
    texto = json.dumps(datos, sort_keys=True, default=str)
    return hashlib.sha1(texto.encode("utf-8")).hexdigest()[:16]


def _leer_rotulos(carpeta: Path, entradas: dict, imagen: np.ndarray, ppmm: float, previo: dict | None,
                  avance) -> dict:
    """Rótulos, cuadrícula y cuadro de la página, en px de página. Si la digitalización
    anterior leyó la misma página con el mismo dibujo, se reusa: corregir un número y
    digitalizar de nuevo no vuelve a pasar por Tesseract."""
    huella = huella_lector(carpeta, entradas)
    anterior = (previo or {}).get("lector") or {}
    if anterior.get("disponible") and anterior.get("huella") == huella:
        avance("Lector: se reusan las lecturas de la digitalización anterior")
        return dict(anterior, rotulos=[rotulos.Rotulo(**r) for r in anterior.get("rotulos") or []])
    motivo = rotulos.motivo_no_disponible()
    if motivo:
        avance(motivo)
        return dict(disponible=False, motivo=motivo, huella=None, rotulos=[], cuadricula=None, cuadro={},
                    segundos=0.0)
    inicio = time.time()
    # El avance por pasada, para retomar si la instancia muere a mitad. Otra huella es
    # otro dibujo: lo guardado de antes ya no sirve.
    avances = Path(carpeta) / AVANCE_LECTOR
    if avances.is_dir():
        for vieja in avances.iterdir():
            if vieja.name != huella:
                shutil.rmtree(vieja, ignore_errors=True)
    rect = entradas.get("rectangulo") or [0, 0, imagen.shape[1], imagen.shape[0]]
    x0, y0, x1, y1 = pag._rect_entero(rect, imagen.shape)
    # El dibujo con las máscaras tapadas (los cuadros y el cajetín traen números que no
    # son lotes), en la resolución de la página: el texto chico no aguanta remuestreo.
    dibujo = pag.tapar(imagen[y0:y1, x0:x1], [[m[0] - x0, m[1] - y0, m[2] - x0, m[3] - y0]
                                             for m in _mascaras(entradas)],
                       pag.color_papel(imagen, rect))
    leidos = [replace(r, x=r.x + x0, y=r.y + y0)
              for r in rotulos.leer(dibujo, ppmm, avance, avance_en=avances / huella)]
    del dibujo
    # Siempre, aunque la loteadora ya haya dado la cuadrícula: así aceptar la propuesta
    # (que cambia las entradas) no obliga a leer todo de nuevo. Son solo franjas.
    cuadricula = rotulos.leer_cuadricula(imagen, ppmm, avance, rectangulo=[x0, y0, x1, y1])
    cuadro = _leer_cuadro(carpeta, entradas, imagen, avance)
    # Sin ningún rótulo no se guarda la huella: lo más probable es que el lector haya
    # fallado (memoria, tiempo) y `leer` devuelve vacío en vez de caerse. Si se
    # guardara, digitalizar de nuevo reusaría ese vacío para siempre.
    return dict(disponible=True, motivo=None, huella=huella if leidos else None, rotulos=leidos,
                cuadricula=cuadricula,
                cuadro=cuadro, segundos=round(time.time() - inicio, 1))


def _leer_cuadro(carpeta: Path, entradas: dict, imagen: np.ndarray, avance) -> dict[str, float]:
    """El cuadro de superficies. El marcado se lee de la página entera, aunque esté fuera
    del dibujo. Con la unión se lee de su hoja original, girada como va en la unión: el
    recorte de cada hoja suele dejarlo fuera de la unión, y su rectángulo está en px de
    esa hoja. Sin cuadro marcado se prueba cada máscara de la página (o de la unión)."""
    marcado = (entradas.get("union") or {}).get("cuadro")
    if marcado:
        if rotulos.motivo_no_disponible():
            return {}
        hoja = next(h for h in entradas["union"]["hojas"] if h["n"] == marcado["hoja"])
        # Solo el trozo del cuadro, girado como vista y copiado: la hoja entera girada
        # sería otra copia de la hoja al lado de la unión, que sigue en memoria.
        girada = np.rot90(pag.extraer(Path(carpeta) / entradas["pdf"], hoja["n"]).imagen,
                          k=-pag._cuartos(hoja["rotacion"]))
        alto, ancho = girada.shape[:2]
        x0, y0, x1, y1 = (int(round(v)) for v in marcado["rect"])
        x0, x1, y0, y1 = max(0, x0), min(ancho, x1), max(0, y0), min(alto, y1)
        trozo = np.ascontiguousarray(girada[y0:max(y0, y1), x0:max(x0, x1)])
        del girada
        return rotulos.leer_cuadro(trozo, [[0, 0, trozo.shape[1], trozo.shape[0]]], avance)
    return rotulos.leer_cuadro(imagen, [entradas["cuadro"]] if entradas.get("cuadro")
                               else entradas.get("mascaras") or [], avance)


def _resumen_lector(lector: dict | None, entradas: dict, semillas: int, sin_poligono: list[str]) -> dict:
    if lector is None:
        return dict(activo=False)
    return dict(activo=True, disponible=lector["disponible"], motivo=lector.get("motivo"),
                huella=lector.get("huella"), rotulos=[r.como_dict() for r in lector["rotulos"]],
                apoyo_min=entradas["lector_apoyo_min"], semillas=semillas, sin_poligono=sin_poligono,
                cuadricula=lector.get("cuadricula"), cuadro=lector.get("cuadro") or {},
                segundos=lector.get("segundos"))


def leer_entradas(carpeta: Path) -> dict:
    """`entradas.json` revisado y normalizado. Un error dice qué clave está mal, para
    que la consola se lo muestre a la loteadora."""
    try:
        e = json.loads((Path(carpeta) / ENTRADAS).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{ENTRADAS} no es un JSON válido: {error}") from None
    if not isinstance(e, dict):
        raise ValueError(f"{ENTRADAS} debe ser un objeto")

    def numeros(valor, cuantos, clave):
        if (not isinstance(valor, (list, tuple)) or len(valor) != cuantos
                or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in valor)):
            raise ValueError(f"«{clave}» debe ser una lista de {cuantos} números, no {valor!r}")
        return [float(v) for v in valor]

    def entero(clave, defecto):
        valor = e.get(clave, defecto)
        if not isinstance(valor, int) or isinstance(valor, bool):
            raise ValueError(f"«{clave}» debe ser un número entero, no {valor!r}")
        return valor

    salida = dict(e)
    salida["pdf"] = str(e.get("pdf") or "plano.pdf")
    salida["union"] = None
    if e.get("union") is not None:
        # Solo la forma: las páginas y sus tamaños los revisa la consola contra el PDF,
        # y lo que se escape lo dice `componer_desde_pdf` al extraer.
        salida["union"] = union_hojas.leer(e["union"]).a_dic()
    salida["pagina"] = entero("pagina", 0 if salida["union"] else 1)
    salida["rotacion"] = entero("rotacion", 0)
    if salida["union"]:
        if salida["pagina"] != 0:
            raise ValueError(f"con las hojas unidas, «pagina» es 0 (la unión), no {salida['pagina']}")
        if salida["rotacion"] != 0:
            raise ValueError(f"con las hojas unidas, «rotacion» es 0 (cada hoja lleva su giro),"
                             f" no {salida['rotacion']}")
        if e.get("cuadro") is not None:
            raise ValueError("con las hojas unidas, el cuadro de superficies va en «union.cuadro»"
                             " (en px de su hoja), no en «cuadro»")
    elif salida["pagina"] == 0:
        raise ValueError("«pagina» 0 es la unión de hojas, y no hay hojas unidas: elige una página del PDF")
    if e.get("rectangulo") is not None:
        x0, y0, x1, y1 = salida["rectangulo"] = numeros(e["rectangulo"], 4, "rectangulo")
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"el rectángulo del dibujo está vacío: {e['rectangulo']}")
    salida["mascaras"] = [numeros(m, 4, "mascaras[]") for m in e.get("mascaras") or []]
    if e.get("esquinas") is not None:
        if not isinstance(e["esquinas"], list) or len(e["esquinas"]) != 4:
            raise ValueError("«esquinas» son las 4 esquinas del marco, [[x, y] × 4]")
        salida["esquinas"] = [numeros(p, 2, "esquinas[]") for p in e["esquinas"]]
    if e.get("marco_mm") is not None:
        salida["marco_mm"] = numeros(e["marco_mm"], 2, "marco_mm")
    semillas = []
    for s in e.get("semillas") or []:
        if not isinstance(s, dict) or s.get("numero") in (None, ""):
            raise ValueError(f"cada semilla lleva «numero», «x» e «y»: {s!r}")
        x, y = numeros([s.get("x"), s.get("y")], 2, f"semilla {s['numero']}: x, y")
        semillas.append(dict(s, numero=str(s["numero"]), x=x, y=y))
    # Antes de extraer la página: así el error llega en un segundo y no al final.
    # Repetidos por número normalizado: "8-01" y "8-1" son el mismo lote.
    repetidos = numeros_lote.repetidos(s["numero"] for s in semillas)
    if repetidos:
        raise ValueError(f"números de lote repetidos en las semillas: {', '.join(repetidos)}")
    salida["semillas"] = semillas
    lector = e.get("lector", True)
    if not isinstance(lector, bool):
        raise ValueError(f"«lector» es true o false, no {lector!r}")
    salida["lector"] = lector
    salida["lector_apoyo_min"] = entero("lector_apoyo_min", rotulos.APOYO_MIN)
    if salida["lector_apoyo_min"] < 1:
        raise ValueError(f"«lector_apoyo_min» es 1 o más, no {salida['lector_apoyo_min']}")
    if e.get("cuadro") is not None:
        x0, y0, x1, y1 = salida["cuadro"] = numeros(e["cuadro"], 4, "cuadro")
        if x1 <= x0 or y1 <= y0:
            raise ValueError(f"el rectángulo del cuadro de superficies está vacío: {e['cuadro']}")

    if e.get("cuadricula") is not None:
        c = e["cuadricula"]
        if not isinstance(c, dict):
            raise ValueError("«cuadricula» es {\"verticales\": [...], \"horizontales\": [...]}")
        for familia, eje in (("verticales", "x"), ("horizontales", "y")):
            for m in c.get(familia) or []:
                if not isinstance(m, dict):
                    raise ValueError(f"cada línea de «cuadricula.{familia}» lleva «{eje}» y «valor»: {m!r}")
                numeros([m.get(eje)] + ([m["valor"]] if m.get("valor") is not None else []),
                        2 if m.get("valor") is not None else 1, f"cuadricula.{familia}: {eje}, valor")
        if c.get("epsg") is not None and (not isinstance(c["epsg"], int) or isinstance(c["epsg"], bool)):
            raise ValueError(f"«cuadricula.epsg» debe ser un número entero, no {c['epsg']!r}")
    anclas = []
    for i, a in enumerate(e.get("anclas") or []):
        if not isinstance(a, dict):
            raise ValueError(f"cada ancla lleva «x», «y», «lon» y «lat»: {a!r}")
        nombre = str(a.get("nombre") or f"ancla {i + 1}")
        x, y, lon, lat = numeros([a.get(k) for k in ("x", "y", "lon", "lat")], 4, f"{nombre}: x, y, lon, lat")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"{nombre}: lon/lat fuera de rango ({lon}, {lat})")
        anclas.append(dict(a, nombre=nombre, x=x, y=y, lon=lon, lat=lat))
    salida["anclas"] = anclas
    if "ubicacion" in e:
        # Sin la clave no se agrega: unas entradas de antes quedan iguales (y su huella).
        salida["ubicacion"] = _ubicacion(e["ubicacion"])
    if e.get("escala_cuadro") is not None:
        # Sin la clave (o null) no se agrega: las entradas de antes quedan iguales, y su huella.
        if not isinstance(e["escala_cuadro"], bool):
            raise ValueError(f"«escala_cuadro» es true o false, no {e['escala_cuadro']!r}")
        salida["escala_cuadro"] = e["escala_cuadro"]
    fuera = e.get("fuera") or []
    if not isinstance(fuera, list):
        raise ValueError(f"«fuera» es una lista de puntos [[x, y]], no {fuera!r}")
    salida["fuera"] = [numeros(f, 2, "fuera[]") for f in fuera]
    ajuste = e.get("ajuste") or {}
    if not isinstance(ajuste, dict):
        raise ValueError(f"«ajuste» es {{\"de\": metros, \"dn\": metros}}, no {ajuste!r}")
    de, dn = numeros([ajuste.get("de", 0.0), ajuste.get("dn", 0.0)], 2, "ajuste: de, dn")
    salida["ajuste"] = dict(de=de, dn=dn)
    return salida


# La escala impresa de un plano de loteo va de 1:500 a 1:50.000; con holgura, lo que
# está fuera de esto es un error de tipeo (p. ej. 5 por 5.000).
ESCALA_IMPRESA_MIN, ESCALA_IMPRESA_MAX = 100, 1_000_000


def _ubicacion(u) -> dict | None:
    """`ubicacion` revisada. Cada parte es opcional (se arma de a poco en la pantalla),
    pero lo que viene tiene que ser un número que sirva."""
    if u is None:
        return None
    if not isinstance(u, dict):
        raise ValueError(f"«ubicacion» es {{\"x\", \"y\", \"lon\", \"lat\", \"giro\"}}, no {u!r}")
    salida = {}
    for clave in ("x", "y", "lon", "lat", "giro"):
        valor = u.get(clave)
        if valor is None:
            continue
        if not isinstance(valor, (int, float)) or isinstance(valor, bool) or not math.isfinite(valor):
            raise ValueError(f"«ubicacion.{clave}» debe ser un número, no {valor!r}")
        salida[clave] = float(valor)
    if "lon" in salida and not -180 <= salida["lon"] <= 180 or "lat" in salida and not -90 <= salida["lat"] <= 90:
        raise ValueError(f"la coordenada está fuera de rango ({salida.get('lon')}, {salida.get('lat')})")
    if not -180 <= salida.get("giro", 0.0) <= 180:
        raise ValueError(f"el giro va de −180 a 180 grados, no {salida['giro']}")
    escala = u.get("escala_impresa")
    if escala is not None:
        if (not isinstance(escala, (int, float)) or isinstance(escala, bool) or not math.isfinite(escala)
                or escala != int(escala)):
            raise ValueError(f"la escala del plano es un número entero (1:5.000 → 5000), no {escala!r}")
        if not ESCALA_IMPRESA_MIN <= escala <= ESCALA_IMPRESA_MAX:
            raise ValueError(f"la escala del plano 1:{int(escala)} no parece real: revísala (por ejemplo 1:5.000)")
        salida["escala_impresa"] = int(escala)
    else:
        salida["escala_impresa"] = None
    salida.setdefault("giro", 0.0)
    return salida


def _anillo(anillo) -> list[list[float]]:
    return [[round(x, 2), round(y, 2)] for x, y in anillo.coords]


def escribir_json(destino: Path, datos) -> None:
    """Se escribe aparte y se cambia de nombre al final: quien lo lea mientras se
    escribe ve el anterior completo. Sin copystat: los datos pueden vivir en un
    bucket montado (gcsfuse), que no deja cambiar permisos ni fechas."""
    temporal = destino.with_name(f".{destino.name}.{os.getpid()}")
    try:
        temporal.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":"), default=str),
                            encoding="utf-8")
        os.replace(temporal, destino)
    finally:
        temporal.unlink(missing_ok=True)
