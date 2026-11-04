/** Qué pastillas de parcela se dibujan cuando no caben todas. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { rotulosSinChoques, acomodarReferencias, centroVisible } from './rotulos.js';

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

const lugar = (id, x, y, ancho = 120) => ({ id, x, y, ancho });

test('un lugar suelto lleva su rótulo derecho encima, con alfiler vertical', () => {
  const puestos = acomodarReferencias([lugar('a', 100, 300), lugar('b', 600, 300)], { alfiler: 22 });

  assert.deepEqual(puestos.get('a'), { cx: 100, cy: 278, lado: 'centro', guia: [[100, 300], [100, 278]] });
  assert.equal(puestos.get('b').lado, 'centro');
});

test('lugares en la misma dirección conservan cada uno su punto y no se cruzan', () => {
  // Fundo Atalaya: cinco lugares hacia la costa, con los puntos a pocos px.
  const lugares = [lugar('playa', 675, 382), lugar('centro', 700, 378), lugar('golf', 765, 378, 300),
    lugar('humedal', 698, 374), lugar('puerto', 699, 366)];
  const puestos = acomodarReferencias(lugares, { anchoPantalla: 1400 });

  for (const { id, x, y } of lugares) {
    const { guia, lado } = puestos.get(id);
    assert.equal(lado, 'derecha');
    assert.deepEqual(guia[0], [x, y], `${id} arranca en su propio punto`);
  }
  // A la derecha: el punto más a la derecha lleva el rótulo más bajo.
  const deAbajoArriba = [...puestos].sort((a, b) => b[1].cy - a[1].cy).map(([id]) => id);
  assert.deepEqual(deAbajoArriba, ['golf', 'centro', 'puerto', 'humedal', 'playa']);
  // Ningún tramo horizontal corta el tramo vertical de otro.
  for (const [, a] of puestos) {
    for (const [, b] of puestos) {
      if (a === b) continue;
      const [[bx, by0], [, by1]] = b.guia;
      const [, [ax, ay], [aBorde]] = a.guia;
      const corta = ax < bx && bx < aBorde && Math.min(by0, by1) < ay && ay < Math.max(by0, by1);
      assert.ok(!corta);
    }
  }
  // Las píldoras de la columna no se pisan.
  const alturas = [...puestos.values()].map((p) => p.cy).sort((m, n) => m - n);
  alturas.slice(1).forEach((y, k) => assert.ok(y - alturas[k] >= 32));
});

test('sin lugar a la derecha la columna se abre hacia la izquierda', () => {
  const puestos = acomodarReferencias([lugar('a', 1300, 300), lugar('b', 1302, 296)], { anchoPantalla: 1400 });

  assert.equal(puestos.get('a').lado, 'izquierda');
  assert.ok(puestos.get('a').cx <= 1300 - 14);
});

test('en una pantalla angosta los nombres largos se cortan en vez de tapar los alfileres', () => {
  // Celular: puntos entre x 172 y 256 y una píldora de 290 que no cabe a ningún lado.
  const puestos = acomodarReferencias([lugar('a', 172, 358, 120), lugar('b', 256, 357, 290)], { anchoPantalla: 390 });

  const b = puestos.get('b');
  assert.equal(b.lado, 'izquierda');
  assert.equal(b.cx, 172 - 14);
  assert.equal(b.anchoMaximo, 172 - 14 - 8);
  // La que cabe entera no se corta.
  assert.equal(puestos.get('a').anchoMaximo, undefined);
});

test('la columna nunca se sale de la pantalla', () => {
  // Ni cortando cabe (menos de 110 px libres): se corre hasta entrar.
  const puestos = acomodarReferencias([lugar('a', 100, 358, 255), lugar('b', 290, 357, 290)], { anchoPantalla: 390 });

  for (const p of puestos.values()) {
    const x0 = p.lado === 'derecha' ? p.cx : p.cx - 290;
    assert.ok(x0 >= 8 && x0 + 290 <= 390 - 8 + 1e-9);
  }
});

// --- Nombre de una zona ----------------------------------------------------

test('el nombre de una zona que se ve entera va en su centro', () => {
  const [x, y] = centroVisible([[100, 100], [300, 100], [300, 200], [100, 200]], 1000, 800);

  assert.ok(Math.abs(x - 200) < 1e-9 && Math.abs(y - 150) < 1e-9);
});

test('el nombre de una zona que se sale de la pantalla va en lo que se ve de ella', () => {
  // La zona sigue 2000 px a la izquierda: su centro real queda fuera.
  const [x, y] = centroVisible([[-2000, 100], [500, 100], [500, 300], [-2000, 300]], 1000, 800, 40);

  assert.ok(Math.abs(x - 270) < 1e-9);
  assert.ok(Math.abs(y - 200) < 1e-9);
});

test('una zona fuera de la pantalla no lleva nombre', () => {
  assert.equal(centroVisible([[-500, 100], [-100, 100], [-100, 300]], 1000, 800), null);
});
