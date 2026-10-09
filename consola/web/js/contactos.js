/**
 * Contactos: lo que escriben en el formulario de la landing (tumasterplan.cl).
 *
 * Es del equipo de CTP y de nadie más: quien escribe todavía no es una
 * loteadora, quiere serlo. La pestaña solo aparece para la cuenta de plataforma
 * (`pintarBackOffice`), y las rutas contestan 403 a cualquier otra.
 */
import { $, avisar, estado, json, pedir } from './comun.js';

const ATENDIDOS_A_LA_VISTA = 50;
const FECHA = new Intl.DateTimeFormat('es-CL', {
  day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});
const PLAN = { fly: 'Fly', pro: 'Pro', master: 'Master', enterprise: 'Enterprise' };
const LISTO = { atendido: 'Marcado como atendido.', nuevo: 'Vuelve a nuevos.' };

let refrescar = async () => {};

// --- Lo que decide sin DOM -------------------------------------------------------------

/** Nuevos (el más reciente arriba) y los últimos 50 atendidos. */
export function agrupar(contactos) {
  const recientes = (a, b) => new Date(b.creado_en) - new Date(a.creado_en);
  return {
    nuevos: contactos.filter((c) => c.estado === 'nuevo').sort(recientes),
    atendidos: contactos.filter((c) => c.estado === 'atendido').sort(recientes)
      .slice(0, ATENDIDOS_A_LA_VISTA),
  };
}

/** Lo que pidió, en una línea: plan, tamaño y si hay que volarlo. */
export function pedido(contacto) {
  const partes = [PLAN[contacto.plan] ? `Plan ${PLAN[contacto.plan]}` : 'Aún no sabe qué plan'];
  if (contacto.parcelas) partes.push(`${contacto.parcelas} parcelas`);
  if (contacto.vuelo) partes.push('necesita que lo volemos');
  return partes.join(' · ');
}

/** Para contestarle por WhatsApp. Sin teléfono, no hay enlace. */
export function enlaceWhatsapp(contacto) {
  if (!contacto.telefono) return null;
  const nombre = contacto.nombre.split(' ')[0];
  const mensaje = `Hola ${nombre}, te escribo de Tu Masterplan por tu mensaje en tumasterplan.cl.`;
  return `https://wa.me/${contacto.telefono}?text=${encodeURIComponent(mensaje)}`;
}

// --- Datos ---------------------------------------------------------------------------

/** Solo el equipo de CTP los pide: a una loteadora la ruta le contestaría 403. */
export async function cargarContactos() {
  if (estado.sesion?.rol !== 'plataforma') return [];
  return pedir('/api/plataforma/contactos').catch(() => []);
}

// --- La pantalla ---------------------------------------------------------------------

export function prepararContactos(opciones) {
  refrescar = opciones.refrescar;
  $('#contactos').addEventListener('click', async (evento) => {
    const boton = evento.target.closest('button[data-contacto]');
    if (!boton) return;
    const { contacto: nuevoEstado, id } = boton.dataset;
    boton.disabled = true;
    try {
      await pedir(`/api/plataforma/contactos/${id}/estado`, json({ estado: nuevoEstado }));
      avisar(LISTO[nuevoEstado], 'ok');
      await refrescar();
    } catch (error) {
      boton.disabled = false;
      avisar(error.message);
    }
  });
}

/** El número de la pestaña: cuántos mensajes nadie ha atendido. */
export function pintarContadorContactos() {
  const nuevos = estado.contactos.filter((c) => c.estado === 'nuevo').length;
  const contador = $('#contador-contactos');
  contador.textContent = nuevos;
  contador.hidden = nuevos === 0;
}

export function pintarContactos() {
  const lista = $('#contactos');
  const { nuevos, atendidos } = agrupar(estado.contactos);
  if (!nuevos.length && !atendidos.length) {
    lista.innerHTML = `<li class="vacio"><strong>Todavía no escribe nadie</strong>
      <span>Cuando alguien mande el formulario de <b>tumasterplan.cl</b>, aparece acá y le llega
      un correo al equipo.</span></li>`;
    return;
  }
  lista.replaceChildren(...grupo('Nuevos', nuevos), ...grupo('Atendidos', atendidos));
}

function grupo(titulo, contactos) {
  if (!contactos.length) return [];
  const encabezado = document.createElement('li');
  encabezado.className = 'reservas__grupo';
  encabezado.textContent = `${titulo} (${contactos.length})`;
  return [encabezado, ...contactos.map(fila)];
}

/** Un mensaje. Todo con textContent: lo escribió alguien de afuera. */
function fila(contacto) {
  const item = document.createElement('li');
  item.className = `reserva-fila contacto-fila contacto-fila--${contacto.estado}`;

  const cabeza = document.createElement('div');
  cabeza.className = 'reserva-fila__cabeza';
  const titulo = document.createElement('strong');
  titulo.textContent = contacto.loteadora ? `${contacto.nombre} · ${contacto.loteadora}` : contacto.nombre;
  const cuando = document.createElement('span');
  cuando.className = 'reserva-fila__plazo';
  cuando.textContent = FECHA.format(new Date(contacto.creado_en));
  cabeza.append(titulo, cuando);

  const que = document.createElement('p');
  que.className = 'contacto-fila__pedido';
  que.textContent = pedido(contacto);

  const datos = document.createElement('div');
  datos.className = 'reserva-fila__comprador';
  datos.append(enlace(`mailto:${contacto.email}`, contacto.email));
  if (contacto.telefono) {
    datos.append(enlace(`tel:+${contacto.telefono}`, `+${contacto.telefono}`),
                 enlace(enlaceWhatsapp(contacto), 'WhatsApp', true));
  }

  item.append(cabeza, que, datos);
  if (contacto.mensaje) {
    const mensaje = document.createElement('p');
    mensaje.className = 'contacto-fila__mensaje';
    mensaje.textContent = contacto.mensaje;
    item.append(mensaje);
  }
  item.append(acciones(contacto));
  return item;
}

function enlace(href, texto, externo = false) {
  const elemento = document.createElement('a');
  elemento.href = href;
  elemento.textContent = texto;
  if (externo) {
    elemento.target = '_blank';
    elemento.rel = 'noopener';
  }
  return elemento;
}

function acciones(contacto) {
  const zona = document.createElement('div');
  zona.className = 'reserva-fila__acciones';
  const boton = document.createElement('button');
  boton.type = 'button';
  const atendido = contacto.estado === 'atendido';
  boton.className = atendido ? 'boton boton--contorno' : 'boton';
  boton.textContent = atendido ? 'Volver a nuevos' : 'Marcar atendido';
  Object.assign(boton.dataset, { contacto: atendido ? 'nuevo' : 'atendido', id: contacto.id });
  zona.append(boton);
  return zona;
}
