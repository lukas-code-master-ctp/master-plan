/** La galería de fotos de una referencia: qué foto sigue y cuándo pasa el dedo. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { pasoDeArrastre, textoCuenta, vecina } from './galeria.js';

test('pasar de foto da la vuelta en los extremos', () => {
  assert.equal(vecina(0, 6, 1), 1);
  assert.equal(vecina(5, 6, 1), 0);
  assert.equal(vecina(0, 6, -1), 5);
  assert.equal(vecina(0, 0, 1), 0);
});

test('el contador va solo con más de una foto', () => {
  assert.equal(textoCuenta(1, 6), '2 / 6');
  assert.equal(textoCuenta(0, 1), '');
});

test('arrastrar a la izquierda pasa a la siguiente; un temblor o un gesto vertical, no', () => {
  assert.equal(pasoDeArrastre(-80, 10), 1);
  assert.equal(pasoDeArrastre(80, -5), -1);
  assert.equal(pasoDeArrastre(-20, 0), 0);
  assert.equal(pasoDeArrastre(-60, 120), 0);
});
