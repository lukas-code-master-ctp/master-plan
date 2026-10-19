/** Cómo se nombran los puntos de vuelo en el plano y en los controles. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Catalogo, conteoPorEstado, romano, textoReferencia } from './datos.js';

const vista = (id, posicion, altura_m) => ({ id, posicion, altura_m, lat: -35, lon: -72 });

function catalogoCon(vistas) {
  return new Catalogo({ parcelas: [], estados: {} }, { vistas, inicial: vistas[0]?.id });
}

test('los puntos se numeran en romanos, como en el vuelo', () => {
  assert.deepEqual([1, 2, 3, 4, 8].map(romano), ['I', 'II', 'III', 'IV', 'VIII']);
});

test('un punto fuera de la tabla de romanos conserva su número', () => {
  assert.equal(romano(12), '12');
});

test('un punto volado a una sola altura dice esa altura', () => {
  const catalogo = catalogoCon([vista('p01-210', 1, 210)]);

  assert.equal(catalogo.nombrePunto(1), 'Punto I');
  assert.equal(catalogo.alturasDePunto(1), '210 m');
});

test('un punto volado a varias alturas dice el rango, de la más baja a la más alta', () => {
  const catalogo = catalogoCon([vista('p02-120', 2, 120), vista('p02-40', 2, 40), vista('p02-80', 2, 80)]);

  assert.equal(catalogo.alturasDePunto(2), '40–120 m');
});

test('las alturas de otro punto no se mezclan', () => {
  const catalogo = catalogoCon([vista('p01-120', 1, 120), vista('p04-230', 4, 230)]);

  assert.equal(catalogo.alturasDePunto(4), '230 m');
});

test('un punto sin vistas no inventa altura', () => {
  assert.equal(catalogoCon([vista('p01-120', 1, 120)]).alturasDePunto(9), '');
});

test('el conteo por estado cuenta todas las parcelas de cada estado', () => {
  const parcelas = ['disponible', 'vendido', 'disponible', 'reservado', 'disponible'].map(
    (estado, i) => ({ id: String(i), estado }));

  assert.deepEqual(conteoPorEstado(parcelas),
                   new Map([['disponible', 3], ['vendido', 1], ['reservado', 1]]));
});

test('los caminos de una vista llegan con su overlay, y un sitio viejo no trae ninguno', async () => {
  const catalogo = catalogoCon([vista('p01-500', 1, 500), vista('p02-500', 2, 500)]);
  const camino = [[[10, -40], [12, -40], [12, -42]]];
  const respuestas = {
    'datos/vistas/p01-500.json': { parcelas: [], caminos: [camino] },
    'datos/vistas/p02-500.json': { parcelas: [] },
  };
  const original = globalThis.fetch;
  globalThis.fetch = async (ruta) => ({ ok: true, json: async () => respuestas[ruta] });
  try {
    await catalogo.overlayDe('p01-500');
    await catalogo.overlayDe('p02-500');
  } finally {
    globalThis.fetch = original;
  }

  assert.deepEqual(catalogo.caminosDe('p01-500'), [camino]);
  assert.deepEqual(catalogo.caminosDe('p02-500'), []);
});

test('los otros puntos de vuelo llegan con el overlay, y un sitio viejo no trae ninguno', async () => {
  const catalogo = catalogoCon([vista('p01-500', 1, 500), vista('p03-500', 3, 500)]);
  const punto = { posicion: 3, az: 120.5, el: -14.2, distancia_m: 640 };
  const respuestas = {
    'datos/vistas/p01-500.json': { parcelas: [], puntos: [punto] },
    'datos/vistas/p03-500.json': { parcelas: [] },
  };
  const original = globalThis.fetch;
  globalThis.fetch = async (ruta) => ({ ok: true, json: async () => respuestas[ruta] });
  try {
    await catalogo.overlayDe('p01-500');
    await catalogo.overlayDe('p03-500');
  } finally {
    globalThis.fetch = original;
  }

  assert.deepEqual(catalogo.puntosDe('p01-500'), [punto]);
  assert.deepEqual(catalogo.puntosDe('p03-500'), []);
});

test('un hito con tiempo de viaje dice el tiempo; sin él, los kilómetros', () => {
  assert.equal(textoReferencia({ nombre: 'Quillón', distancia_km: 6.4, tiempo: '10 min' }), 'QUILLÓN · 10 MIN');
  assert.equal(textoReferencia({ nombre: 'Cauquenes', distancia_km: 12.4 }), 'CAUQUENES · 12 KM');
});

test('los esteros de una vista llegan con su overlay, y un sitio viejo no trae ninguno', async () => {
  const catalogo = catalogoCon([vista('p01-500', 1, 500), vista('p02-500', 2, 500)]);
  const estero = { nombre: 'Estero', tramos: [[[10, -40], [12, -41]]] };
  const respuestas = {
    'datos/vistas/p01-500.json': { parcelas: [], aguas: [estero] },
    'datos/vistas/p02-500.json': { parcelas: [] },
  };
  const original = globalThis.fetch;
  globalThis.fetch = async (ruta) => ({ ok: true, json: async () => respuestas[ruta] });
  try {
    await catalogo.overlayDe('p01-500');
    await catalogo.overlayDe('p02-500');
  } finally {
    globalThis.fetch = original;
  }

  assert.deepEqual(catalogo.aguasDe('p01-500'), [estero]);
  assert.deepEqual(catalogo.aguasDe('p02-500'), []);
});
