/**
 * Crea tu KMZ: las cuentas de la pantalla, sin DOM (las prueba `kmz.test.js`).
 *
 * Tres sistemas de coordenadas:
 * - **imagen**: los píxeles de `paginas/<n>.jpg`, sin rotar.
 * - **página**: la imagen girada según `rotacion` (lo que ve la loteadora). Es lo
 *   que guarda `entradas.json` y lo que devuelve `lotes?en=px`. Centro del píxel
 *   en el entero, igual que `pipeline/plano/pagina.py`.
 * - **pantalla**: px CSS del lienzo. `vista = {escala, dx, dy}`:
 *   pantalla = página × escala + (dx, dy).
 */

const cuartos = (grados) => {
  if (grados % 90) throw new Error(`la rotación es 0, 90, 180 o 270, no ${grados}`);
  return (((grados / 90) % 4) + 4) % 4;
};

/** [ancho, alto] de la página ya girada. */
export function tamanoRotado(ancho, alto, rotacion) {
  return cuartos(rotacion) % 2 ? [alto, ancho] : [ancho, alto];
}

/** Imagen sin rotar → página (como `pagina.rotar_punto`). */
export function rotarPunto(x, y, rotacion, ancho, alto) {
  switch (cuartos(rotacion)) {
    case 1: return [alto - 1 - y, x];
    case 2: return [ancho - 1 - x, alto - 1 - y];
    case 3: return [y, ancho - 1 - x];
    default: return [x, y];
  }
}

/** Página → imagen sin rotar. */
export function desrotarPunto(X, Y, rotacion, ancho, alto) {
  switch (cuartos(rotacion)) {
    case 1: return [Y, alto - 1 - X];
    case 2: return [ancho - 1 - X, alto - 1 - Y];
    case 3: return [ancho - 1 - Y, X];
    default: return [X, Y];
  }
}

/**
 * La transformación de canvas (a, b, c, d, e, f) que lleva la imagen sin rotar a
 * píxeles de página: X = a·x + c·y + e, Y = b·x + d·y + f.
 */
export function matrizRotacion(rotacion, ancho, alto) {
  switch (cuartos(rotacion)) {
    case 1: return [0, 1, -1, 0, alto - 1, 0];
    case 2: return [-1, 0, 0, -1, ancho - 1, alto - 1];
    case 3: return [0, -1, 1, 0, 0, ancho - 1];
    default: return [1, 0, 0, 1, 0, 0];
  }
}

/** Un punto de página con la rotación `de` a la rotación `a`. */
export function girarPunto(x, y, de, a, ancho, alto) {
  const [u, v] = desrotarPunto(x, y, de, ancho, alto);
  return rotarPunto(u, v, a, ancho, alto);
}

const redondo = (v) => Math.round(v * 100) / 100;

/**
 * Lo marcado, llevado a otra rotación: si la loteadora gira la página después de
 * marcar, sus rectángulos, esquinas, semillas y anclas siguen donde estaban sobre
 * el dibujo. ancho y alto son los de la imagen sin rotar.
 */
export function girarEntradas(entradas, de, a, ancho, alto) {
  if (de === a) return { ...entradas, rotacion: a };
  const punto = ([x, y]) => girarPunto(x, y, de, a, ancho, alto).map(redondo);
  const caja = (r) => {
    if (!r) return r;
    const [p, q] = [punto([r[0], r[1]]), punto([r[2], r[3]])];
    return rectanguloDe(p, q);
  };
  const conXY = (o) => {
    const [x, y] = punto([o.x, o.y]);
    return { ...o, x, y };
  };
  const salida = {
    ...entradas,
    rotacion: a,
    rectangulo: caja(entradas.rectangulo),
    mascaras: (entradas.mascaras ?? []).map(caja),
    semillas: (entradas.semillas ?? []).map(conXY),
    anclas: (entradas.anclas ?? []).map(conXY),
  };
  if (entradas.cuadro) salida.cuadro = caja(entradas.cuadro);
  if (entradas.esquinas) {
    // Siguen siendo las esquinas del marco, pero el orden es sup-izq, sup-der,
    // inf-der, inf-izq en la página girada: se reordenan por ángulo.
    salida.esquinas = ordenarEsquinas(entradas.esquinas.map(punto));
  }
  // El marco es [ancho, alto] tal como se ve en la página: un cuarto de vuelta los cambia.
  if (Array.isArray(entradas.marco_mm) && (cuartos(a) - cuartos(de)) % 2) {
    salida.marco_mm = [entradas.marco_mm[1], entradas.marco_mm[0]];
  }
  // Las líneas de la cuadrícula se detectan de nuevo al digitalizar.
  if (entradas.cuadricula) delete salida.cuadricula;
  return salida;
}

