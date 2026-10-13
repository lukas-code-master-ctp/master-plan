import { test } from 'node:test';
import assert from 'node:assert/strict';

import { equipoConInvitaciones, fichasDe, inicialesDe, ordenarEquipo, tonoDe } from './js/equipo.js';

test('las iniciales salen del nombre y, sin nombre, del correo', () => {
  assert.equal(inicialesDe({ nombre: 'Pía Soto Rivas', email: 'pia@x.cl' }), 'PS');
  assert.equal(inicialesDe({ nombre: '  rosa ', email: 'rosa@x.cl' }), 'R');
  assert.equal(inicialesDe({ nombre: '', email: 'tomas@x.cl' }), 'T');
});

test('cada correo tiene siempre el mismo tono, entre 0 y 359', () => {
  const tono = tonoDe('pia@bosques.cl');
  assert.equal(tonoDe('pia@bosques.cl'), tono);
  assert.ok(tono >= 0 && tono < 360);
  assert.notEqual(tonoDe('tomas@bosques.cl'), tono);
});

test('las fichas dicen el rol, si eres tú y si falta entrar o está desactivada', () => {
  const textos = (m) => fichasDe(m).map((f) => f.texto);
  assert.deepEqual(textos({ rol: 'dueño', yo: true, activo: true, pendiente: false }), ['Dueño', 'Tú']);
  assert.deepEqual(textos({ rol: 'equipo', yo: false, activo: true, pendiente: true }), ['Equipo', 'Sin entrar todavía']);
  // Desactivada manda sobre "sin entrar": ya no va a entrar.
  assert.deepEqual(textos({ rol: 'equipo', yo: false, activo: false, pendiente: true }), ['Equipo', 'Desactivada']);
});

test('el equipo se ordena: tú, los activos por nombre y al final los desactivados', () => {
  const equipo = [
    { nombre: 'Zoe', email: 'z@x.cl', activo: true, yo: false },
    { nombre: 'Ana', email: 'a@x.cl', activo: false, yo: false },
    { nombre: 'Pía', email: 'p@x.cl', activo: true, yo: true },
    { nombre: 'Bruno', email: 'b@x.cl', activo: true, yo: false },
  ];
  assert.deepEqual(ordenarEquipo(equipo).map((m) => m.nombre), ['Pía', 'Bruno', 'Zoe', 'Ana']);
  assert.equal(equipo[0].nombre, 'Zoe', 'no reordena la lista original');
});

test('una invitación sin aceptar no tiene rol: dice si está enviada o vencida', () => {
  const textos = (m) => fichasDe(m).map((f) => f.texto);
  assert.deepEqual(textos({ invitacion: true, vencida: false }), ['Invitación enviada']);
  assert.deepEqual(textos({ invitacion: true, vencida: true }), ['Invitación vencida']);
});

test('las invitaciones van después de los activos y antes de los desactivados', () => {
  const lista = equipoConInvitaciones({
    equipo: [
      { id: 1, nombre: 'Pía', email: 'p@x.cl', activo: true, yo: true },
      { id: 2, nombre: 'Ana', email: 'a@x.cl', activo: false, yo: false },
      { id: 3, nombre: 'Zoe', email: 'z@x.cl', activo: true, yo: false },
    ],
    invitaciones: [{ id: 1, nombre: 'Bruno', email: 'b@x.cl', vencida: false }],
  });
  assert.deepEqual(ordenarEquipo(lista).map((m) => m.nombre), ['Pía', 'Zoe', 'Bruno', 'Ana']);
  assert.equal(lista.find((m) => m.nombre === 'Bruno').invitacion, true);
});

test('sin invitaciones en la respuesta queda solo el equipo', () => {
  assert.equal(equipoConInvitaciones({ equipo: [{ id: 1 }] }).length, 1);
});
