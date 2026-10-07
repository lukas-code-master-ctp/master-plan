/**
 * Crea tu KMZ: las cuentas de la pantalla (coordenadas, anclas, ajuste, pasos).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  anclaDesde, aPagina, aplicarFuera, aplicarNumero, claveLote, decidirResto, devolverAlKmz, restoDe, conSemillas, esFalloPasajero, formaDelCuadro, mensajeNumerar, numerosQueFaltan, porQueNoSigue, aPantalla, centroide, desrotarPunto, dudosos, empujar, girarEntradas, girarPunto, leerCoordenadas, loteEn,
  herramientaAlEntrar, herramientaTrasRectangulo, HERRAMIENTAS_RECTANGULO, marcarRectangulo, matrizRotacion, metrosDe, nombreDelSistema, detalleUbicacion, distanciaEnPalabras, filaDelPunto, resumenUbicacion, ordenarEsquinas, pasoSugerido, pasosHabilitados, ponerNumero, puedeSeguirANumerar,
  puntoDeRotulo, puntoEnPoligono, rectanguloDe, resumenRevision, rotarPunto, semaforo, sesgoDeEscala, siguienteNombre, sinNumero, sugerencias, verticesDe,
  tamanoRotado, normalizarGiro, puedeUbicar, ubicacionCompleta, textoHuecos, textoSemaforo, vistaAjustada, zoomEn,
  aplicarHomografia, cajaGirada, escalaDeUbicacion, girarEnPantalla, husoDe, leerEscala, lonLatAUtm, lotesEnElMapa, paginaALonLat,
  similitudPorPunto, usaUbicacion, utmALonLat, similitudPorAnclas, afinarAbierta, textoPuntos,
} from './js/kmz_geometria.js';
import { ruta } from './js/comun.js';

const cerca = (a, b, tol = 1e-9) => assert.ok(Math.abs(a - b) <= tol, `${a} ≠ ${b}`);

// --- rotación -------------------------------------------------------------------------

test('girar un punto calza con pipeline/plano/pagina.rotar_punto', () => {
  // Imagen de 100 × 60: los mismos casos que pagina.py.
  assert.deepEqual(rotarPunto(10, 5, 0, 100, 60), [10, 5]);
  assert.deepEqual(rotarPunto(10, 5, 90, 100, 60), [54, 10]);
  assert.deepEqual(rotarPunto(10, 5, 180, 100, 60), [89, 54]);
  assert.deepEqual(rotarPunto(10, 5, 270, 100, 60), [5, 89]);
  assert.deepEqual(tamanoRotado(100, 60, 90), [60, 100]);
  assert.deepEqual(tamanoRotado(100, 60, 180), [100, 60]);
});

test('desrotar deshace rotar en las cuatro rotaciones', () => {
  for (const r of [0, 90, 180, 270]) {
    const [X, Y] = rotarPunto(13.5, 7.25, r, 100, 60);
    assert.deepEqual(desrotarPunto(X, Y, r, 100, 60), [13.5, 7.25]);
  }
  assert.throws(() => rotarPunto(0, 0, 45, 100, 60));
});

test('la matriz del canvas lleva la imagen a la página igual que rotarPunto', () => {
  for (const r of [0, 90, 180, 270]) {
    const [a, b, c, d, e, f] = matrizRotacion(r, 100, 60);
    for (const [x, y] of [[0, 0], [99, 0], [10, 5], [99, 59]]) {
      assert.deepEqual([a * x + c * y + e, b * x + d * y + f], rotarPunto(x, y, r, 100, 60));
    }
  }
});

test('girar la página lleva lo marcado a la nueva rotación', () => {
  const entradas = {
    pagina: 1, rotacion: 0, rectangulo: [10, 5, 50, 30], mascaras: [[0, 0, 4, 4]],
    semillas: [{ numero: '1', x: 20, y: 10 }], anclas: [{ nombre: 'A', x: 30, y: 20, lon: -70, lat: -33 }],
    esquinas: [[0, 0], [99, 0], [99, 59], [0, 59]], cuadricula: { verticales: [{ x: 3 }] }, fuera: [[20, 10]],
  };
  const girada = girarEntradas(entradas, 0, 90, 100, 60);

  assert.equal(girada.rotacion, 90);
  // (10, 5) → (54, 10) y (50, 30) → (29, 50): el rectángulo se normaliza.
  assert.deepEqual(girada.rectangulo, [29, 10, 54, 50]);
  assert.deepEqual(girada.semillas[0], { numero: '1', x: 49, y: 20 });
  assert.deepEqual(girada.fuera, [[49, 20]]);           // lo dejado fuera gira con la página
  assert.deepEqual([girada.anclas[0].x, girada.anclas[0].y, girada.anclas[0].lon], [39, 30, -70]);
  // Las esquinas siguen en orden sup-izq, sup-der, inf-der, inf-izq de la página girada (60 × 100).
  assert.deepEqual(girada.esquinas, [[0, 0], [59, 0], [59, 99], [0, 99]]);
  assert.equal(girada.cuadricula, undefined);

  // Y de vuelta queda igual.
  const vuelta = girarEntradas(girada, 90, 0, 100, 60);
  assert.deepEqual(vuelta.rectangulo, entradas.rectangulo);
  assert.deepEqual(vuelta.semillas, entradas.semillas);
  assert.deepEqual(girarPunto(20, 10, 0, 270, 100, 60), rotarPunto(20, 10, 270, 100, 60));
});

test('girar la página lleva el punto de la coordenada y descuenta el giro', () => {
  // El norte a la izquierda (giro 90): girar la página 90° horario lo deja arriba.
  const entradas = { rotacion: 0, ubicacion: { x: 30, y: 20, lon: -71.5, lat: -34.1, giro: 90, escala_impresa: 5000 } };
  const girada = girarEntradas(entradas, 0, 90, 100, 60);
  assert.deepEqual(girada.ubicacion, { x: 39, y: 30, lon: -71.5, lat: -34.1, giro: 0, escala_impresa: 5000 });
  assert.deepEqual(girarEntradas(girada, 90, 0, 100, 60).ubicacion, entradas.ubicacion);
  // A medio armar (solo la coordenada) se lleva tal cual.
  assert.deepEqual(girarEntradas({ ubicacion: { lon: -71.5, lat: -34.1 } }, 0, 180, 100, 60).ubicacion,
    { lon: -71.5, lat: -34.1 });
  assert.equal(normalizarGiro(-200), 160);
  assert.equal(normalizarGiro(270), -90);
  assert.equal(normalizarGiro(180), 180);
});

test('se puede ubicar con la cuadrícula, 2 puntos o la coordenada con su punto', () => {
  assert.equal(puedeUbicar({ anclas: [{}] }), false);
  assert.equal(puedeUbicar({ anclas: [{}, {}] }), true);
  assert.equal(puedeUbicar({ anclas: [], cuadricula: {} }), true);
  assert.equal(puedeUbicar({ anclas: [], ubicacion: { lon: -71.5, lat: -34.1 } }), false);
  assert.equal(puedeUbicar({ anclas: [], ubicacion: { x: 0, y: 0, lon: -71.5, lat: -34.1 } }), true);
  assert.equal(ubicacionCompleta({ x: 1, y: null, lon: -71.5, lat: -34.1 }), false);
  assert.equal(ubicacionCompleta(null), false);
});

// --- ubicar con un punto: la vista previa ----------------------------------------------
//
// Los números de referencia salen del servidor (pyproj), con `por_punto` de
// pipeline/plano/georreferencia.py: Transformacion.a_utm y a_lonlat de unos puntos.
//   t = por_punto(u, escala, h); t.a_utm(x, y); t.a_lonlat(x, y)

// Caminos de Rapel (parcelas-coipue-lote-8 del QA): el recorte de la página a trabajo, la
// escala del cuadro de superficies y el norte a la izquierda.
const RAPEL = {
  u: { x: 331.5, y: 845.1, lon: -71.54830277777778, lat: -34.17708888888889, giro: 89.3 },
  escala: 0.8298253862191156,
  h: [[1.0159999960572406, 0, -123.94399952095473], [0, 1.0159999960572406, -72.12799972203545], [0, 0, 1]],
  epsg: 32719,
  matriz: [[0.010300185035561377, -0.8430396680943193, 265839.47864415846],
    [-0.8430396680943193, -0.010300185035561377, 6215561.421215], [0, 0, 1]],
  puntos: [
    [[331.5, 845.1], 265130.44033199124, 6215273.248878653, -71.54830277777778, -34.17708888888889],
    [[705.4, 359.1], 265544.0088498699, 6214963.042236679, -71.54390343909354, -34.17997684716372],
    [[2900, 1000], 265026.30951266724, 6213106.305992491, -71.55001943772724, -34.19658890891291],
    [[0, 0], 265839.47864415846, 6215561.421215, -71.54053860573981, -34.17465199646956],
  ],
};
// Chiloé (huso 18), sin homografía y girado al otro lado.
const CHILOE = {
  u: { x: 1000, y: 200, lon: -73.2, lat: -41.5, giro: -30 },
  escala: 0.5,
  epsg: 32718,
  puntos: [
    [[1000, 200], 650236.0471353127, 5404171.784249876, -73.2, -41.499999999999986],
    [[705.4, 359.1], 650148.2565933353, 5404029.241929005, -73.20101580630809, -41.50129976293848],
    [[2900, 1000], 651258.7712689079, 5404300.374088362, -73.18778474585712, -41.49864992541915],
    [[0, 0], 649753.0344334205, 5404008.386790254, -73.20574369732502, -41.50156147969342],
  ],
};

test('la vista previa de Ubicar repite por_punto del servidor', () => {
  for (const caso of [RAPEL, CHILOE]) {
    const t = similitudPorPunto(caso.u, caso.escala, caso.h ?? null);
    assert.equal(t.epsg, caso.epsg);
    for (const [[x, y], e, n, lon, lat] of caso.puntos) {
      const [e1, n1] = aplicarHomografia(t.matriz, x, y);
      // UTM a unos centímetros y lon/lat a ~1 cm (1e-7°): lejos de lo que se ve en el mapa.
      cerca(e1, e, 0.05);
      cerca(n1, n, 0.05);
      const [lon1, lat1] = paginaALonLat(t, x, y);
      cerca(lon1, lon, 1e-7);
      cerca(lat1, lat, 1e-7);
    }
  }
  const t = similitudPorPunto(RAPEL.u, RAPEL.escala, RAPEL.h);
  RAPEL.matriz.forEach((fila, i) => fila.forEach((v, j) => cerca(t.matriz[i][j], v, 0.05)));
  // Sin el punto del plano, o sin escala, no hay vista previa.
  assert.equal(similitudPorPunto({ lon: -71.5, lat: -34.1, giro: 0 }, 0.8), null);
  assert.equal(similitudPorPunto(RAPEL.u, null), null);
});

test('UTM ida y vuelta, y el huso como el servidor', () => {
  assert.equal(husoDe(-71.55, -34.18), 32719);
  assert.equal(husoDe(-73.2, -41.5), 32718);
  assert.equal(husoDe(2.35, 48.85), 32631);
  const [e, n] = lonLatAUtm(-71.5440202, -34.1799429, 32719);
  const [lon, lat] = utmALonLat(e, n, 32719);
  // Las series de Krüger hasta n³: ida y vuelta queda a menos de un milímetro (1e-8°).
  cerca(lon, -71.5440202, 1e-8);
  cerca(lat, -34.1799429, 1e-8);
});

test('la vista previa lleva el ajuste fino y las propiedades de los lotes', () => {
  const t = similitudPorPunto(RAPEL.u, RAPEL.escala, RAPEL.h);
  const rasgos = [{ type: 'Feature', properties: { numero: '8-01', banderas: [] },
    geometry: { type: 'Polygon', coordinates: [[[331.5, 845.1], [340, 845.1], [340, 850], [331.5, 845.1]]] } }];
  const sin = lotesEnElMapa(rasgos, t);
  const con = lotesEnElMapa(rasgos, t, { de: 10, dn: -5 });
  assert.deepEqual(sin.features[0].properties, rasgos[0].properties);
  const [lon0, lat0] = sin.features[0].geometry.coordinates[0][0];
  cerca(lon0, RAPEL.u.lon, 1e-7);
  const [e0, n0] = lonLatAUtm(lon0, lat0, 32719);
  const [e1, n1] = lonLatAUtm(...con.features[0].geometry.coordinates[0][0], 32719);
  cerca(e1 - e0, 10, 1e-3);
  cerca(n1 - n0, -5, 1e-3);
});

test('la escala de la ubicación: la del cuadro, si no la impresa', () => {
  assert.equal(escalaDeUbicacion({ escala_m_px: 0.83, ppmm: 6 }, { escala_impresa: 5000 }), 0.83);
  cerca(escalaDeUbicacion({ escala_m_px: null, ppmm: 6 }, { escala_impresa: 5000 }), 5000 / 1000 / 6);
  assert.equal(escalaDeUbicacion({ escala_m_px: null, ppmm: 6 }, {}), null);
  assert.equal(escalaDeUbicacion({ escala_m_px: null, ppmm: null }, { escala_impresa: 5000 }), null);
  assert.equal(leerEscala('5.000'), 5000);
  assert.equal(leerEscala('1:2500'), 2500);
  assert.equal(leerEscala(' 1 : 10 000 '), 10000);
  assert.equal(leerEscala(''), null);
  assert.ok(Number.isNaN(leerEscala('5')));
  assert.ok(Number.isNaN(leerEscala('5,5')));
  assert.ok(Number.isNaN(leerEscala('1:5.00')));
});

test('el servidor ubica con la coordenada solo sin cuadrícula y sin 2 puntos', () => {
  const u = { x: 1, y: 2, lon: -71.5, lat: -34.1 };
  assert.equal(usaUbicacion({ anclas: [], ubicacion: u }), true);
  assert.equal(usaUbicacion({ anclas: [{}], ubicacion: u }), true);
  assert.equal(usaUbicacion({ anclas: [{}, {}], ubicacion: u }), false);
  assert.equal(usaUbicacion({ anclas: [], cuadricula: {}, ubicacion: u }), false);
  assert.equal(usaUbicacion({ anclas: [], ubicacion: { lon: -71.5, lat: -34.1 } }), false);
});

test('el plano girado en pantalla vuelve a la página', () => {
  const [sx, sy] = girarEnPantalla(110, 50, 90, 100, 50);
  cerca(sx, 100);
  cerca(sy, 60);
  const [x, y] = girarEnPantalla(sx, sy, -90, 100, 50);
  cerca(x, 110);
  cerca(y, 50);
  assert.deepEqual(girarEnPantalla(3, 4, 0, 100, 50), [3, 4]);
  const [w, h] = cajaGirada(100, 60, 90);
  cerca(w, 60);
  cerca(h, 100);
});

// --- afinar con puntos: la vista previa desde el segundo punto -------------------------
//
// Referencias del servidor: `por_anclas(anclas, h)` de pipeline/plano/georreferencia.py,
// con t.matriz, t.a_utm(x, y) y t.a_lonlat(x, y) de unos puntos de la página.

// Los 4 puntos de parcelas-coipue-lote-8 en el QA (recorte: sin homografía).
const ANCLAS_RAPEL = [
  { nombre: 'A', x: 331.5, y: 845.1, lon: -71.5482044, lat: -34.1771027 },
  { nombre: 'B', x: 583.2, y: 832.9, lon: -71.5481615, lat: -34.1790199 },
  { nombre: 'C', x: 705.4, y: 359.1, lon: -71.5440202, lat: -34.1799429 },
  { nombre: 'D', x: 464.0, y: 371.4, lon: -71.5440202, lat: -34.178079 },
];
const POR_ANCLAS = [
  {
    nombre: 'Rapel, 4 puntos',
    anclas: ANCLAS_RAPEL,
    h: null,
    epsg: 32719,
    matriz: [[0.010165534392355477, -0.8190361544500154, 265825.24297401303],
      [-0.8190361544500154, -0.010165534392355477, 6215550.647220799], [0, 0, 1]],
    puntos: [
      [[331.5, 845.1], 265136.4453945384, 6215270.545842484, -71.54823841289004, -34.177114595121324],
      [[2900, 1000], 265035.68686930084, 6213165.276838501, -71.54990175570907, -34.19605971556408],
      [[0, 0], 265825.24297401303, 6215550.647220799, -71.54069583405014, -34.17474587089481],
    ],
  },
  {
    // Con 2 la similitud pasa justo por los dos: A queda en su coordenada.
    nombre: 'Rapel, 2 puntos (A y C)',
    anclas: [ANCLAS_RAPEL[0], ANCLAS_RAPEL[2]],
    h: null,
    epsg: 32719,
    matriz: [[-0.003346997645177568, -0.8124578050544772, 265827.26566422987],
      [-0.8124578050544772, 0.003346997645177568, 6215538.444880181], [0, 0, 1]],
    puntos: [
      [[331.5, 845.1], 265139.54804345896, 6215271.943665516, -71.5482044, -34.177102700000006],
      [[2900, 1000], 265005.1015660044, 6213185.664243168, -71.55022785371447, -34.195869134149774],
      [[0, 0], 265827.26566422987, 6215538.444880181, -71.54067720465869, -34.17485626540894],
    ],
  },
  {
    // Una foto rectificada (perspectiva) en Chiloé: la similitud vale en el plano enderezado.
    nombre: 'Chiloé, 3 puntos con homografía',
    anclas: [{ x: 100, y: 200, lon: -73.2, lat: -41.5 }, { x: 900, y: 250, lon: -73.191, lat: -41.5012 },
      { x: 500, y: 800, lon: -73.1952, lat: -41.5049 }],
    h: [[0.98, 0.03, -40.0], [-0.02, 1.01, 15.0], [0.00002, -0.00001, 1.0]],
    epsg: 32718,
    matriz: [[13.89766687942536, -6.566515113858877, 650199.6020996504],
      [108.01678121587248, -54.96475452988783, 5404355.006486214], [2e-05, -1e-05, 1.0]],
    puntos: [
      [[331.5, 845.1], 650441.7712128364, 5403551.723093821, -73.19738150070138, -41.50554380555408],
      [[2900, 1000], 652610.9932596614, 5403281.409811408, -73.17133365115723, -41.507567149827075],
      [[0, 0], 650199.6020996504, 5404355.006486214, -73.20048212418006, -41.49835728125477],
    ],
  },
];

test('la vista previa con puntos repite por_anclas del servidor', () => {
  for (const caso of POR_ANCLAS) {
    const t = similitudPorAnclas(caso.anclas, caso.h);
    assert.equal(t.epsg, caso.epsg, caso.nombre);
    caso.matriz.forEach((fila, i) => fila.forEach((v, j) => cerca(t.matriz[i][j], v, Math.max(0.05, Math.abs(v) * 1e-9))));
    for (const [[x, y], e, n, lon, lat] of caso.puntos) {
      const [e1, n1] = aplicarHomografia(t.matriz, x, y);
      cerca(e1, e, 0.05);
      cerca(n1, n, 0.05);
      const [lon1, lat1] = paginaALonLat(t, x, y);
      cerca(lon1, lon, 1e-7);
      cerca(lat1, lat, 1e-7);
    }
  }
  // Con uno solo, o con los dos en el mismo lugar del plano, no hay similitud.
  assert.equal(similitudPorAnclas([ANCLAS_RAPEL[0]]), null);
  assert.equal(similitudPorAnclas([ANCLAS_RAPEL[0], { ...ANCLAS_RAPEL[1], x: 331.5, y: 845.1 }]), null);
  assert.equal(similitudPorAnclas([]), null);
  assert.equal(similitudPorAnclas(null), null);
  // Un punto a medias (sin mapa) no cuenta.
  assert.equal(similitudPorAnclas([ANCLAS_RAPEL[0], { nombre: 'B', x: 583.2, y: 832.9 }]), null);
});

test('"Afinar con puntos" se abre sola con puntos, uno a medias o la cuadrícula', () => {
  assert.equal(afinarAbierta({ anclas: [] }), false);
  assert.equal(afinarAbierta({ anclas: [], ubicacion: { x: 1, y: 2, lon: -71, lat: -34 } }), false);
  assert.equal(afinarAbierta({ anclas: [{}] }), true);
  assert.equal(afinarAbierta({ anclas: [], cuadricula: {} }), true);
  assert.equal(afinarAbierta({ anclas: [] }, { pendiente: { nombre: 'A' } }), true);
  assert.equal(afinarAbierta({ anclas: [] }, { rehacer: 'B' }), true);
  assert.equal(afinarAbierta(null), false);
});

test('el estado de los puntos dice qué toca y quién manda', () => {
  assert.match(textoPuntos({ n: 0, coordenada: true }), /^Haz clic en un punto del plano.*ellos mandan sobre tu coordenada\.$/);
  assert.match(textoPuntos({ n: 0 }), /Con 2 puntos ya se ubica el plano\.$/);
  assert.equal(textoPuntos({ n: 1, coordenada: true }), '1 punto. Marca otro: con 2 o más puntos, ellos mandan sobre tu coordenada.');
  assert.equal(textoPuntos({ n: 2, coordenada: true }),
    '2 puntos. Con 2 o más puntos, ellos mandan sobre tu coordenada. Con 4 se nota si alguno quedó mal marcado.');
  assert.equal(textoPuntos({ n: 3 }), '3 puntos. Con 4 se nota si alguno quedó mal marcado.');
  assert.equal(textoPuntos({ n: 4 }), '4 puntos.');
  assert.match(textoPuntos({ n: 2, pendiente: 'C' }), /^Punto C marcado en el plano\. Ahora haz clic en el mismo punto del mapa/);
  assert.match(textoPuntos({ n: 3, rehacer: 'B' }), /^Marca de nuevo el punto B/);
  assert.match(textoPuntos({ n: 0, cuadricula: true }), /comprobar que la cuadrícula calza/);
  assert.match(textoPuntos({ n: 2, cuadricula: true }), /^2 puntos para comprobar la cuadrícula/);
});

test('el cuadro de superficies es un rectángulo solo, que se reemplaza y se quita', () => {
  const vacias = { rectangulo: [100, 100, 300, 300], mascaras: [[0, 0, 4, 4]], cuadro: null };
  assert.deepEqual(HERRAMIENTAS_RECTANGULO, ['dibujo', 'mascara', 'cuadro']);
  // Fuera del dibujo vale igual: no se recorta contra el rectángulo.
  const una = marcarRectangulo(vacias, 'cuadro', [400, 20, 520, 260]);
  assert.deepEqual(una.cuadro, [400, 20, 520, 260]);
  assert.deepEqual([una.rectangulo, una.mascaras], [vacias.rectangulo, vacias.mascaras]);
  // Dibujarlo de nuevo lo reemplaza (no se suman como los tapados).
  const otra = marcarRectangulo(una, 'cuadro', [410, 30, 500, 250]);
  assert.deepEqual(otra.cuadro, [410, 30, 500, 250]);
  assert.equal(marcarRectangulo(otra, 'mascara', [1, 1, 9, 9]).mascaras.length, 2);
  // Un clic (menos de 3 px) no marca nada, y otra herramienta no toca el cuadro.
  assert.equal(marcarRectangulo(otra, 'cuadro', [400, 20, 401, 260]), otra);
  assert.equal(marcarRectangulo(otra, 'numero', [0, 0, 50, 50]), otra);
  assert.deepEqual(marcarRectangulo(otra, 'dibujo', [0, 0, 50, 50]).cuadro, otra.cuadro);
  // Quitarlo es dejarlo en null (lo que hace "Quitar" en la lista).
  assert.equal({ ...otra, cuadro: null }.cuadro, null);
});

test('Marcar se abre en lo que toca: encerrar el dibujo, tapar o mirar', () => {
  const vacias = { rectangulo: null, mascaras: [] };
  const encerrado = { rectangulo: [10, 10, 500, 400], mascaras: [] };
  assert.equal(herramientaAlEntrar(vacias), 'dibujo');
  assert.equal(herramientaAlEntrar(null), 'dibujo');
  // Aunque esté leído: sin dibujo encerrado (lo quitó) lo primero es encerrarlo.
  assert.equal(herramientaAlEntrar(vacias, true), 'dibujo');
  assert.equal(herramientaAlEntrar(encerrado, false), 'mascara');
  // Ya leído, un arrastre para mirar no debe agregar un tapado.
  assert.equal(herramientaAlEntrar(encerrado, true), 'mover');
});

test('tras el primer rectángulo del dibujo se pasa sola a Tapar', () => {
  const vacias = { rectangulo: null, mascaras: [] };
  const primero = marcarRectangulo(vacias, 'dibujo', [10, 10, 500, 400]);
  assert.equal(herramientaTrasRectangulo('dibujo', vacias, primero), 'mascara');
  // Rehacer el rectángulo del dibujo no la cambia: quiso volver a encerrarlo.
  const otro = marcarRectangulo(primero, 'dibujo', [20, 20, 480, 380]);
  assert.equal(herramientaTrasRectangulo('dibujo', primero, otro), 'dibujo');
  // Las demás herramientas se quedan como están.
  const tapado = marcarRectangulo(primero, 'mascara', [30, 30, 60, 60]);
  assert.equal(herramientaTrasRectangulo('mascara', primero, tapado), 'mascara');
  assert.equal(herramientaTrasRectangulo('cuadro', vacias, marcarRectangulo(vacias, 'cuadro', [0, 0, 90, 90])), 'cuadro');
});

test('el cuadro se guarda en px de página aunque la página esté girada', () => {
  // Imagen de 100 × 60 girada 90°: la página mide 60 × 100. Un arrastre en pantalla se
  // pasa a página con la vista (sin rotación de por medio: la vista ya es de la página).
  const vista = { escala: 2, dx: 10, dy: 20 };
  const p = aPagina(vista, 10 + 2 * 5, 20 + 2 * 70);
  const q = aPagina(vista, 10 + 2 * 40, 20 + 2 * 95);
  const entradas = marcarRectangulo({ rotacion: 90, mascaras: [], semillas: [], anclas: [] }, 'cuadro',
    rectanguloDe(q, p));
  assert.deepEqual(entradas.cuadro, [5, 70, 40, 95]);
  // Girar la página lleva el cuadro con lo demás, y de vuelta queda igual.
  const derecha = girarEntradas(entradas, 90, 0, 100, 60);
  assert.deepEqual(derecha.cuadro, [70, 19, 95, 54]);
  assert.deepEqual(girarEntradas(derecha, 0, 90, 100, 60).cuadro, entradas.cuadro);
  assert.deepEqual(girarEntradas(derecha, 0, 270, 100, 60).cuadro, [19, 4, 54, 29]);
});

test('el marco de la foto cambia ancho por alto con un cuarto de vuelta', () => {
  const entradas = { rotacion: 0, mascaras: [], semillas: [], anclas: [], marco_mm: [500, 300] };
  assert.deepEqual(girarEntradas(entradas, 0, 90, 100, 60).marco_mm, [300, 500]);
  assert.deepEqual(girarEntradas(entradas, 0, 270, 100, 60).marco_mm, [300, 500]);
  assert.deepEqual(girarEntradas(entradas, 0, 180, 100, 60).marco_mm, [500, 300]);
  assert.deepEqual(girarEntradas({ ...entradas, marco_mm: null }, 0, 90, 100, 60).marco_mm, null);
});

test('las esquinas se ordenan aunque se marquen en cualquier orden', () => {
  assert.deepEqual(ordenarEsquinas([[200, 90], [5, 100], [190, 3], [0, 0]]),
    [[0, 0], [190, 3], [200, 90], [5, 100]]);
});

// --- vista ---------------------------------------------------------------------------------

test('página ↔ pantalla con zoom y desplazamiento', () => {
  const v = vistaAjustada(1000, 500, 816, 432, 8);   // cabe a lo ancho: escala 0.8
  cerca(v.escala, 0.8);
  assert.deepEqual(aPantalla(v, 0, 0), [8, 16]);
  assert.deepEqual(aPagina(v, ...aPantalla(v, 123, 456)), [123, 456]);

  // Acercar deja quieto el punto bajo el puntero.
  const antes = aPagina(v, 300, 200);
  const z = zoomEn(v, 2, 300, 200);
  cerca(z.escala, 1.6);
  const despues = aPagina(z, 300, 200);
  cerca(despues[0], antes[0]);
  cerca(despues[1], antes[1]);
  // Con tope.
  assert.equal(zoomEn(v, 1000, 0, 0, 0.01, 16).escala, 16);
});

test('un rectángulo arrastrado al revés se normaliza', () => {
  assert.deepEqual(rectanguloDe([50, 40], [10, 60]), [10, 40, 50, 60]);
});

// --- anclas y ajuste -----------------------------------------------------------------------

test('las anclas se nombran A, B, C… sin repetir', () => {
  assert.equal(siguienteNombre([]), 'A');
  assert.equal(siguienteNombre(['A', 'B']), 'C');
  assert.equal(siguienteNombre(['B']), 'A');            // la que se quitó se reusa
  const todas = Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i));
  assert.equal(siguienteNombre(todas), 'AA');
  assert.equal(siguienteNombre([...todas, 'AA']), 'AB');
});

test('el ajuste fino suma de a metros y se queda en decímetros', () => {
  assert.deepEqual(empujar({ de: 0, dn: 0 }, 1, 0), { de: 1, dn: 0 });
  assert.deepEqual(empujar({ de: 0.1, dn: -2 }, 0.2, -5), { de: 0.3, dn: -7 });
  assert.deepEqual(empujar(undefined, -1, 1), { de: -1, dn: 1 });
});

test('un arrastre en el mapa son metros al este y al norte', () => {
  const { de, dn } = metrosDe(-33, 0.0001, 0.0001);
  cerca(dn, 11.132, 1e-3);
  cerca(de, 11.132 * Math.cos((33 * Math.PI) / 180), 1e-3);
});

test('el sistema de la ubicación se nombra en el detalle técnico', () => {
  assert.equal(nombreDelSistema(32719), 'UTM 19S · WGS84');
  assert.equal(nombreDelSistema(24879), 'UTM 19S · PSAD56');
  assert.equal(nombreDelSistema(null), '—');
  assert.equal(detalleUbicacion({ epsg: 32719, parametros: { rms_m: 5.43 }, datum: { datum: 'WGS84' } }),
    'UTM 19S · WGS84 · error medio 5.4 m · datum WGS84');
});

test('la ubicación se resume sin términos técnicos, en metros enteros', () => {
  const g = { metodo: 'anclas', epsg: 32719, parametros: { n_anclas: 4, rms_m: 5.43 }, datum: { datum: 'WGS84' } };
  assert.equal(resumenUbicacion(g), 'Ubicado con 4 puntos · calzan con ±5 m');
  assert.doesNotMatch(resumenUbicacion(g), /UTM|WGS|datum|ancla|error/);
  // Con 2 puntos no hay error medio: no se inventa uno.
  assert.equal(resumenUbicacion({ metodo: 'anclas', parametros: { n_anclas: 2, rms_m: null } }), 'Ubicado con 2 puntos');
  // Sin el conteo del servidor, los marcados; y nunca "±0 m".
  assert.equal(resumenUbicacion({ metodo: 'anclas', parametros: { rms_m: 0.2 } }, 3), 'Ubicado con 3 puntos · calzan con ±1 m');
  assert.equal(resumenUbicacion({ metodo: 'cuadricula', parametros: { rms_m: 1.6 } }),
    'Ubicado con la cuadrícula impresa · calza con ±2 m');
});

test('la distancia de cada punto va en metros enteros', () => {
  assert.equal(distanciaEnPalabras(5.43), '5 m');
  assert.equal(distanciaEnPalabras(12.5), '13 m');
  assert.equal(distanciaEnPalabras(0.4), 'menos de 1 m');
  assert.equal(distanciaEnPalabras(undefined), '—');
  assert.equal(distanciaEnPalabras(Number.NaN), '—');
  assert.equal(distanciaEnPalabras(0), 'menos de 1 m');
});

test('la fila de un punto dice si calza, y con 2 puntos no dice nada', () => {
  const g = { atipicas: ['D'], parametros: { control: 'atipicas' } };
  // "No calza" corto para que quepa en el celular; lo que hay que hacer va aparte.
  assert.deepEqual(filaDelPunto({ nombre: 'D', residuo_m: 7.2 }, g, true),
    { distancia: '7 m', estado: 'No calza', detalle: 'márcalo de nuevo' });
  assert.deepEqual(filaDelPunto({ nombre: 'A', residuo_m: 4.6 }, g, true), { distancia: '5 m', estado: 'Calza', detalle: '' });
  // Desactualizada o sin ubicar con él: nada.
  assert.deepEqual(filaDelPunto({ nombre: 'D', residuo_m: 7.2 }, g, false), { distancia: '—', estado: '', detalle: '' });
  assert.deepEqual(filaDelPunto(undefined, g, true), { distancia: '—', estado: '', detalle: '' });
  // Con 2 puntos la distancia es 0 por construcción: "Calza" contradiría el aviso.
  assert.deepEqual(filaDelPunto({ nombre: 'A', residuo_m: 0 }, { atipicas: [], parametros: { control: 'sin control' } }, true),
    { distancia: '—', estado: '', detalle: '' });
});

test('un error medio que no es número no se muestra', () => {
  assert.equal(resumenUbicacion({ metodo: 'anclas', parametros: { n_anclas: 3, rms_m: Number.NaN } }), 'Ubicado con 3 puntos');
  assert.equal(resumenUbicacion({ metodo: 'cuadricula', parametros: {} }), 'Ubicado con la cuadrícula impresa');
  assert.equal(resumenUbicacion({ metodo: 'punto', parametros: { control: 'sin control', rms_m: null } }),
    'Ubicado con tu coordenada');
  assert.equal(detalleUbicacion({ epsg: 32719, parametros: { rms_m: null } }), 'UTM 19S · WGS84');
});

// --- lotes ------------------------------------------------------------------------------------

const cuadro = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
const lote = (numero, anillos, extra = {}) => ({
  type: 'Feature', geometry: { type: 'Polygon', coordinates: anillos },
  properties: { numero, banderas: [], ...extra },
});

test('un punto en un lote con hueco', () => {
  const anillos = [cuadro(0, 0, 100, 100), cuadro(40, 40, 60, 60)];
  assert.ok(puntoEnPoligono(10, 10, anillos));
  assert.ok(!puntoEnPoligono(50, 50, anillos));
  assert.ok(!puntoEnPoligono(150, 50, anillos));
  assert.deepEqual(centroide(cuadro(0, 0, 10, 20)), [5, 10]);
});

test('el número de un lote va en su semilla o dentro de él', () => {
  assert.deepEqual(puntoDeRotulo(lote('1', [cuadro(0, 0, 10, 10)], { semilla: [2, 3] })), [2, 3]);
  assert.deepEqual(puntoDeRotulo(lote('1', [cuadro(0, 0, 10, 10)])), [5, 5]);
  // Una "L": el centroide cae fuera; el rótulo igual queda dentro.
  const ele = [[[0, 0], [100, 0], [100, 10], [10, 10], [10, 100], [0, 100], [0, 0]]];
  const [x, y] = puntoDeRotulo(lote('2', ele));
  assert.ok(puntoEnPoligono(x, y, ele));
});

test('clic en un lote: se escribe, se corrige, se mueve y se borra su número', () => {
  const a = [cuadro(0, 0, 10, 10)];
  const b = [cuadro(10, 0, 20, 10)];
  let semillas = [];
  semillas = ponerNumero(semillas, ' 12 ', [5, 5], a);
  assert.deepEqual(semillas, [{ numero: '12', x: 5, y: 5 }]);
  // Corregir el mismo lote cambia el número y deja la semilla donde estaba.
  semillas = ponerNumero(semillas, '13', [2, 2], a);
  assert.deepEqual(semillas, [{ numero: '13', x: 5, y: 5 }]);
  // El 13 pasa al lote b: del a se quita (un número va en un solo lote).
  semillas = ponerNumero(semillas, '13', [15, 5], b);
  assert.deepEqual(semillas, [{ numero: '13', x: 15, y: 5 }]);
  // Vacío borra.
  assert.deepEqual(ponerNumero(semillas, '', [15, 5], b), []);
  // Sin lote (antes de digitalizar), se agrega donde se hizo clic.
  assert.deepEqual(ponerNumero([], '7', [1.234, 2.345], null), [{ numero: '7', x: 1.23, y: 2.35 }]);
});

test('el número va tal cual y se compara normalizado', () => {
  assert.equal(claveLote('8-01'), '8-1');
  assert.equal(claveLote('LOTE 8-01'), '8-1');
  assert.equal(claveLote('lote-12'), '12');
  assert.equal(claveLote('A03'), 'A3');
  assert.equal(claveLote('10-6'), '10-6');
  // Igual que `pipeline.plano.numeros.clave`.
  assert.equal(claveLote('LOTE12'), '12');
  assert.equal(claveLote('#12'), '12');
  assert.equal(claveLote('12 .'), '12');
  assert.equal(claveLote('3A'), '3A');
  const a = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]];
  const b = [[[10, 0], [20, 0], [20, 10], [10, 10], [10, 0]]];
  // Escribe "8-01" en a (con el cero: se guarda así) y luego "8-1" en b: es el mismo lote, pasa a b.
  let semillas = ponerNumero([], '8-01', [5, 5], a);
  assert.deepEqual(semillas, [{ numero: '8-01', x: 5, y: 5 }]);
  semillas = ponerNumero(semillas, '8-1', [15, 5], b);
  assert.deepEqual(semillas, [{ numero: '8-1', x: 15, y: 5 }]);
});

test('el lote bajo el clic', () => {
  const rasgos = [lote('1', [cuadro(0, 0, 10, 10)]), lote('2', [cuadro(10, 0, 20, 10)])];
  assert.equal(loteEn(rasgos, 15, 5).properties.numero, '2');
  assert.equal(loteEn(rasgos, 50, 5), null);
});

test('la revisión cuenta por color y marca los sin número y repetidos', () => {
  const rasgos = [
    lote('1', [], { nivel: 'verde' }), lote('2', [], { nivel: 'rojo' }), lote('3', []),
    lote('4', [], { nivel: 'verde', banderas: ['duplicado'] }), lote(null, [], { banderas: ['sin_numero'] }),
    lote(null, [], { banderas: ['sin_numero', 'de_lote'], de_lote: true }),
  ];
  assert.deepEqual(resumenRevision(rasgos),
    { lotes: 4, verde: 2, ambar: 0, rojo: 1, gris: 1, sin_numero: 2, sin_numero_lote: 1, duplicados: 1, fuera: 0 });
});

test('el sesgo de escala: casi todos los lotes hacia el mismo lado y más de 3 %', () => {
  const con = (...errores) => errores.map((e) => ({ properties: { error_area: e } }));
  cerca(sesgoDeEscala(con(0.06, 0.07, 0.05, 0.08, 0.06)), 0.06);
  cerca(sesgoDeEscala(con(-0.05, -0.06, -0.04, -0.07)), -0.055);
  assert.equal(sesgoDeEscala(con(0.02, 0.03, 0.01, 0.025)), null);         // dentro de lo normal
  assert.equal(sesgoDeEscala(con(0.06, -0.06, 0.07, -0.08, 0.05)), null);  // unos y otros: el dibujo
  assert.equal(sesgoDeEscala(con(0.06, 0.07)), null);                      // muy pocos
  assert.equal(sesgoDeEscala([...con(0.06, 0.07, 0.08), { properties: {} }]), 0.07);
});

test('las partes sin número: primero los lotes, y entre ellos los que traen sugerencia', () => {
  const camino = lote(null, [], { banderas: ['sin_numero'] });
  const solo = lote(null, [], { banderas: ['sin_numero', 'de_lote'], de_lote: true });
  const con = lote(null, [], { banderas: ['sin_numero', 'de_lote'], de_lote: true,
    sugerencia: { numero: '8-03', confianza: 0.01, apoyo: 1 } });
  const rasgos = [lote('1', []), camino, solo, con];
  assert.deepEqual(sinNumero(rasgos), [con, solo, camino]);
  assert.deepEqual(sugerencias(rasgos), [{ numero: '8-03', rasgo: con }]);
  assert.deepEqual(sugerencias([lote('1', [])]), []);
});

test('los huecos de la numeración se dicen en una frase', () => {
  assert.equal(textoHuecos([]), '');
  assert.equal(textoHuecos(undefined), '');
  assert.equal(textoHuecos(['8-03']), 'Falta el número 8-03.');
  assert.equal(textoHuecos(['8-03', '8-05', '8-11']), 'Faltan los números 8-03, 8-05 y 8-11.');
});

test('los leídos con poco apoyo se señalan para mirarlos', () => {
  const rasgos = [
    lote('1', [], { origen: 'lector', apoyo: 1, confianza: 0.9 }),
    lote('2', [], { origen: 'lector', apoyo: 8, confianza: 0.9 }),
    lote('3', [], { origen: 'usuario' }),
  ];
  assert.deepEqual(dudosos(rasgos).map((r) => r.properties.numero), ['1']);
});

test('un número puesto se ve al tiro: el lote queda verde y sin su lectura por confirmar', () => {
  const rojo = lote(null, [cuadro(0, 0, 10, 10)], { banderas: ['sin_numero', 'de_lote'], de_lote: true,
    sugerencia: { numero: '8-16', apoyo: 1 } });
  const otro = lote('8-02', [cuadro(10, 0, 20, 10)], { origen: 'lector', apoyo: 5 });
  const rasgos = [rojo, otro];
  const copia = structuredClone(rasgos);
  const nuevos = aplicarNumero(rasgos, '8-16', [5, 5]);

  const p = nuevos[0].properties;
  assert.equal(p.numero, '8-16');
  assert.equal(p.origen, 'usuario');
  assert.deepEqual(p.banderas, []);
  assert.equal(p.sugerencia, undefined);
  assert.deepEqual(nuevos[0].rotulo, [5, 5]);
  assert.equal(nuevos[1], otro);
  assert.deepEqual(sinNumero(nuevos), []);
  assert.deepEqual(sugerencias(nuevos), []);
  // Los rasgos de antes quedan como estaban.
  assert.deepEqual(rasgos, copia);
  // Un clic fuera de todo lote, o un número vacío, no cambia nada.
  assert.equal(aplicarNumero(rasgos, '8-16', [50, 50]), rasgos);
  assert.equal(aplicarNumero(rasgos, ' ', [5, 5]), rasgos);
});

test('un número que estaba en otro lote pasa al nuevo y el otro queda sin número', () => {
  const a = lote('8-1', [cuadro(0, 0, 10, 10)], { origen: 'lector', semilla: [5, 5] });
  const b = lote('8-01', [cuadro(10, 0, 20, 10)], { banderas: ['duplicado'] });
  const c = lote(null, [cuadro(20, 0, 30, 10)], { banderas: ['sin_numero', 'de_lote'], de_lote: true });
  const nuevos = aplicarNumero([a, b, c], '8-01', [25, 5]);
  assert.deepEqual(nuevos.map((r) => r.properties.numero), [null, null, '8-01']);
  assert.deepEqual(nuevos[0].properties.banderas, ['sin_numero', 'de_lote']);
  assert.deepEqual(nuevos[0].rotulo, [5, 5]);
  assert.deepEqual(nuevos[2].properties.banderas, []);
  assert.equal(mensajeNumerar(nuevos), 'Faltan 2 números: haz clic en cada lote rojo y elige su número.');
  // Dos lotes con el mismo número quedan repetidos; al corregir uno, el otro deja de estarlo.
  const d = lote('5', [cuadro(30, 0, 40, 10)]);
  const repetidos = aplicarNumero([d, c], '5', [25, 5]);
  assert.ok(repetidos[0].properties.numero === null);
  const dos = aplicarNumero(aplicarNumero([d, c, lote('6', [cuadro(40, 0, 50, 10)])], '6', [25, 5]), '7', [25, 5]);
  assert.deepEqual(dos.map((r) => r.properties.numero), ['5', '7', null]);
});

test('las semillas que el digitalizado no tiene todavía se ponen encima al recargar', () => {
  const rasgos = [lote(null, [cuadro(0, 0, 10, 10)], { banderas: ['sin_numero', 'de_lote'], de_lote: true }),
    lote('2', [cuadro(10, 0, 20, 10)])];
  const nuevos = conSemillas(rasgos, [{ numero: '1', x: 5, y: 5 }, { numero: '2', x: 15, y: 5 }]);
  assert.deepEqual(nuevos.map((r) => r.properties.numero), ['1', '2']);
  assert.equal(nuevos[1], rasgos[1]);
  assert.equal(conSemillas(rasgos, []), rasgos);
});

test('lo escrito se guarda como lo dice el cuadro de superficies', () => {
  const cuadroSup = ['8-01', '8-08', '8-16'];
  assert.equal(formaDelCuadro('8-8', cuadroSup), '8-08');
  assert.equal(formaDelCuadro(' lote 8-8 ', cuadroSup), '8-08');
  assert.equal(formaDelCuadro('LOTE 8-16', cuadroSup), '8-16');
  // No está en el cuadro (o no hay cuadro): como lo escribió, sin "lote".
  assert.equal(formaDelCuadro('8-17', cuadroSup), '8-17');
  assert.equal(formaDelCuadro('Lote 12', undefined), '12');
  assert.equal(formaDelCuadro('  ', cuadroSup), '');
});

test('los números que faltan según el cuadro', () => {
  const rasgos = [lote('8-1', []), lote(null, [], { banderas: ['sin_numero'] }), lote('8-03', [])];
  assert.deepEqual(numerosQueFaltan(['8-01', '8-02', '8-03', '8-04'], rasgos), ['8-02', '8-04']);
  assert.deepEqual(numerosQueFaltan(undefined, rasgos), []);
});

test('Numerar dice una sola cosa: cuántos números faltan', () => {
  const rojo = (extra = {}) => lote(null, [], { banderas: ['sin_numero', 'de_lote'], de_lote: true, ...extra });
  const camino = lote(null, [], { banderas: ['sin_numero'] });
  const siete = Array.from({ length: 7 }, () => rojo());
  assert.equal(mensajeNumerar([lote('1', []), ...siete]),
    'Faltan 7 números: haz clic en cada lote rojo y elige su número.');
  assert.equal(mensajeNumerar([rojo({ sugerencia: { numero: '8-16' } })]),
    'Falta 1 número: haz clic en cada lote rojo y elige su número.');
  assert.equal(mensajeNumerar([lote('1', [])]), 'Todos los lotes tienen número.');
  assert.equal(mensajeNumerar([lote('1', []), camino]),
    'Todos los lotes tienen número. Queda 1 parte chica sin número: si es un camino o un área común, se deja así.');
  assert.equal(mensajeNumerar([rojo(), camino, camino]),
    'Falta 1 número: haz clic en cada lote rojo y elige su número.'
    + ' Quedan 2 partes chicas sin número: si son caminos o áreas comunes, se dejan así.');
  // Sin lotes rojos pero con un número que no tiene ningún lote.
  assert.equal(mensajeNumerar([lote('1', [])], ['8-04']),
    'Falta el 8-04 en el plano: búscalo; puede que dos lotes hayan quedado juntos.');
  assert.match(mensajeNumerar([lote('1', [])], ['8-04', '8-07']), /^Faltan 8-04 y 8-07 en el plano: búscalos/);
});

test('un error de red o del servidor es pasajero; uno que responde, no', () => {
  assert.ok(esFalloPasajero(new TypeError('Failed to fetch')));
  assert.ok(esFalloPasajero(Object.assign(new Error('x'), { estado: 502 })));
  assert.ok(!esFalloPasajero(Object.assign(new Error('x'), { estado: 409 })));
  assert.ok(!esFalloPasajero(Object.assign(new Error('x'), { estado: 400 })));
});

// --- pasos ------------------------------------------------------------------------------------

test('los pasos se abren según lo que ya hay', () => {
  assert.deepEqual(pasosHabilitados({ pdf: false }),
    { subir: true, marcar: false, digitalizar: false, numerar: false, ubicar: false, revisar: false, crear: false });
  const digitalizado = { pdf: true, entradas: {}, digitalizado: { vigente: true }, georreferencia: null };
  assert.equal(pasosHabilitados(digitalizado).ubicar, true);
  assert.equal(pasosHabilitados(digitalizado).crear, false);
  assert.equal(pasosHabilitados({ ...digitalizado, georreferencia: { vigente: true } }).crear, true);
  assert.equal(pasosHabilitados({ ...digitalizado, georreferencia: { vigente: false } }).revisar, false);
});

test('"Seguir: numerar" pide una digitalización vigente y que no corra otra', () => {
  assert.equal(puedeSeguirANumerar(null), false);
  assert.equal(puedeSeguirANumerar({ pdf: true, entradas: {}, digitalizado: null }), false);
  assert.equal(puedeSeguirANumerar({ digitalizado: { vigente: false } }), false);
  assert.equal(puedeSeguirANumerar({ digitalizado: { vigente: true } }), true);
  assert.equal(puedeSeguirANumerar({ digitalizado: { vigente: true }, trabajo: { id: 'x', terminado: false } }), false);
  assert.equal(puedeSeguirANumerar({ digitalizado: { vigente: true }, trabajo: { id: 'x', terminado: true } }), true);
});

test('al llegar se abre el paso que sigue', () => {
  assert.equal(pasoSugerido({ paso: 'subir' }), 'subir');
  assert.equal(pasoSugerido({ paso: 'digitalizar', digitalizado: null }), 'digitalizar');
  assert.equal(pasoSugerido({ paso: 'digitalizar', digitalizado: { vigente: false } }), 'numerar');
  assert.equal(pasoSugerido({ paso: 'ubicar', digitalizado: { sin_numero: 0, faltantes: ['13'] } }), 'numerar');
  // Una cara sin número puede ser un camino: no obliga a volver a numerar.
  assert.equal(pasoSugerido({ paso: 'ubicar', digitalizado: { sin_numero: 3, faltantes: [] } }), 'ubicar');
  assert.equal(pasoSugerido({ paso: 'crear' }), 'revisar');
  assert.equal(pasoSugerido({ paso: 'listo' }), 'crear');
});

test('el hash lleva a Mis KMZ y a un KMZ, que ya no cuelga de un master', () => {
  assert.deepEqual(ruta('#/kmz'), { pantalla: 'kmzs' });
  assert.deepEqual(ruta('#/kmz/'), { pantalla: 'kmzs' });
  assert.deepEqual(ruta('#/kmz/los-robles'), { pantalla: 'kmz', slug: 'los-robles' });
  assert.deepEqual(ruta('#/planos/los-robles'), { pantalla: 'plano', slug: 'los-robles' });
  // La ruta vieja dentro del master ya no existe: cae en el master.
  assert.deepEqual(ruta('#/planos/los-robles/kmz'), { pantalla: 'plano', slug: 'los-robles' });
});

// --- ir a coordenadas -----------------------------------------------------------------

const enCoordenadas = (texto, lat, lon, tol = 1e-6) => {
  const p = leerCoordenadas(texto);
  assert.ok(p, `no leyó ${texto}`);
  cerca(p.lat, lat, tol);
  cerca(p.lon, lon, tol);
};

test('leerCoordenadas: decimales con coma, espacios o punto y coma', () => {
  enCoordenadas('-34.98, -71.24', -34.98, -71.24);
  enCoordenadas('-34.98,-71.24', -34.98, -71.24);
  enCoordenadas('  -34.98   -71.24 ', -34.98, -71.24);
  enCoordenadas('-34.98; -71.24', -34.98, -71.24);
  enCoordenadas('-34,98 -71,24', -34.98, -71.24);
  enCoordenadas('+10.5, 20', 10.5, 20);
});

test('leerCoordenadas: el ejemplo de Google Earth del usuario', () => {
  enCoordenadas(`34°10'37.50"S 71°32'53.89"W`, -34.177083, -71.548303);
  enCoordenadas(`34°10'37.50"S, 71°32'53.89"W`, -34.177083, -71.548303);
});

test('leerCoordenadas: variantes de símbolos y espacios', () => {
  enCoordenadas('34º10′37.50″S 71º32′53.89″W', -34.177083, -71.548303);
  enCoordenadas('34° 10’ 37.50” S   71° 32’ 53.89” W', -34.177083, -71.548303);
  enCoordenadas(`34°10'37.50''S 71°32'53.89''W`, -34.177083, -71.548303);
  enCoordenadas(`34°10'37,50"S 71°32'53,89"W`, -34.177083, -71.548303);
  enCoordenadas(`34°10'37.50"s 71°32'53.89"w`, -34.177083, -71.548303);
  enCoordenadas(`34 10'37.50"S 71 32'53.89"W`, -34.177083, -71.548303);
});

test('leerCoordenadas: hemisferio adelante, O de oeste y N/E positivos', () => {
  enCoordenadas(`S 34°10'37.5" W 71°32'53.89"`, -34.177083, -71.548303);
  enCoordenadas(`S34°10'37.5" O71°32'53.89"`, -34.177083, -71.548303);
  enCoordenadas(`34°10'37.5"S 71°32'53.89"O`, -34.177083, -71.548303);
  enCoordenadas(`40°26'46"N 79°58'56"E`, 40 + 26 / 60 + 46 / 3600, 79 + 58 / 60 + 56 / 3600);
  enCoordenadas(`-34°10'37.5" -71°32'53.89"`, -34.177083, -71.548303);
});

test('leerCoordenadas: grados y minutos decimales', () => {
  enCoordenadas(`34°10.625'S 71°32.89817'W`, -34.177083, -71.548303);
  enCoordenadas('34.177083°S 71.548303°W', -34.177083, -71.548303);
});

test('leerCoordenadas: las letras deciden cuál es la latitud', () => {
  enCoordenadas(`71°32'53.89"W 34°10'37.50"S`, -34.177083, -71.548303);
  enCoordenadas(`71°32'53.89"W, 34°10'37.50"`, 34.177083, -71.548303);  // sin letra, positiva
  // Sin letras va latitud, longitud; salvo que el primero no pueda ser latitud.
  enCoordenadas('-34.98, -71.24', -34.98, -71.24);
  enCoordenadas('10, 20', 10, 20);
  enCoordenadas('-120.5, -34.98', -34.98, -120.5);
});

test('leerCoordenadas: lo que no entiende o se sale de rango da null', () => {
  for (const malo of [
    '', '   ', 'hola', '-34.98', '-34.98, -71.24, 5', 'S W',
    `34°10'37.50"S 71°32'53.89"S`,          // dos latitudes
    `34°10'37.50"W 71°32'53.89"E`,          // dos longitudes
    `34°60'00"S 71°00'00"W`,                // minutos ≥ 60
    `34°10'60"S 71°00'00"W`,                // segundos ≥ 60
    `34.5°10'S 71°W`,                       // grados con decimales y además minutos
    `34°10.5'30"S 71°W`,                    // minutos con decimales y además segundos
    `34"10'S 71°W`,                         // símbolos en desorden
    '-34°N 71°W',                           // el signo contradice la letra
    '95, 95', '-34, 190', '120, 100',      // fuera de rango
    `91°00'00"S 71°W`, `34°S 181°W`,
    '-34.98 x -71.24',
  ]) assert.equal(leerCoordenadas(malo), null, malo);
  assert.equal(leerCoordenadas(null), null);
  assert.equal(leerCoordenadas(undefined), null);
});

test('anclaDesde: el punto del plano con el lugar escrito, igual que un clic en el mapa', () => {
  const p = leerCoordenadas(`34°10'37.50"S 71°32'53.89"W`);
  const ancla = anclaDesde({ nombre: 'A', x: 120.5, y: 88 }, p.lat, p.lon);
  assert.deepEqual(Object.keys(ancla).sort(), ['lat', 'lon', 'nombre', 'x', 'y']);
  assert.equal(ancla.nombre, 'A');
  assert.equal(ancla.x, 120.5);
  assert.equal(ancla.y, 88);
  assert.equal(ancla.lat, -34.1770833);
  assert.equal(ancla.lon, -71.5483028);
});

test('leerCoordenadas: comas decimales ambiguas y textos largos', () => {
  // "-34,98, -71,24" mezcla coma decimal y coma separadora: no se adivina.
  assert.equal(leerCoordenadas('-34,98, -71,24'), null);
  enCoordenadas('-34,98;-71,24', -34.98, -71.24);
  for (const largo of ['1,1' + ' '.repeat(100000) + 'x', '1'.repeat(100000), `1'`.repeat(50000), '1 '.repeat(50000)]) {
    const t0 = performance.now();
    assert.equal(leerCoordenadas(largo), null);
    assert.ok(performance.now() - t0 < 500, `lento con ${largo.length} caracteres`);
  }
});

test('los vértices para corregir: uno por punto, aunque lo compartan dos lotes', () => {
  const lote = (...puntos) => ({ geometry: { type: 'Polygon', coordinates: [[...puntos, puntos[0]]] } });
  const rasgos = [lote([0, 0], [1, 0], [1, 1], [0, 1]), lote([1, 0], [2, 0], [2, 1], [1, 1])];
  assert.deepEqual(verticesDe(rasgos).map((p) => [p.lon, p.lat]),
    [[0, 0], [1, 0], [1, 1], [0, 1], [2, 0], [2, 1]]);
  assert.deepEqual(verticesDe(null), []);
});

test('bajo un "Seguir" apagado va por qué, en cada paso', () => {
  const pdf = { pdf: true };
  assert.equal(porQueNoSigue('marcar', pdf, { entradas: { rectangulo: null } }), 'Falta encerrar el dibujo del loteo.');
  assert.equal(porQueNoSigue('marcar', { pdf: true, entradas: {} }, {}), '');

  assert.equal(porQueNoSigue('digitalizar', { pdf: true, entradas: {} }), 'Falta leer el plano.');
  assert.equal(porQueNoSigue('digitalizar', { trabajo: { terminado: false }, digitalizado: { vigente: true } }), 'Leyendo el plano…');
  assert.match(porQueNoSigue('digitalizar', { digitalizado: { vigente: false } }), /de nuevo/);
  assert.equal(porQueNoSigue('digitalizar', { digitalizado: { vigente: true } }), '');

  const vigente = { digitalizado: { vigente: true } };
  assert.equal(porQueNoSigue('numerar', vigente), '');
  assert.equal(porQueNoSigue('numerar', vigente, { actualizando: true }), 'Actualizando los lotes…');
  assert.equal(porQueNoSigue('numerar', { digitalizado: { vigente: false } }), 'Actualizando los lotes…');
  assert.equal(porQueNoSigue('numerar', { ...vigente, trabajo: { terminado: false } }), 'Actualizando los lotes…');
  assert.match(porQueNoSigue('numerar', { digitalizado: { vigente: false } }, { releerFallo: true }), /^No se pudieron/);
  // Falló una relectura y después se leyó bien en el paso 3: no queda trabado.
  assert.equal(porQueNoSigue('numerar', vigente, { releerFallo: true }), '');

  assert.equal(porQueNoSigue('ubicar', { ...vigente, georreferencia: { vigente: true } }), '');
  // Recién girado o movido, lo ubicado en el servidor aún no es lo que se ve.
  assert.equal(porQueNoSigue('ubicar', { digitalizado: { vigente: true, escala_m_px: 0.8 }, georreferencia: { vigente: true } },
    { entradas: { anclas: [], ubicacion: { x: 1, y: 2, lon: -71.5, lat: -34.1 } }, ubicando: true }), 'Ubicando el plano…');
  assert.equal(porQueNoSigue('ubicar', vigente, { entradas: { anclas: [{}] } }),
    'Pega tu coordenada y haz clic en ese punto del plano, o marca 2 puntos en "Afinar con puntos".');
  // La coordenada sola, sin el punto del plano, todavía no ubica.
  assert.match(porQueNoSigue('ubicar', vigente, { entradas: { anclas: [], ubicacion: { lon: -71.5, lat: -34.1 } } }),
    /coordenada/);
  const punto = { x: 10, y: 20, lon: -71.5, lat: -34.1, giro: 90 };
  // Con la coordenada y su punto, la escala sale del cuadro…
  assert.equal(porQueNoSigue('ubicar', { digitalizado: { vigente: true, escala_m_px: 0.8 } },
    { entradas: { anclas: [], ubicacion: punto }, ubicando: true }), 'Ubicando el plano…');
  // …o de la escala impresa; sin ninguna de las dos, se pide.
  assert.match(porQueNoSigue('ubicar', { digitalizado: { vigente: true, escala_m_px: null } },
    { entradas: { anclas: [], ubicacion: punto } }), /1:5\.000/);
  assert.equal(porQueNoSigue('ubicar', { digitalizado: { vigente: true, escala_m_px: null } },
    { entradas: { anclas: [], ubicacion: { ...punto, escala_impresa: 5000 } }, ubicando: true }), 'Ubicando el plano…');
  assert.equal(porQueNoSigue('ubicar', vigente, { entradas: { anclas: [{}, {}] }, ubicando: true }), 'Ubicando el plano…');
  assert.match(porQueNoSigue('ubicar', { digitalizado: { vigente: false } }, { entradas: { anclas: [] } }), /Numerar/);

  assert.equal(porQueNoSigue('revisar', vigente, { duplicados: 2 }), 'Hay números repetidos: corrígelos en Numerar.');
  assert.equal(porQueNoSigue('revisar', vigente, { duplicados: 0 }), '');
});

// --- el resto de la propiedad -------------------------------------------------------------

/** Rapel en chico: dos lotes y el resto, una parte sin número enorme que el servidor marca. */
const conResto = (extra = {}) => [
  { ...lote('8-01', [cuadro(0, 0, 10, 10)], { semilla: [5, 5] }), rotulo: [5, 5] },
  { ...lote('8-02', [cuadro(10, 0, 20, 10)], { semilla: [15, 5] }), rotulo: [15, 5] },
  { ...lote(null, [cuadro(0, 10, 200, 100)], { banderas: ['sin_numero', 'de_lote'], de_lote: true, resto: true,
    numero_resto: '8', punto: [100, 50], ...extra }), rotulo: [100, 50] },
];