/** [x0, y0, x1, y1] con x0 < x1 e y0 < y1, de dos esquinas cualesquiera. */
export function rectanguloDe(p, q) {
  return [Math.min(p[0], q[0]), Math.min(p[1], q[1]), Math.max(p[0], q[0]), Math.max(p[1], q[1])];
}

/** 4 puntos en el orden de `entradas.esquinas`: sup-izq, sup-der, inf-der, inf-izq. */
export function ordenarEsquinas(puntos) {
  const cx = puntos.reduce((s, p) => s + p[0], 0) / puntos.length;
  const cy = puntos.reduce((s, p) => s + p[1], 0) / puntos.length;
  // Ángulo desde el centro, con y hacia abajo: sup-izq cae en (−180°, −90°),
  // sup-der en (−90°, 0°), inf-der en (0°, 90°) e inf-izq en (90°, 180°).
  const angulo = ([x, y]) => Math.atan2(y - cy, x - cx);
  return [...puntos].sort((p, q) => angulo(p) - angulo(q));
}

// --- vista -------------------------------------------------------------------------

/** La vista que muestra la página entera centrada en un lienzo de W×H. */
export function vistaAjustada(ancho, alto, W, H, margen = 16) {
  const escala = Math.max(1e-6, Math.min((W - 2 * margen) / ancho, (H - 2 * margen) / alto));
  return { escala, dx: (W - ancho * escala) / 2, dy: (H - alto * escala) / 2 };
}

export const aPantalla = (v, x, y) => [x * v.escala + v.dx, y * v.escala + v.dy];
export const aPagina = (v, sx, sy) => [(sx - v.dx) / v.escala, (sy - v.dy) / v.escala];

/** Acerca o aleja `factor` veces dejando quieto el punto (sx, sy) de la pantalla. */
export function zoomEn(v, factor, sx, sy, minimo = 0.01, maximo = 16) {
  const escala = Math.min(maximo, Math.max(minimo, v.escala * factor));
  const real = escala / v.escala;
  return { escala, dx: sx - (sx - v.dx) * real, dy: sy - (sy - v.dy) * real };
}

/** La vista con (x, y) de página en el centro de un lienzo W×H. */
export function centrarEn(v, x, y, W, H, escala = v.escala) {
  return { escala, dx: W / 2 - x * escala, dy: H / 2 - y * escala };
}

// --- anclas y ajuste --------------------------------------------------------------

/** A, B, …, Z, AA, AB…: la primera que no esté usada. */
export function siguienteNombre(usados) {
  const tomados = new Set(usados);
  for (let i = 0; ; i += 1) {
    let n = i;
    let nombre = '';
    do {
      nombre = String.fromCharCode(65 + (n % 26)) + nombre;
      n = Math.floor(n / 26) - 1;
    } while (n >= 0);
    if (!tomados.has(nombre)) return nombre;
  }
}

const decima = (v) => Math.round(v * 10) / 10;

/** El ajuste fino movido (de, dn) metros, redondeado al decímetro. */
export function empujar(ajuste, de, dn) {
  return { de: decima((ajuste?.de ?? 0) + de), dn: decima((ajuste?.dn ?? 0) + dn) };
}

const METROS_POR_GRADO = 111320;

