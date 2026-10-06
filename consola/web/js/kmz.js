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
import { $, $$, abrirDialogo, avisar, estado, json, pedir } from './comun.js';
import {
  anclaDesde, aplicarFuera, aplicarNumero, claveLote, conSemillas, decidirResto, devolverAlKmz, dudosos, duplicados, empujar, esFalloPasajero, formaDelCuadro, girarEntradas,
  herramientaAlEntrar, herramientaTrasRectangulo, HERRAMIENTAS_RECTANGULO, leerCoordenadas, loteEn, marcarRectangulo, mensajeNumerar, detalleUbicacion, filaDelPunto, numerosQueFaltan,
  ordenarEsquinas, PASOS, pasoSugerido, pasosHabilitados, pasosHechos, ponerNumero, porQueNoSigue, puntoDeRotulo,
  puntoEnPoligono, restoDe, semaforo, sesgoDeEscala, resumenRevision, resumenUbicacion, siguienteNombre, sinNumero, sugerencias, textoSemaforo, verticesDe,
} from './kmz_geometria.js';
import { LienzoPlano } from './lienzo_plano.js';
import { abrirNombre, abrirUsarKmz, descargaDe, textoDeCreado } from './kmzs.js';
import { cargarLeaflet, COLORES, MapaKmz } from './mapa_kmz.js';
import { oyentes, seguir } from './plano.js';
import { soltadero } from './subida.js';
import { pintarEscaner } from './vuelo.js';

