/**
 * Mis KMZ (`#/kmz`): los KMZ que la loteadora arma desde el plano aprobado, sin
 * master. La lista, el diálogo del nombre (nuevo y renombrar) y el de "usar un KMZ
 * en un master", que se abre desde tres lados:
 *
 *  - Revisar y descargar, el paso 4 de un KMZ: elegir un master existente o "Nuevo master con este KMZ";
 *  - el detalle de un master: elegir uno de los KMZ terminados;
 *  - (Nuevo master tiene su propia lista de terminados, en el formulario.)
 *
 * Usar un KMZ es `POST /api/proyectos/<master>/kmz {kmz}`. Si el master ya tiene uno,
 * el servidor contesta 409 con `existentes`: se pide confirmar nombrándolos y se
 * repite con `confirmar_reemplazo`. El anterior queda como `.anterior`.
 */
import { $, abrirDialogo, avisar, estado, fecha, json, pastilla, pedir } from './comun.js';

let refrescar = async () => {};

// --- lo que no necesita la página ---------------------------------------------------

/** En qué va un KMZ, en palabras: los pasos del servidor (`paso`). */
export const PASO_EN_PALABRAS = {
  subir: 'Falta subir el plano',
  marcar: 'Falta marcar el dibujo',
  digitalizar: 'Falta leer el plano',
  ubicar: 'Falta ubicarlo en el mapa',
  crear: 'Falta crear el KMZ',
  listo: 'KMZ creado',
};

/** Lo que dice la tarjeta de un KMZ sobre su avance. */
export function pasoEnPalabras(kmz) {
  if (kmz?.trabajo) return 'Leyendo el plano…';
  return PASO_EN_PALABRAS[kmz?.paso] ?? PASO_EN_PALABRAS.subir;
}

/** Los que se pueden usar en un master: los que ya tienen su `.kmz`. */
export const terminados = (kmzs) => (kmzs ?? []).filter((k) => k.terminado);

/** "1 lote", "12 lotes"; nada si todavía no se digitalizó. */
export function cuantosLotes(n) {
  if (n == null) return null;
  return `${n} ${n === 1 ? 'lote' : 'lotes'}`;
}

// En 24 horas: es-CL sale con "a. m." si no se le pide el ciclo.
const HORA = new Intl.DateTimeFormat('es-CL', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

/** El aviso al crear el KMZ. Lleva la hora para que crearlo de nuevo se note aunque
 *  el resto del texto no cambie. */
export function textoDeCreado(nombre, lotes, cuando = new Date()) {
  const cuantos = cuantosLotes(lotes);
  return `Listo: el KMZ "${nombre}" quedó creado${cuantos ? ` con ${cuantos}` : ''} a las ${HORA.format(cuando)}.`;
}

/** Lo que se dice al terminar de poner un KMZ en un master. */
export function textoDeUso(respuesta, master) {
  const lotes = cuantosLotes(respuesta.lotes);
  return `Listo: ${master} ya tiene el KMZ${lotes ? ` (${lotes})` : ''}.`
    + (respuesta.anteriores?.length ? ` El anterior quedó como ${respuesta.anteriores.join(', ')}.` : '')
    + ' Ahora sube las panorámicas si faltan y construye.';
}

const rutaDelKmz = (slug) => `/api/kmz/${encodeURIComponent(slug)}`;
export const descargaDe = (slug) => `${rutaDelKmz(slug)}/descargar`;

// --- preparar --------------------------------------------------------------------------

export function prepararKmzs(opciones) {
  refrescar = opciones.refrescar;
  $('#kmzs-nuevo').addEventListener('click', () => abrirNombre());

  $('#kmzs').addEventListener('click', (evento) => {
    const nodo = evento.target.closest('[data-renombrar], [data-borrar], [data-usar]');
    if (!nodo) return;
    const kmz = estado.kmzs.find((k) => k.slug === (nodo.dataset.renombrar ?? nodo.dataset.borrar ?? nodo.dataset.usar));
    if (!kmz) return;
    avisar(null);
    if (nodo.dataset.renombrar) abrirNombre(kmz);
    else if (nodo.dataset.borrar) borrar(kmz).catch((error) => avisar(error.message));
    else abrirUsarKmz(kmz);
  });

  $('#kmz-nombre-form').addEventListener('submit', (evento) => {
    evento.preventDefault();
    guardarNombre().catch((error) => avisar(error.message));
  });
  $('#kmz-usar-listo').addEventListener('click', () => usarElegido().catch((error) => avisar(error.message)));
  $('#kmz-usar-opciones').addEventListener('change', pintarUsar);
  $('#kmz-reemplazar').addEventListener('click', () => {
    const pendiente = reemplazo;
    reemplazo = null;
    $('#kmz-reemplazo').close();
    if (pendiente) usarEnMaster(pendiente.kmz, pendiente.master, true).catch((error) => avisar(error.message));
  });
}

// --- la lista --------------------------------------------------------------------------

export function pintarKmzs() {
  document.title = 'Mis KMZ — Tu Masterplan';
  const lista = $('#kmzs');
  if (!estado.kmzs.length) {
    lista.innerHTML = `<li class="vacio"><strong>Todavía no tienes KMZ</strong>
      <span>Créalo desde el plano aprobado del SAG con <b>Nuevo KMZ</b>.</span></li>`;
    return;
  }
  lista.replaceChildren(...estado.kmzs.map(tarjeta));
}

function tarjeta(kmz) {
  const item = document.createElement('li');
  item.className = 'mi-kmz';

  const enlace = document.createElement('a');
  enlace.className = 'mi-kmz__abrir';
  enlace.href = `#/kmz/${encodeURIComponent(kmz.slug)}`;
  const titulo = document.createElement('span');
  titulo.className = 'mi-kmz__titulo';
  const nombre = document.createElement('strong');
  nombre.className = 'mi-kmz__nombre';
  nombre.textContent = kmz.nombre;
  titulo.append(nombre);
  if (kmz.terminado) titulo.append(pastilla('Listo', 'ok'));
  if (kmz.trabajo) titulo.append(pastilla('Leyendo el plano…', 'curso'));
  const detalle = document.createElement('span');
  detalle.className = 'mi-kmz__detalle';
  // Terminado y al día no repite "KMZ creado": ya lo dice la pastilla.
  const avance = kmz.terminado && kmz.paso === 'listo' ? null : kmz.trabajo ? null : pasoEnPalabras(kmz);
  detalle.textContent = [avance, cuantosLotes(kmz.lotes), `creado ${fecha(kmz.creado_en)}`]
    .filter(Boolean).join(' · ');
  enlace.append(titulo, detalle);

  const acciones = document.createElement('div');
  acciones.className = 'mi-kmz__acciones';
  const boton = (texto, dato, clase = 'boton boton--texto boton--chico') => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = clase;
    b.textContent = texto;
    b.dataset[dato] = kmz.slug;
    b.setAttribute('aria-label', `${texto}: ${kmz.nombre}`);
    return b;
  };
  if (kmz.terminado) {
    const bajar = document.createElement('a');
    bajar.className = 'boton boton--contorno boton--chico';
    bajar.href = descargaDe(kmz.slug);
    bajar.setAttribute('download', '');
    bajar.textContent = 'Descargar';
    bajar.setAttribute('aria-label', `Descargar ${kmz.nombre}`);
    acciones.append(bajar, boton('Usar en un master', 'usar', 'boton boton--contorno boton--chico'));
  }
  acciones.append(boton('Renombrar', 'renombrar'));
  const quitar = boton('Borrar', 'borrar', 'boton boton--texto boton--chico boton--peligro');
  quitar.disabled = Boolean(kmz.trabajo);
  acciones.append(quitar);

  item.append(enlace, acciones);
  return item;
}

