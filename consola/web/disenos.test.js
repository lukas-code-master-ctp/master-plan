/** Mis diseños: qué foto de fondo lleva la muestra de cada diseño. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { fotoDeFondo } from './js/comun.js';

const proyectos = [
  { slug: 'sin-construir', construido: false, diseno_id: 7 },
  { slug: 'praderas', construido: true, diseno_id: null },
  { slug: 'vichuquen', construido: true, diseno_id: 7 },
];

test('la muestra usa la foto de un loteo construido que lleva ese diseño', () => {
  assert.equal(fotoDeFondo(proyectos, 7), 'vichuquen');
});

test('si ninguno lo lleva, usa la de cualquier loteo construido', () => {
  assert.equal(fotoDeFondo(proyectos, 99), 'praderas');
});

test('sin loteos construidos no hay foto', () => {
  assert.equal(fotoDeFondo([{ slug: 'x', construido: false }], 1), null);
});