const VACIAS = () => ({
  pagina: 1, rotacion: 0, rectangulo: null, mascaras: [], cuadro: null, esquinas: null, semillas: [], anclas: [],
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
let avisoCuadricula = '';     // la cuadrícula elegida no ubicó y se quitó: se dice en Ubicar
let cuadriculaNoSirve = false; // y no se vuelve a ofrecer mientras se esté en este KMZ
let numerando = null;         // {x, y, anillos}: el lote al que se le escribe el número
let lienzo = null;
let mapa = null;
let version = 0;              // cambia al subir otro PDF: la imagen se pide de nuevo
let arrastrar = false;
let corrigiendo = false;      // Revisar: los vértices se arrastran o se borran a mano
let corrigiendoYa = false;    // una corrección sin respuesta: los vértices del mapa están viejos
let esquinasMarcando = [];    // las esquinas del marco mientras faltan: el servidor pide 4 o ninguna
let ubicandoYa = false;       // se está calculando la ubicación: "Seguir" espera eso, no más puntos
let restoCentrado = null;     // dónde ya se centró el plano para preguntar por el resto (una vez)
let pasoPintado = null;       // el paso de la última pintada: la herramienta de Marcar se elige al entrar
let lanzando = null;          // el KMZ (slug) cuya lectura se está pidiendo: un segundo clic no lanza otra
let falloAlPedir = '';        // por qué no se pudo lanzar la lectura: queda escrito en el paso 3, sobre el botón

// --- guardar ---------------------------------------------------------------------------

let sucio = false;
let temporizador = 0;
let enVuelo = null;
let ubicarLuego = 0;
let vaciado = Promise.resolve();  // el guardado pendiente al dejar un KMZ: se espera antes de releer
let lotesAtrasados = false;   // lo guardado cambia los lotes del servidor sin releer (lo dejado fuera)

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
  const recargar = lotesAtrasados;
  lotesAtrasados = false;
  $('#kmz-guardado').textContent = 'Guardando…';
  enVuelo = (async () => {
    try {
      const normalizadas = await pedir(`${api(mias)}/entradas`, json(entradas, 'PUT'));
      if (mias !== slug) return;
      if (!sucio) entradas = normalizadas;
      plano = await pedir(api(mias));
      // Lo dejado fuera no relee el plano, pero cambia lo que cuentan los lotes en el mapa
      // de Revisar: se traen de nuevo. Los del plano ya se ven así desde el clic.
      if (recargar && mias === slug) await cargarLotes();
      $('#kmz-guardado').textContent = 'Guardado';
    } catch (error) {
      $('#kmz-guardado').textContent = 'No se guardó';
      throw error;
    }
  })();
  try { await enVuelo; } finally { enVuelo = null; }
  pintar();
}

// --- releer solo --------------------------------------------------------------------------
//
// Al cambiar un número en Numerar, los lotes se separan de nuevo con él (la semilla manda
// en el reparto), así que el digitalizado queda atrasado. En vez de pedirle que vuelva a
// digitalizar, se relee el plano solo, un momento después del último cambio: una ráfaga
// de números es una sola lectura. El cambio ya se ve al tiro (`aplicarNumero`); esto es
// para que los lotes queden bien separados y "Seguir" se habilite.

let releerLuego = 0;          // el temporizador: se reinicia con cada cambio
let releyendo = null;         // el KMZ (slug) cuya relectura sola se está lanzando o corre
let releerFallo = false;      // la relectura sola falló: no se insiste hasta el próximo cambio
const RELEER_MS = 1500;

const trabajando = () => Boolean(plano?.trabajo && !plano.trabajo.terminado);
/** "Seguir" en Numerar espera: hay una relectura por lanzar, corriendo o un cambio sin guardar. */
const actualizando = () => Boolean(releerLuego) || releyendo === slug || trabajando() || (paso === 'numerar' && sucio);

function programarRelectura() {
  clearTimeout(releerLuego);
  releerFallo = false;
  const mio = slug;
  releerLuego = setTimeout(() => {
    releerLuego = 0;
    // Si salió de Numerar no se lee a sus espaldas: al volver, `releerSiHaceFalta` la programa.
    if (paso !== 'numerar') return;
    releerSolo(mio).catch((error) => {
      if (mio === slug) {
        releyendo = null;
        releerFallo = true;
        pintarPanel();
      }
      avisar(error.message);
    });
  }, RELEER_MS);
}

/** En Numerar, con el digitalizado atrasado y nada en camino, se programa la relectura. */
function releerSiHaceFalta() {
  const d = plano?.digitalizado;
  if (paso !== 'numerar' || !d || d.vigente || releerLuego || releyendo === slug || releerFallo || trabajando()) return;
  programarRelectura();
}

async function releerSolo(mio) {
  if (mio !== slug) return;
  // Se marca antes de guardar: el guardado repinta y no debe programar otra.
  releyendo = mio;
  await guardar();
  // Con un trabajo corriendo no se lanza otro: al terminar ese, si sigue atrasado, se relanza.
  if (mio !== slug || trabajando() || !plano?.digitalizado || plano.digitalizado.vigente) {
    if (releyendo === mio) releyendo = null;
    if (mio === slug) pintarPanel();
    return;
  }
  await digitalizar({ solo: true });
}

// --- preparar --------------------------------------------------------------------------

export function prepararKmz(opciones) {
  refrescar = opciones.refrescar;
  const pantalla = $('#pantalla-kmz');
  pantalla.addEventListener('click', (evento) => {
    const nodo = evento.target.closest('[data-accion], [data-paso], [data-pagina], [data-herramienta],'
      + ' [data-quitar-mascara], [data-quitar-cuadro], [data-quitar-semilla], [data-ancla-quitar], [data-ancla-rehacer],'
      + ' [data-centrar],'
      + ' [data-confirmar]');
    if (!nodo || nodo.disabled) return;
    manejar(nodo).catch((error) => avisar(error.message));
  });

  $('#kmz-crear-sin-numero').addEventListener('click', () => {
    const pendiente = sinNumeroPendiente;
    sinNumeroPendiente = null;
    $('#kmz-sin-numero-dialogo').close();
    if (pendiente && pendiente === slug) crearKmz(true).catch((error) => avisar(error.message));
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
    if (!e.target.checked && herramienta === 'esquinas') elegirHerramienta(herramientaAlEntrar(entradas, Boolean(plano?.digitalizado)));
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
    if (e.key === 'Enter') { e.preventDefault(); (pendiente ? usarCoordenadas : irA)().catch((error) => avisar(error.message)); }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || pantalla.hidden || document.querySelector('dialog[open]')) return;
    if (pendiente) { cancelarAncla(); e.preventDefault(); }
    else if (numerando) { cerrarNumero(); e.preventDefault(); }
  });

  // Al cambiar el ancho la cabecera puede envolver (pasos en dos líneas): se vuelve a medir.
  window.addEventListener('resize', medirPanel);

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
  // La relectura programada era del KMZ anterior.
  clearTimeout(releerLuego);
  releerLuego = 0;
  releyendo = null;
  releerFallo = false;
  corrigiendo = false;
  plano = null;
  entradas = VACIAS();
  rasgos = [];
  rasgosGeo = null;
  pendiente = null;
  rehacer = null;
  avisoCuadricula = '';
  cuadriculaNoSirve = false;
  sucio = false;
  esquinasMarcando = [];
  restoCentrado = null;
  pasoPintado = null;
  falloAlPedir = '';
  cerrarNumero();
  $('#kmz-guardado').textContent = '';
  $('#kmz-registro').replaceChildren();
  $('#kmz-escaner').hidden = true;
  $('#kmz-listo').hidden = true;
  $('#kmz-listo').classList.remove('kmz-listo--nuevo');
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
    for (const r of px.features) r.rotulo = puntoDeRotulo(r);
    // Si se está releyendo el plano, los números escritos desde la última lectura siguen
    // viéndose puestos: si no, el lote recién numerado volvería a rojo hasta que termine.
    // También con un número escrito que aún no llega al servidor (`sucio` o guardándose):
    // para el servidor los lotes siguen al día, pero no tienen ese número.
    const alDia = plano.digitalizado.vigente && !sucio && !enVuelo;
    rasgos = alDia ? px.features : conSemillas(px.features, entradas.semillas);
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
  if (dataset.quitarCuadro) return cambiar({ ...entradas, cuadro: null });
  if (dataset.quitarSemilla) {
    return cambiar({ ...entradas, semillas: entradas.semillas.filter((s) => s.numero !== dataset.quitarSemilla) });
  }
  if (dataset.anclaQuitar) return quitarAncla(dataset.anclaQuitar, false);
  if (dataset.anclaRehacer) return quitarAncla(dataset.anclaRehacer, true);
  if (dataset.centrar) {
    const [x, y] = dataset.centrar.split(',').map(Number);
    return lienzo.centrar(x, y, Math.max(lienzo.vista.escala, 0.6));
  }
  if (dataset.confirmar) return confirmarSugerencia(Number(dataset.confirmar));

  const accion = dataset.accion;
  // "Seguir" de Marcar no solo abre el paso 3: lee el plano, que es lo único que se hace ahí.
  if (accion === 'kmz-siguiente' && paso === 'marcar') return digitalizar({ desdeMarcar: true });
  if (accion === 'kmz-siguiente') return irAlPaso(PASOS[PASOS.indexOf(paso) + 1]);
  if (accion === 'kmz-girar-izq') return girar(-90);
  if (accion === 'kmz-girar-der') return girar(90);
  if (accion === 'kmz-acercar') return lienzo.acercar(1.5);
  if (accion === 'kmz-alejar') return lienzo.acercar(1 / 1.5);
  if (accion === 'kmz-ajustar') return lienzo.ajustar();
  if (accion === 'kmz-quitar-dibujo') {
    cambiar({ ...entradas, rectangulo: null });
    // Sin dibujo encerrado, lo que toca es encerrarlo otra vez.
    return elegirHerramienta('dibujo');
  }
  if (accion === 'kmz-borrar-esquinas') {
    esquinasMarcando = [];
    return cambiar({ ...entradas, esquinas: null });
  }
  if (accion === 'kmz-digitalizar' || accion === 'kmz-redigitalizar') return digitalizar();
  if (accion === 'kmz-siguiente-sin-numero') return siguienteSinNumero();
  if (accion === 'kmz-resto-incluir') return elegirResto(true);
  if (accion === 'kmz-resto-fuera') return elegirResto(false);
  if (accion === 'kmz-ir') return irA();
  if (accion === 'kmz-usar-coordenadas') return usarCoordenadas();
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
  if (accion === 'kmz-corregir') {
    corrigiendo = !corrigiendo;
    pintarPanel();
    return pintarMapa();
  }
  if (accion === 'kmz-deshacer') return corregir({ accion: 'deshacer' });
  if (accion === 'kmz-georreferenciar') return ubicar();
  if (accion === 'kmz-crear') return crearKmz();
  if (accion === 'kmz-volver-ubicar') return irAlPaso('ubicar');
  if (accion === 'kmz-renombrar') return renombrar();
  if (accion === 'kmz-usar') return usar();
  return undefined;
}

async function irAlPaso(destino) {
  if (!destino || !pasosHabilitados(plano)[destino]) return;
  if (paso === 'ubicar' && destino !== 'ubicar') pendiente = null;
  if (destino !== 'revisar') corrigiendo = false;
  cerrarNumero();
  paso = destino;
  await guardar();
  await pintarPaso();
  $(`#kmz-panel-${paso} h2`)?.focus();
}

// --- 1. subir -------------------------------------------------------------------------

