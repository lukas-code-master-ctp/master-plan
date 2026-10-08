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

Costo: hasta 96 pasadas por plano (24 ángulos × 2 escalas × gris/Otsu). Primero se
sondean unas pocas orientaciones (`ANGULOS_SONDEO`) y después solo se leen los ángulos
cercanos a las que dieron rótulos (`orientaciones`): de 96 a ~20–40 pasadas. Cada
pasada lee la imagen **por teselas** de tamaño acotado (`teselas`), con un margen que
no corta rótulos: la memoria de una pasada no crece con el plano (con texto de 15 px
el dibujo se agranda 1,6× y, girado en diagonal, crece otra vez al doble; entero, una
página de 5000×7000 px no cabía en 4 GiB).

Las pasadas corren en hebras, tantas como núcleos del contenedor (`LECTOR_HEBRAS` lo
acota) y que quepan en su memoria (`_hebras`): el trabajo pesado es el subproceso
`tesseract`, con `OMP_THREAD_LIMIT=1` (sin eso las pasadas en paralelo se estorban y
un plano tarda más de 10 min en vez de 1).

Avance retomable: una lectura larga (Constitución, más de 15 min) se perdía entera si
Cloud Run cambiaba la instancia. Con `leer(…, avance_en=<carpeta>)` cada pasada que
termina entera y sin teselas malas se guarda como `<carpeta>/e<escala>-<variante>-<ángulo>.json`
(escritura atómica), y al empezar se cargan las que ya estén y no se vuelven a leer:
el sondeo, `orientaciones` y `seleccionar` las usan igual que las nuevas. Un archivo
ilegible cuenta como no leído. `digitalizar` elige la carpeta por la huella del lector.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, replace
from math import gcd, hypot

import cv2
import numpy as np

from .numeros import clave, mismo_lote, segun_cuadro, ultimo

# Una hebra por proceso de Tesseract: las pasadas ya corren en paralelo. Antes de
# lanzar el primer subproceso (lo heredan).
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

# Cambia si cambia el método: invalida las lecturas guardadas en digitalizado.json.
# 2: el número es el rótulo completo ("8-01"), no el último número.
# 3: el cuadro de superficies lee "8-01" y la unidad ("5.000 m2").
# 4: el cuadro lee la fila del resto de la propiedad, aunque venga en dos líneas.
VERSION = 4

SIN_LECTOR = "sin lector de rótulos: tesseract no está instalado"

# --- números de lote (parámetros globales de la tarea 1) -------------------------------
# tessedit_do_invert=0: Tesseract no vuelve a leer en negativo las líneas dudosas (un
# plano no tiene texto blanco sobre negro). Mismas lecturas, ~10 % menos de tiempo.
CFG_ROTULOS = "--oem 1 --psm 11 -c tessedit_char_whitelist=LOTE0123456789-,. -c tessedit_do_invert=0"
PASO_GRADOS = 15          # 30° pierde los rótulos diagonales (Hidango cae a 24 %)
ALTO_TEXTO_PX = 24.0      # el texto modal se lleva a este alto
ESCALA_GRANDE = 2.5       # segunda escala, 2,5× más chica, para los rótulos grandes
MIN_LECTURAS_LOTE = 10    # con tantas lecturas "LOTE…", solo cuentan esas
ALTO_SUELTO = 1.4         # sin "LOTE", un número suelto debe medir esto × el texto modal
RADIO_ALTOS = 3.0         # radio de agrupación = esto × el alto mediano del rótulo
APOYO_MIN = 2             # lo que `digitalizar` toma como semilla (apoyo ≥ 2: precisión)
TIMEOUT_PASADA_S = 600
# Memoria de una pasada por píxel de la imagen girada que se le da a Tesseract (Tesseract
# ~4,4 MB/Mpx más las copias de Python: el recorte escalado, el girado y el PNG que
# escribe pytesseract): con 16 pasadas a la vez, Algarrobo llegó a 9,2 GB.
BYTES_POR_PIXEL = 6.0
# Lo fijo de una pasada (el proceso de Tesseract con su modelo, las listas de Python).
BYTES_FIJOS_PASADA = 60e6
# De la memoria libre del contenedor, cuánto se reparte entre las pasadas.
FRACCION_MEMORIA = 0.6

