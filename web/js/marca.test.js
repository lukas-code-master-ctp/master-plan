/** La marca de la loteadora: que los botones se lean, y que la consola y el visor
 * ofrezcan las mismas tipografías. */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { TIPOGRAFIAS, contraste, paleta } from './marca.js';

test('un color oscuro queda tal cual como color del botón', () => {
  assert.equal(paleta('#1f5132')['--marca-700'], '#1f5132');
});

test('un color claro se oscurece hasta que el texto blanco se lee', () => {
  const boton = paleta('#ffd400')['--marca-700'];

  assert.notEqual(boton, '#ffd400');
  assert.ok(contraste(boton, '#ffffff') >= 4.5, `${boton} no llega a 4.5:1`);
});

test('el blanco también termina siendo un botón legible', () => {
  assert.ok(contraste(paleta('#ffffff')['--marca-700'], '#ffffff') >= 4.5);
});

test('la escala va de claro a oscuro', () => {
  const escala = paleta('#2563eb');
  const brillo = (hex) => [1, 3, 5].reduce((s, i) => s + parseInt(hex.slice(i, i + 2), 16), 0);
  const orden = ['--marca-50', '--marca-100', '--marca-500', '--marca-600', '--marca-700',
    '--marca-800', '--marca-900'].map((v) => brillo(escala[v]));

  assert.deepEqual([...orden].sort((a, b) => b - a), orden);
});

test('la consola ofrece las mismas tipografías que el visor sabe dibujar', () => {
  const aqui = dirname(fileURLToPath(import.meta.url));
  const python = readFileSync(join(aqui, '..', '..', 'consola', 'disenos.py'), 'utf8');
  const bloque = python.match(/TIPOGRAFIAS = \{([^}]*)\}/s)[1];
  const enLaConsola = [...bloque.matchAll(/"(\w+)":/g)].map((c) => c[1]).sort();

  assert.deepEqual(enLaConsola, Object.keys(TIPOGRAFIAS).sort());
});
