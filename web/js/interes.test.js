/** "Me interesa": qué manda el sitio y qué decir si falla. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { cuerpoInteres, enviarInteres, mensajeDeErrorInteres } from './interes.js';

const META = { consola: 'https://consola.cl/', loteo: 'praderas' };

test('manda el loteo, la parcela y los datos limpios, con la trampa tal cual', () => {
  const cuerpo = JSON.parse(cuerpoInteres(META, { id: '1-7' }, {
    nombre: '  Camila ', telefono: ' +56 9 8123 4567', horario: 'tarde', sitio: '',
  }));

  assert.deepEqual(cuerpo, { loteo: 'praderas', parcela: '1-7', nombre: 'Camila',
                             telefono: '+56 9 8123 4567', email: '', horario: 'tarde', sitio: '' });
});

test('un horario que no existe se manda como "a cualquier hora"', () => {
  assert.equal(JSON.parse(cuerpoInteres(META, { id: '1-7' }, { horario: 'noche' })).horario, '');
});

test('se manda a la consola del sitio, en texto plano y sin cookies', async () => {
  let pedido;
  await enviarInteres(META, { id: '1-7' }, {}, async (url, opciones) => {
    pedido = { url, ...opciones };
    return { ok: true, status: 201, json: async () => ({ ok: true }) };
  });

  assert.equal(pedido.url, 'https://consola.cl/api/publico/interesados');
  assert.equal(pedido.headers['Content-Type'], 'text/plain');
  assert.equal(pedido.credentials, 'omit');
});

test('sin red contesta estado 0 y un mensaje genérico', async () => {
  const resultado = await enviarInteres(META, { id: '1-7' }, {}, async () => { throw new TypeError('sin red'); });

  assert.equal(resultado.estado, 0);
  assert.match(mensajeDeErrorInteres(resultado.estado), /No pudimos enviar/);
});

test('el motivo de la consola se muestra tal cual cuando es un dato que corregir', () => {
  assert.equal(mensajeDeErrorInteres(400, 'Escribe tu nombre.'), 'Escribe tu nombre.');
  assert.match(mensajeDeErrorInteres(429), /varios seguidos/);
});