# --- teselas ------------------------------------------------------------------------------
# Una tesela, ya escalada y con su margen, tiene a lo más estos píxeles: girada en
# diagonal llega al doble. Una página de 5000×7000 px con texto de 15 px son ~90 Mpx
# escalados (y ~190 Mpx girada): no se lee de una vez.
TESELA_MPX = 14.0
# El margen de cada tesela, en altos de texto escalado (ALTO_TEXTO_PX): un rótulo
# "LOTE 8-01" mide ~7 altos. Cada rótulo cae entero en la tesela cuyo núcleo tiene su
# centro, y solo esa lo cuenta: dos teselas vecinas se traslapan 2 × MARGEN.
MARGEN_TESELA_ALTOS = 10.0

# --- orientaciones primero -----------------------------------------------------------------
# El sondeo: las pasadas de la escala del texto (gris y Otsu) en estos ángulos. Son
# parte de las pasadas finales (no se repiten).
ANGULOS_SONDEO = tuple(range(0, 360, 45))
# Un ángulo del sondeo es una orientación de los rótulos si da más "pares" (un número
# de lote que leen igual, en el mismo lugar, el gris y el Otsu de ese ángulo) que el
# ruido: la mediana de los pares de los ángulos sondeados más RUIDO_SIGMAS × su raíz,
# y al menos MIN_SONDEO. Las lecturas sueltas no sirven: el ruido (cotas, pedazos de
# línea) da tantas en todos los ángulos como los rótulos en el suyo; los pares no. En
# el set de regresión, el 90 % o más de los pares del ángulo bueno son rótulos de
# verdad; en los planos que dicen LOTE los otros ángulos no dan ni un par (basta uno),
# y en Algarrobo (sin LOTE) dan 4–26 contra 73.
RUIDO_SIGMAS = 3.0
MIN_SONDEO = 1
MIN_LOTE_SONDEO = 3       # con tantas lecturas "LOTE…" en el sondeo, solo cuentan esas
# Después se leen los ángulos a ± esto de cada orientación encontrada (PASO_GRADOS
# de 15: tres ángulos por orientación).
VENTANA_ORIENTACION = 20

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
    """Bytes que quedan para el lector: el límite del contenedor (cgroup v2 `memory.max`
    o v1 `memory.limit_in_bytes`) menos lo que ya usa el contenedor entero (en Cloud Run,
    también la consola que lanzó este proceso) o, si no hay límite, MemAvailable (que
    nunca es más que lo libre del contenedor). None si no se sabe (Windows)."""
    meminfo = None
    for linea in (_leer_archivo("/proc/meminfo") or "").splitlines():
        if linea.startswith("MemAvailable:"):
            try:
                meminfo = int(linea.split()[1]) * 1024
            except (ValueError, IndexError):
                pass
            break
    for limite, usado in (("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory.current"),
                          ("/sys/fs/cgroup/memory/memory.limit_in_bytes",
                           "/sys/fs/cgroup/memory/memory.usage_in_bytes")):
        tope, uso = _leer_archivo(limite), _leer_archivo(usado)
        try:
            # cgroup v1 sin límite dice un número enorme (2^63 redondeado a la página).
            if tope and uso and tope != "max" and int(tope) < 1 << 60:
                libre = max(0, int(tope) - int(uso))
                return libre if meminfo is None else min(libre, meminfo)
        except ValueError:
            pass
    return meminfo


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


def pixeles_girada(ancho: float, alto: float, angulo: float) -> float:
    """Píxeles de una imagen ancho×alto girada `angulo` grados sin recortar (`rotar`):
    a 45° un cuadrado ocupa el doble."""
    r = np.radians(angulo)
    c, s = abs(np.cos(r)), abs(np.sin(r))
    return float((ancho * c + alto * s) * (ancho * s + alto * c))


def memoria_pasada(ancho: float, alto: float, angulo: float) -> float:
    """Bytes que pide una pasada de Tesseract sobre una imagen (ya escalada) ancho×alto
    girada `angulo`: lo fijo más BYTES_POR_PIXEL por píxel de la imagen girada."""
    return BYTES_FIJOS_PASADA + BYTES_POR_PIXEL * pixeles_girada(ancho, alto, angulo)


