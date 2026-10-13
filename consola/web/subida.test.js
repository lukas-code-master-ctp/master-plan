/** El vuelo se sube en tandas: un solo pedido de gigas llenaba la memoria del servidor. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { tandas } from './js/subida.js';

const MB = 1024 * 1024;
const archivo = (ruta, megas) => ({ ruta, archivo: { size: megas * MB } });
const rutas = (grupos) => grupos.map((grupo) => grupo.map((a) => a.ruta));

test('el KMZ y los archivos chicos van en la primera tanda', () => {
  const lista = [archivo('P1/DJI_1.JPG', 65), archivo('loteo.kmz', 1), archivo('inventario.xlsx', 1)];

  const grupos = tandas(lista, 100);

  assert.equal(grupos[0][0].ruta, 'loteo.kmz');
  assert.deepEqual(rutas(grupos), [['loteo.kmz', 'inventario.xlsx', 'P1/DJI_1.JPG']]);
});

test('ninguna tanda pasa del tope', () => {
  const lista = Array.from({ length: 10 }, (_, i) => archivo(`P1/DJI_${i}.JPG`, 65));

  const grupos = tandas(lista, 256);

  assert.deepEqual(grupos.map((g) => g.length), [3, 3, 3, 1]);
  for (const grupo of grupos) {
    assert.ok(grupo.reduce((suma, a) => suma + a.archivo.size, 0) <= 256 * MB);
  }
});

test('un archivo más grande que el tope va solo, y el servidor dirá si lo acepta', () => {
  const lista = [archivo('chico.JPG', 10), archivo('video.mp4', 900), archivo('otro.JPG', 10)];

  // El video no es foto: va antes que las panorámicas, y solo.
  assert.deepEqual(rutas(tandas(lista, 256)), [['video.mp4'], ['chico.JPG', 'otro.JPG']]);
});

test('sin archivos no hay tandas', () => {
  assert.deepEqual(tandas([], 256), []);
});
