/** Grupos de parcelas vecinas: de lejos, una burbuja con contador en vez de números encimados. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { agruparParcelas, debeColapsar, rangoDe, resumenDeGrupo } from './grupos.js';

// Una cuadrícula de lotes de ~70 m, como un loteo de verdad: filas de `ancho` lotes.
function cuadricula(cuantas, ancho = 10) {
  return Array.from({ length: cuantas }, (_, i) => ({
    id: `A${i + 1}`,
    rotulo: String(i + 1),
    estado: i % 3 === 0 ? 'disponible' : 'vendido',
    centroide: [-72 + (i % ancho) * 0.0008, -34.8 + Math.floor(i / ancho) * 0.0006],
  }));
}

test('cada parcela con polígono queda en un solo grupo, y ninguno pasa del tamaño', () => {
  const parcelas = [...cuadricula(579), { id: 'SIN', rotulo: 'x', estado: 'vendido', centroide: null }];

  const grupos = agruparParcelas(parcelas, { tamano: 12 });

  const ids = grupos.flatMap((g) => g.ids);
  assert.equal(ids.length, 579);
  assert.equal(new Set(ids).size, 579);
  assert.ok(!ids.includes('SIN'));
  assert.ok(grupos.every((g) => g.ids.length <= 12 && g.ids.length >= 1));
});

test('cada grupo sigue la numeración y se corta donde los lotes dejan de ser vecinos', () => {
  // Filas de 20 lotes de ~70 m: del 20 al 21 se salta a la fila de al lado, lejos.
  const grupos = agruparParcelas(cuadricula(400, 20), { tamano: 12 });

  for (const grupo of grupos) {
    const numeros = grupo.ids.map((id) => Number(id.slice(1)));
    // Seguidos: es un rango de verdad.
    assert.deepEqual(numeros, numeros.map((_, i) => numeros[0] + i));
    // Y en una sola fila: no cruza al otro extremo del loteo.
    assert.equal(new Set(numeros.map((n) => Math.ceil(n / 20))).size, 1, numeros.join(','));
  }
});

test('el mismo loteo da los mismos grupos aunque las parcelas lleguen en otro orden', () => {
  const parcelas = cuadricula(150);
  const firma = (grupos) => grupos.map((g) => [...g.ids].sort().join(',')).sort().join('|');

  assert.equal(firma(agruparParcelas(parcelas)), firma(agruparParcelas([...parcelas].reverse())));
});

test('el centro del grupo es el promedio de sus parcelas', () => {
  const [grupo] = agruparParcelas(cuadricula(4, 2), { tamano: 12 });

  assert.deepEqual(grupo.centroide.map((v) => Number(v.toFixed(6))), [-71.9996, -34.7997]);
});

test('el rango va del rótulo menor al mayor, en orden numérico', () => {
  assert.equal(rangoDe(['120', '9', '160', '33']), '9–160');
  assert.equal(rangoDe(['7']), '7');
  assert.equal(rangoDe(['1-7', '1-12', '1-9']), '1-7–1-12');
});

test('el resumen cuenta solo lo que dejan ver los filtros', () => {
  const parcelas = cuadricula(6);
  const porId = new Map(parcelas.map((p) => [p.id, p]));
  const [grupo] = agruparParcelas(parcelas);
  const datos = {
    parcela: (id) => porId.get(id),
    esDisponible: (parcela) => parcela.estado === 'disponible',
  };

  assert.deepEqual(resumenDeGrupo(grupo, datos), { rango: '1–6', total: 6, disponibles: 2 });
  assert.deepEqual(resumenDeGrupo(grupo, { ...datos, visible: (id) => id !== 'A1' }),
                   { rango: '2–6', total: 5, disponibles: 1 });
});

test('un grupo se colapsa cuando no caben sus números y se abre cuando vuelven a caber', () => {
  // Abierto: aguanta hasta el 40 % de números escondidos.
  assert.equal(debeColapsar(4, 10, false), false);
  assert.equal(debeColapsar(5, 10, false), true);
  // Colapsado: no se abre hasta que falte menos del 20 %, para no parpadear al hacer zoom.
  assert.equal(debeColapsar(3, 10, true), true);
  assert.equal(debeColapsar(1, 10, true), false);
  // Con una sola parcela no hay grupo que mostrar.
  assert.equal(debeColapsar(1, 1, false), false);
});

test('si los números del grupo saltan, la burbuja dice cuántas son y no un rango engañoso', () => {
  // Dos filas enfrentadas: 120 a 125 de un lado del camino, 300 a 305 del otro.
  const parcelas = [...[120, 121, 122, 123, 124, 125], ...[300, 301, 302, 303, 304, 305]].map((n, i) => ({
    id: `A${n}`, rotulo: String(n), estado: 'disponible', centroide: [-72 + (i % 6) * 0.0008, -34.8],
  }));
  const porId = new Map(parcelas.map((p) => [p.id, p]));
  const grupo = { id: 'g0', ids: parcelas.map((p) => p.id) };

  const resumen = resumenDeGrupo(grupo, { parcela: (id) => porId.get(id), esDisponible: () => true });

  assert.equal(resumen.rango, '12 parcelas');
});
