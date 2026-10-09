/**
 * Reservas: las solicitudes que llegan desde los sitios publicados.
 *
 * Una parcela queda apartada mientras el comprador paga (2 horas, o lo que la
 * loteadora fijó en Configuración → Reservas y contacto). Acá la loteadora la
 * confirma cuando ve el pago (queda apartada hasta que el inventario la marque) o
 * la libera. Si nadie hace nada, vence sola.
 *
 * Arriba, el resumen sobre tinta como en Mis 360°; después, por confirmar con un
 * reloj que se va vaciando, las confirmadas y las anteriores.
 */
import { $, avisar, estado, horas, pedir } from './comun.js';
import { contar } from './planos.js';

const ANTERIORES_A_LA_VISTA = 20;
// Cada cuánto se mueve el reloj de las que esperan: el plazo se cuenta en minutos.
const TICK_MS = 30_000;
// Con menos de esto del plazo, el reloj se pone urgente.
const URGENTE = 0.2;
// En 24 horas, como se lee en Chile: según el navegador, es-CL podía salir "02:00 p. m.".
const HORA = new Intl.DateTimeFormat('es-CL', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

const PREGUNTAS = { liberar: '¿Liberar la parcela? Vuelve a estar disponible para otros compradores.' };
const LISTO = { confirmar: 'Pago confirmado: la parcela sigue apartada.', liberar: 'Parcela liberada.' };

let refrescar = async () => {};
let filtro = null;   // el slug del loteo elegido, o null para todos

// --- Lo que decide sin DOM -------------------------------------------------------------

/** Por confirmar (la que vence antes arriba), confirmadas y las 20 anteriores más recientes. */
export function agrupar(solicitudes) {
  const recientes = (a, b) => new Date(b.creada_en) - new Date(a.creada_en);
  return {
    porConfirmar: solicitudes.filter((s) => s.estado === 'pendiente')
      .sort((a, b) => new Date(a.vence_en) - new Date(b.vence_en)),
    confirmadas: solicitudes.filter((s) => s.estado === 'confirmada').sort(recientes),
    anteriores: solicitudes.filter((s) => s.estado === 'vencida' || s.estado === 'liberada')
      .sort(recientes).slice(0, ANTERIORES_A_LA_VISTA),
  };
}

function minutosQueFaltan(solicitud, ahora) {
  return Math.max(0, Math.round((new Date(solicitud.vence_en) - ahora) / 60000));
}

/** "1 h 20" o "25 min": lo que cabe adentro del reloj. */
export function cuantoFalta(solicitud, ahora = new Date()) {
  const minutos = minutosQueFaltan(solicitud, ahora);
  return minutos >= 60 ? `${Math.floor(minutos / 60)} h ${String(minutos % 60).padStart(2, '0')}` : `${minutos} min`;
}

/** En qué está la solicitud, en palabras. */
export function textoDelPlazo(solicitud, ahora = new Date()) {
  if (solicitud.estado === 'confirmada') return 'Pago confirmado: sigue apartada';
  if (solicitud.estado === 'vencida') return 'Venció sin confirmar: volvió a estar disponible';
  if (solicitud.estado === 'liberada') return 'Liberada: volvió a estar disponible';
  const minutos = minutosQueFaltan(solicitud, ahora);
  const falta = minutos >= 60 ? `${Math.floor(minutos / 60)} h ${minutos % 60} min` : `${minutos} min`;
  return `Apartada hasta las ${HORA.format(new Date(solicitud.vence_en))} · quedan ${falta}`;
}

/** Qué parte del plazo queda, de 1 (recién pedida) a 0 (vencida). */
export function fraccionRestante(solicitud, ahora = new Date()) {
  const desde = new Date(solicitud.creada_en);
  const hasta = new Date(solicitud.vence_en);
  const total = hasta - desde;
  if (total <= 0) return 0;
  return Math.min(1, Math.max(0, (hasta - ahora) / total));
}

/** "recién", "hace 40 min", "hace 3 h", "hace 2 días". */
export function haceCuanto(fecha, ahora = new Date()) {
  const minutos = Math.floor((ahora - new Date(fecha)) / 60000);
  if (minutos < 1) return 'recién';
  if (minutos < 60) return `hace ${minutos} min`;
  const horasPasadas = Math.floor(minutos / 60);
  if (horasPasadas < 24) return `hace ${horasPasadas} h`;
  const dias = Math.floor(horasPasadas / 24);
  return `hace ${dias} ${dias === 1 ? 'día' : 'días'}`;
}

/** Los loteos que tienen solicitudes, en el orden en que aparecen, con sus pendientes. */
export function loteosDe(solicitudes) {
  const loteos = new Map();
  for (const s of solicitudes) {
    const loteo = loteos.get(s.slug) ?? { slug: s.slug, nombre: s.loteo, pendientes: 0 };
    if (s.estado === 'pendiente') loteo.pendientes += 1;
    loteos.set(s.slug, loteo);
  }
  return [...loteos.values()];
}

export function filtrarPorLoteo(solicitudes, slug) {
  return slug ? solicitudes.filter((s) => s.slug === slug) : solicitudes;
}

/** Para escribirle al comprador por WhatsApp, con la parcela ya nombrada. */
export function enlaceWhatsapp(solicitud) {
  const mensaje = `Hola ${solicitud.nombre}, te escribo por tu reserva de la parcela ${solicitud.parcela} en ${solicitud.loteo}.`;
  return `https://wa.me/${solicitud.telefono}?text=${encodeURIComponent(mensaje)}`;
}

// --- Datos ---------------------------------------------------------------------------

/**
 * Las solicitudes de todos los loteos publicados de quien mira. Un loteo que
 * falla no deja sin las demás: se cuenta y se sigue.
 */
export async function cargarReservas(proyectos) {
  const publicados = proyectos.filter((p) => p.publicado);
  const listas = await Promise.all(publicados.map((p) =>
    pedir(`/api/proyectos/${encodeURIComponent(p.slug)}/reservas`)
      .then((lista) => lista.map((s) => ({ ...s, slug: p.slug, loteo: p.nombre })))
      .catch(() => [])));
  return listas.flat();
}

// --- La pantalla ---------------------------------------------------------------------

export function prepararReservas(opciones) {
  refrescar = opciones.refrescar;
  // Los botones de cada solicitud se crean al pintar la lista: llevan `data-reserva`
  // y no `data-accion`, que es para los botones fijos de la página.
  $('#reservas').addEventListener('click', async (evento) => {
    const boton = evento.target.closest('button[data-reserva]');
    if (!boton) return;
    const { reserva: que, slug, id } = boton.dataset;
    if (PREGUNTAS[que] && !confirm(PREGUNTAS[que])) return;
    boton.disabled = true;
    try {
      await pedir(`/api/proyectos/${encodeURIComponent(slug)}/reservas/${id}/${que}`, { method: 'POST' });
      avisar(LISTO[que], 'ok');
      await refrescar();
    } catch (error) {
      boton.disabled = false;
      avisar(error.message);
    }
  });
  $('#reservas-filtro').addEventListener('click', (evento) => {
    const boton = evento.target.closest('button[data-loteo]');
    if (!boton) return;
    filtro = boton.dataset.loteo || null;
    pintarReservas();
  });
  // El reloj se mueve solo mientras se mira la pantalla; si una vence, se recarga.
  setInterval(() => {
    if ($('#pantalla-reservas').hidden) return;
    if (moverRelojes()) refrescar().catch(() => {});
  }, TICK_MS);
}

/** El número de la pestaña: cuántas esperan que alguien las mire. */
export function pintarContador() {
  const pendientes = estado.reservas.filter((s) => s.estado === 'pendiente').length;
  const contador = $('#contador-reservas');
  contador.textContent = pendientes;
  contador.hidden = pendientes === 0;
}

export function pintarReservas({ animar = false } = {}) {
  const movimiento = animar && !matchMedia('(prefers-reduced-motion: reduce)').matches;
  const horasApartado = estado.sesion?.preferencias?.horas_apartado ?? 2;
  $('#reservas-horas').textContent = horas(horasApartado);
  if (filtro && !estado.reservas.some((s) => s.slug === filtro)) filtro = null;
  pintarResumen(agrupar(estado.reservas), horasApartado, movimiento);
  pintarFiltro();

  const lista = $('#reservas');
  lista.classList.toggle('reservas--entrando', movimiento);
  const { porConfirmar, confirmadas, anteriores } = agrupar(filtrarPorLoteo(estado.reservas, filtro));
  if (!porConfirmar.length && !confirmadas.length && !anteriores.length) {
    lista.replaceChildren(vacio());
    return;
  }
  const ahora = new Date();
  lista.replaceChildren(...[
    grupo('Por confirmar', 'pendiente', porConfirmar, (s, i) => tarjetaPendiente(s, ahora, i)),
    grupo('Confirmadas', 'confirmada', confirmadas, (s, i) => tarjetaConfirmada(s, ahora, i)),
    grupo('Anteriores', 'anterior', anteriores, (s, i) => filaAnterior(s, ahora, i)),
  ].filter(Boolean));
}

function pintarResumen({ porConfirmar, confirmadas, anteriores }, horasApartado, movimiento) {
  const resumen = $('#reservas-resumen');
  const cifras = [
    ['Por confirmar', porConfirmar.length, 'reservado'],
    ['Confirmadas', confirmadas.length, 'disponible'],
    ['Anteriores', anteriores.length, 'no_disponible'],
    ['Se apartan por', horasApartado, 'total', horasApartado === 1 ? 'hora' : 'horas'],
  ];
  const dl = $('.resumen-planos__cifras', resumen);
  dl.replaceChildren(...cifras.map(([rotulo, valor, color, unidad]) => {
    const div = document.createElement('div');
    const dt = document.createElement('dt');
    const punto = document.createElement('i');
    punto.className = `punto-estado punto-estado--${color}`;
    dt.append(punto, rotulo);
    const dd = document.createElement('dd');
    const numero = document.createElement('span');
    numero.dataset.valor = valor;
    numero.textContent = movimiento ? '0' : String(valor);
    dd.append(numero);
    if (unidad) {
      const chico = document.createElement('small');
      chico.textContent = ` ${unidad}`;
      dd.append(chico);
    }
    div.append(dt, dd);
    return div;
  }));
  resumen.classList.toggle('resumen-planos--entrando', movimiento);
  if (movimiento) contar([...dl.querySelectorAll('[data-valor]')]);
}

function pintarFiltro() {
  const loteos = loteosDe(estado.reservas);
  const nav = $('#reservas-filtro');
  nav.hidden = loteos.length < 2;
  if (nav.hidden) return;
  const opcion = (slug, texto, pendientes) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.dataset.loteo = slug ?? '';
    boton.setAttribute('aria-pressed', String((slug ?? null) === filtro));
    boton.textContent = texto;
    if (pendientes) {
      const cuenta = document.createElement('span');
      cuenta.className = 'filtro-loteos__cuenta';
      cuenta.textContent = pendientes;
      boton.append(cuenta);
    }
    return boton;
  };
  const total = loteos.reduce((suma, l) => suma + l.pendientes, 0);
  nav.replaceChildren(opcion(null, 'Todos', total), ...loteos.map((l) => opcion(l.slug, l.nombre, l.pendientes)));
}

