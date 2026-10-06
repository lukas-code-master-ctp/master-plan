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
  anclaDesde, claveLote, dudosos, duplicados, empujar, girarEntradas, HERRAMIENTAS_RECTANGULO, leerCoordenadas, loteEn, marcarRectangulo,
  nombreDelSistema, ordenarEsquinas, PASOS,
  pasoSugerido, pasosHabilitados, pasosHechos, ponerNumero, puedeSeguirANumerar, puntoDeRotulo, puntoEnPoligono, sesgoDeEscala,
  resumenRevision, siguienteNombre, sinNumero, sugerencias, textoHuecos, verticesDe,
} from './kmz_geometria.js';
import { LienzoPlano } from './lienzo_plano.js';
import { EditorUnion } from './kmz_union.js';
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
let numerando = null;         // {x, y, anillos}: el lote al que se le escribe el número
let lienzo = null;
let mapa = null;
let version = 0;              // cambia al subir otro PDF: la imagen se pide de nuevo
let arrastrar = false;
let corrigiendo = false;      // Revisar: los vértices se arrastran o se borran a mano
let corrigiendoYa = false;    // una corrección sin respuesta: los vértices del mapa están viejos
let esquinasMarcando = [];    // las esquinas del marco mientras faltan: el servidor pide 4 o ninguna
let editorUnion = null;       // el editor de "Une las hojas" (paso 1), creado la primera vez que se abre
const uniendo = () => Boolean(editorUnion?.abierto);

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
    if (e.key === 'Enter') { e.preventDefault(); (pendiente ? usarCoordenadas : irA)().catch((error) => avisar(error.message)); }
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
  corrigiendo = false;
  plano = null;
  entradas = VACIAS();
  rasgos = [];
  rasgosGeo = null;
  pendiente = null;
  rehacer = null;
  sucio = false;
  esquinasMarcando = [];
  editorUnion?.cerrar();
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
  // La imagen de la unión cambia con ella: su huella va en la URL para que se pida de nuevo.
  const v = hoja.huella ? `${version}-${hoja.huella}` : version;
  await lienzo.cargar(`${api()}/paginas/${hoja.n}?v=${v}`,
    hoja.ancho, hoja.alto, entradas.rotacion ?? 0);
}

/** La página del lienzo. La 0 es la unión de hojas: su tamaño lo trae `plano.union`, y
 *  sin él (aún no guardada o inválida) no hay qué mostrar, en vez de la página 1 con
 *  coordenadas que no son suyas. */
const paginaActual = () => {
  if (entradas.pagina === 0) return plano?.union ? { n: 0, ancho: plano.union.ancho, alto: plano.union.alto, huella: plano.union.huella } : null;
  return plano?.paginas?.find((p) => p.n === entradas.pagina) ?? plano?.paginas?.[0];
};

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
  if (accion === 'kmz-siguiente') return irAlPaso(PASOS[PASOS.indexOf(paso) + 1]);
  if (accion === 'kmz-girar-izq') return girar(-90);
  if (accion === 'kmz-girar-der') return girar(90);
  // Con el editor de la unión abierto, el zoom del visor es el suyo.
  const visor = uniendo() ? editorUnion : lienzo;
  if (accion === 'kmz-acercar') return visor.acercar(1.5);
  if (accion === 'kmz-alejar') return visor.acercar(1 / 1.5);
  if (accion === 'kmz-ajustar') return visor.ajustar();
  if (accion === 'kmz-unir') return abrirUnion();
  if (accion === 'kmz-quitar-dibujo') return cambiar({ ...entradas, rectangulo: null });
  if (accion === 'kmz-borrar-esquinas') {
    esquinasMarcando = [];
    return cambiar({ ...entradas, esquinas: null });
  }
  if (accion === 'kmz-digitalizar' || accion === 'kmz-redigitalizar') return digitalizar();
  if (accion === 'kmz-siguiente-sin-numero') return siguienteSinNumero();
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
  if (accion === 'kmz-renombrar') return renombrar();
  if (accion === 'kmz-usar') return usar();
  return undefined;
}