function subirPdf(archivo) {
  if (plano?.pdf && (plano.entradas || plano.digitalizado)
    && !confirm('Subir otro PDF borra lo marcado y lo leído del plano actual. ¿Seguir?')) {
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

const hayMarcas = () => Boolean(entradas.rectangulo || entradas.mascaras.length || entradas.cuadro || entradas.esquinas
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
  lienzo.herramienta = HERRAMIENTAS_RECTANGULO.includes(nombre) ? 'rectangulo' : 'mover';
  for (const boton of $$('[data-herramienta]')) {
    boton.setAttribute('aria-pressed', String(boton.dataset.herramienta === nombre));
  }
  $('#kmz-plano').dataset.herramienta = nombre;
  pintarPanel();
}

function rectangulo(rect) {
  if (paso !== 'marcar') return;
  const nuevas = marcarRectangulo(entradas, herramienta, rect);
  if (nuevas === entradas) return;
  const despues = herramientaTrasRectangulo(herramienta, entradas, nuevas);
  cambiar(nuevas);
  if (despues !== herramienta) elegirHerramienta(despues);
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
    if (trabajo.interrumpido && plano?.trabajo) {
      // Se perdió con el servidor (`seguir`): el botón vuelve aunque el servidor todavía
      // no conteste para recargar el KMZ.
      plano = { ...plano, trabajo: { ...plano.trabajo, estado: 'falló', terminado: true } };
    }
    pintarRegistro();
    if (trabajo.terminado) {
      terminoDigitalizar(trabajo).catch((error) => {
        if (mio === slug) pintarPaso();
        avisar(error.message);
      });
    }
  });
}

/**
 * Con `solo`, es la relectura de Numerar: sin preguntar y sin cambiar de paso. Si no, se
 * abre el paso 3 antes de pedirla, con el escáner ya corriendo. Con `desdeMarcar` ("Seguir"
 * de Marcar), una lectura al día o ya en camino no se repite: solo se va a mirarla.
 */
async function digitalizar({ solo = false, desdeMarcar = false } = {}) {
  const mio = slug;
  // Un doble clic, o "Seguir" y el botón del paso 3 seguidos: la primera ya se está pidiendo.
  if (!solo && lanzando === mio) return;
  if (!solo && !entradas.rectangulo
    && !confirm('No encerraste el dibujo: se va a leer la página entera, con cuadros y cajetín. ¿Seguir?')) return;
  if (!solo) lanzando = mio;
  try {
    await guardar();
    if (mio !== slug) return;
    if (!solo) {
      // La relectura sola de Numerar o una lectura que ya corre: lanzar otra la choca en el
      // servidor. Leído con lo mismo que está marcado (volvió a Marcar a mirar), no hay qué leer.
      const enCamino = trabajando() || releyendo === mio;
      if (enCamino || (desdeMarcar && plano?.digitalizado?.vigente)) {
        await irAlPaso('digitalizar');
        return;
      }
    }
    // Cualquier lectura que se lanza, también la relectura sola de Numerar, deja viejo el
    // "no se pudo empezar": si no, al volver al paso 3 seguiría ahí después de leer bien.
    falloAlPedir = '';
    estado.registros.set(clave(), []);
    // La tarjeta aparece al tiro, en "Abriendo el plano", sin esperar la primera línea.
    estado.trabajos.set(clave(), { accion: 'digitalizar-plano', estado: 'corriendo', terminado: false });
    escuchar();
    if (solo) pintarRegistro();
    else await irAlPaso('digitalizar');
    let id;
    try {
      ({ id } = await pedir(`${api(mio)}/digitalizar`, json({})));
    } catch (error) {
      // No se lanzó (otro trabajo corriendo, sin conexión): la tarjeta no puede quedar
      // escaneando. Queda el aviso y, en el paso 3, el botón para intentarlo de nuevo.
      if (mio === slug) {
        estado.trabajos.delete(clave());
        pintarRegistro();
        // El aviso general queda bajo la barra en el celular: en el paso 3 se dice junto al
        // botón, y no se repite arriba.
        if (!solo && paso === 'digitalizar') {
          falloAlPedir = error.message;
          return;
        }
      }
      throw error;
    }
    if (mio !== slug) return;
    plano = { ...plano, trabajo: { id, terminado: false } };
    pintar();
    seguir(clave(), id);
    refrescar().catch(() => {});
  } finally {
    if (!solo && lanzando === mio) {
      lanzando = null;
      if (mio === slug) pintarPanel();
    }
  }
}

