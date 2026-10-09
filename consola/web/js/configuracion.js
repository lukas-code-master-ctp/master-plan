/**
 * Configuración: lo que se deja listo una vez y vale para todos los masters.
 *
 * Tu cuenta y el equipo viven en equipo.js, Reservas y contacto en preferencias.js y
 * Actividad en actividad.js; acá, el índice de la izquierda y la integración con Cierra. La clave de API es de la loteadora, no de un
 * master: se pega acá una sola vez, se guarda cifrada y solo se muestran sus
 * últimos caracteres. Después, en cada master solo se elige el proyecto.
 */
import { $, $$, avisar, fecha, json, pedir } from './comun.js';
import { pintarEquipo, prepararEquipo } from './equipo.js';
import { pintarPreferencias, prepararPreferencias } from './preferencias.js';
import { pintarActividad, prepararActividad } from './actividad.js';

let actual = null;   // lo que contestó GET /api/cierra

export function prepararConfiguracion() {
  prepararEquipo();
  prepararPreferencias();
  prepararActividad();
  prepararIndice();
  $('#config-cierra-guardar').addEventListener('click', guardar);
  $('#config-cierra-cambiar').addEventListener('click', () => pintar(actual, { editando: true }));
  $('#config-cierra-cancelar').addEventListener('click', () => pintar(actual));
  $('#config-cierra-quitar').addEventListener('click', quitar);
  $('#config-cierra-clave').addEventListener('keydown', (evento) => {
    if (evento.key === 'Enter') guardar();
  });
}

export async function pintarConfiguracion({ animar = false } = {}) {
  pintarEquipo({ animar });
  pintarPreferencias();
  pintarActividad();
  try {
    pintar(await pedir('/api/cierra'));
  } catch (error) {
    avisar(error.message);
  }
}

function pintar(estado, { editando = false } = {}) {
  actual = estado;
  const caja = $('#config-cierra');
  const pastilla = $('#config-cierra-pastilla');
  $('#config-cierra-clave').value = '';
  if (!estado?.disponible) {
    pastilla.textContent = 'No disponible';
    pastilla.className = 'pastilla';
    $('#config-cierra-estado').textContent = 'La integración con Cierra todavía no está activa en esta consola.';
    $('#config-cierra-formulario').hidden = true;
    $('#config-cierra-conectada').hidden = true;
    return;
  }
  const conectada = Boolean(estado.pista);
  pastilla.textContent = conectada ? 'Conectada' : 'Sin conectar';
  pastilla.className = conectada ? 'pastilla pastilla--ok' : 'pastilla pastilla--aviso';
  $('#config-cierra-estado').textContent = conectada
    ? `Con la clave que termina en …${estado.pista}`
      + (estado.desde ? `, guardada el ${fecha(estado.desde)}.` : '.')
      + ' En cada master solo eliges el proyecto de Cierra.'
    : 'Pega la clave una sola vez: sirve para todos tus masters.';
  $('#config-cierra-formulario').hidden = conectada && !editando;
  $('#config-cierra-conectada').hidden = !conectada || editando;
  $('#config-cierra-guardar').textContent = conectada ? 'Guardar la clave nueva' : 'Conectar';
  $('#config-cierra-cancelar').hidden = !(conectada && editando);
  caja.dataset.conectada = String(conectada);
  if (editando) $('#config-cierra-clave').focus();
}

async function guardar() {
  const entrada = $('#config-cierra-clave');
  const clave = entrada.value.trim();
  if (!clave) return avisar('Pega la clave de API de Cierra.');
  const boton = $('#config-cierra-guardar');
  boton.disabled = true;
  try {
    avisar(null);
    // Se prueba contra Cierra antes de guardarla: una clave mala no queda guardada.
    await pedir('/api/cierra/clave', json({ clave }, 'PUT'));
    pintar(await pedir('/api/cierra'));
  } catch (error) {
    avisar(error.message);
  } finally {
    entrada.value = '';
    boton.disabled = false;
  }
  return undefined;
}

async function quitar() {
  if (!confirm('¿Quitar la clave de Cierra? Los masters conectados dejan de traer los estados '
    + 'y precios de Cierra (se quedan con los últimos que llegaron).')) return;
  try {
    await pedir('/api/cierra/clave', { method: 'DELETE' });
    pintar(await pedir('/api/cierra'));
  } catch (error) {
    avisar(error.message);
  }
}

// --- El índice ---------------------------------------------------------------------

/**
 * Botones y no enlaces `#…`: el hash es de las rutas de la app. La sección que se
 * está leyendo queda marcada mientras se baja, para saber dónde se está.
 */
function prepararIndice() {
  const botones = $$('.config__indice [data-ir]');
  for (const boton of botones) {
    boton.addEventListener('click', () => {
      const destino = $(`#${boton.dataset.ir}`);
      const quieto = matchMedia('(prefers-reduced-motion: reduce)').matches;
      destino.scrollIntoView({ behavior: quieto ? 'auto' : 'smooth', block: 'start' });
      marcar(boton.dataset.ir);
    });
  }
  const marcar = (id) => {
    for (const boton of botones) boton.toggleAttribute('aria-current', boton.dataset.ir === id);
  };
  const observador = new IntersectionObserver((entradas) => {
    // Al fondo de la página la última sección no alcanza a subir hasta la franja
    // que se mira: si ya no se puede bajar más, es esa la que se está leyendo.
    const alFondo = innerHeight + scrollY >= document.documentElement.scrollHeight - 4;
    if (alFondo) { marcar(botones.at(-1).dataset.ir); return; }
    const visible = entradas.filter((e) => e.isIntersecting)
      .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
    if (visible) marcar(visible.target.id);
  }, { rootMargin: '-20% 0px -60% 0px', threshold: [0, 0.5, 1] });
  for (const boton of botones) observador.observe($(`#${boton.dataset.ir}`));
  // Un salto suave termina después del último aviso del observador: al terminar
  // de moverse se mira de nuevo si quedó al fondo.
  addEventListener('scrollend', () => {
    if (innerHeight + scrollY >= document.documentElement.scrollHeight - 4) marcar(botones.at(-1).dataset.ir);
  });
}
