/**
 * Mientras se construye o se publica un loteo: un dron sobrevuela un loteo de
 * juguete y sus parcelas se van pintando a medida que avanza el trabajo.
 *
 * El avance sale de las propias líneas del pipeline ("Leyendo el KMZ...",
 * "Proyectando parcelas...") y no de un temporizador: la barra dice la verdad.
 * El registro técnico sigue ahí, plegado, para cuando algo sale raro.
 */
import { $ } from './comun.js';

/** Cada paso que la persona ve, y las líneas del pipeline que lo anuncian. */
export const PASOS = {
  construir: [
    ['Leyendo el plano', /^Leyendo el KMZ/],
    ['Leyendo precios y estados', /^Leyendo (la planilla|el CRM)/],
    ['Ordenando las fotos del dron', /^Leyendo las panorámicas/],
    ['Orientando las fotos con el sol', /^Resolviendo el rumbo/],
    ['Midiendo el terreno', /^(Cargando el modelo de terreno|Ubicando los puntos de referencia)/],
    ['Calzando el plano con la foto', /^(Calibrando la pose|Sin calibración)/],
    ['Dibujando las parcelas', /^Proyectando parcelas/],
    ['Preparando las imágenes', /^(Generando niveles de imagen|Escribiendo los datos)/],
    ['Revisando el calce', /^Generando control de calce/],
  ],
  publicar: [
    ['Preparando el sitio', /^Visor copiado/],
    ['Subiendo a la web', /^▶ Publicando/],
    ['Dejándolo en línea', /^(Production|Aliased|▶ URL publicada)/],
  ],
  // Crea tu KMZ: las líneas de `python -m pipeline.plano digitalizar`.
  'digitalizar-plano': [
    ['Abriendo el plano', /^Página \d+/],
    ['Leyendo los números de lote', /^(Rótulos|Lector|Cuadrícula|Cuadro de superficies)/],
    ['Siguiendo los deslindes', /^(Imagen de trabajo|Tinta)/],
    ['Separando los lotes', /^(Semillas|Regiones)/],
    ['Enderezando las líneas', /^(Red de deslindes|Lotes:)/],
  ],
};

/** El resultado de los trabajos que no son construir ni publicar. */
const RESUMENES = {
  'digitalizar-plano': (lineas) => {
    const lotes = lineas.map((l) => String(l).trim()).find((l) => /^Lotes: \d+/.test(l));
    return lotes ? `Plano digitalizado: ${lotes.match(/^Lotes: (\d+)/)[1]} lotes` : 'Plano digitalizado';
  },
};

/** Cómo se nombra cada trabajo en la tarjeta: mientras corre y si falla. */
const NOMBRES = {
  construir: ['Construyendo', 'construir'],
  publicar: ['Publicando', 'publicar'],
  'digitalizar-plano': ['Digitalizando el plano', 'digitalizar el plano'],
};

const LOTES = 15;     // los que tiene el loteo dibujado en index.html
// Los mismos colores de estado que el sitio publicado, repartidos como un loteo real.
const ESTADOS = ['disponible', 'disponible', 'reservado', 'vendido', 'disponible',
  'vendido', 'disponible', 'reservado', 'disponible', 'disponible', 'vendido',
  'disponible', 'reservado', 'disponible', 'vendido'];

/**
 * En qué paso va un trabajo, según sus líneas. Puro, para poder probarlo.
 * `fraccion` va de 0 a 1; un trabajo terminado bien vale 1.
 */
export function avance(lineas, accion, terminado = false, fallo = false) {
  const pasos = PASOS[accion] ?? PASOS.construir;
  let indice = -1;
  for (const texto of lineas) {
    const limpio = String(texto).trim();
    const encontrado = pasos.findIndex(([, patron]) => patron.test(limpio));
    if (encontrado > indice) indice = encontrado;
  }
  const actual = Math.max(indice, 0);
  const listo = terminado && !fallo;
  return {
    paso: actual + 1,
    total: pasos.length,
    titulo: pasos[actual][0],
    fraccion: listo ? 1 : Math.min((actual + 0.5) / pasos.length, 0.97),
    resumen: listo ? resumenDe(lineas, accion) : null,
    causa: fallo ? causaDe(lineas) : null,
  };
}

/** "Listo. 88 parcelas (88 con geometría) en 3 vistas." → lo que se le dice a la persona. */
function resumenDe(lineas, accion) {
  if (accion === 'publicar') {
    const url = [...lineas].reverse().find((l) => /URL publicada/.test(l));
    return url ? `En línea: ${url.split(': ').pop().trim()}` : 'Publicado';
  }
  if (RESUMENES[accion]) return RESUMENES[accion](lineas);
  const listo = lineas.find((l) => /^Listo\. /.test(String(l).trim()));
  const medida = listo?.match(/(\d+) parcelas .* en (\d+) vistas?/);
  if (!medida) return 'Listo';
  const vistas = Number(medida[2]) === 1 ? '1 vista' : `${medida[2]} vistas`;
  return `Listo: ${medida[1]} parcelas en ${vistas}`;
}

/** La línea que explica por qué falló: la del error, no la del traceback. */
function causaDe(lineas) {
  const errores = lineas.map((l) => String(l).trim())
    .filter((l) => /^(\w+Error|Error|error):|no pude|no encontré|falta/i.test(l));
  const ultima = errores.at(-1);
  if (!ultima) return 'Algo falló. El detalle está en el registro.';
  return ultima.replace(/^\w+Error:\s*/, '');
}

/**
 * Pinta la tarjeta del vuelo. `trabajo` es {accion, estado} del último trabajo
 * del loteo; sin líneas no hay nada que mostrar.
 */
export function pintarVuelo(lineas, trabajo) {
  const tarjeta = $('#plano-vuelo');
  if (!lineas?.length || !trabajo) { tarjeta.hidden = true; return; }
  tarjeta.hidden = false;

  const corriendo = !trabajo.terminado;
  const fallo = trabajo.estado === 'falló';
  const progreso = avance(lineas, trabajo.accion, trabajo.terminado, fallo);
  tarjeta.dataset.estado = corriendo ? 'volando' : (fallo ? 'fallo' : 'listo');

  const [verbo, infinitivo] = NOMBRES[trabajo.accion] ?? NOMBRES.construir;
  $('#vuelo-titulo').textContent = corriendo ? progreso.titulo
    : (fallo ? `No se pudo terminar de ${infinitivo}` : progreso.resumen);
  $('#vuelo-paso').textContent = corriendo
    ? `${verbo} · paso ${progreso.paso} de ${progreso.total}`
    : (fallo ? progreso.causa : 'El detalle técnico está en el registro.');
  const barra = $('#vuelo-barra');
  barra.style.transform = `scaleX(${fallo ? 1 : progreso.fraccion})`;
  barra.parentElement.setAttribute('aria-valuenow', String(Math.round(progreso.fraccion * 100)));

  // Las parcelas del dibujo se pintan al ritmo del trabajo.
  const pintadas = Math.round(progreso.fraccion * LOTES);
  document.querySelectorAll('#plano-vuelo .vuelo__lote').forEach((lote, i) => {
    lote.dataset.estado = !fallo && i < pintadas ? ESTADOS[i % ESTADOS.length] : '';
  });
  // Si falló, el registro se abre solo: es lo primero que hay que leer.
  if (fallo && !tarjeta.dataset.abierto) {
    $('#vuelo-detalle').open = true;
    tarjeta.dataset.abierto = '1';
  }
  if (corriendo) delete tarjeta.dataset.abierto;
}
