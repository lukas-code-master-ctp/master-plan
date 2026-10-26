import { test } from 'node:test';
import assert from 'node:assert/strict';

import { calzaCon, estadoDelLoteo, juntarRepetidos, marcasDeCuenta, resumenDe, resumenDelPlan } from './js/backoffice.js';

test('el estado de un loteo se mira desde el cobro', () => {
  assert.deepEqual(estadoDelLoteo({ publicado: true, pagado: false, habilitado: true }), { texto: 'Publicado', tono: 'ok' });
  assert.deepEqual(estadoDelLoteo({ publicado: true, pagado: true }), { texto: 'Publicado · pagado aparte', tono: 'ok' });
  assert.deepEqual(estadoDelLoteo({ publicado: false, pagado: true }), { texto: 'Pagado aparte', tono: 'ok' });
  assert.deepEqual(estadoDelLoteo({ publicado: false, pagado: false, habilitado: true }), { texto: 'Habilitado', tono: 'ok' });
  assert.deepEqual(estadoDelLoteo({ publicado: false, pagado: false, habilitado: false, habilitacion_pedida: null }),
    { texto: 'Sin plan', tono: null });
  const pedido = estadoDelLoteo({ publicado: false, pagado: false, habilitacion_pedida: '2026-10-21T15:00:00Z' });
  assert.equal(pedido.tono, 'aviso');
  assert.match(pedido.texto, /^Pidió habilitar · 21/);
});

test('el plan de una loteadora en una línea', () => {
  const planes = [{ plan: 'fly', nombre: 'Fly' }, { plan: 'pro', nombre: 'Pro' }];
  assert.equal(resumenDelPlan(null, planes), 'Sin plan');
  assert.equal(resumenDelPlan({ plan: null, pedido: 'pro' }, planes), 'Sin plan · pidió Pro');
  assert.equal(resumenDelPlan({ plan: 'fly', nombre: 'Fly', loteos: 1, en_linea: 1, pedido: 'pro' }, planes),
    'Fly · 1 de 1 en línea · pidió Pro');
  assert.equal(resumenDelPlan({ plan: 'pro', nombre: 'Pro', loteos: 3, en_linea: 2, pedido: null }, planes),
    'Pro · 2 de 3 en línea');
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
