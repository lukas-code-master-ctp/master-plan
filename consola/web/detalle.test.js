/** El detalle de un loteo: cómo se nombran las vistas y qué dice el medidor del sol. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { medicionDelSol, nombreDeVista } from './js/detalle.js';

test('cada vista se nombra como en el visor: punto en romanos y altura', () => {
  assert.equal(nombreDeVista('p01-500.jpg'), 'Punto I · 500 m');
  assert.equal(nombreDeVista('p04-500'), 'Punto IV · 500 m');
  assert.equal(nombreDeVista('p29-300.jpg'), 'Punto XXIX · 300 m');
});

test('una vista bajo el despegue dice cuánto más abajo', () => {
  assert.equal(nombreDeVista('p01--10.jpg'), 'Punto I · −10 m');
});

test('un nombre que no es de vista se muestra tal cual, sin la extensión', () => {
  assert.equal(nombreDeVista('vista-rara.jpg'), 'vista-rara');
});

test('el medidor toma el peor punto y lo compara con el límite de 3°', () => {
  const sol = medicionDelSol([{ error_sol: 0.19 }, { error_sol: 0.77 }, { error_sol: 0.05 }]);

  assert.equal(sol.peor, 0.77);
  assert.equal(sol.revisar, false);
  assert.ok(Math.abs(sol.fraccion - 0.77 / 3) < 1e-9);
});

test('sobre 3° pide revisar y el medidor queda lleno', () => {
  const sol = medicionDelSol([{ error_sol: 4.2 }]);

  assert.equal(sol.revisar, true);
  assert.equal(sol.fraccion, 1);
});

test('sin vistas no hay medición', () => {
  assert.equal(medicionDelSol([]), null);
});
