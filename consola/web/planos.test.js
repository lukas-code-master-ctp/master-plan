/** Mis planos: el resumen de arriba, las barras de cada loteo y cómo se reparten las tarjetas. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { formaDeTarjeta, ordenarParaLista, resumenDe, segmentos } from './js/planos.js';

const construido = (por_estado) => ({
  construido: true,
  resumen: { parcelas: Object.values(por_estado).reduce((a, b) => a + b, 0), por_estado },
});

test('el resumen suma las parcelas de los loteos construidos y deja fuera los que no', () => {
  const proyectos = [
    construido({ disponible: 148, reservado: 48, vendido: 347, no_disponible: 36 }),
    construido({ disponible: 21, reservado: 6, vendido: 42, no_disponible: 19 }),
    { construido: false, resumen: {} },
  ];

  assert.deepEqual(resumenDe(proyectos), {
    masters: 2,
    parcelas: 667,
    por_estado: { disponible: 169, reservado: 54, vendido: 389, no_disponible: 55 },
  });
});

test('sin loteos construidos no hay resumen que mostrar', () => {
  assert.equal(resumenDe([{ construido: false, resumen: {} }]), null);
});

test('la barra va en el orden del rubro y omite los estados sin parcelas', () => {
  const barra = segmentos({ vendido: 30, disponible: 50, no_disponible: 20, reservado: 0 }, 100);

  assert.deepEqual(barra.map((s) => [s.estado, s.porcentaje]),
    [['disponible', 50], ['vendido', 30], ['no_disponible', 20]]);
});

test('"no en venta" cuenta junto a "no disponible" en la barra', () => {
  const barra = segmentos({ disponible: 6, no_disponible: 2, no_en_venta: 2 }, 10);

  assert.deepEqual(barra.map((s) => [s.estado, s.porcentaje]), [['disponible', 60], ['no_disponible', 40]]);
});

test('con tres o más loteos el primero va destacado y los dos siguientes a su lado', () => {
  assert.deepEqual([0, 1, 2, 3, 4].map((i) => formaDeTarjeta(i, 5)),
    ['destacada', 'lateral', 'lateral', 'tercio', 'tercio']);
});

test('uno solo ocupa todo el ancho y dos van mitad y mitad', () => {
  assert.equal(formaDeTarjeta(0, 1), 'ancha');
  assert.deepEqual([0, 1].map((i) => formaDeTarjeta(i, 2)), ['mitad', 'mitad']);
});

test('lo publicado va primero y lo que falta construir al final, sin desordenar cada grupo', () => {
  const lista = [
    { slug: 'vacio' }, { slug: 'b', construido: true }, { slug: 'a', publicado: true, construido: true },
    { slug: 'c', construido: true }, { slug: 'd', publicado: true, construido: true },
  ];

  assert.deepEqual(ordenarParaLista(lista).map((p) => p.slug), ['a', 'd', 'b', 'c', 'vacio']);
});