test('el resto de la propiedad se pregunta aparte y no cuenta como lote sin número que numerar', () => {
  const rasgos = conResto();
  assert.deepEqual(restoDe(rasgos), { rasgo: rasgos[2], estado: 'pendiente', numero: '8', punto: [100, 50] });
  // Sin número en el cuadro, iría como "Resto".
  assert.equal(restoDe(conResto({ numero_resto: null })).numero, 'Resto');
  assert.equal(restoDe(rasgos.slice(0, 2)), null);
  // La tarjeta pregunta por él: ni "Falta 1 número" ni "Ir al siguiente sin número".
  assert.deepEqual(sinNumero(rasgos), []);
  assert.equal(mensajeNumerar(rasgos), 'Todos los lotes tienen número.');
  // El rótulo va en el punto que da el servidor, que cae dentro.
  const { rotulo: _r, ...sinRotulo } = rasgos[2];
  assert.deepEqual(puntoDeRotulo(sinRotulo), [100, 50]);
});

test('dejar fuera el resto: se anota un punto dentro y deja de contar en Revisar', () => {
  const rasgos = conResto();
  const anillos = rasgos[2].geometry.coordinates;
  const entradas = { semillas: [{ numero: '8-01', x: 5, y: 5 }], fuera: [] };

  const fuera = decidirResto(entradas, anillos, [100, 50], false, '8');
  assert.deepEqual(fuera.fuera, [[100, 50]]);
  assert.deepEqual(fuera.semillas, entradas.semillas);          // no cambia cómo se parte: no relee

  const vistos = aplicarFuera(rasgos, [100, 50], true);
  assert.equal(restoDe(vistos).estado, 'fuera');
  assert.deepEqual(vistos[2].properties.banderas, ['sin_numero', 'fuera']);
  const cuenta = resumenRevision(vistos);
  assert.equal(cuenta.sin_numero_lote, 0);
  assert.equal(cuenta.sin_numero, 0);
  assert.equal(cuenta.fuera, 1);
  assert.equal(rasgos[2].properties.fuera, undefined);          // no toca los que recibe
  // Antes de decidir, en Revisar sí cuenta como lote sin número.
  assert.equal(resumenRevision(rasgos).sin_numero_lote, 1);
});

