/**
 * Un KMZ de Mis KMZ (`#/kmz/<slug>`): del plano aprobado al KMZ de la subdivisión.
 * Todo va contra `/api/kmz/<slug>/...`; el KMZ no es de ningún master. Al crearlo
 * se descarga o se usa en un master (ver `kmzs.js`).
 *
 * Siete pasos, como el spec: subir el PDF, marcar el dibujo, digitalizar, numerar,
 * ubicar en el mapa, revisar y crear el KMZ. Lo que marca la loteadora vive en
 * `entradas` (el mismo `entradas.json` del servidor, en píxeles de página) y se
 * guarda solo, un momento después de cada cambio. El servidor dice qué quedó
 * atrasado (`vigente`) y qué paso sigue (`paso`).
 */
import { $, $$, avisar, estado, json, pedir } from './comun.js';
import {
  dudosos, duplicados, empujar, girarEntradas, loteEn, nombreDelSistema, ordenarEsquinas, PASOS,
  pasoSugerido, pasosHabilitados, pasosHechos, ponerNumero, puedeSeguirANumerar, puntoDeRotulo, puntoEnPoligono,
  resumenRevision, siguienteNombre,
} from './kmz_geometria.js';
import { LienzoPlano } from './lienzo_plano.js';
import { abrirNombre, abrirUsarKmz, cuantosLotes, descargaDe } from './kmzs.js';
import { cargarLeaflet, COLORES, MapaKmz } from './mapa_kmz.js';
import { oyentes, seguir } from './plano.js';
import { soltadero } from './subida.js';
import { pintarEscaner } from './vuelo.js';

const VACIAS = () => ({
  pagina: 1, rotacion: 0, rectangulo: null, mascaras: [], esquinas: null, semillas: [], anclas: [],
  ajuste: { de: 0, dn: 0 },
});

let refrescar = async () => {};
let slug = null;
let plano = null;             // GET /api/kmz/<slug>: el estado del plano, con nombre y trabajo

/** Las rutas del KMZ en el servidor. */
const api = (de = slug) => `/api/kmz/${encodeURIComponent(de)}`;
/** La clave de sus trabajos, la misma del servidor: no choca con el slug de un master. */
const clave = (de = slug) => `kmz:${de}`;
let entradas = VACIAS();
let rasgos = [];              // lotes en px de página
let rasgosGeo = null;         // lotes en lon/lat, si está ubicado
let paso = 'subir';
let herramienta = 'mover';
let pendiente = null;         // ancla a medias: {nombre, x, y} en el plano, falta el mapa
let rehacer = null;           // el nombre del ancla que se está volviendo a marcar
let numerando = null;         // {x, y, anillos}: el lote al que se le escribe el número
let lienzo = null;
let mapa = null;
let version = 0;              // cambia al subir otro PDF: la imagen se pide de nuevo
let arrastrar = false;
let esquinasMarcando = [];    // las esquinas del marco mientras faltan: el servidor pide 4 o ninguna

// --- guardar ---------------------------------------------------------------------------

let sucio = false;
let temporizador = 0;
let enVuelo = null;
let ubicarLuego = 0;
let vaciado = Promise.resolve();  // el guardado pendiente al dejar un KMZ: se espera antes de releer

function cambiar(nuevas) {
  entradas = nuevas;
  sucio = true;
  clearTimeout(temporizador);
  temporizador = setTimeout(() => guardar().catch((e) => avisar(e.message)), 700);
  $('#kmz-guardado').textContent = 'Sin guardar…';
  lienzo?.redibujar();
  pintarPanel();
}

/** Guarda lo pendiente y trae el estado al día. Se espera antes de cada paso pesado. */
async function guardar() {
  clearTimeout(temporizador);
  if (enVuelo) await enVuelo.catch(() => {});
  if (!sucio || !slug) return;
  sucio = false;
  const mias = slug;
  $('#kmz-guardado').textContent = 'Guardando…';
  enVuelo = (async () => {
    try {
      const normalizadas = await pedir(`${api(mias)}/entradas`, json(entradas, 'PUT'));
      if (mias !== slug) return;
      if (!sucio) entradas = normalizadas;
      plano = await pedir(api(mias));
      $('#kmz-guardado').textContent = 'Guardado';
    } catch (error) {
      $('#kmz-guardado').textContent = 'No se guardó';
      throw error;
    }
  })();
  try { await enVuelo; } finally { enVuelo = null; }
  pintar();
}

// --- preparar --------------------------------------------------------------------------

export function prepararKmz(opciones) {
  refrescar = opciones.refrescar;
  const pantalla = $('#pantalla-kmz');
  pantalla.addEventListener('click', (evento) => {
    const nodo = evento.target.closest('[data-accion], [data-paso], [data-pagina], [data-herramienta],'
      + ' [data-quitar-mascara], [data-quitar-semilla], [data-ancla-quitar], [data-ancla-rehacer], [data-centrar]');
    if (!nodo || nodo.disabled) return;
    manejar(nodo).catch((error) => avisar(error.message));
  });

  $('#kmz-pdf').addEventListener('change', (e) => {
    const [archivo] = e.target.files;
    e.target.value = '';
    if (archivo) subirPdf(archivo).catch((error) => avisar(error.message));
  });
  soltadero($('#kmz-soltadero'), (encontrados) => {
    const pdf = encontrados.find(({ archivo }) => /\.pdf$/i.test(archivo.name));
    if (!pdf) return avisar('Eso no es un PDF: el plano va en PDF.');
    subirPdf(pdf.archivo).catch((error) => avisar(error.message));
  });

  $('#kmz-es-foto').addEventListener('change', (e) => {
    if (!e.target.checked && entradas.esquinas) cambiar({ ...entradas, esquinas: null, marco_mm: null });
    if (!e.target.checked && herramienta === 'esquinas') elegirHerramienta('mover');
    pintarPanel();
  });
  $('#kmz-lector').addEventListener('change', (e) => cambiar({ ...entradas, lector: e.target.checked }));
  for (const campo of ['#kmz-marco-ancho', '#kmz-marco-alto']) {
    $(campo).addEventListener('change', () => {
      const ancho = Number($('#kmz-marco-ancho').value);
      const alto = Number($('#kmz-marco-alto').value);
      cambiar({ ...entradas, marco_mm: ancho > 0 && alto > 0 ? [ancho, alto] : null });
    });
  }

  $('#kmz-numero').addEventListener('submit', (e) => {
    e.preventDefault();
    escribirNumero($('#kmz-numero-valor').value);
  });
  $('#kmz-numero-valor').addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.stopPropagation(); cerrarNumero(); }
  });
  $('#kmz-ir-a').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); irA().catch((error) => avisar(error.message)); }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || pantalla.hidden || document.querySelector('dialog[open]')) return;
    if (pendiente) { cancelarAncla(); e.preventDefault(); }
    else if (numerando) { cerrarNumero(); e.preventDefault(); }
  });

  lienzo = new LienzoPlano($('#kmz-plano'), $('#kmz-lienzo'));
  lienzo.alDibujar = dibujar;
  lienzo.alTocar = tocarPlano;
  lienzo.alRectangulo = rectangulo;
}

