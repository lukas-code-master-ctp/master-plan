/**
 * Un KMZ de Mis KMZ (`#/kmz/<slug>`): del plano aprobado al KMZ de la subdivisión.
 * Todo va contra `/api/kmz/<slug>/...`; el KMZ no es de ningún master. Al crearlo
 * se descarga o se usa en un master (ver `kmzs.js`).
 *
 * Cuatro pasos a la vista: subir el PDF, marcar el dibujo, ubicar en el mapa, y revisar y
 * descargar el KMZ. Leer el plano (`digitalizar`) y Numerar son paneles de Marcar: "Seguir"
 * lee el plano y pasa por Numerar solo si hace falta. Lo que marca la loteadora vive en
 * `entradas` (el mismo `entradas.json` del servidor, en píxeles de página) y se
 * guarda solo, un momento después de cada cambio. El servidor dice qué quedó
 * atrasado (`vigente`) y qué paso sigue (`paso`).
 */
import { $, $$, abrirDialogo, avisar, estado, json, pedir } from './comun.js';
import {
  anclaDesde, aplicarFuera, confirmarSugerencias, calzaLoDigitalizado, aplicarNumero, claveLote, conSemillas, decidirResto, devolverAlKmz, dudosos, duplicados, empujar, esFalloPasajero, formaDelCuadro, girarEntradas,
  herramientaAlEntrar, herramientaTrasRectangulo, HERRAMIENTAS_RECTANGULO, leerCoordenadas, loteEn, marcarRectangulo, mensajeNumerar, detalleUbicacion, filaDelPunto, numerosQueFaltan,
  ordenarEsquinas, PASTILLAS, pastillaDe, pasoDeRuta, pasoSiguiente, pasoSugerido, pasosHabilitados, pasosHechos, ponerNumero, porQueNoSigue, puedeUbicar, puntoDeRotulo,
  puntoEnPoligono, restoDe, semaforo, sesgoDeEscala, resumenRevision, resumenUbicacion, sinNumero, sugerencias, tamanoRotado, textoSemaforo, verticesDe,
  escalaDeUbicacion, escalaDesdeLinea, leerEscala, lotesEnElMapa, textoEscala, textoMetros, ESCALA_LINEA_MIN_PX, normalizarGiro, similitudPorPunto, usaAnclas, usaUbicacion, metodoVigente,
  similitudPorAnclas, ubicacionCompleta, estadoDePuntos, guiaDePuntos, textoFilaActiva, coordenadaCorta, coordenadaDelCampo, ajustaConElCuadro, ofrecerAjusteDelCuadro,
  destinoDelClic, METODOS, metodoAlEntrar, metodosOfrecidos, NOMBRES_METODO, origenDeEscala, textoClicSuelto,
  cambiaElMetodo, avisosDeUbicacion, notaDeEscalaVisible,
  renumerarUniones, siguienteNombre, aplicarUnion, loteConNumero, separarPartes, seTocan, unirParte,
} from './kmz_geometria.js';
import { LienzoPlano } from './lienzo_plano.js';
import { cuadroEnHoja, EditorUnion, hojaDelCuadro, textoBorraLoMarcado, textoHojasUnidas } from './kmz_union.js';
import { abrirNombre, abrirUsarKmz, descargaDe, textoDeCreado } from './kmzs.js';
import { cargarLeaflet, COLORES, MapaKmz } from './mapa_kmz.js';
import { oyentes, seguir } from './plano.js';
import { relevo } from './sondeo.js';
import { soltadero } from './subida.js';
import { pintarEscaner } from './vuelo.js';

const VACIAS = () => ({
  pagina: 1, rotacion: 0, rectangulo: null, mascaras: [], cuadro: null, esquinas: null, semillas: [], anclas: [], uniones: [],
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
// La fila de puntos a medias (`estadoDePuntos`): {nombre} espera su coordenada y {nombre,
// lat, lon} el clic en el plano. Si el nombre ya es un ancla, se está rehaciendo: el ancla
// sigue valiendo hasta que el clic en el plano la reemplace (cancelar la deja como estaba).
let pendiente = null;
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
// La línea de la escala mientras se marca (0, 1 o 2 extremos en px de página): se guarda
// recién con los metros, así que dos clics sueltos no dejan una escala a medias.
let escalaMarcando = [];
let cursorEscala = null;      // dónde está el mouse, para que la línea lo siga tras el primer clic
let editorUnion = null;       // el editor de "Une las hojas" (paso 1), creado la primera vez que se abre
const uniendo = () => Boolean(editorUnion?.abierto);
// Marcar con la unión: el cuadro de superficies se lee de su hoja original, así que se
// encierra en ella. `null` muestra la unión; un número, esa hoja (y solo se dibuja el cuadro).
let cuadroHoja = null;
const conUnion = () => entradas.pagina === 0 && Boolean(entradas.union);
let ubicandoYa = false;       // se está calculando la ubicación: "Seguir" espera eso, no más puntos
let ajustandoCuadro = false;  // se está ajustando (o deshaciendo) el tamaño con el cuadro
let restoCentrado = null;     // dónde ya se centró el plano para preguntar por el resto (una vez)
let rutaAplicada = null;      // el paso de la ruta (`#/kmz/<slug>/<paso>`) que ya se abrió
let pasoPintado = null;       // el paso de la última pintada: la herramienta de Marcar se elige al entrar
let lanzando = null;          // el KMZ (slug) cuya lectura se está pidiendo: un segundo clic no lanza otra
let falloAlPedir = '';        // por qué no se pudo lanzar la lectura: queda escrito en el paso 3, sobre el botón
// Ubicar: el método en pantalla (`METODOS`, o null con las tarjetas a la vista). Al entrar es
// el de `metodoAlEntrar`; "Cambiar de método" lo deja en null sin tocar `entradas.metodo`,
// que cambia recién al elegir otra tarjeta. Lo que hace un clic en el plano sale de él
// (`destinoDelClic`):
// - "un punto": el punto de la coordenada, solo con `marcandoPunto` (tras "Ir", o con
//   "Marcar el punto en el plano"). Un toque para desplazar en el celular no lo mueve.
// - "varios puntos" o "cuadrícula": el punto de la fila activa, cuando ya tiene su coordenada.
// - Si no, no marca nada: se dice cómo (`pistaSuelta`).
let metodoUbicar = null;
let marcandoPunto = false;
let pistaSuelta = '';
// Cuándo fue el último toque (dedo o lápiz, no mouse) en el plano de Ubicar. En el celular,
// tras marcar en el plano la página baja al mapa en el mismo toque, y el clic que el
// navegador sintetiza al final cae en lo que quedó debajo del dedo: el mapa (marcaba el punto
// ahí mismo, en cualquier lugar) o los botones de giro sobre él (giraba el plano 1° o 15° sin
// que ella los tocara). Un clic fuera del plano tan seguido no lo hizo ella.
let tocadoEnPlano = -Infinity;
const CLIC_FANTASMA_MS = 500;
let ubicarVez = 0;            // la última `ubicar` pedida: una anterior que llega tarde no pisa nada

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
    // `button[...]`: el visor también lleva `data-herramienta` (para el cursor), y un clic en
    // el plano no es elegir herramienta.
    const nodo = evento.target.closest('[data-accion], [data-paso], [data-pagina], button[data-herramienta],'
      + ' [data-quitar-mascara], [data-quitar-cuadro], [data-quitar-escala], [data-quitar-semilla], [data-ancla-quitar], [data-ancla-rehacer],'
      + ' [data-centrar], [data-giro], [data-cuadro-hoja], [data-metodo],'
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
  for (const [boton, unir] of [['#kmz-unir-si', true], ['#kmz-unir-pasar', false]]) {
    $(boton).addEventListener('click', () => {
      const pendiente = unirPendiente;
      unirPendiente = null;
      $('#kmz-unir-dialogo').close();
      // Si cambió de KMZ con el diálogo abierto, la parte ya no es de este plano.
      if (pendiente?.slug === slug) (unir ? pendiente.unir : pendiente.pasar)();
    });
  }
  $('#kmz-unir-dialogo').addEventListener('close', () => { unirPendiente = null; });

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
  // Mientras se arrastra el deslizador solo se mueve la vista previa; al soltar, un
  // momento después, se guarda y se ubica en el servidor (`programarUbicar`).
  $('#kmz-giro').addEventListener('input', (e) => girarA(Number(e.target.value)));
  $('#kmz-escala-metros').addEventListener('submit', (e) => {
    e.preventDefault();
    usarEscalaLinea();
  });
  $('#kmz-escala-numero').addEventListener('submit', (e) => {
    e.preventDefault();
    usarEscalaImpresa();
  });
  $('#kmz-ir-a').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); irA().catch((error) => avisar(error.message)); }
  });
  $('#kmz-ancla-coord').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); irAncla().catch((error) => avisar(error.message)); }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape' || pantalla.hidden || document.querySelector('dialog[open]')) return;
    if (pendiente) { cancelarAncla(); e.preventDefault(); }
    else if (marcandoPunto && paso === 'ubicar') { marcandoPunto = false; pintarPanel(); e.preventDefault(); }
    else if (escalaMarcando.length) { cancelarEscala(); e.preventDefault(); }
    else if (numerando) { cerrarNumero(); e.preventDefault(); }
    else if (cuadroHoja !== null || (herramienta === 'cuadro' && conUnion())) { elegirHerramienta('mover'); e.preventDefault(); }
  });

  // Al cambiar el ancho la cabecera puede envolver (pasos en dos líneas): se vuelve a medir.
  window.addEventListener('resize', medirPanel);

  // El clic fantasma tras un toque en el plano (ver `tocadoEnPlano`) no llega a nadie: en
  // captura, antes que Leaflet y que `manejar`.
  document.addEventListener('click', (evento) => {
    if (performance.now() - tocadoEnPlano >= CLIC_FANTASMA_MS || evento.target.closest?.('#kmz-plano')) return;
    tocadoEnPlano = -Infinity;
    evento.preventDefault();
    evento.stopPropagation();
  }, true);

  lienzo = new LienzoPlano($('#kmz-plano'), $('#kmz-lienzo'));
  lienzo.alDibujar = dibujar;
  lienzo.alTocar = tocarPlano;
  lienzo.alRectangulo = rectangulo;
  lienzo.alPasar = pasarPorPlano;
}

/**
 * Llega a la pantalla (`nuevo`) o se repinta tras un refresco de la lista. `pasoPedido`: el
 * de `#/kmz/<slug>/<paso>` (también los nombres de antes, ver `pasoDeRuta`).
 */
export function pintarKmz(nuevoSlug, { nuevo = false, paso: pasoPedido = null } = {}) {
  pintarCabecera(nuevoSlug);
  if (!nuevo && nuevoSlug === slug) {
    // El mismo KMZ con otro paso en la ruta: se va a ese paso, si ya se puede abrir.
    if (pasoPedido && plano && pasoPedido !== rutaAplicada) {
      rutaAplicada = pasoPedido;
      irAlPaso(pasoDeRuta(pasoPedido, plano)).catch((error) => avisar(error.message));
    }
    return;
  }
  rutaAplicada = pasoPedido;
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
  $('#kmz-ancla-coord').value = '';
  metodoUbicar = null;
  marcandoPunto = false;
  pistaSuelta = '';
  clearTimeout(ubicarLuego);
  ubicarLuego = 0;
  avisoCuadricula = '';
  cuadriculaNoSirve = false;
  sucio = false;
  esquinasMarcando = [];
  escalaMarcando = [];
  cursorEscala = null;
  cuadroHoja = null;
  // Otro KMZ parte moviendo: una herramienta del anterior (el cuadro de una página suelta)
  // dejaría el lienzo dibujando rectángulos sobre una unión sin hoja elegida.
  elegirHerramienta('mover');
  editorUnion?.cerrar();
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
  // La pantalla dio la lectura por interrumpida y la consola, al volver, la retomó con otro
  // trabajo: se sigue, aunque ya haya terminado, para que el escáner diga cómo terminó de
  // verdad y no "se interrumpió". `refrescar` solo ve las que siguen corriendo. Si es la
  // misma (no se reinició: se cortó la red más de un minuto), se sigue donde iba.
  const perdida = estado.registroDe.get(clave());
  const retomada = !perdida?.perdido ? null
    : plano.trabajo?.id === perdida.id ? perdida.id : relevo(plano, perdida.id);
  if (retomada && !estado.sondeos.has(clave())) {
    escuchar();
    seguir(clave(), retomada);
  }
  await cargarLotes();
  if (alLlegar) {
    paso = pasoSugerido(plano);
    if (plano.trabajo && !plano.trabajo.terminado) {
      paso = 'digitalizar';
      escuchar();
      if (!estado.sondeos.has(clave())) seguir(clave(), plano.trabajo.id);
    }
    // El paso de la ruta gana si ya se puede abrir; si no, el sugerido.
    const pedido = pasoDeRuta(rutaAplicada, plano);
    if (pedido && pasosHabilitados(plano)[pedido]) paso = pedido;
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
    rasgos = alDia ? px.features : conSemillas(px.features, entradas.semillas, entradas.uniones);
  }
  if (plano?.georreferencia) {
    rasgosGeo = await pedir(`${api(mio)}/lotes?en=lonlat`);
  }
  lienzo?.redibujar();
}