async function borrar(kmz) {
  if (!confirm(`¿Borrar el KMZ "${kmz.nombre}"? Se borran también el plano subido y lo marcado. `
    + 'Los masters donde ya lo usaste conservan su copia. No se puede deshacer.')) return;
  await pedir(rutaDelKmz(kmz.slug), { method: 'DELETE' });
  estado.registros.delete(`kmz:${kmz.slug}`);
  await refrescar();
}

// --- nombre: nuevo y renombrar -----------------------------------------------------------

let renombrando = null;     // el KMZ al que se le cambia el nombre, o null si es uno nuevo
let alRenombrar = null;

/**
 * El diálogo del nombre. Sin KMZ, crea uno y lleva a él; con uno, lo renombra y
 * avisa a `despues` (la pantalla del KMZ repinta su título).
 */
export function abrirNombre(kmz = null, despues = null) {
  renombrando = kmz;
  alRenombrar = despues;
  $('#kmz-nombre-titulo').textContent = kmz ? 'Cambiar el nombre del KMZ' : 'Nuevo KMZ';
  $('#kmz-nombre-ayuda').textContent = kmz
    ? 'Es el nombre con que aparece en Mis KMZ y el del archivo al descargarlo.'
    : 'Un nombre para reconocerlo, por ejemplo el del loteo. Después subes el PDF del plano aprobado.';
  $('#kmz-nombre-listo').textContent = kmz ? 'Guardar' : 'Crear y seguir';
  $('#kmz-nombre-valor').value = kmz?.nombre ?? '';
  abrirDialogo($('#kmz-nombre'));
  $('#kmz-nombre-valor').focus();
  $('#kmz-nombre-valor').select();
}

async function guardarNombre() {
  const nombre = $('#kmz-nombre-valor').value.trim();
  if (!nombre) {
    avisar('Ponle un nombre al KMZ.');
    $('#kmz-nombre-valor').focus();
    return;
  }
  const boton = $('#kmz-nombre-listo');
  boton.disabled = true;
  try {
    if (renombrando) {
      const listo = await pedir(rutaDelKmz(renombrando.slug), json({ nombre }, 'PATCH'));
      $('#kmz-nombre').close();
      await refrescar();
      alRenombrar?.(listo);
      return;
    }
    const nuevo = await pedir('/api/kmz', json({ nombre }));
    $('#kmz-nombre').close();
    await refrescar();
    location.hash = `#/kmz/${encodeURIComponent(nuevo.slug)}`;
  } finally {
    boton.disabled = false;
  }
}