/** Llega a la pantalla (`nuevo`) o se repinta tras un refresco de la lista. */
export function pintarKmz(nuevoSlug, { nuevo = false } = {}) {
  pintarCabecera(nuevoSlug);
  if (!nuevo && nuevoSlug === slug) return;
  if (sucio && slug) {
    // Lo marcado hace un instante (aún en la espera del guardado) no se pierde al volver
    // a entrar ni al pasar a otro KMZ: se guarda en el suyo antes de limpiar.
    clearTimeout(temporizador);
    vaciado = pedir(`${api(slug)}/entradas`, json(entradas, 'PUT'))
      .catch((error) => avisar(error.message));
  }
  slug = nuevoSlug;
  plano = null;
  entradas = VACIAS();
  rasgos = [];
  rasgosGeo = null;
  pendiente = null;
  rehacer = null;
  sucio = false;
  esquinasMarcando = [];
  cerrarNumero();
  $('#kmz-guardado').textContent = '';
  $('#kmz-registro').replaceChildren();
  $('#kmz-escaner').hidden = true;
  $('#kmz-listo').hidden = true;
  $('#kmz-listo-texto').textContent = '';
  cargarTodo(true).catch((error) => {
    // Borrado en otra pestaña, o de otra loteadora: el servidor dice 404.
    if (nuevoSlug === slug && !plano) $('#kmz-titulo').textContent = 'Este KMZ no existe';
    avisar(error.message);
  });
}

/** El nombre del KMZ: el del servidor si ya llegó, si no el de la lista. */
function pintarCabecera(de = slug) {
  const nombre = (de === slug ? plano?.nombre : null)
    ?? estado.kmzs.find((k) => k.slug === de)?.nombre;
  $('#kmz-titulo').textContent = nombre ?? 'Cargando…';
  document.title = `${nombre ?? 'KMZ'} — Mis KMZ — Tu Masterplan`;
}

async function cargarTodo(alLlegar = false) {
  const mio = slug;
  await vaciado;
  const nuevo = await pedir(api(mio));
  if (mio !== slug) return;
  plano = nuevo;
  pintarCabecera();
  if (!sucio) entradas = { ...VACIAS(), ...(plano.entradas ?? {}) };
  $('#kmz-es-foto').checked = Boolean(entradas.esquinas || entradas.marco_mm);
  await cargarLotes();
  if (alLlegar) {
    paso = pasoSugerido(plano);
    if (plano.trabajo && !plano.trabajo.terminado) {
      paso = 'digitalizar';
      escuchar();
      if (!estado.sondeos.has(clave())) seguir(clave(), plano.trabajo.id);
    }
  }
  mostrarPagina().catch((error) => avisar(error.message));
  await pintarPaso();
}

async function cargarLotes() {
  const mio = slug;
  rasgos = [];
  rasgosGeo = null;
  if (plano?.digitalizado) {
    const px = await pedir(`${api(mio)}/lotes?en=px`);
    rasgos = px.features;
    for (const r of rasgos) r.rotulo = puntoDeRotulo(r);
  }
  if (plano?.georreferencia) {
    rasgosGeo = await pedir(`${api(mio)}/lotes?en=lonlat`);
  }
  lienzo?.redibujar();
}

/** La página elegida, en el lienzo. */
async function mostrarPagina() {
  const hoja = paginaActual();
  if (!hoja) return;
  await lienzo.cargar(`${api()}/paginas/${hoja.n}?v=${version}`,
    hoja.ancho, hoja.alto, entradas.rotacion ?? 0);
}

const paginaActual = () => plano?.paginas?.find((p) => p.n === entradas.pagina) ?? plano?.paginas?.[0];

// --- acciones -----------------------------------------------------------------------

async function manejar(nodo) {
  avisar(null);
  const { dataset } = nodo;
  if (dataset.paso) return irAlPaso(dataset.paso);
  if (dataset.pagina) return elegirPagina(Number(dataset.pagina));
  if (dataset.herramienta) return elegirHerramienta(dataset.herramienta);
  if (dataset.quitarMascara) {
    return cambiar({ ...entradas, mascaras: entradas.mascaras.filter((_, i) => i !== Number(dataset.quitarMascara)) });
  }
  if (dataset.quitarSemilla) {
    return cambiar({ ...entradas, semillas: entradas.semillas.filter((s) => s.numero !== dataset.quitarSemilla) });
  }
  if (dataset.anclaQuitar) return quitarAncla(dataset.anclaQuitar, false);
  if (dataset.anclaRehacer) return quitarAncla(dataset.anclaRehacer, true);
  if (dataset.centrar) {
    const [x, y] = dataset.centrar.split(',').map(Number);
    return lienzo.centrar(x, y, Math.max(lienzo.vista.escala, 0.6));
  }

  const accion = dataset.accion;
  if (accion === 'kmz-siguiente') return irAlPaso(PASOS[PASOS.indexOf(paso) + 1]);
  if (accion === 'kmz-girar-izq') return girar(-90);
  if (accion === 'kmz-girar-der') return girar(90);
  if (accion === 'kmz-acercar') return lienzo.acercar(1.5);
  if (accion === 'kmz-alejar') return lienzo.acercar(1 / 1.5);
  if (accion === 'kmz-ajustar') return lienzo.ajustar();
  if (accion === 'kmz-quitar-dibujo') return cambiar({ ...entradas, rectangulo: null });
  if (accion === 'kmz-borrar-esquinas') {
    esquinasMarcando = [];
    return cambiar({ ...entradas, esquinas: null });
  }
  if (accion === 'kmz-digitalizar' || accion === 'kmz-redigitalizar') return digitalizar();
  if (accion === 'kmz-siguiente-sin-numero') return siguienteSinNumero();
  if (accion === 'kmz-ir') return irA();
  if (accion === 'kmz-cancelar-ancla') return cancelarAncla();
  if (accion === 'kmz-usar-cuadricula') return usarCuadricula(true);
  if (accion === 'kmz-quitar-cuadricula') return usarCuadricula(false);
  if (accion === 'kmz-norte') return moverAjuste(0, 1);
  if (accion === 'kmz-sur') return moverAjuste(0, -1);
  if (accion === 'kmz-este') return moverAjuste(1, 0);
  if (accion === 'kmz-oeste') return moverAjuste(-1, 0);
  if (accion === 'kmz-ajuste-cero') return moverAjuste(null, null);
  if (accion === 'kmz-arrastrar') {
    arrastrar = !arrastrar;
    if (mapa) mapa.arrastrable = arrastrar;
    return pintarPanel();
  }
  if (accion === 'kmz-georreferenciar') return ubicar();
  if (accion === 'kmz-crear') return crearKmz();
  if (accion === 'kmz-renombrar') return renombrar();
  if (accion === 'kmz-usar') return usar();
  return undefined;
}