function grupo(titulo, tipo, solicitudes, tarjeta) {
  if (!solicitudes.length) return null;
  const seccion = document.createElement('section');
  seccion.className = `reservas__grupo reservas__grupo--${tipo}`;
  const cabeza = document.createElement('h2');
  cabeza.textContent = titulo;
  const cuenta = document.createElement('span');
  cuenta.className = 'config__cuenta';
  cuenta.textContent = solicitudes.length;
  cabeza.append(cuenta);
  const lista = document.createElement('ul');
  lista.className = 'reservas__lista';
  lista.append(...solicitudes.map(tarjeta));
  seccion.append(cabeza, lista);
  return seccion;
}

// --- Las tarjetas: todo con textContent, lo escribió alguien de afuera -------------

function nodo(etiqueta, clase, texto) {
  const elemento = document.createElement(etiqueta);
  if (clase) elemento.className = clase;
  if (texto != null) elemento.textContent = texto;
  return elemento;
}

function base(solicitud, clase, orden) {
  const item = nodo('li', `solicitud solicitud--${clase}`);
  item.style.setProperty('--orden', Math.min(orden, 8));
  const parcela = nodo('div', 'solicitud__parcela');
  parcela.append(nodo('span', 'solicitud__rotulo', 'Parcela'), nodo('strong', 'solicitud__lote', solicitud.parcela),
                 nodo('small', 'solicitud__loteo', solicitud.loteo));
  return { item, parcela };
}

