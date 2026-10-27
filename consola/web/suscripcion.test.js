import { test } from 'node:test';
import assert from 'node:assert/strict';

import { dia, resumenDelPlan } from './js/suscripcion.js';
import { avisoDeVuelta, conTarjeta, textoDelBoton } from './js/planes.js';

const PLANES = [{ plan: 'fly', nombre: 'Fly' }, { plan: 'pro', nombre: 'Pro' }];

test('sin plan se invita a elegir uno', () => {
  const resumen = resumenDelPlan({ plan: null, en_linea: 0 }, { pagoConTarjeta: true });
  assert.equal(resumen.nombre, 'Sin plan');
  assert.equal(resumen.boton, 'Elegir plan');
  assert.equal(resumen.cancelable, false);
  assert.match(resumen.estado, /tarjeta/);
});

test('un plan elegido sin tarjeta registrada se dice', () => {
  const resumen = resumenDelPlan({ plan: null, pedido: 'pro' }, { pagoConTarjeta: true, planes: PLANES });
  assert.equal(resumen.pastilla[0], 'Sin pagar');
  assert.match(resumen.estado, /plan Pro, pero la tarjeta no quedó registrada/);
});

test('con tarjeta: cuántos en línea, con qué tarjeta, y se puede cancelar', () => {
  const resumen = resumenDelPlan({
    plan: 'pro', nombre: 'Pro', loteos: 3, en_linea: 2, precio_mensual: 80000,
    con_tarjeta: true, tarjeta: 'Visa ···· 4242', hasta: null,
  });
  assert.match(resumen.cupo, /^2 de 3 loteos en línea · \$\s?80\.000 al mes$/);
  assert.match(resumen.estado, /Visa ···· 4242/);
  assert.equal(resumen.boton, 'Cambiar de plan');
  assert.equal(resumen.cancelable, true);
});

test('cancelada: sigue hasta fin de mes y no se cancela dos veces', () => {
  const resumen = resumenDelPlan({ plan: 'fly', nombre: 'Fly', loteos: 1, en_linea: 1, con_tarjeta: true, hasta: '2026-11-27' });
  assert.equal(resumen.pastilla[0], 'Cancelado');
  assert.match(resumen.estado, /27 de noviembre/);
  assert.equal(resumen.cancelable, false);
});

test('un plan anotado a mano no se cancela desde acá', () => {
  const resumen = resumenDelPlan({ plan: 'enterprise', nombre: 'Enterprise', loteos: 10, en_linea: 4, con_tarjeta: false });
  assert.equal(resumen.cancelable, false);
  assert.match(resumen.estado, /coordinamos contigo/);
});

test('el día se lee sin correrse por la zona horaria', () => {
  assert.equal(dia('2026-11-01'), '1 de noviembre');
});

test('el plan a la medida nunca se paga con tarjeta', () => {
  const sesion = { pago_con_tarjeta: true };
  assert.equal(conTarjeta(sesion, 'pro'), true);
  assert.equal(conTarjeta(sesion, 'enterprise'), false);
  assert.equal(conTarjeta({ pago_con_tarjeta: false }, 'pro'), false);
  assert.equal(textoDelBoton(sesion, 'fly'), 'Pagar con tarjeta');
  assert.equal(textoDelBoton(sesion, 'enterprise'), 'Pedir este plan');
});

test('la vuelta de Flow se avisa, y lo que no viene de Flow no', () => {
  assert.equal(avisoDeVuelta('listo')[1], 'ok');
  assert.match(avisoDeVuelta('sin-tarjeta')[0], /no quedó registrada/);
  assert.ok(avisoDeVuelta('error'));
  assert.equal(avisoDeVuelta(null), null);
  assert.equal(avisoDeVuelta('<script>'), null);
});
