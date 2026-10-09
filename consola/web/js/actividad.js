/**
 * Configuración → Actividad: lo que pasó en la loteadora, quién y cuándo.
 *
 * Cada evento del historial se cuenta como una frase ("Pía publicó Praderas") con un
 * tipo que le da color: masters, reservas, equipo, marca o cuenta. Se agrupan por día
 * y se piden de a partes hacia atrás con "Ver más".
 */
import { $, avisar, pedir } from './comun.js';

const POR_PARTE = 30;

// que → [lo que hizo, tipo]. `{d}` es el detalle del evento.
const FRASES = {
  'master creado': ['creó el master {d}', 'master'],
  'master quitado': ['quitó el master {d}', 'master'],
  'construcción': ['construyó {d}', 'master'],
  'publicación': ['publicó {d}', 'publicado'],
  'loteo habilitado': ['habilitó para publicar {d}', 'publicado'],
  'loteo pagado': ['anotó el pago de {d}', 'publicado'],
  'reserva confirmada': ['confirmó la reserva de la {d}', 'reserva'],
  'reserva liberada': ['liberó la {d}', 'reserva'],
  'diseño creado': ['creó el diseño {d}', 'marca'],
  'diseño borrado': ['borró el diseño {d}', 'marca'],
  'invitación al equipo': ['invitó a {d}', 'equipo'],
  'cuenta desactivada': ['desactivó a {d}', 'equipo'],
  'cuenta reactivada': ['reactivó a {d}', 'equipo'],
  'alta de cuenta': ['creó la cuenta de {d}', 'equipo'],
  'clave provisional nueva': ['le dio una contraseña provisional a {d}', 'cuenta'],
  'loteadora renombrada': ['renombró la loteadora a «{d}»', 'cuenta'],
  'preferencias cambiadas': ['cambió Reservas y contacto', 'cuenta'],
  'contraseña cambiada': ['cambió su contraseña', 'cuenta'],
  'sesiones cerradas': ['cerró todas sus sesiones', 'cuenta'],
  'alta de loteadora': ['creó la loteadora', 'cuenta'],
};

/** El nombre corto de quien lo hizo: "Pía Soto" → "Pía"; sin nombre, el correo. */
function nombreCorto(quien) {
  return String(quien?.nombre ?? '').trim().split(/\s+/)[0] || quien?.email || 'Alguien';
}

/** La frase de un evento y su tipo, para el color. */
export function fraseDe(evento) {
  // Lo pide un comprador desde el sitio: no hay persona de la loteadora detrás.
  if (evento.que === 'reserva pedida') {
    return { texto: `Un comprador pidió reservar la ${evento.detalle}`, tipo: 'reserva', quien: null };
  }
  const conocida = FRASES[evento.que];
  const quien = evento.quien ? nombreCorto(evento.quien) : 'Tu Masterplan';
  if (!conocida) {
    return { texto: `${quien}: ${evento.que}${evento.detalle ? ` · ${evento.detalle}` : ''}`, tipo: 'cuenta', quien };
  }
  const [hizo, tipo] = conocida;
  return { texto: `${quien} ${hizo.replace('{d}', evento.detalle ?? '')}`.trim(), tipo, quien };
}

function dia(fecha) {
  return new Date(fecha.getFullYear(), fecha.getMonth(), fecha.getDate()).getTime();
}

const DIA = new Intl.DateTimeFormat('es-CL', { weekday: 'long', day: 'numeric', month: 'long' });
const HORA = new Intl.DateTimeFormat('es-CL', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

/** "Hoy", "Ayer" o "Martes 6 de octubre". */
export function nombreDelDia(fecha, ahora = new Date()) {
  const diferencia = Math.round((dia(ahora) - dia(fecha)) / 86_400_000);
  if (diferencia === 0) return 'Hoy';
  if (diferencia === 1) return 'Ayer';
  // Sin la coma que pone es-CL después del día de la semana: es un título.
  const texto = DIA.format(fecha).replace(',', '');
  return texto[0].toUpperCase() + texto.slice(1);
}

/** Los eventos (más nuevos primero) en grupos por día, en el mismo orden. */
export function agruparPorDia(eventos, ahora = new Date()) {
  const grupos = [];
  for (const evento of eventos) {
    const fecha = new Date(evento.cuando);
    const titulo = nombreDelDia(fecha, ahora);
    if (grupos.at(-1)?.titulo !== titulo) grupos.push({ titulo, eventos: [] });
    grupos.at(-1).eventos.push(evento);
  }
  return grupos;
}

// --- La pantalla ----------------------------------------------------------------------

let eventos = [];
let quedanMas = false;

export function prepararActividad() {
  $('#actividad-mas').addEventListener('click', () => cargar({ mas: true }));
}

export async function pintarActividad() {
  await cargar({ mas: false });
}

async function cargar({ mas }) {
  const boton = $('#actividad-mas');
  boton.disabled = true;
  try {
    const antes = mas && eventos.length ? `&antes=${eventos.at(-1).id}` : '';
    const nuevos = await pedir(`/api/actividad?limite=${POR_PARTE}${antes}`);
    eventos = mas ? [...eventos, ...nuevos] : nuevos;
    quedanMas = nuevos.length === POR_PARTE;
    pintar();
  } catch (error) {
    avisar(error.message);
  } finally {
    boton.disabled = false;
  }
}

function pintar() {
  const lista = $('#actividad-lista');
  $('#actividad-vacia').hidden = eventos.length > 0;
  $('#actividad-mas').hidden = !quedanMas;
  lista.replaceChildren(...agruparPorDia(eventos).map(({ titulo, eventos: delDia }) => {
    const grupo = document.createElement('li');
    grupo.className = 'actividad__dia';
    const cabeza = document.createElement('h3');
    cabeza.textContent = titulo;
    const items = document.createElement('ol');
    items.className = 'actividad__eventos';
    items.append(...delDia.map((evento, orden) => {
      const { texto, tipo } = fraseDe(evento);
      const item = document.createElement('li');
      item.className = `evento evento--${tipo}`;
      item.style.setProperty('--orden', Math.min(orden, 8));
      const punto = document.createElement('i');
      punto.className = 'evento__punto';
      punto.setAttribute('aria-hidden', 'true');
      const frase = document.createElement('p');
      frase.textContent = texto;
      const hora = document.createElement('time');
      hora.dateTime = evento.cuando;
      hora.textContent = HORA.format(new Date(evento.cuando));
      item.append(punto, frase, hora);
      return item;
    }));
    grupo.append(cabeza, items);
    return grupo;
  }));
}
