/**
 * Crea tu KMZ: unir las hojas de un plano (paso 1, "El loteo está en varias hojas").
 * Ver docs/specs/2026-10-06-kmz-unir-hojas.md.
 *
 * Arriba, la geometría de `pipeline/plano/union.py`, fórmula por fórmula y sin DOM:
 * un punto p de la hoja girada va a R(angulo)·k·(p − c) + (x, y) − origen. La pantalla
 * y el servidor tienen que ver la misma unión, por eso `kmz_union.test.js` y
 * `test_plano_union.py` prueban los mismos números.
 *
 * Abajo, el editor (`EditorUnion`): su propio canvas sobre el visor del paso 1 y el
 * panel "Une las hojas". Trabaja en px de unión **sin restar el origen** (el "mundo"):
 * ahí viven x e y de cada hoja, y el origen solo importa al componer, en el servidor.
 */
import { aPagina, aPantalla, girarPunto, matrizRotacion, vistaAjustada, zoomEn } from './kmz_geometria.js';

// Los topes de union.py y pagina.py: la pantalla avisa lo mismo que diría el servidor.
export const MAX_MEGAPIXELES = 250;
export const MIN_HOJAS = 2;
export const MAX_HOJAS = 12;
export const GIRO_FINO = 5;                 // la pantalla deja ±5°; union.py acepta ±10
const TOLERANCIA_ESCALA = 1e-6;
const TOLERANCIA_PX = 1e-6;
const PPMM_TRABAJO_MAXIMO = 8.0;
// math.radians de Python multiplica por pi/180 ya calculado: así salen los mismos bits.
const GRADO = Math.PI / 180;

// --- geometría (la de union.py) ------------------------------------------------------

/** [ancho, alto] de la hoja ya girada (`union._girado`). */
export function tamanoGirado(ancho, alto, rotacion) {
  return rotacion % 180 ? [alto, ancho] : [ancho, alto];
}

/** El punto (px, py) de una hoja girada de ancho×alto, en px de la unión (`union.transformar_punto`). */
export function transformarPunto(px, py, ancho, alto, k, angulo, x, y, ox = 0, oy = 0) {
  const a = angulo * GRADO;
  const cos = Math.cos(a);
  const sen = Math.sin(a);
  const dx = k * (px - (ancho - 1) / 2);
  const dy = k * (py - (alto - 1) / 2);
  return [cos * dx - sen * dy + x - ox, sen * dx + cos * dy + y - oy];
}

/**
 * La misma transformación como matriz de canvas [a, b, c, d, e, f], sin el origen:
 * X = a·px + c·py + e, Y = b·px + d·py + f (`union._matriz`).
 */
export function matrizHoja(ancho, alto, k, angulo, x, y) {
  const a = angulo * GRADO;
  const cos = Math.cos(a);
  const sen = Math.sin(a);
  const cx = (ancho - 1) / 2;
  const cy = (alto - 1) / 2;
  return [k * cos, k * sen, -k * sen, k * cos, x - k * (cos * cx - sen * cy), y - k * (sen * cx + cos * cy)];
}

export const aplicar = (m, px, py) => [m[0] * px + m[2] * py + m[4], m[1] * px + m[3] * py + m[5]];

export function invertir(m) {
  const [a, b, c, d, e, f] = m;
  const det = a * d - b * c;
  return [d / det, -b / det, -c / det, a / det, (c * f - d * e) / det, (b * e - a * f) / det];
}

/** Las esquinas de un recorte: los centros de sus píxeles extremos (`union._esquinas`). */
export function esquinasRecorte([x0, y0, x1, y1]) {
  return [[x0, y0], [x1 - 1, y0], [x1 - 1, y1 - 1], [x0, y1 - 1]];
}

/** El ruido de redondeo de un giro de 0° no debe sumar un píxel en floor/ceil (`union._pegar`). */
export function pegar(v) {
  const cerca = Math.round(v);
  return Math.abs(v - cerca) < TOLERANCIA_PX ? cerca : v;
}

/** k de la hoja: 1 exacto si las resoluciones difieren en ruido (`union._escala`). */
export function escala(ppmmUnion, ppmmHoja) {
  const k = ppmmUnion / ppmmHoja;
  return Math.abs(k - 1) < TOLERANCIA_ESCALA ? 1 : k;
}

// `tamanos` y `ppmms` llegan como objeto (n → …, como en los casos de Python) o como Map.
const de = (mapa, n) => (mapa instanceof Map ? mapa.get(n) : mapa[n]);

/** ppmm de la unión: el de la hoja más fina, sin pasar del de trabajo. */
export function ppmmDeUnion(hojas, ppmms) {
  return Math.min(Math.max(...hojas.map((h) => Number(de(ppmms, h.n)))), PPMM_TRABAJO_MAXIMO);
}

/**
 * Cada hoja con su tamaño girado, su k, su recorte (el entero si es null) y su matriz
 * hoja → mundo (sin el origen). Es lo que el editor dibuja; `geometria` le resta el origen.
 */
