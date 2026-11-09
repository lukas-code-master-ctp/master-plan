/** Las estadísticas del sitio: barras, tarjetas y la frase que resume. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { barras, lectura, tarjetas, unaDeCada } from './js/estadisticas.js';

const dias = (cantidad) => Array.from({ length: cantidad }, (_, n) => ({
  dia: new Date(Date.UTC(2026, 9, 1 + n)).toISOString().slice(0, 10), visitas: n + 1,
}));

test('hasta 30 días hay una barra por día', () => {
  const lista = barras(dias(30));
  assert.equal(lista.length, 30);
  assert.equal(lista[0].valor, 1);
  assert.equal(lista[0].desde, '2026-10-01');
});

test('en 90 días las barras son semanas y suman sus visitas', () => {
  const lista = barras(dias(90));
  assert.equal(lista.length, 13);
  assert.equal(lista[0].valor, 1 + 2 + 3 + 4 + 5 + 6 + 7);
  // La última semana viene corta: 90 = 12 × 7 + 6.
  assert.equal(lista.at(-1).hasta, '2026-12-29');
  assert.equal(lista.reduce((s, b) => s + b.valor, 0), (90 * 91) / 2);
});

test('las tarjetas comparan con las visitas cuando hay con qué', () => {
  const [visitas, abiertas, whatsapp, interesa, reservas] = tarjetas({ totales: {
    visita: 280, ficha: 840, whatsapp: 10, reservar: 4, interesa: 0, reservas: 1 } });

  assert.equal(visitas.valor, 280);
  assert.equal(abiertas.detalle, '3,0 por visita');
  assert.equal(whatsapp.detalle, '1 de cada 28 visitas');
  assert.equal(interesa.detalle, null);
  assert.equal(reservas.detalle, '4 clics en Reservar');
  assert.equal(unaDeCada(5, 0), null);
});

test('la frase nombra la disponible que más se mira sin reservas', () => {
  const parcelas = [
    { parcela: '2-03', estado: 'reservado', ficha: 300, interesa: 1, reservas: 1 },
    { parcela: '2-21', estado: 'disponible', ficha: 412, interesa: 4, reservas: 0 },
  ];
  assert.match(lectura({ parcelas }), /^La 2-21 se abrió 412 veces y 4 dejaron sus datos/);
  assert.equal(lectura({ parcelas: [{ parcela: '1-1', estado: 'disponible', ficha: 3, reservas: 0 }] }), null);
});
