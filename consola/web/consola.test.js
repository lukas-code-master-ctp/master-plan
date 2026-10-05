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

test('cada herramienta del plano tiene su botón y su cursor', async () => {
  const { HERRAMIENTAS_RECTANGULO } = await import('./js/kmz_geometria.js');
  const css = readFileSync(join(aqui, 'consola.css'), 'utf8');
  const botones = conjunto(html, /data-herramienta="([\w-]+)"/g);

  for (const h of HERRAMIENTAS_RECTANGULO) assert.ok(botones.has(h), `falta el botón de la herramienta ${h}`);
  const sinCursor = [...botones].filter((h) => h !== 'mover' && !css.includes(`[data-herramienta="${h}"] canvas`));
  assert.deepEqual(sinCursor, [], `herramientas sin cursor de mira: ${sinCursor.join(', ')}`);
});

test('cada "Quitar" de lo marcado tiene quién lo atienda', () => {
  const kmz = readFileSync(join(aqui, 'js', 'kmz.js'), 'utf8');
  // Los botones de la lista llevan `{ quitarAlgo: ... }` en su dataset.
  const quitar = conjunto(kmz, /\{ (quitar[A-Z]\w*):/g);
  const kebab = (c) => c.replace(/[A-Z]/g, (l) => `-${l.toLowerCase()}`);

  assert.ok(quitar.has('quitarCuadro'));
  for (const clave of quitar) {
    assert.ok(kmz.includes(`[data-${kebab(clave)}]`), `el clic no escucha data-${kebab(clave)}`);
    assert.ok(kmz.includes(`dataset.${clave}`), `nadie atiende dataset.${clave}`);
  }
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
  // En el orden real: "Semillas" sale después del lector y antes de la imagen de trabajo.
  const lineas = ['Página 1 de 1: 6596×9600 px, 150 dpi', 'Rótulos: texto típico de 24 px; 96 pasadas',
    'Semillas: 3 de la loteadora y 62 del lector', 'Imagen de trabajo: 5000×7000 px a 7.87 px/mm',
    'Regiones: 70 núcleos, 65 semillas, 2 bolsillos unidos a su lote'];
  const progreso = avance(lineas, 'digitalizar-plano');
  assert.equal(progreso.titulo, 'Separando los lotes');
  assert.equal(progreso.total, 5);
  assert.equal(avance([...lineas, 'Lotes: 65 de 65', 'Listo: /datos/x/plano/digitalizado.json'],
    'digitalizar-plano', true).resumen, 'Plano digitalizado: 65 lotes');
});

// Las líneas de un plano real (Algarrobo, con lector), en el orden en que salen.
const DIGITALIZAR = [
  'Página 1 de 1: 5008×7038 px, 5.91 px/mm (imagen embebida), rotación 0°',
  'Rótulos: texto típico de 15 px; 96 pasadas de Tesseract en 2 hebras',
  'Rótulos: 2 de 96 pasadas (3 s)',
  'Rótulos: 32 de 96 pasadas (40 s)',
  'Rótulos: 64 de 96 pasadas (81 s)',
  'Rótulos: 96 de 96 pasadas (118 s)',
  'Rótulos: 71 números leídos (64 con apoyo ≥ 2)',
  'Cuadrícula: 8 de 16 pasadas (2 s)',
  'Cuadrícula: 16 de 16 pasadas (4 s)',
  'Cuadrícula: 40 marcas leídas, 6 líneas confiables (4 s)',
  'Cuadro de superficies: 65 áreas oficiales (6 s)',
  'Semillas: 3 de la loteadora y 62 del lector (apoyo ≥ 2)',
  'Imagen de trabajo: 4100×5900 px a 5.91 px/mm (rectangulo)',
  'Tinta: 1830442 px de línea, 3 tramos de pliegue borrados',
  'Regiones: 70 núcleos, 65 semillas, 2 bolsillos unidos a su lote',
  'Red de deslindes: 412 aristas (380 rectas), 290 nodos',
  'Lotes: 65 de 65',
  'Listo: /datos/kmz/x/plano/digitalizado.json',
];

test('digitalizar avanza dentro del paso de lectura con las pasadas del lector', () => {
  const avances = DIGITALIZAR.map((_, i) => avance(DIGITALIZAR.slice(0, i + 1), 'digitalizar-plano'));
  // El paso y la barra nunca retroceden, y cada pasada nueva mueve la barra.
  for (let i = 1; i < avances.length; i++) {
    assert.ok(avances[i].paso >= avances[i - 1].paso, `el paso retrocede en "${DIGITALIZAR[i]}"`);
    assert.ok(avances[i].fraccion >= avances[i - 1].fraccion, `la barra retrocede en "${DIGITALIZAR[i]}"`);
  }
  assert.deepEqual(avances.map((a) => a.paso), [1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 3, 4, 5, 5, 5]);
  for (const i of [2, 3, 4, 5, 7]) assert.ok(avances[i].fraccion > avances[i - 1].fraccion);
  // A media lectura, la barra va a media lectura: (1 + 0,85 × 32/96) / 5.
  assert.equal(avances[3].titulo, 'Leyendo los números de lote');
  assert.ok(Math.abs(avances[3].fraccion - (1 + 0.85 * 32 / 96) / 5) < 1e-9);
  // Con todas las pasadas el paso no se da por terminado: falta la línea del siguiente.
  assert.ok(avances[11].dentro < 1 && avances[11].fraccion < 2 / 5);
  assert.equal(avance(DIGITALIZAR, 'digitalizar-plano', true).resumen, 'Plano digitalizado: 65 lotes');
});

test('las pasadas que llegan desordenadas no hacen retroceder la barra', () => {
  const lineas = DIGITALIZAR.slice(0, 2);
  const adelante = avance([...lineas, 'Rótulos: 64 de 96 pasadas (81 s)'], 'digitalizar-plano');
  const despues = avance([...lineas, 'Rótulos: 64 de 96 pasadas (81 s)', 'Rótulos: 32 de 96 pasadas (82 s)'],
    'digitalizar-plano');
  assert.equal(despues.fraccion, adelante.fraccion);
});

test('sin lector (Windows, sin Tesseract) el paso de lectura no se queda pegado', () => {
  const lineas = ['Página 1 de 1: 1200×900 px, 3.00 px/mm (renderizada), rotación 0°',
    'sin lector de rótulos: falta pytesseract', 'Semillas: 12 de la loteadora y 0 del lector'];
  const progreso = avance(lineas, 'digitalizar-plano');
  assert.equal(progreso.paso, 2);
  assert.ok(progreso.fraccion > avance(lineas.slice(0, 1), 'digitalizar-plano').fraccion);
});

test('los tramos dentro del paso son solo de digitalizar: construir sigue igual', () => {
  // "X de Y" en otras líneas no reparte nada: la mitad del paso, como antes.
  const lineas = ['Leyendo el KMZ...', 'Lotes: 3 de 10'];
  assert.equal(avance(lineas, 'construir').fraccion, 0.5 / 9);
  assert.equal(avance(['Página 1 de 1', 'Red de deslindes: 1', 'Lotes: 3 de 10'], 'digitalizar-plano').fraccion,
    4.5 / 5);
});

test('la tarjeta del escáner tiene un número por lote del dibujo', () => {
  const tarjeta = html.slice(html.indexOf('id="kmz-escaner"'), html.indexOf('</section>', html.indexOf('id="kmz-escaner"')));
  const lotes = (tarjeta.match(/class="escaner__lote"/g) ?? []).length;
  assert.ok(lotes >= 10 && lotes <= 12, `${lotes} lotes`);
  assert.equal((tarjeta.match(/class="escaner__deslinde"/g) ?? []).length, lotes);
  assert.equal((tarjeta.match(/class="escaner__numero"/g) ?? []).length, lotes);
  // El registro técnico quedó plegado dentro de la tarjeta.
  assert.match(tarjeta, /<details id="kmz-escaner-detalle"[^>]*>\s*<summary>Ver el detalle técnico<\/summary>\s*<pre id="kmz-registro"/);
});

test('la tarjeta del escáner anuncia solo el texto y se ve aunque la animación no corra', () => {
  const desde = html.indexOf('id="kmz-escaner"');
  const tarjeta = html.slice(desde, html.indexOf('</section>', desde));
  // El aviso va en el título y el paso, no en el dibujo ni en el registro técnico.
  assert.doesNotMatch(html.slice(html.lastIndexOf('<section', desde), desde + 80), /aria-live/);
  assert.match(tarjeta, /<svg[^>]*aria-hidden="true"/);
  assert.match(tarjeta, /aria-live="polite"[^>]*>\s*<p id="kmz-escaner-titulo"/);
  assert.equal((tarjeta.match(/aria-live/g) ?? []).length, 1);
  // La hoja entra moviéndose, nunca desde transparente (pestaña oculta, sin movimiento).
  const css = readFileSync(join(aqui, 'consola.css'), 'utf8');
  const entrada = css.match(/@keyframes escaner-hoja \{[^\n]*\}/)[0];
  assert.doesNotMatch(entrada, /opacity/);
});

test('actualizar desde Cierra cuenta los pasos de construir y de publicar', () => {
  const lineas = [...CONSTRUIR, 'Generando control de calce...', 'Visor copiado en /datos/x',
    '▶ Publicando /datos/x como masterplan-x'];
  const progreso = avance(lineas, 'actualizar');
  assert.equal(progreso.total, 12);
  assert.equal(progreso.titulo, 'Subiendo a la web');
  assert.equal(avance([...lineas, '▶ URL publicada: https://masterplan-x.vercel.app'], 'actualizar', true).resumen,
    'Al día en línea: https://masterplan-x.vercel.app');
});
