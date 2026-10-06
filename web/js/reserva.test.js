/** El formulario de reserva: qué manda, qué parcelas quedan apartadas y qué decir si falla. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  aplicarApartadas, cuerpoSolicitud, destinoDelPago, mensajeDeError, pedirApartadas,
} from './reserva.js';

const META = { consola: 'https://consola.cl', loteo: 'praderas', link_reserva: 'https://pago.cl/r' };

// --- apartadas -----------------------------------------------------------------------

test('una parcela disponible apartada se muestra como reserva en proceso', () => {
  const parcelas = [{ id: '1-7', estado: 'disponible' }, { id: '1-8', estado: 'disponible' }];

  const resultado = aplicarApartadas(parcelas, { '1-7': '2026-10-06T17:00:00+00:00' });

  assert.deepEqual(resultado, [
    { id: '1-7', estado: 'reservado', apartada: true },
    { id: '1-8', estado: 'disponible' },
  ]);
  // Sin tocar las originales.
  assert.equal(parcelas[0].estado, 'disponible');
});

test('una apartada que el inventario ya marcó vendida sigue vendida', () => {
  const resultado = aplicarApartadas([{ id: '1-7', estado: 'vendido' }], { '1-7': null });

  assert.deepEqual(resultado, [{ id: '1-7', estado: 'vendido' }]);
});

test('sin consola no se piden apartadas y no hay ninguna', async () => {
  let pedido = false;
  const resultado = await pedirApartadas({ loteo: 'x' }, async () => { pedido = true; });

  assert.deepEqual(resultado, {});
  assert.equal(pedido, false);
});

test('las apartadas se piden a la consola del sitio para su loteo', async () => {
  let url;
  const resultado = await pedirApartadas(META, async (pedida) => {
    url = pedida;
    return { ok: true, json: async () => ({ '1-7': null }) };
  });

  assert.equal(url, 'https://consola.cl/api/publico/apartadas?loteo=praderas');
  assert.deepEqual(resultado, { '1-7': null });
});

test('si la consola no contesta, el sitio sigue sin apartadas', async () => {
  const resultado = await pedirApartadas(META, async () => { throw new TypeError('sin red'); });

  assert.deepEqual(resultado, {});
});

// --- la solicitud ----------------------------------------------------------------------

test('la solicitud lleva el loteo, la parcela y lo que escribió el comprador', () => {
  const campos = { nombre: ' Pedro ', telefono: '+56 9 8765 4321', email: 'p@c.cl', sitio: '' };

  assert.deepEqual(JSON.parse(cuerpoSolicitud(META, { id: '1-7' }, campos)), {
    loteo: 'praderas', parcela: '1-7', nombre: 'Pedro', telefono: '+56 9 8765 4321',
    email: 'p@c.cl', sitio: '',
  });
});

test('después de apartar, el pago va al link propio de la parcela si lo tiene', () => {
  assert.equal(destinoDelPago({ link_pago: 'https://pago.cl/7' }, 'https://pago.cl/r?parcela=1-7'),
               'https://pago.cl/7');
  assert.equal(destinoDelPago({}, 'https://pago.cl/r?parcela=1-7'), 'https://pago.cl/r?parcela=1-7');
});

// --- errores -----------------------------------------------------------------------------

test('lo que la consola explica (datos o parcela tomada) se muestra tal cual', () => {
  assert.equal(mensajeDeError(400, 'Escribe un correo válido.'), 'Escribe un correo válido.');
  assert.equal(mensajeDeError(409, 'Esta parcela está apartada.'), 'Esta parcela está apartada.');
});

test('demasiados intentos y fallas sin explicación dan un mensaje propio', () => {
  assert.match(mensajeDeError(429, null), /muchas solicitudes/);
  assert.match(mensajeDeError(0, null), /No pudimos apartar/);
  assert.match(mensajeDeError(500, 'Internal Server Error'), /No pudimos apartar/);
});
