import assert from 'node:assert/strict';
import test from 'node:test';

import {
  Camara, FRENADO_MS, VELOCIDAD_MAXIMA, VELOCIDAD_MINIMA, anguloEntre, direccion, escalaComunDeRotulos, frenar,
  giroMasCorto, recortarCerca, rumboCardinal, rumboCorto, suavizar, velocidadAlSoltar,
} from './camara.js';

const ANCHO = 1200;
const ALTO = 800;

const cerca = (a, b, tolerancia = 1e-6) =>
  assert.ok(Math.abs(a - b) <= tolerancia, `${a} no está cerca de ${b}`);

// --- direccion ---------------------------------------------------------------

test('el azimut 0 apunta al norte y el 90 al este', () => {
  const [nx, ny, nz] = direccion(0, 0);
  cerca(nx, 0); cerca(ny, 1); cerca(nz, 0);
  const [ex, ey, ez] = direccion(90, 0);
  cerca(ex, 1); cerca(ey, 0); cerca(ez, 0);
});

test('la elevación -90 apunta al nadir', () => {
  const [, , z] = direccion(37, -90);
  cerca(z, -1);
});

test('las direcciones son unitarias', () => {
  for (const [az, el] of [[0, 0], [123, -45], [359, 88]]) {
    const d = direccion(az, el);
    cerca(Math.hypot(...d), 1);
  }
});

test('el ángulo entre direcciones cruza bien el norte', () => {
  cerca(anguloEntre([359, 0], [1, 0]), 2, 1e-9);
});

// --- orientación -------------------------------------------------------------

test('la base de la cámara es ortonormal', () => {
  const camara = new Camara({ azimut: 123, elevacion: -37 });
  const { adelante, derecha, arriba } = camara.base();
  for (const v of [adelante, derecha, arriba]) cerca(Math.hypot(...v), 1);
  const punto = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  cerca(punto(adelante, derecha), 0, 1e-9);
  cerca(punto(adelante, arriba), 0, 1e-9);
  cerca(punto(derecha, arriba), 0, 1e-9);
});

test('la derecha de la cámara apunta a azimut creciente', () => {
  const { derecha } = new Camara({ azimut: 0, elevacion: 0 }).base();
  cerca(derecha[0], 1);   // mirando al norte, la derecha es el este
});

test('la elevación se acota para no dar vuelta la cámara', () => {
  const camara = new Camara();
  camara.apuntar(0, -200);
  assert.ok(camara.elevacion >= -88);
  camara.apuntar(0, 200);
  assert.ok(camara.elevacion <= 88);
});

test('el azimut siempre queda entre 0 y 360', () => {
  const camara = new Camara();
  camara.apuntar(-30, 0);
  cerca(camara.azimut, 330);
  camara.apuntar(725, 0);
  cerca(camara.azimut, 5);
});

test('el zoom se acota en ambos extremos', () => {
  const camara = new Camara({ fov: 70 });
  for (let i = 0; i < 50; i++) camara.acercar(0.8);
  assert.ok(camara.fov >= 22);
  for (let i = 0; i < 50; i++) camara.acercar(1.25);
  assert.ok(camara.fov <= 100);
});

// --- proyección --------------------------------------------------------------

test('el centro de la pantalla corresponde a hacia dónde mira la cámara', () => {
  const camara = new Camara({ azimut: 210, elevacion: -30 });
  const [x, y] = camara.aPantalla(camara.aCamara(210, -30), ANCHO, ALTO);
  cerca(x, ANCHO / 2, 1e-6);
  cerca(y, ALTO / 2, 1e-6);
});

test('proyectar y despronectar es la identidad', () => {
  const camara = new Camara({ azimut: 47, elevacion: -22, fov: 65 });
  for (const [px, py] of [[100, 100], [ANCHO / 2, ALTO / 2], [ANCHO - 30, ALTO - 40]]) {
    const [az, el] = camara.desdePantalla(px, py, ANCHO, ALTO);
    const [x, y] = camara.aPantalla(camara.aCamara(az, el), ANCHO, ALTO);
    cerca(x, px, 1e-6);
    cerca(y, py, 1e-6);
  }
});