async function irAlPaso(destino) {
  if (!destino || !pasosHabilitados(plano)[destino]) return;
  if (paso === 'ubicar' && destino !== 'ubicar') pendiente = null;
  cerrarNumero();
  paso = destino;
  await guardar();
  await pintarPaso();
  $(`#kmz-panel-${paso} h2`)?.focus();
}

// --- 1. subir -------------------------------------------------------------------------

function subirPdf(archivo) {
  if (plano?.pdf && (plano.entradas || plano.digitalizado)
    && !confirm('Subir otro PDF borra lo marcado y lo digitalizado del plano actual. ¿Seguir?')) {
    return Promise.resolve();
  }
  const cuerpo = new FormData();
  cuerpo.append('archivo', archivo, archivo.name);
  const caja = $('#kmz-subiendo');
  caja.hidden = false;
  $('#kmz-subiendo-texto').textContent = `Subiendo ${archivo.name}…`;
  const mio = slug;
  return new Promise((listo, fallo) => {
    const peticion = new XMLHttpRequest();
    peticion.open('POST', `${api(mio)}/plano`);
    peticion.upload.addEventListener('progress', (e) => {
      if (!e.lengthComputable) return;
      $('#kmz-subiendo i').style.width = `${Math.round((e.loaded / e.total) * 100)}%`;
      if (e.loaded === e.total) $('#kmz-subiendo-texto').textContent = 'Sacando las páginas del PDF…';
    });
    peticion.addEventListener('load', async () => {
      let cuerpoRespuesta = {};
      try { cuerpoRespuesta = JSON.parse(peticion.responseText); } catch { /* sin cuerpo */ }
      caja.hidden = true;
      if (peticion.status >= 400) {
        fallo(new Error(cuerpoRespuesta.detail ?? `Error ${peticion.status}`));
        return;
      }
      version += 1;
      sucio = false;
      entradas = VACIAS();
      try {
        await cargarTodo();
        await refrescar();
        listo();
      } catch (error) { fallo(error); }
    });
    peticion.addEventListener('error', () => {
      caja.hidden = true;
      fallo(new Error('Se cortó la subida. Revisa la conexión y vuelve a intentarlo.'));
    });
    peticion.send(cuerpo);
  });
}

const hayMarcas = () => Boolean(entradas.rectangulo || entradas.mascaras.length || entradas.esquinas
  || entradas.semillas.length || entradas.anclas.length);

async function elegirPagina(n) {
  if (n === entradas.pagina && plano.entradas) return;
  if (n !== entradas.pagina && hayMarcas()
    && !confirm('Lo marcado es de otra página. Cambiar de página lo borra. ¿Seguir?')) return;
  const limpio = n !== entradas.pagina;
  cambiar({ ...(limpio ? VACIAS() : entradas), pagina: n, rotacion: limpio ? 0 : entradas.rotacion });
  await mostrarPagina();
  pintarPaso();
}

async function girar(grados) {
  const hoja = paginaActual();
  if (!hoja) return;
  const de = entradas.rotacion ?? 0;
  const a = (((de + grados) % 360) + 360) % 360;
  cambiar(girarEntradas(entradas, de, a, hoja.ancho, hoja.alto));
  await mostrarPagina();
}

// --- 2. marcar -------------------------------------------------------------------------

function elegirHerramienta(nombre) {
  herramienta = nombre;
  lienzo.herramienta = ['dibujo', 'mascara'].includes(nombre) ? 'rectangulo' : 'mover';
  for (const boton of $$('[data-herramienta]')) {
    boton.setAttribute('aria-pressed', String(boton.dataset.herramienta === nombre));
  }
  $('#kmz-plano').dataset.herramienta = nombre;
  pintarPanel();
}

function rectangulo(rect) {
  if (paso !== 'marcar') return;
  if (rect[2] - rect[0] < 3 || rect[3] - rect[1] < 3) return;
  if (herramienta === 'dibujo') cambiar({ ...entradas, rectangulo: rect });
  if (herramienta === 'mascara') cambiar({ ...entradas, mascaras: [...entradas.mascaras, rect] });
}

function tocarPlano(x, y) {
  if (paso === 'marcar' && herramienta === 'esquinas') {
    esquinasMarcando = [...esquinasMarcando, [round(x), round(y)]];
    if (esquinasMarcando.length < 4) {
      lienzo.redibujar();
      pintarPanel();
      return undefined;
    }
    const esquinas = ordenarEsquinas(esquinasMarcando);
    esquinasMarcando = [];
    return cambiar({ ...entradas, esquinas });
  }
  if ((paso === 'marcar' && herramienta === 'numero') || paso === 'numerar') return abrirNumero(x, y);
  if (paso === 'ubicar') return marcarEnPlano(x, y);
  return undefined;
}

const round = (v) => Math.round(v * 10) / 10;

// --- 3. digitalizar ----------------------------------------------------------------------

function escuchar() {
  const mio = slug;
  oyentes.set(clave(mio), (trabajo) => {
    if (mio !== slug) return;
    pintarRegistro();
    if (trabajo.terminado) terminoDigitalizar(trabajo).catch((error) => avisar(error.message));
  });
}

async function digitalizar() {
  if (!entradas.rectangulo
    && !confirm('No encerraste el dibujo: se va a digitalizar la página entera, con cuadros y cajetín. ¿Seguir?')) return;
  await guardar();
  estado.registros.set(clave(), []);
  // La tarjeta aparece al tiro, en "Abriendo el plano", sin esperar la primera línea.
  estado.trabajos.set(clave(), { accion: 'digitalizar-plano', estado: 'corriendo', terminado: false });
  pintarRegistro();
  escuchar();
  let id;
  try {
    ({ id } = await pedir(`${api()}/digitalizar`, json({})));
  } catch (error) {
    // No se lanzó (otro trabajo corriendo, p. ej.): la tarjeta no puede quedar escaneando.
    estado.trabajos.delete(clave());
    pintarRegistro();
    throw error;
  }
  paso = 'digitalizar';
  plano = { ...plano, trabajo: { id, terminado: false } };
  pintarPaso();
  seguir(clave(), id);
  refrescar().catch(() => {});
}

async function terminoDigitalizar(trabajo) {
  await cargarTodo();
  if (trabajo.estado === 'listo') {
    await irAlPaso(plano.digitalizado?.sin_numero || plano.digitalizado?.faltantes?.length ? 'numerar' : 'ubicar');
  } else {
    pintarPaso();
  }
}

/**
 * La tarjeta del escáner y, plegado adentro, el registro técnico. Las líneas son las
 * que se van sondeando; si no hay (se volvió a abrir el KMZ), las que trae el último
 * trabajo del servidor.
 */
function pintarRegistro() {
  const caja = $('#kmz-registro');
  const sondeadas = estado.registros.get(clave()) ?? [];
  const lineas = sondeadas.length ? sondeadas : plano?.trabajo?.lineas ?? [];
  const trabajo = estado.trabajos.get(clave()) ?? plano?.trabajo ?? null;
  // Un trabajo que terminó bien pero cuyo resultado ya no está (se subió otro PDF)
  // no tiene nada que contar.
  const vigente = trabajo && !(trabajo.terminado && trabajo.estado === 'listo' && !plano?.digitalizado);
  pintarEscaner(lineas, vigente ? trabajo : null);
  caja.replaceChildren(...lineas.map((texto) => {
    const span = document.createElement('span');
    const bajo = texto.toLowerCase();
    if (bajo.includes('aviso')) span.className = 'aviso-linea';
    else if (bajo.includes('error') || bajo.includes('traceback')) span.className = 'error-linea';
    span.textContent = `${texto}\n`;
    return span;
  }));
  caja.scrollTop = caja.scrollHeight;
}

