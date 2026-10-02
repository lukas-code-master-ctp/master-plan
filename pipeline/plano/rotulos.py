"""Lector de rótulos: los números de lote, las marcas de la cuadrícula UTM y el cuadro
de superficies, leídos con Tesseract.

Es el método medido en la tarea 1 (`docs/specs/2026-10-01-crea-tu-kmz-rotulos.md`,
scripts en `trabajo_crea_kmz/rotulos/`), con los mismos parámetros **globales**.
Detrás de una interfaz fija, para cambiar de lector (un modelo de visión) sin tocar
`digitalizar`:

    leer(imagen, ppmm)            -> [Rotulo(numero, x, y, confianza, apoyo, alto)]
    leer_cuadricula(imagen, ppmm) -> {"verticales": [{"x", "valor"}],
                                      "horizontales": [{"y", "valor"}], "epsg": None} | None
    leer_cuadro(imagen, rects)    -> {"12": area_m2, ...}

Las posiciones van en **píxeles de la imagen que se entrega**. `digitalizar` le pasa
recortes de la página (ya girada) y suma el origen del recorte: lo que sale de allí va
en píxeles de página, como las semillas de `entradas.json`.

Sin el ejecutable `tesseract` (o sin `pytesseract`) cada función avisa una línea y
devuelve vacío: digitalizar sigue con las semillas de la loteadora. Un error de
Tesseract en una pasada se salta esa pasada; nunca se cae el trabajo por el lector.

Costo: 96 pasadas por plano (24 ángulos × 2 escalas × gris/Otsu). Corren en hebras,
tantas como núcleos (`LECTOR_HEBRAS` lo acota): el trabajo pesado es el subproceso
`tesseract`, con `OMP_THREAD_LIMIT=1` (sin eso las pasadas en paralelo se estorban y
un plano tarda más de 10 min en vez de 1).
"""
from __future__ import annotations

import os
import re
import shutil
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from math import gcd, hypot

import cv2
import numpy as np

from .numeros import mismo_lote, ultimo

# Una hebra por proceso de Tesseract: las pasadas ya corren en paralelo. Antes de
# lanzar el primer subproceso (lo heredan).
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

# Cambia si cambia el método: invalida las lecturas guardadas en digitalizado.json.
# 2: el número es el rótulo completo ("8-01"), no el último número.
# 3: el cuadro de superficies lee "8-01" y la unidad ("5.000 m2").
VERSION = 3

SIN_LECTOR = "sin lector de rótulos: tesseract no está instalado"

# --- números de lote (parámetros globales de la tarea 1) -------------------------------
CFG_ROTULOS = "--oem 1 --psm 11 -c tessedit_char_whitelist=LOTE0123456789-,."
PASO_GRADOS = 15          # 30° pierde los rótulos diagonales (Hidango cae a 24 %)
ALTO_TEXTO_PX = 24.0      # el texto modal se lleva a este alto
ESCALA_GRANDE = 2.5       # segunda escala, 2,5× más chica, para los rótulos grandes
MIN_LECTURAS_LOTE = 10    # con tantas lecturas "LOTE…", solo cuentan esas
ALTO_SUELTO = 1.4         # sin "LOTE", un número suelto debe medir esto × el texto modal
RADIO_ALTOS = 3.0         # radio de agrupación = esto × el alto mediano del rótulo
APOYO_MIN = 2             # lo que `digitalizar` toma como semilla (apoyo ≥ 2: precisión)
TIMEOUT_PASADA_S = 600
# Memoria de una pasada por píxel de la imagen que se le da (Tesseract ~4,4 MB/Mpx más
# las copias de Python): con 16 pasadas a la vez, Algarrobo llegó a 9,2 GB.
BYTES_POR_PIXEL = 6.0

# --- cuadrícula y cuadro -----------------------------------------------------------------
CFG_CUADRICULA = "--oem 1 --psm 11 -c tessedit_char_whitelist=EN0123456789-"
TOLERANCIA_CUADRICULA_MM = 3.0   # una marca se aparta a lo más esto de la recta valor→píxel
SEPARACION_CUADRICULA_MM = 10.0  # dos líneas vecinas de la cuadrícula están al menos así de lejos
BANDA_CUADRICULA_MM = 30.0       # las marcas se buscan a ± esto del borde del dibujo
PASO_MINIMO_M = 50               # la progresión de la cuadrícula va de a 50 m o más
MIN_VALORES_CUADRICULA = 3
ALTO_TABLA_PX = 22.0             # el texto del cuadro se lleva a este alto (×2 en Algarrobo)
MIN_FILAS_CUADRO = 3
# Las cifras, el guion de "8-01" y las letras de la unidad ("m2", "hás"): sin la "m",
# Tesseract lee "5.000 m2" como "5.0002" (Caminos de Rapel no daba ninguna fila).
CFG_CUADRO = "--oem 1 --psm {} -c tessedit_char_whitelist=0123456789,.-mhas"


