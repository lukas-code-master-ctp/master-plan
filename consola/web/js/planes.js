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
 * El plan que conviene marcar de entrada: sin plan, el que eligió en la landing o el
 * más chico; con uno lleno, el siguiente que tenga cupo para uno más.
 */
export function planSugerido(actual, planes) {
  if (!actual?.plan) {
    // El que eligió en la landing antes de registrarse, si sigue existiendo.
    if (planes.some((p) => p.plan === actual?.interes)) return actual.interes;
    return planes[0]?.plan ?? null;
  }
  const necesita = (actual.en_linea ?? 0) + 1;
  const mayor = planes.find((p) => p.loteos == null || p.loteos >= necesita);
  return mayor?.plan ?? null;
}

/**
 * Lo que pasa después de pedir el plan marcado. El a la medida no tiene precio que
 * pagar todavía: primero se conversa.
 */
export function pieDelPlan(clave, planes) {
  const plan = planes.find((p) => p.plan === clave);
  if (plan && plan.loteos == null) {
    return 'Lo armamos contigo: te escribimos para acordar cuántos loteos incluye y su precio.';
  }
  return 'Te escribimos para coordinar el pago y te avisamos por correo cuando esté activo. '
    + 'Se paga mes a mes y te recordamos antes de cada vencimiento.';
}

/** El texto del botón: elegir el primero o cambiar el que tiene. */
export const botonDePlan = (actual) => (actual?.plan ? 'Cambiar de plan' : 'Elegir plan');

const DIA_LARGO = new Intl.DateTimeFormat('es-CL', { day: 'numeric', month: 'long', year: 'numeric' });
const diaDe = (iso) => DIA_LARGO.format(new Date(`${iso}T12:00:00`));

/**
 * Lo que la loteadora ve de su plan en Configuración: la pastilla, los datos y una
 * nota con lo que sigue. `plan` es el de la sesión.
 */
export function resumenDeMiPlan(plan, planes = []) {
  const nombre = (clave) => planes.find((p) => p.plan === clave)?.nombre ?? clave;
  if (!plan?.plan) {
    return {
      pastilla: plan?.pedido ? { texto: `Pediste ${nombre(plan.pedido)}`, tono: 'aviso' } : { texto: 'Sin plan', tono: null },
      datos: [],
      nota: plan?.pedido
        ? 'Te escribimos para el pago y te avisamos por correo cuando esté activo.'
        : 'Lo eliges al publicar tu primer master: ábrelo y aprieta Elegir plan.',
    };
  }
  const datos = [
    ['Plan', plan.nombre],
    ['Precio', plan.precio_mensual == null ? 'A la medida' : `${PESOS.format(plan.precio_mensual)} al mes`],
    ['En línea', `${plan.en_linea} de ${loteos(plan.loteos)}`],
  ];
  if (plan.hasta) datos.push(['Pagado hasta', diaDe(plan.hasta)]);
  let nota = plan.en_linea >= plan.loteos
    ? 'Tu plan está lleno: para publicar otro, baja uno del aire o cambia a un plan más grande.'
    : `Te ${plan.loteos - plan.en_linea === 1 ? 'queda 1 cupo' : `quedan ${plan.loteos - plan.en_linea} cupos`} para publicar.`;
  if (plan.pedido && plan.pedido !== plan.plan) nota = `Pediste cambiar a ${nombre(plan.pedido)}: te escribimos para el pago.`;
  if (plan.vencido) {
    return {
      pastilla: { texto: 'Vencido', tono: 'aviso' },
      datos,
      nota: 'Tus loteos siguen en línea 7 días después de la fecha pagada; ese día se bajan del aire si no '
        + 'se renueva. Escríbenos para renovarlo.',
    };
  }
  return { pastilla: { texto: 'Activo', tono: 'ok' }, datos, nota };
}

/** Abre el diálogo para pedir un plan para este loteo. `alPedir` refresca la página. */
export function abrirPlanes(proyecto, alPedir) {
  const actual = estado.sesion?.plan;
  const planes = estado.sesion?.planes ?? [];
  const sugerido = planSugerido(actual, planes);
  $('#plan-titulo').textContent = actual?.plan ? `Tu plan es ${actual.nombre}: elige otro` : 'Elige tu plan';
  $('#plan-opciones').replaceChildren(...planes.map((plan) => {
    const opcion = document.createElement('label');
    const radio = Object.assign(document.createElement('input'),
      { type: 'radio', name: 'plan', value: plan.plan, checked: plan.plan === sugerido });
    // El que ya tiene no se pide de nuevo.
    radio.disabled = plan.plan === actual?.plan;
    const nombre = document.createElement('strong');
    nombre.textContent = plan.nombre;
    const cupo = Object.assign(document.createElement('span'), { className: 'planes__cupo', textContent: cupoDe(plan) });
    const precio = Object.assign(document.createElement('span'), { className: 'planes__precio', textContent: precioDe(plan) });
    opcion.append(radio, nombre, precio, cupo);
    return opcion;
  }));
  const pie = () => { $('#plan-pie').textContent = pieDelPlan($('#plan-opciones input:checked')?.value, planes); };
  $('#plan-opciones').onchange = pie;
  pie();
  const listo = $('#plan-listo');
  listo.onclick = async () => {
    const elegido = $('#plan-opciones input:checked')?.value;
    if (!elegido) return avisar('Elige un plan.');
    listo.disabled = true;
    try {
      await pedir(`/api/proyectos/${proyecto.slug}/habilitacion`, json({ plan: elegido }));
      // La sesión no se vuelve a pedir: basta con saber que ya hay un pedido.
      if (estado.sesion?.plan) estado.sesion.plan.pedido = elegido;
      $('#plan').close();
      const nombre = planes.find((p) => p.plan === elegido)?.nombre ?? elegido;
      const aLaMedida = planes.find((p) => p.plan === elegido)?.loteos == null;
      avisar(aLaMedida ? `Pediste el plan ${nombre}. Te escribimos para armarlo contigo.`
        : `Pediste el plan ${nombre}. Te escribimos para el pago y te avisamos por correo cuando esté activo.`, 'ok');
      await alPedir();
    } catch (error) {
      avisar(error.message);
    } finally {
      listo.disabled = false;
    }
  };
  abrirDialogo($('#plan'));
}