/** Cuántos metros (este, norte) hay de (lat, lon) a (lat + dlat, lon + dlon). */
export function metrosDe(lat, dlat, dlon) {
  return { de: dlon * METROS_POR_GRADO * Math.cos(lat * Math.PI / 180), dn: dlat * METROS_POR_GRADO };
}

// --- lotes --------------------------------------------------------------------------

/** ¿(x, y) cae dentro del polígono (exterior y huecos, regla par-impar)? */
export function puntoEnPoligono(x, y, anillos) {
  let dentro = false;
  for (const anillo of anillos) {
    for (let i = 0, j = anillo.length - 1; i < anillo.length; j = i, i += 1) {
      const [xi, yi] = anillo[i];
      const [xj, yj] = anillo[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) dentro = !dentro;
    }
  }
  return dentro;
}

/** El centroide de un anillo (por área). */
export function centroide(anillo) {
  let a = 0;
  let cx = 0;
  let cy = 0;
  for (let i = 0, j = anillo.length - 1; i < anillo.length; j = i, i += 1) {
    const [x0, y0] = anillo[j];
    const [x1, y1] = anillo[i];
    const cruz = x0 * y1 - x1 * y0;
    a += cruz;
    cx += (x0 + x1) * cruz;
    cy += (y0 + y1) * cruz;
  }
  if (Math.abs(a) < 1e-9) {
    const n = anillo.length || 1;
    return [anillo.reduce((s, p) => s + p[0], 0) / n, anillo.reduce((s, p) => s + p[1], 0) / n];
  }
  return [cx / (3 * a), cy / (3 * a)];
}

/** Dónde escribir el número de un lote: su semilla, o el centroide si cae dentro. */
export function puntoDeRotulo(rasgo) {
  const semilla = rasgo.properties?.semilla;
  if (Array.isArray(semilla) && semilla.length === 2) return semilla;
  const anillos = rasgo.geometry.coordinates;
  const c = centroide(anillos[0]);
  if (puntoEnPoligono(c[0], c[1], anillos)) return c;
  // Un lote en "L": el punto medio entre dos vértices opuestos suele caer dentro.
  const exterior = anillos[0];
  const medio = Math.floor(exterior.length / 2);
  return [(exterior[0][0] + exterior[medio][0]) / 2, (exterior[0][1] + exterior[medio][1]) / 2];
}

/** El lote (rasgo) que contiene el punto, o null. */
export function loteEn(rasgos, x, y) {
  return rasgos.find((r) => puntoEnPoligono(x, y, r.geometry.coordinates)) ?? null;
}

/**
 * Le pone `numero` al lote que contiene el clic. Devuelve las semillas nuevas:
 * - la semilla de la loteadora que ya estaba dentro de ese lote cambia de número
 *   (o se quita si el número viene vacío);
 * - si no había, se agrega una en `punto`;
 * - si otra semilla tenía ese número, se quita (un número va en un solo lote).
 */
export function ponerNumero(semillas, numero, punto, anillos) {
  const limpio = String(numero ?? '').trim();
  const dentro = anillos ? (s) => puntoEnPoligono(s.x, s.y, anillos) : () => false;
  const propia = semillas.find(dentro);
  let salida = semillas.filter((s) => s !== propia && (!limpio || s.numero !== limpio));
  if (limpio) {
    const [x, y] = propia ? [propia.x, propia.y] : punto;
    salida = [...salida, { numero: limpio, x: redondo(x), y: redondo(y) }];
  }
  return salida;
}

/** verde ±2 %, ámbar ±5 %, rojo más; gris si no hay área oficial con qué comparar. */
export function nivelDe(propiedades) {
  return propiedades?.nivel ?? 'gris';
}