async function irAlPaso(destino) {
  if (!destino || !pasosHabilitados(plano)[destino]) return;
  if (paso === 'ubicar' && destino !== 'ubicar') pendiente = null;
  if (destino !== 'revisar') corrigiendo = false;
  cerrarNumero();
  editorUnion?.cerrar();
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
      editorUnion?.cerrar();
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
  // La unión no se gira entera: cada hoja lleva su giro en el editor.
  if (!hoja || entradas.pagina === 0) return;
  const de = entradas.rotacion ?? 0;
  const a = (((de + grados) % 360) + 360) % 360;
  cambiar(girarEntradas(entradas, de, a, hoja.ancho, hoja.alto));
  await mostrarPagina();
}

// --- 1b. unir las hojas ---------------------------------------------------------------

function abrirUnion() {
  if (!plano?.paginas || plano.paginas.length < 2) return;
  if (!editorUnion) {
    editorUnion = new EditorUnion({ contenedor: $('#kmz-plano'), canvas: $('#kmz-union-lienzo'), panel: $('#kmz-panel-unir') });
    editorUnion.alAfinar = (cuerpo) => pedir(`${api()}/union/afinar`, json(cuerpo));
    editorUnion.alUsar = (union) => usarUnion(union);
    editorUnion.alVolver = () => volverAUnaPagina();
    editorUnion.alCancelar = () => cerrarUnion();
    editorUnion.alError = (error) => avisar(error.message);
  }
  editorUnion.abrir({
    paginas: plano.paginas,
    union: entradas.pagina === 0 ? entradas.union : null,
    // Si ya giró la página elegida hasta leerla derecha, las demás hojas vienen igual.
    rotacion: entradas.pagina === 0 ? 0 : entradas.rotacion ?? 0,
    urlImagen: (n) => `${api()}/paginas/${n}?medio=1&v=${version}`,
  });
  pintarPaso();
  $('#kmz-panel-unir h2').focus();
}

function cerrarUnion() {
  editorUnion?.cerrar();
  pintarPaso();
  mostrarPagina().catch((error) => avisar(error.message));
}

/** "Usar la unión": como cambiar de página, borra lo marcado si la unión cambió. */
async function usarUnion(union) {
  const cambia = entradas.pagina !== 0 || JSON.stringify(entradas.union?.hojas ?? null) !== JSON.stringify(union.hojas);
  if (cambia && hayMarcas()
    && !confirm('Lo marcado es de otra página. Cambiar de página lo borra. ¿Seguir?')) return;
  const antes = entradas;
  cambiar(cambia ? { ...VACIAS(), pagina: 0, rotacion: 0, union } : { ...entradas, union });
  try {
    await guardar();
  } catch (error) {
    // El servidor no la aceptó (p. ej. demasiado grande): vuelve lo de antes y el editor
    // sigue abierto con las hojas como estaban.
    entradas = antes;
    sucio = false;
    throw error;
  }
  editorUnion.cerrar();
  // La imagen de la unión se compone en el servidor la primera vez (unos segundos con
  // láminas grandes): se carga mientras ya se ve el paso Marcar.
  mostrarPagina().catch((error) => avisar(error.message));
  await irAlPaso('marcar');
}

