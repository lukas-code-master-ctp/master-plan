import { test } from 'node:test';
import assert from 'node:assert/strict';

import { estadoDelLoteo, marcasDeCuenta, resumenDe } from './js/backoffice.js';

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
