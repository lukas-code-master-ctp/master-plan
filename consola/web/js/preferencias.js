/**
 * Configuración → Reservas y contacto.
 *
 * El WhatsApp con que nacen los masters, el diseño que Nuevo master ofrece primero y
 * cuánto queda apartada una parcela. Lo cambia el dueño (rutas_preferencias.py); el
 * equipo lo ve sin poder tocarlo.
 */
import { $, avisar, estado, horas, json, pedir } from './comun.js';
import { opcionesDeDiseno } from './disenos.js';

// Las que se ofrecen: de una hora (pago al toque) a dos días (transferencia lenta).
const OPCIONES_HORAS = [1, 2, 4, 12, 24, 48];

let guardadas = null;   // lo que contestó el servidor la última vez

export function prepararPreferencias() {
  $('#preferencias-horas').replaceChildren(...OPCIONES_HORAS.map((cantidad) => {
    const etiqueta = document.createElement('label');
    etiqueta.className = 'hora';
    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = 'horas_apartado';
    radio.value = String(cantidad);
    const numero = document.createElement('strong');
    numero.textContent = String(cantidad);
    const unidad = document.createElement('small');
    unidad.textContent = cantidad === 1 ? 'hora' : 'horas';
    etiqueta.append(radio, numero, unidad);
    return etiqueta;
  }));
  const form = $('#preferencias-form');
  form.addEventListener('input', () => { $('#preferencias-guardar').disabled = !cambios(); });
  form.addEventListener('change', () => { $('#preferencias-guardar').disabled = !cambios(); });
  form.addEventListener('submit', (evento) => { evento.preventDefault(); guardar(); });
}

export async function pintarPreferencias() {
  try {
    // Al entrar directo a Configuración, la lista de diseños puede no haber llegado.
    const [preferencias, disenos] = await Promise.all([
      pedir('/api/preferencias'), estado.disenos.length ? estado.disenos : pedir('/api/disenos')]);
    estado.disenos = disenos;
    pintar(preferencias);
  } catch (error) {
    avisar(error.message);
  }
}

function pintar(preferencias) {
  guardadas = preferencias;
  estado.sesion = { ...estado.sesion, preferencias };
  const form = $('#preferencias-form');
  form.elements.whatsapp.value = preferencias.whatsapp ? `+${preferencias.whatsapp}` : '';
  opcionesDeDiseno($('#preferencias-diseno'), preferencias.diseno_id);
  // Si las horas guardadas no están entre las ofrecidas (se fijaron a mano), igual se ven.
  const radio = form.querySelector(`input[name="horas_apartado"][value="${preferencias.horas_apartado}"]`);
  for (const opcion of form.querySelectorAll('input[name="horas_apartado"]')) opcion.checked = opcion === radio;
  $('#preferencias-campos').disabled = !preferencias.administra;
  $('#preferencias-solo-duenio').hidden = preferencias.administra;
  $('#preferencias-guardar').hidden = !preferencias.administra;
  $('#preferencias-guardar').disabled = true;
}

function cambios() {
  if (!guardadas) return null;
  const form = $('#preferencias-form');
  const nuevos = {};
  const whatsapp = form.elements.whatsapp.value.replace(/\D/g, '');
  if (whatsapp !== guardadas.whatsapp) nuevos.whatsapp = form.elements.whatsapp.value.trim();
  const diseno = form.elements.diseno_id.value ? Number(form.elements.diseno_id.value) : null;
  if (diseno !== guardadas.diseno_id) nuevos.diseno_id = diseno;
  const elegida = form.querySelector('input[name="horas_apartado"]:checked');
  if (elegida && Number(elegida.value) !== guardadas.horas_apartado) nuevos.horas_apartado = Number(elegida.value);
  return Object.keys(nuevos).length ? nuevos : null;
}

async function guardar() {
  const nuevos = cambios();
  if (!nuevos) return;
  const boton = $('#preferencias-guardar');
  boton.disabled = true;
  try {
    pintar(await pedir('/api/preferencias', json(nuevos, 'PATCH')));
    avisar(`Listo. Las parcelas se apartan por ${horas(guardadas.horas_apartado)}.`, 'ok');
  } catch (error) {
    boton.disabled = false;
    avisar(error.message);
  }
}
