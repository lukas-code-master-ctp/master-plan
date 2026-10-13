/**
 * Recoger archivos del navegador y subirlos a un loteo.
 *
 * Lo usan Nuevo master y el diálogo de "Subir archivos". Las rutas relativas se
 * conservan (`POSICION 01/DJI_0001.JPG`): el pipeline usa esas carpetas para
 * saber de qué posición de vuelo es cada toma.
 */

export const UTILES = /\.(kmz|jpe?g|xlsx|csv|json)$/i;
export const esKmz = (ruta) => /\.kmz$/i.test(ruta);
export const esFoto = (ruta) => /\.jpe?g$/i.test(ruta);
export const esPlanilla = (ruta) => /\.(xlsx|csv)$/i.test(ruta);

/** Quita el nombre de la carpeta que se eligió: dentro del proyecto no aporta. */
export function sinRaiz(ruta) {
  const partes = ruta.split('/');
  return partes.length > 1 ? partes.slice(1).join('/') : ruta;
}

/** Lo que eligió un `<input type=file>`, con su ruta dentro de la carpeta. */
export function desdeEntrada(entrada) {
  return [...entrada.files].map(
    (archivo) => ({ archivo, ruta: sinRaiz(archivo.webkitRelativePath || archivo.name) }));
}

/** Lo que se soltó: archivos sueltos o carpetas enteras, recorridas. */
export async function desdeSoltar(evento) {
  const entradas = [...evento.dataTransfer.items]
    .map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
  const encontrados = [];
  for (const raiz of entradas) await recorrer(raiz, '', encontrados);
  return encontrados;
}

async function recorrer(entrada, prefijo, encontrados) {
  if (entrada.isFile) {
    const archivo = await new Promise((ok, mal) => entrada.file(ok, mal));
    if (!archivo.name.startsWith('.')) encontrados.push({ archivo, ruta: prefijo + archivo.name });
    return;
  }
  const lector = entrada.createReader();
  for (;;) {
    const tanda = await new Promise((ok, mal) => lector.readEntries(ok, mal));
    if (!tanda.length) return;
    // La raíz que se soltó no cuenta como carpeta: sus hijos van en la primera capa.
    for (const hija of tanda) await recorrer(hija, prefijo ? `${prefijo}${entrada.name}/` : '', encontrados);
  }
}

/** Hace de un soltadero una zona que reacciona al arrastrar encima. */
export function soltadero(nodo, alSoltar) {
  for (const evento of ['dragenter', 'dragover']) {
    nodo.addEventListener(evento, (e) => { e.preventDefault(); nodo.classList.add('soltadero--encima'); });
  }
  for (const evento of ['dragleave', 'drop']) {
    nodo.addEventListener(evento, () => nodo.classList.remove('soltadero--encima'));
  }
  nodo.addEventListener('drop', async (evento) => {
    evento.preventDefault();
    alSoltar(await desdeSoltar(evento));
  });
}

export const megas = (lista) => lista.reduce((total, { archivo }) => total + archivo.size, 0) / 1048576;

// Cuánto lleva cada pedido de la subida. El servidor recibe un pedido entero en su
// memoria antes de guardarlo (Cloud Run no tiene disco): un vuelo de gigas en un solo
// pedido, sumado a una construcción corriendo, la dejaba sin memoria. El servidor
// rechaza los de más de 512 MB (MAX_CUERPO_MB en consola/app.py).
const TANDA_MB = 256;

// El KMZ primero: la subida exige que el loteo ya lo tenga. Después lo chico.
const prioridad = ({ ruta }) => (esKmz(ruta) ? 0 : esFoto(ruta) ? 2 : 1);

/**
 * Los archivos repartidos en tandas de hasta `topeMb`, con el KMZ en la primera.
 * Un archivo más grande que el tope va solo: lo que no quepa lo rechaza el servidor.
 */
export function tandas(lista, topeMb = TANDA_MB) {
  const tope = topeMb * 1048576;
  const ordenados = [...lista].sort((a, b) => prioridad(a) - prioridad(b));
  const grupos = [];
  let actual = [];
  let peso = 0;
  for (const elegido of ordenados) {
    if (actual.length && peso + elegido.archivo.size > tope) {
      grupos.push(actual);
      actual = [];
      peso = 0;
    }
    actual.push(elegido);
    peso += elegido.archivo.size;
  }
  if (actual.length) grupos.push(actual);
  return grupos;
}

/**
 * Sube archivos a un loteo, de a una tanda por pedido. Devuelve el loteo como quedó.
 * `alAvanzar` recibe la fracción de todo lo que hay que subir, no de cada tanda.
 */
export async function subir(slug, lista, alAvanzar = () => {}) {
  const total = lista.reduce((suma, { archivo }) => suma + archivo.size, 0) || 1;
  let enviado = 0;
  let loteo = null;
  for (const grupo of tandas(lista)) {
    const peso = grupo.reduce((suma, { archivo }) => suma + archivo.size, 0);
    loteo = await subirTanda(slug, grupo, (fraccion) => alAvanzar((enviado + fraccion * peso) / total));
    enviado += peso;
  }
  return loteo;
}

/** Una tanda en un pedido. XHR y no fetch: es la única forma de ver el avance de una subida. */
function subirTanda(slug, lista, alAvanzar) {
  const cuerpo = new FormData();
  for (const { archivo, ruta } of lista) cuerpo.append('archivos', archivo, ruta);

  return new Promise((ok, mal) => {
    const peticion = new XMLHttpRequest();
    peticion.open('POST', `/api/proyectos/${slug}/archivos`);
    peticion.upload.addEventListener('progress', (evento) => {
      if (evento.lengthComputable) alAvanzar(evento.loaded / evento.total);
    });
    peticion.addEventListener('load', () => {
      let cuerpoRespuesta = {};
      try { cuerpoRespuesta = JSON.parse(peticion.responseText); } catch { /* sin cuerpo */ }
      if (peticion.status === 201) return ok(cuerpoRespuesta);
      return mal(new Error(cuerpoRespuesta.detail ?? `Error ${peticion.status}`));
    });
    peticion.addEventListener('error', () => mal(new Error('Se cortó la subida. Revisa la conexión y vuelve a intentarlo.')));
    peticion.send(cuerpo);
  });
}
