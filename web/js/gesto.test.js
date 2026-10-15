/** Distinguir un toque de un arrastre o un pellizco en el visor. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Gesto } from './gesto.js';

test('un toque quieto es clic', () => {
  const gesto = new Gesto(5);
  gesto.bajar(1, 100, 100);
  gesto.mover(1, 102, 101);
  assert.equal(gesto.soltar(1), true);
});

test('arrastrar para girar no es clic, aunque termine cerca de donde empezó', () => {
  const gesto = new Gesto(5);
  gesto.bajar(1, 100, 100);
  assert.deepEqual(gesto.mover(1, 160, 100), { tipo: 'giro', dx: 60, dy: 0 });
  gesto.mover(1, 101, 100);
  assert.equal(gesto.soltar(1), false);
});

test('pellizcar con dos dedos y soltarlos no es clic', () => {
  const gesto = new Gesto(5);
  gesto.bajar(1, 100, 100);
  gesto.bajar(2, 140, 100);
  gesto.mover(1, 90, 100);
  assert.deepEqual(gesto.mover(2, 150, 100), { tipo: 'pellizco', factor: 50 / 60 });
  assert.equal(gesto.soltar(1), false);
  assert.equal(gesto.soltar(2), false);
});

test('al soltar un dedo del pellizco, el otro gira desde donde está, sin salto', () => {
  const gesto = new Gesto(5);
  gesto.bajar(1, 100, 100);
  gesto.bajar(2, 300, 100);
  gesto.soltar(1);
  assert.deepEqual(gesto.mover(2, 304, 100), { tipo: 'giro', dx: 4, dy: 0 });
});

test('un puntero que el navegador cancela no es clic', () => {
  const gesto = new Gesto(5);
  gesto.bajar(1, 100, 100);
  assert.equal(gesto.soltar(1, { cancelado: true }), false);
});

test('después de un pellizco, el siguiente toque vuelve a ser clic', () => {
  const gesto = new Gesto(5);
  gesto.bajar(1, 100, 100);
  gesto.bajar(2, 140, 100);
  gesto.soltar(1);
  gesto.soltar(2);
  gesto.bajar(3, 50, 50);
  assert.equal(gesto.soltar(3), true);
});

test('soltar un puntero que nunca bajó en el visor no es clic', () => {
  assert.equal(new Gesto(5).soltar(9), false);
});
