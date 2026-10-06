/** Cómo se nombran los puntos de vuelo en el plano y en los controles. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Catalogo, romano } from './datos.js';

const vista = (id, posicion, altura_m) => ({ id, posicion, altura_m, lat: -35, lon: -72 });

function catalogoCon(vistas) {
  return new Catalogo({ parcelas: [], estados: {} }, { vistas, inicial: vistas[0]?.id });
}

test('los puntos se numeran en romanos, como en el vuelo', () => {
  assert.deepEqual([1, 2, 3, 4, 8].map(romano), ['I', 'II', 'III', 'IV', 'VIII']);
});

test('un punto fuera de la tabla de romanos conserva su número', () => {
  assert.equal(romano(12), '12');
});

test('un punto volado a una sola altura dice esa altura', () => {
  const catalogo = catalogoCon([vista('p01-210', 1, 210)]);

  assert.equal(catalogo.nombrePunto(1), 'Punto I');
  assert.equal(catalogo.alturasDePunto(1), '210 m');
});

test('un punto volado a varias alturas dice el rango, de la más baja a la más alta', () => {
  const catalogo = catalogoCon([vista('p02-120', 2, 120), vista('p02-40', 2, 40), vista('p02-80', 2, 80)]);

  assert.equal(catalogo.alturasDePunto(2), '40–120 m');
});

test('las alturas de otro punto no se mezclan', () => {
  const catalogo = catalogoCon([vista('p01-120', 1, 120), vista('p04-230', 4, 230)]);

  assert.equal(catalogo.alturasDePunto(4), '230 m');
});

test('un punto sin vistas no inventa altura', () => {
  assert.equal(catalogoCon([vista('p01-120', 1, 120)]).alturasDePunto(9), '');
});
