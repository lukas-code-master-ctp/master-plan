/** La sección Contactos: los mensajes del formulario de la landing, para el equipo de CTP. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { agrupar, enlaceWhatsapp, pedido } from './js/contactos.js';

const contacto = (id, estado, cambios = {}) => ({
  id, estado, nombre: 'Marta Soto', email: 'marta@loteos.cl', telefono: '56987654321',
  loteadora: 'Loteos del Sur', plan: 'pro', vuelo: false, parcelas: null, mensaje: '',
  creado_en: '2026-10-09T15:00:00+00:00', atendido_en: null, ...cambios,
});

test('primero los nuevos, el más reciente arriba; después los atendidos', () => {
  const grupos = agrupar([
    contacto(1, 'nuevo', { creado_en: '2026-10-08T10:00:00+00:00' }),
    contacto(2, 'atendido'),
    contacto(3, 'nuevo', { creado_en: '2026-10-09T10:00:00+00:00' }),
  ]);

  assert.deepEqual(grupos.nuevos.map((c) => c.id), [3, 1]);
  assert.deepEqual(grupos.atendidos.map((c) => c.id), [2]);
});

test('de los atendidos se muestran los 50 más recientes', () => {
  const viejos = Array.from({ length: 60 }, (_, i) =>
    contacto(i, 'atendido', { creado_en: new Date(Date.UTC(2026, 8, 1, i)).toISOString() }));

  const { atendidos } = agrupar(viejos);

  assert.equal(atendidos.length, 50);
  assert.equal(atendidos[0].id, 59);
});

test('lo que pidió, en una línea', () => {
  assert.equal(pedido(contacto(1, 'nuevo', { plan: 'master', parcelas: 120, vuelo: true })),
    'Plan Master · 120 parcelas · necesita que lo volemos');
  assert.equal(pedido(contacto(1, 'nuevo', { plan: 'no-se' })), 'Aún no sabe qué plan');
});

test('el WhatsApp lleva su nombre; sin teléfono no hay enlace', () => {
  assert.match(enlaceWhatsapp(contacto(1, 'nuevo')), /^https:\/\/wa\.me\/56987654321\?text=Hola%20Marta/);
  assert.equal(enlaceWhatsapp(contacto(1, 'nuevo', { telefono: '' })), null);
});