// --- 4. numerar ---------------------------------------------------------------------------

function abrirNumero(x, y) {
  const lote = loteEn(rasgos, x, y);
  // El número se pone donde el lector leyó el rótulo (así lo corrige) o donde
  // se hizo clic, que está dentro del lote.
  const punto = lote?.properties.semilla ?? [x, y];
  numerando = { x: punto[0], y: punto[1], anillos: lote?.geometry.coordinates ?? null };
  const forma = $('#kmz-numero');
  const [sx, sy] = lienzo.aPantalla(x, y);
  const caja = $('#kmz-plano');
  forma.style.left = `${Math.min(Math.max(sx, 8), caja.clientWidth - 200)}px`;
  forma.style.top = `${Math.min(Math.max(sy + 12, 8), caja.clientHeight - 56)}px`;
  forma.hidden = false;
  const actual = lote?.properties.numero ?? '';
  $('#kmz-numero-valor').value = actual;
  $('#kmz-numero-rotulo').textContent = lote
    ? (actual ? `Lote ${actual}${lote.properties.origen === 'lector' ? ' (leído)' : ''}: corrige el número` : 'Número de este lote')
    : 'Número del lote que está aquí';
  $('#kmz-numero-valor').focus();
  $('#kmz-numero-valor').select();
  lienzo.redibujar();
}

function cerrarNumero() {
  numerando = null;
  const forma = $('#kmz-numero');
  if (forma) forma.hidden = true;
  lienzo?.redibujar();
}

function escribirNumero(valor) {
  if (!numerando) return;
  const limpio = valor.trim().replace(/^lote\s*/i, '');
  const otra = entradas.semillas.find((s) => s.numero === limpio
    && !(numerando.anillos && puntoEnPoligono(s.x, s.y, numerando.anillos)));
  if (limpio && otra && !confirm(`El ${limpio} ya está marcado en otro lote. ¿Lo pasas a este?`)) return;
  cambiar({ ...entradas, semillas: ponerNumero(entradas.semillas, limpio, [numerando.x, numerando.y], numerando.anillos) });
  cerrarNumero();
  lienzo.canvas.focus({ preventScroll: true });
}

function siguienteSinNumero() {
  const lista = rasgos.filter((r) => r.properties.banderas.includes('sin_numero'));
  if (!lista.length) return;
  siguienteSinNumero.i = ((siguienteSinNumero.i ?? -1) + 1) % lista.length;
  const [x, y] = lista[siguienteSinNumero.i].rotulo;
  lienzo.centrar(x, y, Math.max(lienzo.vista.escala, 0.6));
}

// --- 5. ubicar -----------------------------------------------------------------------------

function marcarEnPlano(x, y) {
  const nombre = pendiente?.nombre ?? rehacer ?? siguienteNombre(entradas.anclas.map((a) => a.nombre));
  pendiente = { nombre, x: round(x), y: round(y) };
  lienzo.redibujar();
  pintarPanel();
}

function marcarEnMapa(lat, lon) {
  if (paso !== 'ubicar') return;
  if (!pendiente) {
    $('#kmz-ancla-estado').textContent = 'Primero haz clic en el punto del plano; después, en el mismo punto del mapa.';
    return;
  }
  const ancla = { ...pendiente, lon: Number(lon.toFixed(7)), lat: Number(lat.toFixed(7)) };
  pendiente = null;
  rehacer = null;
  cambiar({ ...entradas, anclas: [...entradas.anclas.filter((a) => a.nombre !== ancla.nombre), ancla] });
  pintarMapa();
  if (entradas.anclas.length >= 2 || entradas.cuadricula) ubicar().catch((e) => avisar(e.message));
}

function cancelarAncla() {
  pendiente = null;
  rehacer = null;
  lienzo.redibujar();
  pintarPanel();
}

function quitarAncla(nombre, otraVez) {
  pendiente = null;
  rehacer = otraVez ? nombre : null;
  cambiar({ ...entradas, anclas: entradas.anclas.filter((a) => a.nombre !== nombre) });
  pintarMapa();
  if (!otraVez && (entradas.anclas.length >= 2 || entradas.cuadricula)) ubicar().catch((e) => avisar(e.message));
}

function usarCuadricula(si) {
  const propuesta = plano?.digitalizado?.lector?.cuadricula;
  if (si && !propuesta) return;
  const nuevas = { ...entradas };
  if (si) nuevas.cuadricula = propuesta; else delete nuevas.cuadricula;
  cambiar(nuevas);
}

function moverAjuste(de, dn) {
  const paso1 = Number($('#kmz-paso-ajuste').value) || 1;
  const ajuste = de === null ? { de: 0, dn: 0 } : empujar(entradas.ajuste, de * paso1, dn * paso1);
  cambiar({ ...entradas, ajuste });
  // Varias flechas seguidas son un solo cálculo.
  clearTimeout(ubicarLuego);
  ubicarLuego = setTimeout(() => ubicar().catch((e) => avisar(e.message)), 500);
}

function arrastreDelMapa(de, dn) {
  cambiar({ ...entradas, ajuste: empujar(entradas.ajuste, de, dn) });
  // Si no se pudo recalcular, los lotes no se quedan corridos con el arrastre a medias.
  ubicar().catch((e) => avisar(e.message)).finally(() => pintarMapa());
}

async function ubicar() {
  clearTimeout(ubicarLuego);
  await guardar();
  if (!plano?.digitalizado?.vigente) return;
  if (entradas.anclas.length < 2 && !entradas.cuadricula) return;
  $('#kmz-ancla-estado').textContent = 'Ubicando…';
  try {
    plano.georreferencia = await pedir(`${api()}/georreferenciar`, json({}));
  } catch (error) {
    $('#kmz-ancla-estado').textContent = '';
    throw error;
  }
  plano = await pedir(api());
  rasgosGeo = await pedir(`${api()}/lotes?en=lonlat`);
  pintar();
  pintarMapa();
}

async function irA() {
  const texto = $('#kmz-ir-a').value;
  const numeros = (texto.match(/-?\d+(?:[.,]\d+)?/g) ?? []).map((n) => Number(n.replace(',', '.')));
  if (numeros.length !== 2) throw new Error('Escribe la latitud y la longitud, por ejemplo -34.98, -71.24');
  let [lat, lon] = numeros;
  // Google Maps copia "lat, lon"; si vienen al revés (lon primero) se nota en Chile.
  if (Math.abs(lat) > 60 && Math.abs(lon) <= 60) [lat, lon] = [lon, lat];
  await prepararMapa();
  mapa.ir(lat, lon, 16);
}

