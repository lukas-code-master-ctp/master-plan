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
      avisar(`Pediste el plan ${nombre}. Te escribimos para el pago y te avisamos por correo cuando esté activo.`, 'ok');
      await alPedir();
    } catch (error) {
      avisar(error.message);
    } finally {
      listo.disabled = false;
    }
  };
  abrirDialogo($('#plan'));
}
