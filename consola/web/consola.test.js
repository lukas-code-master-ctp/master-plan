/**
 * Que el guion y la página se sigan hablando.
 *
 * La consola no tiene framework: el JavaScript busca nodos por id y por
 * `data-accion`, y si alguien renombra uno en el HTML no falla nada al cargar
 * —`$('#loque-sea')` devuelve null— sino después, cuando alguien hace clic.
 * Estas dos pruebas convierten ese silencio en un error de la suite.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const aqui = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(aqui, 'index.html'), 'utf8');
const guion = readFileSync(join(aqui, 'consola.js'), 'utf8');

const conjunto = (texto, patron, grupo = 1) =>
  new Set([...texto.matchAll(patron)].map((c) => c[grupo]));

test('cada id que busca el guion existe en la página', () => {
  const enLaPagina = conjunto(html, /\bid="([^"]+)"/g);
  const queBusca = conjunto(guion, /\$\$?\('#([\w-]+)'/g);

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