/** "Volver a una sola página": quita la unión (y lo marcado en ella) y vuelve a la página 1. */
async function volverAUnaPagina() {
  if (entradas.pagina !== 0) return cerrarUnion();
  if (hayMarcas() && !confirm('Lo marcado es de otra página. Cambiar de página lo borra. ¿Seguir?')) return undefined;
  editorUnion.cerrar();
  cambiar({ ...VACIAS(), pagina: 1 });
  await mostrarPagina();
  return pintarPaso();
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
  if (nuevas !== entradas) cambiar(nuevas);
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

function escribirNumero(valor) {
  if (!numerando) return;
  const limpio = valor.trim().replace(/^lote\s*/i, '');
  const otra = entradas.semillas.find((s) => claveLote(s.numero) === claveLote(limpio)
    && !(numerando.anillos && puntoEnPoligono(s.x, s.y, numerando.anillos)));
  if (limpio && otra && !confirm(`El ${limpio} ya está marcado en otro lote. ¿Lo pasas a este?`)) return;
  cambiar({ ...entradas, semillas: ponerNumero(entradas.semillas, limpio, [numerando.x, numerando.y], numerando.anillos) });
  cerrarNumero();
  lienzo.canvas.focus({ preventScroll: true });
}

/** Confirma la lectura sugerida de la i-ésima parte con sugerencia: queda como número suyo. */
function confirmarSugerencia(i) {
  const s = sugerencias(rasgos)[i];
  if (!s) return;
  const otra = entradas.semillas.find((x) => claveLote(x.numero) === claveLote(s.numero));
  if (otra && !confirm(`El ${s.numero} ya está marcado en otro lote. ¿Lo pasas a este?`)) return;
  cambiar({ ...entradas, semillas: ponerNumero(entradas.semillas, s.numero, s.rasgo.rotulo, s.rasgo.geometry.coordinates) });
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
  // El editor de la unión vive en el paso 1: su panel reemplaza al de subir mientras está abierto.
  const abierto = uniendo() && paso === 'subir' ? 'unir' : paso;
  for (const panel of $$('.kmz-panel')) panel.hidden = panel.dataset.panel !== abierto;
  const conPlano = ['subir', 'marcar', 'digitalizar', 'numerar', 'ubicar'].includes(paso) && Boolean(plano?.pdf);
  const conMapa = ['ubicar', 'revisar'].includes(paso);
  $('#kmz-escena').hidden = !conPlano && !conMapa;
  $('#kmz-plano').hidden = !conPlano;
  $('#kmz-mapa-caja').hidden = !conMapa;
  $('#kmz-escena').classList.toggle('kmz-escena--doble', conPlano && conMapa);
  $('#kmz-plano').dataset.modo = abierto;
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
  $('#kmz-unir-caja').hidden = plano.paginas.length < 2;
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
  const huecos = d?.huecos ?? [];
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
  const deLote = partes.filter((r) => r.properties.de_lote).length;
  const repetidos = duplicados(rasgos);
  const dudas = dudosos(rasgos);
  const lotesSin = deLote === 1 ? 'Un lote quedó sin número' : `${deLote} lotes quedaron sin número`;
  $('#kmz-sin-numero').textContent = deLote
    ? `${lotesSin} (en rojo, con "?"): no se leyó su número. Haz clic y escríbelo; si no, no va al KMZ.`
      + (partes.length > deLote ? ` Además hay ${partes.length - deLote} ${partes.length - deLote === 1 ? 'parte' : 'partes'}`
        + ' sin número más chicas: si son caminos o áreas comunes, se dejan así.' : '')
    : partes.length
      ? `${partes.length} ${partes.length === 1 ? 'parte sin número' : 'partes sin número'} (en rojo, con "?"). `
        + 'Si es un lote, haz clic y escribe su número. Los caminos y áreas comunes se dejan así: no van al KMZ.'
      : 'Todos los lotes tienen número.';
  $('[data-accion="kmz-siguiente-sin-numero"]').hidden = !partes.length;
  const huecos = textoHuecos(d?.huecos);
  $('#kmz-huecos').hidden = !huecos;
  $('#kmz-huecos').textContent = huecos ? `${huecos} Búscalos en el plano: suelen ser los lotes sin número.` : '';
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
  $('#kmz-dudosos').replaceChildren(...botones(dudas,
    (p) => `${p.numero} · ${p.apoyo ?? 0} lect.${p.confianza != null ? ` · ${Math.round(p.confianza * 100)} %` : ''}`));
  $('#kmz-panel-numerar [data-accion="kmz-siguiente"]').disabled = !d?.vigente;
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
  } else {
    const n = entradas.anclas.length;
    estadoAncla.textContent = n >= 4 ? `${n} puntos marcados.`
      : `${n} de 4 puntos. Haz clic en un punto del plano (acerca bien) y después en el mismo punto del mapa.`;
  }
  $('[data-accion="kmz-cancelar-ancla"]').hidden = !pendiente && !rehacer;
  const usar = $('[data-accion="kmz-usar-coordenadas"]');
  usar.hidden = !pendiente;
  if (pendiente) usar.textContent = `Usar como punto ${pendiente.nombre}`;

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
    ['Lotes sin número', cuenta.sin_numero_lote, cuenta.sin_numero_lote ? 'rojo' : null],
    ['Otras partes sin número', cuenta.sin_numero - cuenta.sin_numero_lote, null],
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
  $('#kmz-panel-revisar [data-accion="kmz-siguiente"]').disabled = Boolean(problemas);
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
  crear.textContent = creando ? 'Creando el KMZ…' : hay ? 'Crear el KMZ de nuevo' : 'Crear el KMZ';
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
        const texto = p.numero == null ? (p.sugerencia?.numero ? `¿${p.sugerencia.numero}?` : '?')
          : `${p.numero}${lector && (p.apoyo ?? 0) < 3 ? '?' : ''}`;
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
