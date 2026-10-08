/** El visor dentro de un iframe (la landing de tumasterplan.cl) no se adueña del scroll. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { estaInsertado, pistaDelVisor, ruedaAcerca } from './insertado.js';

test('una ventana que es su propia cima no está insertada', () => {
  const ventana = {};
  ventana.self = ventana;
  ventana.top = ventana;

  assert.equal(estaInsertado(ventana), false);
});

test('una ventana con otra cima está insertada', () => {
  assert.equal(estaInsertado({ self: {}, top: {} }), true);
});

test('si leer la cima falla, se toma como insertada', () => {
  const ventana = { self: {} };
  Object.defineProperty(ventana, 'top', { get() { throw new Error('cross-origin'); } });

  assert.equal(estaInsertado(ventana), true);
});

test('suelto, la rueda siempre acerca', () => {
  assert.equal(ruedaAcerca({ ctrlKey: false, metaKey: false }, false), true);
});

test('insertado, la rueda sola es para bajar por la página', () => {
  assert.equal(ruedaAcerca({ ctrlKey: false, metaKey: false }, true), false);
});

test('insertado, con Ctrl o ⌘ la rueda acerca (el pellizco del trackpad trae Ctrl)', () => {
  assert.equal(ruedaAcerca({ ctrlKey: true, metaKey: false }, true), true);
  assert.equal(ruedaAcerca({ ctrlKey: false, metaKey: true }, true), true);
});

test('la pista dice qué tecla usar según dónde corre', () => {
  assert.equal(pistaDelVisor(false, false), 'Arrastra para mirar · rueda para acercar');
  assert.equal(pistaDelVisor(true, false), 'Arrastra para mirar · Ctrl + rueda para acercar');
  assert.equal(pistaDelVisor(true, true), 'Arrastra para mirar · ⌘ + rueda para acercar');
});