function comprador(solicitud, ahora) {
  const zona = nodo('div', 'solicitud__comprador');
  const iniciales = String(solicitud.nombre ?? '').trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase()).join('');
  const quien = nodo('div', 'solicitud__quien');
  const textos = nodo('div');
  textos.append(nodo('strong', null, solicitud.nombre), nodo('small', null, `pidió ${haceCuanto(solicitud.creada_en, ahora)}`));
  quien.append(nodo('span', 'solicitud__avatar', iniciales || '?'), textos);
  const contactos = nodo('div', 'solicitud__contactos');
  contactos.append(
    contacto(enlaceWhatsapp(solicitud), 'WhatsApp', 'contacto contacto--whatsapp', true),
    contacto(`tel:+${solicitud.telefono}`, `+${solicitud.telefono}`, 'contacto'),
    contacto(`mailto:${solicitud.email}`, solicitud.email, 'contacto'),
  );
  zona.append(quien, contactos);
  return zona;
}

function contacto(href, texto, clase, externo = false) {
  const enlace = nodo('a', clase, texto);
  enlace.href = href;
  if (externo) { enlace.target = '_blank'; enlace.rel = 'noopener'; }
  return enlace;
}

function boton(solicitud, que, texto, clase) {
  const elemento = nodo('button', clase, texto);
  elemento.type = 'button';
  Object.assign(elemento.dataset, { reserva: que, slug: solicitud.slug, id: solicitud.id });
  return elemento;
}

