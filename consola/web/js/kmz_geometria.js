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

/**
 * Lo marcado tras dibujar `rect` (px de página) con una herramienta del paso Marcar:
 * "dibujo" encierra el dibujo, "mascara" suma un tapado y "cuadro" encierra el cuadro de
 * superficies (uno solo: dibujarlo de nuevo lo reemplaza; puede quedar fuera del
 * dibujo). Un rectángulo de menos de 3 px por lado es un clic, no se marca.
 */
export function marcarRectangulo(entradas, herramienta, rect) {
  if (rect[2] - rect[0] < 3 || rect[3] - rect[1] < 3) return entradas;
  if (herramienta === 'dibujo') return { ...entradas, rectangulo: rect };
  if (herramienta === 'mascara') return { ...entradas, mascaras: [...(entradas.mascaras ?? []), rect] };
  if (herramienta === 'cuadro') return { ...entradas, cuadro: rect };
  return entradas;
}

/** Las herramientas del paso Marcar que dibujan un rectángulo. */
export const HERRAMIENTAS_RECTANGULO = ['dibujo', 'mascara', 'cuadro'];

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

// --- coordenadas escritas -------------------------------------------------------------

/**
 * El ancla completa: el punto marcado en el plano ({nombre, x, y}) con su lugar en el
 * mapa, sea un clic o unas coordenadas escritas. Lon/lat a 7 decimales (~1 cm).
 */
export function anclaDesde(pendiente, lat, lon) {
  return { ...pendiente, lon: Number(lon.toFixed(7)), lat: Number(lat.toFixed(7)) };
}