export function hojasColocadas(hojas, tamanos, ppmms) {
  if (!hojas.length) return [];
  const ppmm = ppmmDeUnion(hojas, ppmms);
  return hojas.map((h) => {
    const [ancho, alto] = tamanoGirado(...de(tamanos, h.n), h.rotacion ?? 0);
    const recorte = h.recorte ?? [0, 0, ancho, alto];
    const k = escala(ppmm, Number(de(ppmms, h.n)));
    return { n: h.n, ancho, alto, ppmm: Number(de(ppmms, h.n)), k, recorte,
      matriz: matrizHoja(ancho, alto, k, h.angulo ?? 0, h.x, h.y) };
  });
}

/**
 * La geometría de la unión (`union.geometria`): origen, ancho, alto, ppmm y, por hoja,
 * la matriz hoja girada → px de unión ya con el origen restado. Falla como en Python
 * si un recorte se sale o si la unión pasa de MAX_MEGAPIXELES.
 */
export function geometria(hojas, tamanos, ppmms) {
  const ppmm = ppmmDeUnion(hojas, ppmms);
  const colocadas = hojasColocadas(hojas, tamanos, ppmms);
  const esquinas = [];
  for (const c of colocadas) {
    if (c.recorte[2] > c.ancho || c.recorte[3] > c.alto) throw new Error(`la hoja ${c.n}: el recorte se sale de la hoja`);
    for (const [px, py] of esquinasRecorte(c.recorte)) esquinas.push(aplicar(c.matriz, px, py).map(pegar));
  }
  const ox = Math.floor(Math.min(...esquinas.map((p) => p[0])));
  const oy = Math.floor(Math.min(...esquinas.map((p) => p[1])));
  const ancho = Math.ceil(Math.max(...esquinas.map((p) => p[0]))) - ox + 1;
  const alto = Math.ceil(Math.max(...esquinas.map((p) => p[1]))) - oy + 1;
  if (ancho * alto > MAX_MEGAPIXELES * 1e6) {
    throw new Error(`La unión es demasiado grande (${Math.round(ancho * alto / 1e6)} MP; el tope es `
      + `${MAX_MEGAPIXELES}): recorta las hojas a su dibujo`);
  }
  return {
    origen: [ox, oy], ancho, alto, ppmm,
    hojas: colocadas.map((c) => {
      const [a, b, cc, d, e, f] = c.matriz;
      return { ...c, matriz: [a, b, cc, d, e - ox, f - oy] };
    }),
  };
}

/** Un punto de la unión (o del mundo, con una matriz sin origen) en px de la hoja girada. */
export const aHoja = (matriz, X, Y) => aplicar(invertir(matriz), X, Y);

/** ¿El punto de mundo (X, Y) cae en un píxel del recorte de la hoja colocada? */
export function dentro(colocada, X, Y) {
  const [x, y] = aHoja(colocada.matriz, X, Y);
  const [x0, y0, x1, y1] = colocada.recorte;
  return x >= x0 - 0.5 && x < x1 - 0.5 && y >= y0 - 0.5 && y < y1 - 0.5;
}

/** La hoja de más arriba que tiene (X, Y) dentro de su recorte, o null. `colocadas` va de abajo hacia arriba. */
export function hojaEn(colocadas, X, Y) {
  for (let i = colocadas.length - 1; i >= 0; i -= 1) {
    if (dentro(colocadas[i], X, Y)) return colocadas[i].n;
  }
  return null;
}

/** Los bordes del recorte (no los centros de píxel) en el mundo: lo que se ve y se toca. */
export function bordesRecorte(colocada) {
  const [x0, y0, x1, y1] = colocada.recorte;
  return [[x0 - 0.5, y0 - 0.5], [x1 - 0.5, y0 - 0.5], [x1 - 0.5, y1 - 0.5], [x0 - 0.5, y1 - 0.5]]
    .map(([x, y]) => aplicar(colocada.matriz, x, y));
}

