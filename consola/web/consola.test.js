/**
 * Que el guion y la página se sigan hablando, y que lo que decide sin DOM
 * decida bien.
 *
 * La app no tiene framework: los módulos buscan nodos por id y por
 * `data-accion`, y si alguien renombra uno en el HTML no falla nada al cargar
 * —`$('#loque-sea')` devuelve null— sino después, cuando alguien hace clic.
 * Las primeras pruebas convierten ese silencio en un error de la suite.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { dinero, iniciales, ruta } from './js/comun.js';

const aqui = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(aqui, 'index.html'), 'utf8');
const modulos = readdirSync(join(aqui, 'js')).filter((f) => f.endsWith('.js'));
const guion = modulos.map((f) => readFileSync(join(aqui, 'js', f), 'utf8')).join('\n');
const servidor = readFileSync(join(aqui, '..', 'app.py'), 'utf8');

const conjunto = (texto, patron, grupo = 1) =>
  new Set([...texto.matchAll(patron)].map((c) => c[grupo]));

test('cada id que busca el guion existe en la página', () => {
  const enLaPagina = conjunto(html, /\bid="([^"]+)"/g);
  const queBusca = conjunto(guion, /\$\$?\(['`]#([\w-]+)['`\s]/g);

  const huerfanos = [...queBusca].filter((id) => !enLaPagina.has(id));

  assert.deepEqual(huerfanos, [],
    `el guion busca ids que no están en index.html: ${huerfanos.join(', ')}`);
});

test('cada acción que despacha el guion existe como botón', () => {
  const enLaPagina = conjunto(html, /data-accion="([\w-]+)"/g);
  // `manejar()` compara contra literales: esos son los nombres que hay que tener.
  const queDespacha = conjunto(guion, /accion === '([\w-]+)'/g);

  const huerfanas = [...queDespacha].filter((a) => !enLaPagina.has(a));

  assert.deepEqual(huerfanas, [],
    `el guion despacha acciones sin botón: ${huerfanas.join(', ')}`);
});

test('todo botón de la página tiene quién lo atienda', () => {
  const enLaPagina = conjunto(html, /data-accion="([\w-]+)"/g);
  const queDespacha = conjunto(guion, /accion === '([\w-]+)'/g);

  const sinAtender = [...enLaPagina].filter((a) => !queDespacha.has(a));

  assert.deepEqual(sinAtender, [],
    `hay botones que no hacen nada al tocarlos: ${sinAtender.join(', ')}`);
});

test('el servidor sirve todos los módulos, y solo esos', () => {
  // El servidor los sirve de una lista cerrada: un módulo nuevo que no esté en
  // ella da 404 y la página queda en blanco sin decir por qué.
  const lista = servidor.match(/MODULOS = \(([^)]*)\)/s)[1];
  const servidos = conjunto(lista, /"([\w.-]+\.js)"/g);

  assert.deepEqual([...servidos].sort(), [...modulos].sort());
});

test('cada módulo que se importa existe', () => {
  const importados = conjunto(guion, /from '\.\/([\w.-]+\.js)'/g);

  const faltan = [...importados].filter((m) => !modulos.includes(m));

  assert.deepEqual(faltan, []);
});

// --- lo que no necesita la página ------------------------------------------------

test('el hash elige la pantalla', () => {
  assert.deepEqual(ruta(''), { pantalla: 'planos' });
  assert.deepEqual(ruta('#/planos'), { pantalla: 'planos' });
  assert.deepEqual(ruta('#/planos/nuevo'), { pantalla: 'nuevo' });
  assert.deepEqual(ruta('#/planos/praderas-de-cauquenes'),
    { pantalla: 'plano', slug: 'praderas-de-cauquenes' });
  assert.deepEqual(ruta('#/disenos'), { pantalla: 'disenos' });
  assert.deepEqual(ruta('#/cualquier-cosa'), { pantalla: 'planos' });
});

test('las iniciales del avatar salen del correo', () => {
  assert.equal(iniciales('ana.perez@losrobles.cl'), 'AP');
  assert.equal(iniciales('e.ruiz@compratuparcela.cl'), 'ER');
  assert.equal(iniciales('luis@delvalle.cl'), 'L');
  assert.equal(iniciales(''), '?');
});

test('el precio se escribe como en el visor', () => {
  assert.equal(dinero(9990000, 'CLP'), '$9.990.000');
  assert.equal(dinero(1250, 'UF'), 'UF 1.250');
  assert.equal(dinero(null, 'CLP'), null);
});