@dataclass(frozen=True)
class Rotulo:
    numero: str
    x: float
    y: float
    confianza: float      # apoyo / pasadas (0–1)
    apoyo: int = 1        # cuántas pasadas (escala, ángulo, variante) lo leyeron
    alto: float = 0.0     # alto del texto leído, px

    def como_dict(self) -> dict:
        d = asdict(self)
        d.update(x=round(self.x, 2), y=round(self.y, 2), confianza=round(self.confianza, 4),
                 alto=round(self.alto, 1))
        return d


# ------------------------------------------------------------------------- disponibilidad
def motivo_no_disponible() -> str | None:
    """None si se puede leer; si no, la línea que se muestra."""
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return "sin lector de rótulos: falta pytesseract"
    if shutil.which("tesseract") is None:
        return SIN_LECTOR
    return None


def disponible() -> bool:
    return motivo_no_disponible() is None


def memoria_libre() -> int | None:
    """Bytes que quedan para el lector: el límite del contenedor (cgroup v2) menos lo
    usado o, si no hay límite, MemAvailable. None si no se sabe (Windows)."""
    try:
        limite = open("/sys/fs/cgroup/memory.max").read().strip()
        if limite != "max":
            return int(limite) - int(open("/sys/fs/cgroup/memory.current").read())
    except (OSError, ValueError):
        pass
    try:
        for linea in open("/proc/meminfo"):
            if linea.startswith("MemAvailable:"):
                return int(linea.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return None


def _leer_archivo(ruta: str) -> str | None:
    try:
        with open(ruta) as f:
            return f.read().strip()
    except OSError:
        return None


def nucleos() -> int:
    """Los núcleos que de verdad tiene el proceso. En un contenedor `os.cpu_count()` da
    los del host (16 en vez de los 2 de Cloud Run): se acota por la afinidad y por la
    cuota de CPU del cgroup (v2 `cpu.max`, v1 `cpu.cfs_quota_us`)."""
    try:
        n = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        n = os.cpu_count() or 1
    cuota = None
    v2 = _leer_archivo("/sys/fs/cgroup/cpu.max")
    if v2:
        partes = v2.split()
        if len(partes) == 2 and partes[0] != "max":
            try:
                cuota = int(partes[0]) / int(partes[1])
            except (ValueError, ZeroDivisionError):
                pass
    else:
        q, p = _leer_archivo("/sys/fs/cgroup/cpu/cpu.cfs_quota_us"), _leer_archivo("/sys/fs/cgroup/cpu/cpu.cfs_period_us")
        try:
            if q and p and int(q) > 0:
                cuota = int(q) / int(p)
        except (ValueError, ZeroDivisionError):
            pass
    if cuota:
        n = min(n, max(1, int(cuota + 0.5)))
    return max(1, n)


def _hebras(hebras: int | None, trabajos: int, pixeles_por_pasada: float = 0) -> int:
    """Cuántas pasadas a la vez: tantas como núcleos del contenedor (`LECTOR_HEBRAS` lo
    acota) y que quepan en la memoria (cada pasada pide ~BYTES_POR_PIXEL por píxel de su
    imagen). Más hebras que núcleos no acelera Tesseract y sí multiplica la memoria."""
    tope = nucleos()
    try:
        tope = min(tope, int(os.environ.get("LECTOR_HEBRAS") or tope))
    except ValueError:
        pass
    libre = memoria_libre()
    if libre is not None and pixeles_por_pasada > 0:
        tope = min(tope, int(0.7 * libre / (BYTES_POR_PIXEL * pixeles_por_pasada)))
    return max(1, min(trabajos, hebras or tope, tope))


# ------------------------------------------------------------------------- imagen
def gris_normalizado(rgb: np.ndarray) -> np.ndarray:
    """Luminancia dividida por el fondo (quita sombras de foto y escaneo pálido)."""
    g = (cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) if rgb.ndim == 3 else rgb).astype(np.float32)
    k = max(31, (min(g.shape) // 40) | 1)
    fondo = cv2.medianBlur(cv2.resize(g, None, fx=0.25, fy=0.25).astype(np.uint8), k | 1)
    fondo = cv2.resize(fondo, (g.shape[1], g.shape[0])).astype(np.float32)
    return np.clip(g / np.maximum(fondo, 1) * 255, 0, 255).astype(np.uint8)


def alto_caracter(gris: np.ndarray) -> float:
    """Alto típico de carácter: la moda de las alturas de los componentes "tipo letra"."""
    b = (gris < 150).astype(np.uint8)
    _, _, st, _ = cv2.connectedComponentsWithStats(b, 8)
    h, w, a = st[1:, cv2.CC_STAT_HEIGHT], st[1:, cv2.CC_STAT_WIDTH], st[1:, cv2.CC_STAT_AREA]
    ok = ((h >= 6) & (h <= 200) & (w >= 2) & (w <= 1.3 * h) & (w >= 0.25 * h)
          & (a > 0.15 * w * h) & (a < 0.75 * w * h))
    hs = h[ok]
    if len(hs) < 20:
        return 20.0
    hist = np.convolve(np.bincount(np.clip(hs, 0, 200)), np.ones(3), "same")
    return float(np.argmax(hist[6:]) + 6)


def rotar(img: np.ndarray, angulo: float, fondo: int = 255):
    """Gira `angulo` grados (antihorario, como cv2) sin recortar. Devuelve (imagen, M)."""
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angulo, 1.0)
    c, s = abs(m[0, 0]), abs(m[0, 1])
    ancho, alto = int(h * s + w * c), int(h * c + w * s)
    m[0, 2] += ancho / 2 - w / 2
    m[1, 2] += alto / 2 - h / 2
    return cv2.warpAffine(img, m, (ancho, alto), flags=cv2.INTER_LINEAR, borderValue=fondo), m


def _escalar(g: np.ndarray, escala: float) -> np.ndarray:
    if abs(escala - 1) < 1e-6:
        return g
    return cv2.resize(g, None, fx=escala, fy=escala,
                      interpolation=cv2.INTER_AREA if escala < 1 else cv2.INTER_CUBIC)


def _otsu(g: np.ndarray) -> np.ndarray:
    return cv2.threshold(cv2.GaussianBlur(g, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]


def _correr(tareas, hebras: int, avance, etiqueta: str) -> list:
    """Corre las pasadas en hebras y avisa por tandas. Una pasada que falla se salta."""
    salida, hechas, inicio = [], 0, time.time()
    total = len(tareas)
    tanda = max(1, min(hebras, total))
    errores = 0
    with ThreadPoolExecutor(hebras) as grupo:
        futuros = [grupo.submit(f, *args) for f, *args in tareas]
        for futuro in as_completed(futuros):
            try:
                salida.extend(futuro.result())
            except Exception:              # noqa: BLE001 - una pasada mala no tumba el lector
                errores += 1
            hechas += 1
            if hechas % tanda == 0 or hechas == total:
                avance(f"{etiqueta}: {hechas} de {total} pasadas ({time.time() - inicio:.0f} s)")
    if errores:
        avance(f"{etiqueta}: {errores} pasadas fallaron y se saltaron")
    return salida


# ------------------------------------------------------------------------- números de lote
RE_NUMERO = re.compile(r"^(?:LOTE)?-*(?:(\d{1,3})-)?(\d{1,3})-*$")


def numero(texto: str) -> str | None:
    """El rótulo como está en el plano: 'LOTE-12' / '12' / '10-6' / 'LOTE 8-01' (el par
    sector-lote) → '12' / '12' / '10-6' / '8-01', con los ceros tal cual. Las cotas y
    áreas (con , o .) no; el lote 0 tampoco."""
    t = (texto or "").strip().upper().replace("—", "-")
    if not t or "," in t or "." in t:
        return None
    m = RE_NUMERO.match(t)
    if not m or int(m.group(2)) == 0:
        return None
    return f"{m.group(1)}-{m.group(2)}" if m.group(1) else m.group(2)


def interpretar(datos: dict, inversa: np.ndarray, escala: float, angulo: float, variante: str) -> list[dict]:
    """Las palabras de `pytesseract.image_to_data` que son número de lote, con su centro
    llevado de vuelta a la imagen original (`inversa`: de la girada a la escalada)."""
    salida = []
    textos = datos["text"]
    linea = lambda k: (datos["block_num"][k], datos["par_num"][k], datos["line_num"][k])
    for i, t in enumerate(textos):
        n = numero(t)
        if n is None:
            continue
        x0, y0 = datos["left"][i], datos["top"][i]
        x1, y1 = x0 + datos["width"][i], y0 + datos["height"][i]
        # "LOTE" pegado (LOTE-12) o como palabra anterior en la misma línea (LOTE 12).
        lote = "OTE" in t.upper()
        j = i - 1
        if not lote and j >= 0 and "OTE" in str(textos[j]).upper() and linea(j) == linea(i):
            lote = True
            x0 = min(x0, datos["left"][j])
            y0 = min(y0, datos["top"][j])
            y1 = max(y1, datos["top"][j] + datos["height"][j])
        x, y = inversa @ np.array([(x0 + x1) / 2, (y0 + y1) / 2, 1.0])
        salida.append(dict(numero=n, lote=lote, x=float(x / escala), y=float(y / escala),
                           conf=float(datos["conf"][i]), ang=angulo, var=variante, escala=round(escala, 4),
                           alto=float(datos["height"][i] / escala)))
    return salida


def _pasada_rotulos(imagen: np.ndarray, escala: float, angulo: float, variante: str) -> list[dict]:
    import pytesseract
    girada, m = rotar(imagen, angulo)
    datos = pytesseract.image_to_data(girada, config=CFG_ROTULOS, output_type=pytesseract.Output.DICT,
                                      timeout=TIMEOUT_PASADA_S)
    del girada
    return interpretar(datos, cv2.invertAffineTransform(m), escala, angulo, variante)


def seleccionar(lecturas: list[dict], alto_modal: float, pasadas: int, radio: float | None = None) -> list[Rotulo]:
    """De las lecturas crudas a un rótulo por lugar y un lugar por número (`seleccion.py`
    de la tarea 1):

    1. Si el plano rotula con "LOTE" (≥ MIN_LECTURAS_LOTE lecturas), solo cuentan esas.
       Si no, solo los números sueltos de alto ≥ ALTO_SUELTO × el texto modal.
    2. Mismo número a menos de `radio` → un candidato; su apoyo es cuántas pasadas lo leyeron.
       "Mismo" es `numeros.mismo_lote`: "8-01", "8-1" y "1" (la pasada que no vio el
       sector) se juntan. El candidato se queda con la forma más leída de las que traen
       el sector, si alguna lo trae ("LOTE 8-01" → "8-01").
    3. Un número por lugar (candidatos a < radio/2) y un lugar por número: gana el de más apoyo.

    `radio` por omisión: RADIO_ALTOS × el alto mediano de las lecturas que cuentan.
    """
    con_lote = sum(1 for d in lecturas if d["lote"]) >= MIN_LECTURAS_LOTE
    det = ([d for d in lecturas if d["lote"]] if con_lote
           else [d for d in lecturas if d["alto"] >= ALTO_SUELTO * alto_modal])
    if not det:
        return []
    if radio is None:
        radio = RADIO_ALTOS * float(np.median([d["alto"] for d in det]))
    grupos: list[dict] = []
    for d in sorted(det, key=lambda d: -d["conf"]):
        n = str(d["numero"])
        for g in grupos:
            if mismo_lote(g["numero"], n) and hypot(g["x"] - d["x"], g["y"] - d["y"]) < radio:
                g["pasadas"].add((d["escala"], d["ang"], d["var"]))
                g["alto"] = max(g["alto"], d["alto"])
                g["formas"][n] += 1
                break
        else:
            grupos.append(dict(numero=n, x=d["x"], y=d["y"], conf=d["conf"], alto=d["alto"],
                               pasadas={(d["escala"], d["ang"], d["var"])}, formas=Counter([n])))
    for g in grupos:
        formas = g["formas"]
        con_sector = [f for f in formas if "-" in f]
        g["numero"] = max(con_sector or formas, key=lambda f: (formas[f], len(f)))
    grupos.sort(key=lambda g: (-len(g["pasadas"]), -g["conf"]))
    elegidos: list[dict] = []
    for g in grupos:
        if any(hypot(o["x"] - g["x"], o["y"] - g["y"]) < radio / 2 for o in elegidos):
            continue
        if any(mismo_lote(o["numero"], g["numero"]) for o in elegidos):
            continue
        elegidos.append(g)
    total = max(1, pasadas)
    return [Rotulo(str(g["numero"]), float(g["x"]), float(g["y"]), len(g["pasadas"]) / total,
                   len(g["pasadas"]), float(g["alto"])) for g in elegidos]


def leer(imagen: np.ndarray, ppmm: float | None = None, avance=print, hebras: int | None = None,
         paso: int = PASO_GRADOS) -> list[Rotulo]:
    """Los números de lote de `imagen` (RGB o gris: el dibujo, con las máscaras ya
    tapadas). Posiciones en px de `imagen`. `ppmm` no lo usa Tesseract (el método se
    ajusta solo al alto del texto); está en la interfaz para otros lectores."""
    motivo = motivo_no_disponible()
    if motivo:
        avance(motivo)
        return []
    try:
        inicio = time.time()
        g = gris_normalizado(imagen)
        alto = alto_caracter(g)
        e1 = ALTO_TEXTO_PX / alto
        variantes = []
        for escala in (e1, e1 / ESCALA_GRANDE):
            gs = _escalar(g, escala)
            variantes += [(escala, "gris", gs), (escala, "bin", _otsu(gs))]
        del g
        tareas = [(_pasada_rotulos, img, escala, float(a), var)
                  for escala, var, img in variantes for a in range(0, 360, paso)]
        # A 45° la imagen girada ocupa hasta el doble.
        n = _hebras(hebras, len(tareas), 2.0 * max(img.size for _, _, img in variantes))
        avance(f"Rótulos: texto típico de {alto:.0f} px; {len(tareas)} pasadas de Tesseract en {n} hebras")
        lecturas = _correr(tareas, n, avance, "Rótulos")
        del variantes, tareas
        rotulos = seleccionar(lecturas, alto, len(range(0, 360, paso)) * 4)
        avance(f"Rótulos: {len(rotulos)} números leídos ({sum(r.apoyo >= APOYO_MIN for r in rotulos)}"
               f" con apoyo ≥ {APOYO_MIN}) en {time.time() - inicio:.0f} s")
        return rotulos
    except Exception as error:             # noqa: BLE001 - el lector nunca tumba digitalizar
        avance(f"El lector de rótulos falló ({error}); se sigue sin él")
        return []


# ------------------------------------------------------------------------- semillas
def combinar(usuario, lector: list[Rotulo], radio: float, apoyo_min: int = APOYO_MIN,
             poligonos=(), oficiales=()) -> list[dict]:
    """Las semillas de digitalizar: las de la loteadora y, donde ella no marcó, las del lector.

    `usuario`: [(numero, x, y)] o [{"numero", "x", "y"}]; `lector`: rótulos en el mismo
    sistema de píxeles. Gana siempre la loteadora: un rótulo leído se descarta si

    - tiene apoyo < `apoyo_min`,
    - su número ya lo marcó ella (lo corrigió o lo movió; `numeros.mismo_lote`),
    - cae a menos de `radio` de una semilla suya (ella corrigió ese rótulo), o
    - cae dentro del mismo lote que una semilla suya (`poligonos`: los lotes de la
      digitalización anterior; ella hace clic en el lote, no en el rótulo), o
    - hay cuadro de superficies (`oficiales`: los números que trae) y el número no está
      en él y es mayor que todos los suyos: es una cota o un área (en Algarrobo, 40
      de las 56 lecturas sobrantes). Un número menor que el máximo sí pasa, por si el
      cuadro se leyó a medias. Si el cuadro dejaría fuera a más de la mitad de lo
      leído con apoyo, no se usa (no es el de superficies).

    Devuelve [{"numero", "x", "y", "origen": "usuario"|"lector", "confianza", "apoyo"}].
    """
    salida = []
    for s in usuario:
        n, x, y = (s["numero"], s["x"], s["y"]) if isinstance(s, dict) else s
        salida.append(dict(numero=str(n), x=float(x), y=float(y), origen="usuario", confianza=None, apoyo=None))
    numeros = [s["numero"] for s in salida]
    puntos = [(s["x"], s["y"]) for s in salida]
    tomados = []
    if poligonos and puntos:
        from shapely.geometry import Point, Polygon
        figuras = [p if isinstance(p, Polygon) else Polygon(p) for p in poligonos]
        tomados = [f for f in figuras if f.is_valid and any(f.contains(Point(p)) for p in puntos)]
    # Contra el cuadro se compara el número dentro del sector ("8-01" → 1): el cuadro
    # puede listar "1" o "8-01".
    oficiales = {ultimo(n) for n in oficiales} - {None}
    tope = max(oficiales, default=None)
    fuera = lambda r: ultimo(r.numero) is None or (ultimo(r.numero) not in oficiales and ultimo(r.numero) > tope)
    candidatos = [r for r in lector if r.apoyo >= apoyo_min]
    if tope is not None and 2 * sum(fuera(r) for r in candidatos) > len(candidatos):
        # El cuadro dejaría fuera a la mayoría de lo leído: lo más probable es que no sea
        # el de superficies (un cuadro de coordenadas de vértices numerados 1…20). En
        # Algarrobo saca 42 de 117.
        tope = None
    for r in sorted(lector, key=lambda r: (-r.apoyo, -r.confianza)):
        if r.apoyo < apoyo_min or any(mismo_lote(r.numero, n) for n in numeros):
            continue
        if tope is not None and fuera(r):
            continue
        if any(hypot(r.x - x, r.y - y) < radio for x, y in puntos):
            continue
        if tomados:
            from shapely.geometry import Point
            if any(f.contains(Point(r.x, r.y)) for f in tomados):
                continue
        salida.append(dict(numero=r.numero, x=float(r.x), y=float(r.y), origen="lector",
                           confianza=round(r.confianza, 4), apoyo=r.apoyo))
        numeros.append(r.numero)
    return salida


# ------------------------------------------------------------------------- cuadrícula
RE_MARCA = re.compile(r"^([EN])-*(\d{6,7})$")


def marca(texto: str) -> tuple[str, int] | None:
    """'E-255750' → ('E', 255750); 'N-6306750' → ('N', 6306750). El este UTM tiene 6
    cifras y el norte 7: lo demás es una lectura mala."""
    m = RE_MARCA.match((texto or "").strip().upper())
    if not m:
        return None
    eje, digitos = m.group(1), m.group(2)
    if (eje == "E") != (len(digitos) == 6):
        return None
    return eje, int(digitos)


def _pasada_cuadricula(imagen: np.ndarray, escala: float, angulo: float, origen=(0, 0)) -> list[tuple]:
    import pytesseract
    girada, m = rotar(imagen, angulo)
    d = pytesseract.image_to_data(girada, config=CFG_CUADRICULA, output_type=pytesseract.Output.DICT,
                                  timeout=TIMEOUT_PASADA_S)
    inversa = cv2.invertAffineTransform(m)
    salida = []
    for i, t in enumerate(d["text"]):
        mk = marca(t)
        if mk is None:
            continue
        x, y = inversa @ np.array([d["left"][i] + d["width"][i] / 2, d["top"][i] + d["height"][i] / 2, 1.0])
        salida.append((mk[0], mk[1], float(x / escala + origen[0]), float(y / escala + origen[1])))
    return salida


def franjas(rectangulo, forma, ancho: float) -> list[tuple[int, int, int, int]]:
    """Las 4 franjas de ±`ancho` px alrededor del borde del dibujo, donde van las marcas
    de la cuadrícula (en Algarrobo, de 8 mm por fuera a 14 mm por dentro). Se traslapan
    en las esquinas para no cortar una marca."""
    alto, ancho_img = forma[:2]
    x0, y0, x1, y1 = rectangulo
    b = ancho
    cajas = [(x0 - b, y0 - b, x1 + b, y0 + b), (x0 - b, y1 - b, x1 + b, y1 + b),
             (x0 - b, y0 - b, x0 + b, y1 + b), (x1 - b, y0 - b, x1 + b, y1 + b)]
    salida = []
    for a0, c0, a1, c1 in cajas:
        a0, c0 = max(0, int(a0)), max(0, int(c0))
        a1, c1 = min(ancho_img, int(round(a1))), min(alto, int(round(c1)))
        if a1 - a0 > 10 and c1 - c0 > 10:
            salida.append((a0, c0, a1, c1))
    return salida


def _recta(puntos: list[tuple[int, float]], tolerancia: float, separacion: float):
    """Ajuste robusto posición = a·valor + b sobre [(valor, pos)]: el par de marcas con
    más valores distintos a menos de `tolerancia`, reajustado por mínimos cuadrados.
    Dos marcas de distinto valor deben estar a `separacion` o más en esa coordenada (si
    no, la recta es casi horizontal y "explica" cualquier valor). Devuelve (a, b,
    inliers) o None."""
    mejor = None
    for i in range(len(puntos)):
        for j in range(i + 1, len(puntos)):
            (vi, pi), (vj, pj) = puntos[i], puntos[j]
            if vi == vj or abs(pj - pi) < separacion:
                continue
            a = (pj - pi) / (vj - vi)
            dentro = [(v, p) for v, p in puntos if abs(p - (pi + a * (v - vi))) <= tolerancia]
            clave = (len({v for v, _ in dentro}), len(dentro))
            if mejor is None or clave > mejor[0]:
                mejor = (clave, dentro)
    if mejor is None:
        return None
    dentro = mejor[1]
    for _ in range(2):
        v = np.array([v for v, _ in dentro], float)
        p = np.array([p for _, p in dentro], float)
        if len(set(v)) < 2:
            return None
        a, b = np.polyfit(v - v.mean(), p, 1)
        b -= a * v.mean()
        dentro = [(vv, pp) for vv, pp in puntos if abs(pp - (a * vv + b)) <= tolerancia]
    return float(a), float(b), dentro


def progresion(valores) -> list[int]:
    """Los valores que forman una progresión regular de PASO_MINIMO_M o más (750 m en
    Algarrobo). Una lectura que rompe el paso (6306756 por 6306750) se saca, de a una,
    la que más lo arregla. Devuelve los valores que quedan (vacío si no hay progresión)."""
    vals = sorted(set(int(v) for v in valores))
    def paso(vs):
        g = 0
        for a, b in zip(vs, vs[1:]):
            g = gcd(g, b - a)
        return g
    while len(vals) >= MIN_VALORES_CUADRICULA and paso(vals) < PASO_MINIMO_M:
        candidatos = [(paso(vals[:k] + vals[k + 1:]), k) for k in range(len(vals))]
        _, k = max(candidatos)
        vals.pop(k)
    return vals if len(vals) >= MIN_VALORES_CUADRICULA else []


def ajustar_cuadricula(lecturas: list[tuple], tolerancia: float, separacion: float) -> dict | None:
    """De las marcas leídas [(eje 'E'|'N', valor, x, y)] a la `cuadricula` de
    `entradas.json`. Cada eje se ajusta contra x y contra y; se queda la orientación
    (E en x y N en y, o al revés) con más marcas consistentes. Una familia vale con
    MIN_VALORES_CUADRICULA valores en progresión regular y en su recta valor→píxel. La
    posición de cada línea es la mediana de sus marcas buenas."""
    por_eje = {e: [(v, x, y) for ee, v, x, y in lecturas if ee == e] for e in ("E", "N")}

    def familia(eje, coordenada):
        puntos = [(v, (x, y)[coordenada]) for v, x, y in por_eje[eje]]
        if len({v for v, _ in puntos}) < MIN_VALORES_CUADRICULA:
            return None
        ajuste = _recta(puntos, tolerancia, separacion)
        if ajuste is None:
            return None
        a, b, dentro = ajuste
        vals = progresion(v for v, _ in dentro)
        if not vals or abs(a) * min(b_ - a_ for a_, b_ in zip(vals, vals[1:])) < separacion:
            return None
        buenos = set(vals)
        pos = {v: float(np.median([p for vv, p in dentro if vv == v])) for v in sorted(buenos)}
        return dict(a=a, valores=pos)

    opciones = []
    for e_coord in (0, 1):
        fe, fn = familia("E", e_coord), familia("N", 1 - e_coord)
        puntaje = sum(len(f["valores"]) for f in (fe, fn) if f)
        opciones.append((puntaje, e_coord, fe, fn))
    puntaje, e_coord, fe, fn = max(opciones, key=lambda o: o[0])
    if not puntaje:
        return None
    if fe and fn:
        # La misma escala en los dos ejes: si no, una de las familias está mal leída.
        razon = abs(fe["a"]) / abs(fn["a"])
        if not 0.9 <= razon <= 1.1:
            fe, fn = (fe, None) if len(fe["valores"]) >= len(fn["valores"]) else (None, fn)
    salida = dict(verticales=[], horizontales=[], epsg=None)
    for f, coord in ((fe, e_coord), (fn, 1 - e_coord)):
        if not f:
            continue
        familia_ = "verticales" if coord == 0 else "horizontales"
        clave = "x" if coord == 0 else "y"
        salida[familia_] = [{clave: round(p, 1), "valor": v} for v, p in f["valores"].items()]
    return salida


def leer_cuadricula(imagen: np.ndarray, ppmm: float, avance=print, hebras: int | None = None,
                    rectangulo=None) -> dict | None:
    """Las marcas E-/N- de la cuadrícula UTM. Van en el borde del dibujo: con
    `rectangulo` (el dibujo, px de `imagen`) se leen solo las franjas de
    ±BANDA_CUADRICULA_MM alrededor de su borde; sin él, la página completa. La página
    completa de Hidango (64 Mpx) pide ~6 GB y más de 1 min por pasada. Devuelve la
    `cuadricula` de `entradas.json` (posiciones en px de `imagen`) o None si no hay una
    confiable."""
    motivo = motivo_no_disponible()
    if motivo:
        return None
    try:
        inicio = time.time()
        cajas = (franjas(rectangulo, imagen.shape, BANDA_CUADRICULA_MM * ppmm) if rectangulo is not None
                 else [(0, 0, imagen.shape[1], imagen.shape[0])])
        tareas = []
        for x0, y0, x1, y1 in cajas:
            g = gris_normalizado(imagen[y0:y1, x0:x1])
            escala = ALTO_TEXTO_PX / alto_caracter(g)
            gs = _escalar(g, escala)
            del g
            tareas += [(_pasada_cuadricula, img, escala, float(a), (x0, y0))
                       for img in (gs, _otsu(gs)) for a in (0, 90, 180, 270)]
        lecturas = _correr(tareas, _hebras(hebras, len(tareas), max(t[1].size for t in tareas) if tareas else 0),
                           avance, "Cuadrícula")
        del tareas
        c = ajustar_cuadricula(lecturas, TOLERANCIA_CUADRICULA_MM * ppmm, SEPARACION_CUADRICULA_MM * ppmm)
        n = 0 if c is None else len(c["verticales"]) + len(c["horizontales"])
        avance(f"Cuadrícula: {len(lecturas)} marcas leídas, {n} líneas confiables ({time.time() - inicio:.0f} s)")
        return c if n else None
    except Exception as error:             # noqa: BLE001
        avance(f"No se pudo leer la cuadrícula ({error})")
        return None


# ------------------------------------------------------------------------- cuadro de superficies
RE_VALOR = re.compile(r"\d+(?:[.,]\d+)*")
RE_HA = re.compile(r"h[aá]s?\b|hect", re.I)
RE_M2 = re.compile(r"m2|m²|mt2|mts2", re.I)


def a_numero(texto: str) -> float | None:
    """Número con la costumbre chilena: '.' de miles y ',' decimal ('5.000,50' → 5000.5,
    '5,00' → 5.0, '5.000' → 5000). Un solo punto que no agrupa miles es decimal."""
    m = RE_VALOR.search(texto or "")
    if not m:
        return None
    t = m.group(0)
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        if t.count(",") > 1:
            return None
        t = t.replace(",", ".")
    elif "." in t and re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")
    elif t.count(".") > 1:
        return None
    try:
        return float(t)
    except ValueError:
        return None


def area_m2(texto: str, unidad: str | None = None) -> float | None:
    """'5,00hás' → 50000; '5.000 m²' → 5000; '5.000' → 5000. La unidad sale del texto,
    de `unidad` ('ha' o 'm2') o, si no hay, de la magnitud: bajo 100 son hectáreas (una
    parcela de agrado tiene al menos 5.000 m²; nadie anota 100 ha en un cuadro)."""
    v = a_numero(texto)
    if v is None or v <= 0:
        return None
    if RE_HA.search(texto or ""):
        unidad = "ha"
    elif RE_M2.search(texto or ""):
        unidad = "m2"
    if unidad is None:
        unidad = "ha" if v < 100 else "m2"
    return round(v * 10000 if unidad == "ha" else v, 2)


RE_AREA = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{1,2}|\d{1,3}(?:\.\d{3})+|\d{4,7}")
# El número del lote al comienzo de la fila, como está impreso: "12", "8-01".
RE_LOTE_FILA = re.compile(r"^\D*?(\d{1,3}(?:-\d{1,3})?)(?![\d.,])")
# Una celda numérica y, si viene pegada o a un espacio, su unidad ("5.000m2", "5,00 hás").
RE_CELDA = re.compile(r"(\d+(?:[.,]\d+)*)(\s?(?:m2|m²|mts?2|h[aá]s?\b|hect\w*))?", re.I)


def filas_cuadro(texto: str) -> list[list[str]]:
    """Filas del cuadro: [lote, celda, ..., total]. Las líneas que empiezan con un
    número de lote ("12" o "8-01", como está impreso; no 0) seguido de al menos una
    celda, la última con forma de área ('5,00', '5.000', '5.000,50', '5000', con o sin
    unidad: '5.000 m2'; no '222'). Las celdas llevan su unidad si la trae."""
    salida = []
    for linea in (texto or "").splitlines():
        m = RE_LOTE_FILA.match(linea)
        if not m or not any(int(d) for d in re.findall(r"\d+", m.group(1))[-1:]):
            continue
        celdas = [c.group(0).strip() for c in RE_CELDA.finditer(linea, m.end())]
        if celdas and RE_AREA.fullmatch(RE_CELDA.match(celdas[-1]).group(1)):
            salida.append([m.group(1)] + celdas)
    return salida


def _lote_de_fila(texto: str) -> str:
    """'012' → '12'; '8-01' queda como está impreso (así sale en el KMZ)."""
    return texto if "-" in texto else str(int(texto))


def areas_de_filas(filas: list[list[str]]) -> dict[str, float]:
    """{numero: m²} con la última celda de cada fila (la columna TOTAL: la de más a la
    derecha; las del medio, como "SUP. SERVIDUMBRE", no cuentan). Si varias pasadas
    leen el mismo lote, gana el valor más leído (a igual cuenta, el primero). La unidad
    es la que trae la celda ("m2", "hás") o, si no trae, la de la columna: si la
    mediana es < 100, son hectáreas.

    Un número de lote se compara por `numeros.clave` ("8-01" = "8-1") y se guarda como
    se leyó primero."""
    from .numeros import clave
    lecturas: dict[str, list[str]] = defaultdict(list)
    impreso: dict[str, str] = {}
    for f in filas:
        n = _lote_de_fila(f[0])
        impreso.setdefault(clave(n), n)
        lecturas[clave(n)].append(f[-1])
    valores = [a_numero(t) for ts in lecturas.values() for t in ts if not RE_HA.search(t) and not RE_M2.search(t)]
    valores = [v for v in valores if v]
    unidad = "ha" if valores and statistics.median(valores) < 100 else "m2"
    salida = {}
    for c, textos in lecturas.items():
        areas = [a for a in (area_m2(t, unidad) for t in textos) if a]
        if areas:
            salida[impreso[c]] = Counter(areas).most_common(1)[0][0]
    return salida


def sin_lineas(g: np.ndarray, largo: int = 60) -> np.ndarray:
    """Borra las líneas de la grilla del cuadro (aperturas morfológicas largas). Sin
    esto Tesseract lee 5 de 76 filas en Algarrobo."""
    b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    h = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (largo, 1)))
    v = cv2.morphologyEx(b, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, largo)))
    m = cv2.dilate(cv2.bitwise_or(h, v), np.ones((3, 3), np.uint8))
    salida = g.copy()
    salida[m > 0] = 255
    return salida