test('incluir el resto pone su número del cuadro, y se puede cambiar de idea', () => {
  const rasgos = conResto();
  const anillos = rasgos[2].geometry.coordinates;
  const fuera = decidirResto({ semillas: [], fuera: [[3, 3]] }, anillos, [100, 50], false);

  const incluido = decidirResto(fuera, anillos, [100, 50], true, '8');
  assert.deepEqual(incluido.semillas, [{ numero: '8', x: 100, y: 50 }]);
  assert.deepEqual(incluido.fuera, [[3, 3]]);                    // solo se quita lo de esta parte
  const vistos = aplicarNumero(aplicarFuera(rasgos, [100, 50], false), '8', [100, 50]);
  assert.equal(restoDe(vistos).estado, 'incluido');
  assert.deepEqual(vistos[2].properties.banderas, []);
  assert.equal(resumenRevision(vistos).sin_numero_lote, 0);

  // Y de vuelta fuera: la semilla queda (no se relee el plano), pero no va al KMZ.
  const otraVez = decidirResto(incluido, anillos, [100, 50], false);
  assert.deepEqual(otraVez.semillas, incluido.semillas);
  assert.deepEqual(otraVez.fuera, [[3, 3], [100, 50]]);
  const sacado = aplicarFuera(vistos, [100, 50], true);
  assert.equal(restoDe(sacado).estado, 'fuera');
  assert.equal(sacado[2].properties.numero, '8');
  assert.deepEqual(resumenRevision(sacado), { ...resumenRevision(rasgos.slice(0, 2)), fuera: 1 });
  // Incluirlo de nuevo, ya con número: solo se quita lo anotado, sin otra semilla.
  assert.deepEqual(decidirResto(otraVez, anillos, [100, 50], true), incluido);
  assert.equal(restoDe(aplicarFuera(sacado, [100, 50], false)).estado, 'incluido');
});

