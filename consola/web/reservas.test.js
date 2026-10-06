/** La sección Reservas: cómo se ordenan las solicitudes y qué dice cada una. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { agrupar, enlaceWhatsapp, textoDelPlazo } from './js/reservas.js';

const AHORA = new Date('2026-10-06T15:40:00Z');
const solicitud = (id, estado, cambios = {}) => ({
  id, estado, parcela: '1-7', loteo: 'Praderas', nombre: 'Pedro', telefono: '56987654321',
  email: 'p@c.cl', creada_en: '2026-10-06T15:00:00+00:00', vence_en: '2026-10-06T17:00:00+00:00',
  ...cambios,
});

test('primero lo que hay que confirmar, la que vence antes arriba', () => {
  const grupos = agrupar([
    solicitud(1, 'pendiente', { vence_en: '2026-10-06T17:00:00+00:00' }),
    solicitud(2, 'confirmada'),
    solicitud(3, 'pendiente', { vence_en: '2026-10-06T16:00:00+00:00' }),
    solicitud(4, 'vencida'),
    solicitud(5, 'liberada'),
  ]);

  assert.deepEqual(grupos.porConfirmar.map((s) => s.id), [3, 1]);
  assert.deepEqual(grupos.confirmadas.map((s) => s.id), [2]);
  assert.deepEqual(grupos.anteriores.map((s) => s.id).sort(), [4, 5]);
});

test('de las anteriores se muestran las 20 más recientes', () => {
  const viejas = Array.from({ length: 25 }, (_, i) =>
    solicitud(i, 'liberada', { creada_en: new Date(Date.UTC(2026, 9, 1, i)).toISOString() }));

  const { anteriores } = agrupar(viejas);

  assert.equal(anteriores.length, 20);
  assert.equal(anteriores[0].id, 24);
});

test('una pendiente dice hasta qué hora queda apartada y cuánto falta', () => {
  assert.match(textoDelPlazo(solicitud(1, 'pendiente'), AHORA), /Apartada hasta las \d{2}:\d{2} · quedan 1 h 20 min/);
});

test('con menos de una hora, faltan solo minutos', () => {
  const pronto = solicitud(1, 'pendiente', { vence_en: '2026-10-06T16:05:00+00:00' });

  assert.match(textoDelPlazo(pronto, AHORA), /quedan 25 min$/);
});

test('las demás dicen en qué quedaron', () => {
  assert.equal(textoDelPlazo(solicitud(1, 'confirmada'), AHORA), 'Pago confirmado: sigue apartada');
  assert.equal(textoDelPlazo(solicitud(1, 'vencida'), AHORA), 'Venció sin confirmar: volvió a estar disponible');
  assert.equal(textoDelPlazo(solicitud(1, 'liberada'), AHORA), 'Liberada: volvió a estar disponible');
});

test('el WhatsApp al comprador nombra la parcela y el loteo', () => {
  assert.equal(enlaceWhatsapp(solicitud(1, 'pendiente')),
               `https://wa.me/56987654321?text=${encodeURIComponent(
                 'Hola Pedro, te escribo por tu reserva de la parcela 1-7 en Praderas.')}`);
});
