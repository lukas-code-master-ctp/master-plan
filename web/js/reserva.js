/**
 * Reservar una parcela antes de pagar.
 *
 * El link de pago del loteo no le avisa al Masterplan. Por eso, antes de ir ahí,
 * el comprador deja nombre, teléfono y correo: la consola aparta la parcela por un
 * rato, le escribe a la loteadora y contesta adónde ir a pagar. Mientras tanto,
 * todos ven la parcela como "Reserva en proceso".
 *
 * Solo pasa si el sitio sabe a qué consola pedir (`consola` y `loteo` en
 * parcelas.json, que escribe la publicación). Sin eso, el botón va directo al
 * link de pago, como antes.
 */

// Lo que se espera a la consola antes de mostrar el sitio sin apartadas: que
// tarde no puede dejar al comprador mirando una pantalla en blanco.
const ESPERA_APARTADAS_MS = 4000;

/** ¿Este sitio puede pedir reservas a su consola? */
export function conReservas(meta) {
  return Boolean(meta?.consola && meta?.loteo);
}

/**
 * Las parcelas con las apartadas encima: una disponible apartada pasa a
 * reservada ("Reserva en proceso"). Las demás no se tocan: si el inventario ya
 * la marcó, manda el inventario.
 */
export function aplicarApartadas(parcelas, apartadas) {
  return parcelas.map((parcela) => (parcela.id in apartadas && parcela.estado === 'disponible'
    ? { ...parcela, estado: 'reservado', apartada: true }
    : parcela));
}

/** Las apartadas según la consola, o ninguna si no hay consola o no contesta. */
export async function pedirApartadas(meta, pedir = fetch) {
  if (!conReservas(meta)) return {};
  const corte = typeof AbortController === 'undefined' ? null : new AbortController();
  const reloj = corte && setTimeout(() => corte.abort(), ESPERA_APARTADAS_MS);
  try {
    const url = `${meta.consola.replace(/\/$/, '')}/api/publico/apartadas?loteo=${encodeURIComponent(meta.loteo)}`;
    const respuesta = await pedir(url, corte ? { signal: corte.signal } : undefined);
    return respuesta?.ok ? await respuesta.json() : {};
  } catch {
    return {};
  } finally {
    if (reloj) clearTimeout(reloj);
  }
}

/** Lo que se le manda a la consola. En texto plano: así el navegador no pregunta antes. */
export function cuerpoSolicitud(meta, parcela, campos) {
  return JSON.stringify({
    loteo: meta.loteo,
    parcela: parcela.id,
    nombre: String(campos.nombre ?? '').trim(),
    telefono: String(campos.telefono ?? '').trim(),
    email: String(campos.email ?? '').trim(),
    sitio: String(campos.sitio ?? ''),
  });
}

/** Adónde ir a pagar: el link propio de la parcela (planilla) o el del loteo que contestó la consola. */
export function destinoDelPago(parcela, linkDelLoteo) {
  return parcela.link_pago || linkDelLoteo || null;
}

/** Qué decirle al comprador si no se pudo apartar. */
export function mensajeDeError(estado, detalle) {
  if ((estado === 400 || estado === 409) && detalle) return detalle;
  if (estado === 429) return 'Hiciste muchas solicitudes seguidas. Prueba en un rato o escríbenos por WhatsApp.';
  return 'No pudimos apartar la parcela. Prueba de nuevo o escríbenos por WhatsApp.';
}

/** Manda la solicitud. Devuelve { ok, estado, datos }; sin red, estado 0. */
export async function enviarSolicitud(meta, parcela, campos, pedir = fetch) {
  try {
    const respuesta = await pedir(`${meta.consola.replace(/\/$/, '')}/api/publico/reservas`, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: cuerpoSolicitud(meta, parcela, campos),
    });
    const datos = await respuesta.json().catch(() => ({}));
    return { ok: respuesta.ok, estado: respuesta.status, datos };
  } catch {
    return { ok: false, estado: 0, datos: {} };
  }
}

// En 24 horas, como se lee en Chile.
const HORA = new Intl.DateTimeFormat('es-CL', { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });

/** Lo que se le dice al comprador cuando quedó apartada sin link de pago. */
export function textoApartada(hasta) {
  const momento = hasta ? new Date(hasta) : null;
  const cuando = momento && !Number.isNaN(momento.getTime()) ? ` hasta las ${HORA.format(momento)}` : '';
  return `Listo: la parcela quedó apartada${cuando}. Te van a escribir para seguir.`;
}

/**
 * Abre el formulario de una parcela. Cuando la consola la apartó, `alTerminar(link)`
 * recibe adónde ir a pagar, o null si no hay link (y el formulario lo dice).
 */
export function abrirFormulario(dialogo, { catalogo, parcela, alTerminar }) {
  const formulario = dialogo.querySelector('form');
  const error = dialogo.querySelector('#reserva-error');
  const enviar = dialogo.querySelector('#reserva-enviar');
  dialogo.querySelector('#reserva-titulo').textContent = `Reservar ${catalogo.titulo(parcela)}`;
  dialogo.querySelector('#reserva-explicacion').textContent =
    // Sin número de horas: cada loteadora fija las suyas y el sitio no las sabe
    // hasta que la consola contesta. La hora exacta se dice al apartarla.
    'Te la apartamos mientras pagas, para que nadie más la reserve. '
    + 'Te escribirán para confirmar.';
  const listo = dialogo.querySelector('#reserva-listo');
  formulario.reset();
  formulario.classList.remove('reserva--lista');
  error.hidden = true;
  listo.hidden = true;
  enviar.hidden = false;
  enviar.disabled = false;
  const cancelar = dialogo.querySelector('[data-accion="cancelar"]');
  cancelar.textContent = 'Cancelar';

  formulario.onsubmit = async (evento) => {
    evento.preventDefault();
    if (!formulario.reportValidity()) return;
    enviar.disabled = true;
    enviar.textContent = 'Apartando…';
    const campos = Object.fromEntries(new FormData(formulario));
    const { ok, estado, datos } = await enviarSolicitud(catalogo.meta, parcela, campos);
    enviar.textContent = 'Apartar e ir a pagar';
    if (ok) {
      const destino = destinoDelPago(parcela, datos.link);
      if (destino) {
        dialogo.close();
        alTerminar(destino);
        return;
      }
      // Sin link de pago: queda apartada y la loteadora contacta. Se dice acá mismo.
      formulario.classList.add('reserva--lista');
      enviar.hidden = true;
      cancelar.textContent = 'Cerrar';
      listo.textContent = textoApartada(datos.apartada_hasta);
      listo.hidden = false;
      alTerminar(null);
      return;
    }
    enviar.disabled = false;
    error.textContent = mensajeDeError(estado, datos.detail);
    error.hidden = false;
  };
  cancelar.onclick = () => dialogo.close();
  dialogo.showModal();
  formulario.elements.nombre.focus();
}
