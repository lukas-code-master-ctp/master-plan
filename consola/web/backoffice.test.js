import { test } from 'node:test';
import assert from 'node:assert/strict';

import { calzaCon, estadoDelLoteo, juntarRepetidos, marcasDeCuenta, resumenDe } from './js/backoffice.js';

test('el estado de un loteo se mira desde el cobro', () => {
  assert.deepEqual(estadoDelLoteo({ publicado: true, pagado: true }), { texto: 'Publicado', tono: 'ok' });
  assert.deepEqual(estadoDelLoteo({ publicado: false, pagado: true }), { texto: 'Habilitado', tono: 'ok' });
  assert.deepEqual(estadoDelLoteo({ publicado: false, pagado: false, habilitacion_pedida: null }),
    { texto: 'Sin pagar', tono: null });
  const pedido = estadoDelLoteo({ publicado: false, pagado: false, habilitacion_pedida: '2026-10-21T15:00:00Z' });
  assert.equal(pedido.tono, 'aviso');
  assert.match(pedido.texto, /^Pidió habilitar · 21/);
});

test('el resumen de una loteadora cuenta loteos y cuentas en singular o plural', () => {
  assert.equal(resumenDe({ loteos: 1, cuentas: ['a@x.cl'] }), '1 loteo · 1 cuenta');
  assert.equal(resumenDe({ loteos: 3, cuentas: ['a@x.cl', 'b@x.cl'] }), '3 loteos · 2 cuentas');
});

test('una cuenta dice su rol y por qué podría no estar entrando', () => {
  assert.deepEqual(marcasDeCuenta({ rol: 'dueño', activo: true, email_verificado: true }),
    [{ texto: 'Dueño', tono: null }]);
  assert.deepEqual(marcasDeCuenta({ rol: 'equipo', activo: true, email_verificado: false })[1],
    { texto: 'Sin confirmar el correo', tono: 'aviso' });
  // Desactivada pesa más que sin confirmar: confirmar no la dejaría entrar.
  assert.deepEqual(marcasDeCuenta({ rol: 'equipo', activo: false, email_verificado: false }).slice(1),
    [{ texto: 'Desactivada', tono: 'apagada' }]);
});

test('el buscador calza por nombre o por correo, sin tildes ni mayúsculas', () => {
  const quillon = { nombre: 'Lomas de Quillón', slug: 'lomas', cuentas: ['ana@robles.cl'] };
  assert.ok(calzaCon(quillon, 'quillon'));
  assert.ok(calzaCon(quillon, 'ROBLES'));
  assert.ok(calzaCon(quillon, '  '));
  assert.ok(!calzaCon(quillon, 'praderas'));
});

test('lo último junta lo repetido del mismo día y deja lo distinto aparte', () => {
  const eduardo = { email: 'e@ctp.cl', nombre: 'Eduardo' };
  const ev = (que, cuando, quien = eduardo) => ({ que, detalle: 'Lomas', cuando, quien });
  const lineas = juntarRepetidos([
    ev('publicación', '2026-10-20T18:00:00'),
    ev('publicación', '2026-10-20T17:00:00'),
    ev('publicación', '2026-10-20T16:00:00'),
    ev('construcción', '2026-10-20T15:00:00'),
    ev('publicación', '2026-10-20T14:00:00'),
    ev('publicación', '2026-10-19T14:00:00'),
  ]);
  assert.deepEqual(lineas.map((l) => [l.evento.que, l.veces]),
    [['publicación', 3], ['construcción', 1], ['publicación', 1], ['publicación', 1]]);
});