def _tabla(recorte: np.ndarray) -> dict[str, float]:
    import pytesseract
    cfg = CFG_CUADRO
    g = gris_normalizado(recorte)
    escala = min(4.0, max(1.0, ALTO_TABLA_PX / alto_caracter(g)))
    g = _escalar(g, escala)

    def puntaje(angulo):
        t = pytesseract.image_to_string(sin_lineas(rotar(g, angulo)[0]), config=cfg.format(6),
                                        timeout=TIMEOUT_PASADA_S)
        return len(re.findall(r"(?<![\d,.])\d{1,3}(?:\.\d{3})*,\d{2}(?![\d,.])|(?<![\d,.])\d{1,3}(?:\.\d{3})+(?![\d,.])", t))

    angulo = max((0, 90, 180, 270), key=puntaje)
    r = sin_lineas(rotar(g, angulo)[0])
    filas = []
    for psm in (6, 4):
        for img in (r, _otsu(r)):
            filas += filas_cuadro(pytesseract.image_to_string(img, config=cfg.format(psm), timeout=TIMEOUT_PASADA_S))
    return areas_de_filas(filas)


def leer_cuadro(imagen: np.ndarray, rectangulos, avance=print) -> dict[str, float]:
    """El cuadro de superficies: {numero: área en m²}. `rectangulos`: dónde puede estar
    (el `cuadro` que marcó la loteadora o, si no, cada máscara); se queda el que da más
    filas. Vacío si ninguno da al menos MIN_FILAS_CUADRO."""
    if motivo_no_disponible() or not rectangulos:
        return {}
    inicio = time.time()
    mejor: dict[str, float] = {}
    alto, ancho = imagen.shape[:2]
    for rect in rectangulos:
        x0, y0, x1, y1 = (int(round(v)) for v in rect)
        x0, x1 = max(0, x0), min(ancho, x1)
        y0, y1 = max(0, y0), min(alto, y1)
        if x1 - x0 < 20 or y1 - y0 < 20:
            continue
        try:
            areas = _tabla(imagen[y0:y1, x0:x1])
        except Exception as error:         # noqa: BLE001
            avance(f"Cuadro de superficies: no se pudo leer {list(rect)} ({error})")
            continue
        if len(areas) > len(mejor):
            mejor = areas
    if len(mejor) < MIN_FILAS_CUADRO:
        mejor = {}
    avance(f"Cuadro de superficies: {len(mejor)} áreas oficiales ({time.time() - inicio:.0f} s)")
    return mejor
