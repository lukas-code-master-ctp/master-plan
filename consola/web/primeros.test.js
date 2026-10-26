/** Primeros pasos: qué se marca solo y cuándo deja de mostrarse. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { pasosDe } from './js/primeros.js';

const hechos = (pasos) => Object.fromEntries(pasos.map((p) => [p.clave, p.hecho]));

test('una cuenta recién creada tiene los cuatro pasos por hacer', () => {
  const pasos = pasosDe({});

  assert.deepEqual(pasos.map((p) => p.clave), ['whatsapp', 'marca', 'master', 'publicar']);
  assert.deepEqual(hechos(pasos), { whatsapp: false, marca: false, master: false, publicar: false });
  assert.equal(pasos[2].accion.href, '#/planos/nuevo');
});

test('se marcan con lo que ya hay en la cuenta', () => {
  const pasos = pasosDe({
    preferencias: { whatsapp: '56912345678' },
    disenos: [{ id: 1 }],
    proyectos: [{ slug: 'mi-loteo', construido: true, habilitado: false, publicado: false }],
  });

  assert.deepEqual(hechos(pasos), { whatsapp: true, marca: true, master: true, publicar: false });
  assert.equal(pasos[3].accion.href, '#/planos/mi-loteo');
});

test('un master empezado y sin construir lleva a seguirlo, no a crear otro', () => {
  const pasos = pasosDe({ proyectos: [{ slug: 'a medias', construido: false }] });

  assert.equal(pasos[2].accion.texto, 'Seguir con el master');
  assert.equal(pasos[2].accion.href, '#/planos/a%20medias');
  assert.equal(pasos[3].accion, null);
});

test('ya pedida la habilitación, el último paso dice que se espera el correo', () => {
  const pasos = pasosDe({
    proyectos: [{ slug: 'x', construido: true, habilitado: false, habilitacion_pedida: '2026-10-13T15:00:00Z' }],
  });

  assert.match(pasos[3].texto, /Ya pediste tu plan/);
  assert.equal(pasos[3].accion, null);
});

test('con algo publicado, o para el equipo de CTP, no se muestran', () => {
  assert.equal(pasosDe({ proyectos: [{ slug: 'x', publicado: true }] }), null);
  assert.equal(pasosDe({ plataforma: true }), null);
});

test('habilitado y sin publicar, el último paso dice que ya se puede', () => {
  const pasos = pasosDe({ proyectos: [{ slug: 'x', construido: true, habilitado: true, publicado: false }] });

  assert.match(pasos[3].texto, /Ya está habilitado/);
  assert.equal(pasos[3].accion.href, '#/planos/x');
});
