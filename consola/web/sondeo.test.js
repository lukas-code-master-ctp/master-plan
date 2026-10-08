/**
 * El sondeo de un trabajo que desaparece: la instancia se reinició y ya no lo conoce.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  ESPERA_MAX_MS, FALLOS_SEGUIDOS_MAX, relevo, retomarRegistro, textoInterrumpido, trasFalloDeSondeo,
} from './js/sondeo.js';
import { avance } from './js/vuelo.js';

const http = (estado) => Object.assign(new Error(`Error ${estado}`), { estado });
const deRed = () => new TypeError('Failed to fetch');

test('un 404 es un trabajo perdido: se deja de sondear al tiro', () => {
  assert.equal(trasFalloDeSondeo(http(404), 0).que, 'interrumpido');
  // Aunque vinieran errores de red antes (la instancia estaba arrancando).
  assert.equal(trasFalloDeSondeo(http(404), 3).que, 'interrumpido');
});

test('errores de red y 502/503/504 seguidos: se reintenta cerca de un minuto y después se da por interrumpido', () => {
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
    const reintentos = esperas.slice(0, -1);
    // Cada vez se espera más, hasta el tope: la instancia nueva tarda en arrancar.
    assert.ok(reintentos.every((e, i) => e > 0 && e <= ESPERA_MAX_MS && (i === 0 || e >= reintentos[i - 1])));
    assert.equal(Math.max(...reintentos), ESPERA_MAX_MS);
    // La del 2026-10-08 tardó ~20 s en quedar lista: se aguanta cerca de un minuto.
    const total = reintentos.reduce((a, b) => a + b, 0);
    assert.ok(total >= 55_000 && total <= 70_000, `aguanta ${total} ms`);
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
  assert.equal(kmz, 'La lectura del plano se interrumpió (el servidor se reinició). Vuelve a intentarlo.');
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

test('relevo: tras perder la lectura se sigue la que retomó la consola, con otro id', () => {
  const kmz = (trabajo) => ({ slug: 'rapel', nombre: 'Rapel', trabajo });
  const retomada = { id: 'nuevo', terminado: false, estado: 'corriendo',
    lineas: ['Se retoma la lectura del plano donde quedó (intento 2 de 3).'] };
  assert.equal(relevo(kmz(retomada), 'viejo'), 'nuevo');
  // Una que lanzó otra persona después del reinicio también es la lectura de este KMZ.
  assert.equal(relevo(kmz({ id: 'otra', terminado: false, lineas: [] }), 'viejo'), 'otra');
});

test('relevo: una retomada que ya terminó se sigue igual, para mostrar cómo terminó', () => {
  const lista = { id: 'nuevo', terminado: true, estado: 'listo',
    lineas: ['Se retoma la lectura del plano donde quedó (intento 2 de 3).', 'Lotes: 88'] };
  assert.equal(relevo({ trabajo: lista }, 'viejo'), 'nuevo');
  // Terminada y sin ser retomada no tiene que ver con lo que se estaba mirando.
  assert.equal(relevo({ trabajo: { id: 'otra', terminado: true, estado: 'listo', lineas: ['Página 1 de 1'] } }, 'viejo'), null);
});

test('relevo: sin trabajo, el mismo id o uno ya perdido no es relevo (no se dan vueltas)', () => {
  assert.equal(relevo({ trabajo: null }, 'viejo'), null);
  assert.equal(relevo(null, 'viejo'), null);
  assert.equal(relevo({ trabajo: { id: 'viejo', terminado: false } }, 'viejo'), null);
  assert.equal(relevo({ trabajo: { id: 'a', terminado: false } }, ['a', 'b']), null);
  assert.equal(relevo({ trabajo: { id: 'c', terminado: false } }, ['a', 'b']), 'c');
});

test('el escáner sigue la lectura retomada debajo de la perdida sin retroceder ni darla por fallida', () => {
  const perdida = [
    'Página 1 de 1: 5008×7038 px',
    'Rótulos: 16 de 96 pasadas (320 s)',
    'Rótulos: 26 de 36 pasadas (480 s)',
  ];
  const retomada = [
    'Se retoma la lectura del plano donde quedó (intento 2 de 3).',
    'Página 1 de 1: 5008×7038 px',
    'Rótulos: se retoman 26 pasadas ya leídas',
    'Rótulos: 28 de 36 pasadas (40 s)',
  ];
  const antes = avance(perdida, 'digitalizar-plano');
  let previa = antes.fraccion;
  for (let i = 1; i <= retomada.length; i += 1) {
    const ahora = avance([...perdida, ...retomada.slice(0, i)], 'digitalizar-plano');
    assert.equal(ahora.paso, 2, retomada[i - 1]);
    assert.equal(ahora.causa, null);
    assert.ok(ahora.fraccion >= previa, `retrocede en: ${retomada[i - 1]}`);
    previa = ahora.fraccion;
  }
  // Si la retomada falla, la causa es la suya, no la línea "Se retoma…".
  const fallida = avance([...perdida, ...retomada, 'Error: no encontré el dibujo'], 'digitalizar-plano', true, true);
  assert.equal(fallida.causa, 'no encontré el dibujo');
});

test('retomarRegistro: el mismo trabajo sigue donde iba, aunque el registro traiga el aviso de interrumpido', () => {
  assert.deepEqual(retomarRegistro({ id: 'a', total: 7 }, 'a'), { desde: 7, conservar: true });
  // Se dio por interrumpido (se agregó "Error: …se interrumpió") y después volvió a contestar.
  assert.deepEqual(retomarRegistro({ id: 'a', total: 7, perdido: true }, 'a'), { desde: 7, conservar: true });
});

test('retomarRegistro: otro trabajo empieza en su primera línea, sin saltarse las del largo del registro', () => {
  // La consola tardó más de un minuto: la pantalla dio la lectura por interrumpida y después
  // `refrescar` encuentra la retomada. Sus líneas van debajo de las de la perdida.
  assert.deepEqual(retomarRegistro({ id: 'viejo', total: 30, perdido: true }, 'nuevo'), { desde: 0, conservar: true });
  // Uno que terminó bien y otro que se lanzó después (otra pestaña): registro en limpio.
  assert.deepEqual(retomarRegistro({ id: 'viejo', total: 30 }, 'nuevo'), { desde: 0, conservar: false });
  // Tras recargar la página no se sabe nada: desde el principio.
  assert.deepEqual(retomarRegistro(undefined, 'nuevo'), { desde: 0, conservar: false });
});