// --- 7. crear ----------------------------------------------------------------------------

async function crearKmz() {
  await guardar();
  const mio = slug;
  const creado = await pedir(`${api(mio)}/crear`, json({}));
  if (mio !== slug) return;
  plano = await pedir(api(mio));
  const lotes = cuantosLotes(creado.lotes);
  $('#kmz-listo-texto').textContent = `Listo: el KMZ "${plano.nombre}" quedó creado${lotes ? ` con ${lotes}` : ''}.`;
  await refrescar();
  pintar();
}

const terminado = () => Boolean(plano?.kmz?.length);

/** Cambiar el nombre: el mismo diálogo de Nuevo KMZ. */
function renombrar() {
  if (!plano) return;
  abrirNombre({ slug, nombre: plano.nombre }, (listo) => {
    if (plano && listo.slug === slug) plano = { ...plano, nombre: listo.nombre };
    // El texto de "listo" lleva el nombre: se rehace con el nuevo.
    $('#kmz-listo-texto').textContent = '';
    pintarCabecera();
    pintarCrear();
  });
}

/** Usar en un master: uno existente o uno nuevo con este KMZ. */
function usar() {
  if (!terminado()) return;
  abrirUsarKmz({ slug, nombre: plano.nombre });
}

// --- pintar --------------------------------------------------------------------------------

function pintar() {
  pintarPasos();
  pintarPanel();
  lienzo?.redibujar();
}

async function pintarPaso() {
  for (const panel of $$('.kmz-panel')) panel.hidden = panel.dataset.panel !== paso;
  const conPlano = ['subir', 'marcar', 'digitalizar', 'numerar', 'ubicar'].includes(paso) && Boolean(plano?.pdf);
  const conMapa = ['ubicar', 'revisar'].includes(paso);
  $('#kmz-escena').hidden = !conPlano && !conMapa;
  $('#kmz-plano').hidden = !conPlano;
  $('#kmz-mapa-caja').hidden = !conMapa;
  $('#kmz-escena').classList.toggle('kmz-escena--doble', conPlano && conMapa);
  $('#kmz-plano').dataset.modo = paso;
  $('#kmz-cuerpo').classList.toggle('kmz-cuerpo--solo', paso === 'subir' && !plano?.pdf || paso === 'crear');
  if (paso !== 'marcar') elegirHerramienta('mover');
  pintar();
  if (conMapa) {
    await prepararMapa();
    pintarMapa(true);
  }
}

function pintarPasos() {
  const habilitados = pasosHabilitados(plano);
  const hechos = pasosHechos(plano);
  for (const boton of $$('#kmz-pasos [data-paso]')) {
    const nombre = boton.dataset.paso;
    boton.disabled = !habilitados[nombre];
    boton.classList.toggle('paso--hecho', Boolean(hechos[nombre]));
    if (nombre === paso) boton.setAttribute('aria-current', 'step'); else boton.removeAttribute('aria-current');
  }
}

/** El texto y los controles del paso abierto. */
function pintarPanel() {
  if (!plano) return;
  const d = plano.digitalizado;
  const atrasado = Boolean(d && !d.vigente) && ['digitalizar', 'numerar', 'ubicar'].includes(paso);
  $('#kmz-atrasado').hidden = !atrasado || Boolean(plano.trabajo && !plano.trabajo.terminado);
  if (paso === 'subir') pintarSubir();
  if (paso === 'marcar') pintarMarcar();
  if (paso === 'digitalizar') pintarDigitalizar();
  if (paso === 'numerar') pintarNumerar();
  if (paso === 'ubicar') pintarUbicar();
  if (paso === 'revisar') pintarRevisar();
  if (paso === 'crear') pintarCrear();
}

function pintarSubir() {
  const hay = Boolean(plano.pdf);
  $('#kmz-soltadero-texto').textContent = hay
    ? 'Subir otro PDF (reemplaza el actual)' : 'Arrastra el PDF del plano aquí o haz clic para elegirlo';
  $('#kmz-hojas-caja').hidden = !hay;
  if (!hay) return;
  const lista = $('#kmz-hojas');
  lista.replaceChildren(...plano.paginas.map((hoja) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'hoja';
    boton.dataset.pagina = hoja.n;
    boton.setAttribute('aria-pressed', String(hoja.n === entradas.pagina));
    const imagen = document.createElement('img');
    imagen.src = `${api()}/paginas/${hoja.n}?mini=1&v=${version}`;
    imagen.alt = '';
    imagen.loading = 'lazy';
    const texto = document.createElement('span');
    texto.textContent = `Página ${hoja.n} · ${hoja.ancho}×${hoja.alto} px`;
    boton.append(imagen, texto);
    return boton;
  }));
  $('#kmz-rotacion').textContent = `${entradas.rotacion ?? 0}°`;
}

function pintarMarcar() {
  const foto = $('#kmz-es-foto').checked;
  $('[data-herramienta="esquinas"]').hidden = !foto;
  $('#kmz-foto').hidden = !foto;
  const [ancho, alto] = entradas.marco_mm ?? ['', ''];
  if (document.activeElement !== $('#kmz-marco-ancho')) $('#kmz-marco-ancho').value = ancho;
  if (document.activeElement !== $('#kmz-marco-alto')) $('#kmz-marco-alto').value = alto;
  $('#kmz-esquinas-nota').textContent = entradas.esquinas && !esquinasMarcando.length
    ? 'Las 4 esquinas están marcadas.'
    : `Con la herramienta "Esquinas del marco", haz clic en las 4 esquinas del marco impreso (${esquinasMarcando.length} de 4).`;
  $('[data-accion="kmz-borrar-esquinas"]').hidden = !entradas.esquinas && !esquinasMarcando.length;
  $('[data-accion="kmz-quitar-dibujo"]').hidden = !entradas.rectangulo;
  $('#kmz-lector-caja').hidden = !plano.lector;
  $('#kmz-lector').checked = entradas.lector !== false;
  const sinLector = !plano.lector || entradas.lector === false;
  $('#kmz-sin-lector').hidden = !sinLector;

  const lista = $('#kmz-marcas');
  const filas = [];
  filas.push(fila(entradas.rectangulo ? 'Dibujo encerrado' : 'Falta encerrar el dibujo', null,
    entradas.rectangulo ? 'ok' : 'falta'));
  entradas.mascaras.forEach((_, i) => filas.push(fila(`Tapado ${i + 1}`, { quitarMascara: String(i) })));
  for (const s of entradas.semillas) filas.push(fila(`Lote ${s.numero}`, { quitarSemilla: s.numero }));
  lista.replaceChildren(...filas);
  const listo = Boolean(entradas.rectangulo) && (!sinLector || entradas.semillas.length > 0);
  $('#kmz-panel-marcar [data-accion="kmz-siguiente"]').disabled = !pasosHabilitados(plano).digitalizar;
  $('#kmz-marcar-nota').textContent = listo ? '' : !entradas.rectangulo
    ? 'Encierra el dibujo del loteo con la herramienta "Encerrar el dibujo".'
    : 'Marca el número de al menos un lote antes de digitalizar.';
}

