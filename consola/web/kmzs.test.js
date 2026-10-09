/** Mis KMZ: cuánto le falta a cada KMZ, para la barra de su tarjeta. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { avanceDe } from './js/kmzs.js';

test('cada paso cuenta cuántos de los cinco ya están hechos', () => {
  assert.deepEqual(avanceDe({ paso: 'subir' }), { hechos: 0, total: 5 });
  assert.deepEqual(avanceDe({ paso: 'marcar' }), { hechos: 1, total: 5 });
  assert.deepEqual(avanceDe({ paso: 'ubicar' }), { hechos: 3, total: 5 });
  assert.deepEqual(avanceDe({ paso: 'crear' }), { hechos: 4, total: 5 });
  assert.deepEqual(avanceDe({ paso: 'listo' }), { hechos: 5, total: 5 });
});

test('un paso desconocido cuenta como recién empezado', () => {
  assert.deepEqual(avanceDe({ paso: 'otro' }), { hechos: 0, total: 5 });
  assert.deepEqual(avanceDe(null), { hechos: 0, total: 5 });
});