def _hebras(hebras: int | None, trabajos: int, bytes_por_pasada: float = 0) -> int:
    """Cuántas pasadas a la vez: tantas como núcleos del contenedor (`LECTOR_HEBRAS` lo
    acota) y que quepan en FRACCION_MEMORIA de la memoria libre del contenedor, con
    `bytes_por_pasada` la de la pasada más grande (`memoria_pasada`: cuenta el
    agrandado y el giro). Más hebras que núcleos no acelera Tesseract y sí multiplica
    la memoria. Nunca los núcleos ni la memoria del host: los del contenedor."""
    tope = nucleos()
    try:
        tope = min(tope, int(os.environ.get("LECTOR_HEBRAS") or tope))
    except ValueError:
        pass
    libre = memoria_libre()
    if libre is not None and bytes_por_pasada > 0:
        tope = min(tope, int(FRACCION_MEMORIA * libre / bytes_por_pasada))
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


def otsu_de_histograma(histograma: np.ndarray) -> float:
    """El umbral de Otsu de un histograma de 256 niveles, como el de cv2.threshold con
    THRESH_OTSU (el primer nivel que maximiza la varianza entre clases)."""
    p = np.asarray(histograma, np.float64)
    p = p / max(p.sum(), 1.0)
    niveles = np.arange(len(p))
    omega = np.cumsum(p)
    mu = np.cumsum(p * niveles)
    with np.errstate(divide="ignore", invalid="ignore"):
        entre = (mu[-1] * omega - mu) ** 2 / (omega * (1 - omega))
    entre[~np.isfinite(entre)] = 0
    return float(np.argmax(entre))


def umbral_otsu(g: np.ndarray, escala: float, cortes: list[Tesela]) -> float:
    """El umbral de Otsu de `g` escalada y suavizada como en `_otsu`, sin armar la
    imagen escalada entera: se suma el histograma de los núcleos de las teselas
    (`cortes`, que la parten). Así todas las teselas se binarizan con el mismo umbral
    que tenía la imagen entera; uno por tesela, o el de `g` sin escalar, no sirve (con
    el de `g` sin escalar Caminos de Rapel perdía la mitad de los rótulos del Otsu)."""
    alto, ancho = g.shape[:2]
    histograma = np.zeros(256, np.int64)
    for t in cortes:
        x0, y0, x1, y1 = t.nucleo
        x0, y0 = int(max(0, x0)), int(max(0, y0))
        x1, y1 = int(min(ancho, x1)), int(min(alto, y1))
        if x1 > x0 and y1 > y0:
            suave = cv2.GaussianBlur(_escalar(g[y0:y1, x0:x1], escala), (3, 3), 0)
            histograma += np.bincount(suave.ravel(), minlength=256)
    return otsu_de_histograma(histograma)


def _binarizar(g: np.ndarray, umbral: float) -> np.ndarray:
    return cv2.threshold(cv2.GaussianBlur(g, (3, 3), 0), umbral, 255, cv2.THRESH_BINARY)[1]


# ------------------------------------------------------------------------- teselas
@dataclass(frozen=True)
class Tesela:
    """Un trozo de la imagen, en px de la imagen (sin escalar). `recorte` es lo que se
    lee; `nucleo`, lo que cuenta: los núcleos de todas las teselas parten la imagen sin
    traslape (los de los bordes se abren hasta el infinito) y cada recorte es su núcleo
    más un margen. Una lectura cuenta solo en la tesela cuyo núcleo tiene su centro:
    un rótulo leído en dos teselas cuenta una vez, y el pedazo de un rótulo cortado en
    el borde del recorte (su centro cae en el margen) no cuenta."""
    nucleo: tuple[float, float, float, float]
    recorte: tuple[int, int, int, int]

    def tiene(self, x: float, y: float) -> bool:
        x0, y0, x1, y1 = self.nucleo
        return x0 <= x < x1 and y0 <= y < y1


def _cortes(largo: int, partes: int) -> list[int]:
    return [round(i * largo / partes) for i in range(partes + 1)]


