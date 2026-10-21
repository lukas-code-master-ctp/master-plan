/**
 * Los esqueletos: mientras llega lo que va en una lista, la lista ya muestra la
 * forma de lo que viene (tarjetas, filas, avatares) en gris, con un brillo que la
 * recorre. Así la pantalla no salta de vacía a llena, y se nota que algo viene.
 *
 * Son solo forma: van con `aria-hidden` y la lista con `aria-busy`, para que un
 * lector de pantalla no lea cajas grises. Lo que pinta el contenido de verdad
 * los reemplaza con su `replaceChildren` y les quita el `aria-busy`.
 */
import { $ } from './comun.js';

/** Una barra gris. `ancho` en cualquier unidad de CSS; `clase`, la forma. */
function hueso(ancho = '100%', clase = 'esqueleto--linea') {
  const span = document.createElement('span');
  span.className = `esqueleto ${clase}`;
  span.style.width = ancho;
  return span;
}

function item(clase, ...hijos) {
  const li = document.createElement('li');
  li.className = clase;
  li.setAttribute('aria-hidden', 'true');
  li.append(...hijos);
  return li;
}

function caja(clase, ...hijos) {
  const div = document.createElement('div');
  div.className = clase;
  div.append(...hijos);
  return div;
}

// Mis 360°: la rejilla de siempre (una destacada y dos al lado), en gris.
function tarjetasDePlanos() {
  return ['destacada', 'lateral', 'lateral'].map((forma) => item(
    `planos__item planos__item--${forma}`,
    caja('esqueleto-plano', hueso('5.5rem', 'esqueleto--chip'), hueso('62%', 'esqueleto--titulo'), hueso('40%')),
  ));
}

// Mis KMZ y Mis diseños: miniatura arriba, nombre y una línea abajo.
function tarjetasConMiniatura() {
  return [0, 1, 2].map(() => item(
    'esqueleto-tarjeta',
    hueso('100%', 'esqueleto--miniatura'),
    caja('esqueleto-tarjeta__pie', hueso('58%', 'esqueleto--titulo'), hueso('80%')),
  ));
}

// Reservas y contactos: un rótulo de grupo y filas como las solicitudes.
function filas() {
  const grupo = caja('reservas__grupo', hueso('9rem', 'esqueleto--titulo'));
  grupo.setAttribute('aria-hidden', 'true');
  const lista = document.createElement('ul');
  lista.className = 'reservas__lista';
  lista.append(...[0, 1, 2].map(() => item(
    'esqueleto-fila',
    hueso('4.5rem', 'esqueleto--bloque'),
    caja('esqueleto-fila__texto', hueso('45%', 'esqueleto--titulo'), hueso('70%')),
    hueso('6.5rem', 'esqueleto--boton'),
  )));
  grupo.append(lista);
  return [grupo];
}

// Configuración → Equipo: avatar redondo, nombre y correo.
function miembros() {
  return [0, 1].map(() => item(
    'esqueleto-miembro',
    hueso('2.5rem', 'esqueleto--avatar'),
    caja('esqueleto-fila__texto', hueso('35%'), hueso('55%')),
  ));
}

// Configuración → Actividad: el día y unas líneas.
function actividad() {
  return [item(
    'esqueleto-actividad',
    hueso('6rem', 'esqueleto--titulo'),
    ...['82%', '64%', '74%', '52%'].map((ancho) => hueso(ancho)),
  )];
}

const FORMAS = {
  planos: tarjetasDePlanos,
  kmzs: tarjetasConMiniatura,
  disenos: tarjetasConMiniatura,
  reservas: filas,
  contactos: filas,
  'equipo-lista': miembros,
  'actividad-lista': actividad,
};

/** Los esqueletos de una lista, por su id. Sin forma conocida, ninguno. */
export function esqueletosDe(id) {
  return FORMAS[id]?.() ?? [];
}

/** Llena la lista `#id` con su esqueleto y la marca ocupada. */
export function pintarEsqueleto(id) {
  const lista = $(`#${id}`);
  if (!lista) return;
  lista.replaceChildren(...esqueletosDe(id));
  lista.setAttribute('aria-busy', 'true');
  // Lo de verdad reemplaza los hijos; al hacerlo, la lista deja de estar ocupada.
  const vigia = new MutationObserver(() => {
    if (lista.querySelector('.esqueleto')) return;
    lista.removeAttribute('aria-busy');
    vigia.disconnect();
  });
  vigia.observe(lista, { childList: true });
}

/** Las cifras del resumen de reservas, en gris mientras llegan. */
export function pintarCifrasEsqueleto(dl, cantidad = 4) {
  dl.replaceChildren(...Array.from({ length: cantidad }, () => {
    const div = caja('esqueleto-cifra', hueso('60%'), hueso('2.5rem', 'esqueleto--cifra'));
    div.setAttribute('aria-hidden', 'true');
    return div;
  }));
}

/**
 * Un texto que todavía no llega: una barra, con un "Cargando…" para quien no ve.
 * El ancho va en `vw` y no en %: el título suele ir en una caja que mide lo que su
 * texto, y sin texto mediría cero.
 */
export function tituloEsqueleto(nodo, { ancho = 'min(22rem, 60vw)', clase = 'esqueleto--h1' } = {}) {
  const oculto = document.createElement('span');
  oculto.className = 'oculto';
  oculto.textContent = 'Cargando…';
  const barra = hueso(ancho, clase);
  barra.setAttribute('aria-hidden', 'true');
  nodo.replaceChildren(oculto, barra);
}
