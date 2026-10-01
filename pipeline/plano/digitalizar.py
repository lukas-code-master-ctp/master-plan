"""Digitalizar un plano: de `entradas.json` a `digitalizado.json`.

    python -m pipeline.plano digitalizar <carpeta-del-plano>

Imprime una línea por etapa: la consola muestra la salida en vivo.

`<carpeta>/entradas.json` (lo que aporta la loteadora; `anclas` y `ajuste` son de
`georreferenciar` y aquí solo se revisan):

    {
      "pdf": "plano.pdf",              ruta relativa a la carpeta
      "pagina": 1,                     desde 1
      "rotacion": 0,                   grados en sentido horario: 0, 90, 180 o 270
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
      "cuadro": null,                  [x0, y0, x1, y1] del cuadro de superficies; sin
                                       él se prueba cada máscara
      "anclas": [{"nombre": "roja", "x": 2533, "y": 8037,       punto del plano ↔ su lon/lat
                  "lon": -70.8240, "lat": -34.7240}],           WGS84 en grados decimales
      "ajuste": {"de": 0.0, "dn": 0.0}  traslación fina en metros (este, norte)
    }

Todas las coordenadas van en **píxeles de página**: la imagen que trae el PDF, ya
girada según `rotacion` (lo que ve la loteadora), con el centro del píxel en el
entero. Si cambia la rotación, cambian las coordenadas.

`<carpeta>/digitalizado.json`:

    {
      "pagina": {"numero", "rotacion", "ancho", "alto", "ppmm", "fuente"},
      "trabajo": {"ancho", "alto", "ppmm", "modo", "homografia"},   página -> trabajo (3×3)
      "lotes": [{"numero", "semilla": [x, y], "poligono": [[x, y], ...],
                 "huecos": [[[x, y], ...]], "area_px", "vertices",
                 "origen": "usuario" | "lector",   de dónde salió el número
                 "confianza", "apoyo",             del lector (null si lo marcó ella)
                 "area_oficial"}],                 m² del cuadro de superficies (o null)
                                                   todo en px de página
      "sin_numero": [{"poligono", "area_px"}],     caras dentro del contorno sin lote
      "faltantes": ["13"],                         semillas de la loteadora sin polígono
      "cuadricula": {"verticales": [{"valor", "p": [x, y], "q": [x, y], "valida"}],
                     "horizontales": [...]},       las rectas detectadas (o null)
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
import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

import cv2
import numpy as np
from shapely.geometry import Polygon
from shapely.ops import unary_union

from . import pagina as pag
from . import particion, rotulos, tinta

ENTRADAS = "entradas.json"
SALIDA = "digitalizado.json"

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
        gris = cv2.cvtColor(imagen, cv2.COLOR_RGB2GRAY)
        verticales, horizontales = cuadricula.get("verticales") or [], cuadricula.get("horizontales") or []
        xs = [float(v["x"]) for v in verticales]
        ys = [float(v["y"]) for v in horizontales]
        lineas = tinta.lineas_cuadricula(gris, ppmm, xs, ys)
        del gris
        segmentos = [(p, q) for p, q, _ in lineas]
        # Las rectas detectadas (no la posición aproximada) son las que georreferencian.
        punto = lambda p: [round(float(p[0]), 3), round(float(p[1]), 3)]
        detectada = {familia: [dict(valor=m.get("valor"), p=punto(p), q=punto(q), valida=bool(v))
                               for m, (p, q, v) in zip(marcas, trozo)]
                     for familia, marcas, trozo in (("verticales", verticales, lineas[:len(xs)]),
                                                    ("horizontales", horizontales, lineas[len(xs):]))}
        avance(f"Cuadrícula: {sum(v for *_, v in lineas)} de {len(lineas)} líneas bien ubicadas")

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
    numeros = [str(n) for n, _, _ in semillas]
    faltantes = [n for n in numeros if n not in lotes]
    suma = sum(g.area for g in red.lotes.values())
    union = unary_union(list(red.lotes.values())) if red.lotes else Polygon()
    estadisticas = dict(
        particion=estadisticas_particion, red=red.estadisticas,
        lotes=len(lotes), semillas=len(semillas), faltantes=faltantes, sin_numero=len(sin_numero),
        traslape_px=float(suma - union.area),
        segundos=round(time.time() - inicio, 1),
    )
    avance(f"Lotes: {len(lotes)} de {len(semillas)}"
           + (f"; sin polígono: {', '.join(faltantes)}" if faltantes else "")
           + (f"; {len(sin_numero)} caras sin número" if sin_numero else ""))
    return Resultado(encuadre, lotes, sin_numero, red.lotes, estadisticas, detectada)


def _transformar(g: Polygon, encuadre: pag.Encuadre) -> Polygon:
    exterior = encuadre.a_pagina(np.asarray(g.exterior.coords))
    huecos = [encuadre.a_pagina(np.asarray(h.coords)) for h in g.interiors]
    return Polygon(exterior, huecos)


def digitalizar(carpeta: Path, avance=print) -> dict:
    carpeta = Path(carpeta)
    entradas = leer_entradas(carpeta)
    numero, rotacion = entradas["pagina"], entradas["rotacion"]
    hoja = pag.extraer(carpeta / entradas["pdf"], numero)
    imagen = pag.rotar(hoja.imagen, rotacion)
    hoja.imagen = None
    avance(f"Página {numero} de {hoja.paginas}: {imagen.shape[1]}×{imagen.shape[0]} px,"
           f" {hoja.ppmm:.2f} px/mm ({'imagen embebida' if hoja.fuente == 'embebida' else 'renderizada'}),"
           f" rotación {rotacion}°")
    previo = _previo(carpeta, numero, rotacion)
    usuario = [(s["numero"], s["x"], s["y"]) for s in entradas["semillas"]]
    lector = None
    if entradas["lector"]:
        lector = _leer_rotulos(carpeta, entradas, imagen, hoja.ppmm, previo, avance)
        poligonos = ([l["poligono"] for l in previo.get("lotes") or []]
                     + [c["poligono"] for c in previo.get("sin_numero") or []]) if previo else []
        combinadas = rotulos.combinar(usuario, lector["rotulos"], RADIO_CORRECCION_MM * hoja.ppmm,
                                      entradas["lector_apoyo_min"], poligonos, lector.get("cuadro") or {})
    else:
        combinadas = rotulos.combinar(usuario, [], 0.0)
    del previo
    de_lector = sum(s["origen"] == "lector" for s in combinadas)
    avance(f"Semillas: {len(combinadas) - de_lector} de la loteadora y {de_lector} del lector"
           + (f" (apoyo ≥ {entradas['lector_apoyo_min']})" if lector else " (lector apagado)"))
    semillas = [(s["numero"], s["x"], s["y"]) for s in combinadas]
    r = digitalizar_imagen(imagen, hoja.ppmm, semillas, entradas.get("rectangulo"),
                           entradas.get("mascaras") or [], entradas.get("esquinas"),
                           entradas.get("marco_mm"), entradas.get("cuadricula"), avance)
    posicion = {s["numero"]: s for s in combinadas}
    cuadro = (lector or {}).get("cuadro") or {}
    # Faltantes son las semillas de la loteadora: un rótulo leído sin polígono suele
    # ser ruido (una cota, un número fuera del loteo) y va aparte.
    faltantes = [n for n in r.estadisticas["faltantes"] if posicion[n]["origen"] == "usuario"]
    sin_poligono = [n for n in r.estadisticas["faltantes"] if posicion[n]["origen"] == "lector"]
    r.estadisticas.update(faltantes=faltantes, semillas_lector=de_lector)
    datos = dict(
        pagina=dict(numero=numero, rotacion=rotacion, ancho=int(imagen.shape[1]), alto=int(imagen.shape[0]),
                    ppmm=hoja.ppmm, fuente=hoja.fuente),
        trabajo=dict(ancho=int(r.encuadre.imagen.shape[1]), alto=int(r.encuadre.imagen.shape[0]),
                     ppmm=r.encuadre.ppmm, modo=r.encuadre.modo, homografia=r.encuadre.homografia.tolist()),
        lotes=[dict(numero=n, semilla=[posicion[n]["x"], posicion[n]["y"]], poligono=_anillo(g.exterior),
                    huecos=[_anillo(h) for h in g.interiors], area_px=round(g.area, 1),
                    vertices=len(g.exterior.coords) - 1, origen=posicion[n]["origen"],
                    confianza=posicion[n]["confianza"], apoyo=posicion[n]["apoyo"],
                    area_oficial=cuadro.get(n))
               for n, g in r.lotes.items()],
        sin_numero=[dict(poligono=_anillo(g.exterior), area_px=round(g.area, 1)) for g in r.sin_numero],
        faltantes=faltantes,
        cuadricula=r.cuadricula,
        lector=_resumen_lector(lector, entradas, de_lector, sin_poligono),
        estadisticas=r.estadisticas,
    )
    escribir_json(carpeta / SALIDA, datos)
    avance(f"Listo: {carpeta / SALIDA}")
    return datos


def _previo(carpeta: Path, numero: int, rotacion: int) -> dict | None:
    """La digitalización anterior, si es de la misma página y rotación (sus lotes dicen
    dónde corrigió la loteadora; sus lecturas se reusan)."""
    try:
        d = json.loads((Path(carpeta) / SALIDA).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    p = d.get("pagina") or {}
    return d if (p.get("numero"), p.get("rotacion")) == (numero, rotacion) else None


def huella_lector(carpeta: Path, entradas: dict) -> str:
    """Lo que cambia lo que lee el lector: el PDF, la página, el dibujo y sus máscaras."""
    resumen = hashlib.sha1()
    with open(Path(carpeta) / entradas["pdf"], "rb") as f:
        for trozo in iter(lambda: f.read(1 << 20), b""):
            resumen.update(trozo)
    datos = dict(pdf=resumen.hexdigest(), version=rotulos.VERSION,
                 **{k: entradas.get(k) for k in ("pagina", "rotacion", "rectangulo", "mascaras", "cuadro")})
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
    rect = entradas.get("rectangulo") or [0, 0, imagen.shape[1], imagen.shape[0]]
    x0, y0, x1, y1 = pag._rect_entero(rect, imagen.shape)
    # El dibujo con las máscaras tapadas (los cuadros y el cajetín traen números que no
    # son lotes), en la resolución de la página: el texto chico no aguanta remuestreo.
    dibujo = pag.tapar(imagen[y0:y1, x0:x1], [[m[0] - x0, m[1] - y0, m[2] - x0, m[3] - y0]
                                             for m in entradas.get("mascaras") or []],
                       pag.color_papel(imagen, rect))
    leidos = [replace(r, x=r.x + x0, y=r.y + y0) for r in rotulos.leer(dibujo, ppmm, avance)]
    del dibujo
    # Siempre, aunque la loteadora ya haya dado la cuadrícula: así aceptar la propuesta
    # (que cambia las entradas) no obliga a leer todo de nuevo. Son solo franjas.
    cuadricula = rotulos.leer_cuadricula(imagen, ppmm, avance, rectangulo=[x0, y0, x1, y1])
    cuadro = rotulos.leer_cuadro(imagen, [entradas["cuadro"]] if entradas.get("cuadro")
                                 else entradas.get("mascaras") or [], avance)
    # Sin ningún rótulo no se guarda la huella: lo más probable es que el lector haya
    # fallado (memoria, tiempo) y `leer` devuelve vacío en vez de caerse. Si se
    # guardara, digitalizar de nuevo reusaría ese vacío para siempre.
    return dict(disponible=True, motivo=None, huella=huella if leidos else None, rotulos=leidos,
                cuadricula=cuadricula,
                cuadro=cuadro, segundos=round(time.time() - inicio, 1))


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
    salida["pagina"] = entero("pagina", 1)
    salida["rotacion"] = entero("rotacion", 0)
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
    repetidos = sorted({s["numero"] for s in semillas if sum(t["numero"] == s["numero"] for t in semillas) > 1})
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
    ajuste = e.get("ajuste") or {}
    if not isinstance(ajuste, dict):
        raise ValueError(f"«ajuste» es {{\"de\": metros, \"dn\": metros}}, no {ajuste!r}")
    de, dn = numeros([ajuste.get("de", 0.0), ajuste.get("dn", 0.0)], 2, "ajuste: de, dn")
    salida["ajuste"] = dict(de=de, dn=dn)
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
