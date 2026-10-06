/** Lo que dice la ficha de una parcela y en qué orden ofrece las acciones. */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { Catalogo } from './datos.js';
import {
  accionesDe, atributosDe, debeCerrarAlArrastrar, escapar, formatearPrecio, kmlDeParcela,
  rotuloConPrecio,
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

test('el precio en pesos va redondeado y con signo', () => {
  assert.equal(formatearPrecio(8990000.4, 'CLP'), '$8.990.000');
});

test('el precio en UF conserva los decimales', () => {
  assert.equal(formatearPrecio(1234.5, 'UF'), 'UF 1.234,5');
});

test('sin precio no hay texto de precio', () => {
  assert.equal(formatearPrecio(null, 'CLP'), null);
});

test('escapar deja el texto inofensivo dentro del HTML', () => {
  assert.equal(escapar('<b>"A&B"</b>'), '&lt;b&gt;&quot;A&amp;B&quot;&lt;/b&gt;');
});

// --- Tarjetas de la ficha --------------------------------------------------------

const tarjetas = (p) => atributosDe(p).map(({ rotulo, valor, detalle }) => [rotulo, valor, detalle]);

test('la superficie va con punto de miles y sus hectáreas con coma decimal', () => {
  assert.deepEqual(tarjetas(parcela({ superficie_m2: 5120 })), [['Superficie', '5.120 m²', '0,51 hectáreas']]);
});

test('la servidumbre con superficie y ancho dice las dos cosas', () => {
  assert.deepEqual(tarjetas(parcela({ servidumbre_m2: 240.4, servidumbre_m: 8 }))[1],
                   ['Servidumbre', '240 m²', 'Camino de 8 m de ancho']);
});

test('la servidumbre con solo el ancho lo dice como valor', () => {
  assert.deepEqual(tarjetas(parcela({ servidumbre_m: 8 }))[1], ['Servidumbre', '8 m de ancho', null]);
});

test('la servidumbre con solo la superficie no inventa un ancho', () => {
  assert.deepEqual(tarjetas(parcela({ servidumbre_m2: 515 }))[1], ['Servidumbre', '515 m²', null]);
});

test('sin superficie ni servidumbre no hay tarjetas, y la cuadrícula no se dibuja', () => {
  assert.deepEqual(atributosDe(parcela({ superficie_m2: null })), []);
});

// --- Acciones ------------------------------------------------------------------

test('una parcela en venta ofrece primero WhatsApp, después reservar o comprar, y verla en 360°', () => {
  const p = parcela({ link_pago: 'https://pago.example/7' });

  const acciones = accionesDe(p, catalogoCon(p));

  assert.deepEqual(acciones.map((a) => a.tipo), ['contacto', 'pago', 'aire']);
  assert.equal(acciones[1].texto, 'Comprar');
  assert.equal(acciones[1].href, 'https://pago.example/7');
});

test('el WhatsApp dice Consultar por WhatsApp y lleva el nombre de la parcela y del loteo', () => {
  const p = parcela();

  const contacto = accionesDe(p, catalogoCon(p)).find((a) => a.tipo === 'contacto');

  assert.equal(contacto.texto, 'Consultar por WhatsApp');
  assert.equal(contacto.href, `https://wa.me/56900000000?text=${encodeURIComponent(
    'Hola, me interesa la parcela 7 de Loteo de Prueba.')}`);
});

test('sin precio, el link de pago es para reservar', () => {
  const p = parcela({ precio: null, link_pago: 'https://pago.example/7' });

  assert.equal(accionesDe(p, catalogoCon(p)).find((a) => a.tipo === 'pago').texto, 'Reservar parcela');
});

test('los textos de los botones salen del diseño de la loteadora', () => {
  const p = parcela({ link_pago: 'https://pago.example/7' });
  const diseno = { texto_pago: 'Reservar ahora', texto_contacto: 'Hablar con un asesor' };

  const acciones = accionesDe(p, catalogoCon(p, { diseno }));

  assert.equal(acciones[0].texto, 'Hablar con un asesor');
  assert.equal(acciones[1].texto, 'Reservar ahora');
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

// --- Deslindes en KML --------------------------------------------------------------

test('los deslindes salen como un polígono KML cerrado, en longitud,latitud', () => {
  const p = parcela({ poligono: [[-72.1, -35.1], [-72.09, -35.1], [-72.09, -35.09]] });

  const kml = kmlDeParcela(p, 'Parcela 7', 'Loteo de Prueba');

  assert.match(kml, /^<\?xml version="1.0" encoding="UTF-8"\?>/);
  assert.match(kml, /<name>Parcela 7 · Loteo de Prueba<\/name>/);
  // El anillo se cierra repitiendo el primer vértice, como pide KML.
  assert.match(kml, /<coordinates>-72.1,-35.1,0 -72.09,-35.1,0 -72.09,-35.09,0 -72.1,-35.1,0<\/coordinates>/);
});

test('los nombres van escapados dentro del KML', () => {
  const kml = kmlDeParcela(parcela({ poligono: [[0, 0], [1, 0], [1, 1]] }), 'Parcela <7>', 'A & B');

  assert.match(kml, /<name>Parcela &lt;7&gt; · A &amp; B<\/name>/);
});

test('una parcela sin polígono no tiene KML', () => {
  assert.equal(kmlDeParcela(parcela({ poligono: null }), 'Parcela 7', 'Loteo'), null);
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
