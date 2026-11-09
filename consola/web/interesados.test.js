/** La sección Interesados: filtros, contacto y la planilla para Excel. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
  detalleDeContacto, enlaceWhatsapp, filtrar, loteosDe, planilla, responsables, telefonoLegible,
} from './js/interesados.js';

const interesado = (id, cambios = {}) => ({
  id, slug: 'praderas', loteo: 'Praderas', parcela: '1-7', nombre: 'Camila Soto', telefono: '56981234567',
  email: '', horario: 'manana', estado: 'nuevo', responsable: '', nota: '',
  creado_en: '2026-11-09T13:00:00+00:00', ...cambios,
});

test('filtra por loteo y por estado, el más reciente arriba', () => {
  const lista = [
    interesado(1, { creado_en: '2026-11-01T10:00:00+00:00' }),
    interesado(2, { slug: 'lomas', loteo: 'Lomas' }),
    interesado(3, { estado: 'contactado', creado_en: '2026-11-08T10:00:00+00:00' }),
  ];

  assert.deepEqual(filtrar(lista).map((i) => i.id), [2, 3, 1]);
  assert.deepEqual(filtrar(lista, { loteo: 'praderas' }).map((i) => i.id), [3, 1]);
  assert.deepEqual(filtrar(lista, { estado: 'nuevo' }).map((i) => i.id), [2, 1]);
});

test('los loteos cuentan solo los nuevos', () => {
  const loteos = loteosDe([interesado(1), interesado(2, { estado: 'reservo' }), interesado(3, { slug: 'lomas', loteo: 'Lomas' })]);
  assert.deepEqual(loteos, [{ slug: 'praderas', nombre: 'Praderas', nuevos: 1 },
                            { slug: 'lomas', nombre: 'Lomas', nuevos: 1 }]);
});

test('un celular chileno se lee con espacios; otro número va tal cual', () => {
  assert.equal(telefonoLegible('56981234567'), '+56 9 8123 4567');
  assert.equal(telefonoLegible('5422334455'), '+5422334455');
  assert.equal(detalleDeContacto(interesado(1)), '+56 9 8123 4567 · prefiere en la mañana');
  assert.equal(detalleDeContacto(interesado(1, { horario: '' })), '+56 9 8123 4567');
});

test('el WhatsApp va al número del interesado y nombra la parcela', () => {
  const enlace = enlaceWhatsapp(interesado(1));
  assert.ok(enlace.startsWith('https://wa.me/56981234567?text='));
  assert.match(decodeURIComponent(enlace), /Hola Camila, .*parcela 1-7 de Praderas/);
});

test('los responsables sugeridos no se repiten', () => {
  assert.deepEqual(responsables([interesado(1, { responsable: 'María' }), interesado(2, { responsable: 'Eduardo' }),
                                 interesado(3, { responsable: 'María' }), interesado(4)]), ['Eduardo', 'María']);
});

test('la planilla se abre en Excel: BOM, punto y coma y comillas donde hace falta', () => {
  const texto = planilla([interesado(1, { nota: 'Llamar; el "sábado"', estado: 'visita' })]);
  const [cabecera, fila] = texto.slice(1).split('\r\n');

  assert.ok(texto.startsWith('﻿'));
  assert.equal(cabecera, 'Fecha;Loteo;Parcela;Nombre;Teléfono;Correo;Horario;Estado;Responsable;Nota');
  assert.match(fila, /;Praderas;1-7;Camila Soto;\+56981234567;;en la mañana;Visita agendada;;"Llamar; el ""sábado"""$/);
});
