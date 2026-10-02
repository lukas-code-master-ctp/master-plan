/**
 * Que el guion y la página se sigan hablando, y que lo que decide sin DOM
 * decida bien.
 *
 * La app no tiene framework: los módulos buscan nodos por id y por
 * `data-accion`, y si alguien renombra uno en el HTML no falla nada al cargar
 * —`$('#loque-sea')` devuelve null— sino después, cuando alguien hace clic.
 * Las primeras pruebas convierten ese silencio en un error de la suite.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

import { dinero, iniciales, ruta } from './js/comun.js';
import { avance } from './js/vuelo.js';
import { cuantosLotes, descargaDe, pasoEnPalabras, terminados, textoDeUso } from './js/kmzs.js';

const aqui = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(aqui, 'index.html'), 'utf8');
const modulos = readdirSync(join(aqui, 'js')).filter((f) => f.endsWith('.js'));
const guion = modulos.map((f) => readFileSync(join(aqui, 'js', f), 'utf8')).join('\n');
const servidor = readFileSync(join(aqui, '..', 'app.py'), 'utf8');

const conjunto = (texto, patron, grupo = 1) =>
  new Set([...texto.matchAll(patron)].map((c) => c[grupo]));

test('cada id que busca el guion existe en la página', () => {
  const enLaPagina = conjunto(html, /\bid="([^"]+)"/g);
  const queBusca = conjunto(guion, /\$\$?\(['`]#([\w-]+)['`\s]/g);

  const huerfanos = [...queBusca].filter((id) => !enLaPagina.has(id));

  assert.deepEqual(huerfanos, [],
    `el guion busca ids que no están en index.html: ${huerfanos.join(', ')}`);
});

test('cada acción que despacha el guion existe como botón', () => {
  const enLaPagina = conjunto(html, /data-accion="([\w-]+)"/g);
  // `manejar()` compara contra literales: esos son los nombres que hay que tener.
  const queDespacha = conjunto(guion, /accion === '([\w-]+)'/g);

  const huerfanas = [...queDespacha].filter((a) => !enLaPagina.has(a));

  assert.deepEqual(huerfanas, [],
    `el guion despacha acciones sin botón: ${huerfanas.join(', ')}`);
});

test('todo botón de la página tiene quién lo atienda', () => {
  const enLaPagina = conjunto(html, /data-accion="([\w-]+)"/g);
  const queDespacha = conjunto(guion, /accion === '([\w-]+)'/g);

  const sinAtender = [...enLaPagina].filter((a) => !queDespacha.has(a));

  assert.deepEqual(sinAtender, [],
    `hay botones que no hacen nada al tocarlos: ${sinAtender.join(', ')}`);
});

test('el servidor sirve todos los módulos, y solo esos', () => {
  // El servidor los sirve de una lista cerrada: un módulo nuevo que no esté en
  // ella da 404 y la página queda en blanco sin decir por qué.
  const lista = servidor.match(/MODULOS = \(([^)]*)\)/s)[1];
  const servidos = conjunto(lista, /"([\w.-]+\.js)"/g);

  assert.deepEqual([...servidos].sort(), [...modulos].sort());
});

test('cada módulo que se importa existe', () => {
  const importados = conjunto(guion, /from '\.\/([\w.-]+\.js)'/g);
  // Los que la consola toma prestados del visor se sirven desde web/js.
  const delVisor = conjunto(servidor.match(/MODULOS_DEL_VISOR = \(([^)]*)\)/s)[1], /"([\w.-]+\.js)"/g);
  const visor = readdirSync(join(aqui, '..', '..', 'web', 'js'));

  const faltan = [...importados].filter((m) => !modulos.includes(m)
    && !(delVisor.has(m) && visor.includes(m)));

  assert.deepEqual(faltan, []);
});

// --- lo que no necesita la página ------------------------------------------------

test('el hash elige la pantalla', () => {
  assert.deepEqual(ruta(''), { pantalla: 'planos' });
  assert.deepEqual(ruta('#/planos'), { pantalla: 'planos' });
  assert.deepEqual(ruta('#/planos/nuevo'), { pantalla: 'nuevo' });
  assert.deepEqual(ruta('#/planos/praderas-de-cauquenes'),
    { pantalla: 'plano', slug: 'praderas-de-cauquenes' });
  assert.deepEqual(ruta('#/disenos'), { pantalla: 'disenos' });
  assert.deepEqual(ruta('#/kmz'), { pantalla: 'kmzs' });
  assert.deepEqual(ruta('#/kmz/los-robles'), { pantalla: 'kmz', slug: 'los-robles' });
  assert.deepEqual(ruta('#/cualquier-cosa'), { pantalla: 'planos' });
});

test('Nuevo master puede llegar con un KMZ de Mis KMZ ya elegido', () => {
  assert.deepEqual(ruta('#/planos/nuevo?kmz=los-robles'), { pantalla: 'nuevo', kmz: 'los-robles' });
  assert.deepEqual(ruta('#/planos/nuevo?kmz='), { pantalla: 'nuevo' });
  assert.deepEqual(ruta('#/planos/nuevo?otra=1'), { pantalla: 'nuevo' });
});

test('la navegación tiene la pestaña Mis KMZ, entre Mis planos y Mis diseños', () => {
  const pestanas = [...html.matchAll(/<a href="#\/(\w+)" data-seccion="(\w+)">/g)].map((c) => c[2]);
  assert.deepEqual(pestanas, ['planos', 'kmz', 'disenos']);
});

test('Nuevo KMZ va a la derecha de Nuevo master en Mis planos', () => {
  const planos = html.slice(html.indexOf('id="pantalla-planos"'), html.indexOf('id="planos"'));
  assert.ok(planos.indexOf('Nuevo master') < planos.indexOf('id="planos-nuevo-kmz"'));
});

test('ya no queda el flujo del KMZ dentro del master', () => {
  for (const viejo of ['plano-kmz', 'nuevo-desde-plano', 'nuevo-plano-nota', 'kmz-al-master', '/plano/']) {
    assert.ok(!html.includes(viejo), `index.html todavía tiene ${viejo}`);
  }
  for (const viejo of ['}/plano/', 'proyecto.plano', '/kmz`;', 'desdePlano', 'alCrearDesdePlano']) {
    assert.ok(!guion.includes(viejo), `el guion todavía tiene ${viejo}`);
  }
});

// --- Mis KMZ ----------------------------------------------------------------------

test('el paso de un KMZ se dice en palabras', () => {
  assert.equal(pasoEnPalabras({ paso: 'subir' }), 'Falta subir el plano');
  assert.equal(pasoEnPalabras({ paso: 'marcar' }), 'Falta marcar el dibujo');
  assert.equal(pasoEnPalabras({ paso: 'digitalizar' }), 'Falta digitalizar');
  assert.equal(pasoEnPalabras({ paso: 'ubicar' }), 'Falta ubicarlo en el mapa');
  assert.equal(pasoEnPalabras({ paso: 'crear' }), 'Falta crear el KMZ');
  assert.equal(pasoEnPalabras({ paso: 'listo' }), 'KMZ creado');
  // Digitalizando gana sobre el paso; algo raro cae en el primero.
  assert.equal(pasoEnPalabras({ paso: 'digitalizar', trabajo: { id: 'x' } }), 'Digitalizando…');
  assert.equal(pasoEnPalabras({ paso: 'otro' }), 'Falta subir el plano');
  assert.equal(pasoEnPalabras(null), 'Falta subir el plano');
});

test('para usar en un master se ofrecen solo los KMZ terminados', () => {
  const lista = [
    { slug: 'a', terminado: true, paso: 'listo' },
    { slug: 'b', terminado: false, paso: 'ubicar' },
    // Subió otro PDF: el paso volvió atrás, pero el KMZ de antes sigue sirviendo.
    { slug: 'c', terminado: true, paso: 'marcar' },
  ];
  assert.deepEqual(terminados(lista).map((k) => k.slug), ['a', 'c']);
  assert.deepEqual(terminados([]), []);
  assert.deepEqual(terminados(undefined), []);
});

test('los lotes van en singular o plural, y nada si no se digitalizó', () => {
  assert.equal(cuantosLotes(1), '1 lote');
  assert.equal(cuantosLotes(12), '12 lotes');
  assert.equal(cuantosLotes(0), '0 lotes');
  assert.equal(cuantosLotes(null), null);
});

test('al usar un KMZ se dice en qué master quedó y qué pasó con el anterior', () => {
  assert.equal(textoDeUso({ lotes: 12, anteriores: [] }, 'Los Robles'),
    'Listo: Los Robles ya tiene el KMZ (12 lotes). Ahora sube las panorámicas si faltan y construye.');
  assert.match(textoDeUso({ lotes: 1, anteriores: ['subdivision.kmz.anterior'] }, 'X'),
    /\(1 lote\)\. El anterior quedó como subdivision\.kmz\.anterior\./);
  assert.equal(descargaDe('los robles'), '/api/kmz/los%20robles/descargar');
});

test('las iniciales del avatar salen del correo', () => {
  assert.equal(iniciales('ana.perez@losrobles.cl'), 'AP');
  assert.equal(iniciales('e.ruiz@compratuparcela.cl'), 'ER');
  assert.equal(iniciales('luis@delvalle.cl'), 'L');
  assert.equal(iniciales(''), '?');
});

test('el precio se escribe como en el visor', () => {
  assert.equal(dinero(9990000, 'CLP'), '$9.990.000');
  assert.equal(dinero(1250, 'UF'), 'UF 1.250');
  assert.equal(dinero(null, 'CLP'), null);
});


// --- El vuelo: en qué paso va un trabajo ------------------------------------------

const CONSTRUIR = [
  'Proyecto: Praderas de Cauquenes', 'Leyendo el KMZ...', '  88 parcelas con nombre',
  'Leyendo la planilla...', '  88 parcelas con datos comerciales', 'Leyendo las panorámicas...',
  'Resolviendo el rumbo de cada panorámica con la posición del sol...',
  'Cargando el modelo de terreno...', 'Calibrando la pose de cada vista contra la foto...',
  'Proyectando parcelas sobre cada vista...',
];

test('el paso sale de la última línea conocida del pipeline', () => {
  const progreso = avance(CONSTRUIR, 'construir');
  assert.equal(progreso.titulo, 'Dibujando las parcelas');
  assert.equal(progreso.paso, 7);
  assert.equal(progreso.total, 9);
  assert.ok(progreso.fraccion > 0.6 && progreso.fraccion < 0.8);
});

test('sin líneas reconocibles todavía, va en el primer paso', () => {
  assert.equal(avance(['Proyecto: X'], 'construir').paso, 1);
  assert.equal(avance([], 'publicar').titulo, 'Preparando el sitio');
});

test('terminado bien dice el resultado y llena la barra', () => {
  const progreso = avance([...CONSTRUIR, '', 'Listo. 88 parcelas (88 con geometría) en 3 vistas.'],
    'construir', true);
  assert.equal(progreso.fraccion, 1);
  assert.equal(progreso.resumen, 'Listo: 88 parcelas en 3 vistas');
});

test('publicado dice dónde quedó', () => {
  const progreso = avance(['Visor copiado en /datos/x', '▶ Publicando /datos/x como m',
    '▶ URL publicada: https://masterplan-x.vercel.app'], 'publicar', true);
  assert.equal(progreso.resumen, 'En línea: https://masterplan-x.vercel.app');
});

test('si falla, la causa es la línea del error y no el traceback', () => {
  const progreso = avance(['Leyendo la planilla...', 'Traceback (most recent call last):',
    '  File "x.py", line 3', 'ValueError: inventario.xlsx repite 20 parcela(s): 3-1'],
  'construir', true, true);
  assert.equal(progreso.causa, 'inventario.xlsx repite 20 parcela(s): 3-1');
  assert.ok(progreso.fraccion < 1);
});

test('una sola vista va en singular', () => {
  assert.equal(avance(['Listo. 88 parcelas (88 con geometría) en 1 vistas.'], 'construir', true).resumen,
    'Listo: 88 parcelas en 1 vista');
});

test('digitalizar el plano tiene sus propios pasos, no los de construir', () => {
  const lineas = ['Página 1 de 1: 6596×9600 px, 150 dpi', 'Rótulos: texto típico de 24 px; 96 pasadas',
    'Imagen de trabajo: 5000×7000 px a 7.87 px/mm', 'Semillas: 3 de la loteadora y 62 del lector'];
  const progreso = avance(lineas, 'digitalizar-plano');
  assert.equal(progreso.titulo, 'Separando los lotes');
  assert.equal(progreso.total, 5);
  assert.equal(avance([...lineas, 'Lotes: 65 de 65', 'Listo: /datos/x/plano/digitalizado.json'],
    'digitalizar-plano', true).resumen, 'Plano digitalizado: 65 lotes');
});
