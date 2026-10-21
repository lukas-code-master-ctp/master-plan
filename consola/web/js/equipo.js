/**
 * Configuración → Tu cuenta y Equipo.
 *
 * El perfil propio (nombre, la loteadora, contraseña y sesiones) y quién más entra a
 * la loteadora. Invitar y desactivar lo hace el dueño; el servidor lo controla igual
 * (rutas_equipo.py): acá solo no se ofrece lo que no se puede.
 */
import { $, abrirDialogo, avisar, json, pedir } from './comun.js';
import { pintarEsqueleto, tituloEsqueleto } from './esqueleto.js';

const ROLES = { 'dueño': 'Dueño', equipo: 'Equipo', plataforma: 'Operación CTP' };

let cuenta = null;   // lo que contestó GET /api/cuenta

/** Las personas del equipo y, detrás, las invitaciones que nadie ha aceptado. */
export function equipoConInvitaciones({ equipo, invitaciones = [] }) {
  return [...equipo, ...invitaciones.map((i) => ({ ...i, invitacion: true, activo: true, yo: false }))];
}

/** "Pía Soto Rivas" → "PS"; sin nombre, del correo: "tomas@x.cl" → "T". */
export function inicialesDe({ nombre, email }) {
  const palabras = String(nombre ?? '').trim().split(/\s+/).filter(Boolean);
  if (palabras.length) return palabras.slice(0, 2).map((p) => p[0].toUpperCase()).join('');
  return (String(email ?? '')[0] ?? '?').toUpperCase();
}

/** Un tono fijo por persona, para que cada avatar se reconozca de un vistazo. */
export function tonoDe(email) {
  let suma = 0;
  for (const letra of String(email ?? '')) suma = (suma * 31 + letra.charCodeAt(0)) % 360;
  return suma;
}

/** Las fichas al lado del nombre de un miembro, en orden de importancia. */
export function fichasDe(miembro) {
  // Una invitación no es todavía alguien del equipo: no tiene rol hasta que acepta.
  if (miembro.invitacion) {
    return [miembro.vencida
      ? { texto: 'Invitación vencida', tono: 'apagada' }
      : { texto: 'Invitación enviada', tono: 'aviso' }];
  }
  const fichas = [{ texto: ROLES[miembro.rol] ?? miembro.rol, tono: miembro.rol === 'dueño' ? 'tinta' : '' }];
  if (miembro.yo) fichas.push({ texto: 'Tú', tono: '' });
  if (!miembro.activo) fichas.push({ texto: 'Desactivada', tono: 'apagada' });
  else if (miembro.pendiente) fichas.push({ texto: 'Sin entrar todavía', tono: 'aviso' });
  return fichas;
}

/** Primero quien mira, después los activos por nombre, las invitaciones sin aceptar
 * y al final los desactivados. */
export function ordenarEquipo(equipo) {
  const peso = (m) => (m.yo ? 0 : m.invitacion ? 2 : m.activo ? 1 : 3);
  return [...equipo].sort((a, b) => peso(a) - peso(b)
    || (a.nombre || a.email).localeCompare(b.nombre || b.email, 'es'));
}

export function prepararEquipo() {
  const form = $('#perfil-form');
  form.addEventListener('input', () => { $('#perfil-guardar').disabled = !cambiosDelPerfil(); });
  form.addEventListener('submit', (evento) => { evento.preventDefault(); guardarPerfil(); });
  $('#seguridad-clave').addEventListener('click', () => {
    $('#clave-actual').value = '';
    $('#clave-nueva').value = '';
    abrirDialogo($('#clave'));
  });
  $('#seguridad-sesiones').addEventListener('click', cerrarSesiones);
  $('#equipo-invitar').addEventListener('submit', (evento) => { evento.preventDefault(); invitar(); });
  $('#equipo-lista').addEventListener('click', (evento) => {
    const anular = evento.target.closest('[data-anular]');
    if (anular) {
      anularInvitacion(Number(anular.dataset.anular));
      return;
    }
    const boton = evento.target.closest('[data-estado]');
    if (boton) cambiarEstado(Number(boton.dataset.id), boton.dataset.estado === 'activar');
  });
  $('#equipo-enlace-copiar').addEventListener('click', copiarEnlace);
}

