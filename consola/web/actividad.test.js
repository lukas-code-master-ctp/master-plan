import { test } from 'node:test';
import assert from 'node:assert/strict';

import { agruparPorDia, fraseDe, nombreDelDia } from './js/actividad.js';

const PIA = { nombre: 'Pía Soto', email: 'pia@x.cl', rol: 'dueño' };

test('cada evento se cuenta como una frase con quien lo hizo y su tipo', () => {
  assert.deepEqual(fraseDe({ que: 'publicación', detalle: 'Praderas', quien: PIA }),
    { texto: 'Pía publicó Praderas', tipo: 'publicado', quien: 'Pía' });
  assert.equal(fraseDe({ que: 'contraseña cambiada', detalle: null, quien: PIA }).texto,
    'Pía cambió su contraseña');
  // Lo que hizo el equipo de CTP sin persona anotada.
  assert.equal(fraseDe({ que: 'loteo pagado', detalle: 'praderas · transferencia', quien: null }).texto,
    'Tu Masterplan anotó el pago de praderas · transferencia');
});

test('una reserva pedida es de un comprador, no de alguien del equipo', () => {
  const frase = fraseDe({ que: 'reserva pedida', detalle: 'Parcela 1-7 · Praderas', quien: null });
  assert.equal(frase.texto, 'Un comprador pidió reservar la Parcela 1-7 · Praderas');
  assert.equal(frase.tipo, 'reserva');
});

test('un evento desconocido igual se muestra', () => {
  assert.equal(fraseDe({ que: 'algo nuevo', detalle: 'x', quien: PIA }).texto, 'Pía: algo nuevo · x');
});

test('los días se llaman Hoy, Ayer o por su fecha', () => {
  const ahora = new Date(2026, 9, 9, 12, 0);
  assert.equal(nombreDelDia(new Date(2026, 9, 9, 0, 5), ahora), 'Hoy');
  assert.equal(nombreDelDia(new Date(2026, 9, 8, 23, 59), ahora), 'Ayer');
  assert.match(nombreDelDia(new Date(2026, 9, 6, 10, 0), ahora), /^Martes 6 de octubre$/);
});

test('los eventos se agrupan por día sin cambiar el orden', () => {
  const ahora = new Date(2026, 9, 9, 12, 0);
  const eventos = [
    { id: 3, cuando: new Date(2026, 9, 9, 11).toISOString() },
    { id: 2, cuando: new Date(2026, 9, 9, 9).toISOString() },
    { id: 1, cuando: new Date(2026, 9, 8, 18).toISOString() },
  ];
  const grupos = agruparPorDia(eventos, ahora);
  assert.deepEqual(grupos.map((g) => [g.titulo, g.eventos.map((e) => e.id)]), [['Hoy', [3, 2]], ['Ayer', [1]]]);
});
