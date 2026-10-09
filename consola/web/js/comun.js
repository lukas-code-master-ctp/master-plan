/**
 * Lo que comparten todas las pantallas de la app: buscar nodos, hablar con la
 * API, avisar y dar formato a lo que se muestra.
 */

export const $ = (sel, raiz = document) => raiz.querySelector(sel);
export const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];

/** Lo que la app sabe en este momento. Una sola fuente, que todas leen. */
export const estado = {
  sesion: null,
  proyectos: [],
  disenos: [],
  kmzs: [],
  // Las solicitudes de reserva de los loteos publicados (js/reservas.js).
  reservas: [],
  // Los mensajes del formulario de la landing, solo para el equipo de CTP (js/contactos.js).
  contactos: [],
  // Las líneas del último trabajo de cada loteo, y el temporizador que las sondea.
  // La clave es el slug del master, o `kmz:<slug>` para un KMZ de Mis KMZ (la misma
  // clave que usa el servidor): un slug nunca lleva ":", así que no chocan.
  registros: new Map(),
  // De qué trabajo son las líneas del registro de cada clave: {id, total, perdido}.
  // `total` es cuántas de ese trabajo ya se mostraron (el registro puede traer además
  // las de uno perdido, o el aviso de que se interrumpió), y `perdido`, que se dio por
  // interrumpido. Sin esto, seguir otro trabajo con la misma clave se saltaba sus
  // primeras líneas.
  registroDe: new Map(),
  sondeos: new Map(),
  // De cada loteo, el último trabajo: {accion, estado, terminado}.
  trabajos: new Map(),
};

// --- API ---------------------------------------------------------------------

export async function pedir(ruta, opciones = {}) {
  const respuesta = await fetch(ruta, opciones);
  if (respuesta.status === 204) return null;
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) {
    // El estado y el cuerpo van en el error: un 409 puede traer qué ofrecer (p. ej.
    // crear el KMZ igual, sin los lotes sin número).
    throw Object.assign(new Error(cuerpo.detail ?? `Error ${respuesta.status}`),
      { estado: respuesta.status, cuerpo });
  }
  return cuerpo;
}

export const json = (datos, method = 'POST') => ({
  method, headers: { 'content-type': 'application/json' }, body: JSON.stringify(datos),
});

// --- Avisos ------------------------------------------------------------------

/**
 * Dice algo, donde la persona está mirando.
 *
 * Un `<dialog>` modal se dibuja en la capa de arriba y tapa la página entera, así
 * que un aviso puesto en la página mientras hay un diálogo abierto es invisible:
 * uno aprieta un botón, no pasa nada aparente, cierra el diálogo y recién ahí
 * descubre un mensaje rojo sin saber de qué era. Por eso el aviso va adentro del
 * diálogo cuando hay uno abierto.
 */
export function avisar(mensaje, tono = null) {
  const dialogo = document.querySelector('dialog[open]');
  const general = $('#aviso');

  if (!dialogo) {
    general.textContent = mensaje ?? '';
    general.hidden = !mensaje;
    // `ok`: algo que salió bien y conviene decir (p. ej. el KMZ quedó en el master).
    general.classList.toggle('aviso--ok', tono === 'ok');
    general.setAttribute('role', tono === 'ok' ? 'status' : 'alert');
    if (mensaje) general.scrollIntoView({ block: 'nearest' });
    return;
  }
  // Que no quede un mensaje viejo esperando detrás del diálogo.
  general.textContent = '';
  general.hidden = true;

  const dentro = avisoDe(dialogo);
  dentro.textContent = mensaje ?? '';
  dentro.hidden = !mensaje;
  dentro.classList.toggle('aviso--ok', tono === 'ok');
}

/** El hueco para avisos de un diálogo, creado la primera vez que hace falta. */
function avisoDe(dialogo) {
  let nodo = dialogo.querySelector('.aviso');
  if (!nodo) {
    nodo = document.createElement('p');
    nodo.className = 'aviso';
    const pie = dialogo.querySelector('.modal__pie');
    if (pie) pie.before(nodo); else dialogo.append(nodo);
  }
  return nodo;
}

/** Abre un diálogo sin los mensajes de la vez anterior. */
export function abrirDialogo(dialogo) {
  const nodo = dialogo.querySelector('.aviso');
  if (nodo) { nodo.textContent = ''; nodo.hidden = true; }
  dialogo.showModal();
}

