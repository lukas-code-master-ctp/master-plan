/** El geo de un loteo: dónde se descarga y cuándo tiene link fijo. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { geoDelLoteo } from './js/inventario.js';

test('sin construir no hay geo', () => {
  assert.equal(geoDelLoteo({ slug: 'praderas', construido: false }), null);
});

test('construido sin publicar se descarga, pero todavía no tiene link fijo', () => {
  const geo = geoDelLoteo({ slug: 'praderas', construido: true, publicado: false, url: 'https://praderas.tumasterplan.cl' });

  assert.equal(geo.descarga, '/api/proyectos/praderas/geo.pdf');
  assert.equal(geo.link, null);
});

test('publicado, el link fijo es el geo dentro del sitio', () => {
  const geo = geoDelLoteo({ slug: 'praderas', construido: true, publicado: true, url: 'https://praderas.tumasterplan.cl/' });

  assert.equal(geo.link, 'https://praderas.tumasterplan.cl/geo.pdf');
});