async function terminoDigitalizar(trabajo) {
  const sola = releyendo === slug;
  releyendo = null;
  // Antes de cargar: `cargarTodo` repinta el paso y, con el fallo sin anotar, programaría
  // otra relectura que vuelve a fallar. Una lectura que salió bien borra un fallo anterior.
  if (trabajo.estado === 'listo') releerFallo = false;
  else if (sola || paso === 'numerar') releerFallo = true;
  await cargarTodo();
  if (sola || paso === 'numerar') {
    // La relectura de Numerar (o una que terminó mientras numeraba) no la saca de ahí.
    pintar();
    releerSiHaceFalta();
  } else if (trabajo.estado === 'listo') {
    await irAlPaso(plano.digitalizado?.sin_numero || plano.digitalizado?.faltantes?.length || plano.digitalizado?.huecos?.length ? 'numerar' : 'ubicar');
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
  const actual = lote?.properties.numero ?? '';
  // Un lote sin número con una lectura del lector: va escrita, y Enter la confirma.
  const sugerido = actual ? '' : lote?.properties.sugerencia?.numero ?? '';
  $('#kmz-numero-valor').value = actual || sugerido;
  $('#kmz-numero-rotulo').textContent = lote
    ? (actual ? `Lote ${actual}${lote.properties.origen === 'lector' ? ' (leído)' : ''}: corrige el número`
      : sugerido ? `¿Es el ${sugerido}? Enter lo confirma` : 'Número de este lote')
    : 'Número del lote que está aquí';
  forma.hidden = false;
  // Se mide ya visible y se mantiene entera dentro del plano, también junto a los bordes.
  const margen = 8;
  forma.style.left = `${Math.max(margen, Math.min(sx, caja.clientWidth - forma.offsetWidth - margen))}px`;
  forma.style.top = `${Math.max(margen, Math.min(sy + 12, caja.clientHeight - forma.offsetHeight - margen))}px`;
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

/** Los números del cuadro de superficies, tal como los escribe el cuadro. */
const numerosCuadro = () => plano?.digitalizado?.lector?.numeros_cuadro ?? [];

/**
 * Pone el número: en las semillas (lo que se guarda) y, en Numerar, también en los lotes
 * que se ven, para que el lote pase a verde al tiro. Después se relee el plano solo.
 */
function ponerEnLote(numero, punto, anillos) {
  const semillas = ponerNumero(entradas.semillas, numero, punto, anillos);
  if (paso === 'numerar') {
    // Donde quedó la semilla (si el lote ya tenía una, ahí): ahí va el rótulo.
    const puesta = numero ? semillas.find((s) => s.numero === numero) : null;
    if (puesta) rasgos = aplicarNumero(rasgos, numero, [puesta.x, puesta.y]);
    programarRelectura();
  }
  // Con número, la parte vuelve al KMZ aunque ella la hubiera dejado fuera.
  cambiar({ ...(numero ? devolverAlKmz(entradas, anillos) : entradas), semillas });
}

function escribirNumero(valor) {
  if (!numerando) return;
  // Como lo dice el cuadro: "8-8" queda "8-08", que es como sale en el KMZ.
  const limpio = formaDelCuadro(valor, numerosCuadro());
  const otra = entradas.semillas.find((s) => claveLote(s.numero) === claveLote(limpio)
    && !(numerando.anillos && puntoEnPoligono(s.x, s.y, numerando.anillos)));
  if (limpio && otra && !confirm(`El ${limpio} ya está marcado en otro lote. ¿Lo pasas a este?`)) return;
  const { x, y, anillos } = numerando;
  cerrarNumero();
  ponerEnLote(limpio, [x, y], anillos);
  lienzo.canvas.focus({ preventScroll: true });
}

/** Confirma la lectura sugerida de la i-ésima parte con sugerencia: queda como número suyo. */
function confirmarSugerencia(i) {
  const s = sugerencias(rasgos)[i];
  if (!s) return;
  const numero = formaDelCuadro(s.numero, numerosCuadro());
  const otra = entradas.semillas.find((x) => claveLote(x.numero) === claveLote(numero));
  if (otra && !confirm(`El ${numero} ya está marcado en otro lote. ¿Lo pasas a este?`)) return;
  ponerEnLote(numero, s.rasgo.rotulo, s.rasgo.geometry.coordinates);
}

/**
 * Incluir el resto de la propiedad en el KMZ (con el número del cuadro, o "Resto") o
 * dejarlo fuera. Se ve al tiro; ponerle número cambia las semillas y relee el plano solo,
 * dejarlo fuera no (no cambia cómo se parte el dibujo, solo qué va al KMZ).
 */
function elegirResto(incluir) {
  const resto = restoDe(rasgos);
  if (!resto) return;
  const { rasgo, numero, punto } = resto;
  // Solo si no tiene número se le pone: si ya lo tiene (lo leyó el lector), basta con no dejarlo fuera.
  const ponerle = incluir && rasgo.properties.numero == null ? numero : null;
  const nuevas = decidirResto(entradas, rasgo.geometry.coordinates, punto, incluir, ponerle);
  const otrasSemillas = JSON.stringify(nuevas.semillas) !== JSON.stringify(entradas.semillas);
  rasgos = aplicarFuera(rasgos, punto, !incluir);
  if (ponerle) rasgos = aplicarNumero(rasgos, ponerle, punto);
  if (otrasSemillas) programarRelectura();
  lotesAtrasados = true;
  cambiar(nuevas);
}

function siguienteSinNumero() {
  // Primero los del tamaño de un lote: los caminos y áreas comunes quedan al final.
  const lista = sinNumero(rasgos);
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
  // En pantalla angosta el mapa queda debajo del plano: se trae a la vista para el clic que falta.
  const caja = $('#kmz-mapa-caja');
  const { top, bottom } = caja.getBoundingClientRect();
  if (!caja.hidden && (top < 0 || bottom > window.innerHeight)) caja.scrollIntoView({ block: 'nearest' });
}

function marcarEnMapa(lat, lon) {
  if (paso !== 'ubicar') return;
  if (!pendiente) {
    $('#kmz-ancla-estado').textContent = 'Primero haz clic en el punto del plano; después, en el mismo punto del mapa.';
    return;
  }
  const ancla = anclaDesde(pendiente, lat, lon);
  pendiente = null;
  rehacer = null;
  avisoCuadricula = '';
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

const NO_UBICO_CUADRICULA = 'No se pudo ubicar con la cuadrícula del plano. Marca los puntos a mano.';

/** Elegir la cuadrícula ubica al tiro. Si no ubica con ella (error, o el servidor cayó a
 * las anclas), se quita sola y se dice: así no queda elegida algo que no sirve. */
async function usarCuadricula(si) {
  const propuesta = plano?.digitalizado?.lector?.cuadricula;
  if (si && !propuesta) return;
  const mio = slug;
  avisoCuadricula = '';
  const nuevas = { ...entradas };
  if (si) nuevas.cuadricula = propuesta; else delete nuevas.cuadricula;
  cambiar(nuevas);
  if (!si) {
    if (entradas.anclas.length >= 2) await ubicar();
    return;
  }
  let sirvio = false;
  try {
    // `ubicar` no corre si el digitalizado está atrasado: eso no es culpa de la cuadrícula.
    if (!await ubicar()) return;
    sirvio = plano?.georreferencia?.metodo === 'cuadricula';
  } catch (error) {
    // Sin conexión o con el servidor caído no se sabe si sirve: se avisa y queda elegida,
    // para reintentar con "Ubicar de nuevo". Solo un "no" del servidor la descarta.
    if (esFalloPasajero(error)) {
      if (mio === slug) avisar(error.message);
      return;
    }
    sirvio = false;
  }
  // Si en la espera se pasó a otro KMZ, `entradas` y `plano` ya son de ese: no se toca.
  if (mio !== slug || sirvio || !entradas.cuadricula) return;
  const sinCuadricula = { ...entradas };
  delete sinCuadricula.cuadricula;
  cambiar(sinCuadricula);
  avisoCuadricula = NO_UBICO_CUADRICULA;
  cuadriculaNoSirve = true;
  if (entradas.anclas.length >= 2) await ubicar().catch((e) => avisar(e.message));
  else await guardar();
  pintarPanel();
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

/** Devuelve si de verdad ubicó (no corre con el digitalizado atrasado o sin con qué). */
async function ubicar() {
  clearTimeout(ubicarLuego);
  const mio = slug;
  await guardar();
  // Se pasó a otro KMZ mientras se guardaba: ubicar ese no lo pidió nadie.
  if (mio !== slug) return false;
  if (!plano?.digitalizado?.vigente) return false;
  if (entradas.anclas.length < 2 && !entradas.cuadricula) return false;
  $('#kmz-ancla-estado').textContent = 'Ubicando…';
  ubicandoYa = true;
  pintarPorQue();
  try {
    const georreferencia = await pedir(`${api(mio)}/georreferenciar`, json({}));
    if (mio !== slug) return false;
    plano.georreferencia = georreferencia;
  } catch (error) {
    if (mio !== slug) return false;
    $('#kmz-ancla-estado').textContent = '';
    ubicandoYa = false;
    pintarPorQue();
    throw error;
  } finally {
    ubicandoYa = false;
  }
  const nuevo = await pedir(api(mio));
  const geo = await pedir(`${api(mio)}/lotes?en=lonlat`);
  if (mio !== slug) return false;
  plano = nuevo;
  rasgosGeo = geo;
  pintar();
  pintarMapa();
  return true;
}

const NO_ENTENDI = `No entendí esas coordenadas. Escríbelas como -34.98, -71.24 o como 34°10'37.5"S 71°32'53.9"W.`;

async function irA() {
  const punto = leerCoordenadas($('#kmz-ir-a').value);
  if (!punto) throw new Error(NO_ENTENDI);
  await prepararMapa();
  mapa.ir(punto.lat, punto.lon, 16);
}

/** Con un punto marcado en el plano, las coordenadas escritas son su lugar en el mapa. */
async function usarCoordenadas() {
  if (!pendiente) return irA();
  const punto = leerCoordenadas($('#kmz-ir-a').value);
  if (!punto) throw new Error(NO_ENTENDI);
  await prepararMapa();
  mapa.ir(punto.lat, punto.lon, 16);
  marcarEnMapa(punto.lat, punto.lon);
}

// --- 7. crear ----------------------------------------------------------------------------

/** El KMZ (slug) que espera que confirme crearlo sin sus lotes sin número. */
let sinNumeroPendiente = null;

/** El KMZ (slug) que se está creando: su botón queda trabajando hasta que responda. */
let creandoKmz = null;

/** Con `omitir`, sin los lotes sin número (lo confirmó en el diálogo). */
async function crearKmz(omitir = false) {
  const mio = slug;
  if (creandoKmz === mio) return;
  // Se prende antes de guardar: el guardado pendiente también es parte de la espera.
  creandoKmz = mio;
  pintarCrear();
  try {
    await guardar();
    let creado;
    try {
      creado = await pedir(`${api(mio)}/crear`, json(omitir ? { omitir_sin_numero: true } : {}));
    } catch (error) {
      // Quedan lotes sin número: se crea igual solo si ella lo confirma en el diálogo.
      // El `finally` suelta el botón: mientras decide, nada está trabajando.
      if (omitir || error.estado !== 409 || !error.cuerpo?.sin_numero) throw error;
      if (mio !== slug) return;
      sinNumeroPendiente = mio;
      $('#kmz-sin-numero-texto').textContent = error.message;
      abrirDialogo($('#kmz-sin-numero-dialogo'));
      return;
    }
    if (mio !== slug) return;
    const fresco = await pedir(api(mio));
    // Si se fue a otro KMZ mientras se leía, ese no recibe el plano ni el aviso de este.
    if (mio !== slug) return;
    plano = fresco;
    $('#kmz-listo-texto').textContent = textoDeCreado(plano.nombre, creado.lotes);
    await refrescar();
    pintar();
    destellarListo();
  } finally {
    // Si mientras tanto fue a otro KMZ y lo creó, ese sigue trabajando: solo se suelta el propio.
    if (creandoKmz === mio) {
      creandoKmz = null;
      if (mio === slug) pintarCrear();
    }
  }
}

/** El aviso verde destella al crear: si ya estaba a la vista, sin esto un segundo
 *  clic no se nota. Quitar la clase y forzar el reflow reinicia la animación. */
function destellarListo() {
  const listo = $('#kmz-listo');
  listo.classList.remove('kmz-listo--nuevo');
  void listo.offsetWidth;
  listo.classList.add('kmz-listo--nuevo');
  // Se saca al terminar: si quedara puesta, volvería a destellar cada vez que el aviso
  // se muestra de nuevo (al volver a este KMZ desde otro).
  listo.addEventListener('animationend', () => listo.classList.remove('kmz-listo--nuevo'), { once: true });
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
  else if (pasoPintado !== 'marcar') elegirHerramienta(herramientaAlEntrar(entradas, Boolean(plano?.digitalizado)));
  pasoPintado = paso;
  medirPanel();
  pintar();
  // Llegar a Numerar con los lotes atrasados (se cambió algo antes): se releen solos.
  releerSiHaceFalta();
  if (conMapa) {
    await prepararMapa();
    pintarMapa(true);
  }
}

/**
 * El alto del panel en escritorio es lo que queda de pantalla bajo su borde de arriba. Con
 * un alto fijo (`100vh - 12rem`) la cabecera real era más alta y el panel terminaba ~70 px
 * bajo el borde: el pie pegado al panel ("Seguir") no se veía hasta desplazar la página.
 */
function medirPanel() {
  const cuerpo = $('#kmz-cuerpo');
  if (!cuerpo || $('#pantalla-kmz').hidden) return;
  const arriba = Math.round(cuerpo.getBoundingClientRect().top + window.scrollY);
  cuerpo.style.setProperty('--kmz-arriba', `${arriba}px`);
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
  // En Numerar no: ahí los lotes se releen solos y el panel dice "Actualizando los lotes…".
  const atrasado = Boolean(d && !d.vigente) && ['digitalizar', 'ubicar'].includes(paso);
  $('#kmz-atrasado').hidden = !atrasado || trabajando();
  if (paso === 'subir') pintarSubir();
  if (paso === 'marcar') pintarMarcar();
  if (paso === 'digitalizar') pintarDigitalizar();
  if (paso === 'numerar') pintarNumerar();
  if (paso === 'ubicar') pintarUbicar();
  if (paso === 'revisar') pintarRevisar();
  if (paso === 'crear') pintarCrear();
  pintarPorQue();
}

/** El "Seguir" del paso abierto: se apaga con su motivo debajo, en una línea. */
function pintarPorQue() {
  const panel = $(`#kmz-panel-${paso}`);
  const boton = panel?.querySelector('[data-accion="kmz-siguiente"]');
  if (!plano || !boton) return;
  // Mientras se pide la lectura, el servidor todavía no la cuenta como trabajo: ya lo es.
  const e = lanzando === slug ? { ...plano, trabajo: { terminado: false } } : plano;
  const motivo = porQueNoSigue(paso, e, {
    entradas, actualizando: actualizando(), releerFallo, ubicando: ubicandoYa,
    duplicados: paso === 'revisar' ? resumenRevision(rasgosGeo?.features ?? []).duplicados : 0,
  });
  boton.disabled = Boolean(motivo);
  const linea = panel.querySelector('.kmz-por-que');
  if (!linea) return;
  linea.textContent = motivo;
  linea.hidden = !motivo;
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
  if (entradas.cuadro) filas.push(fila('Cuadro de superficies', { quitarCuadro: '1' }));
  for (const s of entradas.semillas) filas.push(fila(`Lote ${s.numero}`, { quitarSemilla: s.numero }));
  lista.replaceChildren(...filas);
  const listo = Boolean(entradas.rectangulo) && (!sinLector || entradas.semillas.length > 0);
  $('#kmz-marcar-nota').textContent = listo ? '' : !entradas.rectangulo
    ? 'Encierra el dibujo del loteo con la herramienta "Encerrar el dibujo".'
    : 'Marca el número de al menos un lote antes de leer el plano.';
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
  const leyendo = trabajando() || lanzando === slug;
  const d = plano.digitalizado;
  const huecos = d?.huecos ?? [];
  const boton = $('[data-accion="kmz-digitalizar"]');
  // La lectura la lanza "Seguir" de Marcar: este botón es para leer de nuevo (o reintentar si
  // falló), y mientras se lee no aparece, que el escáner ya dice lo que pasa.
  boton.hidden = leyendo;
  boton.disabled = leyendo || !pasosHabilitados(plano).digitalizar;
  const fallo = plano.trabajo?.terminado && plano.trabajo.estado === 'falló';
  boton.textContent = d || fallo || falloAlPedir ? 'Leer el plano de nuevo' : 'Leer el plano';
  $('#kmz-leer-fallo').hidden = leyendo || !falloAlPedir;
  $('#kmz-leer-fallo').textContent = falloAlPedir ? `No se pudo empezar a leer el plano: ${falloAlPedir}` : '';
  pintarRegistro();
  const cifras = $('#kmz-cifras');
  cifras.hidden = !d;
  if (!d) return;
  const lector = d.lector;
  const lineas = [
    ['Lotes', d.lotes],
    ['Lotes sin número', d.sin_numero_lote ?? 0],
    ['Otras partes sin número', d.sin_numero - (d.sin_numero_lote ?? 0)],
    ['Faltan en la numeración', huecos.length ? huecos.join(', ') : '—'],
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
  const partes = sinNumero(rasgos);
  const dudas = dudosos(rasgos);
  const repetidos = duplicados(rasgos);
  // Un solo mensaje: cuántos faltan y qué hacer. Los huecos de la numeración van ahí cuando
  // no queda ningún lote rojo (si no, son esos mismos lotes).
  $('#kmz-sin-numero').textContent = mensajeNumerar(rasgos, numerosQueFaltan(d?.huecos, rasgos));
  pintarResto();
  $('#kmz-actualizando').hidden = !actualizando() || Boolean(releerFallo && !trabajando());
  $('[data-accion="kmz-siguiente-sin-numero"]').hidden = !partes.length;
  // El campo del número ofrece los que faltan: los del cuadro de superficies o, sin cuadro,
  // los huecos de la numeración.
  const cuadro = numerosCuadro();
  $('#kmz-numeros-faltan').replaceChildren(...numerosQueFaltan(cuadro.length ? cuadro : d?.huecos, rasgos)
    .map((numero) => {
      const opcion = document.createElement('option');
      opcion.value = numero;
      return opcion;
    }));
  const porConfirmar = sugerencias(rasgos);
  $('#kmz-sugerencias-caja').hidden = !porConfirmar.length;
  $('#kmz-sugerencias').replaceChildren(...porConfirmar.map(({ numero }, i) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'pastilla pastilla--boton';
    boton.dataset.confirmar = String(i);
    boton.textContent = `¿${numero}? Confirmar`;
    boton.setAttribute('aria-label', `Confirmar el número ${numero} en su lote`);
    return boton;
  }));
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
  $('#kmz-dudosos').replaceChildren(...botones(dudas, (p) => p.numero));
}

/** La tarjeta del resto de la propiedad: la pregunta o lo que ya eligió, con cómo cambiarlo. */
function pintarResto() {
  const resto = restoDe(rasgos);
  const caja = $('#kmz-resto');
  caja.hidden = !resto;
  if (!resto) return;
  const { estado: decision, numero, punto, rasgo } = resto;
  const comoVa = numero === 'Resto' ? 'como "Resto"' : `como lote ${numero}`;
  const m2 = rasgo.properties.area_resto_m2;
  caja.classList.toggle('kmz-resto--decidido', decision !== 'pendiente');
  $('#kmz-resto-texto').textContent = {
    pendiente: '¿Este polígono grande es el resto de la propiedad?',
    incluido: `El resto de la propiedad va en el KMZ ${comoVa}.`,
    fuera: 'El resto de la propiedad queda fuera del KMZ.',
  }[decision];
  $('#kmz-resto-detalle').textContent = decision === 'pendiente'
    ? (m2 ? `El cuadro de superficies trae el ${numero} con ${new Intl.NumberFormat('es-CL').format(m2)} m². ` : '')
      + `Si lo incluyes, va ${comoVa}; si no, no cuenta como lote sin número.`
    : 'Puedes cambiarlo cuando quieras.';
  const incluir = $('[data-accion="kmz-resto-incluir"]');
  const fuera = $('[data-accion="kmz-resto-fuera"]');
  incluir.hidden = decision === 'incluido';
  fuera.hidden = decision === 'fuera';
  incluir.textContent = decision === 'fuera' ? 'Cambiar: incluirlo en el KMZ' : 'Incluirlo en el KMZ';
  fuera.textContent = decision === 'incluido' ? 'Cambiar: dejarlo fuera' : 'Dejarlo fuera';
  // Uno se ve como pregunta principal; el otro, como alternativa.
  incluir.className = `boton boton--chico${decision === 'pendiente' ? '' : ' boton--contorno'}`;
  $('#kmz-resto-ver').dataset.centrar = punto.map((v) => v.toFixed(1)).join(',');
  // Al aparecer la pregunta, el plano va a esa parte: si no, la tarjeta habla de algo que no se ve.
  const donde = `${slug}:${punto.join(',')}`;
  if (decision === 'pendiente' && restoCentrado !== donde && lienzo?.ancho && lienzo.contenedor.clientWidth) {
    restoCentrado = donde;
    // Primero el encuadre de la página: si no, el que hace al llegar la imagen lo pisaría.
    if (!lienzo.ajustada) lienzo.ajustar();
    lienzo.centrar(punto[0], punto[1]);
  }
}

function pintarUbicar() {
  const g = plano.georreferencia;
  const vigente = Boolean(g?.vigente);
  const estadoAncla = $('#kmz-ancla-estado');
  if (pendiente) {
    estadoAncla.textContent = `Punto ${pendiente.nombre} marcado en el plano. Ahora haz clic en el mismo punto del mapa, `
      + `o pega sus coordenadas y aprieta Usar como punto ${pendiente.nombre} (Esc cancela).`;
  } else if (rehacer) {
    estadoAncla.textContent = `Marca de nuevo el punto ${rehacer}: primero en el plano.`;
  } else if (avisoCuadricula) {
    estadoAncla.textContent = avisoCuadricula;
  } else {
    const n = entradas.anclas.length;
    estadoAncla.textContent = n >= 4 ? `${n} puntos marcados.`
      : `${n} de 4 puntos. Haz clic en un punto del plano (acerca bien) y después en el mismo punto del mapa.`;
  }
  $('[data-accion="kmz-cancelar-ancla"]').hidden = !pendiente && !rehacer;
  const usar = $('[data-accion="kmz-usar-coordenadas"]');
  usar.hidden = !pendiente;
  if (pendiente) usar.textContent = `Usar como punto ${pendiente.nombre}`;

  // Una propuesta que ya no ubicó no se vuelve a ofrecer (hasta salir del KMZ).
  const propuesta = cuadriculaNoSirve ? null : plano.digitalizado?.lector?.cuadricula;
  $('#kmz-cuadricula').hidden = !propuesta && !entradas.cuadricula;
  $('[data-accion="kmz-usar-cuadricula"]').hidden = Boolean(entradas.cuadricula) || !propuesta;
  $('[data-accion="kmz-quitar-cuadricula"]').hidden = !entradas.cuadricula;
  $('#kmz-cuadricula-texto').textContent = entradas.cuadricula
    ? 'Se está usando la cuadrícula impresa en el plano. Puedes sumar puntos para comprobar que calza.'
    : 'El plano trae una cuadrícula con coordenadas impresas: es lo más preciso para ubicarlo.';

  // Los puntos con su distancia: cuánto se aleja cada uno de donde lo dejan los demás.
  const porNombre = new Map((g?.anclas ?? []).map((a) => [a.nombre, a]));
  const cuerpo = $('#kmz-anclas tbody');
  cuerpo.replaceChildren(...entradas.anclas.map((a) => {
    const r = porNombre.get(a.nombre);
    const tr = document.createElement('tr');
    const { distancia, estado, detalle } = filaDelPunto(r, g, vigente);
    if (detalle) tr.className = 'kmz-atipica';
    const celda = (texto) => { const td = document.createElement('td'); td.textContent = texto; return td; };
    const celdaEstado = celda(estado);
    // En el celular la tabla no da para la frase entera: "No calza" se ve, y lo que hay que
    // hacer va en el título y para el lector de pantalla (la lista de avisos lo repite).
    if (detalle) {
      celdaEstado.title = `${estado}: ${detalle}`;
      const oculto = document.createElement('span');
      oculto.className = 'oculto';
      oculto.textContent = `: ${detalle}`;
      celdaEstado.append(oculto);
    }
    tr.append(celda(a.nombre), celda(distancia), celdaEstado);
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
    const texto = $('#kmz-ubicacion-texto');
    texto.textContent = (vigente ? '' : 'Antes de tus últimos cambios: ') + resumenUbicacion(g, entradas.anclas.length);
    // Lo técnico (sistema de coordenadas, error medio) queda a mano para el topógrafo.
    texto.title = detalleUbicacion(g);
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
}

function pintarRevisar() {
  const cuenta = resumenRevision(rasgosGeo?.features ?? []);
  const datos = [
    ['Lotes', cuenta.lotes, null],
    ['Área ±2 %', cuenta.verde, 'verde'],
    ['Área ±5 %', cuenta.ambar, 'ambar'],
    ['Área más de 5 %', cuenta.rojo, 'rojo'],
    ['Sin área oficial', cuenta.gris, 'gris'],
    ['Lotes sin número', cuenta.sin_numero_lote, cuenta.sin_numero_lote ? 'rojo' : null],
    ['Otras partes sin número', cuenta.sin_numero - cuenta.sin_numero_lote, null],
    ['Repetidos', cuenta.duplicados, cuenta.duplicados ? 'rojo' : null],
    ...(cuenta.fuera ? [['Fuera del KMZ', cuenta.fuera, 'gris']] : []),
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
  const sesgo = sesgoDeEscala(rasgosGeo?.features ?? []);
  $('#kmz-revision-nota').textContent = problemas
    ? 'Hay números repetidos: el KMZ no se puede crear así. Vuelve a Numerar.'
    : cuenta.sin_numero_lote
      ? (cuenta.sin_numero_lote === 1 ? 'Un lote quedó sin número y no iría al KMZ.'
        : `${cuenta.sin_numero_lote} lotes quedaron sin número y no irían al KMZ.`) + ' Vuelve a Numerar.'
    : cuenta.sin_numero
      ? (cuenta.sin_numero === 1 ? 'Una parte queda sin número (rayada en rojo) y no va al KMZ.'
        : `${cuenta.sin_numero} partes quedan sin número (rayadas en rojo) y no van al KMZ.`)
        + ' Si es un lote, vuelve a Numerar.'
      : cuenta.lotes === cuenta.gris
      ? (entradas.cuadro ? 'No se leyó el cuadro de superficies: revisa a ojo que los lotes calcen con los caminos.'
        : 'Sin cuadro de superficies no hay áreas oficiales: si el plano lo trae, enciérralo en Marcar'
          + ' con "Cuadro de superficies". Si no, revisa a ojo que los lotes calcen con los caminos.')
      : sesgo != null
      ? `Casi todos los lotes salen cerca de un ${Math.abs(sesgo * 100).toFixed(1).replace('.', ',')} %`
        + ` ${sesgo > 0 ? 'más grandes' : 'más chicos'} que el oficial: suele ser la escala de los puntos de Ubicar,`
        + ' no el dibujo. Vuelve a Ubicar y marca 3 o 4 esquinas con coordenadas exactas.'
      : cuenta.rojo
      ? 'Los rojos tienen un área muy distinta a la oficial: suelen ser lotes mal separados.'
      : 'Ningún lote se aparta más de un 5 % del área oficial.';
  const boton = $('[data-accion="kmz-corregir"]');
  boton.setAttribute('aria-pressed', String(corrigiendo));
  boton.textContent = corrigiendo ? 'Listo, dejar de corregir' : 'Corregir vértices a mano';
  const correcciones = plano.digitalizado?.correcciones ?? 0;
  const deshacer = $('[data-accion="kmz-deshacer"]');
  deshacer.hidden = !correcciones;
  deshacer.textContent = `Deshacer (${correcciones})`;
  $('#kmz-corregir-ayuda').hidden = !corrigiendo;
  $('#kmz-corregir-lejos').hidden = !corrigiendo || Boolean(mapa?.verticesVisibles());
}

/** Una corrección a mano: la manda, y trae los lotes y el estado al día. */
async function corregir(cuerpo) {
  // Con una en vuelo, los puntos del mapa todavía son los de antes: otra corrección
  // apuntaría a un vértice que ya no está ahí.
  if (corrigiendoYa) { pintarMapa(); return; }
  const mio = slug;
  corrigiendoYa = true;
  try {
    await pedir(`${api(mio)}/corregir`, json(cuerpo));
  } finally {
    // También si falló: el mapa vuelve a dejar el vértice donde estaba. Si la recarga
    // falla, se avisa aparte para no tapar el error de la corrección.
    try {
      if (mio === slug) {
        plano = await pedir(api(mio));
        await cargarLotes();
        pintar();
        pintarMapa();
      }
    } catch (error) {
      avisar(error.message);
    } finally {
      corrigiendoYa = false;
    }
  }
}

function pintarCrear() {
  if (!plano) return;
  const hay = terminado();
  $('#kmz-crear-texto').textContent = plano.paso === 'listo'
    ? 'El KMZ ya está creado con lo último que ubicaste.'
    : hay ? 'Ya hay un KMZ creado de antes: crearlo de nuevo lo reemplaza con lo último que ubicaste.'
      : 'Un polígono por lote, con su número. Después lo descargas o lo usas en un master.';
  const crear = $('[data-accion="kmz-crear"]');
  const creando = creandoKmz === slug;
  crear.disabled = creando || !pasosHabilitados(plano).crear;
  // Con los lotes en lon/lat (se cargan con el plano ubicado): sin ellos no hay con qué
  // comparar y el semáforo queda oculto, como sin cuadro.
  // Sin la ubicación vigente no se puede crear: los desvíos serían de los puntos viejos.
  const luz = semaforo(pasosHabilitados(plano).crear ? rasgosGeo?.features ?? [] : []);
  const caja = $('#kmz-semaforo');
  const texto = textoSemaforo(luz);
  caja.hidden = !texto;
  caja.dataset.tono = luz.tono ?? '';
  // Solo si cambia: reescribir el mismo texto en una región `status` lo vuelve a anunciar
  // cada vez que algo repinta el panel.
  if ($('#kmz-semaforo-texto').textContent !== texto) $('#kmz-semaforo-texto').textContent = texto;
  $('[data-accion="kmz-volver-ubicar"]').hidden = luz.tono !== 'ambar';
  // Ámbar avisa pero no bloquea: el botón dice que se crea igual. Con el KMZ ya creado
  // con esto mismo no hay "igual" que valga: ya se creó, y rehacerlo da lo mismo.
  const igual = luz.tono === 'ambar' && plano.paso !== 'listo';
  crear.textContent = creando ? 'Creando el KMZ…' : igual ? 'Crear el KMZ igual'
    : hay ? 'Crear el KMZ de nuevo' : 'Crear el KMZ';
  if (creando) crear.setAttribute('aria-busy', 'true'); else crear.removeAttribute('aria-busy');
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
    // Al acercarse aparecen los vértices: el aviso de "acércate" se va.
    mapa.mapa.on('zoomend', () => { if (paso === 'revisar') pintarPanel(); });
  }
  mapa.arrastrable = arrastrar;
  requestAnimationFrame(() => mapa.invalidar());
}

function pintarMapa(encuadrar = false) {
  if (!mapa) return;
  const g = plano?.georreferencia;
  mapa.ponerAnclas(paso === 'ubicar' ? entradas.anclas : [], g?.vigente ? g.atipicas ?? [] : []);
  const revisando = paso === 'revisar';
  mapa.ponerLotes(rasgosGeo, revisando ? 'nivel' : 'contorno', revisando && !corrigiendo ? ficha : null);
  mapa.ponerVertices(revisando && corrigiendo ? verticesDe(rasgosGeo?.features) : [], {
    mover: (punto, a) => corregir({ accion: 'mover', punto: [punto.lon, punto.lat], a: [a.lon, a.lat] })
      .catch((error) => avisar(error.message)),
    borrar: (punto) => corregir({ accion: 'borrar', punto: [punto.lon, punto.lat] })
      .catch((error) => avisar(error.message)),
  });
  if (encuadrar) requestAnimationFrame(() => { mapa.invalidar(); mapa.encuadrar(); });
}

/** Lo que dice un lote al tocarlo en la revisión. */
function ficha(p) {
  const nodo = document.createElement('div');
  nodo.className = 'kmz-ficha';
  const titulo = document.createElement('strong');
  titulo.textContent = p.fuera ? 'Fuera del KMZ' : p.numero ? `Lote ${p.numero}` : 'Sin número';
  nodo.append(titulo);
  const renglon = (texto) => { const s = document.createElement('span'); s.textContent = texto; nodo.append(s); };
  if (p.resto) renglon('Resto de la propiedad');
  const m2 = (v) => `${new Intl.NumberFormat('es-CL').format(Math.round(v))} m²`;
  if (p.area_m2 != null) renglon(`Área: ${m2(p.area_m2)}`);
  if (p.area_oficial_m2 != null) {
    renglon(`Oficial: ${m2(p.area_oficial_m2)} (${p.error_area > 0 ? '+' : ''}${(p.error_area * 100).toFixed(1)} %)`);
  }
  if (p.banderas?.includes('duplicado')) renglon('Número repetido');
  if (p.origen === 'lector') renglon('Número leído del plano');
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
    if (entradas.cuadro) {
      // Puede estar fuera del dibujo: se lee igual (los lotes y sus áreas oficiales).
      const [x0, y0, x1, y1] = entradas.cuadro;
      const [a, b] = P(x0, y0);
      const [c, d] = P(x1, y1);
      ctx.fillStyle = 'rgb(217 119 6 / 0.14)';
      ctx.fillRect(a, b, c - a, d - b);
      ctx.strokeStyle = '#d97706';
      ctx.lineWidth = 2;
      ctx.strokeRect(a, b, c - a, d - b);
      etiqueta(ctx, 'Cuadro de superficies', a + 4, b + 4, '#b45309', 'left');
    }
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
      // Lo que ella dejó fuera del KMZ va en gris: ya no es un problema.
      const afuera = Boolean(p.fuera);
      const malo = p.banderas.length > 0 && !afuera;
      const lector = p.origen === 'lector';
      const alfa = lector ? 0.35 + 0.5 * Math.min(1, p.confianza ?? 0.5) : 1;
      ctx.beginPath();
      for (const anillo of r.geometry.coordinates) {
        anillo.forEach(([x, y], i) => { const [a, b] = P(x, y); if (i) ctx.lineTo(a, b); else ctx.moveTo(a, b); });
        ctx.closePath();
      }
      ctx.fillStyle = afuera ? 'rgb(113 113 122 / 0.12)' : malo ? 'rgb(220 38 38 / 0.18)'
        : lector ? `rgb(37 99 235 / ${0.12 * alfa})` : 'rgb(22 163 74 / 0.10)';
      if (!tenue) ctx.fill('evenodd');
      ctx.strokeStyle = afuera ? '#71717a' : malo ? '#dc2626' : lector ? `rgb(37 99 235 / ${alfa})` : '#15803d';
      ctx.lineWidth = malo ? 2 : 1.25;
      ctx.setLineDash(malo || afuera ? [5, 3] : []);
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
        const texto = p.fuera ? (p.numero ? `${p.numero} · fuera del KMZ` : 'Fuera del KMZ') : p.numero == null
          ? (p.resto ? '¿Resto de la propiedad?' : p.sugerencia?.numero ? `¿${p.sugerencia.numero}?` : '?')
          : `${p.numero}${lector && (p.apoyo ?? 0) < 3 ? '?' : ''}`;
        const color = p.fuera ? '#52525b' : p.banderas.length ? '#dc2626' : lector ? '#1d4ed8' : '#14532d';
        etiqueta(ctx, texto, a, b, color, 'center');
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
