/**
 * Los planes de suscripción, del lado de la loteadora: cuál ofrecer y cómo decirlo.
 *
 * El catálogo y la regla que cobra viven en el servidor (consola/planes.py); acá solo
 * se muestran. La sesión trae `plan` (el de su loteadora) y `planes` (los que hay).
 */
import { $, abrirDialogo, avisar, estado, json, pedir } from './comun.js';

const PESOS = new Intl.NumberFormat('es-CL', { style: 'currency', currency: 'CLP', maximumFractionDigits: 0 });

export const loteos = (n) => `${n} ${n === 1 ? 'loteo' : 'loteos'}`;

/** "1 loteo en línea", "A la medida": lo que trae cada plan. */
export function cupoDe(plan) {
  return plan.loteos == null ? 'Más de seis loteos, a la medida' : `${loteos(plan.loteos)} en línea`;
}

/** "$30.000 al mes", o "Lo armamos contigo" para el que no tiene precio fijo. */
export function precioDe(plan) {
  return plan.precio_mensual == null ? 'Lo armamos contigo' : `${PESOS.format(plan.precio_mensual)} al mes`;
}

/**
 * El plan que conviene marcar de entrada: sin plan, el más chico; con uno lleno, el
 * siguiente que tenga cupo para uno más.
 */
export function planSugerido(actual, planes) {
  if (!actual?.plan) return planes[0]?.plan ?? null;
  const necesita = (actual.en_linea ?? 0) + 1;
  const mayor = planes.find((p) => p.loteos == null || p.loteos >= necesita);
  return mayor?.plan ?? null;
}

/** El texto del botón: elegir el primero o cambiar el que tiene. */
export const botonDePlan = (actual) => (actual?.plan ? 'Cambiar de plan' : 'Elegir plan');

/** ¿Este plan se paga con tarjeta en Flow? El plan a la medida se conversa. */
export const conTarjeta = (sesion, plan) => Boolean(sesion?.pago_con_tarjeta) && plan !== 'enterprise';

/** Lo que dice el botón del diálogo según el plan marcado. */
export const textoDelBoton = (sesion, plan) => (conTarjeta(sesion, plan) ? 'Pagar con tarjeta' : 'Pedir este plan');

/**
 * Lo que se le dice a la loteadora al volver de Flow (`/?plan=…`), o null si no
 * viene de ahí.
 */
export function avisoDeVuelta(resultado) {
  if (resultado === 'listo') {
    return ['Tu tarjeta quedó registrada. Cuando Flow confirme el primer cobro, tu plan queda activo.', 'ok'];
  }
  if (resultado === 'sin-tarjeta') return ['La tarjeta no quedó registrada. Puedes intentarlo de nuevo.', null];
  if (resultado === 'error') return ['No pudimos confirmar el registro con Flow. Vuelve a intentarlo en un rato.', null];
  return null;
}

/**
 * Abre el diálogo de planes. Con Flow activo, los planes se pagan con tarjeta: se
 * va a Flow a registrarla y se vuelve a Configuración. Sin Flow (o el plan a la
 * medida), se pide y CTP lo anota; eso necesita el loteo desde el que se pide.
 * `alPedir` refresca la página.
 */
export function abrirPlanes(proyecto, alPedir) {
  const sesion = estado.sesion;
  const actual = sesion?.plan;
  const planes = sesion?.planes ?? [];
  const sugerido = planSugerido(actual, planes);
  // Con la cancelación pedida, el mismo plan se puede volver a tomar.
  const vigente = actual?.hasta ? null : actual?.plan;
  $('#plan-titulo').textContent = actual?.plan ? `Tu plan es ${actual.nombre}: elige otro` : 'Elige tu plan';
  $('#plan-nota').textContent = sesion?.pago_con_tarjeta
    ? 'Pagas con tarjeta en Flow y se cobra solo cada mes. Puedes cancelar cuando quieras.'
    : 'Te escribimos para el pago y te avisamos por correo cuando esté activo.';
  const listo = $('#plan-listo');
  $('#plan-opciones').replaceChildren(...planes.map((plan) => {
    const opcion = document.createElement('label');
    const radio = Object.assign(document.createElement('input'),
      { type: 'radio', name: 'plan', value: plan.plan, checked: plan.plan === sugerido });
    radio.disabled = plan.plan === vigente;
    radio.addEventListener('change', () => { listo.textContent = textoDelBoton(sesion, plan.plan); });
    const nombre = document.createElement('strong');
    nombre.textContent = plan.nombre;
    const cupo = Object.assign(document.createElement('span'), { className: 'planes__cupo', textContent: cupoDe(plan) });
    const precio = Object.assign(document.createElement('span'), { className: 'planes__precio', textContent: precioDe(plan) });
    opcion.append(radio, nombre, precio, cupo);
    return opcion;
  }));
  listo.textContent = textoDelBoton(sesion, sugerido);
  listo.onclick = async () => {
    const elegido = $('#plan-opciones input:checked')?.value;
    if (!elegido) return avisar('Elige un plan.');
    const nombre = planes.find((p) => p.plan === elegido)?.nombre ?? elegido;
    listo.disabled = true;
    try {
      if (conTarjeta(sesion, elegido)) {
        const { url } = await pedir('/api/plan/flow', json({ plan: elegido }));
        // A Flow, a registrar la tarjeta: vuelve solo a Configuración.
        if (url) { location.href = url; return; }
        $('#plan').close();
        estado.sesion = await pedir('/api/sesion');
        avisar(`Cambiaste al plan ${nombre}. Se cobra a tu tarjeta registrada.`, 'ok');
      } else if (proyecto) {
        await pedir(`/api/proyectos/${proyecto.slug}/habilitacion`, json({ plan: elegido }));
        // La sesión no se vuelve a pedir: basta con saber que ya hay un pedido.
        if (estado.sesion?.plan) estado.sesion.plan.pedido = elegido;
        $('#plan').close();
        avisar(`Pediste el plan ${nombre}. Te escribimos para el pago y te avisamos por correo cuando esté activo.`, 'ok');
      } else {
        $('#plan').close();
        avisar(`El plan ${nombre} lo armamos contigo: escríbenos desde tumasterplan.cl.`);
        return;
      }
      await alPedir();
    } catch (error) {
      avisar(error.message);
    } finally {
      listo.disabled = false;
    }
  };
  abrirDialogo($('#plan'));
}