/** La página elegida, en el lienzo. */
async function mostrarPagina() {
  const original = cuadroHoja !== null ? hojaDelCuadro(plano?.paginas, entradas.union, cuadroHoja) : null;
  if (original) {
    await lienzo.cargar(`${api()}/paginas/${original.n}?v=${version}`, original.ancho, original.alto, original.rotacion);
    return;
  }
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
  if (dataset.quitarCuadro) {
    return cambiar(conUnion() ? { ...entradas, union: { ...entradas.union, cuadro: null } } : { ...entradas, cuadro: null });
  }
  if (dataset.quitarEscala) return cambiar({ ...entradas, escala: null });
  if (dataset.cuadroHoja) return verHojaDelCuadro(Number(dataset.cuadroHoja));
  if (dataset.quitarSemilla) {
    return cambiar({ ...entradas, semillas: entradas.semillas.filter((s) => s.numero !== dataset.quitarSemilla) });
  }
  if (dataset.anclaQuitar) return quitarAncla(dataset.anclaQuitar);
  if (dataset.anclaRehacer) return rehacerAncla(dataset.anclaRehacer);
  if (dataset.centrar) {
    const [x, y] = dataset.centrar.split(',').map(Number);
    return lienzo.centrar(x, y, Math.max(lienzo.vista.escala, 0.6));
  }
  if (dataset.confirmar) return confirmarSugerencia(Number(dataset.confirmar));
  if (dataset.giro) return girarA((entradas.ubicacion?.giro ?? 0) + Number(dataset.giro));
  if (dataset.metodo) return elegirMetodo(dataset.metodo);

  const accion = dataset.accion;
  // "Seguir" de Marcar no solo cambia de panel: lee el plano, y al terminar va a Numerar o a Ubicar.
  if (accion === 'kmz-siguiente' && paso === 'marcar') return digitalizar({ desdeMarcar: true });
  if (accion === 'kmz-siguiente') return irAlPaso(pasoSiguiente(paso, plano, rasgos));
  if (accion === 'kmz-girar-izq') return girar(-90);
  if (accion === 'kmz-girar-der') return girar(90);
  // Con el editor de la unión abierto, el zoom del visor es el suyo.
  const visor = uniendo() ? editorUnion : lienzo;
  if (accion === 'kmz-acercar') return visor.acercar(1.5);
  if (accion === 'kmz-alejar') return visor.acercar(1 / 1.5);
  if (accion === 'kmz-ajustar') return visor.ajustar();
  if (accion === 'kmz-unir') return abrirUnion();
  if (accion === 'kmz-volver-union') return elegirHerramienta('mover');
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
  if (accion === 'kmz-separar') return separar();
  if (accion === 'kmz-confirmar-todos') return confirmarTodos();
  if (accion === 'kmz-resto-incluir') return elegirResto(true);
  if (accion === 'kmz-resto-fuera') return elegirResto(false);
  if (accion === 'kmz-ir') return irA();
  if (accion === 'kmz-ancla-ir') return irAncla();
  if (accion === 'kmz-anadir-punto') return anadirPunto();
  if (accion === 'kmz-cancelar-ancla') return cancelarAncla();
  if (accion === 'kmz-cambiar-metodo') return cambiarDeMetodo();
  if (accion === 'kmz-ir-escala') return irAMarcarEscala();
  if (accion === 'kmz-marcar-punto') {
    marcandoPunto = !marcandoPunto;
    pistaSuelta = '';
    lienzo.redibujar();
    return pintarPanel();
  }
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
  if (accion === 'kmz-ajustar-cuadro') return ajustarConElCuadro(true);
  if (accion === 'kmz-deshacer-cuadro') return ajustarConElCuadro(false);
  if (accion === 'kmz-renombrar') return renombrar();
  if (accion === 'kmz-usar') return usar();
  return undefined;
}

async function irAlPaso(destino) {
  if (!destino || !pasosHabilitados(plano)[destino]) return;
  if (paso === 'ubicar' && destino !== 'ubicar') soltarFila();
  if (destino !== 'revisar') corrigiendo = false;
  cerrarNumero();
  editorUnion?.cerrar();
  paso = destino;
  await guardar();
  await pintarPaso();
  $(`#kmz-panel-${paso} h2`)?.focus();
}

// --- ubicar: el método -------------------------------------------------------------------

/** La cuadrícula que propone el lector, si no se probó ya sin éxito en este KMZ. */
const propuestaCuadricula = () => (cuadriculaNoSirve ? null : plano?.digitalizado?.lector?.cuadricula ?? null);

/** Con "un punto": la coordenada ya está y falta su punto en el plano. */
function faltaElPunto() {
  const u = entradas.ubicacion ?? {};
  return Number.isFinite(u.lon) && Number.isFinite(u.lat) && !(Number.isFinite(u.x) && Number.isFinite(u.y));
}

/**
 * Lo que ella cambia dentro de un método lo deja elegido: en un KMZ de antes (sin
 * `entradas.metodo`, con el método deducido) quitar un punto podía pasar a ubicar con la
 * coordenada sin que se viera.
 */
function conMetodo(nuevas) {
  return metodoUbicar && nuevas.metodo !== metodoUbicar ? { ...nuevas, metodo: metodoUbicar } : nuevas;
}

/** Una tarjeta: se guarda el método y se ubica con lo que ese método ya tenía. */
function elegirMetodo(metodo) {
  if (!METODOS.includes(metodo) || paso !== 'ubicar') return;
  metodoUbicar = metodo;
  soltarFila();
  pistaSuelta = '';
  marcandoPunto = metodo === 'punto' && faltaElPunto();
  // El que ya se usaba (también el deducido de un KMZ de antes) no se guarda: lo ubicado sigue al día.
  const otro = cambiaElMetodo(entradas, metodo);
  if (otro) cambiar({ ...entradas, metodo }); else pintarPanel();
  if (giroDelPlano() !== lienzo.giro) lienzo.ponerGiro(giroDelPlano(), true);
  lienzo.redibujar();
  pintarMapa();
  // Con otro método lo ubicado quedó atrasado: se ubica con lo que este ya tenía.
  if (otro) programarUbicar();
  // La tarjeta apretada desaparece: el foco va a lo primero del método.
  const campo = metodo === 'punto' && !Number.isFinite(entradas.ubicacion?.lon) ? $('#kmz-ir-a')
    : metodo === 'puntos' && !entradas.anclas.length ? $('#kmz-ancla-coord') : $('#kmz-panel-ubicar h2');
  campo.focus();
}

/** Vuelve a las tarjetas sin borrar nada: `entradas.metodo` cambia al elegir otra. */
function cambiarDeMetodo() {
  metodoUbicar = null;
  soltarFila();
  marcandoPunto = false;
  pistaSuelta = '';
  if (giroDelPlano() !== lienzo.giro) lienzo.ponerGiro(giroDelPlano(), true);
  lienzo.redibujar();
  pintarPanel();
  pintarMapa();
  $('#kmz-metodos [data-metodo]:not([hidden])')?.focus();
}

/** "Ir a Marcar" del aviso de la escala: a Marcar, con la herramienta Escala en la mano. */
async function irAMarcarEscala() {
  await irAlPaso('marcar');
  if (paso === 'marcar') elegirHerramienta('escala');
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
      cuadroHoja = null;
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

const hayMarcas = () => Boolean(entradas.rectangulo || entradas.mascaras.length || entradas.cuadro || entradas.union?.cuadro || entradas.esquinas
  || entradas.escala || entradas.semillas.length || entradas.anclas.length || entradas.uniones?.length || hayUbicacion(entradas.ubicacion));

/** ¿Ya puso algo de la ubicación con un punto (la coordenada, el punto o la escala)? */
const hayUbicacion = (u) => Boolean(u) && ['x', 'lon', 'escala_impresa'].some((k) => u[k] != null);

async function elegirPagina(n) {
  if (n === entradas.pagina && plano.entradas) return;
  if (n !== entradas.pagina && hayMarcas()
    && !confirm(textoBorraLoMarcado(entradas.pagina, n))) return;
  // Sin nada marcado no hay qué perder, salvo la unión misma: armarla cuesta.
  if (n !== entradas.pagina && !hayMarcas() && conUnion()
    && !confirm('Elegir una página suelta quita la unión de las hojas. ¿Seguir?')) return;
  const limpio = n !== entradas.pagina;
  cuadroHoja = null;
  olvidarEscalaAMedias();
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
  // Los extremos a medias están en px de la página sin girar: se marcan de nuevo.
  olvidarEscalaAMedias();
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
    && !confirm(textoBorraLoMarcado(entradas.pagina, 0))) return;
  const antes = entradas;
  cuadroHoja = null;
  if (cambia) olvidarEscalaAMedias();
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
  if (hayMarcas() && !confirm(textoBorraLoMarcado(0, 1))) return undefined;
  editorUnion.cerrar();
  cuadroHoja = null;
  olvidarEscalaAMedias();
  cambiar({ ...VACIAS(), pagina: 1 });
  await mostrarPagina();
  return pintarPaso();
}

// --- 2. marcar -------------------------------------------------------------------------

function elegirHerramienta(nombre) {
  herramienta = nombre;
  // Con la unión, el cuadro se dibuja recién sobre su hoja: antes hay que elegirla.
  const sinHoja = nombre === 'cuadro' && conUnion() && cuadroHoja === null;
  lienzo.herramienta = HERRAMIENTAS_RECTANGULO.includes(nombre) && !sinHoja ? 'rectangulo' : 'mover';
  for (const boton of $$('button[data-herramienta]')) {
    boton.setAttribute('aria-pressed', String(boton.dataset.herramienta === nombre));
  }
  $('#kmz-plano').dataset.herramienta = sinHoja ? 'mover' : nombre;
  if (nombre !== 'escala') olvidarEscalaAMedias();
  if (nombre !== 'cuadro' && cuadroHoja !== null) {
    cuadroHoja = null;
    mostrarPagina().catch((error) => avisar(error.message));
  }
  pintarPanel();
  lienzo.redibujar();
}

/** Muestra la hoja `n` original, para encerrar en ella el cuadro de superficies. */
async function verHojaDelCuadro(n) {
  if (!conUnion() || !hojaDelCuadro(plano?.paginas, entradas.union, n)) return;
  cuadroHoja = n;
  elegirHerramienta('cuadro');
  await mostrarPagina();
}

function rectangulo(rect) {
  if (paso !== 'marcar') return;
  if (cuadroHoja !== null) {
    const hoja = hojaDelCuadro(plano?.paginas, entradas.union, cuadroHoja);
    if (!hoja) return;
    const dentro = cuadroEnHoja(rect, ...tamanoRotado(hoja.ancho, hoja.alto, hoja.rotacion));
    if (!dentro) return;
    cambiar({ ...entradas, union: { ...entradas.union, cuadro: { hoja: hoja.n, rect: dentro } } });
    // Listo el cuadro, de vuelta a la unión: todo lo demás se marca en ella.
    elegirHerramienta('mover');
    return;
  }
  const nuevas = marcarRectangulo(entradas, herramienta, rect);
  if (nuevas === entradas) return;
  const despues = herramientaTrasRectangulo(herramienta, entradas, nuevas);
  cambiar(nuevas);
  if (despues !== herramienta) elegirHerramienta(despues);
}

