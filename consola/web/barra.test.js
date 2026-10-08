/** La barra: a qué sección pertenece cada pantalla, para marcarla en la isla. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { seccionDe } from './js/barra.js';

test('cada pantalla marca su sección en la barra', () => {
  assert.equal(seccionDe('planos'), 'planos');
  assert.equal(seccionDe('plano'), 'planos');
  assert.equal(seccionDe('nuevo'), 'planos');
  assert.equal(seccionDe('configuracion'), 'planos');
  assert.equal(seccionDe('kmzs'), 'kmz');
  assert.equal(seccionDe('kmz'), 'kmz');
  assert.equal(seccionDe('disenos'), 'disenos');
  assert.equal(seccionDe('diseno'), 'disenos');
  assert.equal(seccionDe('reservas'), 'reservas');
});