test('lo que está a la derecha del centro se dibuja a la derecha', () => {
  const camara = new Camara({ azimut: 0, elevacion: 0 });
  const [x] = camara.aPantalla(camara.aCamara(10, 0), ANCHO, ALTO);
  assert.ok(x > ANCHO / 2);
});

test('lo que está más abajo se dibuja más abajo', () => {
  const camara = new Camara({ azimut: 0, elevacion: -20 });
  const [, arriba] = camara.aPantalla(camara.aCamara(0, -10), ANCHO, ALTO);
  const [, abajo] = camara.aPantalla(camara.aCamara(0, -30), ANCHO, ALTO);
  assert.ok(abajo > arriba);
});

test('acercar agranda lo que se ve', () => {
  const camara = new Camara({ azimut: 0, elevacion: 0, fov: 80 });
  const ancho = () => {
    const [a] = camara.aPantalla(camara.aCamara(-5, 0), ANCHO, ALTO);
    const [b] = camara.aPantalla(camara.aCamara(5, 0), ANCHO, ALTO);
    return b - a;
  };
  const antes = ancho();
  camara.acercar(0.5);
  assert.ok(ancho() > antes);
});

// --- recorte -----------------------------------------------------------------

test('un polígono completamente al frente no se toca', () => {
  const puntos = [[-1, -1, 5], [1, -1, 5], [1, 1, 5], [-1, 1, 5]];
  assert.equal(recortarCerca(puntos).length, 4);
});

test('un polígono completamente detrás desaparece', () => {
  const puntos = [[-1, -1, -5], [1, -1, -5], [1, 1, -5]];
  assert.equal(recortarCerca(puntos).length, 0);
});

test('un polígono a medio camino se corta en el plano cercano', () => {
  const puntos = [[-1, 0, 5], [1, 0, 5], [1, 0, -5], [-1, 0, -5]];
  const recortado = recortarCerca(puntos);
  assert.equal(recortado.length, 4);
  assert.ok(recortado.every(([, , z]) => z > 0));
});

test('el anillo proyectado se descarta si queda todo atrás', () => {
  const camara = new Camara({ azimut: 0, elevacion: 0 });
  const atras = [[180, -5], [182, -5], [182, -3], [180, -3]];
  assert.equal(camara.proyectarAnillo(atras, ANCHO, ALTO), null);
});

test('el anillo proyectado devuelve píxeles cuando está al frente', () => {
  const camara = new Camara({ azimut: 0, elevacion: -20 });
  const frente = [[-2, -22], [2, -22], [2, -18], [-2, -18]];
  const pixeles = camara.proyectarAnillo(frente, ANCHO, ALTO);
  assert.equal(pixeles.length, 4);
  for (const [x, y] of pixeles) {
    assert.ok(Number.isFinite(x) && Number.isFinite(y));
  }
});

// --- descarte rápido ---------------------------------------------------------

test('lo que está justo al frente puede verse', () => {
  const camara = new Camara({ azimut: 100, elevacion: -30 });
  assert.ok(camara.puedeVerse([100, -30], ANCHO, ALTO));
});

test('lo que está a la espalda no puede verse', () => {
  const camara = new Camara({ azimut: 100, elevacion: -30, fov: 60 });
  assert.ok(!camara.puedeVerse([280, -30], ANCHO, ALTO));
});

test('la apertura horizontal es mayor que el fov vertical en pantalla apaisada', () => {
  const camara = new Camara({ fov: 60 });
  assert.ok(camara.aperturaHorizontal(ANCHO, ALTO) > 60);
});

// --- matriz para el shader ---------------------------------------------------

test('la matriz lleva derecha, arriba y adelante en ese orden', () => {
  const camara = new Camara({ azimut: 31, elevacion: -12 });
  const { adelante, derecha, arriba } = camara.base();
  const m = camara.matriz();
  assert.equal(m.length, 9);
  [...derecha, ...arriba, ...adelante].forEach((v, i) => cerca(m[i], v, 1e-6));
});

// --- rumboCardinal -----------------------------------------------------------

