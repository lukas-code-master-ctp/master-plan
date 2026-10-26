import { test } from 'node:test';
import assert from 'node:assert/strict';

import { botonDePlan, cupoDe, planSugerido, precioDe } from './js/planes.js';

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
