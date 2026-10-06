/** La miniatura de "Entrar a 360°" y el conteo de la franja de perspectivas. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { encuadreMiniatura, textoConteo } from './perspectivas.js';

const LADO = 80;

test('con 90° de abertura, la panorámica mide cuatro miniaturas de ancho y la mitad de alto', () => {
  const { ancho, alto } = encuadreMiniatura({ azimut: 0, elevacion: 0 }, 0, LADO);

  assert.equal(ancho, 320);
  assert.equal(alto, 160);
});

test('mirando al rumbo inicial y al horizonte, el centro de la miniatura es el borde izquierdo y la mitad de la imagen', () => {
  const { x, y } = encuadreMiniatura({ azimut: 120, elevacion: 0 }, 120, LADO);

  // La columna 0 de la imagen queda al centro de la miniatura (40 px) y la fila
  // del horizonte (80 px de 160) también.
  assert.equal(x, 40);
  assert.equal(y, -40);
});

test('girar 90° a la derecha corre la imagen una miniatura entera hacia la izquierda', () => {
  const recto = encuadreMiniatura({ azimut: 10, elevacion: -30 }, 10, LADO);
  const girado = encuadreMiniatura({ azimut: 100, elevacion: -30 }, 10, LADO);

  assert.equal(recto.x - girado.x, LADO);
});

test('un azimut por debajo del rumbo inicial da la vuelta en vez de salirse de la imagen', () => {
  const { x } = encuadreMiniatura({ azimut: 350, elevacion: 0 }, 10, LADO);

  // 340° más allá del rumbo inicial: 340/360 de 320 px.
  assert.equal(x, 40 - (340 / 360) * 320);
});

test('mirar hacia abajo baja el encuadre hacia el terreno', () => {
  const horizonte = encuadreMiniatura({ azimut: 0, elevacion: 0 }, 0, LADO);
  const abajo = encuadreMiniatura({ azimut: 0, elevacion: -30 }, 0, LADO);

  // 30° de 180 son un sexto de los 160 px de alto.
  assert.ok(Math.abs(horizonte.y - abajo.y - 160 / 6) < 1e-9);
});

test('el conteo dice puntos en plural y punto en singular', () => {
  assert.equal(textoConteo(3), '3 puntos de vuelo');
  assert.equal(textoConteo(1), '1 punto de vuelo');
});
