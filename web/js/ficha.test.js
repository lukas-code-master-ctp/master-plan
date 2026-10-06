/** Lo que dice la ficha de una parcela y en qué orden ofrece las acciones. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Catalogo } from './datos.js';
import {
  accionesDe, atributosDe, debeCerrarAlArrastrar, escapar,
  formatearPrecio, formatearServidumbre, formatearSuperficie, rotuloConPrecio,
} from './ficha.js';

const ESTADOS = {
  disponible: { etiqueta: 'Disponible', color: '#15803d', vendible: true },
  vendido: { etiqueta: 'Vendido', color: '#2563eb', vendible: false },
};

function catalogoCon(parcela, { whatsapp = '56900000000', diseno = null } = {}) {
  return new Catalogo(
    { proyecto: 'Loteo de Prueba', whatsapp, estados: ESTADOS, parcelas: [parcela] },
    { vistas: [] },
    diseno,
  );
}

const parcela = (cambios = {}) => ({
  id: '7', numero: 7, rotulo: '7', etapa: null, estado: 'disponible',
  superficie_m2: 5100, precio: 8990000, moneda: 'CLP', link_pago: null,
  mejor_vista: 'p01-120', poligono: [[0, 0]], ...cambios,
});

// --- Formatos ------------------------------------------------------------------

test('la superficie va con punto de miles', () => {
  assert.equal(formatearSuperficie(5100), '5.100 m²');
});

test('desde una hectárea la superficie suma las hectáreas, con coma decimal', () => {
  assert.equal(formatearSuperficie(13200), '13.200 m² · 1,32 ha');
});

test('sin superficie no se inventa un guion', () => {
  assert.equal(formatearSuperficie(null), null);
});

test('el precio en pesos va redondeado y con signo', () => {
  assert.equal(formatearPrecio(8990000.4, 'CLP'), '$8.990.000');
});

test('el precio en UF conserva los decimales', () => {
  assert.equal(formatearPrecio(1234.5, 'UF'), 'UF 1.234,5');
});

test('sin precio no hay texto de precio', () => {
  assert.equal(formatearPrecio(null, 'CLP'), null);
});

test('la servidumbre prefiere el ancho en metros', () => {
  assert.equal(formatearServidumbre({ servidumbre_m: 8, servidumbre_m2: 940.5 }), '8 m');
});

test('sin ancho, la servidumbre dice su superficie', () => {
  assert.equal(formatearServidumbre({ servidumbre_m2: 940.53 }), '941 m²');
});

test('sin servidumbre no hay dato', () => {
  assert.equal(formatearServidumbre({}), null);
});

test('escapar deja el texto inofensivo dentro del HTML', () => {
  assert.equal(escapar('<b>"A&B"</b>'), '&lt;b&gt;&quot;A&amp;B&quot;&lt;/b&gt;');
});

// --- Atributos -----------------------------------------------------------------

test('la servidumbre aparece como atributo cuando existe', () => {
  const atributos = atributosDe(parcela({ servidumbre_m2: 515 }));

  assert.deepEqual(atributos.map((a) => [a.rotulo, a.valor]), [['Servidumbre', '515 m²']]);
});

test('sin datos extra no hay atributos, y la fila no se dibuja', () => {
  assert.deepEqual(atributosDe(parcela()), []);
});

// --- Acciones ------------------------------------------------------------------

test('una parcela disponible con link de pago ofrece primero comprar', () => {
  const p = parcela({ link_pago: 'https://pago.example/7' });

  const acciones = accionesDe(p, catalogoCon(p));

  assert.deepEqual(acciones.map((a) => a.tipo), ['pago', 'contacto', 'aire']);
  assert.equal(acciones[0].texto, 'Comprar');
  assert.equal(acciones[0].href, 'https://pago.example/7');
});

test('sin precio, el link de pago es para reservar', () => {
  const p = parcela({ precio: null, link_pago: 'https://pago.example/7' });

  assert.equal(accionesDe(p, catalogoCon(p))[0].texto, 'Reservar');
});

test('los textos de los botones salen del diseño de la loteadora', () => {
  const p = parcela({ link_pago: 'https://pago.example/7' });
  const diseno = { texto_pago: 'Reservar ahora', texto_contacto: 'Hablar con un asesor' };

  const acciones = accionesDe(p, catalogoCon(p, { diseno }));

  assert.equal(acciones[0].texto, 'Reservar ahora');
  assert.equal(acciones[1].texto, 'Hablar con un asesor');
});

test('el WhatsApp lleva el nombre de la parcela y del loteo', () => {
  const p = parcela();

  const contacto = accionesDe(p, catalogoCon(p)).find((a) => a.tipo === 'contacto');

  assert.equal(contacto.href, `https://wa.me/56900000000?text=${encodeURIComponent(
    'Hola, me interesa la parcela 7 de Loteo de Prueba.')}`);
});

test('una parcela vendida no ofrece comprar ni contactar, pero sí verla', () => {
  const p = parcela({ estado: 'vendido', link_pago: 'https://pago.example/7' });

  assert.deepEqual(accionesDe(p, catalogoCon(p)).map((a) => a.tipo), ['aire']);
});

test('sin WhatsApp del proyecto no hay botón de contacto', () => {
  const p = parcela();

  assert.deepEqual(accionesDe(p, catalogoCon(p, { whatsapp: null })).map((a) => a.tipo), ['aire']);
});

test('una parcela que no se ve desde el aire no ofrece verla en 360°', () => {
  const p = parcela({ mejor_vista: null });

  assert.deepEqual(accionesDe(p, catalogoCon(p)).map((a) => a.tipo), ['contacto']);
});

// --- Arrastre del panel ----------------------------------------------------------

test('arrastrar el panel más de un tercio hacia abajo lo cierra', () => {
  assert.equal(debeCerrarAlArrastrar(140, 400, 0.1), true);
});

test('un arrastre corto y lento devuelve el panel a su lugar', () => {
  assert.equal(debeCerrarAlArrastrar(60, 400, 0.1), false);
});

test('un tirón rápido hacia abajo lo cierra aunque sea corto', () => {
  assert.equal(debeCerrarAlArrastrar(40, 400, 0.9), true);
});

test('un temblor del dedo no cierra el panel por rápido que sea', () => {
  assert.equal(debeCerrarAlArrastrar(8, 400, 2), false);
});

// --- Pastilla de la parcela elegida ---------------------------------------------

test('la pastilla de la parcela elegida suma el precio al número', () => {
  assert.equal(rotuloConPrecio(parcela({ precio: 24990000 }), '14'), '14 · $24.990.000');
});

test('sin precio la pastilla elegida dice solo el número', () => {
  assert.equal(rotuloConPrecio(parcela({ precio: null }), '14'), '14');
});