def teselas(alto: int, ancho: int, escala: float, mpx: float = TESELA_MPX,
            margen_altos: float = MARGEN_TESELA_ALTOS) -> list[Tesela]:
    """Las teselas para leer una imagen alto×ancho (px sin escalar) a `escala`: las
    menos posibles cuyo recorte, ya escalado, tenga a lo más `mpx` Mpx **girado en
    diagonal la mitad** (ancho + alto ≤ 2·√mpx: un recorte alargado crece mucho más
    que el doble al girarlo). El margen es `margen_altos` × ALTO_TEXTO_PX px escalados
    (a lo más 1/4 del lado de una tesela): un rótulo cuyo centro está en el núcleo cabe
    entero en el recorte."""
    lado = (mpx * 1e6) ** 0.5 / escala                   # px sin escalar
    margen = min(margen_altos * ALTO_TEXTO_PX / escala, lado / 4)
    mejor = None
    for nx in range(1, max(1, ancho) + 1):
        w = min(ancho, -(-ancho // nx) + 2 * margen)
        h_max = 2 * lado - w
        if h_max >= alto:
            ny = 1
        elif h_max - 2 * margen >= 1:
            ny = int(np.ceil(alto / (h_max - 2 * margen)))
        else:
            continue
        clave = (nx * ny, abs(np.log((ancho / nx) / (alto / ny))))
        if mejor is None or clave < mejor[0]:
            mejor = (clave, nx, ny)
        if ny == 1:
            break
    _, nx, ny = mejor
    xs, ys = _cortes(ancho, nx), _cortes(alto, ny)
    salida = []
    for j in range(ny):
        for i in range(nx):
            nucleo = (xs[i] if i else -np.inf, ys[j] if j else -np.inf,
                      xs[i + 1] if i < nx - 1 else np.inf, ys[j + 1] if j < ny - 1 else np.inf)
            recorte = (max(0, int(xs[i] - margen)), max(0, int(ys[j] - margen)),
                       min(ancho, int(np.ceil(xs[i + 1] + margen))), min(alto, int(np.ceil(ys[j + 1] + margen))))
            salida.append(Tesela(nucleo, recorte))
    return salida


def _correr(tareas, hebras: int, avance, etiqueta: str, pasadas=None, total: int | None = None,
            previas: int = 0, inicio: float | None = None, al_completar=None) -> list:
    """Corre las tareas en hebras y avisa por tandas: "Rótulos: X de Y pasadas (N s)" (la
    tarjeta del escáner lo lee). Una tarea que falla se salta.

    `pasadas`: a qué pasada pertenece cada tarea (las teselas de una pasada); la pasada
    cuenta como hecha cuando terminan todas sus teselas. Sin él, cada tarea es una
    pasada. `previas` pasadas ya hechas se suman a X; `total` es Y (por omisión, las
    previas más las de aquí); `inicio`, desde cuándo se cuentan los segundos.

    `al_completar(pasada, lecturas)` se llama con cada pasada que terminó entera y sin
    teselas malas (una a medias no se puede guardar: retomarla perdería esas teselas)."""
    salida = []
    inicio = time.time() if inicio is None else inicio
    pasadas = list(range(len(tareas))) if pasadas is None else list(pasadas)
    faltan = Counter(pasadas)
    total = previas + len(faltan) if total is None else total
    hechas = previas
    tanda = max(1, min(hebras, len(faltan)))
    malas = set()
    por_pasada = defaultdict(list)
    sin_guardar = False                    # un disco lleno avisa una vez, no en cada pasada
    with ThreadPoolExecutor(hebras) as grupo:
        futuros = {grupo.submit(f, *args): p for (f, *args), p in zip(tareas, pasadas)}
        for futuro in as_completed(futuros):
            p = futuros[futuro]
            try:
                leidas = futuro.result()
                salida.extend(leidas)
                por_pasada[p].extend(leidas)
            except Exception:              # noqa: BLE001 - una pasada mala no tumba el lector
                malas.add(p)
            faltan[p] -= 1
            if faltan[p]:
                continue
            hechas += 1
            if al_completar is not None and p not in malas:
                try:
                    al_completar(p, por_pasada[p])
                except Exception as error:     # noqa: BLE001 - sin guardar se pierde el retomar, no la lectura
                    if not sin_guardar:
                        avance(f"{etiqueta}: no se pudo guardar el avance ({error}); se sigue sin guardarlo")
                    sin_guardar = True
            if (hechas - previas) % tanda == 0 or not +faltan:
                avance(f"{etiqueta}: {hechas} de {total} pasadas ({time.time() - inicio:.0f} s)")
    if malas:
        avance(f"{etiqueta}: {len(malas)} pasadas fallaron y se saltaron")
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


def _para_tesseract(img: np.ndarray):
    """La imagen como la guarda pytesseract para el subproceso: en PGM, sin comprimir
    (Pillow escribe "PPM" en gris como PGM). Por omisión la escribe en PNG, y comprimir
    una tesela girada de 28 Mpx toma más de lo que ahorra en disco: con PGM las mismas
    lecturas en un 20 % menos de tiempo (la página grande de 5000×7000 px)."""
    from PIL import Image
    salida = Image.fromarray(img)
    salida.format = "PPM"
    return salida


def _pasada_rotulos(imagen: np.ndarray, escala: float, angulo: float, variante: str) -> list[dict]:
    import pytesseract
    girada, m = rotar(imagen, angulo)
    datos = pytesseract.image_to_data(_para_tesseract(girada), config=CFG_ROTULOS,
                                      output_type=pytesseract.Output.DICT, timeout=TIMEOUT_PASADA_S)
    del girada
    return interpretar(datos, cv2.invertAffineTransform(m), escala, angulo, variante)


def _pasada_tesela(g: np.ndarray, tesela: Tesela, escala: float, angulo: float, variante: str,
                   umbral: float) -> list[dict]:
    """Una pasada sobre una tesela de `g` (gris sin escalar): se recorta, se escala, se
    binariza si toca y se gira aquí, para que en memoria haya solo lo de las teselas que
    se están leyendo. Devuelve las lecturas de su núcleo, en px de `g`."""
    x0, y0, x1, y1 = tesela.recorte
    img = _escalar(g[y0:y1, x0:x1], escala)
    if variante == "bin":
        img = _binarizar(img, umbral)
    salida = []
    for d in _pasada_rotulos(img, escala, angulo, variante):
        d.update(x=d["x"] + x0, y=d["y"] + y0)
        if tesela.tiene(d["x"], d["y"]):
            salida.append(d)
    return salida


def orientaciones(lecturas: list[dict], alto_modal: float, sondeados=ANGULOS_SONDEO,
                  paso: int = PASO_GRADOS, ventana: float = VENTANA_ORIENTACION) -> list[int] | None:
    """Los ángulos (múltiplos de `paso`) que vale la pena leer, según las lecturas del
    sondeo (`sondeados`, en gris y en Otsu). Cuentan las lecturas "de lote", como en
    `seleccionar`: las que traen LOTE si hay al menos MIN_LOTE_SONDEO, si no los números
    de alto ≥ ALTO_SUELTO × el texto modal. Por ángulo se cuentan los pares: una lectura
    del gris con una del Otsu del mismo número a menos de RADIO_ALTOS altos. Un ángulo
    es una orientación de los rótulos si sus pares pasan el ruido (la mediana de los
    ángulos sondeados + RUIDO_SIGMAS × su raíz, y al menos MIN_SONDEO); se leen los
    ángulos a ± `ventana` de cada una. None si ningún ángulo pasa: no se sabe, se leen
    todos."""
    con_lote = sum(1 for d in lecturas if d["lote"]) >= MIN_LOTE_SONDEO
    utiles = [d for d in lecturas if (d["lote"] if con_lote else d["alto"] >= ALTO_SUELTO * alto_modal)]
    por_angulo = defaultdict(lambda: defaultdict(list))
    for d in utiles:
        por_angulo[int(round(d["ang"])) % 360][d["var"]].append(d)
    pares = Counter()
    for a, variantes in por_angulo.items():
        for d in variantes["gris"]:
            radio = RADIO_ALTOS * max(d["alto"], 1.0)
            if any(mismo_lote(d["numero"], o["numero"]) and hypot(d["x"] - o["x"], d["y"] - o["y"]) < radio
                   for o in variantes["bin"]):
                pares[a] += 1
    if not sondeados:
        return None
    piso = float(np.median([pares[a % 360] for a in sondeados]))
    umbral = max(MIN_SONDEO, piso + RUIDO_SIGMAS * piso ** 0.5)
    modos = [a for a in sondeados if pares[a % 360] >= umbral]
    if not modos:
        return None
    cerca = lambda a, b: min((a - b) % 360, (b - a) % 360) <= ventana
    return [a for a in range(0, 360, paso) if any(cerca(a, m) for m in modos)]


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


# --- avance retomable: una pasada terminada por archivo ----------------------------------
# Lo que `orientaciones` y `seleccionar` leen de cada lectura, con su tipo: una lectura
# guardada que no lo cumple invalida su pasada entera (se vuelve a leer).
CAMPOS_LECTURA = dict(numero=str, lote=bool, x=float, y=float, conf=float, ang=float, var=str,
                      escala=float, alto=float)


def _nombre_pasada(escalas, pasada) -> str:
    """Nombre estable de una pasada: por el índice de la escala (la escala misma es un
    float que no conviene poner en un nombre de archivo), la variante y el ángulo."""
    e, var, a = pasada
    return f"e{list(escalas).index(e)}-{var}-{int(a) % 360:03d}.json"


def _nativo(valor):
    """Valores de numpy a los de Python, para que el JSON no falle y vuelva igual."""
    if isinstance(valor, np.generic):
        return valor.item()
    return valor


def _lectura_valida(d) -> bool:
    # Un número que se guardó entero (45) vuelve como int: vale donde va un float. Un
    # bool, que en Python también es int, no.
    return isinstance(d, dict) and all(
        (isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool)) if tipo is float
        else isinstance(d.get(k), tipo)
        for k, tipo in CAMPOS_LECTURA.items())


def _cargar_pasada(ruta) -> list[dict] | None:
    """Las lecturas guardadas de una pasada, o None si el archivo falta o no se entiende
    (cortado a mitad, editado, de otra versión): esa pasada se lee de nuevo."""
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(datos, list) or not all(_lectura_valida(d) for d in datos):
        return None
    return datos


def _guardar_pasada(ruta: str, lecturas: list[dict]) -> None:
    """Escritura atómica (temporal en la misma carpeta + `os.replace`): si la instancia
    muere a mitad, queda el archivo anterior o ninguno, nunca uno a medias."""
    carpeta = os.path.dirname(ruta)
    # En un despliegue la revisión vieja y la nueva leen a la vez un rato; si la vieja
    # termina primero borra `lector-avance/` y la nueva no puede caerse por eso.
    os.makedirs(carpeta, exist_ok=True)
    fd, temporal = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=carpeta)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump([{k: _nativo(v) for k, v in d.items()} for d in lecturas], f)
        os.replace(temporal, ruta)
    except BaseException:
        try:
            os.unlink(temporal)
        except OSError:
            pass
        raise


