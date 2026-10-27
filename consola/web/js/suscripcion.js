/**
 * Configuración → Plan y pago: el plan de la loteadora, cuántos loteos tiene en
 * línea y, si paga con tarjeta en Flow, con cuál y hasta cuándo.
 *
 * Elegir o cambiar de plan abre el mismo diálogo que se abre al publicar
 * (planes.js). Al volver de registrar la tarjeta en Flow, la consola abre con
 * `?plan=<resultado>`: se avisa y se saca de la dirección.
 */
import { $, avisar, estado, pedir } from './comun.js';
import { abrirPlanes, avisoDeVuelta, botonDePlan, loteos, precioDe } from './planes.js';

const DIA = new Intl.DateTimeFormat('es-CL', { day: 'numeric', month: 'long', timeZone: 'UTC' });

/** "2026-11-27" (o un instante ISO) → "27 de noviembre". */
export const dia = (iso) => DIA.format(new Date(String(iso).slice(0, 10)));

/** Lo que se muestra en la tarjeta del plan. Sin DOM, para probarlo. */
export function resumenDelPlan(plan, { pagoConTarjeta = false, planes = [] } = {}) {
  if (!plan?.plan) {
    const pedido = plan?.pedido && (planes.find((p) => p.plan === plan.pedido)?.nombre ?? plan.pedido);
    return {
      nombre: 'Sin plan',
      cupo: 'Con un plan publicas tus loteos y los mantienes en línea.',
      // Sin pedido, el título ya dice "Sin plan": la pastilla no lo repite.
      pastilla: pedido ? [pagoConTarjeta ? 'Sin pagar' : 'Pedido', 'pastilla pastilla--aviso'] : ['', 'pastilla'],
      estado: pedido
        ? (pagoConTarjeta ? `Elegiste el plan ${pedido}, pero la tarjeta no quedó registrada.`
          : `Pediste el plan ${pedido}: te avisamos por correo cuando esté activo.`)
        : (pagoConTarjeta ? 'Elige un plan y paga con tarjeta: se cobra solo cada mes.' : ''),
      boton: botonDePlan(plan),
      cancelable: false,
    };
  }
  const cupo = plan.loteos == null
    ? `${loteos(plan.en_linea ?? 0)} en línea`
    : `${plan.en_linea ?? 0} de ${loteos(plan.loteos)} en línea`;
  const precio = plan.precio_mensual == null ? '' : ` · ${precioDe(plan)}`;
  let pastilla = ['Activo', 'pastilla pastilla--ok'];
  let texto;
  if (plan.con_tarjeta && plan.hasta) {
    pastilla = ['Cancelado', 'pastilla pastilla--aviso'];
    texto = `Cancelaste la suscripción: el plan sigue hasta el ${dia(plan.hasta)} y no se vuelve a cobrar.`;
  } else if (plan.con_tarjeta) {
    texto = `Se cobra solo cada mes${plan.tarjeta ? ` a tu ${plan.tarjeta}` : ' a tu tarjeta'}, en Flow.`;
  } else {
    texto = plan.desde ? `Activo desde el ${dia(plan.desde)}. El pago lo coordinamos contigo.`
      : 'El pago lo coordinamos contigo.';
  }
  return {
    nombre: `Plan ${plan.nombre}`,
    cupo: cupo + precio,
    pastilla,
    estado: texto,
    boton: botonDePlan(plan),
    cancelable: Boolean(plan.con_tarjeta && !plan.hasta),
  };
}

export function prepararSuscripcion({ refrescar }) {
  $('#config-plan-elegir').addEventListener('click', () => abrirPlanes(null, async () => {
    pintarSuscripcion();
    await refrescar();
  }));
  $('#config-plan-cancelar').addEventListener('click', cancelar);
}

/** Pinta la sección. CTP no paga plan: a su equipo no se le muestra. */
export function pintarSuscripcion() {
  const sesion = estado.sesion;
  if (!sesion) return;
  const visible = sesion.rol !== 'plataforma';
  $('#config-plan').hidden = !visible;
  const enIndice = document.querySelector('.config__indice [data-ir="config-plan"]');
  if (enIndice) enIndice.hidden = !visible;
  if (!visible) return;
  const resumen = resumenDelPlan(sesion.plan, { pagoConTarjeta: sesion.pago_con_tarjeta, planes: sesion.planes });
  $('#config-plan-nombre').textContent = resumen.nombre;
  $('#config-plan-cupo').textContent = resumen.cupo;
  const [texto, clase] = resumen.pastilla;
  Object.assign($('#config-plan-pastilla'), { textContent: texto, className: clase });
  $('#config-plan-pastilla').hidden = !texto;
  $('#config-plan-estado').textContent = resumen.estado;
  $('#config-plan-estado').hidden = !resumen.estado;
  const duenio = sesion.rol === 'dueño';
  $('#config-plan-acciones').hidden = !duenio;
  $('#config-plan-solo-duenio').hidden = duenio;
  $('#config-plan-elegir').textContent = resumen.boton;
  $('#config-plan-cancelar').hidden = !resumen.cancelable;
}

async function cancelar() {
  if (!confirm('¿Cancelar la suscripción? El plan sigue hasta el fin del mes pagado y después '
    + 'no se vuelve a cobrar. Tus sitios publicados siguen en línea, pero no podrás publicar más.')) return;
  const boton = $('#config-plan-cancelar');
  boton.disabled = true;
  try {
    const { hasta } = await pedir('/api/plan/flow/cancelar', { method: 'POST' });
    estado.sesion = await pedir('/api/sesion');
    pintarSuscripcion();
    avisar(hasta ? `Listo: tu plan sigue hasta el ${dia(hasta)}.` : 'Listo: cancelaste la suscripción.', 'ok');
  } catch (error) {
    avisar(error.message);
  } finally {
    boton.disabled = false;
  }
}

/**
 * Al volver de Flow: avisa cómo quedó y deja la dirección limpia, para que una
 * recarga no repita el aviso.
 */
export function avisarVueltaDeFlow() {
  const parametros = new URLSearchParams(location.search);
  const aviso = avisoDeVuelta(parametros.get('plan'));
  if (!parametros.has('plan')) return;
  parametros.delete('plan');
  const resto = parametros.toString();
  history.replaceState(null, '', `${location.pathname}${resto ? `?${resto}` : ''}${location.hash}`);
  if (!aviso) return;
  // Con el primer mes ya cobrado, el plan está activo al volver: se dice cuál.
  const activo = estado.sesion?.plan;
  if (aviso[1] === 'ok' && activo?.plan) {
    aviso[0] = `Tu tarjeta quedó registrada y tu plan ${activo.nombre} ya está activo.`;
  }
  avisar(...aviso);
}
