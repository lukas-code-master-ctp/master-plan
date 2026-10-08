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
    fuera: (entradas.fuera ?? []).map(punto),
  };
  if (entradas.cuadro) salida.cuadro = caja(entradas.cuadro);
  if (entradas.ubicacion) {
    // El punto sigue sobre el mismo lugar del dibujo, y el giro que falta para dejar el
    // norte arriba es el de antes menos lo que ya se giró la página (ambos horarios).
    const u = { ...entradas.ubicacion };
    if (Number.isFinite(u.x) && Number.isFinite(u.y)) [u.x, u.y] = punto([u.x, u.y]);
    if (Number.isFinite(u.giro)) u.giro = normalizarGiro(u.giro - (a - de));
    salida.ubicacion = u;
  }
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

/** Un giro en grados llevado a −180..180 (lo que acepta el servidor). */
export function normalizarGiro(grados) {
  const g = ((((grados + 180) % 360) + 360) % 360) - 180;
  return g === -180 && grados > 0 ? 180 : g;
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
  // Con la unión, el cuadro va en px de su hoja (`union.cuadro`): uno en px de la unión
  // no lo dibuja nadie y el servidor lo tomaría por el cuadro.
  if (herramienta === 'cuadro') return entradas.pagina === 0 && entradas.union ? entradas : { ...entradas, cuadro: rect };
  return entradas;
}

/** Las herramientas del paso Marcar que dibujan un rectángulo. */
export const HERRAMIENTAS_RECTANGULO = ['dibujo', 'mascara', 'cuadro'];

/**
 * La herramienta con que se abre Marcar. Sin el dibujo encerrado, "Encerrar el dibujo":
 * es lo primero que hay que hacer y con "Mover" un arrastre no marca nada, que es donde
 * se perdía la gente. Encerrado pero sin leer el plano todavía, sigue tapar. Ya leído,
 * "Mover": se vuelve a mirar, y un arrastre para correr el plano no debe agregar un
 * tapado que deje la lectura atrasada.
 */
export function herramientaAlEntrar(entradas, digitalizado = false) {
  if (!entradas?.rectangulo) return 'dibujo';
  return digitalizado ? 'mover' : 'mascara';
}

