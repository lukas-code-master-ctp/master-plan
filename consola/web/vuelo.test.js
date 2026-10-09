/** Lo que dice la tarjeta del vuelo mientras la construcción espera su turno. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { textoDeCola } from './js/vuelo.js';

test('la próxima en la fila parte apenas termine la que corre', () => {
  assert.equal(textoDeCola(1), 'Es la próxima: parte sola apenas termine la que está corriendo.');
  assert.equal(textoDeCola(null), 'Es la próxima: parte sola apenas termine la que está corriendo.');
});

test('más atrás, dice cuántas hay antes', () => {
  assert.equal(textoDeCola(2), 'Hay 1 otra antes en la fila. Parte sola cuando le toque.');
  assert.equal(textoDeCola(4), 'Hay 3 otras antes en la fila. Parte sola cuando le toque.');
});