// --- usar un KMZ en un master --------------------------------------------------------------

// Lo que se está eligiendo: {kmz} desde un KMZ (se elige el master) o {master} desde
// un master (se elige el KMZ).
let usando = null;
// Un uso que espera confirmar el reemplazo: {kmz, master}.
let reemplazo = null;
const NUEVO = '__nuevo__';

/** Desde un KMZ terminado: ¿en qué master? Uno existente o uno nuevo. */
export function abrirUsarKmz(kmz) {
  usando = { kmz: kmz.slug };
  $('#kmz-usar-titulo').textContent = 'Usar en un master';
  $('#kmz-usar-texto').textContent = `"${kmz.nombre}" queda en el master como subdivision.kmz. `
    + 'Si ese master ya tiene un KMZ, se te pide confirmar y el anterior se guarda, no se borra.';
  $('#kmz-usar-rotulo').textContent = 'Master';
  const opciones = [{ valor: NUEVO, texto: 'Nuevo master con este KMZ' },
    ...estado.proyectos.map((p) => ({ valor: p.slug, texto: p.nombre }))];
  llenar(opciones, NUEVO);
  abrirDialogo($('#kmz-usar'));
  pintarUsar();
}

/** Desde un master: ¿cuál de Mis KMZ? Solo los terminados. */
export function abrirElegirKmz(proyecto) {
  usando = { master: proyecto.slug };
  const listos = terminados(estado.kmzs);
  $('#kmz-usar-titulo').textContent = 'Usar un KMZ de Mis KMZ';
  $('#kmz-usar-texto').textContent = `El KMZ elegido queda en "${proyecto.nombre}" como subdivision.kmz. `
    + 'Si ya tiene uno, se te pide confirmar y el anterior se guarda, no se borra.';
  $('#kmz-usar-rotulo').textContent = 'KMZ';
  llenar(listos.map((k) => ({ valor: k.slug, texto: `${k.nombre}${k.lotes != null ? ` · ${cuantosLotes(k.lotes)}` : ''}` })),
    listos[0]?.slug ?? '');
  abrirDialogo($('#kmz-usar'));
  pintarUsar();
}

function llenar(opciones, elegido) {
  const select = $('#kmz-usar-opciones');
  select.replaceChildren(...opciones.map(({ valor, texto }) => {
    const opcion = document.createElement('option');
    opcion.value = valor;
    opcion.textContent = texto;
    return opcion;
  }));
  select.value = elegido;
}

function pintarUsar() {
  const vacio = Boolean(usando?.master) && !terminados(estado.kmzs).length;
  $('#kmz-usar-vacio').hidden = !vacio;
  $('#kmz-usar-campo').hidden = vacio;
  $('#kmz-usar-listo').disabled = vacio;
  $('#kmz-usar-listo').textContent = usando?.kmz && $('#kmz-usar-opciones').value === NUEVO
    ? 'Crear el master' : 'Usar este KMZ';
}

async function usarElegido() {
  const valor = $('#kmz-usar-opciones').value;
  if (!usando || !valor) return;
  if (usando.kmz && valor === NUEVO) {
    $('#kmz-usar').close();
    location.hash = `#/planos/nuevo?kmz=${encodeURIComponent(usando.kmz)}`;
    return;
  }
  const kmz = usando.kmz ?? valor;
  const master = usando.master ?? valor;
  const boton = $('#kmz-usar-listo');
  boton.disabled = true;
  try {
    await usarEnMaster(kmz, master, false, () => $('#kmz-usar').close());
  } finally {
    boton.disabled = false;
  }
}

/**
 * Pone el KMZ en el master. Con 409 y `existentes`, pide confirmar el reemplazo
 * nombrando los archivos; al confirmar, se repite con `confirmar_reemplazo`.
 * Al terminar lleva al master y lo dice.
 */
export async function usarEnMaster(kmz, master, confirmado = false, alSalir = () => {}) {
  const respuesta = await fetch(`/api/proyectos/${encodeURIComponent(master)}/kmz`,
    json({ kmz, confirmar_reemplazo: confirmado }));
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (respuesta.status === 409 && cuerpo.existentes) {
    alSalir();
    reemplazo = { kmz, master };
    const nombre = estado.proyectos.find((p) => p.slug === master)?.nombre ?? master;
    $('#kmz-reemplazo-master').textContent = `Ya hay un KMZ en "${nombre}"`;
    $('#kmz-reemplazo-lista').replaceChildren(...cuerpo.existentes.map((archivo) => {
      const li = document.createElement('li');
      li.textContent = archivo;
      return li;
    }));
    abrirDialogo($('#kmz-reemplazo'));
    return null;
  }
  if (!respuesta.ok) throw new Error(cuerpo.detail ?? `Error ${respuesta.status}`);
  alSalir();
  const nombre = estado.proyectos.find((p) => p.slug === master)?.nombre ?? master;
  location.hash = `#/planos/${encodeURIComponent(master)}`;
  await refrescar();
  avisar(textoDeUso(cuerpo, nombre), 'ok');
  return cuerpo;
}
