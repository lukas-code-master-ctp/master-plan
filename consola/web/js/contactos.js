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
  const caja = $('#contactos');
  const { nuevos, atendidos } = agrupar(estado.contactos);
  if (!nuevos.length && !atendidos.length) {
    caja.replaceChildren(vacio());
    return;
  }
  caja.replaceChildren(...[grupo('Nuevos', nuevos), grupo('Atendidos', atendidos)].filter(Boolean));
}

function grupo(titulo, contactos) {
  if (!contactos.length) return null;
  const seccion = nodo('section', 'reservas__grupo');
  const cabeza = nodo('h2', null, titulo);
  cabeza.append(nodo('span', 'config__cuenta', contactos.length));
  const lista = nodo('ul', 'reservas__lista');
  lista.append(...contactos.map(tarjeta));
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

function tarjeta(contacto) {
  const item = nodo('li', `mensaje mensaje--${contacto.estado}`);
  const cuerpo = nodo('div', 'mensaje__cuerpo');

  // Quién: iniciales, nombre y loteadora, y cuándo escribió. Las clases son las de
  // Reservas, para que las dos pestañas se lean igual.
  const iniciales = contacto.nombre.trim().split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase()).join('');
  const quien = nodo('div', 'solicitud__quien');
  const textos = nodo('div');
  textos.append(nodo('strong', null, contacto.loteadora ? `${contacto.nombre} · ${contacto.loteadora}` : contacto.nombre),
                nodo('small', null, `escribió el ${FECHA.format(new Date(contacto.creado_en))}`));
  quien.append(nodo('span', 'solicitud__avatar', iniciales || '?'), textos);

  const contactos = nodo('div', 'solicitud__contactos');
  const whatsapp = enlaceWhatsapp(contacto);
  if (whatsapp) contactos.append(enlace(whatsapp, 'WhatsApp', 'contacto contacto--whatsapp', true));
  if (contacto.telefono) contactos.append(enlace(`tel:+${contacto.telefono}`, `+${contacto.telefono}`, 'contacto'));
  contactos.append(enlace(`mailto:${contacto.email}`, contacto.email, 'contacto'));

  cuerpo.append(quien, nodo('p', 'mensaje__pedido', pedido(contacto)), contactos);
  if (contacto.mensaje) cuerpo.append(nodo('p', 'mensaje__texto', contacto.mensaje));

  const atendido = contacto.estado === 'atendido';
  const boton = nodo('button', `boton mensaje__accion${atendido ? ' boton--contorno' : ''}`,
                     atendido ? 'Volver a nuevos' : 'Marcar atendido');
  boton.type = 'button';
  Object.assign(boton.dataset, { contacto: atendido ? 'nuevo' : 'atendido', id: contacto.id });

  item.append(cuerpo, boton);
  return item;
}

function enlace(href, texto, clase, externo = false) {
  const elemento = nodo('a', clase, texto);
  elemento.href = href;
  if (externo) {
    elemento.target = '_blank';
    elemento.rel = 'noopener';
  }
  return elemento;
}

function vacio() {
  const caja = nodo('div', 'reservas-vacio');
  caja.append(nodo('strong', null, 'Todavía no escribe nadie'),
              nodo('p', null, 'Cuando alguien mande el formulario de tumasterplan.cl, aparece acá y le llega un correo al equipo.'));
  return caja;
}
