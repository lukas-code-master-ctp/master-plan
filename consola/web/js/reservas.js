/**
 * Reservas: las solicitudes que llegan desde los sitios publicados.
 *
 * Una parcela queda apartada 2 horas mientras el comprador paga. Acá la
 * loteadora la confirma cuando ve el pago (queda apartada hasta que el
 * inventario la marque) o la libera. Si nadie hace nada, vence sola.
 */
import { $, avisar, estado, pedir } from './comun.js';

const ANTERIORES_A_LA_VISTA = 20;
// En 24 horas, como se lee en Chile: según el navegador, es-CL podía salir "02:00 p. m.".
const HORA = new Intl.DateTimeFormat('es-CL', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const FECHA = new Intl.DateTimeFormat('es-CL', {
  day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

const PREGUNTAS = { liberar: '¿Liberar la parcela? Vuelve a estar disponible para otros compradores.' };
const LISTO = { confirmar: 'Pago confirmado: la parcela sigue apartada.', liberar: 'Parcela liberada.' };

let refrescar = async () => {};

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

/** En qué está la solicitud, en palabras. */
export function textoDelPlazo(solicitud, ahora = new Date()) {
  if (solicitud.estado === 'confirmada') return 'Pago confirmado: sigue apartada';
  if (solicitud.estado === 'vencida') return 'Venció sin confirmar: volvió a estar disponible';
  if (solicitud.estado === 'liberada') return 'Liberada: volvió a estar disponible';
  const vence = new Date(solicitud.vence_en);
  const minutos = Math.max(0, Math.round((vence - ahora) / 60000));
  const falta = minutos >= 60 ? `${Math.floor(minutos / 60)} h ${minutos % 60} min` : `${minutos} min`;
  return `Apartada hasta las ${HORA.format(vence)} · quedan ${falta}`;
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
}

/** El número de la pestaña: cuántas esperan que alguien las mire. */
export function pintarContador() {
  const pendientes = estado.reservas.filter((s) => s.estado === 'pendiente').length;
  const contador = $('#contador-reservas');
  contador.textContent = pendientes;
  contador.hidden = pendientes === 0;
}

export function pintarReservas() {
  const lista = $('#reservas');
  const { porConfirmar, confirmadas, anteriores } = agrupar(estado.reservas);
  if (!porConfirmar.length && !confirmadas.length && !anteriores.length) {
    lista.innerHTML = `<li class="vacio"><strong>Todavía no llegan solicitudes</strong>
      <span>Cuando alguien toque <b>Reservar parcela</b> en uno de tus sitios publicados, aparece
      acá y te llega un correo.</span></li>`;
    return;
  }
  const ahora = new Date();
  lista.replaceChildren(
    ...grupo('Por confirmar', porConfirmar, ahora, true),
    ...grupo('Confirmadas', confirmadas, ahora, true),
    ...grupo('Anteriores', anteriores, ahora, false),
  );
}

function grupo(titulo, solicitudes, ahora, conAcciones) {
  if (!solicitudes.length) return [];
  const encabezado = document.createElement('li');
  encabezado.className = 'reservas__grupo';
  encabezado.textContent = `${titulo} (${solicitudes.length})`;
  return [encabezado, ...solicitudes.map((s) => fila(s, ahora, conAcciones))];
}

/** Una solicitud. Todo con textContent: lo escribió alguien de afuera. */
function fila(solicitud, ahora, conAcciones) {
  const item = document.createElement('li');
  item.className = `reserva-fila reserva-fila--${solicitud.estado}`;

  const cabeza = document.createElement('div');
  cabeza.className = 'reserva-fila__cabeza';
  const titulo = document.createElement('strong');
  titulo.textContent = `Parcela ${solicitud.parcela} · ${solicitud.loteo}`;
  const plazo = document.createElement('span');
  plazo.className = 'reserva-fila__plazo';
  plazo.textContent = textoDelPlazo(solicitud, ahora);
  cabeza.append(titulo, plazo);

  const comprador = document.createElement('div');
  comprador.className = 'reserva-fila__comprador';
  const nombre = document.createElement('span');
  nombre.textContent = `${solicitud.nombre} · pidió el ${FECHA.format(new Date(solicitud.creada_en))}`;
  comprador.append(nombre, contacto(`tel:+${solicitud.telefono}`, `+${solicitud.telefono}`),
                   contacto(`mailto:${solicitud.email}`, solicitud.email),
                   contacto(enlaceWhatsapp(solicitud), 'WhatsApp', true));

  item.append(cabeza, comprador);
  if (conAcciones) item.append(acciones(solicitud));
  return item;
}

function contacto(href, texto, externo = false) {
  const enlace = document.createElement('a');
  enlace.href = href;
  enlace.textContent = texto;
  if (externo) {
    enlace.target = '_blank';
    enlace.rel = 'noopener';
  }
  return enlace;
}

function acciones(solicitud) {
  const zona = document.createElement('div');
  zona.className = 'reserva-fila__acciones';
  const boton = (que, texto, clase) => {
    const elemento = document.createElement('button');
    elemento.type = 'button';
    elemento.className = clase;
    elemento.textContent = texto;
    Object.assign(elemento.dataset, { reserva: que, slug: solicitud.slug, id: solicitud.id });
    return elemento;
  };
  if (solicitud.estado === 'pendiente') zona.append(boton('confirmar', 'Confirmar pago', 'boton'));
  zona.append(boton('liberar', 'Liberar', 'boton boton--contorno'));
  return zona;
}