function tocarPlano(x, y, evento) {
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
  if (paso === 'marcar' && herramienta === 'escala') return marcarEscala(x, y, evento);
  if ((paso === 'marcar' && herramienta === 'numero') || paso === 'numerar') return abrirNumero(x, y);
  if (paso === 'ubicar') {
    // Con el mouse no hay clic sintetizado: un clic rápido en el mapa es de ella.
    if (evento?.pointerType && evento.pointerType !== 'mouse') tocadoEnPlano = performance.now();
    const destino = destinoDelClic(metodoUbicar, { marcandoPunto, esperaPlano: puntosAhora().activa?.espera === 'plano' });
    if (destino === 'punto') return ponerPunto(x, y);
    if (destino === 'ancla') return marcarEnPlano(x, y);
    return clicSuelto();
  }
  return undefined;
}

const round = (v) => Math.round(v * 10) / 10;

/**
 * Un extremo de la barra de escala. El tercer clic empieza otra línea: marcar de nuevo
 * reemplaza la escala al confirmar los metros. Uno pegado al primero no cuenta (el servidor
 * pide 10 px), así un doble clic no deja una línea de nada.
 */
function marcarEscala(x, y, evento) {
  const punto = [round(x), round(y)];
  if (escalaMarcando.length === 1) {
    const [p] = escalaMarcando;
    if (Math.hypot(punto[0] - p[0], punto[1] - p[1]) < ESCALA_LINEA_MIN_PX) return;
    escalaMarcando = [p, punto];
  } else {
    escalaMarcando = [punto];
  }
  cursorEscala = null;
  lienzo.redibujar();
  pintarPanel();
  if (escalaMarcando.length !== 2) return;
  if (!evento?.pointerType || evento.pointerType === 'mouse') {
    enfocarMetros();
    return;
  }
  // Al toque le sigue su clic. Si el foco desplaza la página antes, ese clic cae en lo que
  // quedó bajo el dedo (el campo 1:N). Se enfoca con el clic, que además es un gesto: así
  // el celular sí abre el teclado.
  let hecho = false;
  const una = () => { if (!hecho) { hecho = true; enfocarMetros(); } };
  window.addEventListener('click', una, { once: true });
  setTimeout(una, 500);
}

function enfocarMetros() {
  if (escalaMarcando.length !== 2 || paso !== 'marcar') return;
  const campo = $('#kmz-escala-metros-valor');
  campo.focus();
  campo.select();
  verEntero($('#kmz-escala-metros'));
}

/**
 * El foco deja ver el campo, pero no lo que sigue: en el panel con scroll "Usar" quedaba
 * cortado bajo el pie fijo. Se desplaza solo el panel, no la página (el plano no se mueve).
 */
function verEntero(nodo) {
  const panel = nodo.closest('.kmz-panel');
  if (!panel) return;
  const pie = panel.querySelector('.kmz-panel__pie');
  const limite = (pie && !pie.hidden ? pie.getBoundingClientRect().top : panel.getBoundingClientRect().bottom) - 8;
  const sobra = nodo.getBoundingClientRect().bottom - limite;
  if (sobra > 0) panel.scrollTop += sobra;
}

/** Los extremos sin confirmar son de la página que se veía: con otra página o giro no sirven. */
function olvidarEscalaAMedias() {
  escalaMarcando = [];
  cursorEscala = null;
}

/** El campo de los metros se esconde al guardar o cancelar: el foco no se pierde con él. */
function devolverFocoEscala() {
  if ($('#kmz-escala-metros').contains(document.activeElement)) $('button[data-herramienta="escala"]').focus();
}

function cancelarEscala() {
  devolverFocoEscala();
  olvidarEscalaAMedias();
  lienzo.redibujar();
  pintarPanel();
}

/** Con el mouse, la línea sigue al cursor mientras falta el segundo extremo. */
function pasarPorPlano(x, y) {
  if (paso !== 'marcar' || herramienta !== 'escala' || escalaMarcando.length !== 1) {
    if (cursorEscala) { cursorEscala = null; lienzo.redibujar(); }
    return;
  }
  cursorEscala = x == null ? null : [x, y];
  lienzo.redibujar();
}

// La escala no es de leer el plano (solo de ubicar): se guarda sin releerlo.
function usarEscalaLinea() {
  const [p, q] = escalaMarcando;
  const { escala, error } = escalaDesdeLinea(p, q, $('#kmz-escala-metros-valor').value);
  if (error) return avisar(error);
  avisar(null);
  devolverFocoEscala();
  olvidarEscalaAMedias();
  $('#kmz-escala-metros-valor').value = '';
  return cambiar({ ...entradas, escala });
}

function usarEscalaImpresa() {
  const n = leerEscala($('#kmz-escala-numero-valor').value);
  if (n === null || Number.isNaN(n)) {
    return avisar('Escribe la escala como dice el plano, por ejemplo 1:5.000 (entre 1:100 y 1:1.000.000).');
  }
  avisar(null);
  olvidarEscalaAMedias();
  return cambiar({ ...entradas, escala: { impresa: n } });
}

// --- 3. digitalizar ----------------------------------------------------------------------