/** Lo que la revisión cuenta de un vistazo. */
export function resumenRevision(rasgos) {
  const cuenta = { lotes: 0, verde: 0, ambar: 0, rojo: 0, gris: 0, sin_numero: 0, duplicados: 0 };
  for (const { properties: p } of rasgos) {
    const banderas = p.banderas ?? [];
    if (banderas.includes('sin_numero')) { cuenta.sin_numero += 1; continue; }
    cuenta.lotes += 1;
    if (banderas.includes('duplicado')) cuenta.duplicados += 1;
    cuenta[nivelDe(p)] += 1;
  }
  return cuenta;
}

/** Los números que se repiten entre los lotes. */
export function duplicados(rasgos) {
  return [...new Set(rasgos.filter((r) => (r.properties.banderas ?? []).includes('duplicado'))
    .map((r) => r.properties.numero))];
}

/** Leídos por el lector con poco apoyo: los que conviene mirar. */
export function dudosos(rasgos, apoyoMinimo = 3) {
  return rasgos.filter(({ properties: p }) => p.origen === 'lector'
    && ((p.apoyo ?? 0) < apoyoMinimo || (p.confianza ?? 1) < 0.6));
}

// --- pasos ---------------------------------------------------------------------------

export const PASOS = ['subir', 'marcar', 'digitalizar', 'numerar', 'ubicar', 'revisar', 'crear'];

/** Qué pasos se pueden abrir con lo que ya hay en el servidor. */
export function pasosHabilitados(e) {
  const digitalizado = Boolean(e?.digitalizado);
  const ubicado = Boolean(e?.georreferencia?.vigente);
  return {
    subir: true,
    marcar: Boolean(e?.pdf),
    digitalizar: Boolean(e?.pdf && e?.entradas),
    numerar: digitalizado,
    ubicar: digitalizado,
    revisar: ubicado,
    crear: ubicado,
  };
}

/**
 * "Seguir: numerar" desde el paso 3: solo con una digitalización vigente (hecha con
 * lo último que se marcó) y sin otra corriendo. Sin digitalizar, no hay qué numerar.
 */
export function puedeSeguirANumerar(e) {
  const trabajando = Boolean(e?.trabajo && !e.trabajo.terminado);
  return Boolean(e?.digitalizado?.vigente) && !trabajando;
}

/** El paso donde conviene abrir la pantalla, según `estado.paso` del servidor. */
export function pasoSugerido(e) {
  switch (e?.paso) {
    case 'subir': return 'subir';
    case 'marcar': return 'marcar';
    case 'digitalizar': return e.digitalizado ? 'numerar' : 'digitalizar';
    // Las caras sin número pueden ser caminos: solo los números perdidos piden volver.
    case 'ubicar': return e.digitalizado?.faltantes?.length ? 'numerar' : 'ubicar';
    case 'crear': return 'revisar';
    case 'listo': return 'crear';
    default: return 'subir';
  }
}

/** Qué pasos ya están hechos (para la marca ✓). */
export function pasosHechos(e) {
  const hecho = (paso) => {
    const orden = ['subir', 'marcar', 'digitalizar', 'ubicar', 'crear', 'listo'];
    return orden.indexOf(e?.paso) > orden.indexOf(paso);
  };
  return {
    subir: hecho('subir'),
    marcar: hecho('marcar'),
    digitalizar: hecho('digitalizar'),
    numerar: hecho('digitalizar') && !e?.digitalizado?.faltantes?.length,
    ubicar: hecho('ubicar'),
    revisar: hecho('ubicar'),
    crear: e?.paso === 'listo',
  };
}

/** "UTM 19S · WGS84" para mostrar dónde quedó ubicado. */
export function nombreDelSistema(epsg) {
  if (epsg >= 32701 && epsg <= 32760) return `UTM ${epsg - 32700}S · WGS84`;
  if (epsg >= 32601 && epsg <= 32660) return `UTM ${epsg - 32600}N · WGS84`;
  if (epsg >= 24877 && epsg <= 24882) return `UTM ${epsg - 24860}S · PSAD56`;
  if (epsg >= 24817 && epsg <= 24821) return `UTM ${epsg - 24800}N · PSAD56`;
  return epsg ? `EPSG ${epsg}` : '—';
}
