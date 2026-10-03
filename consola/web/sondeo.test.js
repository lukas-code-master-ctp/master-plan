/**
 * El sondeo de un trabajo que desaparece: la instancia se reinició y ya no lo conoce.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { FALLOS_SEGUIDOS_MAX, textoInterrumpido, trasFalloDeSondeo } from './js/sondeo.js';
import { avance } from './js/vuelo.js';

const http = (estado) => Object.assign(new Error(`Error ${estado}`), { estado });
const deRed = () => new TypeError('Failed to fetch');

test('un 404 es un trabajo perdido: se deja de sondear al tiro', () => {
  assert.equal(trasFalloDeSondeo(http(404), 0).que, 'interrumpido');
  // Aunque vinieran errores de red antes (la instancia estaba arrancando).
  assert.equal(trasFalloDeSondeo(http(404), 3).que, 'interrumpido');
});

test('errores de red y 502/503/504 seguidos: se reintenta y, al quinto, se da por interrumpido', () => {
  for (const error of [deRed(), http(502), http(503), http(504)]) {
    let fallos = 0;
    const acciones = [];
    const esperas = [];
    for (let i = 0; i < FALLOS_SEGUIDOS_MAX; i += 1) {
      const d = trasFalloDeSondeo(error, fallos);
      fallos = d.fallos;
      acciones.push(d.que);
      esperas.push(d.espera);
    }
    assert.deepEqual(acciones, [...Array(FALLOS_SEGUIDOS_MAX - 1).fill('reintentar'), 'interrumpido']);
    // Cada vez se espera más: la instancia nueva tarda en arrancar.
    assert.ok(esperas.slice(0, -1).every((e, i, todas) => e > 0 && (i === 0 || e > todas[i - 1])));
  }
});

test('un sondeo bueno entre medio vuelve a contar desde cero', () => {
  // Quien sondea pone fallos = 0 al recibir una respuesta: el siguiente error es el primero.
  const d = trasFalloDeSondeo(deRed(), 0);
  assert.deepEqual(d, { que: 'reintentar', fallos: 1, espera: 1000 });
});

test('otros errores se avisan y se deja de sondear, como antes', () => {
  for (const estado of [401, 403, 500]) {
    assert.equal(trasFalloDeSondeo(http(estado), 0).que, 'detener');
  }
});

test('el texto dice qué se interrumpió', () => {
  const kmz = textoInterrumpido('kmz:rapel', 'digitalizar-plano');
  assert.equal(kmz, 'La digitalización se interrumpió (el servidor se reinició). Vuelve a intentarlo.');
  assert.equal(textoInterrumpido('kmz:rapel', undefined), kmz);
  assert.match(textoInterrumpido('hidango', 'construir'), /^La construcción se interrumpió/);
  assert.match(textoInterrumpido('hidango', 'publicar'), /^La publicación se interrumpió/);
});

test('la tarjeta del escáner queda fallida con esa causa, sin el "Error:" de adelante', () => {
  const texto = textoInterrumpido('kmz:rapel', 'digitalizar-plano');
  const lineas = ['Página 1 de 1: 5008×7038 px', 'Rótulos: 30 de 96 pasadas (360 s)', `Error: ${texto}`];
  const progreso = avance(lineas, 'digitalizar-plano', true, true);
  assert.equal(progreso.causa, texto);
  assert.equal(progreso.paso, 2);
});

test('la barra del lector no retrocede cuando Y baja de 96 a las pasadas que se leen', () => {
  // Lo que escribe `rotulos.leer`: el sondeo (16 pasadas, Y = 96) y después solo los
  // ángulos de las orientaciones encontradas (Y = 16 + el resto).
  const lineas = [
    'Página 1 de 1: 5008×7038 px',
    'Rótulos: texto típico de 15 px; hasta 96 pasadas de Tesseract en 2 hebras, por teselas (9 por pasada, de hasta 14 Mpx)',
    'Rótulos: 2 de 96 pasadas (40 s)',
    'Rótulos: 8 de 96 pasadas (160 s)',
    'Rótulos: 16 de 96 pasadas (320 s)',
    'Rótulos: orientaciones de los rótulos 345°, 0°, 15°, 75°, 90°, 105°; se leen 36 pasadas de 96',
    'Rótulos: 18 de 36 pasadas (360 s)',
    'Rótulos: 26 de 36 pasadas (480 s)',
    'Rótulos: 36 de 36 pasadas (600 s)',
    'Rótulos: 120 números leídos (110 con apoyo ≥ 2) en 600 s',
    'Cuadrícula: 8 de 16 pasadas (2 s)',
  ];
  let antes = -1;
  for (let i = 1; i <= lineas.length; i += 1) {
    const { fraccion } = avance(lineas.slice(0, i), 'digitalizar-plano');
    assert.ok(fraccion >= antes, `retrocede en la línea ${i}: ${lineas[i - 1]}`);
    antes = fraccion;
  }
  // El sondeo no deja la barra al 100 % del tramo; el resto la lleva adelante.
  const tras = (n) => avance(lineas.slice(0, n), 'digitalizar-plano').fraccion;
  assert.ok(tras(5) < tras(7));
});
