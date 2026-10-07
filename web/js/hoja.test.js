/** La ficha del celular como hoja: tres alturas y adónde va al soltar el dedo. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { conResistencia, destinoAlSoltar, nivelesDeLaHoja } from './hoja.js';

// Una hoja de 600 px en una pantalla de 800, con 130 px de cabecera asomada.
const NIVELES = nivelesDeLaHoja(600, 800, 130);

test('las tres alturas son cuánto se corre la hoja hacia abajo', () => {
  // Entera no se corre; a media altura deja ver el 52 % de la pantalla; asomada, la cabecera.
  assert.deepEqual(NIVELES, { entera: 0, media: 600 - 416, minima: 600 - 130 });
});

test('una hoja corta no tiene media altura: abre entera', () => {
  assert.deepEqual(nivelesDeLaHoja(300, 800, 130), { entera: 0, media: 0, minima: 170 });
});

test('al soltar quieta, va a la altura más cercana', () => {
  assert.equal(destinoAlSoltar(20, 0, NIVELES), 'entera');
  assert.equal(destinoAlSoltar(200, 0, NIVELES), 'media');
  assert.equal(destinoAlSoltar(400, 0, NIVELES), 'minima');
});

test('al soltar con impulso, sigue hacia donde iba el dedo', () => {
  // Desde media altura, un tirón corto pero rápido hacia abajo la deja asomada…
  assert.equal(destinoAlSoltar(240, 1.5, NIVELES), 'minima');
  // …y uno hacia arriba la abre entera.
  assert.equal(destinoAlSoltar(150, -1.5, NIVELES), 'entera');
});

test('un tirón muy fuerte no se salta la hoja fuera de sus alturas', () => {
  assert.equal(destinoAlSoltar(400, 50, NIVELES), 'minima');
  assert.equal(destinoAlSoltar(100, -50, NIVELES), 'entera');
});

test('asomada nunca se cierra: bajarla más la deja asomada', () => {
  assert.equal(destinoAlSoltar(560, 2, NIVELES), 'minima');
});

test('fuera de los topes el dedo arrastra con freno', () => {
  assert.equal(conResistencia(100, 0, 470), 100);
  assert.ok(conResistencia(-100, 0, 470) > -100 && conResistencia(-100, 0, 470) < 0);
  assert.ok(conResistencia(570, 0, 470) > 470 && conResistencia(570, 0, 470) < 570);
});