function escuchar() {
  const mio = slug;
  oyentes.set(clave(mio), (trabajo) => {
    if (mio !== slug) return;
    const estaba = trabajando();
    if (trabajo.id && plano && !trabajo.terminado
      && (plano.trabajo?.id !== trabajo.id || plano.trabajo.terminado)) {
      // La consola retomó la lectura perdida con otro trabajo y `seguir` ya lo sigue. Si la
      // pantalla ya la había dado por interrumpida (la consola tardó más de un minuto en
      // volver), vuelve a leerse: el botón se esconde, que relanzarla chocaría con esta.
      plano = { ...plano, trabajo: { ...plano.trabajo, id: trabajo.id, estado: trabajo.estado, terminado: false } };
    } else if (trabajo.id && plano?.trabajo && plano.trabajo.id !== trabajo.id) {
      plano = { ...plano, trabajo: { ...plano.trabajo, id: trabajo.id } };
    }
    if (trabajo.interrumpido && plano?.trabajo) {
      // Se perdió con el servidor (`seguir`): el botón vuelve aunque el servidor todavía
      // no conteste para recargar el KMZ.
      plano = { ...plano, trabajo: { ...plano.trabajo, estado: 'falló', terminado: true } };
    }
    // Solo al pasar de "falló" a "leyendo": el panel (botón, aviso) cambia; cada tanda de
    // líneas no lo repinta entero.
    if (!estaba && trabajando()) pintar();
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
      if (enCamino) {
        await irAlPaso('digitalizar');
        return;
      }
      // Ya leído con esto mismo: no se lee de nuevo, se sigue a Numerar (si hace falta) o a Ubicar.
      if (desdeMarcar && plano?.digitalizado?.vigente) {
        await irAlPaso(pasoSiguiente('marcar', plano, rasgos));
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
    // Numerar es una pantalla intermedia: solo si falta algo de los números (`hayQueNumerar`).
    await irAlPaso(pasoSiguiente('digitalizar', plano, rasgos));
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
  // El número cuyas partes unidas se pueden separar: las del servidor (`unidas`) o las
  // recién unidas que aún esperan la relectura (`parte_de`), tocando el lote o una parte.
  const p = lote?.properties;
  const delLote = p?.parte_de ?? p?.numero;
  // Solo en Numerar: con la herramienta de número de Marcar no se une ni se separa.
  const conPartes = paso === 'numerar' && delLote != null && (p.parte_de != null || p.unidas > 0
    || rasgos.some((r) => r.properties.parte_de != null && claveLote(r.properties.parte_de) === claveLote(delLote)));
  numerando = { x: punto[0], y: punto[1], anillos: lote?.geometry.coordinates ?? null, lote, separar: conPartes ? delLote : null };
  $('#kmz-numero [data-accion="kmz-separar"]').hidden = !conPartes;
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
  const base = renumerarUniones(entradas, numero, anillos);
  cambiar({ ...(numero ? devolverAlKmz(base, anillos) : base), semillas });
}

function escribirNumero(valor) {
  if (!numerando) return;
  // Como lo dice el cuadro: "8-8" queda "8-08", que es como sale en el KMZ.
  const limpio = formaDelCuadro(valor, numerosCuadro());
  const { x, y, anillos } = numerando;
  // Si los lotes se releyeron con el cuadro abierto, el de la apertura ya no está en
  // `rasgos`: se busca de nuevo, o el lote se vería a sí mismo como "la parte de al lado".
  const lote = loteEn(rasgos, x, y) ?? numerando.lote;
  // Una parte ya unida a ese mismo número: no hay nada que cambiar.
  if (limpio && lote?.properties.parte_de != null && claveLote(lote.properties.parte_de) === claveLote(limpio)) {
    return cerrarNumero();
  }
  const pasar = () => {
    cerrarNumero();
    ponerEnLote(limpio, [x, y], anillos);
    lienzo.canvas.focus({ preventScroll: true });
  };
  if (limpio && preguntarUnir(limpio, [x, y], lote?.geometry.coordinates ?? anillos, lote, pasar)) return;
  const otra = entradas.semillas.find((s) => claveLote(s.numero) === claveLote(limpio)
    && !(anillos && puntoEnPoligono(s.x, s.y, anillos)));
  if (limpio && otra && !confirm(`El ${limpio} ya está marcado en otro lote. ¿Lo pasas a este?`)) return;
  pasar();
}

/** Confirma la lectura sugerida de la i-ésima parte con sugerencia: queda como número suyo. */
function confirmarSugerencia(i) {
  const s = sugerencias(rasgos)[i];
  if (!s) return;
  const numero = formaDelCuadro(s.numero, numerosCuadro());
  const pasar = () => ponerEnLote(numero, s.rasgo.rotulo, s.rasgo.geometry.coordinates);
  if (preguntarUnir(numero, s.rasgo.rotulo, s.rasgo.geometry.coordinates, s.rasgo, pasar)) return;
  const otra = entradas.semillas.find((x) => claveLote(x.numero) === claveLote(numero));
  if (otra && !confirm(`El ${numero} ya está marcado en otro lote. ¿Lo pasas a este?`)) return;
  pasar();
}

// --- unir las partes de un lote -----------------------------------------------------------

/** Lo que espera la respuesta del diálogo de unir: {slug, unir, pasar}. */
let unirPendiente = null;

/**
 * "Se tocan" en la pantalla: 0,5 mm de papel en px de página. Sin `ppmm` (una foto) se
 * supone una página dibujada a 200 ppp, como se dibujan los PDF: unos 4 px. Es solo para
 * decidir si se ofrece unir; si no se tocan de verdad, el servidor no las une y lo avisa.
 */
const tolUnir = () => 0.5 * (plano?.digitalizado?.pagina?.ppmm || 200 / 25.4);

/**
 * Si el número ya lo tiene otro lote (o una parte ya unida a él) que toca esta parte,
 * pregunta si unirlas o pasarle el número, y devuelve true. También cuando ese número
 * lo puso el lector y no ella: también es el mismo lote partido.
 */
function preguntarUnir(numero, punto, anillos, parte, pasar) {
  if (paso !== 'numerar' || !anillos || !loteConNumero(rasgos, numero, parte)) return false;
  const clave = claveLote(numero);
  const vecina = rasgos.some((r) => r !== parte && r.properties.numero != null && claveLote(r.properties.numero) === clave
    && seTocan(anillos, r.geometry.coordinates, tolUnir()));
  if (!vecina) return false;
  $('#kmz-unir-titulo').textContent = `El ${numero} ya está en la parte de al lado`;
  $('#kmz-unir-si').textContent = `Unirlas en el lote ${numero}`;
  $('#kmz-unir-pasar').textContent = `Pasar el ${numero} a esta parte`;
  unirPendiente = { slug, pasar, unir: () => unirEnLote(numero, punto, anillos) };
  abrirDialogo($('#kmz-unir-dialogo'));
  return true;
}

/** Suma la parte al lote `numero`: se ve al tiro y la relectura la trae ya fundida. */
function unirEnLote(numero, punto, anillos) {
  cerrarNumero();
  if (paso === 'numerar') {
    rasgos = aplicarUnion(rasgos, numero, punto);
    programarRelectura();
  }
  // Como al ponerle número: la parte vuelve al KMZ aunque la hubiera dejado fuera.
  cambiar(unirParte(devolverAlKmz(entradas, anillos), numero, punto, anillos));
  lienzo.canvas.focus({ preventScroll: true });
}

/** Quita las uniones del lote que está en el cuadro del número: al releer salen sus partes. */
async function separar() {
  const numero = numerando?.separar;
  if (numero == null) return;
  const mio = slug;
  const optimistas = rasgos.some((r) => r.properties.parte_de != null && claveLote(r.properties.parte_de) === claveLote(numero));
  cerrarNumero();
  cambiar(separarPartes(entradas, numero));
  programarRelectura();
  // Las partes recién unidas (aún sin releer) se ven unidas solo en la pantalla: los lotes
  // se traen de nuevo para que vuelvan a verse sueltas aunque no haga falta releer.
  if (!optimistas) return;
  await guardar();
  if (mio !== slug) return;
  await cargarLotes();
  pintarPanel();
}

/** El aviso de las uniones que no se aplicaron al leer el plano (los números de sus lotes). */
function textoUnionesDescartadas(numeros) {
  if (!numeros?.length) return '';
  if (numeros.length === 1) {
    return `No se pudo unir la parte del lote ${numeros[0]}: después de leer el plano ya no se toca con él.`;
  }
  const cuales = `${numeros.slice(0, -1).join(', ')} y ${numeros[numeros.length - 1]}`;
  return `No se pudieron unir las partes de los lotes ${cuales}: después de leer el plano ya no se tocan con ellos.`;
}

/**
 * Confirma de una vez todas las sugerencias, como si se apretara cada pastilla, pero en un
 * solo cambio y una sola relectura. Las que chocan con un número ya puesto (o entre ellas)
 * no se confirman: quedan en la lista para resolverlas a mano con su pastilla, que pregunta.
 */
function confirmarTodos() {
  const n = sugerencias(rasgos).length;
  if (!n) return;
  if (!confirm(`¿Confirmar los ${n} números sugeridos? Cada uno queda como número de su lote.`)) return;
  const r = confirmarSugerencias(entradas, rasgos, numerosCuadro());
  // `confirmadas` y `omitidas` son las listas de números; aquí basta cuántos.
  const confirmadas = r.confirmadas.length;
  const omitidas = r.omitidas.length;
  if (!confirmadas) {
    avisar('No se confirmó ninguno: sus números ya están en otros lotes. Confírmalos uno a uno.');
    return;
  }
  rasgos = r.rasgos;
  if (paso === 'numerar') programarRelectura();
  cambiar(r.entradas);
  if (omitidas) {
    const quedan = omitidas === 1
      ? '1 queda por confirmar porque su número ya está en otro lote.'
      : `${omitidas} quedan por confirmar porque su número ya está en otro lote.`;
    avisar(`Se ${confirmadas === 1 ? 'confirmó 1' : `confirmaron ${confirmadas}`}. ${quedan}`);
  }
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

/** Las filas de puntos como están ahora (cuál está hecha, cuál activa, qué se puede añadir). */
const puntosAhora = () => estadoDePuntos(entradas.anclas, pendiente);

/** Olvida la fila a medias y lo escrito en su campo (al cambiar de método, de paso o de KMZ). */
function soltarFila() {
  pendiente = null;
  $('#kmz-ancla-coord').value = '';
}

/** El clic en el plano de la fila que ya tiene su coordenada: el punto queda hecho. */
function marcarEnPlano(x, y) {
  if (!Number.isFinite(pendiente?.lat)) return;
  const ancla = anclaDesde({ nombre: pendiente.nombre, x: round(x), y: round(y) }, pendiente.lat, pendiente.lon);
  const viejo = entradas.anclas.find((a) => a.nombre === ancla.nombre);
  if (viejo && ['x', 'y', 'lat', 'lon'].every((k) => viejo[k] === ancla[k])) {
    // Rehecho igual que estaba: no es un cambio. Guardarlo dejaría `metodo` en un KMZ de
    // antes y lo ubicado atrasado sin que nada cambie (como "Ir" con la misma coordenada).
    cancelarAncla();
    return;
  }
  pendiente = null;
  $('#kmz-ancla-coord').value = '';
  avisoCuadricula = '';
  // Al rehacer, el punto queda en su lugar de la lista (no se va al final).
  const ya = Boolean(viejo);
  const anclas = ya ? entradas.anclas.map((a) => (a.nombre === ancla.nombre ? ancla : a)) : [...entradas.anclas, ancla];
  cambiar(conMetodo({ ...entradas, anclas }));
  // Desde el segundo punto los lotes ya se ven (vista previa); el servidor llega después.
  pintarMapa(anclas.length === 2 && !ya);
  if (puedeUbicar(entradas)) ubicar().catch((e) => avisar(e.message));
  // Con el punto hecho, lo que sigue es "Añadir" (o nada, con 4): el foco no se pierde en el aire.
  const anadir = $('[data-accion="kmz-anadir-punto"]');
  if (document.activeElement === document.body || !document.activeElement) (anadir.hidden ? $('#kmz-panel-ubicar h2') : anadir).focus({ preventScroll: true });
}

/** Un clic en el plano de Ubicar sin nada que marcar: se dice cómo, sin marcar nada. */
function clicSuelto() {
  pistaSuelta = textoClicSuelto(metodoUbicar, entradas.ubicacion, puntosAhora());
  pintarPanel();
}

/**
 * Un clic en el mapa con varios puntos o la cuadrícula: mientras la fila activa espera su
 * coordenada (o el clic en el plano, para corregirla) el clic es esa coordenada. Con "un
 * punto" o en las tarjetas es mirar, no marcar.
 */
function marcarEnMapa(lat, lon) {
  if (paso !== 'ubicar' || destinoDelClic(metodoUbicar, { esperaPlano: true }) !== 'ancla') return;
  const { activa } = puntosAhora();
  if (!activa) {
    pistaSuelta = textoClicSuelto(metodoUbicar, entradas.ubicacion, puntosAhora());
    pintarPanel();
    return;
  }
  ponerCoordenada(activa.nombre, lat, lon);
  $('#kmz-ancla-coord').value = coordenadaDelCampo(pendiente.lat, pendiente.lon);
}

/** La fila activa ya tiene su coordenada: el alfiler en el mapa y a esperar el clic en el plano. */
function ponerCoordenada(nombre, lat, lon) {
  pendiente = { nombre, lat: Number(lat.toFixed(7)), lon: Number(lon.toFixed(7)) };
  pistaSuelta = '';
  lienzo.redibujar();
  pintarPanel();
  pintarMapa();
}

/** "Añadir B": abre la fila de la letra que sigue, vacía y esperando su coordenada. */
function anadirPunto() {
  const { anadir } = puntosAhora();
  if (!anadir || paso !== 'ubicar') return;
  pendiente = { nombre: anadir };
  pistaSuelta = '';
  $('#kmz-ancla-coord').value = '';
  pintarPanel();
  enfocarFilaActiva();
}

/** El foco al campo de la fila activa, con la fila entera a la vista dentro del panel. */
function enfocarFilaActiva({ seleccionar = false } = {}) {
  const campo = $('#kmz-ancla-coord');
  campo.focus({ preventScroll: true });
  if (seleccionar) campo.select();
  $('#kmz-punto-activo').scrollIntoView({ block: 'nearest' });
}

/** "Rehacer": la fila vuelve a pedir coordenada (la que tenía, ya escrita) y el clic en el plano. */
function rehacerAncla(nombre) {
  const ancla = entradas.anclas.find((a) => a.nombre === nombre);
  if (!ancla || (pendiente && pendiente.nombre !== nombre)) return;
  pendiente = { nombre };
  pistaSuelta = '';
  $('#kmz-ancla-coord').value = coordenadaDelCampo(ancla.lat, ancla.lon);
  lienzo.redibujar();
  pintarPanel();
  pintarMapa();
  enfocarFilaActiva({ seleccionar: true });
}

/** Esc o "Cancelar": se deshace lo a medias; un punto que se rehacía queda como estaba. */
function cancelarAncla() {
  const nombre = pendiente?.nombre;
  const enCampo = $('#kmz-punto-activo').contains(document.activeElement);
  soltarFila();
  lienzo.redibujar();
  pintarPanel();
  pintarMapa();
  // La fila activa se fue (o volvió a ser A vacía) con el foco adentro: no se pierde en el aire.
  if (enCampo || document.activeElement === document.body) enfocarTrasFila(nombre);
}

/**
 * El foco cuando la fila en que estaba desaparece: al Rehacer de ese punto (si sigue), a la
 * fila A vacía, a "Añadir" o, sin nada de eso, al título del panel.
 */
function enfocarTrasFila(nombre) {
  const rehacer = nombre && [...document.querySelectorAll('[data-ancla-rehacer]')].find((b) => b.dataset.anclaRehacer === nombre);
  if (rehacer) return rehacer.focus();
  if (!$('#kmz-punto-activo').hidden) return enfocarFilaActiva();
  const anadir = $('[data-accion="kmz-anadir-punto"]');
  return (anadir.hidden ? $('#kmz-panel-ubicar h2') : anadir).focus();
}

function quitarAncla(nombre) {
  if (!entradas.anclas.some((a) => a.nombre === nombre)) return;
  if (pendiente?.nombre === nombre) soltarFila();
  cambiar(conMetodo({ ...entradas, anclas: entradas.anclas.filter((a) => a.nombre !== nombre) }));
  pintarMapa();
  if (puedeUbicar(entradas)) ubicar().catch((e) => avisar(e.message));
  // Su botón se fue con la fila. No se pasa al Quitar de al lado: otro Enter borraría otro punto.
  if (document.activeElement === document.body || !document.activeElement) enfocarTrasFila(null);
}

const NO_UBICO_CUADRICULA = 'No se pudo ubicar con la cuadrícula del plano. Marca los puntos a mano.';

/** Elegir la cuadrícula ubica al tiro. Si no ubica con ella (error, o el servidor cayó a
 * las anclas), se quita sola y se dice: así no queda elegida algo que no sirve. */
async function usarCuadricula(si) {
  const propuesta = plano?.digitalizado?.lector?.cuadricula;
  if (si && !propuesta) return;
  const mio = slug;
  avisoCuadricula = '';
  const nuevas = conMetodo({ ...entradas });
  if (si) nuevas.cuadricula = propuesta; else delete nuevas.cuadricula;
  cambiar(nuevas);
  if (!si) {
    if (puedeUbicar(entradas)) await ubicar();
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
  // Sin la cuadrícula, a marcar los puntos a mano: lo que dice el aviso.
  const sinCuadricula = { ...entradas, metodo: 'puntos' };
  delete sinCuadricula.cuadricula;
  metodoUbicar = 'puntos';
  cambiar(sinCuadricula);
  avisoCuadricula = NO_UBICO_CUADRICULA;
  cuadriculaNoSirve = true;
  if (puedeUbicar(entradas)) await ubicar().catch((e) => avisar(e.message));
  else await guardar();
  pintarPanel();
}

function moverAjuste(de, dn) {
  const paso1 = Number($('#kmz-paso-ajuste').value) || 1;
  const ajuste = de === null ? { de: 0, dn: 0 } : empujar(entradas.ajuste, de * paso1, dn * paso1);
  cambiar({ ...entradas, ajuste });
  // Con la vista previa los lotes se mueven al tiro; varias flechas seguidas son un solo cálculo.
  pintarMapa();
  programarUbicar();
}

function arrastreDelMapa(de, dn) {
  cambiar({ ...entradas, ajuste: empujar(entradas.ajuste, de, dn) });
  if (vistaPrevia()) {
    // Los lotes ya quedan donde se soltaron (vista previa): el servidor, un momento después.
    pintarMapa();
    programarUbicar();
    return;
  }
  // Si no se pudo recalcular, los lotes no se quedan corridos con el arrastre a medias.
  ubicar().catch((e) => avisar(e.message)).finally(() => pintarMapa());
}

// --- ubicar con un punto ------------------------------------------------------------------
//
// La coordenada (alfiler en el mapa), su punto en el plano y el giro van en
// `entradas.ubicacion`. Cada cambio se ve al tiro con la vista previa (la misma similitud
// del servidor, calculada aquí) y, un momento después del último, se guarda y se ubica en
// el servidor: girar con el deslizador es una ráfaga de cambios y un solo cálculo.

const UBICAR_MS = 600;

function cambiarUbicacion(cambios, { encuadrar = false } = {}) {
  const ubicacion = { giro: 0, escala_impresa: null, ...(entradas.ubicacion ?? {}), ...cambios };
  cambiar(conMetodo({ ...entradas, ubicacion }));
  lienzo.ponerGiro(giroDelPlano());
  pintarMapa(encuadrar && Boolean(vistaPrevia()));
  programarUbicar();
}

function ponerPunto(x, y) {
  marcandoPunto = false;
  pistaSuelta = '';
  // La primera vez que hay lotes que ver, el mapa se acerca a ellos.
  cambiarUbicacion({ x: round(x), y: round(y) }, { encuadrar: !vistaPrevia() });
}

/** Gira el plano a `grados` (horario), al décimo de grado y dentro de −180..180. */
function girarA(grados) {
  if (!Number.isFinite(grados)) return;
  // Se redondea después de normalizar: el módulo deja colas como 89.29999999999995.
  cambiarUbicacion({ giro: Math.round(normalizarGiro(grados) * 10) / 10 });
  // Al girar, los lotes barren en torno al punto y se salen del mapa (en Rapel, a 89°
  // quedaban abajo, fuera de la vista): al soltar, el mapa los vuelve a mostrar.
  clearTimeout(seguirLuego);
  seguirLuego = setTimeout(() => { seguirLuego = 0; if (paso === 'ubicar') mapa?.seguirLotes(); }, UBICAR_MS);
}
let seguirLuego = 0;

/** El giro con que se muestra el plano: el de la ubicación, y solo en Ubicar con un punto. */
const giroDelPlano = () => (paso === 'ubicar' && metodoUbicar === 'punto' ? entradas.ubicacion?.giro ?? 0 : 0);

/** Ubica en el servidor un momento después del último cambio, si hay con qué. */
function programarUbicar() {
  clearTimeout(ubicarLuego);
  ubicarLuego = 0;
  if (!puedeUbicar(entradas) || !plano?.digitalizado?.vigente) return;
  // Con la coordenada y sin escala el servidor solo diría lo que ya dice la línea bajo "Seguir".
  if (usaUbicacion(entradas) && !escalaDeUbicacion(plano.digitalizado, entradas.ubicacion, entradas.escala)) return;
  ubicarLuego = setTimeout(() => {
    ubicarLuego = 0;
    ubicar().catch((e) => avisar(e.message));
  }, UBICAR_MS);
  pintarPorQue();
}

/**
 * Los lotes sobre el mapa calculados aquí (GeoJSON lon/lat), con lo mismo que usará el
 * servidor: 2 o más puntos, o la coordenada con su punto y la escala. Con la cuadrícula
 * elegida no hay vista previa (esa la calcula solo el servidor).
 */
function vistaPrevia() {
  const d = plano?.digitalizado;
  if (!d || !rasgos.length || metodoVigente(entradas) === 'cuadricula') return null;
  const hoja = d.pagina;
  if (hoja && (hoja.numero !== entradas.pagina || hoja.rotacion !== entradas.rotacion)) return null;
  // Con 2 o más puntos mandan ellos (`por_anclas`), como en el servidor; si no, la coordenada.
  // Con "Ajustar el tamaño con el cuadro", el tamaño del cuadro, como en el servidor: si no,
  // los lotes saltarían al soltar el último cambio.
  const ajuste = ajustaConElCuadro(entradas) && d.escala_m_px > 0
    ? { escalaMPx: d.escala_m_px, homografiaTrabajo: d.homografia } : {};
  const t = usaAnclas(entradas)
    ? similitudPorAnclas(entradas.anclas, d.perspectiva ? d.homografia : null, ajuste)
    : usaUbicacion(entradas) && similitudPorPunto(entradas.ubicacion, escalaDeUbicacion(d, entradas.ubicacion, entradas.escala), d.homografia);
  return t ? lotesEnElMapa(rasgos, t, entradas.ajuste) : null;
}

/**
 * "Ajustar el tamaño con el cuadro" (o deshacerlo): los puntos dejan la posición y el giro,
 * el cuadro de superficies el tamaño. Ubica de nuevo al tiro, que trae los lotes al día.
 */
async function ajustarConElCuadro(ajustar) {
  if (ajustandoCuadro) return;
  ajustandoCuadro = true;
  try {
    cambiar({ ...entradas, escala_cuadro: ajustar });
    await ubicar();
  } finally {
    ajustandoCuadro = false;
    pintarPanel();
  }
}

/**
 * En el panel `raiz`: el botón de ajustar (Revisar y el semáforo, si hay `sesgo`) y la línea
 * "Tamaño ajustado con el cuadro · Deshacer el ajuste" (Revisar y Ubicar). Devuelve si se
 * ofrece ajustar.
 */
function pintarAjusteDelCuadro(raiz, sesgo = null) {
  const conCuadro = plano?.digitalizado?.escala_m_px > 0;
  const ajustado = ajustaConElCuadro(entradas) && conCuadro;
  for (const p of $$('.kmz-ajustado', raiz)) p.hidden = !ajustado;
  for (const b of $$('[data-accion="kmz-deshacer-cuadro"]', raiz)) b.disabled = ajustandoCuadro;
  // Mientras ajusta, el botón sigue a la vista (apagado) en vez de desaparecer de golpe.
  // El sesgo es de lo ubicado: si la ubicación quedó atrasada, ajustar sería sobre lotes viejos.
  const vigente = Boolean(plano?.georreferencia?.vigente);
  const ofrecer = (vigente && ofrecerAjusteDelCuadro(entradas, sesgo) || (ajustandoCuadro && entradas.escala_cuadro))
    && conCuadro;
  for (const b of $$('[data-accion="kmz-ajustar-cuadro"]', raiz)) {
    b.hidden = !ofrecer;
    b.disabled = ajustandoCuadro;
    b.textContent = ajustandoCuadro && entradas.escala_cuadro ? 'Ajustando el tamaño…' : 'Ajustar el tamaño con el cuadro';
  }
  return Boolean(ofrecer);
}

/** Devuelve si de verdad ubicó (no corre con el digitalizado atrasado o sin con qué). */
async function ubicar() {
  clearTimeout(ubicarLuego);
  ubicarLuego = 0;
  const mio = slug;
  const vez = ++ubicarVez;
  // "Seguir" espera desde ya: mientras se guarda, `plano` aún dice vigente lo ubicado antes
  // del último giro, y se podía pasar a Revisar con eso.
  ubicandoYa = true;
  pintarPorQue();
  // Al girar seguido se encadenan varias: solo la última suelta "Seguir" y pinta lo suyo.
  const vigenteYo = () => mio === slug && vez === ubicarVez;
  const soltar = () => { if (vez === ubicarVez) { ubicandoYa = false; pintarPorQue(); } };
  try {
    await guardar();
  } catch (error) {
    soltar();
    throw error;
  }
  // Se pasó a otro KMZ mientras se guardaba: ubicar ese no lo pidió nadie.
  if (!vigenteYo() || !plano?.digitalizado?.vigente || !puedeUbicar(entradas)) {
    soltar();
    return false;
  }
  $('#kmz-ancla-estado').textContent = 'Ubicando…';
  let nuevo;
  let geo;
  try {
    const georreferencia = await pedir(`${api(mio)}/georreferenciar`, json({}));
    if (!vigenteYo()) return false;
    plano.georreferencia = georreferencia;
    nuevo = await pedir(api(mio));
    geo = await pedir(`${api(mio)}/lotes?en=lonlat`);
  } catch (error) {
    if (!vigenteYo()) return false;
    $('#kmz-ancla-estado').textContent = '';
    throw error;
  } finally {
    soltar();
  }
  if (!vigenteYo()) return false;
  plano = nuevo;
  rasgosGeo = geo;
  pintar();
  pintarMapa();
  return true;
}

const NO_ENTENDI = `No entendí esas coordenadas. Escríbelas como -34.98, -71.24 o como 34°10'37.5"S 71°32'53.9"W.`;

/** "Ir": la coordenada que tiene es el paso 1 de ubicar con un punto. Queda el alfiler y
 * se guarda, y el próximo clic en el plano es su punto (paso 2), sin otro botón. Si la
 * coordenada es la misma y su punto ya está, no se pide de nuevo. */
async function irA() {
  const punto = leerCoordenadas($('#kmz-ir-a').value);
  if (!punto) throw new Error(NO_ENTENDI);
  const mio = slug;
  await prepararMapa();
  // La primera vez el mapa tarda en cargar: si entretanto se cambió de KMZ, de paso o de
  // método, la coordenada ya no es de lo que está en pantalla.
  if (mio !== slug || paso !== 'ubicar' || metodoUbicar !== 'punto') return;
  mapa.ir(punto.lat, punto.lon, 17);
  const lon = Number(punto.lon.toFixed(7));
  const lat = Number(punto.lat.toFixed(7));
  const u = entradas.ubicacion ?? {};
  const misma = u.lon === lon && u.lat === lat;
  pistaSuelta = '';
  // La misma coordenada: Ir solo vuelve a mostrarla (y, sin su punto, lo pide). Guardarla
  // otra vez dejaría `metodo` en un KMZ de antes y lo ubicado atrasado sin que cambie nada.
  if (misma) {
    if (!Number.isFinite(u.x)) marcandoPunto = true;
    lienzo.redibujar();
    pintarPanel();
    if (marcandoPunto) llevarAlPlano();
    return;
  }
  marcandoPunto = true;
  cambiarUbicacion({ lon, lat });
  lienzo.redibujar();
  llevarAlPlano(Number.isFinite(u.x) ? [u.x, u.y] : null);
}

/**
 * Tras "Ir" toca el clic en el plano (con un punto y con varios). En pantalla angosta el
 * plano queda bajo el panel, fuera de la vista: se baja hasta él. `centro` (px de página):
 * dónde estaba el punto que se corrige, para que se vea al llegar.
 */
function llevarAlPlano(centro = null) {
  if (centro && Number.isFinite(centro[0]) && Number.isFinite(centro[1])) lienzo.centrar(centro[0], centro[1]);
  if (!window.matchMedia('(max-width: 70rem)').matches) return;
  const caja = $('#kmz-plano');
  const { top, bottom } = caja.getBoundingClientRect();
  // La barra de arriba está fija: lo que queda debajo de ella tampoco se ve.
  const arriba = document.querySelector('.barra')?.getBoundingClientRect().bottom ?? 0;
  if (top >= arriba && bottom <= window.innerHeight) return;
  const quieto = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  caja.scrollIntoView({ block: 'center', behavior: quieto ? 'auto' : 'smooth' });
}

/**
 * "Ir" de la fila activa: el mapa va a la coordenada escrita, con su alfiler, y el próximo
 * clic en el plano completa el punto. Otra coordenada estando ya en el plano la corrige.
 */
async function irAncla() {
  const { activa } = puntosAhora();
  if (!activa) return;
  const punto = leerCoordenadas($('#kmz-ancla-coord').value);
  if (!punto) throw new Error(NO_ENTENDI);
  const [mio, metodo] = [slug, metodoUbicar];
  await prepararMapa();
  // Si mientras cargaba el mapa se cambió de KMZ, de paso, de método o de fila, esta
  // coordenada ya no es de la fila que está en pantalla.
  if (mio !== slug || paso !== 'ubicar' || metodo !== metodoUbicar || puntosAhora().activa?.nombre !== activa.nombre) return;
  mapa.ir(punto.lat, punto.lon, 17);
  ponerCoordenada(activa.nombre, punto.lat, punto.lon);
  // Al rehacer, el plano se centra donde estaba el punto: ahí se corrige.
  const antes = entradas.anclas.find((a) => a.nombre === activa.nombre);
  llevarAlPlano(antes ? [antes.x, antes.y] : null);
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
      if (omitir || error.estado !== 409 || !(error.cuerpo?.sin_numero || error.cuerpo?.resto)) throw error;
      if (mio !== slug) return;
      sinNumeroPendiente = mio;
      // Solo el resto sin decidir: se nombra como la pregunta que es, no como lotes sin número.
      const soloResto = !error.cuerpo.sin_numero;
      $('#kmz-sin-numero-titulo').textContent = soloResto ? 'Falta decidir el resto de la propiedad'
        : 'Quedan lotes sin número';
      $('#kmz-crear-sin-numero').textContent = soloResto ? 'Crear sin el resto' : 'Crear sin ellos';
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
    $('#kmz-listo-texto').dataset.alDia = String(plano.paso === 'listo');
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
  // Crear está en el pie y el aviso arriba en el panel: se trae a la vista.
  listo.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
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
  $('#kmz-cuerpo').classList.toggle('kmz-cuerpo--solo', paso === 'subir' && !plano?.pdf);
  if (paso !== 'marcar') elegirHerramienta('mover');
  else if (pasoPintado !== 'marcar') elegirHerramienta(herramientaAlEntrar(entradas, Boolean(plano?.digitalizado)));
  if (paso === 'ubicar' && pasoPintado !== 'ubicar') {
    metodoUbicar = metodoAlEntrar(entradas, Boolean(propuestaCuadricula()));
    // Con un punto, la coordenada puesta y sin su punto en el plano: el clic en el plano es ese.
    marcandoPunto = metodoUbicar === 'punto' && faltaElPunto();
  }
  if (paso !== 'ubicar') {
    marcandoPunto = false;
    pistaSuelta = '';
  }
  // En Ubicar el plano se ve girado como el mapa; al entrar o salir se vuelve a encuadrar.
  if (giroDelPlano() !== lienzo.giro) lienzo.ponerGiro(giroDelPlano(), true);
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
  // Leyendo el plano o numerando, la pastilla marcada es Marcar: son parte de ese paso.
  const actual = pastillaDe(paso);
  for (const boton of $$('#kmz-pasos [data-paso]')) {
    const nombre = boton.dataset.paso;
    if (!PASTILLAS.includes(nombre)) continue;
    boton.disabled = !habilitados[nombre];
    boton.classList.toggle('paso--hecho', Boolean(hechos[nombre]));
    if (nombre === actual) boton.setAttribute('aria-current', 'step'); else boton.removeAttribute('aria-current');
  }
}

/** El texto y los controles del paso abierto. */
function pintarPanel() {
  if (!plano) return;
  const d = plano.digitalizado;
  // En Numerar no: ahí los lotes se releen solos y el panel dice "Actualizando los lotes…".
  const atrasado = Boolean(d && !d.vigente) && ['digitalizar', 'ubicar'].includes(paso);
  $('#kmz-atrasado').hidden = !atrasado || trabajando();
  // Fuera de Marcar también: al cambiar de paso, la pregunta por la hoja se va.
  pintarCuadroHoja();
  if (paso === 'subir') pintarSubir();
  if (paso === 'marcar') pintarMarcar();
  if (paso === 'digitalizar') pintarDigitalizar();
  if (paso === 'numerar') pintarNumerar();
  if (paso === 'ubicar') pintarUbicar();
  else $('#kmz-giro-mapa').hidden = true;
  if (paso === 'revisar') pintarRevisar();
  pintarPorQue();
}

/** El "Seguir" del paso abierto: se apaga con su motivo debajo, en una línea. */
function pintarPorQue() {
  const panel = $(`#kmz-panel-${paso}`);
  // En Revisar y descargar no hay "Seguir": el motivo es el de Crear (que apaga `pintarCrear`).
  const boton = panel?.querySelector('[data-accion="kmz-siguiente"]');
  const linea = panel?.querySelector('.kmz-por-que');
  if (!plano || (!boton && !linea)) return;
  // Mientras se pide la lectura, el servidor todavía no la cuenta como trabajo: ya lo es.
  const e = lanzando === slug ? { ...plano, trabajo: { terminado: false } } : plano;
  const motivo = porQueNoSigue(paso, e, {
    entradas, actualizando: actualizando(), releerFallo, ubicando: ubicandoYa || Boolean(ubicarLuego),
    duplicados: paso === 'revisar' ? resumenRevision(rasgosGeo?.features ?? []).duplicados : 0,
  });
  if (boton) boton.disabled = Boolean(motivo);
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
  const miniatura = (n, src, texto) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'hoja';
    boton.dataset.pagina = n;
    boton.setAttribute('aria-pressed', String(n === entradas.pagina));
    const imagen = document.createElement('img');
    imagen.src = src;
    imagen.alt = '';
    imagen.loading = 'lazy';
    const span = document.createElement('span');
    span.textContent = texto;
    boton.append(imagen, span);
    return boton;
  };
  // La unión guardada es la "página 0": va primera, y elegir otra la quita (`elegirPagina`).
  const unida = conUnion() && plano.union;
  const miniaturas = unida
    ? [miniatura(0, `${api()}/paginas/0?mini=1&v=${version}-${plano.union.huella}`,
      `${textoHojasUnidas(plano.union.hojas)} · ${plano.union.ancho}×${plano.union.alto} px`)]
    : [];
  lista.replaceChildren(...miniaturas, ...plano.paginas.map((hoja) => miniatura(hoja.n,
    `${api()}/paginas/${hoja.n}?mini=1&v=${version}`, `Página ${hoja.n} · ${hoja.ancho}×${hoja.alto} px`)));
  // La unión no se gira entera: cada hoja lleva su giro en el editor.
  $('#kmz-giro-caja').hidden = Boolean(unida);
  $('#kmz-giro-union').hidden = !unida;
  $('#kmz-rotacion').textContent = `${entradas.rotacion ?? 0}°`;
  $('#kmz-unir-caja').hidden = plano.paginas.length < 2;
  $('[data-accion="kmz-unir"]').textContent = unida ? 'Editar la unión' : 'El loteo está en varias hojas: unirlas';
}

function pintarMarcar() {
  const foto = $('#kmz-es-foto').checked;
  $('button[data-herramienta="esquinas"]').hidden = !foto;
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
  const escala = textoEscala(entradas.escala);
  if (escala) filas.push(fila(escala, { quitarEscala: '1' }));
  const cuadroUnion = conUnion() ? entradas.union.cuadro : null;
  if (cuadroUnion) filas.push(fila(`Cuadro de superficies (hoja ${cuadroUnion.hoja})`, { quitarCuadro: '1' }));
  for (const s of entradas.semillas) filas.push(fila(`Lote ${s.numero}`, { quitarSemilla: s.numero }));
  lista.replaceChildren(...filas);
  pintarEscalaMarcar();
  const listo = Boolean(entradas.rectangulo) && (!sinLector || entradas.semillas.length > 0);
  $('#kmz-marcar-nota').textContent = listo ? '' : !entradas.rectangulo
    ? 'Encierra el dibujo del loteo con la herramienta "Encerrar el dibujo".'
    : 'Marca el número de al menos un lote antes de leer el plano.';
}

/** El bloque de la herramienta Escala: la pista, los metros de la línea o la escala 1:N. */
function pintarEscalaMarcar() {
  const caja = $('#kmz-escala-marcar');
  caja.hidden = herramienta !== 'escala';
  if (caja.hidden) return;
  const marcados = escalaMarcando.length;
  $('#kmz-escala-metros').hidden = marcados < 2;
  const actual = textoEscala(entradas.escala);
  // En celular no hay Esc: tocar otra herramienta es lo que cancela.
  const conTeclado = window.matchMedia?.('(hover: hover)').matches;
  $('#kmz-escala-pista').textContent = marcados === 1 ? `Ahora haz clic en el otro extremo de la barra${conTeclado ? ' (Esc cancela)' : ''}.`
    : marcados === 2 ? 'Escribe cuánto mide la línea, como dice la barra del plano.'
      : actual ? `${actual}. Para cambiarla, haz clic en los dos extremos de la barra de escala del plano.`
        : 'Haz clic en los dos extremos de la barra de escala del plano.';
  const campo = $('#kmz-escala-numero-valor');
  if (document.activeElement !== campo) {
    const n = entradas.escala?.impresa;
    campo.value = n ? new Intl.NumberFormat('es-CL').format(n) : '';
  }
}

/** Con la unión y la herramienta del cuadro: la pregunta por la hoja, o la hoja que se ve. */
function pintarCuadroHoja() {
  const caja = $('#kmz-cuadro-hoja');
  const visible = paso === 'marcar' && herramienta === 'cuadro' && conUnion();
  caja.hidden = !visible;
  if (!visible) return;
  const eligiendo = cuadroHoja === null;
  $('#kmz-cuadro-hoja-texto').textContent = eligiendo
    ? '¿En qué hoja está el cuadro?'
    : `Hoja ${cuadroHoja}: encierra el cuadro de superficies.`;
  const hojas = [...entradas.union.hojas].map((h) => h.n).sort((a, b) => a - b);
  $('#kmz-cuadro-hojas').replaceChildren(...(eligiendo ? hojas : []).map((n) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'boton boton--contorno boton--chico';
    boton.dataset.cuadroHoja = String(n);
    boton.textContent = `Hoja ${n}`;
    return boton;
  }));
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
  // "Seguir" dice adónde lleva cuando ya se sabe: Numerar es intermedio y se salta si no hace
  // falta. Mientras se lee (o con una lectura vieja) todavía no se sabe.
  $('#kmz-panel-digitalizar [data-accion="kmz-siguiente"]').textContent = leyendo || !d?.vigente ? 'Seguir'
    : pasoSiguiente('digitalizar', plano, rasgos) === 'numerar' ? 'Seguir: revisar los números' : 'Seguir: ubicar en el mapa';
  const cifras = $('#kmz-cifras');
  cifras.hidden = !d;
  if (!d) return;
  const lector = d.lector;
  const lineas = [
    ['Lotes', d.lotes],
    ['Lotes sin número', d.sin_numero_lote ?? 0],
    ['Otras partes sin número', d.sin_numero - (d.sin_numero_lote ?? 0) - (d.resto_pendiente ? 1 : 0)],
    ...(d.resto_pendiente ? [['Resto de la propiedad', 'sin decidir']] : []),
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
  const descartadas = $('#kmz-uniones-descartadas');
  descartadas.textContent = textoUnionesDescartadas(d?.uniones_descartadas);
  descartadas.hidden = !descartadas.textContent;
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
  // Con una sola basta su pastilla: el botón de todas es para cuando son varias.
  const todos = $('[data-accion="kmz-confirmar-todos"]');
  todos.hidden = porConfirmar.length < 2;
  todos.textContent = `Confirmar todos (${porConfirmar.length})`;
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
  const metodo = metodoUbicar;
  const propuesta = propuestaCuadricula();

  // Sin método en pantalla, las tarjetas; con él, "Método: … · Cambiar de método".
  $('#kmz-metodos').hidden = Boolean(metodo);
  $('#kmz-ubicar-ayuda').hidden = Boolean(metodo);
  const ofrecidos = metodosOfrecidos({ propuesta: Boolean(propuesta), elegida: Boolean(entradas.cuadricula) });
  // Al volver con "Cambiar de método", se ve cuál es el que usa ahora.
  const enUso = metodoAlEntrar(entradas, Boolean(propuesta));
  for (const tarjeta of $$('#kmz-metodos [data-metodo]')) {
    tarjeta.hidden = !ofrecidos.includes(tarjeta.dataset.metodo);
    const actual = tarjeta.dataset.metodo === enUso;
    tarjeta.classList.toggle('kmz-metodo--actual', actual);
    tarjeta.querySelector('.kmz-metodo__actual').hidden = !actual;
  }
  $('#kmz-metodo-elegido').hidden = !metodo;
  $('#kmz-metodo-nombre').textContent = metodo ? NOMBRES_METODO[metodo] : '';
  $('#kmz-con-punto').hidden = metodo !== 'punto';
  const conPuntos = metodo === 'puntos' || metodo === 'cuadricula';
  $('#kmz-con-puntos').hidden = !conPuntos;
  pintarGuia();
  const pista = $('#kmz-pista');
  pista.textContent = pistaSuelta;
  pista.hidden = !pista.textContent;

  $('#kmz-cuadricula').hidden = metodo !== 'cuadricula';
  $('[data-accion="kmz-usar-cuadricula"]').hidden = Boolean(entradas.cuadricula) || !propuesta;
  $('[data-accion="kmz-quitar-cuadricula"]').hidden = !entradas.cuadricula;
  $('#kmz-cuadricula-texto').textContent = entradas.cuadricula
    ? 'Se está usando la cuadrícula impresa en el plano. Puedes sumar puntos para comprobar que calza.'
    : 'El plano trae una cuadrícula con coordenadas impresas: es lo más preciso para ubicarlo.';
  $('#kmz-puntos-titulo').hidden = metodo !== 'cuadricula';
  if (conPuntos) pintarPuntos(g, vigente, metodo === 'cuadricula');

  // Lo ubicado y el ajuste fino van con un método a la vista (en las tarjetas, solo elegir).
  const resumen = $('#kmz-ubicacion');
  resumen.hidden = !g || !metodo;
  pintarAjusteDelCuadro(resumen);
  if (g) {
    const texto = $('#kmz-ubicacion-texto');
    texto.textContent = (vigente ? '' : 'Antes de tus últimos cambios: ') + resumenUbicacion(g, entradas.anclas.length);
    // Lo técnico (sistema de coordenadas, error medio) queda a mano para el topógrafo.
    texto.title = detalleUbicacion(g);
    $('#kmz-avisos').replaceChildren(...avisosDeUbicacion(g).map((texto) => {
      const li = document.createElement('li');
      li.textContent = texto;
      return li;
    }));
  }
  $('#kmz-ajuste-fino').hidden = !metodo;
  const ajuste = entradas.ajuste ?? { de: 0, dn: 0 };
  const signo = (v) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(1)}`;
  $('#kmz-ajuste').textContent = `Este ${signo(ajuste.de)} m · Norte ${signo(ajuste.dn)} m`;
  const arrastre = $('[data-accion="kmz-arrastrar"]');
  arrastre.setAttribute('aria-pressed', String(arrastrar));
  arrastre.textContent = arrastrar ? 'Arrastrando los lotes (clic para dejar de arrastrar)' : 'Arrastrar los lotes';
  // Con la vista previa ya hay lotes que mover, aunque el servidor todavía no ubique.
  const hayLotes = Boolean(g) || Boolean(vistaPrevia());
  for (const b of $$('#kmz-ajuste-fino button')) b.disabled = !hayLotes;
  $('[data-accion="kmz-georreferenciar"]').disabled = !plano.digitalizado?.vigente
    || !puedeUbicar(entradas);
}

/**
 * Las filas A..D de "varios puntos" (y las de comprobar la cuadrícula). Las hechas se
 * rehacen en cada repintado; la activa es siempre el mismo <li> de index.html, que se deja
 * en su lugar entre ellas (al final, o donde está el punto que se rehace).
 */
function pintarPuntos(g, vigente, cuadricula) {
  const estadoPuntos = puntosAhora();
  const { activa, anadir } = estadoPuntos;
  const enCurso = Boolean(pendiente);
  $('#kmz-ancla-estado').textContent = avisoCuadricula && !enCurso ? avisoCuadricula
    : guiaDePuntos(estadoPuntos.hechas, { cuadricula });

  const lista = $('#kmz-puntos');
  const filaActiva = $('#kmz-punto-activo');
  for (const li of lista.querySelectorAll('.kmz-fila-punto--hecha')) li.remove();
  filaActiva.hidden = !activa;
  if (activa) {
    filaActiva.querySelector('.kmz-fila-punto__letra').textContent = activa.nombre;
    filaActiva.dataset.espera = activa.espera;
    $('#kmz-ancla-etiqueta').textContent = activa.rehace ? `Punto ${activa.nombre}: de nuevo` : `Punto ${activa.nombre}`;
    const paso1 = $('#kmz-ancla-paso');
    const texto = textoFilaActiva(activa);
    if (paso1.textContent !== texto) paso1.textContent = texto;
    filaActiva.querySelector('[data-accion="kmz-cancelar-ancla"]').hidden = !estadoPuntos.cancelable;
  }

  // Los puntos con su distancia: cuánto se aleja cada uno de donde lo dejan los demás.
  const porNombre = new Map((g?.anclas ?? []).map((a) => [a.nombre, a]));
  let antes = true;
  for (const fila of estadoPuntos.filas) {
    if (fila.activa) { antes = false; continue; }
    const li = filaHecha(fila.ancla, porNombre.get(fila.nombre), g, vigente, enCurso);
    if (antes && activa) lista.insertBefore(li, filaActiva); else lista.append(li);
  }

  const boton = $('[data-accion="kmz-anadir-punto"]');
  boton.hidden = !anadir;
  if (anadir) boton.textContent = `Añadir ${anadir}`;
}

/** Una fila de un punto hecho: su letra, la coordenada, cuánto se aleja, si calza, y qué hacer. */
function filaHecha(a, r, g, vigente, enCurso) {
  const li = document.createElement('li');
  li.className = 'kmz-fila-punto kmz-fila-punto--hecha';
  const { distancia, estado: estadoFila, detalle } = filaDelPunto(r, g, vigente);
  if (detalle) li.classList.add('kmz-atipica');
  const span = (clase, texto = '') => {
    const s = document.createElement('span');
    s.className = clase;
    s.textContent = texto;
    return s;
  };
  const letra = span('kmz-fila-punto__letra', a.nombre);
  letra.title = a.nombre;
  letra.setAttribute('aria-hidden', 'true');
  // La coordenada en su línea y lo demás abajo, junto a los botones (ver .kmz-fila-punto).
  const coord = span('kmz-fila-punto__coord');
  coord.append(span('oculto', `Punto ${a.nombre}: `), document.createTextNode(coordenadaCorta(a.lat, a.lon)));
  const datos = span('kmz-fila-punto__datos');
  if (distancia !== '—') {
    const dist = span('kmz-fila-punto__dist');
    dist.title = 'Cuánto se aleja de donde lo dejan los demás puntos';
    dist.append(span('oculto', 'a '), document.createTextNode(distancia));
    datos.append(dist);
  }
  if (estadoFila) {
    const celda = span('kmz-fila-punto__estado', estadoFila);
    // En el celular no da para la frase entera: "No calza" se ve, y lo que hay que hacer va
    // en el título y para el lector de pantalla (la lista de avisos lo repite).
    if (detalle) {
      celda.title = `${estadoFila}: ${detalle}`;
      celda.append(span('oculto', `: ${detalle}`));
    }
    datos.append(celda);
  }
  const acciones = span('kmz-fila-punto__acciones');
  for (const [texto, clave] of [['Rehacer', 'anclaRehacer'], ['Quitar', 'anclaQuitar']]) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'boton boton--texto boton--chico';
    b.textContent = texto;
    b.dataset[clave] = a.nombre;
    b.setAttribute('aria-label', `${texto} el punto ${a.nombre}`);
    // Con otra fila a medias no se abre una segunda: primero se termina o se cancela.
    if (clave === 'anclaRehacer' && enCurso) continue;
    acciones.append(b);
  }
  li.append(letra, coord, datos, acciones);
  return li;
}

const grados = (g) => `${new Intl.NumberFormat('es-CL', { maximumFractionDigits: 1 }).format(g)}°`;

/** Los tres pasos de "un punto y girar": qué ya está, qué toca, el giro y de dónde sale el tamaño. */
function pintarGuia() {
  const u = entradas.ubicacion ?? {};
  const coordenada = Number.isFinite(u.lon) && Number.isFinite(u.lat);
  const punto = Number.isFinite(u.x) && Number.isFinite(u.y);
  const conPunto = metodoUbicar === 'punto';
  const d = plano.digitalizado;
  const escala = escalaDeUbicacion(d, u, entradas.escala);
  const estado = (li, hecho, ahora) => {
    if (hecho) li.dataset.estado = 'hecho'; else if (ahora) li.dataset.estado = 'ahora'; else delete li.dataset.estado;
  };
  estado($('#kmz-guia-coordenada'), coordenada, !coordenada && !marcandoPunto);
  estado($('#kmz-guia-punto'), punto && !marcandoPunto, marcandoPunto || (coordenada && !punto));
  estado($('#kmz-guia-giro'), false, coordenada && punto && !marcandoPunto && Boolean(escala));

  const textoCoordenada = $('#kmz-coordenada-estado');
  textoCoordenada.hidden = !coordenada;
  if (coordenada) {
    textoCoordenada.textContent = `Tu coordenada: ${u.lat.toFixed(6)}, ${u.lon.toFixed(6)} (el alfiler naranja del mapa).`;
  }

  const textoPunto = $('#kmz-punto-estado');
  const boton = $('[data-accion="kmz-marcar-punto"]');
  boton.setAttribute('aria-pressed', String(marcandoPunto));
  if (marcandoPunto) {
    textoPunto.textContent = 'Ahora haz clic en el plano donde está tu coordenada (acerca bien). Esc cancela.';
    boton.textContent = 'Cancelar';
  } else if (punto) {
    textoPunto.textContent = 'Listo: es la marca naranja del plano.';
    boton.textContent = 'Mover el punto';
  } else {
    textoPunto.textContent = '';
    boton.textContent = 'Marcar el punto en el plano';
  }

  // El giro aparece con lo que gira: la coordenada y su punto.
  const conGiro = coordenada && punto;
  $('#kmz-guia-giro .kmz-giro').hidden = !conGiro;
  $('#kmz-giro-espera').hidden = conGiro;
  const giro = u.giro ?? 0;
  const deslizador = $('#kmz-giro');
  if (Number(deslizador.value) !== giro) deslizador.value = String(giro);
  // Con el sentido en palabras: "−20° como el reloj" se lee al revés.
  const textoGiro = giro ? `${grados(Math.abs(giro))} ${giro > 0 ? 'como el reloj' : 'contra el reloj'}` : '0° (sin girar)';
  deslizador.setAttribute('aria-valuetext', textoGiro);
  $('#kmz-giro-valor').textContent = textoGiro;
  // El del mapa, mientras hay lotes de la vista previa que girar.
  $('#kmz-giro-mapa').hidden = paso !== 'ubicar' || !conPunto || !vistaPrevia();
  $('#kmz-giro-mapa-valor').textContent = grados(giro);

  // El tamaño sale de la escala: sin ella se dice dónde marcarla; con ella, de cuál sale.
  $('#kmz-sin-escala').hidden = !d || Boolean(escala);
  const origen = $('#kmz-origen-escala');
  // Con lo ubicado al día lo dice su aviso, justo abajo: no se repite.
  origen.textContent = notaDeEscalaVisible(plano.georreferencia) ? origenDeEscala(d, u, entradas.escala) ?? '' : '';
  origen.hidden = !origen.textContent;
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
    ...(cuenta.resto_pendiente ? [['Resto de la propiedad', 'sin decidir', 'ambar']] : []),
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
  // El semáforo y el botón de crear van en este mismo panel: el sesgo y si se ofrece ajustar
  // salen de ahí, para que la nota y el semáforo no se contradigan.
  const { luz, ajustable } = pintarCrear();
  const sesgo = luz.sesgo ?? sesgoDeEscala(rasgosGeo?.features ?? []);
  // El semáforo ya dice cuántos calzan y, si salen parejo distintos, qué hacer: la nota no lo repite.
  const conSemaforo = Boolean(luz.tono);
  $('#kmz-revision-nota').textContent = problemas
    ? 'Hay números repetidos: el KMZ no se puede crear así. Corrígelos en "Revisar los números".'
    : cuenta.resto_pendiente
      ? (cuenta.sin_numero_lote
        ? `${cuenta.sin_numero_lote === 1 ? 'Un lote quedó' : `${cuenta.sin_numero_lote} lotes quedaron`} sin número`
          + ' y falta decidir si el resto de la propiedad va en el KMZ: Revisar los números.'
        : 'Falta decidir si el resto de la propiedad va en el KMZ: Revisar los números.')
    : cuenta.sin_numero_lote
      ? (cuenta.sin_numero_lote === 1 ? 'Un lote quedó sin número y no iría al KMZ. Ponle su número'
        : `${cuenta.sin_numero_lote} lotes quedaron sin número y no irían al KMZ. Ponles su número`)
        + ' en "Revisar los números".'
    : cuenta.sin_numero
      ? (cuenta.sin_numero === 1 ? 'Una parte queda sin número (rayada en rojo) y no va al KMZ.'
        : `${cuenta.sin_numero} partes quedan sin número (rayadas en rojo) y no van al KMZ.`)
        + ' Si es un lote, ponle su número en "Revisar los números".'
      : cuenta.lotes === cuenta.gris
      ? (entradas.cuadro || entradas.union?.cuadro
        ? 'No se leyó el cuadro de superficies: revisa a ojo que los lotes calcen con los caminos.'
        : 'Sin cuadro de superficies no hay áreas oficiales: si el plano lo trae, enciérralo en Marcar'
          + ` con "Cuadro de superficies"${conUnion() ? ' (en la hoja donde está)' : ''}.`
          + ' Si no, revisa a ojo que los lotes calcen con los caminos.')
      : sesgo != null && !conSemaforo
      ? `Casi todos los lotes salen cerca de un ${Math.abs(sesgo * 100).toFixed(1).replace('.', ',')} %`
        + ` ${sesgo > 0 ? 'más grandes' : 'más chicos'} que el oficial: suele ser la escala de los puntos de Ubicar,`
        + (ajustable ? ' no el dibujo. Ajusta el tamaño con el cuadro de superficies, o vuelve a Ubicar y marca'
          + ' 3 o 4 esquinas con coordenadas exactas.'
          : ' no el dibujo. Vuelve a Ubicar y marca 3 o 4 esquinas con coordenadas exactas.')
      : cuenta.rojo
      ? 'Los rojos tienen un área muy distinta a la oficial: suelen ser lotes mal separados.'
      : conSemaforo ? '' : 'Ningún lote se aparta más de un 5 % del área oficial.';
  $('#kmz-revision-nota').hidden = !$('#kmz-revision-nota').textContent;
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

/**
 * La parte de crear del panel Revisar y descargar: el semáforo (con "Ajustar el tamaño con
 * el cuadro" y "Volver a Ubicar"), el botón de crear y, si ya hay un KMZ, descargarlo o
 * usarlo en un master. Devuelve el semáforo (`luz`) y si se ofrece ajustar.
 */
function pintarCrear() {
  if (!plano) return { luz: { tono: null }, ajustable: false };
  const hay = terminado();
  const ubicado = pasosHabilitados(plano).revisar;
  $('#kmz-crear-texto').textContent = plano.paso === 'listo'
    ? 'El KMZ ya está creado con lo último que ubicaste.'
    : hay ? 'Ya hay un KMZ creado de antes: crearlo de nuevo lo reemplaza con lo último que ubicaste.'
      : 'Un polígono por lote, con su número. Después lo descargas o lo usas en un master.';
  const crear = $('[data-accion="kmz-crear"]');
  const creando = creandoKmz === slug;
  // Con números repetidos el servidor no lo crea: el motivo queda bajo el botón (`porQueNoSigue`).
  const repetidos = resumenRevision(rasgosGeo?.features ?? []).duplicados;
  crear.disabled = creando || !ubicado || Boolean(repetidos);
  // Con los lotes en lon/lat (se cargan con el plano ubicado): sin ellos no hay con qué
  // comparar y el semáforo queda oculto, como sin cuadro.
  // Sin la ubicación vigente no se puede crear: los desvíos serían de los puntos viejos.
  const luz = semaforo(ubicado ? rasgosGeo?.features ?? [] : []);
  const panel = $('#kmz-panel-revisar');
  const ajustable = pintarAjusteDelCuadro(panel, luz.sesgo);
  const caja = $('#kmz-semaforo');
  const texto = textoSemaforo(luz, { ajustable });
  caja.hidden = !texto;
  caja.dataset.tono = luz.tono ?? '';
  // Solo si cambia: reescribir el mismo texto en una región `status` lo vuelve a anunciar
  // cada vez que algo repinta el panel.
  if ($('#kmz-semaforo-texto').textContent !== texto) $('#kmz-semaforo-texto').textContent = texto;
  $('[data-accion="kmz-volver-ubicar"]').hidden = luz.tono !== 'ambar';
  $('#kmz-semaforo-acciones').hidden = luz.tono !== 'ambar' && !ajustable;
  // Ámbar avisa pero no bloquea: el botón dice que se crea igual. Con el KMZ ya creado
  // con esto mismo no hay "igual" que valga: ya se creó, y rehacerlo da lo mismo.
  const igual = luz.tono === 'ambar' && plano.paso !== 'listo';
  crear.textContent = creando ? 'Creando el KMZ…' : igual ? 'Crear el KMZ igual'
    : hay ? 'Crear el KMZ de nuevo' : 'Crear el KMZ';
  if (creando) crear.setAttribute('aria-busy', 'true'); else crear.removeAttribute('aria-busy');
  crear.className = hay ? 'boton boton--contorno' : 'boton';
  // Descargar y usar sirven mientras haya un KMZ hecho, aunque esté por rehacerse.
  $('#kmz-listo').hidden = !hay;
  $('#kmz-descargar').hidden = !hay;
  $('#kmz-descargar').href = descargaDe(slug);
  // Se escribe de nuevo cuando el KMZ pasa de al día a atrasado o al revés: si no, tras
  // "Ajustar el tamaño con el cuadro" seguía diciendo "Listo: está creado" con un KMZ que
  // no tiene el ajuste. Mientras siga al día, queda el de recién creado (con la hora).
  const listoTexto = $('#kmz-listo-texto');
  const alDia = String(plano.paso === 'listo');
  if (hay && (!listoTexto.textContent || listoTexto.dataset.alDia !== alDia)) {
    listoTexto.textContent = alDia === 'true'
      ? `Listo: el KMZ "${plano.nombre}" está creado.`
      : `El KMZ "${plano.nombre}" que creaste antes sigue disponible, pero sin tus últimos cambios:`
        + ' créalo de nuevo para que los tenga.';
    listoTexto.dataset.alDia = alDia;
  }
  return { luz, ajustable };
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
  // Como en el plano: lo del método a la vista (en las tarjetas, el que usa).
  const metodo = metodoUbicar ?? metodoVigente(entradas);
  const conAnclas = paso === 'ubicar' && metodo !== 'punto';
  mapa.ponerAnclas(conAnclas ? entradas.anclas : [], g?.vigente ? g.atipicas ?? [] : [], conAnclas ? pendiente?.nombre : null);
  // El alfiler: la coordenada de "un punto", o la de la fila de puntos que espera el plano.
  const u = paso === 'ubicar' && metodo === 'punto' ? entradas.ubicacion
    : conAnclas && Number.isFinite(pendiente?.lat) ? pendiente : null;
  mapa.ponerAlfiler(u?.lat, u?.lon, u && u === pendiente ? pendiente.nombre : '');
  const revisando = paso === 'revisar';
  // En Ubicar, con la coordenada, los lotes son los de la vista previa: siguen al giro y al
  // arrastre sin esperar al servidor (que da lo mismo al terminar).
  const previa = paso === 'ubicar' ? vistaPrevia() : null;
  mapa.ponerLotes(previa ?? rasgosGeo, revisando ? 'nivel' : 'contorno', revisando && !corrigiendo ? ficha : null);
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

  // Una hoja original (para el cuadro de la unión): lo demás está en px de la unión.
  if (cuadroHoja !== null) {
    const c = entradas.union?.cuadro;
    if (c?.hoja === cuadroHoja) pintarCuadro(ctx, P, c.rect, `Cuadro de superficies (hoja ${c.hoja})`);
    return;
  }

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
    // Puede estar fuera del dibujo: se lee igual (los lotes y sus áreas oficiales). El de
    // la unión no se pinta aquí: está en px de su hoja, no de la unión.
    if (entradas.cuadro && !conUnion()) pintarCuadro(ctx, P, entradas.cuadro, 'Cuadro de superficies');
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

  // La escala: la que se está marcando reemplaza a la guardada.
  if (paso === 'marcar') {
    const [p, q] = escalaMarcando;
    if (p && (q || cursorEscala)) pintarEscala(ctx, P, p, q ?? cursorEscala, null, true);
    if (p) punto(ctx, P(...p), COLOR_ESCALA);
    if (q) punto(ctx, P(...q), COLOR_ESCALA);
    const e = entradas.escala;
    if (!p && e?.p && e?.q) pintarEscala(ctx, P, e.p, e.q, textoMetros(e.metros), false);
  }

  // Los lotes digitalizados, si son de esta página y esta rotación.
  const calzan = calzaLoDigitalizado(plano.digitalizado?.pagina, entradas, plano.union?.huella);
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

  // Las anclas, o el punto de la coordenada: lo del método a la vista (en las tarjetas, el que usa).
  if (paso === 'ubicar') {
    const g = plano.georreferencia;
    const metodo = metodoUbicar ?? metodoVigente(entradas);
    const anclas = metodo === 'punto' ? [] : entradas.anclas;
    for (const a of anclas) {
      const mala = g?.vigente && g.atipicas?.includes(a.nombre);
      // El que se rehace, en naranja: es el de la fila activa.
      const activa = pendiente?.nombre === a.nombre;
      const color = activa ? '#ea580c' : mala ? '#dc2626' : '#2563eb';
      const q = P(a.x, a.y);
      mira(ctx, q, color);
      etiqueta(ctx, a.nombre, q[0] + 10, q[1] - 10, activa ? '#c2410c' : mala ? '#dc2626' : '#1d4ed8', 'left');
    }
    const u = metodo === 'punto' ? entradas.ubicacion : null;
    if (Number.isFinite(u?.x) && Number.isFinite(u?.y)) {
      const q = P(u.x, u.y);
      mira(ctx, q, '#ea580c');
      etiqueta(ctx, 'Tu coordenada', q[0] + 10, q[1] + 6, '#c2410c', 'left');
    }
  }
}

const COLOR_ESCALA = '#0e7490';

/** La barra de escala: la línea con una marca en cada extremo y, encima, cuánto mide. */
function pintarEscala(ctx, P, p, q, texto, provisional) {
  const [a, b] = P(...p);
  const [c, d] = P(...q);
  const largo = Math.hypot(c - a, d - b) || 1;
  // La normal que apunta hacia arriba en pantalla: ahí van las marcas y la etiqueta.
  let [nx, ny] = [(b - d) / largo, (c - a) / largo];
  if (ny > 0) [nx, ny] = [-nx, -ny];
  ctx.save();
  ctx.lineCap = 'round';
  ctx.setLineDash(provisional ? [6, 4] : []);
  for (const [ancho, color] of [[5, 'rgb(255 255 255 / 0.9)'], [2, COLOR_ESCALA]]) {
    ctx.lineWidth = ancho;
    ctx.strokeStyle = color;
    ctx.beginPath();
    ctx.moveTo(a, b);
    ctx.lineTo(c, d);
    for (const [x, y] of [[a, b], [c, d]]) {
      ctx.moveTo(x + nx * 9, y + ny * 9);
      ctx.lineTo(x - nx * 9, y - ny * 9);
    }
    ctx.stroke();
  }
  ctx.restore();
  if (texto) etiqueta(ctx, texto, (a + c) / 2 + nx * 16, (b + d) / 2 + ny * 16, COLOR_ESCALA, 'center');
}

function pintarCuadro(ctx, P, [x0, y0, x1, y1], texto) {
  const [a, b] = P(x0, y0);
  const [c, d] = P(x1, y1);
  ctx.fillStyle = 'rgb(217 119 6 / 0.14)';
  ctx.fillRect(a, b, c - a, d - b);
  ctx.strokeStyle = '#d97706';
  ctx.lineWidth = 2;
  ctx.strokeRect(a, b, c - a, d - b);
  etiqueta(ctx, texto, a + 4, b + 4, '#b45309', 'left');
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