test('el resto que numeró el lector se puede dejar fuera, y vuelve a quedar en rojo sin decidir', () => {
  const leido = conResto({ numero: '8', banderas: [], de_lote: false, origen: 'lector' });
  assert.equal(restoDe(leido).estado, 'incluido');
  const sacado = aplicarFuera(leido, [100, 50], true);
  assert.deepEqual(sacado[2].properties.banderas, ['fuera']);
  // Una parte sin número vuelta atrás es otra vez un lote sin número que decidir.
  const deVuelta = aplicarFuera(aplicarFuera(conResto(), [100, 50], true), [100, 50], false);
  assert.deepEqual(deVuelta[2].properties.banderas, ['sin_numero', 'de_lote']);
  assert.equal(restoDe(deVuelta).estado, 'pendiente');
});

test('numerar a mano una parte dejada fuera la devuelve al KMZ, como la muestra aplicarNumero', () => {
  const rasgos = conResto();
  const anillos = rasgos[2].geometry.coordinates;
  const fuera = decidirResto({ semillas: [], fuera: [[3, 3]] }, anillos, [100, 50], false);
  assert.deepEqual(devolverAlKmz(fuera, anillos).fuera, [[3, 3]]);
  // Lo que se ve al tiro y lo que guardará el servidor dicen lo mismo: incluido.
  assert.equal(restoDe(aplicarNumero(aplicarFuera(rasgos, [100, 50], true), '8', [100, 50])).estado, 'incluido');
  const sinFuera = { semillas: [] };
  assert.equal(devolverAlKmz(sinFuera, anillos), sinFuera);
  assert.equal(devolverAlKmz(fuera, null), fuera);
});