test('el rumbo se nombra por el punto cardinal más cercano', () => {
  assert.equal(rumboCardinal(0), 'Norte');
  assert.equal(rumboCardinal(42), 'Noreste');
  assert.equal(rumboCardinal(91), 'Este');
  assert.equal(rumboCardinal(200), 'Sur');
  assert.equal(rumboCardinal(300), 'Noroeste');
});

test('cerca de 360° el rumbo vuelve a ser norte', () => {
  assert.equal(rumboCardinal(359), 'Norte');
  assert.equal(rumboCardinal(-10), 'Norte');
});

test('el rumbo abreviado cabe en un botón redondo', () => {
  assert.deepEqual([0, 42, 90, 135, 211, 270, 300].map(rumboCorto), ['N', 'NE', 'E', 'SE', 'SO', 'O', 'NO']);
});

test('la inercia toma la velocidad de los últimos movimientos antes de soltar', () => {
  const muestras = [
    { t: 0, azimut: 9, elevacion: 0 },      // viejo: solo marca desde cuándo se mide
    { t: 900, azimut: 1, elevacion: 0 },
    { t: 916, azimut: 1, elevacion: 0.5 },
    { t: 932, azimut: 1, elevacion: 0.5 },
  ];
  const v = velocidadAlSoltar(muestras, 948);
  assert.ok(Math.abs(v.azimut - 2 / 32) < 1e-9);
  assert.ok(Math.abs(v.elevacion - 1 / 32) < 1e-9);
});

test('con pocos eventos (un teléfono lento) igual hay impulso', () => {
  const muestras = [{ t: 0, azimut: 2, elevacion: 0 }, { t: 80, azimut: 2, elevacion: 0 }];
  const v = velocidadAlSoltar(muestras, 120);
  assert.ok(Math.abs(v.azimut - 2 / 80) < 1e-9);
});

test('un dedo que se quedó quieto antes de soltar no lanza la cámara', () => {
  const muestras = [{ t: 0, azimut: 3, elevacion: 0 }, { t: 16, azimut: 3, elevacion: 0 }];
  assert.deepEqual(velocidadAlSoltar(muestras, 400), { azimut: 0, elevacion: 0 });
});

test('un tirón se acota para que la vista no salga disparada', () => {
  const muestras = [{ t: 0, azimut: 0, elevacion: 0 }, { t: 16, azimut: 200, elevacion: 0 }];
  assert.equal(velocidadAlSoltar(muestras, 20).azimut, VELOCIDAD_MAXIMA);
});

test('la inercia se frena de a poco y llega a cero', () => {
  const v = frenar({ azimut: 1, elevacion: -1 }, FRENADO_MS);
  assert.ok(Math.abs(v.azimut - Math.exp(-1)) < 1e-9);
  assert.ok(Math.abs(v.elevacion + Math.exp(-1)) < 1e-9);
  assert.ok(Math.abs(frenar({ azimut: 1, elevacion: 0 }, 5000).azimut) < VELOCIDAD_MINIMA);
});

test('el vuelo entre encuadres gira por el camino corto', () => {
  assert.equal(giroMasCorto(350, 10), 20);
  assert.equal(giroMasCorto(10, 350), -20);
  assert.equal(giroMasCorto(90, 90), 0);
});

test('el vuelo arranca y llega despacio', () => {
  assert.equal(suavizar(0), 0);
  assert.equal(suavizar(1), 1);
  assert.equal(suavizar(0.5), 0.5);
  assert.ok(suavizar(0.1) < 0.1 && suavizar(0.9) > 0.9);
});

test('con los números fijos todas las pastillas van del mismo tamaño, más chico si se aprietan', () => {
  // Parcelas grandes en pantalla: tamaño normal en escritorio, algo menor en el celular.
  assert.equal(escalaComunDeRotulos([200, 150, 120, 300], 1400), 1);
  assert.equal(escalaComunDeRotulos([200, 150, 120, 300], 390), 0.82);
  // Muchas parcelas chicas: el mínimo que todavía se lee.
  assert.equal(escalaComunDeRotulos([10, 12, 15, 200], 1400), 0.8);
  assert.equal(escalaComunDeRotulos([10, 12, 15, 200], 390), 0.7);
  assert.equal(escalaComunDeRotulos([], 390), 0.82);
});
