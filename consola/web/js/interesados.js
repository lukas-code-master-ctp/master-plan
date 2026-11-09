/**
 * Interesados: quienes tocaron "Me interesa esta parcela" en un sitio publicado.
 *
 * No apartan nada (eso es Reservas): son contactos que alguien del equipo tiene
 * que llamar. Por eso cada uno lleva un estado (de nuevo a reservó o descartado),
 * quién lo atiende y una nota. El responsable es texto libre: muchas loteadoras
 * venden con corredores que no entran a la consola.
 *
 * A la izquierda la lista, con filtros por loteo y estado; a la derecha el que se
 * eligió, con WhatsApp, llamar y lo que se va anotando.
 */
import { $, avisar, estado, json, pedir } from './comun.js';
import { haceCuanto } from './reservas.js';

export const ESTADOS = {
  nuevo: 'Nuevo',
  contactado: 'Contactado',
  visita: 'Visita agendada',
  reservo: 'Reservó',
  descartado: 'Descartado',
};
const HORARIO = { manana: 'en la mañana', tarde: 'en la tarde' };
const FECHA = new Intl.DateTimeFormat('es-CL', {
  day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

let refrescar = async () => {};
const filtro = { loteo: null, estado: null };
let elegido = null;   // `${slug}/${id}` del que se ve a la derecha

// --- Lo que decide sin DOM -------------------------------------------------------------

export const clave = (interesado) => `${interesado.slug}/${interesado.id}`;

/** Los que pasan el filtro, el más reciente arriba. */
export function filtrar(interesados, { loteo = null, estado: cual = null } = {}) {
  return interesados
    .filter((i) => (!loteo || i.slug === loteo) && (!cual || i.estado === cual))
    .sort((a, b) => new Date(b.creado_en) - new Date(a.creado_en));
}

/** Los loteos que tienen interesados, con cuántos nuevos. */
export function loteosDe(interesados) {
  const loteos = new Map();
  for (const i of interesados) {
    const loteo = loteos.get(i.slug) ?? { slug: i.slug, nombre: i.loteo, nuevos: 0 };
    if (i.estado === 'nuevo') loteo.nuevos += 1;
    loteos.set(i.slug, loteo);
  }
  return [...loteos.values()];
}

/** Los responsables ya escritos, para sugerirlos y no tipear "María" de tres formas. */
export function responsables(interesados) {
  return [...new Set(interesados.map((i) => i.responsable).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'es'));
}

/** "+56 9 8123 4567" para leerlo; el enlace usa los dígitos tal cual. */
export function telefonoLegible(digitos) {
  const t = String(digitos ?? '');
  if (/^569\d{8}$/.test(t)) return `+56 9 ${t.slice(3, 7)} ${t.slice(7)}`;
  return `+${t}`;
}

/** Para escribirle por WhatsApp, con la parcela ya nombrada. */
export function enlaceWhatsapp(interesado) {
  const nombre = String(interesado.nombre ?? '').split(' ')[0];
  const mensaje = `Hola ${nombre}, te escribo por tu interés en la parcela ${interesado.parcela} de ${interesado.loteo}.`;
  return `https://wa.me/${interesado.telefono}?text=${encodeURIComponent(mensaje)}`;
}

/** La línea bajo el nombre: el teléfono y cuándo prefiere que lo llamen. */
export function detalleDeContacto(interesado) {
  const horario = HORARIO[interesado.horario];
  return [telefonoLegible(interesado.telefono), horario && `prefiere ${horario}`].filter(Boolean).join(' · ');
}

/**
 * La planilla para Excel: separada por punto y coma y con BOM, que es como Excel
 * en español abre un CSV sin romper los acentos ni partir las columnas.
 */
export function planilla(interesados) {
  const celda = (valor) => {
    const texto = String(valor ?? '');
    return /[";\n\r]/.test(texto) ? `"${texto.replaceAll('"', '""')}"` : texto;
  };
  const filas = [['Fecha', 'Loteo', 'Parcela', 'Nombre', 'Teléfono', 'Correo', 'Horario', 'Estado', 'Responsable', 'Nota']];
  for (const i of interesados) {
    filas.push([FECHA.format(new Date(i.creado_en)), i.loteo, i.parcela, i.nombre, `+${i.telefono}`, i.email,
      HORARIO[i.horario] ?? 'cualquier hora', ESTADOS[i.estado] ?? i.estado, i.responsable, i.nota]);
  }
  return `﻿${filas.map((f) => f.map(celda).join(';')).join('\r\n')}\r\n`;
}

// --- Datos ---------------------------------------------------------------------------

/**
 * Los interesados de los loteos de quien mira. De todos, no solo de los publicados:
 * un loteo que se bajó sigue teniendo contactos por llamar. Uno que falla no deja
 * sin los demás.
 */
export async function cargarInteresados(proyectos) {
  const listas = await Promise.all(proyectos.map((p) =>
    pedir(`/api/proyectos/${encodeURIComponent(p.slug)}/interesados`)
      .then((lista) => lista.map((i) => ({ ...i, slug: p.slug, loteo: p.nombre })))
      .catch(() => [])));
  return listas.flat();
}

async function guardar(interesado, cambios, listo) {
  try {
    const nuevo = await pedir(
      `/api/proyectos/${encodeURIComponent(interesado.slug)}/interesados/${interesado.id}`, json(cambios, 'PATCH'));
    Object.assign(interesado, nuevo);
    avisar(listo, 'ok');
    pintarContadorInteresados();
    pintarInteresados();
  } catch (error) {
    avisar(error.message);
  }
}

// --- La pantalla ---------------------------------------------------------------------

export function prepararInteresados(opciones) {
  refrescar = opciones.refrescar;
  $('#interesados').addEventListener('click', (evento) => {
    const fila = evento.target.closest('[data-interesado]');
    if (!fila) return;
    elegido = fila.dataset.interesado;
    pintarInteresados();
    $('#interesado')?.scrollIntoView?.({ block: 'nearest', behavior: 'smooth' });
  });
  $('#interesados-filtro').addEventListener('click', (evento) => {
    const boton = evento.target.closest('button[data-loteo]');
    if (!boton) return;
    filtro.loteo = boton.dataset.loteo || null;
    pintarInteresados();
  });
  $('#interesados-estado').addEventListener('change', (evento) => {
    filtro.estado = evento.target.value || null;
    pintarInteresados();
  });
  $('#interesados-planilla').addEventListener('click', () => {
    const lista = filtrar(estado.interesados, filtro);
    const enlace = document.createElement('a');
    enlace.href = URL.createObjectURL(new Blob([planilla(lista)], { type: 'text/csv;charset=utf-8' }));
    enlace.download = 'interesados.csv';
    enlace.click();
    setTimeout(() => URL.revokeObjectURL(enlace.href), 1000);
  });
  $('#interesados-actualizar').addEventListener('click', () => refrescar().catch((error) => avisar(error.message)));
}

/** El número de la pestaña: cuántos nadie ha contactado todavía. */
export function pintarContadorInteresados() {
  const nuevos = estado.interesados.filter((i) => i.estado === 'nuevo').length;
  const contador = $('#contador-interesados');
  contador.textContent = nuevos;
  contador.hidden = nuevos === 0;
}

export function pintarInteresados() {
  if (filtro.loteo && !estado.interesados.some((i) => i.slug === filtro.loteo)) filtro.loteo = null;
  pintarFiltro();
  $('#interesados-planilla').disabled = !estado.interesados.length;

  const lista = $('#interesados');
  const visibles = filtrar(estado.interesados, filtro);
  if (!visibles.length) {
    lista.replaceChildren(vacio());
    $('#interesado').hidden = true;
    return;
  }
  if (!visibles.some((i) => clave(i) === elegido)) elegido = clave(visibles[0]);
  const ahora = new Date();
  const ul = nodo('ul', 'interesados__lista');
  ul.append(...visibles.map((i) => fila(i, ahora)));
  lista.replaceChildren(ul);
  pintarDetalle(visibles.find((i) => clave(i) === elegido));
}

function pintarFiltro() {
  const loteos = loteosDe(estado.interesados);
  const nav = $('#interesados-filtro');
  nav.hidden = loteos.length < 2;
  if (nav.hidden) return;
  const opcion = (slug, texto, nuevos) => {
    const boton = nodo('button', null, texto);
    boton.type = 'button';
    boton.dataset.loteo = slug ?? '';
    boton.setAttribute('aria-pressed', String((slug ?? null) === filtro.loteo));
    if (nuevos) boton.append(nodo('span', 'filtro-loteos__cuenta', nuevos));
    return boton;
  };
  const total = loteos.reduce((suma, l) => suma + l.nuevos, 0);
  nav.replaceChildren(opcion(null, 'Todos', total), ...loteos.map((l) => opcion(l.slug, l.nombre, l.nuevos)));
}

// --- Todo con textContent: lo escribió alguien de afuera ------------------------------

function nodo(etiqueta, clase, texto) {
  const elemento = document.createElement(etiqueta);
  if (clase) elemento.className = clase;
  if (texto != null) elemento.textContent = texto;
  return elemento;
}

function insignia(cual) {
  return nodo('span', `insignia-interes insignia-interes--${cual}`, ESTADOS[cual] ?? cual);
}

function fila(interesado, ahora) {
  const item = nodo('li', `interesado-fila interesado-fila--${interesado.estado}`);
  const boton = nodo('button');
  boton.type = 'button';
  boton.dataset.interesado = clave(interesado);
  boton.setAttribute('aria-pressed', String(clave(interesado) === elegido));
  const quien = nodo('span', 'interesado-fila__quien');
  quien.append(nodo('strong', null, interesado.nombre), nodo('small', null, detalleDeContacto(interesado)));
  const parcela = nodo('span', 'interesado-fila__parcela');
  parcela.append(nodo('strong', null, interesado.parcela), nodo('small', null, interesado.loteo));
  boton.append(
    nodo('span', 'interesado-fila__cuando', haceCuanto(interesado.creado_en, ahora)),
    quien, parcela, insignia(interesado.estado),
    nodo('span', 'interesado-fila__responsable', interesado.responsable || 'Sin asignar'),
  );
  item.append(boton);
  return item;
}

function pintarDetalle(interesado) {
  const panel = $('#interesado');
  panel.hidden = !interesado;
  if (!interesado) return;
  // Guardar el estado repinta el panel: una nota a medio escribir no se pierde.
  const borrador = panel.dataset.de === clave(interesado) ? panel.querySelector('textarea')?.value : null;
  panel.dataset.de = clave(interesado);

  const cabeza = nodo('div', 'interesado__cabeza');
  cabeza.append(insignia(interesado.estado), nodo('h2', null, interesado.nombre),
                nodo('p', null, `Parcela ${interesado.parcela} · ${interesado.loteo}`));

  const contactos = nodo('div', 'interesado__contactos');
  contactos.append(enlace(enlaceWhatsapp(interesado), 'WhatsApp', 'boton boton--whatsapp', true),
                   enlace(`tel:+${interesado.telefono}`, 'Llamar', 'boton boton--contorno'));
  const datos = nodo('dl', 'interesado__datos');
  const dato = (rotulo, valor) => {
    const div = nodo('div');
    div.append(nodo('dt', null, rotulo), nodo('dd', null, valor));
    return div;
  };
  datos.append(dato('Teléfono', telefonoLegible(interesado.telefono)));
  if (interesado.email) datos.append(dato('Correo', interesado.email));
  datos.append(dato('Llamar', HORARIO[interesado.horario] ?? 'a cualquier hora'),
               dato('Llegó', FECHA.format(new Date(interesado.creado_en))));

  // Estado: se guarda al elegirlo, como en una planilla.
  const selector = nodo('select');
  selector.id = 'interesado-estado';
  for (const [valor, texto] of Object.entries(ESTADOS)) {
    const opcion = nodo('option', null, texto);
    opcion.value = valor;
    opcion.selected = valor === interesado.estado;
    selector.append(opcion);
  }
  selector.addEventListener('change', () => guardar(interesado, { estado: selector.value }, 'Estado guardado.'));

  const responsable = nodo('input');
  responsable.id = 'interesado-responsable';
  responsable.maxLength = 60;
  responsable.placeholder = 'Sin asignar';
  responsable.value = interesado.responsable;
  responsable.setAttribute('list', 'interesado-responsables');
  const sugeridos = nodo('datalist');
  sugeridos.id = 'interesado-responsables';
  sugeridos.append(...responsables(estado.interesados).map((r) => Object.assign(nodo('option'), { value: r })));
  responsable.addEventListener('change', () => guardar(interesado, { responsable: responsable.value }, 'Responsable guardado.'));

  const nota = nodo('textarea');
  nota.id = 'interesado-nota';
  nota.rows = 3;
  nota.maxLength = 2000;
  nota.placeholder = 'Ej.: quiere visitar el sábado';
  nota.value = borrador ?? interesado.nota;
  const guardarNota = nodo('button', 'boton boton--contorno interesado__guardar', 'Guardar nota');
  guardarNota.type = 'button';
  guardarNota.addEventListener('click', () => guardar(interesado, { nota: nota.value }, 'Nota guardada.'));

  const campos = nodo('div', 'interesado__campos');
  campos.append(campo('Estado', selector), campo('Responsable', responsable, sugeridos));
  const zonaNota = nodo('div', 'interesado__nota');
  zonaNota.append(campo('Nota', nota), guardarNota);

  panel.replaceChildren(cabeza, contactos, datos, campos, zonaNota,
                        nodo('p', 'nota', 'Datos escritos por el comprador en el sitio, sin verificar.'));
}

function campo(rotulo, control, ...extra) {
  const etiqueta = nodo('label', 'interesado__campo');
  etiqueta.append(nodo('span', null, rotulo), control, ...extra);
  return etiqueta;
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
  const filtrando = filtro.loteo || filtro.estado;
  caja.append(nodo('strong', null, filtrando ? 'Nadie con este filtro' : 'Todavía no llegan interesados'),
              nodo('p', null, 'Cuando alguien toque «Me interesa esta parcela» en uno de tus sitios publicados, '
                + 'aparece acá y te llega un correo.'));
  return caja;
}
