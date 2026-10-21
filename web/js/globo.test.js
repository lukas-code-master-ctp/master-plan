/** Dónde se apoya el globo de la parcela elegida. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { apoyoDelGlobo } from './globo.js';

// La 464 de Hacienda Vichuquén, como se veía en pantalla: una tira larga en
// diagonal, con la esquina alta a la derecha y la curva del camino abajo.
const tiraDiagonal = [
  [15, 170], [137, 53], [188, 57], [100, 157], [90, 162], [70, 165], [40, 172],
];

test('la punta cae sobre el borde de la parcela y no en el terreno de al lado', () => {
  const { x, apoyo } = apoyoDelGlobo(tiraDiagonal, 30);

  // El borde de arriba de la tira, entre (15,170) y (137,53), en la columna x.
  const bordeEnX = 170 + ((x - 15) / (137 - 15)) * (53 - 170);
  assert.ok(Math.abs(apoyo - bordeEnX) < 0.01);
  // Antes la punta iba a la altura de la esquina alta (y=53), lejos del borde.
  assert.ok(apoyo - 53 > 30);
});

test('el globo sube por sobre el tramo de parcela que tiene debajo', () => {
  const { x, apoyo, tope } = apoyoDelGlobo(tiraDiagonal, 30);
  const bordeA = (xx) => 170 + ((xx - 15) / (137 - 15)) * (53 - 170);

  assert.ok(Math.abs(tope - bordeA(x + 15)) < 0.01);
  assert.ok(tope < apoyo);
});

test('en un rectángulo derecho la punta va al centro de su borde de arriba', () => {
  const { x, apoyo, tope } = apoyoDelGlobo([[10, 20], [110, 20], [110, 80], [10, 80]], 30);

  assert.equal(x, 60);
  assert.equal(apoyo, 20);
  assert.equal(tope, 20);
});

test('una curva con muchos puntos no corre la columna del globo', () => {
  // Un cuadrado de 0 a 100 cuyo lado izquierdo trae veinte puntos.
  const izquierdo = Array.from({ length: 20 }, (_, i) => [0, 100 - i * 5]);
  const { x } = apoyoDelGlobo([...izquierdo, [0, 0], [100, 0], [100, 100]], 0);

  assert.ok(Math.abs(x - 50) < 0.01);
});

test('sin contorno no hay globo', () => {
  assert.equal(apoyoDelGlobo([], 30), null);
});
