import { test } from 'node:test';
import assert from 'node:assert/strict';

import { horas } from './js/comun.js';

test('las horas de apartado se leen en singular o plural', () => {
  assert.equal(horas(1), '1 hora');
  assert.equal(horas(2), '2 horas');
  assert.equal(horas(48), '48 horas');
});
