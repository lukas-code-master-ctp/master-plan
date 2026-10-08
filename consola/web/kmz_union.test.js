/**
 * Crea tu KMZ: la geometría de la unión de hojas. Los casos numéricos son los de
 * `pipeline/tests/test_plano_union.py` (CASOS_PUNTO y CASO_GEOMETRIA): si uno cambia,
 * cambia el otro, porque la pantalla y el servidor tienen que ver la misma unión.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  aDic, aHoja, bordesRecorte, cajaDe, colocarAlLado, cuadroEnHoja, dentro, hojaDelCuadro, textoBorraLoMarcado, textoHojasUnidas, escala, esquinasRecorte, geometria, girarRecorte, hojaEn,
  hojasColocadas, invertir, matrizHoja, aplicar, moverEnOrden, moverManilla, pegar, recorteNormal, tamanoGirado, textoGrados,
  transformarPunto,
} from './js/kmz_union.js';

const cerca = (a, b, tol = 1e-9) => assert.ok(Math.abs(a - b) <= tol, `${a} ≠ ${b}`);
const cercaPunto = (p, q, tol = 1e-9) => { cerca(p[0], q[0], tol); cerca(p[1], q[1], tol); };

// --- los casos de Python -----------------------------------------------------------------

const CASOS_PUNTO = [
  [[100, 50, 1001, 801, 1.0, 90.0, 0, 0, 0, 0], [350.0, -400.0]],
  [[2400.0, 130.5, 4961, 3508, 0.75, 0.35, 6120.5, 2210.0, -37, 12], [6104.93683033259, 980.4061942936326]],
  [[10, 3999, 3000, 4000, 1.0, -2.5, 1500, 2000, 0, 0], [99.13463899081216, 4062.5679965335926]],
];

const CASO_GEOMETRIA = {
  hojas: [{ n: 1, rotacion: 90, angulo: 1.5, x: 500.0, y: 400.0, recorte: [10, 20, 790, 980] },
    { n: 2, rotacion: 0, angulo: -0.4, x: 1200.0, y: 420.0, recorte: null }],
  tamanos: { 1: [1000, 800], 2: [900, 850] },
  ppmms: { 1: 5.906, 2: 5.906 },
  origen: [98, -90], ancho: 1556, alto: 981, ppmm: 5.906,
  hoja1: [[[10, 20], [25.185318635645615, 0.46839130830370834]],
    [[789, 979], [778.8146813643544, 979.5316086916963]]],
};

test('transformarPunto da los mismos números que union.transformar_punto', () => {
  for (const [entrada, salida] of CASOS_PUNTO) cercaPunto(transformarPunto(...entrada), salida);
});

test('la matriz de la hoja es la misma transformación que transformarPunto', () => {
  for (const [[px, py, ancho, alto, k, angulo, x, y, ox, oy], salida] of CASOS_PUNTO) {
    const [X, Y] = aplicar(matrizHoja(ancho, alto, k, angulo, x, y), px, py);
    cercaPunto([X - ox, Y - oy], salida);
  }
});

test('geometria da el mismo origen, tamaño, ppmm y puntos que union.geometria', () => {
  const c = CASO_GEOMETRIA;
  const geo = geometria(c.hojas, c.tamanos, c.ppmms);
  assert.deepEqual([geo.origen, geo.ancho, geo.alto, geo.ppmm], [c.origen, c.ancho, c.alto, c.ppmm]);
  const h1 = geo.hojas.find((h) => h.n === 1);
  assert.deepEqual([h1.ancho, h1.alto, h1.k], [800, 1000, 1]);
  for (const [p, q] of c.hoja1) {
    cercaPunto(aplicar(h1.matriz, ...p), q);
    const h = c.hojas[0];
    cercaPunto(transformarPunto(...p, 800, 1000, 1.0, h.angulo, h.x, h.y, ...geo.origen), q);
  }
});

test('geometria acepta tamaños y ppmm en un Map', () => {
  const c = CASO_GEOMETRIA;
  const geo = geometria(c.hojas, new Map([[1, [1000, 800]], [2, [900, 850]]]), new Map([[1, 5.906], [2, 5.906]]));
  assert.deepEqual([geo.origen, geo.ancho, geo.alto], [c.origen, c.ancho, c.alto]);
});

test('una sola hoja sin giro con x, y en su centro da una unión idéntica a la hoja', () => {
  const geo = geometria([{ n: 1, rotacion: 0, angulo: 0, x: 499.5, y: 299.5, recorte: null }], { 1: [1000, 600] }, { 1: 6 });
  assert.deepEqual([geo.origen, geo.ancho, geo.alto], [[0, 0], 1000, 600]);
  cercaPunto(aplicar(geo.hojas[0].matriz, 17, 23), [17, 23]);
});

test('la escala: ppmm casi iguales dan k = 1 exacto; distintos, la razón; el tope es 8 px/mm', () => {
  assert.equal(escala(5.906, 5.906 * (1 + 2e-9)), 1);
  cerca(escala(6, 4), 1.5);
  const colocadas = hojasColocadas([{ n: 1, x: 0, y: 0 }, { n: 2, x: 0, y: 0 }], { 1: [10, 10], 2: [10, 10] }, { 1: 12, 2: 4 });
  assert.deepEqual(colocadas.map((c) => c.k), [8 / 12, 2]);
});

test('el pegado a enteros: el ruido de un giro no suma un píxel', () => {
  assert.equal(pegar(3 + 1e-12), 3);
  assert.equal(pegar(-2 - 5e-8), -2);
  assert.equal(pegar(3.25), 3.25);
});

test('geometria falla como union.py: recorte fuera de la hoja y unión demasiado grande', () => {
  assert.throws(() => geometria([{ n: 1, x: 0, y: 0, recorte: [0, 0, 11, 5] }, { n: 2, x: 0, y: 0 }],
    { 1: [10, 10], 2: [10, 10] }, { 1: 5, 2: 5 }), /recorte se sale/);
  assert.throws(() => geometria([{ n: 1, x: 0, y: 0 }, { n: 2, x: 20000, y: 0 }],
    { 1: [10000, 10000], 2: [10000, 10000] }, { 1: 5, 2: 5 }), /demasiado grande .*recorta las hojas/);
});

// --- inversa, recorte y orden ------------------------------------------------------------

test('la inversa lleva de la unión a la hoja', () => {
  const m = matrizHoja(4961, 3508, 0.75, 0.35, 6120.5, 2210.0);
  cercaPunto(aplicar(invertir(m), ...aplicar(m, 2400, 130.5)), [2400, 130.5]);
  const geo = geometria(CASO_GEOMETRIA.hojas, CASO_GEOMETRIA.tamanos, CASO_GEOMETRIA.ppmms);
  for (const [p, q] of CASO_GEOMETRIA.hoja1) cercaPunto(aHoja(geo.hojas[0].matriz, ...q), p);
});

test('las esquinas del recorte son los centros de sus píxeles extremos', () => {
  assert.deepEqual(esquinasRecorte([10, 20, 790, 980]), [[10, 20], [789, 20], [789, 979], [10, 979]]);
});

test('dentro y hojaEn: la de más arriba bajo el punto, solo dentro de su recorte', () => {
  const hojas = [
    { n: 1, rotacion: 0, angulo: 0, x: 49.5, y: 49.5, recorte: null },            // [0, 100) × [0, 100)
    { n: 2, rotacion: 0, angulo: 0, x: 129.5, y: 49.5, recorte: [20, 0, 100, 100] }, // [100, 180) × [0, 100)
  ];
  const c = hojasColocadas(hojas, { 1: [100, 100], 2: [100, 100] }, { 1: 5, 2: 5 });
  assert.equal(hojaEn(c, 50, 50), 1);
  assert.equal(hojaEn(c, 99.4, 50), 1);       // el recorte de la 2 empieza en su px 20 → 99,5 del mundo
  assert.equal(hojaEn(c, 99.6, 50), 2);
  assert.equal(hojaEn(c, 150, 50), 2);
  assert.equal(hojaEn(c, 185, 50), null);
  assert.equal(hojaEn(c, 50, -1), null);
  assert.ok(dentro(c[0], -0.5, -0.5));
  assert.ok(!dentro(c[0], 99.5, 10));
  // La de arriba manda donde se traslapan.
  const encima = hojasColocadas([hojas[1], hojas[0]].map((h) => ({ ...h, recorte: null })), { 1: [100, 100], 2: [100, 100] }, { 1: 5, 2: 5 });
  assert.equal(hojaEn(encima, 95, 50), 1);
  assert.deepEqual(cajaDe(c), [-0.5, -0.5, 179.5, 99.5]);
  assert.deepEqual(bordesRecorte(c[1])[0], [99.5, -0.5]);
});

test('moverManilla: enteros, dentro de la hoja, sin cruzar la esquina opuesta', () => {
  // La manilla está en el borde del píxel: llevarla a −0,5 es el borde 0.
  assert.deepEqual(moverManilla(null, 0, 9.4, 19.6, 100, 80), [10, 20, 100, 80]);
  assert.deepEqual(moverManilla([10, 20, 90, 70], 2, 49.6, 39.4, 100, 80), [10, 20, 50, 40]);
  assert.deepEqual(moverManilla([10, 20, 90, 70], 1, 500, -30, 100, 80), [10, 0, 100, 70]);
  assert.deepEqual(moverManilla([10, 20, 90, 70], 3, 200, 5, 100, 80, 16), [74, 20, 90, 36]);
  assert.deepEqual(moverManilla([10, 20, 90, 70], 0, -40, 300, 100, 80, 16), [0, 54, 90, 70]);
});

test('recorteNormal: la hoja entera es null', () => {
  assert.equal(recorteNormal([0, 0, 100, 80], 100, 80), null);
  assert.equal(recorteNormal(null, 100, 80), null);
  assert.deepEqual(recorteNormal([0, 0, 99, 80], 100, 80), [0, 0, 99, 80]);
});

test('girar el recorte 90° deja el mismo trozo de papel', () => {
  // Página sin girar de 100 × 60. Con 90° es de 60 × 100.
  const r = [10, 5, 30, 25];
  const g = girarRecorte(r, 0, 90, 100, 60);
  assert.deepEqual(g, [35, 10, 55, 30]);   // (10, 5) → (54, 10) y (29, 24) → (35, 29)
  assert.deepEqual(tamanoGirado(100, 60, 90), [60, 100]);
  assert.deepEqual(girarRecorte(g, 90, 0, 100, 60), r);
  assert.deepEqual(girarRecorte(girarRecorte(r, 0, 180, 100, 60), 180, 270, 100, 60), girarRecorte(r, 0, 270, 100, 60));
  assert.equal(girarRecorte(null, 0, 90, 100, 60), null);
});

test('colocarAlLado: en orden de página, una junto a la otra, sin traslaparse', () => {
  const hojas = colocarAlLado([{ n: 1, ancho: 1000, alto: 800 }, { n: 2, ancho: 900, alto: 850 }, { n: 3, ancho: 1000, alto: 800 }], 90);
  assert.deepEqual(hojas.map((h) => h.n), [1, 2, 3]);
  const c = hojasColocadas(hojas, { 1: [1000, 800], 2: [900, 850], 3: [1000, 800] }, { 1: 5, 2: 5, 3: 5 });
  const cajas = c.map((x) => cajaDe([x]));
  assert.deepEqual(cajas[0], [-0.5, -0.5, 799.5, 999.5]);
  for (let i = 1; i < cajas.length; i += 1) assert.ok(cajas[i][0] > cajas[i - 1][2]);
  assert.ok(cajas.every((k) => k[1] === -0.5));
  assert.ok(hojas.every((h) => h.rotacion === 90 && h.angulo === 0 && h.recorte === null));
});

test('moverEnOrden: subir la deja más encima (más al final), y no se sale de la lista', () => {
  const hojas = [{ n: 1 }, { n: 2 }, { n: 3 }];
  assert.deepEqual(moverEnOrden(hojas, 1, 1).map((h) => h.n), [2, 1, 3]);
  assert.deepEqual(moverEnOrden(hojas, 3, -1).map((h) => h.n), [1, 3, 2]);
  assert.equal(moverEnOrden(hojas, 3, 1), hojas);
  assert.equal(moverEnOrden(hojas, 1, -1), hojas);
});

test('aDic deja la hoja como la guarda entradas.union y textoGrados la escribe en castellano', () => {
  assert.deepEqual(aDic({ n: 2, usar: true, rotacion: 90, angulo: 0.35, x: 1, y: 2 }),
    { n: 2, rotacion: 90, angulo: 0.35, x: 1, y: 2, recorte: null });
  assert.equal(textoGrados(0.35), '0,35°');
  assert.equal(textoGrados(-1.2), '−1,20°');
  assert.equal(textoGrados(-0.001), '0,00°');
});

// --- el cuadro de superficies de la unión ------------------------------------------------

test('hojaDelCuadro: la página sin girar con el giro de la hoja en la unión', () => {
  const paginas = [{ n: 1, ancho: 4000, alto: 3000 }, { n: 2, ancho: 4100, alto: 2900 }, { n: 3, ancho: 10, alto: 10 }];
  const union = { hojas: [{ n: 2, rotacion: 90 }, { n: 1, rotacion: 0 }], cuadro: null };
  assert.deepEqual(hojaDelCuadro(paginas, union, 2), { n: 2, ancho: 4100, alto: 2900, rotacion: 90 });
  assert.deepEqual(hojaDelCuadro(paginas, union, 1), { n: 1, ancho: 4000, alto: 3000, rotacion: 0 });
  // Una página del PDF que no está en la unión, o sin unión: no hay hoja.
  assert.equal(hojaDelCuadro(paginas, union, 3), null);
  assert.equal(hojaDelCuadro(paginas, null, 1), null);
});

test('cuadroEnHoja: enteros y recortado a la hoja, como lo acepta union.leer', () => {
  assert.deepEqual(cuadroEnHoja([10.4, 20.6, 300.5, 400.2], 1000, 800), [10, 21, 301, 400]);
  // Un arrastre que pasa del borde queda en el borde.
  assert.deepEqual(cuadroEnHoja([-50, -3, 1200, 900], 1000, 800), [0, 0, 1000, 800]);
  // Lo que queda dentro es casi nada: no se marca.
  assert.equal(cuadroEnHoja([998, 10, 1300, 200], 1000, 800), null);
  assert.equal(cuadroEnHoja([-200, -200, -10, -10], 1000, 800), null);
});

test('textoHojasUnidas: las hojas en orden de página', () => {
  assert.equal(textoHojasUnidas([{ n: 3 }, { n: 1 }, { n: 2 }]), 'Hojas unidas (1, 2 y 3)');
  assert.equal(textoHojasUnidas([{ n: 2 }, { n: 1 }]), 'Hojas unidas (1 y 2)');
  assert.equal(textoHojasUnidas([]), 'Hojas unidas');
});

test('textoBorraLoMarcado: con la unión dice que era de la unión; entre páginas, lo de siempre', () => {
  const suelta = 'Lo marcado es de otra página. Cambiar de página lo borra. ¿Seguir?';
  assert.equal(textoBorraLoMarcado(1, 2), suelta);
  assert.equal(textoBorraLoMarcado(2, 0), suelta);
  assert.match(textoBorraLoMarcado(0, 0), /^Cambiaste las hojas unidas: .*unión anterior\. ¿Seguir\?$/);
  assert.match(textoBorraLoMarcado(0, 1), /hojas unidas.*quita la unión/);
  assert.doesNotMatch(textoBorraLoMarcado(0, 0), /otra página/);
});