export async function pintarEquipo({ animar = false } = {}) {
  // La primera vez la lista está vacía: mientras llega, su forma. Después se deja lo que hay.
  if (!cuenta) {
    pintarEsqueleto('equipo-lista');
    tituloEsqueleto($('#perfil-nombre'), { ancho: 'min(12rem, 40vw)', clase: 'esqueleto--titulo' });
    tituloEsqueleto($('#perfil-email'), { ancho: 'min(16rem, 50vw)', clase: 'esqueleto--linea' });
    $('#perfil-rol').hidden = true;
  }
  try {
    pintar(await pedir('/api/cuenta'), { animar });
  } catch (error) {
    avisar(error.message);
  }
}

function pintar(datos, { animar = false } = {}) {
  cuenta = datos;
  $('#perfil-iniciales').textContent = inicialesDe(datos);
  $('#perfil-iniciales').style.setProperty('--tono', tonoDe(datos.email));
  $('#perfil-nombre').textContent = datos.nombre || datos.email;
  $('#perfil-email').textContent = datos.email;
  $('#perfil-rol').textContent = ROLES[datos.rol] ?? datos.rol;
  $('#perfil-rol').hidden = false;
  $('#perfil-rol').className = `chip${datos.rol === 'dueño' ? ' chip--tinta' : ''}`;
  $('#perfil-google').hidden = !datos.google;
  $('#seguridad-clave-nota').textContent = datos.google
    ? 'Entras con Google, así que no la necesitas. Si la cambias, se cierran todas tus sesiones.'
    : 'Al cambiarla se cierran todas tus sesiones.';

  const form = $('#perfil-form');
  form.elements.nombre.value = datos.nombre;
  form.elements.loteadora.value = datos.loteadora;
  form.elements.loteadora.disabled = !datos.administra;
  $('#perfil-nota-loteadora').hidden = datos.administra;
  $('#perfil-guardar').disabled = true;

  pintarMiembros(equipoConInvitaciones(datos), datos.administra, animar);
  $('#equipo-invitar').hidden = !datos.administra;
  $('#equipo-solo-duenio').hidden = datos.administra;
}

function pintarMiembros(equipo, administra, animar) {
  const activos = equipo.filter((m) => m.activo && !m.invitacion).length;
  $('#equipo-cantidad').textContent = String(activos);
  const lista = $('#equipo-lista');
  const movimiento = animar && !matchMedia('(prefers-reduced-motion: reduce)').matches;
  lista.classList.toggle('miembros--entrando', movimiento);
  lista.replaceChildren(...ordenarEquipo(equipo).map((miembro, orden) => {
    const li = document.createElement('li');
    li.className = `miembro${miembro.activo && !miembro.vencida ? '' : ' miembro--apagado'}`;
    li.style.setProperty('--orden', orden);
    const avatar = document.createElement('span');
    avatar.className = 'miembro__avatar';
    avatar.style.setProperty('--tono', tonoDe(miembro.email));
    avatar.textContent = inicialesDe(miembro);
    const quien = document.createElement('span');
    quien.className = 'miembro__quien';
    const nombre = document.createElement('strong');
    nombre.textContent = miembro.nombre || miembro.email;
    const email = document.createElement('small');
    email.textContent = miembro.email;
    quien.append(nombre, email);
    const fichas = document.createElement('span');
    fichas.className = 'miembro__fichas';
    fichas.append(...fichasDe(miembro).map(({ texto, tono }) => {
      const ficha = document.createElement('span');
      ficha.className = `chip${tono ? ` chip--${tono}` : ''}`;
      ficha.textContent = texto;
      return ficha;
    }));
    li.append(avatar, quien, fichas);
    if (administra && miembro.invitacion) {
      const boton = document.createElement('button');
      boton.type = 'button';
      boton.className = 'boton boton--texto boton--peligro';
      boton.dataset.anular = miembro.id;
      boton.textContent = 'Anular';
      li.append(boton);
    } else if (administra && !miembro.yo) {
      const boton = document.createElement('button');
      boton.type = 'button';
      boton.className = `boton boton--texto${miembro.activo ? ' boton--peligro' : ''}`;
      boton.dataset.id = miembro.id;
      boton.dataset.estado = miembro.activo ? 'desactivar' : 'activar';
      boton.textContent = miembro.activo ? 'Desactivar' : 'Reactivar';
      li.append(boton);
    }
    return li;
  }));
}