function fila(texto, quitar, tono) {
  const li = document.createElement('li');
  if (tono) li.className = `kmz-lista__${tono}`;
  const span = document.createElement('span');
  span.textContent = texto;
  li.append(span);
  if (quitar) {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'boton boton--texto boton--chico';
    boton.textContent = 'Quitar';
    boton.setAttribute('aria-label', `Quitar ${texto.toLowerCase()}`);
    Object.assign(boton.dataset, quitar);
    li.append(boton);
  }
  return li;
}

function pintarDigitalizar() {
  const trabajando = Boolean(plano.trabajo && !plano.trabajo.terminado);
  const d = plano.digitalizado;
  const boton = $('[data-accion="kmz-digitalizar"]');
  boton.disabled = trabajando || !pasosHabilitados(plano).digitalizar;
  boton.textContent = trabajando ? 'Digitalizando…' : d ? 'Digitalizar de nuevo' : 'Digitalizar';
  pintarRegistro();
  // Antes del `return` de abajo: sin digitalizar también hay que apagarlo.
  $('#kmz-panel-digitalizar [data-accion="kmz-siguiente"]').disabled = !puedeSeguirANumerar(plano);
  const cifras = $('#kmz-cifras');
  cifras.hidden = !d;
  if (!d) return;
  const lector = d.lector;
  const lineas = [
    ['Lotes', d.lotes],
    ['Sin número', d.sin_numero],
    ['Números sin lote', d.faltantes.length ? d.faltantes.join(', ') : '—'],
    ['Lector', !lector ? 'apagado' : lector.disponible === false ? 'no disponible'
      : `${lector.rotulos} leídos · ${lector.semillas} usados`],
    ['Tomó', d.segundos ? `${Math.round(d.segundos)} s` : '—'],
  ];
  cifras.replaceChildren(...lineas.map(([rotulo, valor]) => {
    const div = document.createElement('div');
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    dt.textContent = rotulo;
    dd.textContent = valor;
    div.append(dt, dd);
    return div;
  }));
}

function pintarNumerar() {
  const d = plano.digitalizado;
  const sinNumero = rasgos.filter((r) => r.properties.banderas.includes('sin_numero'));
  const repetidos = duplicados(rasgos);
  const dudas = dudosos(rasgos);
  $('#kmz-sin-numero').textContent = sinNumero.length
    ? `${sinNumero.length} ${sinNumero.length === 1 ? 'parte sin número' : 'partes sin número'} (en rojo, con "?"). `
      + 'Si es un lote, haz clic y escribe su número. Los caminos y áreas comunes se dejan así: no van al KMZ.'
    : 'Todos los lotes tienen número.';
  $('[data-accion="kmz-siguiente-sin-numero"]').hidden = !sinNumero.length;
  const faltan = [...(d?.faltantes ?? []), ...(d?.lector?.sin_poligono ?? [])];
  $('#kmz-faltantes').hidden = !faltan.length;
  $('#kmz-faltantes').textContent = faltan.length
    ? `Números marcados que no cayeron en ningún lote: ${faltan.join(', ')}. Revisa que estén dentro de su lote.` : '';

  const botones = (lista, texto) => lista.map((r) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'pastilla pastilla--boton';
    boton.dataset.centrar = r.rotulo.map((v) => v.toFixed(1)).join(',');
    boton.textContent = texto(r.properties);
    return boton;
  });
  const repetidosRasgos = rasgos.filter((r) => repetidos.includes(r.properties.numero));
  $('#kmz-duplicados-caja').hidden = !repetidosRasgos.length;
  $('#kmz-duplicados').replaceChildren(...botones(repetidosRasgos, (p) => `Lote ${p.numero}`));
  $('#kmz-dudosos-caja').hidden = !dudas.length;
  $('#kmz-dudosos').replaceChildren(...botones(dudas,
    (p) => `${p.numero} · ${p.apoyo ?? 0} lect.${p.confianza != null ? ` · ${Math.round(p.confianza * 100)} %` : ''}`));
  $('#kmz-panel-numerar [data-accion="kmz-siguiente"]').disabled = !d?.vigente;
}

