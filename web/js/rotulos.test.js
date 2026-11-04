/** Qué pastillas de parcela se dibujan cuando no caben todas. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { rotulosSinChoques, acomodarReferencias } from './rotulos.js';

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

// --- Rótulos del horizonte -------------------------------------------------

const lugar = (id, x, y, distancia, ancho = 120) => ({ id, x, y, ancho, distancia });

test('lugares en la misma dirección se juntan en una columna con un solo alfiler', () => {
  // Fundo Atalaya: cinco lugares hacia la costa, con sus puntos a un par de px.
  const puestos = acomodarReferencias([
    lugar('puerto', 501, 300, 15), lugar('centro', 500, 301, 11.2), lugar('golf', 502, 300, 11.4),
    lugar('humedal', 499, 302, 13), lugar('playa', 500, 300, 11),
  ]);

  const orden = [...puestos].sort((a, b) => a[1].escalon - b[1].escalon).map(([id]) => id);
  assert.deepEqual(orden, ['playa', 'centro', 'golf', 'humedal', 'puerto']);
  assert.deepEqual([...puestos.values()].map((p) => p.escalon).sort(), [0, 1, 2, 3, 4]);
  assert.deepEqual([...puestos].filter(([, p]) => p.conAlfiler).map(([id]) => id), ['playa']);
  // Todos se paran en el punto del más cercano, para que la columna quede derecha.
  assert.ok([...puestos.values()].every((p) => p.x === 500 && p.y === 300));
});

test('dos lugares que no se tocan quedan cada uno en su sitio', () => {
  const puestos = acomodarReferencias([lugar('a', 100, 300, 3), lugar('b', 600, 300, 5)]);

  assert.deepEqual(puestos.get('a'), { x: 100, y: 300, escalon: 0, conAlfiler: true, columna: 0 });
  assert.deepEqual(puestos.get('b'), { x: 600, y: 300, escalon: 0, conAlfiler: true, columna: 0 });
});

test('un lugar cuyo punto cae bajo la píldora de otro se suma a su columna', () => {
  // A 55 px, con píldoras de 120: sin juntarlos, el alfiler de b cruzaría la de a.
  const puestos = acomodarReferencias([lugar('a', 300, 300, 3), lugar('b', 355, 299, 7)]);

  assert.deepEqual(puestos.get('b'), { x: 300, y: 300, escalon: 1, conAlfiler: false, columna: 1 });
});

test('una columna que choca con otra sube por sobre toda ella', () => {
  // a y b apuntan al mismo sitio; c está 80 px al lado (fuera de la píldora de a)
  // pero su píldora igual pisa las de ellos.
  const puestos = acomodarReferencias([lugar('a', 300, 300, 3), lugar('b', 302, 301, 4), lugar('c', 380, 298, 9)]);

  assert.equal(puestos.get('a').escalon, 0);
  assert.equal(puestos.get('b').escalon, 1);
  assert.equal(puestos.get('c').escalon, 2);
  assert.ok(puestos.get('c').conAlfiler);
});