// --- semáforo antes de crear ------------------------------------------------------------

/** Un lote con número y su desvío contra el cuadro (sin `error_area`: no tiene área oficial). */
const conDesvio = (numero, error_area, extra = {}) => ({
  properties: { numero, banderas: [], ...(error_area === undefined ? {} : { error_area }), ...extra },
});

test('semáforo verde: menos de la mitad se aparta más de un 5 %', () => {
  const luz = semaforo([conDesvio('1', 0.01), conDesvio('2', -0.04), conDesvio('3', 0.05), conDesvio('4', 0.09)]);
  assert.deepEqual(luz, { tono: 'verde', dentro: 3, total: 4, sesgo: null });
  assert.equal(textoSemaforo(luz), 'Los lotes calzan con el cuadro de superficies (3 de 4 dentro del 5 %).');
});

test('semáforo ámbar justo en la mitad, y el texto cuenta los que miden distinto', () => {
  const luz = semaforo([conDesvio('1', 0.01), conDesvio('2', -0.02), conDesvio('3', -0.055), conDesvio('4', 0.07)]);
  assert.deepEqual(luz, { tono: 'ambar', dentro: 2, total: 4, sesgo: null });
  assert.match(textoSemaforo(luz), /^2 de 4 lotes miden distinto al cuadro de superficies\. Suele ser la ubicación/);
  // Uno menos fuera del 5 % y vuelve a verde.
  assert.equal(semaforo([conDesvio('1', 0.01), conDesvio('2', -0.02), conDesvio('3', 0.03), conDesvio('4', 0.07)]).tono, 'verde');
});