function cambiosDelPerfil() {
  if (!cuenta) return null;
  const form = $('#perfil-form');
  const cambios = {};
  const nombre = form.elements.nombre.value.trim();
  const loteadora = form.elements.loteadora.value.trim();
  if (nombre !== cuenta.nombre) cambios.nombre = nombre;
  if (cuenta.administra && loteadora !== cuenta.loteadora) cambios.loteadora = loteadora;
  return Object.keys(cambios).length ? cambios : null;
}

async function guardarPerfil() {
  const cambios = cambiosDelPerfil();
  if (!cambios) return;
  if (Object.values(cambios).some((valor) => !valor)) {
    avisar('El nombre no puede quedar vacío.');
    return;
  }
  const boton = $('#perfil-guardar');
  boton.disabled = true;
  try {
    pintar(await pedir('/api/cuenta', json(cambios, 'PATCH')));
    avisar('Listo, quedó guardado.', 'ok');
  } catch (error) {
    boton.disabled = false;
    avisar(error.message);
  }
}

async function cerrarSesiones() {
  if (!confirm('¿Cerrar todas tus sesiones? También esta: vuelves a entrar con tu correo.')) return;
  try {
    await pedir('/api/cuenta/sesiones/cerrar', json({}));
    location.href = '/entrar';
  } catch (error) {
    avisar(error.message);
  }
}

async function invitar() {
  const nombre = $('#invitar-nombre').value.trim();
  const email = $('#invitar-email').value.trim();
  if (!nombre || !email) {
    avisar('Escribe el nombre y el correo de quien invitas.');
    return;
  }
  const boton = $('#invitar-boton');
  boton.disabled = true;
  try {
    const respuesta = await pedir('/api/equipo', json({ nombre, email }));
    $('#invitar-nombre').value = '';
    $('#invitar-email').value = '';
    mostrarEnlace(respuesta.invitacion === 'enlace' ? { quien: nombre, enlace: respuesta.enlace } : null);
    if (respuesta.invitacion === 'correo') avisar(`Listo: le mandamos la invitación a ${respuesta.email}.`, 'ok');
    pintar(await pedir('/api/cuenta'));
  } catch (error) {
    avisar(error.message);
  } finally {
    boton.disabled = false;
  }
}

/** Sin correo que llegue, el dueño entrega el enlace. El servidor lo manda sin
 * dominio: se completa con el de esta página. */
function mostrarEnlace(invitacion) {
  $('#equipo-enlace').hidden = !invitacion;
  $('#equipo-enlace-quien').textContent = invitacion?.quien ?? '';
  $('#equipo-enlace-texto').textContent = invitacion ? new URL(invitacion.enlace, location.origin).href : '';
  $('#equipo-enlace-copiar').textContent = 'Copiar';
}

async function copiarEnlace() {
  try {
    await navigator.clipboard.writeText($('#equipo-enlace-texto').textContent);
    $('#equipo-enlace-copiar').textContent = 'Copiado';
  } catch {
    avisar('No se pudo copiar: selecciónalo y cópialo a mano.');
  }
}

async function anularInvitacion(id) {
  const invitacion = cuenta?.invitaciones?.find((i) => i.id === id);
  if (!invitacion) return;
  if (!confirm(`¿Anular la invitación a ${invitacion.nombre || invitacion.email}? El enlace deja de servir.`)) return;
  try {
    await pedir(`/api/equipo/invitaciones/${id}`, { method: 'DELETE' });
    pintar(await pedir('/api/cuenta'));
  } catch (error) {
    avisar(error.message);
  }
}

async function cambiarEstado(id, activar) {
  const miembro = cuenta?.equipo.find((m) => m.id === id);
  if (!miembro) return;
  if (!activar && !confirm(`¿Desactivar a ${miembro.nombre || miembro.email}? Deja de entrar en el acto;`
    + ' puedes reactivarla después.')) return;
  try {
    await pedir(`/api/equipo/${id}/estado`, json({ activo: activar }));
    pintar(await pedir('/api/cuenta'));
  } catch (error) {
    avisar(error.message);
  }
}