/** [x0, y0, x1, y1] del mundo que encierra los recortes de las hojas colocadas. */
export function cajaDe(colocadas) {
  const puntos = colocadas.flatMap(bordesRecorte);
  if (!puntos.length) return null;
  const xs = puntos.map((p) => p[0]);
  const ys = puntos.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

/**
 * Mueve la manilla `i` del recorte (0 arriba-izquierda, 1 arriba-derecha, 2 abajo-derecha,
 * 3 abajo-izquierda) al punto (hx, hy) de la hoja girada. La esquina opuesta no se mueve,
 * el recorte queda en enteros, dentro de la hoja y de al menos `minimo` px por lado.
 */
export function moverManilla(recorte, i, hx, hy, ancho, alto, minimo = 1) {
  let [x0, y0, x1, y1] = recorte ?? [0, 0, ancho, alto];
  // La manilla está en el borde del píxel (x − ½): el borde más cercano es round(h + ½).
  const bx = Math.round(hx + 0.5);
  const by = Math.round(hy + 0.5);
  const entre = (v, a, b) => Math.min(Math.max(v, a), b);
  if (i === 0 || i === 3) x0 = entre(bx, 0, x1 - minimo); else x1 = entre(bx, x0 + minimo, ancho);
  if (i === 0 || i === 1) y0 = entre(by, 0, y1 - minimo); else y1 = entre(by, y0 + minimo, alto);
  return [x0, y0, x1, y1];
}

/** El recorte entero es `null`, como lo guarda union.py. */
export const recorteNormal = (r, ancho, alto) => (r && (r[0] || r[1] || r[2] !== ancho || r[3] !== alto) ? r : null);

/**
 * El recorte de una hoja que pasa de la rotación `de` a `a`: el mismo trozo de papel en
 * los px de la hoja con el nuevo giro. `ancho` y `alto` son los de la página sin girar.
 */
export function girarRecorte(recorte, de, a, ancho, alto) {
  if (!recorte) return null;
  const [x0, y0, x1, y1] = recorte;
  const p = girarPunto(x0, y0, de, a, ancho, alto);
  const q = girarPunto(x1 - 1, y1 - 1, de, a, ancho, alto);
  return [Math.min(p[0], q[0]), Math.min(p[1], q[1]), Math.max(p[0], q[0]) + 1, Math.max(p[1], q[1]) + 1];
}

/**
 * Las hojas una al lado de la otra, en orden de página y sin traslaparse: el punto de
 * partida al abrir el editor sin unión. `paginas`: [{n, ancho, alto}] sin girar.
 */
export function colocarAlLado(paginas, rotacion = 0) {
  const tamanos = paginas.map((p) => tamanoGirado(p.ancho, p.alto, rotacion));
  const separacion = Math.round(0.03 * Math.max(...tamanos.map((t) => t[0])));
  let cursor = 0;
  return paginas.map((p, i) => {
    const [ancho, alto] = tamanos[i];
    const hoja = { n: p.n, rotacion, angulo: 0, x: cursor + (ancho - 1) / 2, y: (alto - 1) / 2, recorte: null };
    cursor += ancho + separacion;
    return hoja;
  });
}

/** Sube (`delta` +1, queda más encima) o baja (−1) la hoja `n` en el orden de abajo hacia arriba. */
export function moverEnOrden(hojas, n, delta) {
  const i = hojas.findIndex((h) => h.n === n);
  const j = i + delta;
  if (i < 0 || j < 0 || j >= hojas.length) return hojas;
  const lista = [...hojas];
  [lista[i], lista[j]] = [lista[j], lista[i]];
  return lista;
}

/** Una hoja como la guarda `entradas.union.hojas[]`. */
export const aDic = (h) => ({ n: h.n, rotacion: h.rotacion, angulo: h.angulo, x: h.x, y: h.y, recorte: h.recorte ?? null });

/** "0,35°", "−1,20°": como se lee en el panel. */
export const textoGrados = (v) => `${v < -0.004 ? '−' : ''}${Math.abs(v).toFixed(2).replace('.', ',')}°`;

// --- el editor -------------------------------------------------------------------------

const VIOLETA = '#7c3aed';
const GRIS = '#a1a1aa';
const UMBRAL_ARRASTRE = 4;      // px de pantalla: menos que esto es un toque
const RADIO_MANILLA = 14;       // px de pantalla donde se agarra una manilla
const RECORTE_MINIMO = 16;      // px de hoja: un recorte más chico no se ve ni se agarra

/**
 * El editor de la unión: dibuja en `canvas` (dentro de `contenedor`, el visor del paso
 * 1) y arma las filas de `panel`. Quien lo usa le da:
 * - `alAfinar({hojas})`: la respuesta de POST …/union/afinar;
 * - `alUsar({hojas, cuadro})`, `alVolver()`, `alCancelar()`: los botones del pie;
 * - `alError(error)`: para avisar lo que falló.
 */
export class EditorUnion {
  constructor({ contenedor, canvas, panel }) {
    this.contenedor = contenedor;
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.panel = panel;
    this.lista = panel.querySelector('#kmz-union-hojas');
    this.abierto = false;
    this.sesion = 0;              // cambia al abrir: una respuesta de Afinar vieja no se aplica
    this.paginas = new Map();     // n → {ancho, alto, ppmm} sin girar
    this.hojas = [];              // todas las páginas, de abajo hacia arriba: {n, usar, rotacion, angulo, x, y, recorte}
    this.elegida = null;
    this.recortando = false;
    this.arrastrando = false;
    this.afinando = false;
    this.usando = false;          // "Usar la unión" esperando al servidor: un segundo clic no guarda dos veces
    this.calce = new Map();       // n → {calzada, residuo_mm} de la última vez que se afinó
    this.cuadro = null;
    this.rotacionesIniciales = new Map();
    this.imagenes = new Map();
    this.vista = { escala: 1, dx: 0, dy: 0 };
    this.punteros = new Map();
    this.gesto = null;
    this.pendiente = 0;
    this.alAfinar = async () => ({ hojas: [] });
    this.alUsar = () => {};
    this.alVolver = () => {};
    this.alCancelar = () => {};
    this.alError = () => {};

    new ResizeObserver(() => { if (this.abierto) this.medir(); }).observe(contenedor);
    canvas.addEventListener('pointerdown', (e) => this.bajar(e));
    canvas.addEventListener('pointermove', (e) => this.mover(e));
    canvas.addEventListener('pointerup', (e) => this.subir(e));
    canvas.addEventListener('pointercancel', (e) => this.soltar(e));
    canvas.addEventListener('wheel', (e) => this.rueda(e), { passive: false });
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('keydown', (e) => this.tecla(e));
    panel.addEventListener('click', (e) => {
      const nodo = e.target.closest('[data-union]');
      if (!nodo || nodo.disabled || nodo.type === 'checkbox' || nodo.type === 'range') return;
      Promise.resolve(this.accion(nodo.dataset.union, Number(nodo.closest('[data-hoja]')?.dataset.hoja)))
        .catch((error) => this.alError(error));
    });
    panel.addEventListener('change', (e) => {
      if (e.target.dataset.union !== 'usar') return;
      this.usar(Number(e.target.closest('[data-hoja]').dataset.hoja), e.target.checked);
    });
    panel.addEventListener('input', (e) => {
      if (e.target.dataset.union !== 'angulo') return;
      const n = Number(e.target.closest('[data-hoja]').dataset.hoja);
      this.cambiarHoja(n, { angulo: Number(e.target.value) });
      e.target.closest('[data-hoja]').querySelector('output').textContent = textoGrados(Number(e.target.value));
    });
  }

  /**
   * Abre el editor. `paginas`: [{n, ancho, alto, ppmm?}] sin girar; `union`: la guardada
   * (o null); `rotacion`: el giro con que se ponen las hojas si no hay unión;
   * `urlImagen(n)`: la imagen media de la página.
   */
  abrir({ paginas, union = null, rotacion = 0, urlImagen }) {
    this.sesion += 1;
    this.abierto = true;
    this.recortando = false;
    this.arrastrando = false;
    this.afinando = false;
    this.usando = false;
    this.calce = new Map();
    this.gesto = null;
    this.punteros.clear();
    // Sin ppmm en el estado, todas iguales: k = 1, como en los planos del CBR.
    this.paginas = new Map(paginas.map((p) => [p.n, { ancho: p.ancho, alto: p.alto, ppmm: p.ppmm ?? 1 }]));
    const guardadas = (union?.hojas ?? []).filter((h) => this.paginas.has(h.n));
    if (guardadas.length >= MIN_HOJAS) {
      this.hojas = guardadas.map((h) => ({ ...aDic(h), usar: true }));
      // Las páginas que no estaban en la unión quedan apagadas, a la derecha de todo y
      // con el giro de 90° que más se repite en las usadas (las láminas suelen venir igual).
      const veces = new Map();
      for (const h of guardadas) veces.set(h.rotacion, (veces.get(h.rotacion) ?? 0) + 1);
      const giro = [...veces].sort((a, b) => b[1] - a[1])[0][0];
      const caja = cajaDe(this.colocadas());
      let cursor = caja ? caja[2] + 200 : 0;
      for (const p of paginas) {
        if (guardadas.some((h) => h.n === p.n)) continue;
        const [ancho, alto] = tamanoGirado(p.ancho, p.alto, giro);
        this.hojas.push({ n: p.n, usar: false, rotacion: giro, angulo: 0, x: cursor + (ancho - 1) / 2, y: (alto - 1) / 2, recorte: null });
        cursor += ancho + 200;
      }
      this.cuadro = union.cuadro ?? null;
    } else {
      this.hojas = colocarAlLado(paginas, rotacion).map((h, i) => ({ ...h, usar: i < MAX_HOJAS }));
      this.cuadro = null;
    }
    this.rotacionesIniciales = new Map(this.hojas.map((h) => [h.n, h.rotacion]));
    this.elegida = this.hojas.find((h) => h.usar)?.n ?? null;
    // Las imágenes de páginas que ya no están (otro PDF con menos hojas) se sueltan.
    for (const n of [...this.imagenes.keys()]) if (!this.paginas.has(n)) this.imagenes.delete(n);
    for (const p of paginas) this.cargarImagen(p.n, urlImagen(p.n));
    this.pintarPanel();
    requestAnimationFrame(() => { this.medir(); this.ajustar(); });
  }

  cerrar() {
    this.abierto = false;
    this.sesion += 1;
    this.gesto = null;
    this.punteros.clear();
  }

  cargarImagen(n, url) {
    const actual = this.imagenes.get(n);
    if (actual?.url === url) return;
    const registro = { url, imagen: null };
    this.imagenes.set(n, registro);
    const imagen = new Image();
    imagen.decoding = 'async';
    imagen.onload = () => {
      if (this.imagenes.get(n) !== registro) return;
      registro.imagen = imagen;
      this.redibujar();
    };
    imagen.onerror = () => this.imagenes.get(n) === registro && this.abierto && this.alError(new Error(`No se pudo cargar la imagen de la hoja ${n}.`));
    imagen.src = url;
  }

  // --- estado -------------------------------------------------------------------------

  hoja(n) { return this.hojas.find((h) => h.n === n) ?? null; }

  usadas() { return this.hojas.filter((h) => h.usar); }

  tamanos() { return new Map([...this.paginas].map(([n, p]) => [n, [p.ancho, p.alto]])); }

  ppmms() { return new Map([...this.paginas].map(([n, p]) => [n, p.ppmm])); }

  colocadas() { return hojasColocadas(this.usadas(), this.tamanos(), this.ppmms()); }

  /** Un cambio a una hoja: lo que dijo Afinar de ella ya no vale. */
  cambiarHoja(n, cambios) {
    const h = this.hoja(n);
    if (!h) return;
    Object.assign(h, cambios);
    this.calce.delete(n);
    this.redibujar();
  }

  elegir(n) {
    if (this.elegida === n) return;
    this.elegida = n;
    this.recortando = false;
    this.pintarPanel();
    this.redibujar();
  }

  usar(n, si) {
    const h = this.hoja(n);
    if (!h) return;
    const usadas = this.usadas().length;
    // La casilla ya viene apagada en esos casos; esto cubre un doble clic rápido.
    if ((!si && usadas <= MIN_HOJAS) || (si && usadas >= MAX_HOJAS)) { this.pintarPanel(); return; }
    h.usar = si;
    this.calce.clear();
    // Sigue elegida aunque se apague: en el celular su fila queda abierta para volver a encenderla.
    this.elegida = n;
    this.recortando = false;
    this.pintarPanel();
    this.redibujar();
  }

  async accion(que, n) {
    if (que === 'elegir') return this.elegir(n);
    if (que === 'izq' || que === 'der') return this.girar90(n, que === 'izq' ? -90 : 90);
    if (que === 'recortar') {
      // "Recortar" en otra hoja empieza a recortar esa; solo el "Listo" de la que se recorta termina.
      this.recortando = !(this.recortando && this.elegida === n);
      this.elegida = n;
      this.pintarPanel();
      return this.redibujar();
    }
    if (que === 'subir' || que === 'bajar') {
      this.hojas = moverEnOrden(this.hojas, n, que === 'subir' ? 1 : -1);
      this.calce.clear();
      this.pintarPanel();
      return this.redibujar();
    }
    if (que === 'afinar') return this.afinar();
    if (que === 'usar-union') return this.usarUnion();
    if (que === 'volver') return this.alVolver();
    if (que === 'cancelar') return this.alCancelar();
    return undefined;
  }

  /** Gira la hoja 90° alrededor de su centro: x e y no cambian, el recorte gira con ella. */
  girar90(n, grados) {
    const h = this.hoja(n);
    const p = this.paginas.get(n);
    if (!h || !p) return;
    const a = (((h.rotacion + grados) % 360) + 360) % 360;
    const recorte = girarRecorte(h.recorte, h.rotacion, a, p.ancho, p.alto);
    this.cambiarHoja(n, { rotacion: a, recorte });
    this.elegida = n;
    this.pintarPanel();
  }

  async afinar() {
    if (this.afinando) return;
    const sesion = this.sesion;
    this.afinando = true;
    this.recortando = false;
    this.pintarPanel();
    const pedidas = JSON.stringify(this.usadas().map(aDic));
    try {
      const respuesta = await this.alAfinar({ hojas: JSON.parse(pedidas) });
      if (sesion !== this.sesion) return;
      // Si mientras tanto movió, giró o apagó una hoja, la respuesta es de otra unión:
      // aplicarla desharía lo que hizo.
      if (JSON.stringify(this.usadas().map(aDic)) !== pedidas) {
        this.alError(new Error('Cambiaste las hojas mientras se afinaba: vuelve a pulsar Afinar.'));
        return;
      }
      for (const r of respuesta?.hojas ?? []) {
        const h = this.hoja(r.n);
        if (!h) continue;
        Object.assign(h, { x: r.x, y: r.y, angulo: r.angulo });
        this.calce.set(r.n, { calzada: Boolean(r.calzada), residuo_mm: r.residuo_mm ?? null });
      }
    } finally {
      if (sesion === this.sesion) {
        this.afinando = false;
        this.pintarPanel();
        this.redibujar();
      }
    }
  }

  /** Lo que se guarda en `entradas.union`. Falla antes de guardar si queda demasiado grande. */
  union() {
    const usadas = this.usadas();
    if (usadas.length < MIN_HOJAS) throw new Error(`Elige al menos ${MIN_HOJAS} hojas para unirlas.`);
    geometria(usadas, this.tamanos(), this.ppmms());
    // El cuadro de superficies está en px de su hoja girada: sirve si la hoja sigue
    // usada y con el mismo giro de 90°.
    const c = this.cuadro;
    const vale = c && usadas.some((h) => h.n === c.hoja && h.rotacion === this.rotacionesIniciales.get(c.hoja));
    return { hojas: usadas.map(aDic), cuadro: vale ? c : null };
  }

  async usarUnion() {
    if (this.usando) return;
    const union = this.union();
    this.usando = true;
    this.pintarPanel();
    try {
      await this.alUsar(union);
    } finally {
      this.usando = false;
      this.pintarPanel();
    }
  }

  // --- vista --------------------------------------------------------------------------

  medir() {
    const { clientWidth: W, clientHeight: H } = this.contenedor;
    if (!W || !H) return;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(W * dpr);
    this.canvas.height = Math.round(H * dpr);
    this.canvas.style.width = `${W}px`;
    this.canvas.style.height = `${H}px`;
    this.redibujar();
  }

  ajustar() {
    const caja = cajaDe(this.colocadas());
    const { clientWidth: W, clientHeight: H } = this.contenedor;
    if (!caja || !W) return;
    const v = vistaAjustada(caja[2] - caja[0], caja[3] - caja[1], W, H);
    this.vista = { escala: v.escala, dx: v.dx - caja[0] * v.escala, dy: v.dy - caja[1] * v.escala };
    this.redibujar();
  }

  acercar(factor, sx = this.contenedor.clientWidth / 2, sy = this.contenedor.clientHeight / 2) {
    const caja = cajaDe(this.colocadas());
    const { clientWidth: W, clientHeight: H } = this.contenedor;
    const minimo = caja ? 0.25 * Math.min(W / (caja[2] - caja[0]), H / (caja[3] - caja[1])) : 0.001;
    this.vista = zoomEn(this.vista, factor, sx, sy, minimo, 8);
    this.redibujar();
  }

  redibujar() {
    if (this.pendiente || !this.abierto) return;
    this.pendiente = requestAnimationFrame(() => {
      this.pendiente = 0;
      this.pintar();
    });
  }

  pintar() {
    const { ctx, canvas } = this;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#e4e4e7';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    const colocadas = this.colocadas();
    for (const c of colocadas) {
      const elegida = c.n === this.elegida;
      // Recortando, la hoja entera se ve tenue: así se puede volver a agrandar el recorte.
      if (elegida && this.recortando) this.pintarHoja(c, null, 0.3, dpr);
      this.pintarHoja(c, c.recorte, elegida && this.arrastrando ? 0.5 : 1, dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // Los bordes van después de todas las hojas: el de una hoja tapada también se ve.
    for (const c of colocadas) if (c.n !== this.elegida) this.contorno(c, GRIS, 1.5);
    const elegida = colocadas.find((c) => c.n === this.elegida);
    if (elegida) {
      this.contorno(elegida, VIOLETA, 2.5, this.recortando ? [6, 4] : []);
      const esquinas = bordesRecorte(elegida).map(([X, Y]) => aPantalla(this.vista, X, Y));
      if (this.recortando) for (const q of esquinas) this.manilla(q);
      this.rotulo(`Hoja ${elegida.n}`, esquinas);
    }
  }

  pintarHoja(c, recorte, alfa, dpr) {
    const { ctx } = this;
    const { escala: s, dx, dy } = this.vista;
    const p = this.paginas.get(c.n);
    const h = this.hoja(c.n);
    ctx.save();
    ctx.globalAlpha = alfa;
    ctx.setTransform(dpr * s, 0, 0, dpr * s, dpr * dx, dpr * dy);
    ctx.transform(...c.matriz);
    if (recorte) {
      const [x0, y0, x1, y1] = recorte;
      ctx.beginPath();
      ctx.rect(x0 - 0.5, y0 - 0.5, x1 - x0, y1 - y0);
      ctx.clip();
    }
    const imagen = this.imagenes.get(c.n)?.imagen;
    if (imagen) {
      // La imagen media es la página sin girar, más chica: se estira a sus px de página
      // (el píxel i cubre [i − ½, i + ½], como en LienzoPlano).
      ctx.transform(...matrizRotacion(h.rotacion, p.ancho, p.alto));
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(imagen, -0.5, -0.5, p.ancho, p.alto);
    } else {
      ctx.fillStyle = '#fafafa';
      ctx.fillRect(-0.5, -0.5, c.ancho, c.alto);
    }
    ctx.restore();
  }

  contorno(c, color, ancho, guiones = []) {
    const { ctx } = this;
    ctx.beginPath();
    bordesRecorte(c).forEach(([X, Y], i) => {
      const [a, b] = aPantalla(this.vista, X, Y);
      if (i) ctx.lineTo(a, b); else ctx.moveTo(a, b);
    });
    ctx.closePath();
    ctx.setLineDash(guiones);
    ctx.strokeStyle = color;
    ctx.lineWidth = ancho;
    ctx.stroke();
    ctx.setLineDash([]);
  }

  manilla([a, b]) {
    const { ctx } = this;
    ctx.fillStyle = '#fff';
    ctx.strokeStyle = VIOLETA;
    ctx.lineWidth = 2;
    ctx.fillRect(a - 6, b - 6, 12, 12);
    ctx.strokeRect(a - 6, b - 6, 12, 12);
  }

  /** El número de la hoja elegida, en su esquina de arriba a la izquierda (la que se ve así en pantalla). */
  rotulo(texto, esquinas) {
    const { ctx } = this;
    const [a, b] = esquinas.reduce((m, q) => (q[0] + q[1] < m[0] + m[1] ? q : m));
    const W = this.contenedor.clientWidth;
    const H = this.contenedor.clientHeight;
    ctx.font = '700 13px "Plus Jakarta Sans", system-ui, sans-serif';
    const ancho = ctx.measureText(texto).width + 16;
    // Dentro de la pantalla aunque la esquina no se vea.
    const x = Math.min(Math.max(a + 8, 8), W - ancho - 8);
    const y = Math.min(Math.max(b + 8, 8), H - 30);
    ctx.fillStyle = VIOLETA;
    ctx.beginPath();
    ctx.roundRect(x, y, ancho, 22, 6);
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(texto, x + 8, y + 11.5);
  }

  // --- puntero ------------------------------------------------------------------------

  posicion(e) {
    const caja = this.canvas.getBoundingClientRect();
    return [e.clientX - caja.left, e.clientY - caja.top];
  }

  /** La manilla del recorte bajo el punto de pantalla, o −1. */
  manillaEn(p) {
    const c = this.colocadas().find((x) => x.n === this.elegida);
    if (!c) return -1;
    return bordesRecorte(c).findIndex(([X, Y]) => {
      const [a, b] = aPantalla(this.vista, X, Y);
      return Math.hypot(a - p[0], b - p[1]) <= RADIO_MANILLA;
    });
  }

  bajar(e) {
    this.canvas.focus({ preventScroll: true });
    try { this.canvas.setPointerCapture(e.pointerId); } catch { /* un puntero que ya se fue */ }
    const p = this.posicion(e);
    this.punteros.set(e.pointerId, p);
    if (this.punteros.size === 2) {
      const [a, b] = [...this.punteros.values()];
      this.arrastrando = false;
      this.gesto = { tipo: 'pellizco', distancia: Math.hypot(a[0] - b[0], a[1] - b[1]) };
      this.redibujar();
      return;
    }
    if (this.punteros.size > 2) return;
    const [X, Y] = aPagina(this.vista, ...p);
    const base = { inicio: p, ultimo: p, lejos: false, mundo: [X, Y] };
    const i = this.recortando && e.button === 0 ? this.manillaEn(p) : -1;
    if (i >= 0) { this.gesto = { ...base, tipo: 'manilla', i }; return; }
    // La elegida se arrastra aunque esté tapada: se elige en el panel y se toma donde se vea su borde.
    const colocadas = this.colocadas();
    const elegida = colocadas.find((c) => c.n === this.elegida);
    const n = elegida && dentro(elegida, X, Y) ? elegida.n : hojaEn(colocadas, X, Y);
    if (n != null && e.button === 0) {
      const h = this.hoja(n);
      this.gesto = { ...base, tipo: 'hoja', n, desde: [h.x, h.y] };
    } else {
      this.gesto = { ...base, tipo: 'vista' };
    }
  }

  mover(e) {
    if (!this.punteros.has(e.pointerId) || !this.gesto) return;
    const p = this.posicion(e);
    this.punteros.set(e.pointerId, p);
    const g = this.gesto;
    if (g.tipo === 'pellizco') {
      if (this.punteros.size < 2) return;
      const [a, b] = [...this.punteros.values()];
      const distancia = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (g.distancia > 0) this.acercar(distancia / g.distancia, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
      g.distancia = distancia;
      return;
    }
    if (!g.lejos && Math.hypot(p[0] - g.inicio[0], p[1] - g.inicio[1]) >= UMBRAL_ARRASTRE) {
      g.lejos = true;
      if (g.tipo === 'hoja') {
        if (this.elegida !== g.n) this.elegir(g.n);
        this.arrastrando = true;
      }
    }
    if (!g.lejos) return;
    const [X, Y] = aPagina(this.vista, ...p);
    if (g.tipo === 'vista') {
      this.vista = { ...this.vista, dx: this.vista.dx + p[0] - g.ultimo[0], dy: this.vista.dy + p[1] - g.ultimo[1] };
    } else if (g.tipo === 'hoja') {
      this.cambiarHoja(g.n, { x: g.desde[0] + X - g.mundo[0], y: g.desde[1] + Y - g.mundo[1] });
    } else if (g.tipo === 'manilla') {
      const c = this.colocadas().find((x) => x.n === this.elegida);
      if (c) {
        const [hx, hy] = aHoja(c.matriz, X, Y);
        const minimo = Math.min(RECORTE_MINIMO, c.ancho, c.alto);
        const recorte = moverManilla(c.recorte, g.i, hx, hy, c.ancho, c.alto, minimo);
        this.cambiarHoja(c.n, { recorte: recorteNormal(recorte, c.ancho, c.alto) });
      }
    }
    g.ultimo = p;
    this.redibujar();
  }

  subir(e) {
    const g = this.gesto;
    const p = this.posicion(e);
    this.soltar(e);
    if (!g || g.tipo === 'pellizco') return;
    if (this.arrastrando) {
      this.arrastrando = false;
      this.pintarPanel();
      this.redibujar();
    }
    if (!g.lejos) {
      // Un toque elige la hoja de más arriba bajo el dedo.
      const n = hojaEn(this.colocadas(), ...aPagina(this.vista, ...p));
      if (n != null) this.elegir(n);
    }
  }

  soltar(e) {
    this.punteros.delete(e.pointerId);
    if (!this.punteros.size) this.gesto = null;
    else if (this.gesto?.tipo === 'pellizco') this.gesto = null;
    if (!this.punteros.size && this.arrastrando) {
      this.arrastrando = false;
      this.redibujar();
    }
  }

  rueda(e) {
    e.preventDefault();
    const [sx, sy] = this.posicion(e);
    const delta = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
    this.acercar(Math.exp(-delta * 0.0015), sx, sy);
  }

  /** Las flechas mueven la hoja elegida de a un píxel de pantalla (con Mayúscula, de a 10). */
  tecla(e) {
    const paso = (e.shiftKey ? 10 : 1) / this.vista.escala;
    const flecha = { ArrowLeft: [-paso, 0], ArrowRight: [paso, 0], ArrowUp: [0, -paso], ArrowDown: [0, paso] }[e.key];
    const h = this.hoja(this.elegida);
    if (flecha && h) {
      this.cambiarHoja(h.n, { x: h.x + flecha[0], y: h.y + flecha[1] });
      this.pintarPanel();
    } else if (e.key === '+' || e.key === '=') this.acercar(1.25);
    else if (e.key === '-') this.acercar(0.8);
    else if (e.key === '0') this.ajustar();
    else return;
    e.preventDefault();
  }

  // --- panel --------------------------------------------------------------------------

  pintarPanel() {
    if (!this.abierto) return;
    const usadas = this.usadas().length;
    // La lista va de arriba hacia abajo: la primera es la que se ve encima.
    const orden = [...this.hojas].reverse();
    this.lista.replaceChildren(...orden.map((h, i) => this.fila(h, i, orden.length, usadas)));
    const afinar = this.panel.querySelector('[data-union="afinar"]');
    afinar.disabled = this.afinando || this.usando || usadas < MIN_HOJAS;
    afinar.textContent = this.afinando ? 'Afinando…' : 'Afinar la alineación';
    if (this.afinando) afinar.setAttribute('aria-busy', 'true'); else afinar.removeAttribute('aria-busy');
    this.panel.querySelector('[data-union="usar-union"]').disabled = this.afinando || this.usando || usadas < MIN_HOJAS;
  }

  fila(h, i, total, usadas) {
    const elegida = h.n === this.elegida;
    const li = document.createElement('li');
    li.className = `union-hoja${h.usar ? '' : ' union-hoja--fuera'}`;
    li.dataset.hoja = String(h.n);
    if (elegida) li.setAttribute('aria-current', 'true');

    const cabeza = boton(`Hoja ${h.n}`, 'elegir', 'union-hoja__cabeza');
    cabeza.setAttribute('aria-expanded', String(elegida));
    const resumen = document.createElement('span');
    resumen.className = 'union-hoja__resumen';
    resumen.textContent = !h.usar ? 'No se usa'
      : [`${h.rotacion}°`, Math.abs(h.angulo) >= 0.005 ? textoGrados(h.angulo) : null, h.recorte ? 'recortada' : null]
        .filter(Boolean).join(' · ');
    cabeza.append(resumen);

    const controles = document.createElement('div');
    controles.className = 'union-hoja__controles';
    const casilla = document.createElement('label');
    casilla.className = 'kmz-casilla';
    const check = document.createElement('input');
    check.type = 'checkbox';
    check.checked = h.usar;
    check.dataset.union = 'usar';
    check.disabled = (h.usar && usadas <= MIN_HOJAS) || (!h.usar && usadas >= MAX_HOJAS);
    if (h.usar && usadas <= MIN_HOJAS) casilla.title = `La unión lleva al menos ${MIN_HOJAS} hojas`;
    casilla.append(check, ' Usar');
    controles.append(casilla);

    if (h.usar) {
      const giros = document.createElement('div');
      giros.className = 'fila fila--envuelve';
      const izq = boton('↺ 90°', 'izq', 'boton boton--contorno boton--chico');
      izq.setAttribute('aria-label', `Girar la hoja ${h.n} 90 grados a la izquierda`);
      const der = boton('↻ 90°', 'der', 'boton boton--contorno boton--chico');
      der.setAttribute('aria-label', `Girar la hoja ${h.n} 90 grados a la derecha`);
      giros.append(izq, der);

      const giro = document.createElement('label');
      giro.className = 'union-giro';
      const rango = document.createElement('input');
      rango.type = 'range';
      rango.min = String(-GIRO_FINO);
      rango.max = String(GIRO_FINO);
      rango.step = '0.05';
      rango.value = String(h.angulo);
      rango.dataset.union = 'angulo';
      rango.setAttribute('aria-label', `Giro fino de la hoja ${h.n}, en grados`);
      const valor = document.createElement('output');
      valor.textContent = textoGrados(h.angulo);
      giro.append('Giro fino', rango, valor);

      const otros = document.createElement('div');
      otros.className = 'fila fila--envuelve';
      const recortar = boton(elegida && this.recortando ? 'Listo' : 'Recortar', 'recortar', 'boton boton--contorno boton--chico');
      recortar.setAttribute('aria-pressed', String(elegida && this.recortando));
      const subirB = boton('Subir', 'subir', 'boton boton--texto boton--chico');
      subirB.disabled = i === 0;
      subirB.setAttribute('aria-label', `Subir la hoja ${h.n}: queda encima`);
      const bajarB = boton('Bajar', 'bajar', 'boton boton--texto boton--chico');
      bajarB.disabled = i === total - 1;
      bajarB.setAttribute('aria-label', `Bajar la hoja ${h.n}: queda debajo`);
      otros.append(recortar, subirB, bajarB);
      controles.append(giros, giro, otros);
    }
    li.append(cabeza, controles);

    const calce = this.calce.get(h.n);
    if (calce && h.usar) {
      const p = document.createElement('p');
      p.className = `union-calce union-calce--${calce.calzada ? 'ok' : 'no'}`;
      p.textContent = !calce.calzada
        ? `No se pudo calzar la hoja ${h.n}: acércala a su lugar y vuelve a afinar`
        : calce.residuo_mm == null ? 'Calzada (las demás se calzan con esta)'
          : `Calzada · error medio ${calce.residuo_mm.toFixed(1).replace('.', ',')} mm`;
      li.append(p);
    }
    return li;
  }
}

function boton(texto, accion, clase) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = clase;
  b.dataset.union = accion;
  b.textContent = texto;
  return b;
}