test('semáforo null sin cuadro de superficies: no se muestra', () => {
  const luz = semaforo([conDesvio('1'), conDesvio('2', null), conDesvio('3')]);
  assert.deepEqual(luz, { tono: null, dentro: 0, total: 0 });
  assert.equal(textoSemaforo(luz), '');
  assert.equal(semaforo([]).tono, null);
  assert.equal(semaforo(undefined).tono, null);
});

test('semáforo cuenta solo lo que va al KMZ: sin las partes sin número ni lo dejado fuera', () => {
  const rasgos = [
    conDesvio('1', 0.01), conDesvio('2', 0.02),
    // Una parte sin número y el resto dejado fuera, aunque traigan desvío, no cuentan.
    { properties: { numero: null, banderas: ['sin_numero'], error_area: 0.4 } },
    conDesvio('8', -0.3, { fuera: true, resto: true, banderas: ['fuera'] }),
    conDesvio('X', 0.2, { banderas: ['sin_numero'] }),
    // El resto incluido con el área de su fila del cuadro sí cuenta, como un lote más.
    conDesvio('Resto', 0.03, { resto: true }),
  ];
  assert.deepEqual(semaforo(rasgos), { tono: 'verde', dentro: 3, total: 3, sesgo: null });
});

test('semáforo usa el nivel del servidor si viene: el redondeo de error_area no lo contradice', () => {
  // 5,004 % se guarda como 0.05, pero Revisar lo pinta rojo (nivel sin redondear).
  const luz = semaforo([conDesvio('1', 0.05, { nivel: 'rojo' }), conDesvio('2', 0.01, { nivel: 'verde' }),
    conDesvio('3', -0.03, { nivel: 'ambar' })]);
  assert.deepEqual(luz, { tono: 'verde', dentro: 2, total: 3, sesgo: null });
  assert.equal(semaforo([conDesvio('1', 0.05, { nivel: 'rojo' }), conDesvio('2', 0.01, { nivel: 'verde' })]).tono, 'ambar');
});

test('semáforo en ámbar si casi todos se desvían parejo, aunque menos de la mitad pase del 5 %', () => {
  // Como Rapel en el QA: todos cerca de un 4,9 % más chicos, solo 2 de 5 pasan del 5 %.
  const luz = semaforo([conDesvio('1', -0.045), conDesvio('2', -0.049), conDesvio('3', -0.048),
    conDesvio('4', -0.052), conDesvio('5', -0.055)]);
  assert.equal(luz.tono, 'ambar');
  assert.equal(luz.dentro, 3);
  assert.equal(textoSemaforo(luz), 'Casi todos los lotes salen cerca de un 4,9 % más chicos que en el cuadro'
    + ' de superficies. Suele ser la ubicación: vuelve a Ubicar y marca los puntos de nuevo.');
});