/** El reloj: un anillo que se vacía a medida que se acaba el plazo. */
function reloj(solicitud, ahora) {
  const caja = nodo('div', 'reloj');
  caja.dataset.creada = solicitud.creada_en;
  caja.dataset.vence = solicitud.vence_en;
  const anillo = nodo('div', 'reloj__anillo');
  anillo.innerHTML = '<svg viewBox="0 0 64 64" aria-hidden="true"><circle class="reloj__fondo" cx="32" cy="32" r="27" pathLength="100"/>'
    + '<circle class="reloj__resto" cx="32" cy="32" r="27" pathLength="100"/></svg>';
  const textos = nodo('div', 'reloj__texto');
  textos.append(nodo('strong', 'reloj__falta'), nodo('small', null, 'quedan'));
  anillo.append(textos);
  caja.append(anillo, nodo('small', 'reloj__hora'));
  ponerReloj(caja, solicitud, ahora);
  return caja;
}

function ponerReloj(caja, solicitud, ahora) {
  const resto = fraccionRestante(solicitud, ahora);
  caja.style.setProperty('--resto', resto.toFixed(4));
  caja.classList.toggle('reloj--urgente', resto < URGENTE);
  $('.reloj__falta', caja).textContent = cuantoFalta(solicitud, ahora);
  $('.reloj__hora', caja).textContent = `hasta las ${HORA.format(new Date(solicitud.vence_en))}`;
  caja.title = textoDelPlazo(solicitud, ahora);
}

/** Mueve los relojes sin repintar. Devuelve true si alguno llegó a cero. */
function moverRelojes() {
  const ahora = new Date();
  let vencio = false;
  for (const caja of document.querySelectorAll('#reservas .reloj')) {
    const solicitud = { creada_en: caja.dataset.creada, vence_en: caja.dataset.vence, estado: 'pendiente' };
    ponerReloj(caja, solicitud, ahora);
    if (fraccionRestante(solicitud, ahora) === 0) vencio = true;
  }
  return vencio;
}

function tarjetaPendiente(solicitud, ahora, orden) {
  const { item, parcela } = base(solicitud, 'pendiente', orden);
  const acciones = nodo('div', 'solicitud__acciones');
  acciones.append(boton(solicitud, 'confirmar', 'Confirmar pago', 'boton solicitud__confirmar'),
                  boton(solicitud, 'liberar', 'Liberar', 'boton boton--texto boton--peligro'));
  item.append(parcela, comprador(solicitud, ahora), reloj(solicitud, ahora), acciones);
  return item;
}

function tarjetaConfirmada(solicitud, ahora, orden) {
  const { item, parcela } = base(solicitud, 'confirmada', orden);
  const sello = nodo('div', 'solicitud__sello');
  sello.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 10.5 3.2 3.2L15 7"/></svg>';
  const textos = nodo('div');
  textos.append(nodo('strong', null, 'Pago confirmado'),
                nodo('small', null, 'Sigue apartada. Márcala en tu inventario para que quede así en el sitio.'));
  sello.append(textos);
  const acciones = nodo('div', 'solicitud__acciones');
  acciones.append(boton(solicitud, 'liberar', 'Liberar', 'boton boton--texto boton--peligro'));
  item.append(parcela, comprador(solicitud, ahora), sello, acciones);
  return item;
}

function filaAnterior(solicitud, ahora, orden) {
  const item = nodo('li', `anterior anterior--${solicitud.estado}`);
  item.style.setProperty('--orden', Math.min(orden, 8));
  item.append(nodo('strong', null, `Parcela ${solicitud.parcela}`), nodo('span', null, solicitud.loteo),
              nodo('span', null, solicitud.nombre),
              nodo('span', 'anterior__estado', solicitud.estado === 'vencida' ? 'Venció' : 'Liberada'),
              nodo('small', null, haceCuanto(solicitud.creada_en, ahora)));
  return item;
}

function vacio() {
  const caja = nodo('div', 'reservas-vacio');
  caja.innerHTML = '<span class="reservas-vacio__icono" aria-hidden="true"><span class="plano-nuevo__orbita"></span>'
    + '<svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2.5"/><path d="M4 10h16M9 3v4M15 3v4"/></svg></span>';
  caja.append(nodo('strong', null, filtro ? 'Este loteo no tiene solicitudes' : 'Todavía no llegan solicitudes'),
              nodo('p', null, 'Cuando alguien toque «Reservar parcela» en uno de tus sitios publicados, aparece acá con su reloj y te llega un correo.'));
  return caja;
}
