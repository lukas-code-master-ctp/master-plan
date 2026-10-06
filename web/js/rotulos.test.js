/** Qué pastillas de parcela se dibujan cuando no caben todas. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { rotulosSinChoques } from './rotulos.js';

const pastilla = (id, x, y, prioridad = 0, ancho = 40, alto = 26) => ({ id, x, y, ancho, alto, prioridad });

test('las pastillas que no se tocan se dibujan todas', () => {
  const visibles = rotulosSinChoques([pastilla('a', 0, 0), pastilla('b', 100, 0), pastilla('c', 0, 100)]);

  assert.deepEqual([...visibles].sort(), ['a', 'b', 'c']);
});

test('de dos pastillas encimadas se dibuja la de más prioridad', () => {
  const visibles = rotulosSinChoques([pastilla('lejos', 0, 0, 1), pastilla('cerca', 10, 5, 5)]);

  assert.deepEqual([...visibles], ['cerca']);
});

test('una pastilla escondida no tapa a las que vienen después', () => {
  // b choca con a (que gana) pero no con c: c se dibuja aunque b esté entre medio.
  const visibles = rotulosSinChoques([pastilla('a', 0, 0, 3), pastilla('b', 30, 0, 2), pastilla('c', 60, 0, 1)]);

  assert.deepEqual([...visibles].sort(), ['a', 'c']);
});

test('dos pastillas que apenas se rozan también chocan: necesitan aire entre ellas', () => {
  // 40 de ancho: centros a 41 px dejan un píxel, menos que la separación pedida.
  assert.equal(rotulosSinChoques([pastilla('a', 0, 0, 2), pastilla('b', 41, 0, 1)], 3).size, 1);
  assert.equal(rotulosSinChoques([pastilla('a', 0, 0, 2), pastilla('b', 44, 0, 1)], 3).size, 2);
});

test('a igual prioridad gana la que vino primero', () => {
  assert.deepEqual([...rotulosSinChoques([pastilla('primera', 0, 0), pastilla('segunda', 5, 0)])], ['primera']);
});

test('sin pastillas no hay nada que dibujar', () => {
  assert.equal(rotulosSinChoques([]).size, 0);
});