function pintarUbicar() {
  const g = plano.georreferencia;
  const vigente = Boolean(g?.vigente);
  const estadoAncla = $('#kmz-ancla-estado');
  if (pendiente) {
    estadoAncla.textContent = `Punto ${pendiente.nombre} marcado en el plano. Ahora haz clic en el mismo punto del mapa (Esc cancela).`;
  } else if (rehacer) {
    estadoAncla.textContent = `Marca de nuevo el punto ${rehacer}: primero en el plano.`;
  } else {
    const n = entradas.anclas.length;
    estadoAncla.textContent = n >= 4 ? `${n} puntos marcados.`
      : `${n} de 4 puntos. Haz clic en un punto del plano (acerca bien) y después en el mismo punto del mapa.`;
  }
  $('[data-accion="kmz-cancelar-ancla"]').hidden = !pendiente && !rehacer;

  const propuesta = plano.digitalizado?.lector?.cuadricula;
  $('#kmz-cuadricula').hidden = !propuesta && !entradas.cuadricula;
  $('[data-accion="kmz-usar-cuadricula"]').hidden = Boolean(entradas.cuadricula) || !propuesta;
  $('[data-accion="kmz-quitar-cuadricula"]').hidden = !entradas.cuadricula;
  $('#kmz-cuadricula-texto').textContent = entradas.cuadricula
    ? 'Se está usando la cuadrícula UTM impresa en el plano. Las anclas sirven para confirmar el datum.'
    : 'El plano trae una cuadrícula UTM impresa: es lo más preciso para ubicarlo.';

  // Anclas con su residuo.
  const porNombre = new Map((g?.anclas ?? []).map((a) => [a.nombre, a]));
  const cuerpo = $('#kmz-anclas tbody');
  cuerpo.replaceChildren(...entradas.anclas.map((a) => {
    const r = porNombre.get(a.nombre);
    const tr = document.createElement('tr');
    const atipica = g?.atipicas?.includes(a.nombre);
    if (atipica) tr.className = 'kmz-atipica';
    const celda = (texto) => { const td = document.createElement('td'); td.textContent = texto; return td; };
    const residuo = r && vigente ? `${r.residuo_m.toFixed(1)} m` : '—';
    tr.append(celda(a.nombre), celda(residuo), celda(atipica ? 'Atípica' : r && vigente ? 'ok' : ''));
    const acciones = document.createElement('td');
    for (const [texto, clave] of [['Rehacer', 'anclaRehacer'], ['Quitar', 'anclaQuitar']]) {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'boton boton--texto boton--chico';
      b.textContent = texto;
      b.dataset[clave] = a.nombre;
      b.setAttribute('aria-label', `${texto} el punto ${a.nombre}`);
      acciones.append(b);
    }
    tr.append(acciones);
    return tr;
  }));
  $('#kmz-anclas').hidden = !entradas.anclas.length;

  const resumen = $('#kmz-ubicacion');
  resumen.hidden = !g;
  if (g) {
    const p = g.parametros ?? {};
    const partes = [g.metodo === 'cuadricula' ? 'Con la cuadrícula impresa' : `Con ${p.n_anclas ?? entradas.anclas.length} anclas`,
      nombreDelSistema(g.epsg)];
    if (p.rms_m != null) partes.push(`error medio ${p.rms_m.toFixed(1)} m`);
    if (g.datum?.datum) partes.push(`datum ${g.datum.datum}`);
    $('#kmz-ubicacion-texto').textContent = (vigente ? '' : 'Desactualizado: ') + partes.join(' · ');
    $('#kmz-avisos').replaceChildren(...(g.avisos ?? []).map((texto) => {
      const li = document.createElement('li');
      li.textContent = texto;
      return li;
    }));
  }
  const ajuste = entradas.ajuste ?? { de: 0, dn: 0 };
  const signo = (v) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}`;
  $('#kmz-ajuste').textContent = `Este ${signo(ajuste.de)} m · Norte ${signo(ajuste.dn)} m`;
  const arrastre = $('[data-accion="kmz-arrastrar"]');
  arrastre.setAttribute('aria-pressed', String(arrastrar));
  arrastre.textContent = arrastrar ? 'Arrastrando los lotes (clic para soltar)' : 'Arrastrar los lotes en el mapa';
  for (const b of $$('#kmz-ajuste-fino button')) b.disabled = !g;
  $('[data-accion="kmz-georreferenciar"]').disabled = !plano.digitalizado?.vigente
    || (entradas.anclas.length < 2 && !entradas.cuadricula);
  $('#kmz-panel-ubicar [data-accion="kmz-siguiente"]').disabled = !vigente;
}

function pintarRevisar() {
  const cuenta = resumenRevision(rasgosGeo?.features ?? []);
  const datos = [
    ['Lotes', cuenta.lotes, null],
    ['Área ±2 %', cuenta.verde, 'verde'],
    ['Área ±5 %', cuenta.ambar, 'ambar'],
    ['Área más de 5 %', cuenta.rojo, 'rojo'],
    ['Sin área oficial', cuenta.gris, 'gris'],
    ['Sin número', cuenta.sin_numero, cuenta.sin_numero ? 'rojo' : null],
    ['Repetidos', cuenta.duplicados, cuenta.duplicados ? 'rojo' : null],
  ];
  $('#kmz-revision').replaceChildren(...datos.map(([rotulo, valor, color]) => {
    const div = document.createElement('div');
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    if (color) {
      const punto = document.createElement('i');
      punto.className = 'kmz-punto';
      punto.style.background = COLORES[color];
      dt.append(punto);
    }
    dt.append(rotulo);
    dd.textContent = valor;
    div.append(dt, dd);
    return div;
  }));
  const problemas = cuenta.duplicados;
  $('#kmz-revision-nota').textContent = problemas
    ? 'Hay números repetidos: el KMZ no se puede crear así. Vuelve a Numerar.'
    : cuenta.sin_numero
      ? (cuenta.sin_numero === 1 ? 'Una parte queda sin número (rayada en rojo) y no va al KMZ.'
        : `${cuenta.sin_numero} partes quedan sin número (rayadas en rojo) y no van al KMZ.`)
        + ' Si es un lote, vuelve a Numerar.'
      : cuenta.lotes === cuenta.gris
      ? 'No se leyó el cuadro de superficies: revisa a ojo que los lotes calcen con los caminos.'
      : 'Los rojos tienen un área muy distinta a la oficial: suelen ser lotes mal separados.';
  $('#kmz-panel-revisar [data-accion="kmz-siguiente"]').disabled = Boolean(problemas);
}

function pintarCrear() {
  if (!plano) return;
  const hay = terminado();
  $('#kmz-crear-texto').textContent = plano.paso === 'listo'
    ? 'El KMZ ya está creado con lo último que ubicaste.'
    : hay ? 'Ya hay un KMZ creado de antes: crearlo de nuevo lo reemplaza con lo último que ubicaste.'
      : 'Un polígono por lote, con su número. Después lo descargas o lo usas en un master.';
  const crear = $('[data-accion="kmz-crear"]');
  crear.disabled = !pasosHabilitados(plano).crear;
  crear.textContent = hay ? 'Crear el KMZ de nuevo' : 'Crear el KMZ';
  crear.className = hay ? 'boton boton--contorno' : 'boton boton--grande';
  // Descargar y usar sirven mientras haya un KMZ hecho, aunque esté por rehacerse.
  $('#kmz-listo').hidden = !hay;
  $('#kmz-descargar').href = descargaDe(slug);
  if (hay && !$('#kmz-listo-texto').textContent) {
    $('#kmz-listo-texto').textContent = plano.paso === 'listo'
      ? `Listo: el KMZ "${plano.nombre}" está creado.`
      : `El KMZ "${plano.nombre}" que creaste antes sigue disponible.`;
  }
}

// --- mapa -------------------------------------------------------------------------------

async function prepararMapa() {
  if (!mapa) {
    const L = await cargarLeaflet();
    mapa = new MapaKmz(L, $('#kmz-mapa'));
    mapa.alTocar = marcarEnMapa;
    mapa.alArrastrar = arrastreDelMapa;
  }
  mapa.arrastrable = arrastrar;
  requestAnimationFrame(() => mapa.invalidar());
}

function pintarMapa(encuadrar = false) {
  if (!mapa) return;
  const g = plano?.georreferencia;
  mapa.ponerAnclas(paso === 'ubicar' ? entradas.anclas : [], g?.vigente ? g.atipicas ?? [] : []);
  mapa.ponerLotes(rasgosGeo, paso === 'revisar' ? 'nivel' : 'contorno', paso === 'revisar' ? ficha : null);
  if (encuadrar) requestAnimationFrame(() => { mapa.invalidar(); mapa.encuadrar(); });
}

/** Lo que dice un lote al tocarlo en la revisión. */
function ficha(p) {
  const nodo = document.createElement('div');
  nodo.className = 'kmz-ficha';
  const titulo = document.createElement('strong');
  titulo.textContent = p.numero ? `Lote ${p.numero}` : 'Sin número';
  nodo.append(titulo);
  const renglon = (texto) => { const s = document.createElement('span'); s.textContent = texto; nodo.append(s); };
  const m2 = (v) => `${new Intl.NumberFormat('es-CL').format(Math.round(v))} m²`;
  if (p.area_m2 != null) renglon(`Área: ${m2(p.area_m2)}`);
  if (p.area_oficial_m2 != null) {
    renglon(`Oficial: ${m2(p.area_oficial_m2)} (${p.error_area > 0 ? '+' : ''}${(p.error_area * 100).toFixed(1)} %)`);
  }
  if (p.banderas?.includes('duplicado')) renglon('Número repetido');
  if (p.origen === 'lector') renglon(`Número leído del plano (${p.apoyo ?? 0} lecturas)`);
  return nodo;
}

// --- dibujo sobre el plano -------------------------------------------------------------------

function dibujar(ctx, P) {
  if (!plano?.pdf) return;
  const [W, H] = [ctx.canvas.width, ctx.canvas.height];

  // Lo que queda fuera del dibujo, en penumbra.
  if (entradas.rectangulo && ['marcar', 'digitalizar'].includes(paso)) {
    const [x0, y0, x1, y1] = entradas.rectangulo;
    const [a, b] = P(x0, y0);
    const [c, d] = P(x1, y1);
    ctx.save();
    ctx.fillStyle = 'rgb(9 9 11 / 0.35)';
    ctx.beginPath();
    ctx.rect(0, 0, W, H);
    ctx.rect(a, b, c - a, d - b);
    ctx.fill('evenodd');
    ctx.strokeStyle = '#16a34a';
    ctx.lineWidth = 2;
    ctx.strokeRect(a, b, c - a, d - b);
    ctx.restore();
  }

  if (['marcar', 'digitalizar'].includes(paso)) {
    entradas.mascaras.forEach(([x0, y0, x1, y1], i) => {
      const [a, b] = P(x0, y0);
      const [c, d] = P(x1, y1);
      ctx.fillStyle = 'rgb(220 38 38 / 0.22)';
      ctx.fillRect(a, b, c - a, d - b);
      ctx.strokeStyle = '#dc2626';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(a, b, c - a, d - b);
      etiqueta(ctx, `Tapado ${i + 1}`, a + 4, b + 4, '#dc2626', 'left');
    });
    const esquinas = esquinasMarcando.length ? esquinasMarcando : entradas.esquinas ?? [];
    if (esquinas.length) {
      ctx.strokeStyle = '#7c3aed';
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      esquinas.forEach(([x, y], i) => { const [a, b] = P(x, y); if (i) ctx.lineTo(a, b); else ctx.moveTo(a, b); });
      if (esquinas.length === 4) ctx.closePath();
      ctx.stroke();
      esquinas.forEach(([x, y], i) => punto(ctx, P(x, y), '#7c3aed', String(i + 1)));
    }
  }

  // Los lotes digitalizados, si son de esta página y esta rotación.
  const hoja = plano.digitalizado?.pagina;
  const calzan = !hoja || (hoja.numero === entradas.pagina && hoja.rotacion === entradas.rotacion);
  if (rasgos.length && paso !== 'subir' && calzan) {
    const tenue = paso === 'marcar';
    for (const r of rasgos) {
      const p = r.properties;
      const malo = p.banderas.length > 0;
      const lector = p.origen === 'lector';
      const alfa = lector ? 0.35 + 0.5 * Math.min(1, p.confianza ?? 0.5) : 1;
      ctx.beginPath();
      for (const anillo of r.geometry.coordinates) {
        anillo.forEach(([x, y], i) => { const [a, b] = P(x, y); if (i) ctx.lineTo(a, b); else ctx.moveTo(a, b); });
        ctx.closePath();
      }
      ctx.fillStyle = malo ? 'rgb(220 38 38 / 0.18)' : lector ? `rgb(37 99 235 / ${0.12 * alfa})` : 'rgb(22 163 74 / 0.10)';
      if (!tenue) ctx.fill('evenodd');
      ctx.strokeStyle = malo ? '#dc2626' : lector ? `rgb(37 99 235 / ${alfa})` : '#15803d';
      ctx.lineWidth = malo ? 2 : 1.25;
      ctx.setLineDash(malo ? [5, 3] : []);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    if (!tenue) {
      for (const r of rasgos) {
        const p = r.properties;
        const [a, b0] = P(...r.rotulo);
        // Sobre la semilla va su punto: el número, justo arriba.
        const b = p.semilla ? b0 - 14 : b0;
        const lector = p.origen === 'lector';
        const texto = p.numero == null ? '?' : `${p.numero}${lector && (p.apoyo ?? 0) < 3 ? '?' : ''}`;
        etiqueta(ctx, texto, a, b, p.banderas.length ? '#dc2626' : lector ? '#1d4ed8' : '#14532d', 'center');
      }
    }
  }

  // Los números que marcó la loteadora.
  if (['marcar', 'numerar'].includes(paso)) {
    for (const s of entradas.semillas) {
      const q = P(s.x, s.y);
      punto(ctx, q, '#18181b');
      // En Numerar, el número ya escrito en su lote no se repite.
      const yaEsta = paso === 'numerar' && rasgos.some((r) => r.properties.numero === s.numero);
      if (!yaEsta) etiqueta(ctx, s.numero, q[0], q[1] - 16, '#18181b', 'center');
    }
  }
  if (numerando) punto(ctx, P(numerando.x, numerando.y), '#f59e0b');

  // Las anclas.
  if (paso === 'ubicar') {
    const g = plano.georreferencia;
    for (const a of entradas.anclas) {
      const mala = g?.vigente && g.atipicas?.includes(a.nombre);
      const q = P(a.x, a.y);
      mira(ctx, q, mala ? '#dc2626' : '#2563eb');
      etiqueta(ctx, a.nombre, q[0] + 10, q[1] - 10, mala ? '#dc2626' : '#1d4ed8', 'left');
    }
    if (pendiente) {
      const q = P(pendiente.x, pendiente.y);
      mira(ctx, q, '#f59e0b');
      etiqueta(ctx, `${pendiente.nombre} → mapa`, q[0] + 10, q[1] - 10, '#b45309', 'left');
    }
  }
}

function punto(ctx, [a, b], color, texto) {
  ctx.beginPath();
  ctx.arc(a, b, 6, 0, Math.PI * 2);
  ctx.fillStyle = color;
  ctx.fill();
  ctx.strokeStyle = '#fff';
  ctx.lineWidth = 2;
  ctx.stroke();
  if (texto) etiqueta(ctx, texto, a + 9, b - 9, color, 'left');
}

function mira(ctx, [a, b], color) {
  ctx.strokeStyle = '#fff';
  ctx.lineWidth = 4;
  for (const ancho of [4, 2]) {
    ctx.lineWidth = ancho;
    ctx.strokeStyle = ancho === 4 ? '#fff' : color;
    ctx.beginPath();
    ctx.arc(a, b, 8, 0, Math.PI * 2);
    ctx.moveTo(a - 14, b); ctx.lineTo(a - 4, b);
    ctx.moveTo(a + 4, b); ctx.lineTo(a + 14, b);
    ctx.moveTo(a, b - 14); ctx.lineTo(a, b - 4);
    ctx.moveTo(a, b + 4); ctx.lineTo(a, b + 14);
    ctx.stroke();
  }
}

function etiqueta(ctx, texto, x, y, color, alinear) {
  ctx.font = '600 12px "Plus Jakarta Sans", system-ui, sans-serif';
  ctx.textAlign = alinear;
  ctx.textBaseline = alinear === 'center' ? 'middle' : 'top';
  ctx.lineJoin = 'round';
  ctx.lineWidth = 3.5;
  ctx.strokeStyle = 'rgb(255 255 255 / 0.95)';
  ctx.strokeText(texto, x, y);
  ctx.fillStyle = color;
  ctx.fillText(texto, x, y);
}