/** Tras el primer rectángulo del dibujo se pasa sola a "Tapar"; si no, queda la que estaba. */
export function herramientaTrasRectangulo(herramienta, antes, despues) {
  return herramienta === 'dibujo' && !antes?.rectangulo && despues?.rectangulo ? 'mascara' : herramienta;
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

/**
 * Dónde escribir el número de un lote: su semilla, el punto que el servidor da dentro
 * (el del resto de la propiedad: una parte enorme y torcida) o el centroide si cae dentro.
 */
export function puntoDeRotulo(rasgo) {
  const semilla = rasgo.properties?.semilla;
  if (Array.isArray(semilla) && semilla.length === 2) return semilla;
  const punto = rasgo.properties?.punto;
  if (Array.isArray(punto) && punto.length === 2) return punto;
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
  const cuenta = {
    lotes: 0, verde: 0, ambar: 0, rojo: 0, gris: 0, sin_numero: 0, sin_numero_lote: 0, duplicados: 0, fuera: 0,
    resto_pendiente: false,
  };
  for (const { properties: p } of rasgos) {
    const banderas = p.banderas ?? [];
    // Lo que ella dejó fuera del KMZ (el resto de la propiedad) ya está decidido: no es un aviso.
    if (p.fuera) {
      cuenta.fuera += 1;
      continue;
    }
    // El resto sin decidir es la pregunta de Numerar, no un lote sin número (como lo cuenta
    // el servidor al crear): se avisa aparte.
    if (p.resto && p.numero == null) {
      cuenta.resto_pendiente = true;
      continue;
    }
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
 * Si casi todos los lotes se desvían del área oficial hacia el mismo lado, lo más probable
 * es la escala de los puntos de Ubicar y no el dibujo: un punto corrido unos metros agranda
 * o achica todos los lotes por igual. Devuelve la mediana del error (+0.06 = 6 % más grande)
 * o null si no hay sesgo: menos de 3 lotes con área oficial, una mediana de ±3 % o menos,
 * o menos de 4 de cada 5 lotes hacia el lado de la mediana.
 */
export function sesgoDeEscala(rasgos, umbral = 0.03, parejo = 0.8) {
  const errores = rasgos.map(({ properties: p }) => p?.error_area)
    .filter((e) => typeof e === 'number' && Number.isFinite(e)).sort((a, b) => a - b);
  if (errores.length < 3) return null;
  const m = errores.length;
  const mediana = m % 2 ? errores[(m - 1) / 2] : (errores[m / 2 - 1] + errores[m / 2]) / 2;
  if (Math.abs(mediana) <= umbral) return null;
  const mismoLado = errores.filter((e) => Math.sign(e) === Math.sign(mediana)).length;
  return mismoLado >= parejo * m ? mediana : null;
}

/**
 * Cuántos lotes del KMZ calzan con el cuadro de superficies, para avisar antes de crearlo.
 * Usa el mismo desvío que pinta Revisar (`error_area`, que pone el servidor con el área
 * oficial, también la del resto incluido): así el aviso y los colores nunca se contradicen.
 * Solo cuentan los que van al KMZ: ni las partes sin número ni lo que ella dejó fuera.
 * Ámbar si la mitad o más se aparta más de un 5 % (un desvío así de parejo suele ser la
 * ubicación, no el dibujo); null si ninguno tiene área oficial (sin cuadro no se muestra).
 */
export function semaforo(rasgos, tolerancia = 0.05) {
  const conArea = (rasgos ?? []).map(({ properties: p }) => p ?? {})
    .filter((p) => !p.fuera && p.numero != null && !(p.banderas ?? []).includes('sin_numero'))
    .filter((p) => typeof p.error_area === 'number' && Number.isFinite(p.error_area));
  const total = conArea.length;
  if (!total) return { tono: null, dentro: 0, total: 0 };
  // El `nivel` del servidor sale del desvío sin redondear: con él, un 5,004 % que
  // `error_area` (a 4 decimales) guarda como 0,05 queda rojo aquí igual que en Revisar.
  // Sin `nivel`, el desvío con un margen chico para el redondeo.
  const dentro = conArea.filter((p) => (p.nivel ? p.nivel !== 'rojo'
    : Math.abs(p.error_area) <= tolerancia + 1e-9)).length;
  // Revisar pide volver a Ubicar cuando casi todos se desvían hacia el mismo lado, aunque
  // menos de la mitad pase del 5 % (en Rapel, 7 de 16 a un 4,9 % parejo): el semáforo
  // tiene que decir lo mismo, o Crear queda en verde justo después de ese aviso.
  const sesgo = sesgoDeEscala(conArea.map((p) => ({ properties: p })));
  const ambar = (total - dentro) * 2 >= total || sesgo != null;
  return { tono: ambar ? 'ambar' : 'verde', dentro, total, sesgo };
}

/**
 * El texto del semáforo ("" si no se muestra). Con `ajustable` (ubicó con puntos y se ofrece
 * "Ajustar el tamaño con el cuadro"), el ámbar nombra ese botón antes que volver a Ubicar.
 */
export function textoSemaforo({ tono, dentro, total, sesgo = null }, { ajustable = false } = {}) {
  if (tono === 'verde') return `Los lotes calzan con el cuadro de superficies (${dentro} de ${total} dentro del 5 %).`;
  if (tono === 'ambar') {
    const cuantos = (total - dentro) * 2 >= total || sesgo == null
      ? `${total - dentro} de ${total} lotes miden distinto al cuadro de superficies.`
      : `Casi todos los lotes salen cerca de un ${Math.abs(sesgo * 100).toFixed(1).replace('.', ',')} %`
        + ` ${sesgo > 0 ? 'más grandes' : 'más chicos'} que en el cuadro de superficies.`;
    return ajustable
      ? `${cuantos} Suele ser la escala de los puntos de Ubicar: ajusta el tamaño con el cuadro de superficies`
        + ' o vuelve a Ubicar y marca los puntos de nuevo.'
      : `${cuantos} Suele ser la ubicación: vuelve a Ubicar y marca los puntos de nuevo.`;
  }
  return '';
}

/**
 * Las partes sin número, primero las del tamaño de un lote (un lote cuyo número no se
 * leyó) y, entre ellas, las que traen una lectura que confirmar. Sin el resto de la
 * propiedad (lo pregunta su propia tarjeta) ni lo que ella dejó fuera del KMZ.
 */
export function sinNumero(rasgos) {
  const peso = ({ properties: p }) => (p.de_lote ? 0 : 2) + (p.sugerencia ? 0 : 1);
  return rasgos.filter((r) => (r.properties.banderas ?? []).includes('sin_numero') && r.properties.numero == null
    && !r.properties.fuera && !r.properties.resto)
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

/** Leídos por el lector con poco apoyo: los que conviene mirar. El resto de la propiedad
 *  no: lo muestra su propia tarjeta. */
export function dudosos(rasgos, apoyoMinimo = 3) {
  return rasgos.filter(({ properties: p }) => p.origen === 'lector' && !p.resto
    && ((p.apoyo ?? 0) < apoyoMinimo || (p.confianza ?? 1) < 0.6));
}

/**
 * El número escrito con la forma del cuadro de superficies: si el cuadro trae el mismo
 * lote ("8-8" y "8-08" tienen la misma `claveLote`), va como lo dice el cuadro, que es
 * como sale en el KMZ. Si no, como lo escribió, sin "lote" adelante.
 */
export function formaDelCuadro(numero, cuadro) {
  const limpio = String(numero ?? '').trim().replace(/^lotes?\s*/i, '');
  if (!limpio) return '';
  const clave = claveLote(limpio);
  const delCuadro = (cuadro ?? []).map(String).find((n) => claveLote(n) === clave);
  return delCuadro ?? limpio;
}

/**
 * Los lotes con un número nuevo puesto al tiro, sin esperar a que se lea el plano de
 * nuevo: el lote que contiene `punto` queda con `numero` (de la loteadora, sin bandera
 * de sin número ni lectura que confirmar) y, si ese número estaba en otro lote, ese otro
 * lo pierde, como hará el servidor. Los repetidos se cuentan de nuevo. No toca los
 * rasgos que recibe: devuelve otros.
 */
export function aplicarNumero(rasgos, numero, punto) {
  const limpio = String(numero ?? '').trim();
  const lote = limpio ? loteEn(rasgos, punto[0], punto[1]) : null;
  if (!lote) return rasgos;
  const clave = claveLote(limpio);
  const fuera = (banderas, ...quitar) => (banderas ?? []).filter((b) => !quitar.includes(b));
  const salida = rasgos.map((r) => {
    const p = r.properties;
    if (r === lote) {
      const { sugerencia: _s, ...resto } = p;
      const nuevo = { ...r, properties: { ...resto, numero: limpio, origen: 'usuario', de_lote: false, fuera: false,
        confianza: null, apoyo: null, semilla: [punto[0], punto[1]],
        banderas: fuera(p.banderas, 'sin_numero', 'de_lote', 'fuera') } };
      return { ...nuevo, rotulo: [punto[0], punto[1]] };
    }
    if (p.numero != null && claveLote(p.numero) === clave) {
      // Era un lote con número: queda como un lote sin número (rojo), no como un camino.
      const nuevo = { ...r, properties: { ...p, numero: null, semilla: null, de_lote: true, origen: null,
        banderas: ['sin_numero', 'de_lote'] } };
      return { ...nuevo, rotulo: puntoDeRotulo(nuevo) };
    }
    return r;
  });
  // Un número que estaba repetido puede dejar de estarlo (o al revés).
  const cuenta = new Map();
  for (const { properties: p } of salida) {
    if (p.numero != null) cuenta.set(claveLote(p.numero), (cuenta.get(claveLote(p.numero)) ?? 0) + 1);
  }
  return salida.map((r) => {
    const p = r.properties;
    if (p.numero == null) return r;
    const repetido = cuenta.get(claveLote(p.numero)) > 1;
    const tenia = (p.banderas ?? []).includes('duplicado');
    if (repetido === tenia) return r;
    const banderas = repetido ? [...fuera(p.banderas), 'duplicado'] : fuera(p.banderas, 'duplicado');
    return { ...r, properties: { ...p, banderas } };
  });
}

// --- el resto de la propiedad ----------------------------------------------------------

/**
 * El resto de la propiedad (el rasgo con `resto` que marca el servidor), o null:
 * `{rasgo, estado, numero, punto}`. `estado`: "pendiente" (falta decidir si va al KMZ),
 * "incluido" (tiene número: va como un lote más) o "fuera" (lo dejó fuera, tenga o no el
 * número que leyó el lector). `numero`: con el que va o iría al KMZ, el suyo, el del cuadro
 * de superficies o "Resto" si el cuadro no le da uno. `punto`: dentro de la parte, para
 * centrar el plano y anotar la decisión.
 */
export function restoDe(rasgos) {
  const rasgo = (rasgos ?? []).find((r) => r.properties?.resto);
  if (!rasgo) return null;
  const p = rasgo.properties;
  const estado = p.fuera ? 'fuera' : p.numero != null ? 'incluido' : 'pendiente';
  const numero = p.numero ?? p.numero_resto ?? 'Resto';
  return { rasgo, estado, numero: String(numero), punto: rasgo.rotulo ?? puntoDeRotulo(rasgo) };
}

/**
 * Las entradas con la decisión sobre el resto (`anillos`: su polígono; `punto`: dentro).
 * Dejarlo fuera anota `punto` en `fuera`; incluirlo quita lo anotado dentro y, si se da
 * `numero` (la parte no tiene), pone esa semilla en `punto`. Las semillas no se tocan al
 * dejarlo fuera: así cambiar de idea no obliga a leer el plano de nuevo.
 */
export function decidirResto(entradas, anillos, punto, incluir, numero = null) {
  const dentro = ([x, y]) => puntoEnPoligono(x, y, anillos);
  const { fuera } = devolverAlKmz(entradas, anillos);
  const [x, y] = [redondo(punto[0]), redondo(punto[1])];
  if (!incluir) return { ...entradas, fuera: [...fuera, [x, y]] };
  if (!numero) return { ...entradas, fuera };
  // Un número va en un solo lote: si estaba en otro, se va de ahí (como `ponerNumero`).
  const clave = claveLote(numero);
  const semillas = (entradas.semillas ?? []).filter((s) => !dentro([s.x, s.y]) && claveLote(s.numero) !== clave);
  return { ...entradas, fuera, semillas: [...semillas, { numero, x, y }] };
}

/**
 * Las entradas sin lo anotado como fuera del KMZ dentro de la parte `anillos`. Numerar
 * esa parte a mano también la devuelve al KMZ: `aplicarNumero` la muestra incluida, y si
 * el punto quedara en `fuera` el servidor la volvería a dejar fuera al releer.
 */
export function devolverAlKmz(entradas, anillos) {
  if (!anillos || !(entradas.fuera ?? []).length) return entradas;
  return { ...entradas, fuera: entradas.fuera.filter(([x, y]) => !puntoEnPoligono(x, y, anillos)) };
}

/**
 * Todas las lecturas sugeridas confirmadas de una vez, como si confirmara cada una:
 * semilla nueva, la parte de vuelta al KMZ y el lote verde al tiro. Se salta las que
 * chocan (el número ya está en otra semilla, o dos sugerencias traen el mismo): esas las
 * decide ella una por una, porque pasar un número de lote sin preguntar le quitaría el
 * número a otro. No toca lo que recibe.
 * Devuelve `{entradas, rasgos, confirmadas, omitidas}` (las dos últimas, listas de números).
 */
export function confirmarSugerencias(entradas, rasgos, cuadro) {
  // Se calculan antes: al aplicar cada número los rasgos cambian y la lista se correría.
  const lista = sugerencias(rasgos);
  // También los números que ya tiene un lote (leídos por el lector, sin semilla): confirmar
  // en masa no debe quitárselos callado a otro lote; la pastilla sí pregunta.
  const tomados = new Set([...(entradas.semillas ?? []).map((s) => s.numero),
    ...rasgos.map((r) => r.properties.numero).filter((n) => n != null)].map(claveLote));
  let salidaEntradas = entradas;
  let salidaRasgos = rasgos;
  const confirmadas = [];
  const omitidas = [];
  for (const s of lista) {
    const numero = formaDelCuadro(s.numero, cuadro);
    if (!numero) continue;
    const clave = claveLote(numero);
    if (tomados.has(clave)) {
      omitidas.push(numero);
      continue;
    }
    tomados.add(clave);
    const anillos = s.rasgo.geometry.coordinates;
    const semillas = ponerNumero(salidaEntradas.semillas ?? [], numero, s.rasgo.rotulo, anillos);
    salidaEntradas = { ...devolverAlKmz(salidaEntradas, anillos), semillas };
    // Donde quedó la semilla (si la parte ya tenía una, ahí): ahí va el rótulo.
    const puesta = semillas.find((x) => x.numero === numero);
    if (puesta) salidaRasgos = aplicarNumero(salidaRasgos, numero, [puesta.x, puesta.y]);
    confirmadas.push(numero);
  }
  return { entradas: salidaEntradas, rasgos: salidaRasgos, confirmadas, omitidas };
}

/**
 * Los lotes con el resto dejado fuera (o vuelto atrás) al tiro, como lo dirá el servidor:
 * la parte que contiene `punto` queda fuera del KMZ, sin contar como lote sin número; o
 * vuelve a ser un lote sin número o el lote numerado que era. No toca los rasgos que recibe.
 */
export function aplicarFuera(rasgos, punto, fuera) {
  const parte = loteEn(rasgos, punto[0], punto[1]);
  if (!parte) return rasgos;
  return rasgos.map((r) => {
    if (r !== parte) return r;
    const p = r.properties;
    const otras = (p.banderas ?? []).filter((b) => !['fuera', 'de_lote'].includes(b));
    const sinNumero = p.numero == null;
    const banderas = [...otras, ...(fuera ? ['fuera'] : sinNumero ? ['de_lote'] : [])];
    return { ...r, properties: { ...p, fuera, de_lote: sinNumero && !fuera, sugerencia: fuera ? null : p.sugerencia, banderas } };
  });
}

/**
 * Las semillas de la loteadora que el último digitalizado todavía no tiene (las puso
 * después), puestas encima de los lotes: así un número recién escrito no se borra al
 * recargar los lotes mientras se vuelve a leer el plano.
 */
export function conSemillas(rasgos, semillas) {
  let salida = rasgos;
  for (const s of semillas ?? []) {
    const lote = loteEn(salida, s.x, s.y);
    if (lote && claveLote(lote.properties.numero ?? '') !== claveLote(s.numero)) {
      salida = aplicarNumero(salida, s.numero, [s.x, s.y]);
    }
  }
  return salida;
}

/**
 * Los números de `lista` (los del cuadro de superficies o, sin cuadro, los huecos de la
 * numeración) que ningún lote tiene todavía: los que ofrece el campo del número.
 */
export function numerosQueFaltan(lista, rasgos) {
  const puestos = new Set(rasgos.filter((r) => r.properties.numero != null).map((r) => claveLote(r.properties.numero)));
  return (lista ?? []).map(String).filter((n) => !puestos.has(claveLote(n)));
}

/**
 * El mensaje único de Numerar: cuántos lotes faltan por numerar y qué hacer. Las partes
 * sin número que no son del tamaño de un lote (caminos, áreas comunes) van en una frase
 * corta. `faltan`: los números que ningún lote tiene (para cuando no queda ningún lote
 * rojo pero falta un número, p. ej. dos lotes que quedaron juntos).
 */
export function mensajeNumerar(rasgos, faltan = []) {
  const partes = sinNumero(rasgos);
  const lotes = partes.filter((r) => r.properties.de_lote).length;
  const otras = partes.length - lotes;
  const otrasTexto = otras === 1
    ? ' Queda 1 parte chica sin número: si es un camino o un área común, se deja así.'
    : otras ? ` Quedan ${otras} partes chicas sin número: si son caminos o áreas comunes, se dejan así.` : '';
  if (lotes) {
    const cuantos = lotes === 1 ? 'Falta 1 número' : `Faltan ${lotes} números`;
    return `${cuantos}: haz clic en cada lote rojo y elige su número.${otrasTexto}`;
  }
  const lista = (faltan ?? []).map(String);
  if (lista.length) {
    if (lista.length === 1) {
      return `Falta el ${lista[0]} en el plano: búscalo; puede que dos lotes hayan quedado juntos.${otrasTexto}`;
    }
    const cuales = `${lista.slice(0, -1).join(', ')} y ${lista[lista.length - 1]}`;
    return `Faltan ${cuales} en el plano: búscalos; puede que haya lotes que quedaron juntos.${otrasTexto}`;
  }
  return `Todos los lotes tienen número.${otrasTexto}`;
}

/**
 * ¿Un error de `pedir` es de la conexión o del servidor caído (sin respuesta o 5xx), y no
 * una respuesta que dice que algo no sirve? Lo pasajero se avisa y se puede reintentar.
 */
export function esFalloPasajero(error) {
  const estado = error?.estado;
  return estado == null || estado >= 500;
}

// --- pasos ---------------------------------------------------------------------------

/**
 * Los paneles de la pantalla, en orden. Leer el plano (`digitalizar`, el escáner) y Numerar
 * no tienen pastilla: son parte de Marcar (ver `PASTILLAS` y `pastillaDe`).
 */
export const PASOS = ['subir', 'marcar', 'digitalizar', 'numerar', 'ubicar', 'revisar'];

/** Las pastillas de la barra de pasos: Subir el plano · Marcar · Ubicar · Revisar y descargar. */
export const PASTILLAS = ['subir', 'marcar', 'ubicar', 'revisar'];

/** La pastilla que queda marcada con el panel `paso` abierto. */
export function pastillaDe(paso) {
  return ['digitalizar', 'numerar'].includes(paso) ? 'marcar' : PASTILLAS.includes(paso) ? paso : 'subir';
}

/**
 * El panel que abre `#/kmz/<slug>/<nombre>`, o null si el nombre no es de un paso. Las
 * rutas de cuando había siete pastillas llevan al paso que hoy las contiene: Leer el plano
 * a Marcar (o al escáner si se está leyendo) y Crear el KMZ a Revisar y descargar.
 */
export function pasoDeRuta(nombre, e) {
  const trabajando = Boolean(e?.trabajo && !e.trabajo.terminado);
  switch (nombre) {
    case 'subir': case 'marcar': case 'numerar': case 'ubicar': case 'revisar':
      return nombre;
    case 'digitalizar': case 'leer':
      return trabajando ? 'digitalizar' : 'marcar';
    case 'crear': case 'descargar':
      return 'revisar';
    default:
      return null;
  }
}

/**
 * Si los lotes digitalizados (`digitalizado.pagina`) están en los px de la página que se
 * ve. Con la unión de hojas no basta la página 0: otra unión tiene otros px, y por eso
 * se compara también su huella (`huellaUnion`, la de `plano.union`). Sin `pagina` (lo
 * digitalizado antes de anotarla), se supone que sí.
 */
export function calzaLoDigitalizado(pagina, entradas, huellaUnion = null) {
  if (!pagina) return true;
  const union = entradas.pagina === 0 ? huellaUnion ?? null : null;
  return pagina.numero === entradas.pagina && pagina.rotacion === (entradas.rotacion ?? 0)
    && (pagina.union ?? null) === union;
}

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
  };
}

/**
 * ¿Hace falta pasar por Numerar antes de ubicar? Sí si queda un lote sin número (rojo),
 * falta en los lotes un hueco de la numeración (con los del cuadro, si calza), un número
 * marcado no cayó en ningún lote, hay lecturas por confirmar, números repetidos o la
 * pregunta del resto de la propiedad sin contestar. Las partes chicas sin número (caminos,
 * áreas comunes) no: se dejan así. `e`: el estado del servidor; `rasgos`: los lotes en px.
 */
export function hayQueNumerar(e, rasgos) {
  const d = e?.digitalizado;
  if (!d) return false;
  const lotes = rasgos ?? [];
  if (sinNumero(lotes).some((r) => r.properties.de_lote)) return true;
  if (sugerencias(lotes).length || duplicados(lotes).length) return true;
  const resto = restoDe(lotes);
  if (resto?.estado === 'pendiente') return true;
  if ((d.faltantes ?? []).length || (d.lector?.sin_poligono ?? []).length) return true;
  // Los que faltan son los huecos, lo mismo que dice Numerar (`mensajeNumerar`): ya traen
  // los del cuadro cuando el cuadro calza con lo leído. Con `numeros_cuadro` crudo, un cuadro
  // que no calza (mal leído, o de otra lámina) mandaba a Numerar a leer "Todos los lotes
  // tienen número". El número del resto, si lo dejó fuera, no es un lote que falte.
  const delResto = resto ? claveLote(resto.numero) : null;
  return numerosQueFaltan(d.huecos, lotes).some((n) => claveLote(n) !== delResto);
}

/**
 * A qué panel lleva "Seguir" desde `paso` (null si no hay otro: en Revisar y descargar se
 * crea el KMZ). Después de leer el plano, a Numerar solo si hace falta (`hayQueNumerar`).
 */
export function pasoSiguiente(paso, e, rasgos) {
  switch (paso) {
    case 'subir': return 'marcar';
    case 'marcar': case 'digitalizar': return hayQueNumerar(e, rasgos) ? 'numerar' : 'ubicar';
    case 'numerar': return 'ubicar';
    case 'ubicar': return 'revisar';
    default: return null;
  }
}

/**
 * ¿La ubicación con un punto trae el punto del plano y su coordenada? Mientras se arma
 * puede venir solo la coordenada; el servidor la ignora hasta que esté completa.
 */
export function ubicacionCompleta(u) {
  return Boolean(u) && ['x', 'y', 'lon', 'lat'].every((k) => Number.isFinite(u[k]));
}

/**
 * ¿Hay con qué ubicar? La cuadrícula elegida, 2 o más puntos, o la coordenada con su
 * punto en el plano (lo mismo que prueba `georreferenciar` en el servidor).
 */
export function puedeUbicar(entradas) {
  return Boolean(entradas?.cuadricula) || (entradas?.anclas?.length ?? 0) >= 2
    || ubicacionCompleta(entradas?.ubicacion);
}

/**
 * "Seguir: numerar" desde el paso 3: solo con una digitalización vigente (hecha con
 * lo último que se marcó) y sin otra corriendo. Sin digitalizar, no hay qué numerar.
 */
export function puedeSeguirANumerar(e) {
  const trabajando = Boolean(e?.trabajo && !e.trabajo.terminado);
  return Boolean(e?.digitalizado?.vigente) && !trabajando;
}

/**
 * Por qué no se puede seguir desde `paso` ("" si se puede): va en una línea bajo el
 * "Seguir" deshabilitado, que si no se ve apagado sin explicación. Es también lo que
 * lo deshabilita, para que el motivo y el botón no se contradigan.
 * `e`: el estado del servidor. `local`: lo que sabe solo la pantalla —
 * `entradas`, `actualizando` (se está por volver a leer el plano, o se está leyendo),
 * `releerFallo` (la relectura sola falló), `ubicando` (se está calculando la ubicación)
 * y `duplicados` (cuántos números repetidos).
 */
export function porQueNoSigue(paso, e, local = {}) {
  const trabajando = Boolean(e?.trabajo && !e.trabajo.terminado);
  const d = e?.digitalizado;
  switch (paso) {
    case 'marcar':
      if (pasosHabilitados(e).digitalizar) return '';
      return local.entradas?.rectangulo ? 'Guardando lo marcado…' : 'Falta encerrar el dibujo del loteo.';
    case 'digitalizar':
      if (puedeSeguirANumerar(e)) return '';
      if (trabajando) return 'Leyendo el plano…';
      return d ? 'Cambiaste lo marcado: lee el plano de nuevo.' : 'Falta leer el plano.';
    case 'numerar':
      if (!d) return 'Falta leer el plano.';
      if (trabajando || local.actualizando) return 'Actualizando los lotes…';
      // Al día gana sobre un fallo anterior: si después se leyó bien (en el paso 3), se sigue.
      if (d.vigente) return '';
      return local.releerFallo ? 'No se pudieron actualizar los lotes: vuelve a Marcar y lee el plano de nuevo.'
        : 'Actualizando los lotes…';
    case 'ubicar': {
      // Mientras se ubica (o está por ubicarse tras girar o mover) lo ubicado ya no es lo que se ve.
      if (e?.georreferencia?.vigente && !local.ubicando) return '';
      if (d && !d.vigente) return 'Cambiaste el plano: abre "Revisar los números" para que se lea de nuevo.';
      if (!puedeUbicar(local.entradas)) {
        return 'Pega tu coordenada y haz clic en ese punto del plano, o marca 2 puntos en "Afinar con puntos".';
      }
      // Con solo la coordenada, el tamaño sale del cuadro de superficies o de la escala impresa.
      const soloCoordenada = !local.entradas?.cuadricula && (local.entradas?.anclas?.length ?? 0) < 2;
      if (soloCoordenada && d?.escala_m_px == null && !local.entradas?.ubicacion?.escala_impresa) {
        return 'Para ubicar con tu coordenada falta la escala del plano (por ejemplo 1:5.000), o marca puntos.';
      }
      return local.ubicando ? 'Ubicando el plano…' : 'Aprieta "Ubicar de nuevo" para ubicar los lotes.';
    }
    case 'revisar':
      return local.duplicados ? 'Hay números repetidos: corrígelos en "Revisar los números".' : '';
    default:
      return '';
  }
}

/** El paso donde conviene abrir la pantalla, según `estado.paso` del servidor. */
export function pasoSugerido(e) {
  switch (e?.paso) {
    case 'subir': return 'subir';
    case 'marcar': return 'marcar';
    // Sin leer, el plano se lee con "Seguir" de Marcar; leído con algo que cambió, en
    // Numerar se vuelve a leer solo.
    case 'digitalizar': return e.digitalizado ? 'numerar' : 'marcar';
    // Las caras sin número pueden ser caminos: solo los números perdidos piden volver.
    case 'ubicar': return e.digitalizado?.faltantes?.length ? 'numerar' : 'ubicar';
    case 'crear': return 'revisar';
    case 'listo': return 'revisar';
    default: return 'subir';
  }
}

/** Qué pastillas ya están hechas (para la marca ✓). Marcar incluye leer el plano. */
export function pasosHechos(e) {
  const hecho = (paso) => {
    const orden = ['subir', 'marcar', 'digitalizar', 'ubicar', 'crear', 'listo'];
    return orden.indexOf(e?.paso) > orden.indexOf(paso);
  };
  return {
    subir: hecho('subir'),
    marcar: hecho('digitalizar'),
    ubicar: hecho('ubicar'),
    revisar: e?.paso === 'listo',
  };
}

/** "UTM 19S · WGS84": el sistema de coordenadas, para el detalle técnico de Ubicar. */
export function nombreDelSistema(epsg) {
  if (epsg >= 32701 && epsg <= 32760) return `UTM ${epsg - 32700}S · WGS84`;
  if (epsg >= 32601 && epsg <= 32660) return `UTM ${epsg - 32600}N · WGS84`;
  if (epsg >= 24877 && epsg <= 24882) return `UTM ${epsg - 24860}S · PSAD56`;
  if (epsg >= 24817 && epsg <= 24821) return `UTM ${epsg - 24800}N · PSAD56`;
  return epsg ? `EPSG ${epsg}` : '—';
}

/**
 * Los vértices de los lotes (GeoJSON en lon/lat), sin repetir: un vértice que
 * comparten dos lotes es uno solo, y se mueve en los dos. Van tal como vinieron del
 * servidor, que los busca por esas coordenadas.
 */
export function verticesDe(rasgos) {
  const vistos = new Map();
  for (const rasgo of rasgos ?? []) {
    const anillo = rasgo.geometry?.coordinates?.[0] ?? [];
    for (const [lon, lat] of anillo.slice(0, -1)) {
      const clave = `${lon.toFixed(9)},${lat.toFixed(9)}`;
      if (!vistos.has(clave)) vistos.set(clave, { lon, lat });
    }
  }
  return [...vistos.values()];
}

/**
 * Cuánto se aleja un punto de donde lo dejan los demás, en metros enteros: los decímetros
 * no le dicen nada a quien marcó el punto a ojo en una imagen satelital.
 */
export function distanciaEnPalabras(metros) {
  if (metros == null || !Number.isFinite(metros)) return '—';
  return metros < 1 ? 'menos de 1 m' : `${Math.round(metros)} m`;
}

/**
 * Lo que dice la tabla de Ubicar de un punto: su distancia y si calza. `r` es su fila en la
 * ubicación (undefined si aún no se ubicó con él). Con 2 puntos no se puede comprobar nada
 * (la distancia sale 0 por construcción): decir "Calza" contradiría el aviso.
 */
export function filaDelPunto(r, g, vigente) {
  if (!r || !vigente) return { distancia: '—', estado: '', detalle: '' };
  if (g?.parametros?.control === 'sin control') return { distancia: '—', estado: '', detalle: '' };
  if (g?.atipicas?.includes(r.nombre)) {
    return { distancia: distanciaEnPalabras(r.residuo_m), estado: 'No calza', detalle: 'márcalo de nuevo' };
  }
  return { distancia: distanciaEnPalabras(r.residuo_m), estado: 'Calza', detalle: '' };
}

/**
 * "Ubicado con 4 puntos · calzan con ±5 m": cómo quedó ubicado, sin sistemas de
 * coordenadas ni errores medios. `n` son los puntos marcados, si el servidor no los cuenta.
 */
export function resumenUbicacion(g, n = 0) {
  const p = g?.parametros ?? {};
  if (g?.metodo === 'punto') return 'Ubicado con tu coordenada';
  const cuadricula = g?.metodo === 'cuadricula';
  const cuantos = p.n_anclas ?? n;
  const partes = [cuadricula ? 'Ubicado con la cuadrícula impresa'
    : `Ubicado con ${cuantos} ${cuantos === 1 ? 'punto' : 'puntos'}`];
  // Con 2 puntos no hay con qué comparar (el servidor no da error medio): no se dice nada.
  if (Number.isFinite(p.rms_m)) partes.push(`${cuadricula ? 'calza' : 'calzan'} con ±${Math.max(1, Math.round(p.rms_m))} m`);
  return partes.join(' · ');
}

/** Lo técnico de la ubicación (sistema, error medio, datum), para quien lo quiera ver. */
export function detalleUbicacion(g) {
  if (!g) return '';
  const partes = [nombreDelSistema(g.epsg)];
  if (Number.isFinite(g.parametros?.rms_m)) partes.push(`error medio ${g.parametros.rms_m.toFixed(1)} m`);
  if (g.datum?.datum) partes.push(`datum ${g.datum.datum}`);
  return partes.join(' · ');
}

// --- ubicar con un punto: la vista previa -------------------------------------------
//
// Mientras ella gira el plano o lo arrastra, los lotes se mueven sobre el satélite sin
// esperar al servidor: aquí se repite `por_punto` de `pipeline/plano/georreferencia.py`
// (la misma similitud en UTM) y el paso UTM ↔ lon/lat. Una proyección equirectangular
// alrededor del punto no alcanza: en Rapel el norte de la cuadrícula UTM está ~1,4°
// girado respecto del norte verdadero (convergencia de meridianos, huso 19), y el giro
// que ella eligiera mirando la vista previa saldría corrido eso mismo en el KMZ.

// WGS84 y UTM (k0, falso este y falso norte del hemisferio sur).
const SEMIEJE = 6378137;
const APLANAMIENTO = 1 / 298.257223563;
const K0 = 0.9996;
const N_ = APLANAMIENTO / (2 - APLANAMIENTO);
// Series de Krüger hasta n³ (error de milímetros dentro del huso): radio rectificador A
// y los coeficientes α (directa), β (inversa) y δ (latitud conforme → geodésica).
const RADIO_A = (SEMIEJE / (1 + N_)) * (1 + N_ ** 2 / 4 + N_ ** 4 / 64);
const ALFA = [N_ / 2 - (2 * N_ ** 2) / 3 + (5 * N_ ** 3) / 16, (13 * N_ ** 2) / 48 - (3 * N_ ** 3) / 5, (61 * N_ ** 3) / 240];
const BETA = [N_ / 2 - (2 * N_ ** 2) / 3 + (37 * N_ ** 3) / 96, N_ ** 2 / 48 + N_ ** 3 / 15, (17 * N_ ** 3) / 480];
const DELTA = [2 * N_ - (2 * N_ ** 2) / 3 - 2 * N_ ** 3, (7 * N_ ** 2) / 3 - (8 * N_ ** 3) / 5, (56 * N_ ** 3) / 15];
const RAD = Math.PI / 180;

/** El EPSG del huso UTM WGS84 que contiene el punto (como `huso` del servidor). */
export function husoDe(lon, lat) {
  const zona = Math.min(60, Math.max(1, Math.floor((lon + 180) / 6) + 1));
  return (lat < 0 ? 32700 : 32600) + zona;
}

function zonaUtm(epsg) {
  if (epsg >= 32701 && epsg <= 32760) return { zona: epsg - 32700, sur: true };
  if (epsg >= 32601 && epsg <= 32660) return { zona: epsg - 32600, sur: false };
  throw new Error(`EPSG ${epsg} no es un UTM WGS84`);
}

/** lon/lat WGS84 → [E, N] en el UTM `epsg`. */
export function lonLatAUtm(lon, lat, epsg) {
  const { zona, sur } = zonaUtm(epsg);
  const dl = (lon - (zona * 6 - 183)) * RAD;
  const s = Math.sin(lat * RAD);
  const c = (2 * Math.sqrt(N_)) / (1 + N_);
  const t = Math.sinh(Math.atanh(s) - c * Math.atanh(c * s));
  const xi = Math.atan2(t, Math.cos(dl));
  const eta = Math.atanh(Math.sin(dl) / Math.sqrt(1 + t * t));
  let e = eta;
  let n = xi;
  ALFA.forEach((a, i) => {
    const j = 2 * (i + 1);
    e += a * Math.cos(j * xi) * Math.sinh(j * eta);
    n += a * Math.sin(j * xi) * Math.cosh(j * eta);
  });
  return [500000 + K0 * RADIO_A * e, (sur ? 10000000 : 0) + K0 * RADIO_A * n];
}

/** [E, N] en el UTM `epsg` → [lon, lat] WGS84. */
export function utmALonLat(este, norte, epsg) {
  const { zona, sur } = zonaUtm(epsg);
  const xi = (norte - (sur ? 10000000 : 0)) / (K0 * RADIO_A);
  const eta = (este - 500000) / (K0 * RADIO_A);
  let xi1 = xi;
  let eta1 = eta;
  BETA.forEach((b, i) => {
    const j = 2 * (i + 1);
    xi1 -= b * Math.sin(j * xi) * Math.cosh(j * eta);
    eta1 -= b * Math.cos(j * xi) * Math.sinh(j * eta);
  });
  const chi = Math.asin(Math.sin(xi1) / Math.cosh(eta1));
  let lat = chi;
  DELTA.forEach((d, i) => { lat += d * Math.sin(2 * (i + 1) * chi); });
  const lon = (zona * 6 - 183) * RAD + Math.atan2(Math.sinh(eta1), Math.cos(xi1));
  return [lon / RAD, lat / RAD];
}

/** (x, y) por la homografía 3×3 `h` (null: la identidad). */
export function aplicarHomografia(h, x, y) {
  if (!h) return [x, y];
  const w = h[2][0] * x + h[2][1] * y + h[2][2];
  return [(h[0][0] * x + h[0][1] * y + h[0][2]) / w, (h[1][0] * x + h[1][1] * y + h[1][2]) / w];
}

const multiplicar = (a, b) => a.map((fila) => b[0].map((_, j) => fila.reduce((s, v, k) => s + v * b[k][j], 0)));

/**
 * La similitud de `por_punto`: {epsg, matriz} con matriz 3×3 de px de página a (E, N, 1)
 * en el UTM del punto. `escalaMPx` es m por px de trabajo y `homografia`, página →
 * trabajo. El giro es horario (lo que ella gira el plano en pantalla para dejar el norte
 * arriba), por eso la rotación de la similitud es −giro. null si falta algo.
 */
export function similitudPorPunto(u, escalaMPx, homografia = null) {
  if (!ubicacionCompleta(u) || !(Number.isFinite(escalaMPx) && escalaMPx > 0)) return null;
  const epsg = husoDe(u.lon, u.lat);
  const [xt, yt] = aplicarHomografia(homografia, u.x, u.y);
  const [e, n] = lonLatAUtm(u.lon, u.lat, epsg);
  const rotacion = -(u.giro ?? 0) * RAD;
  // w = a·z + b con z = x − i·y (y del plano hacia abajo, N hacia arriba).
  const ar = escalaMPx * Math.cos(rotacion);
  const ai = escalaMPx * Math.sin(rotacion);
  const br = e - (ar * xt + ai * yt);
  const bi = n - (ai * xt - ar * yt);
  const s = [[ar, ai, br], [ai, -ar, bi], [0, 0, 1]];
  return { epsg, matriz: homografia ? multiplicar(s, homografia) : s };
}

/**
 * La similitud de `por_anclas` (mínimos cuadrados con 2 o más puntos): {epsg, matriz} como
 * `similitudPorPunto`, para ver los lotes desde el segundo punto sin esperar al servidor.
 * `homografia` (página → trabajo) solo si el plano es una foto rectificada (modo
 * perspectiva), igual que `georreferenciar`: en un recorte es una escala y una traslación
 * que la similitud absorbe. null con menos de 2 puntos o con todos en el mismo lugar.
 *
 * Con `escalaMPx` (m por px de trabajo: la del cuadro de superficies) es "Ajustar el tamaño
 * con el cuadro", como `por_anclas(..., escala_m_px=...)`: el mismo giro, ese tamaño y el
 * centroide de los puntos en el mismo lugar del mapa. `homografiaTrabajo` (página →
 * trabajo, la del estado) pasa esa escala a px de página cuando los puntos se ajustan ahí.
 */
export function similitudPorAnclas(anclas, homografia = null, { escalaMPx = null, homografiaTrabajo = null } = {}) {
  const validas = (anclas ?? []).filter((a) => ['x', 'y', 'lon', 'lat'].every((k) => Number.isFinite(a?.[k])));
  if (validas.length < 2) return null;
  const media = (v) => v.reduce((s, x) => s + x, 0) / v.length;
  const epsg = husoDe(media(validas.map((a) => a.lon)), media(validas.map((a) => a.lat)));
  // y del plano hacia abajo y N hacia arriba: con y negada la similitud no refleja.
  const z = validas.map((a) => { const [x, y] = aplicarHomografia(homografia, a.x, a.y); return [x, -y]; });
  const w = validas.map((a) => lonLatAUtm(a.lon, a.lat, epsg));
  const [zr, zi] = [media(z.map((p) => p[0])), media(z.map((p) => p[1]))];
  const [wr, wi] = [media(w.map((p) => p[0])), media(w.map((p) => p[1]))];
  // a = Σ conj(z − z̄)·(w − w̄) / Σ |z − z̄|², b = w̄ − a·z̄ (como `_similitud`).
  let ar = 0;
  let ai = 0;
  let norma = 0;
  z.forEach(([x, y], i) => {
    const [dx, dy] = [x - zr, y - zi];
    const [ex, ey] = [w[i][0] - wr, w[i][1] - wi];
    ar += dx * ex + dy * ey;
    ai += dx * ey - dy * ex;
    norma += dx * dx + dy * dy;
  });
  if (norma < 1e-18) return null;
  ar /= norma;
  ai /= norma;
  if (Number.isFinite(escalaMPx) && escalaMPx > 0) {
    // b = w̄ − a·z̄ (abajo) deja el centroide donde estaba con cualquier |a|.
    const k = escalaEnElAjuste(escalaMPx, homografiaTrabajo, Boolean(homografia)) / Math.hypot(ar, ai);
    ar *= k;
    ai *= k;
  }
  const br = wr - (ar * zr - ai * zi);
  const bi = wi - (ar * zi + ai * zr);
  // z = x − i·y: E = ar·x + ai·y + br, N = ai·x − ar·y + bi.
  const s = [[ar, ai, br], [ai, -ar, bi], [0, 0, 1]];
  return { epsg, matriz: homografia ? multiplicar(s, homografia) : s };
}

/**
 * m por px de trabajo → m por px del plano donde se ajustan los puntos (`escala_en_el_ajuste`
 * del servidor): el mismo con la foto rectificada; en un recorte, un px de página son
 * sqrt(|det|) px de trabajo.
 */
export function escalaEnElAjuste(escalaTrabajo, homografiaTrabajo, enTrabajo) {
  const h = homografiaTrabajo;
  if (enTrabajo || !h) return escalaTrabajo;
  return escalaTrabajo * Math.sqrt(Math.abs(h[0][0] * h[1][1] - h[0][1] * h[1][0])) / Math.abs(h[2][2]);
}

/**
 * ¿Se ubica con el tamaño del cuadro? Lo pidió ("Ajustar el tamaño con el cuadro") y
 * ubica con 2 o más puntos: con la cuadrícula o la coordenada el servidor no lo usa.
 */
export function ajustaConElCuadro(entradas) {
  return Boolean(entradas?.escala_cuadro) && !entradas?.cuadricula && (entradas?.anclas?.length ?? 0) >= 2;
}

/**
 * ¿Se ofrece "Ajustar el tamaño con el cuadro"? Si ubicó con puntos, los lotes salen parejo
 * más chicos o más grandes (`sesgo`, de `sesgoDeEscala` o del semáforo) y aún no lo ajustó.
 */
export function ofrecerAjusteDelCuadro(entradas, sesgo) {
  return sesgo != null && !entradas?.escala_cuadro && !entradas?.cuadricula && (entradas?.anclas?.length ?? 0) >= 2;
}

/** px de página → [lon, lat] con la similitud `t` y el ajuste fino (metros E, N). */
export function paginaALonLat(t, x, y, ajuste = null) {
  const [e, n] = aplicarHomografia(t.matriz, x, y);
  return utmALonLat(e + (ajuste?.de ?? 0), n + (ajuste?.dn ?? 0), t.epsg);
}

/**
 * La escala (m por px de trabajo) con que se ubica con un punto: la del cuadro de
 * superficies o, sin cuadro, la impresa (1:N son N/1000/ppmm m por px). null si no hay.
 */
export function escalaDeUbicacion(digitalizado, ubicacion) {
  if (Number.isFinite(digitalizado?.escala_m_px) && digitalizado.escala_m_px > 0) return digitalizado.escala_m_px;
  const n = ubicacion?.escala_impresa;
  const ppmm = digitalizado?.ppmm;
  return n && ppmm ? n / 1000 / ppmm : null;
}

/**
 * ¿"Afinar con puntos" se abre sola? Cuando ya hay puntos (o un punto a medias o por
 * rehacer) o la cuadrícula elegida, que también vive ahí: si no, lo que manda quedaría
 * escondido.
 */
export function afinarAbierta(entradas, { pendiente = null, rehacer = null } = {}) {
  return (entradas?.anclas?.length ?? 0) > 0 || Boolean(entradas?.cuadricula) || Boolean(pendiente || rehacer);
}

/**
 * La línea de estado de "Afinar con puntos": qué toca ahora y quién manda. `coordenada`
 * dice si ella ya ubicó con su coordenada (con 2 puntos dejan de mandar su coordenada y
 * el giro: hay que decírselo).
 */
export function textoPuntos({ n = 0, pendiente = null, rehacer = null, coordenada = false, cuadricula = false } = {}) {
  if (pendiente) {
    return `Punto ${pendiente} marcado en el plano. Ahora haz clic en el mismo punto del mapa, `
      + `o pega sus coordenadas arriba y aprieta "Usar como punto ${pendiente}" (Esc cancela).`;
  }
  if (rehacer) return `Marca de nuevo el punto ${rehacer}: primero en el plano, después en el mapa.`;
  const como = 'Haz clic en un punto del plano (acerca bien) y después en el mismo punto del mapa.';
  if (cuadricula) {
    return n ? `${n} ${n === 1 ? 'punto' : 'puntos'} para comprobar la cuadrícula. ${como}`
      : `Puedes marcar puntos para comprobar que la cuadrícula calza. ${como}`;
  }
  const mandan = coordenada ? 'Con 2 o más puntos, ellos mandan sobre tu coordenada.' : 'Con 2 puntos ya se ubica el plano.';
  if (n === 0) return `${como} ${mandan}`;
  if (n === 1) return `1 punto. Marca otro: ${mandan.charAt(0).toLowerCase()}${mandan.slice(1)}`;
  const control = n < 4 ? ' Con 4 se nota si alguno quedó mal marcado.' : '';
  return `${n} puntos.${coordenada ? ' Con 2 o más puntos, ellos mandan sobre tu coordenada.' : ''}${control}`;
}

/** ¿El servidor ubica con la coordenada? Sin cuadrícula elegida y sin 2 puntos que manden. */
export function usaUbicacion(entradas) {
  return !entradas?.cuadricula && (entradas?.anclas?.length ?? 0) < 2 && ubicacionCompleta(entradas?.ubicacion);
}

/**
 * Los lotes en px de página (`lotes?en=px`) llevados a lon/lat con la similitud: el mismo
 * GeoJSON que daría el servidor, para dibujarlo al tiro sobre el satélite.
 */
export function lotesEnElMapa(rasgos, t, ajuste = null) {
  return {
    type: 'FeatureCollection',
    features: rasgos.map((r) => ({
      type: 'Feature',
      properties: r.properties,
      geometry: {
        type: 'Polygon',
        coordinates: r.geometry.coordinates.map((anillo) => anillo.map(([x, y]) => paginaALonLat(t, x, y, ajuste))),
      },
    })),
  };
}

// La escala impresa razonable, la misma de `digitalizar._ubicacion` en el servidor.
export const ESCALA_IMPRESA_MIN = 100;
export const ESCALA_IMPRESA_MAX = 1000000;

/**
 * "5.000", "5000", "1:5.000" o "1 : 5 000" → 5000; vacío → null; lo que no es una escala
 * → NaN (para decir que está mal). El punto es separador de miles, como se escribe aquí.
 */
export function leerEscala(texto) {
  const limpio = String(texto ?? '').replace(/\s/g, '').replace(/^1:/, '');
  if (!limpio) return null;
  if (!/^\d{1,3}(\.\d{3})*$|^\d+$/.test(limpio)) return Number.NaN;
  const n = Number(limpio.replace(/\./g, ''));
  return n >= ESCALA_IMPRESA_MIN && n <= ESCALA_IMPRESA_MAX ? n : Number.NaN;
}

/**
 * El lienzo del plano girado `grados` (horario) en torno a (cx, cy): pantalla sin girar →
 * pantalla girada. Con −grados se deshace (para llevar un clic a la página).
 */
export function girarEnPantalla(sx, sy, grados, cx, cy) {
  if (!grados) return [sx, sy];
  const r = grados * RAD;
  const [dx, dy] = [sx - cx, sy - cy];
  return [cx + dx * Math.cos(r) - dy * Math.sin(r), cy + dx * Math.sin(r) + dy * Math.cos(r)];
}

/** La caja [ancho, alto] que ocupa una página ancho×alto girada `grados`. */
export function cajaGirada(ancho, alto, grados) {
  const r = grados * RAD;
  const [c, s] = [Math.abs(Math.cos(r)), Math.abs(Math.sin(r))];
  return [ancho * c + alto * s, ancho * s + alto * c];
}