/** Lleva los símbolos que copian Google Earth, Word o el teclado a ° ' ". */
function normalizarCoordenadas(texto) {
  let t = String(texto ?? '').trim().toUpperCase()
    .replace(/[º˚]/g, '°')
    .replace(/[′’‘´`]/g, "'")
    .replace(/[″”“]/g, '"')
    .replace(/''/g, '"');
  // Coma decimal pegada a un símbolo (37,50") no es la coma que separa el par.
  t = t.replace(/(\d),(\d+)(?=\s*[°'"])/g, '$1.$2');
  // Dos decimales con coma separados por espacio o punto y coma: "-34,98 -71,24".
  const par = !t.includes('.') && t.match(/^([+-]?\d+),(\d+)(?:\s*;\s*|\s+)([+-]?\d+),(\d+)$/);
  if (par) t = `${par[1]}.${par[2]} ${par[3]}.${par[4]}`;
  return t;
}

/** Los pedazos del texto: número (con su símbolo), hemisferio o separador. */
function piezasDeCoordenadas(t) {
  const piezas = [];
  const patron = /\s*(?:([+-]?\d+(?:\.\d+)?)\s*([°'"])?|([NSEWO])|([,;])|(\S))/gy;
  for (const m of t.matchAll(patron)) {
    if (m[5] !== undefined) return null;            // algo que no es coordenada
    if (m[1] !== undefined) piezas.push({ numero: m[1], unidad: m[2] ?? '' });
    else if (m[3]) piezas.push({ hemisferio: m[3] });
    else if (m[4]) piezas.push({ coma: true });
  }
  return piezas;
}

const ORDEN_UNIDAD = { '°': 0, "'": 1, '"': 2 };

/** Una coordenada en grados decimales con su eje según la letra (lat, lon o null). */
function valorDeCoordenada({ numeros, hemisferio }) {
  if (!numeros.length) return null;
  // Sin símbolo solo puede ir sola (grados decimales) o como grados antes de ' o ".
  const unidades = numeros.map((n, i) => n.unidad || (i === 0 ? '°' : null));
  if (unidades.includes(null)) return null;
  const orden = unidades.map((u) => ORDEN_UNIDAD[u]);
  if (orden.some((o, i) => i > 0 && o <= orden[i - 1])) return null;
  let total = 0;
  let signo = 1;
  for (const [i, n] of numeros.entries()) {
    if (i > 0 && /^[+-]/.test(n.numero)) return null;    // el signo va en los grados
    const valor = Number(n.numero);
    if (i === 0 && n.numero.startsWith('-')) signo = -1;
    const abs = Math.abs(valor);
    // Solo la última parte puede tener decimales (34°10.625' sí; 34.5°10' no).
    if (i < numeros.length - 1 && !Number.isInteger(abs)) return null;
    if (orden[i] > 0 && abs >= 60) return null;
    total += abs / 60 ** orden[i];
  }
  let eje = null;
  if (hemisferio) {
    eje = 'NS'.includes(hemisferio) ? 'lat' : 'lon';
    const sur = 'SWO'.includes(hemisferio);
    if (signo < 0 && !sur) return null;                 // "-34° N" se contradice
    signo = sur ? -1 : 1;
  }
  return { valor: signo * total, eje };
}

/**
 * Latitud y longitud desde lo que se escribe o se pega en el "ir a": decimales
 * ("-34.98, -71.24") o grados, minutos y segundos con hemisferio
 * (34°10'37.50"S 71°32'53.89"W, también S 34°10'37.5" O 71°32'53.9", 34°10.625'S …).
 * Las letras dicen cuál es cuál; sin letras va latitud y después longitud.
 * Devuelve { lat, lon } o null si no se entiende o se sale de rango.
 */
export function leerCoordenadas(texto) {
  const piezas = piezasDeCoordenadas(normalizarCoordenadas(texto));
  if (!piezas) return null;
  const coordenadas = [];
  let actual = { numeros: [], hemisferio: null };
  const cerrar = () => {
    if (actual.numeros.length) coordenadas.push(actual);
    else if (actual.hemisferio) coordenadas.push(actual);  // una letra suelta: inválida después
    actual = { numeros: [], hemisferio: null };
  };
  for (const p of piezas) {
    if (p.coma) {
      if (actual.numeros.length) cerrar();
    } else if (p.hemisferio) {
      if (actual.numeros.length && !actual.hemisferio) {
        actual.hemisferio = p.hemisferio;               // va detrás: 34°10'S
        cerrar();
      } else {
        if (actual.numeros.length || actual.hemisferio) cerrar();
        actual.hemisferio = p.hemisferio;               // va delante: S 34°10'
      }
    } else {
      const previo = actual.numeros.at(-1);
      // Unos grados (o un número sin símbolo) después de otro número empiezan otra coordenada.
      if (previo && (p.unidad === '°' || p.unidad === '' || ORDEN_UNIDAD[p.unidad] <= ORDEN_UNIDAD[previo.unidad || '°'])) cerrar();
      actual.numeros.push(p);
    }
  }
  cerrar();
  if (coordenadas.length !== 2) return null;
  const [a, b] = coordenadas.map(valorDeCoordenada);
  if (!a || !b) return null;
  let lat;
  let lon;
  if (a.eje && b.eje && a.eje === b.eje) return null;  // dos latitudes o dos longitudes
  if (a.eje === 'lon' || b.eje === 'lat') [lat, lon] = [b.valor, a.valor];
  else [lat, lon] = [a.valor, b.valor];
  // Sin letras, si el primero no puede ser latitud y el segundo sí, vienen al revés.
  if (!a.eje && !b.eje && Math.abs(lat) > 90 && Math.abs(lon) <= 90) [lat, lon] = [lon, lat];
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { lat, lon };
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
 * El número de lote para comparar, como `pipeline.plano.numeros.clave`: "8-01", "8-1" y
 * "LOTE 8-01" son el mismo lote ("8-1"); "A03" → "A3". Se guarda como lo escribió ella.
 */
export function claveLote(numero) {
  const t = String(numero ?? '').trim().toUpperCase()
    .replace(/^(?:LOTES?(?=\d)|LOTES?\b\s*[-#]?\s*|[-#]\s*)/, '');
  const pares = t.match(/^(\d+(?:\s*-\s*\d+)*)[\s.]*$/);
  if (pares) return pares[1].replace(/\s/g, '').split('-').map((p) => String(Number(p))).join('-');
  const letra = t.match(/^([A-Z])\s*(\d+)$/);
  if (letra) return `${letra[1]}${Number(letra[2])}`;
  return t.replace(/\s+/g, '');
}

/**
 * Le pone `numero` al lote que contiene el clic. Devuelve las semillas nuevas:
 * - la semilla de la loteadora que ya estaba dentro de ese lote cambia de número
 *   (o se quita si el número viene vacío);
 * - si no había, se agrega una en `punto`;
 * - si otra semilla tenía ese número, se quita (un número va en un solo lote; "8-1" y
 *   "8-01" son el mismo). El número va tal como lo escribió.
 */
export function ponerNumero(semillas, numero, punto, anillos) {
  const limpio = String(numero ?? '').trim();
  const dentro = anillos ? (s) => puntoEnPoligono(s.x, s.y, anillos) : () => false;
  const propia = semillas.find(dentro);
  let salida = semillas.filter((s) => s !== propia && (!limpio || claveLote(s.numero) !== claveLote(limpio)));
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
  const cuenta = { lotes: 0, verde: 0, ambar: 0, rojo: 0, gris: 0, sin_numero: 0, sin_numero_lote: 0, duplicados: 0 };
  for (const { properties: p } of rasgos) {
    const banderas = p.banderas ?? [];
    if (banderas.includes('sin_numero')) {
      cuenta.sin_numero += 1;
      if (p.de_lote) cuenta.sin_numero_lote += 1;
      continue;
    }
    cuenta.lotes += 1;
    if (banderas.includes('duplicado')) cuenta.duplicados += 1;
    cuenta[nivelDe(p)] += 1;
  }
  return cuenta;
}

/**
 * Las partes sin número, primero las del tamaño de un lote (un lote cuyo número no se
 * leyó) y, entre ellas, las que traen una lectura que confirmar.
 */
export function sinNumero(rasgos) {
  const peso = ({ properties: p }) => (p.de_lote ? 0 : 2) + (p.sugerencia ? 0 : 1);
  return rasgos.filter((r) => (r.properties.banderas ?? []).includes('sin_numero') && r.properties.numero == null)
    .map((r, i) => [r, i]).sort(([a, i], [b, j]) => peso(a) - peso(b) || i - j).map(([r]) => r);
}

/** Las partes sin número con una lectura del lector que se confirma con un clic: [{numero, rasgo}]. */
export function sugerencias(rasgos) {
  return sinNumero(rasgos).filter((r) => r.properties.sugerencia?.numero)
    .map((r) => ({ numero: String(r.properties.sugerencia.numero), rasgo: r }));
}

/** "Faltan los números 8-03, 8-05 y 8-11." ("" si no falta ninguno). */
export function textoHuecos(huecos) {
  const lista = (huecos ?? []).map(String);
  if (!lista.length) return '';
  if (lista.length === 1) return `Falta el número ${lista[0]}.`;
  return `Faltan los números ${lista.slice(0, -1).join(', ')} y ${lista[lista.length - 1]}.`;
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