// --- Rutas -------------------------------------------------------------------

/**
 * Qué pantalla pide el hash, y de qué loteo o KMZ si es un detalle.
 *
 * `#/kmz/<slug>/<paso>` abre un KMZ en ese paso.
 * `#/planos/nuevo?kmz=<slug>` abre Nuevo master con ese KMZ de Mis KMZ ya elegido
 * (viene de "Usar en un master" → "Nuevo master con este KMZ").
 */
export function ruta(hash) {
  const [camino, consulta = ''] = hash.replace(/^#\/?/, '').split('?');
  const partes = camino.split('/').filter(Boolean).map(decodeURIComponent);
  if (partes[0] === 'disenos' && partes[1]) return { pantalla: 'diseno', id: partes[1] };
  if (partes[0] === 'disenos') return { pantalla: 'disenos' };
  if (partes[0] === 'reservas') return { pantalla: 'reservas' };
  if (partes[0] === 'contactos') return { pantalla: 'contactos' };
  if (partes[0] === 'configuracion') return { pantalla: 'configuracion' };
  // `#/kmz/<slug>/<paso>` abre ese paso (ver `pasoDeRuta` en kmz_geometria.js).
  if (partes[0] === 'kmz' && partes[1] && partes[2]) return { pantalla: 'kmz', slug: partes[1], paso: partes[2] };
  if (partes[0] === 'kmz' && partes[1]) return { pantalla: 'kmz', slug: partes[1] };
  if (partes[0] === 'kmz') return { pantalla: 'kmzs' };
  if (partes[0] === 'planos' && partes[1] === 'nuevo') {
    const kmz = new URLSearchParams(consulta).get('kmz');
    return kmz ? { pantalla: 'nuevo', kmz } : { pantalla: 'nuevo' };
  }
  if (partes[0] === 'planos' && partes[1]) return { pantalla: 'plano', slug: partes[1] };
  return { pantalla: 'planos' };
}

// --- Formato -----------------------------------------------------------------

/** "ana.perez@losrobles.cl" → "AP"; "ana@losrobles.cl" → "A". */
export function iniciales(email) {
  const usuario = String(email ?? '').split('@')[0];
  const partes = usuario.split(/[._-]+/).filter(Boolean);
  return partes.slice(0, 2).map((p) => p[0].toUpperCase()).join('') || '?';
}

/** 1 → "1 hora"; 24 → "24 horas". */
export function horas(cantidad) {
  return `${cantidad} ${cantidad === 1 ? 'hora' : 'horas'}`;
}

const NUMERO = new Intl.NumberFormat('es-CL');

/** Igual que la ficha del visor: el comprador y el dueño leen el mismo número. */
export function dinero(monto, moneda) {
  if (monto == null) return null;
  if (moneda === 'UF') return `UF ${NUMERO.format(monto)}`;
  return `$${NUMERO.format(Math.round(monto))}`;
}

export function fecha(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const dos = (n) => String(n).padStart(2, '0');
  return `${dos(d.getDate())}/${dos(d.getMonth() + 1)} ${dos(d.getHours())}:${dos(d.getMinutes())}`;
}

export function pastilla(texto, tono) {
  const span = document.createElement('span');
  span.className = 'pastilla' + (tono ? ` pastilla--${tono}` : '');
  span.textContent = texto;
  return span;
}

/** El estado de un loteo en una palabra, para la lista y el detalle. */
export function etapaDe(proyecto) {
  if (proyecto.trabajo) {
    return pastilla(proyecto.trabajo.accion === 'publicar' ? 'Publicando…' : 'Construyendo…', 'curso');
  }
  if (proyecto.publicado) return pastilla('Publicado', 'ok');
  if (proyecto.construido) return pastilla('Construido', 'ok');
  if (!proyecto.fuentes_encontradas.kmz) return pastilla('Falta el vuelo', 'aviso');
  return pastilla('Sin construir', 'aviso');
}

/**
 * El loteo cuya foto va de fondo en la muestra de un diseño: uno construido que lo
 * lleve o, si ninguno, cualquiera construido. Así se ve la marca sobre el campo.
 */
export function fotoDeFondo(proyectos, disenoId) {
  const construidos = (proyectos ?? []).filter((p) => p.construido);
  return (construidos.find((p) => p.diseno_id === disenoId) ?? construidos[0])?.slug ?? null;
}
