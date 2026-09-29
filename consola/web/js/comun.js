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
  // Las líneas del último trabajo de cada loteo, y el temporizador que las sondea.
  registros: new Map(),
  sondeos: new Map(),
};

// --- API ---------------------------------------------------------------------

export async function pedir(ruta, opciones = {}) {
  const respuesta = await fetch(ruta, opciones);
  if (respuesta.status === 204) return null;
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(cuerpo.detail ?? `Error ${respuesta.status}`);
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
export function avisar(mensaje) {
  const dialogo = document.querySelector('dialog[open]');
  const general = $('#aviso');

  if (!dialogo) {
    general.textContent = mensaje ?? '';
    general.hidden = !mensaje;
    if (mensaje) general.scrollIntoView({ block: 'nearest' });
    return;
  }
  // Que no quede un mensaje viejo esperando detrás del diálogo.
  general.textContent = '';
  general.hidden = true;

  const dentro = avisoDe(dialogo);
  dentro.textContent = mensaje ?? '';
  dentro.hidden = !mensaje;
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

/** Qué pantalla pide el hash, y de qué loteo si es el detalle. */
export function ruta(hash) {
  const partes = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent);
  if (partes[0] === 'disenos') return { pantalla: 'disenos' };
  if (partes[0] === 'planos' && partes[1] === 'nuevo') return { pantalla: 'nuevo' };
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
    return proyecto.trabajo.accion === 'publicar'
      ? pastilla('Publicando…', 'curso') : pastilla('Construyendo…', 'curso');
  }
  if (proyecto.publicado) return pastilla('Publicado', 'ok');
  if (proyecto.construido) return pastilla('Construido', 'ok');
  if (!proyecto.fuentes_encontradas.kmz) return pastilla('Falta el vuelo', 'aviso');
  return pastilla('Sin construir', 'aviso');
}