def leer(imagen: np.ndarray, ppmm: float | None = None, avance=print, hebras: int | None = None,
         paso: int = PASO_GRADOS, sondeo=ANGULOS_SONDEO, avance_en=None) -> list[Rotulo]:
    """Los números de lote de `imagen` (RGB o gris: el dibujo, con las máscaras ya
    tapadas). Posiciones en px de `imagen`. `ppmm` no lo usa Tesseract (el método se
    ajusta solo al alto del texto); está en la interfaz para otros lectores.

    Primero el sondeo (`sondeo`: ángulos que se leen a la escala del texto, en gris y
    Otsu; vacío lo salta) dice en qué orientaciones están los rótulos (`orientaciones`);
    después se leen solo los ángulos cercanos, a las dos escalas y en gris y Otsu. Cada
    pasada va por teselas (`teselas`) y las hebras se cuentan con la tesela más grande
    agrandada y girada a 45° (`memoria_pasada`).

    `avance_en`: carpeta donde cada pasada terminada se guarda como JSON y de donde se
    retoman las que ya estén (ver el docstring del módulo). La carpeta tiene que ser
    propia de esta imagen: quien llama la elige por una huella de lo que se lee."""
    motivo = motivo_no_disponible()
    if motivo:
        avance(motivo)
        return []
    try:
        inicio = time.time()
        g = gris_normalizado(imagen)
        alto = alto_caracter(g)
        e1 = ALTO_TEXTO_PX / alto
        escalas = (e1, e1 / ESCALA_GRANDE)
        por_escala = {e: teselas(g.shape[0], g.shape[1], e, TESELA_MPX, MARGEN_TESELA_ALTOS) for e in escalas}
        umbrales = {e: umbral_otsu(g, e, por_escala[e]) for e in escalas}
        angulos = list(range(0, 360, paso))
        todas = [(e, var, a) for e in escalas for var in ("gris", "bin") for a in angulos]
        primero = [(e1, var, a) for var in ("gris", "bin") for a in angulos if a in set(sondeo)]

        def tareas_de(pasadas):
            tareas, grupos = [], []
            for p in pasadas:
                e, var, a = p
                for t in por_escala[e]:
                    tareas.append((_pasada_tesela, g, t, e, float(a), var, umbrales[e]))
                    grupos.append(p)
            return tareas, grupos

        def memoria(e, t, a):
            x0, y0, x1, y1 = t.recorte
            return memoria_pasada((x1 - x0) * e, (y1 - y0) * e, a)

        # La pasada más grande: la tesela más grande, girada a 45°.
        pico = max(memoria(e, t, 45) for e in escalas for t in por_escala[e])
        n = _hebras(hebras, len(todas) * len(por_escala[e1]), pico)
        avance(f"Rótulos: texto típico de {alto:.0f} px; hasta {len(todas)} pasadas de Tesseract en {n} hebras,"
               f" por teselas ({len(por_escala[e1])} por pasada, de hasta {TESELA_MPX:.0f} Mpx)")
        guardadas, al_completar = {}, None
        if avance_en is not None:
            avance_en = str(avance_en)
            try:
                os.makedirs(avance_en, exist_ok=True)
            except OSError as error:       # sin carpeta se lee igual, solo que no se retoma
                avance(f"Rótulos: no se pudo guardar el avance ({error}); se sigue sin guardarlo")
                avance_en = None
        if avance_en is not None:
            for p in todas:
                leidas = _cargar_pasada(os.path.join(avance_en, _nombre_pasada(escalas, p)))
                if leidas is not None:
                    guardadas[p] = leidas
            if guardadas:
                avance(f"Rótulos: se retoman {len(guardadas)} pasadas ya leídas")

            def al_completar(p, leidas):
                _guardar_pasada(os.path.join(avance_en, _nombre_pasada(escalas, p)), leidas)

        def correr(pasadas, **contar):
            """Las pasadas que faltan; las guardadas se suman a las lecturas y a las
            `previas` del contador, que así parte donde quedó y nunca pasa de Y."""
            hechas = [p for p in pasadas if p in guardadas]
            tareas, grupos = tareas_de([p for p in pasadas if p not in guardadas])
            previas = contar.pop("previas", 0) + len(hechas)
            leidas = [d for p in hechas for d in guardadas[p]]
            return leidas + _correr(tareas, n, avance, "Rótulos", grupos, previas=previas, inicio=inicio,
                                    al_completar=al_completar, **contar)

        lecturas = []
        if primero:
            lecturas = correr(primero, total=len(todas))
            elegidos = orientaciones(lecturas, alto, sorted({a for _, _, a in primero}), paso)
            if elegidos is None:
                avance("Rótulos: el sondeo no encontró la orientación de los rótulos; se leen todos los ángulos")
                elegidos = angulos
            resto = [p for p in todas if p[2] in elegidos and p not in primero]
            avance(f"Rótulos: orientaciones de los rótulos {', '.join(f'{a}°' for a in elegidos)};"
                   f" se leen {len(primero) + len(resto)} pasadas de {len(todas)}")
        else:
            resto = todas
        lecturas += correr(resto, previas=len(primero), total=len(primero) + len(resto))
        del g
        hechas = len(primero) + len(resto)
        rotulos = seleccionar(lecturas, alto, hechas)
        avance(f"Rótulos: {len(rotulos)} números leídos ({sum(r.apoyo >= APOYO_MIN for r in rotulos)}"
               f" con apoyo ≥ {APOYO_MIN}) en {time.time() - inicio:.0f} s")
        return rotulos
    except Exception as error:             # noqa: BLE001 - el lector nunca tumba digitalizar
        avance(f"El lector de rótulos falló ({error}); se sigue sin él")
        return []


