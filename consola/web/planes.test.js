import { test } from 'node:test';
import assert from 'node:assert/strict';

import { botonDePlan, cupoDe, pieDelPlan, planSugerido, precioDe, resumenDeMiPlan } from './js/planes.js';

const PLANES = [
  { plan: 'fly', nombre: 'Fly', loteos: 1, precio_mensual: 30000 },
  { plan: 'pro', nombre: 'Pro', loteos: 3, precio_mensual: 80000 },
  { plan: 'master', nombre: 'Master', loteos: 6, precio_mensual: 150000 },
  { plan: 'enterprise', nombre: 'Enterprise', loteos: null, precio_mensual: null },
];

test('cada plan se dice como en la landing', () => {
  assert.equal(cupoDe(PLANES[0]), '1 loteo en línea');
  assert.equal(cupoDe(PLANES[1]), '3 loteos en línea');
  assert.match(cupoDe(PLANES[3]), /a la medida/);
  assert.match(precioDe(PLANES[0]), /^\$\s?30\.000 al mes$/);
  assert.equal(precioDe(PLANES[3]), 'Lo armamos contigo');
});

test('sin plan se sugiere el más chico', () => {
  assert.equal(planSugerido(null, PLANES), 'fly');
  assert.equal(planSugerido({ plan: null, en_linea: 0 }, PLANES), 'fly');
});

test('con el plan lleno se sugiere el primero que deja publicar uno más', () => {
  assert.equal(planSugerido({ plan: 'fly', loteos: 1, en_linea: 1 }, PLANES), 'pro');
  assert.equal(planSugerido({ plan: 'pro', loteos: 3, en_linea: 3 }, PLANES), 'master');
  assert.equal(planSugerido({ plan: 'master', loteos: 6, en_linea: 6 }, PLANES), 'enterprise');
});

test('el botón ofrece elegir o cambiar', () => {
  assert.equal(botonDePlan(null), 'Elegir plan');
  assert.equal(botonDePlan({ plan: 'fly' }), 'Cambiar de plan');
});

test('sin plan, Configuración dice dónde se elige', () => {
  const resumen = resumenDeMiPlan({ plan: null, pedido: null }, []);
  assert.deepEqual(resumen.pastilla, { texto: 'Sin plan', tono: null });
  assert.equal(resumen.datos.length, 0);
  assert.match(resumen.nota, /Elegir plan/);
});

test('con plan, Configuración muestra precio, cupos y hasta cuándo está pagado', () => {
  const resumen = resumenDeMiPlan({ plan: 'pro', nombre: 'Pro', loteos: 3, en_linea: 2,
    precio_mensual: 80000, hasta: '2026-11-30', vencido: false }, []);
  assert.deepEqual(resumen.pastilla, { texto: 'Activo', tono: 'ok' });
  assert.deepEqual(resumen.datos.map(([r]) => r), ['Plan', 'Precio', 'En línea', 'Pagado hasta']);
  assert.equal(resumen.datos[2][1], '2 de 3 loteos');
  assert.match(resumen.datos[3][1], /30 de noviembre de 2026/);
  assert.match(resumen.nota, /queda 1 cupo/);
});

test('con el plan vencido, Configuración avisa cuándo se bajan', () => {
  const resumen = resumenDeMiPlan({ plan: 'fly', nombre: 'Fly', loteos: 1, en_linea: 1,
    precio_mensual: 30000, hasta: '2026-10-20', vencido: true }, []);
  assert.deepEqual(resumen.pastilla, { texto: 'Vencido', tono: 'aviso' });
  assert.match(resumen.nota, /se bajan del aire/);
});

test('el pie del diálogo dice qué pasa después de pedir', () => {
  assert.match(pieDelPlan('pro', PLANES), /coordinar el pago/);
  assert.match(pieDelPlan('pro', PLANES), /mes a mes/);
  assert.match(pieDelPlan('enterprise', PLANES), /Lo armamos contigo/);
});

test('sin plan, se sugiere el que eligió en la landing', () => {
  assert.equal(planSugerido({ plan: null, interes: 'pro' }, PLANES), 'pro');
  assert.equal(planSugerido({ plan: null, interes: 'no-existe' }, PLANES), 'fly');
});
