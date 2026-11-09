/** Las cifras del sitio: qué se cuenta una vez, cómo se juntan y adónde van. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Cifras } from './cifras.js';

const META = { consola: 'https://consola.cl', loteo: 'praderas' };

function memoria() {
  const datos = new Map();
  return { getItem: (k) => datos.get(k) ?? null, setItem: (k, v) => datos.set(k, v) };
}

function armar(meta = META, guardado = memoria()) {
  const pedidos = [];
  const reloj = { setTimeout: () => 1, clearTimeout: () => {} };
  const cifras = new Cifras(meta, {
    memoria: guardado, reloj, pedir: async (url, opciones) => { pedidos.push({ url, ...opciones }); },
  });
  return { cifras, pedidos };
}

const eventosDe = (pedido) => JSON.parse(pedido.body).eventos;

test('los eventos se juntan y salen en un pedido a la consola del sitio', () => {
  const { cifras, pedidos } = armar();
  cifras.anotar('visita');
  cifras.anotar('ficha', '1-7');
  cifras.anotar('whatsapp', '1-7');
  assert.equal(pedidos.length, 0);

  cifras.enviar();

  assert.equal(pedidos.length, 1);
  assert.equal(pedidos[0].url, 'https://consola.cl/api/publico/eventos');
  assert.equal(pedidos[0].keepalive, true);
  assert.equal(pedidos[0].credentials, 'omit');
  assert.equal(JSON.parse(pedidos[0].body).loteo, 'praderas');
  assert.deepEqual(eventosDe(pedidos[0]), [
    { tipo: 'visita' }, { tipo: 'ficha', parcela: '1-7' }, { tipo: 'whatsapp', parcela: '1-7' }]);
});

test('la visita y cada ficha cuentan una vez por sesión; los clics, todos', () => {
  const guardado = memoria();
  const { cifras, pedidos } = armar(META, guardado);
  for (let n = 0; n < 2; n += 1) {
    cifras.anotar('visita');
    cifras.anotar('ficha', '1-7');
    cifras.anotar('reservar', '1-7');
  }
  cifras.enviar();
  assert.deepEqual(eventosDe(pedidos[0]).map((e) => e.tipo), ['visita', 'ficha', 'reservar', 'reservar']);

  // Al recargar la página, la sesión recuerda lo contado.
  const otra = armar(META, guardado);
  otra.cifras.anotar('visita');
  otra.cifras.anotar('ficha', '1-8');
  otra.cifras.enviar();
  assert.deepEqual(eventosDe(otra.pedidos[0]), [{ tipo: 'ficha', parcela: '1-8' }]);
});

test('sin consola no se anota ni se manda nada', () => {
  const { cifras, pedidos } = armar({ loteo: 'praderas' });
  cifras.anotar('visita');
  cifras.enviar();
  assert.equal(pedidos.length, 0);
});

test('nunca pasa del tope de eventos por pedido', () => {
  const { cifras, pedidos } = armar();
  for (let n = 0; n < 65; n += 1) cifras.anotar('whatsapp', '1-7');
  cifras.enviar();
  assert.deepEqual(pedidos.map((p) => eventosDe(p).length), [30, 30, 5]);
});

test('sin almacenamiento de sesión igual cuenta', () => {
  const roto = { getItem: () => { throw new Error('privado'); }, setItem: () => { throw new Error('privado'); } };
  const { cifras, pedidos } = armar(META, roto);
  cifras.anotar('visita');
  cifras.enviar();
  assert.equal(pedidos.length, 1);
});