# ------------------------------------------------------------------------- semillas
def combinar(usuario, lector: list[Rotulo], radio: float, apoyo_min: int = APOYO_MIN,
             poligonos=(), oficiales=(), restos=()) -> list[dict]:
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

    Con cuadro, un número leído con otro sector que el del cuadro se corrige antes
    (`numeros.segun_cuadro`: "6-09" es el "8-09"). `oficiales` son los lotes del cuadro,
    sin el resto de la propiedad; `restos`, su número ("8"): el resto que numeró ella no
    descarta la lectura del "8-08". Y el lector no numera el resto: si va al KMZ lo decide
    ella (Numerar le pregunta). En Caminos de Rapel el lector lee el "8" del resto con
    apoyo 4, y sin esto el resto entraba al KMZ como "LOTE 8" sin preguntarle.

    Devuelve [{"numero", "x", "y", "origen": "usuario"|"lector", "confianza", "apoyo"}].
    """
    if oficiales:
        lector = [replace(r, numero=segun_cuadro(r.numero, oficiales)) for r in lector]
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
    del_resto = {clave(n) for n in restos}
    for r in sorted(lector, key=lambda r: (-r.apoyo, -r.confianza)):
        if (r.apoyo < apoyo_min or clave(r.numero) in del_resto
                or any(mismo_lote(r.numero, n, restos) for n in numeros)):
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
        # Las franjas se leen a 0/90/180/270°: girada, la imagen no crece.
        pico = max((memoria_pasada(t[1].shape[1], t[1].shape[0], 0) for t in tareas), default=0)
        lecturas = _correr(tareas, _hebras(hebras, len(tareas), pico), avance, "Cuadrícula")
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
# La fila del resto de la propiedad, cuando se lee la palabra.
RE_RESTO = re.compile(r"\bresto\b", re.I)
# Una celda numérica y, si viene pegada o a un espacio, su unidad ("5.000m2", "5,00 hás").
RE_CELDA = re.compile(r"(\d+(?:[.,]\d+)*)(\s?(?:m2|m²|mts?2|h[aá]s?\b|hect\w*))?", re.I)


def filas_cuadro(texto: str) -> list[list[str]]:
    """Filas del cuadro: [lote, celda, ..., total]. Las líneas que empiezan con un
    número de lote ("12" o "8-01", como está impreso; no 0) seguido de al menos una
    celda, la última con forma de área ('5,00', '5.000', '5.000,50', '5000', con o sin
    unidad: '5.000 m2'; no '222'). Las celdas llevan su unidad si la trae."""
    salida = []
    # Una fila alta parte en dos líneas: el número solo arriba y las celdas abajo, sin
    # número ("8 / o resto de la propiedad / 0.000 m2 760.000 m2" en Caminos de Rapel, que
    # Tesseract lee "8" y "s 0.000m2 760.000m2"). Sin esto el resto no llegaba al cuadro.
    solo, sin_digitos = None, 0
    for linea in (texto or "").splitlines():
        m = RE_LOTE_FILA.match(linea)
        if m and not any(int(d) for d in re.findall(r"\d+", m.group(1))[-1:]):
            m = None
        celdas = [c.group(0).strip() for c in RE_CELDA.finditer(linea, m.end() if m else 0)]
        con_area = bool(celdas) and RE_AREA.fullmatch(RE_CELDA.match(celdas[-1]).group(1))
        if m and con_area:
            salida.append([m.group(1)] + celdas)
            solo = None
        elif m and not linea[m.end():].strip(" .:"):
            solo, sin_digitos = m.group(1), 0
        elif con_area and (solo or RE_RESTO.search(linea)):
            # Sin número arriba, la fila que dice "resto" va con ese nombre.
            salida.append([solo or "Resto"] + celdas)
            solo = None
        elif solo and not re.search(r"\d", linea) and sin_digitos < 3:
            sin_digitos += 1          # "o resto", "de la", "propiedad": la misma fila
        else:
            solo = None
    return salida


def _lote_de_fila(texto: str) -> str:
    """'012' → '12'; '8-01' y 'Resto' quedan como están impresos (así salen en el KMZ)."""
    return texto if "-" in texto or not texto.isdigit() else str(int(texto))


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
