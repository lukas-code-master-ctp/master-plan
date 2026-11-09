/**
 * "Me interesa esta parcela": el comprador deja nombre y teléfono y la loteadora lo
 * sigue desde la consola. A diferencia de reservar, no aparta nada ni lleva a pagar,
 * así que sirve también a quien todavía no está listo para comprar.
 *
 * Como la reserva, solo aparece si el sitio sabe a qué consola pedir.
 */

const HORARIOS = ['manana', 'tarde', ''];

/** Lo que se le manda a la consola. En texto plano: así el navegador no pregunta antes. */
export function cuerpoInteres(meta, parcela, campos) {
  const horario = String(campos.horario ?? '');
  return JSON.stringify({
    loteo: meta.loteo,
    parcela: parcela.id,
    nombre: String(campos.nombre ?? '').trim(),
    telefono: String(campos.telefono ?? '').trim(),
    email: String(campos.email ?? '').trim(),
    horario: HORARIOS.includes(horario) ? horario : '',
    sitio: String(campos.sitio ?? ''),
  });
}

/** Qué decirle al comprador si no se pudo enviar. */
export function mensajeDeErrorInteres(estado, detalle) {
  if (estado === 400 && detalle) return detalle;
  if (estado === 429) return 'Enviaste varios seguidos. Prueba en un rato o escríbenos por WhatsApp.';
  return 'No pudimos enviar tus datos. Prueba de nuevo o escríbenos por WhatsApp.';
}

/** Manda los datos. Devuelve { ok, estado, datos }; sin red, estado 0. */
export async function enviarInteres(meta, parcela, campos, pedir = fetch) {
  try {
    const respuesta = await pedir(`${meta.consola.replace(/\/$/, '')}/api/publico/interesados`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      credentials: 'omit',
      body: cuerpoInteres(meta, parcela, campos),
    });
    const datos = await respuesta.json().catch(() => ({}));
    return { ok: respuesta.ok, estado: respuesta.status, datos };
  } catch {
    return { ok: false, estado: 0, datos: {} };
  }
}

/** Abre el formulario de una parcela. `alEnviar()` avisa que quedó enviado. */
export function abrirInteres(dialogo, { catalogo, parcela, alEnviar = () => {} }) {
  const formulario = dialogo.querySelector('form');
  const error = dialogo.querySelector('#interes-error');
  const listo = dialogo.querySelector('#interes-listo');
  const enviar = dialogo.querySelector('#interes-enviar');
  const cancelar = dialogo.querySelector('[data-accion="cancelar"]');
  dialogo.querySelector('#interes-parcela').textContent = catalogo.titulo(parcela);
  formulario.reset();
  formulario.classList.remove('reserva--lista');
  error.hidden = true;
  listo.hidden = true;
  enviar.hidden = false;
  enviar.disabled = false;
  cancelar.textContent = 'Cancelar';

  formulario.onsubmit = async (evento) => {
    evento.preventDefault();
    if (!formulario.reportValidity()) return;
    enviar.disabled = true;
    enviar.textContent = 'Enviando…';
    const campos = Object.fromEntries(new FormData(formulario));
    const { ok, estado, datos } = await enviarInteres(catalogo.meta, parcela, campos);
    enviar.textContent = 'Enviar';
    if (ok) {
      formulario.classList.add('reserva--lista');
      enviar.hidden = true;
      cancelar.textContent = 'Cerrar';
      listo.textContent = 'Listo: le llegaron tus datos a la loteadora y te van a contactar.';
      listo.hidden = false;
      alEnviar();
      return;
    }
    enviar.disabled = false;
    error.textContent = mensajeDeErrorInteres(estado, datos.detail);
    error.hidden = false;
  };
  cancelar.onclick = () => dialogo.close();
  dialogo.showModal();
  formulario.elements.nombre.focus();
}
