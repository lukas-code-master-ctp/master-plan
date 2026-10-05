#!/usr/bin/env node
/**
 * Capturas de la consola levantada con `npm run qa:levantar`, con Playwright.
 *
 *   node qa/captura.mjs --como duenio --ruta '#/planos'
 *   node qa/captura.mjs --como anonimo --ruta /registro --movil
 *   node qa/captura.mjs --ruta "$(python -m qa.correos --ultimo)" --como anonimo
 *   node qa/captura.mjs                       # el recorrido de siempre
 *
 * Opciones: --como <alias> (plataforma, duenio, equipo, otra, sinconfirmar, anonimo;
 * por defecto duenio), --ruta <#/... | /... | http...>, --movil, --esperar <selector>,
 * --salida <archivo.png>, --pagina-completa.
 *
 * Imprime la ruta de cada captura y, por cada una, los errores de consola del
 * navegador y las respuestas 4xx/5xx que vio: son hallazgos, no fallas del script,
 * así que no cambian el código de salida. Sale con 1 solo si no se pudo abrir la
 * consola o entrar con una cuenta.
 */
import { execSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const CARPETA = path.join(REPO, '.qa', 'capturas');
const BASE = (process.env.QA_URL_CONSOLA
  || `http://127.0.0.1:${process.env.QA_PUERTO_CONSOLA || 8780}`).replace(/\/+$/, '');

// Deben coincidir con CUENTAS de qa/sembrar.py: si cambia una, cambia la otra.
const CLAVE = 'qa-clave-segura-1';
const CUENTAS = {
  plataforma: 'plataforma@qa.test',
  duenio: 'duenio@loteadora-demo.test',
  equipo: 'equipo@loteadora-demo.test',
  otra: 'duenio@otra-loteadora.test',
  sinconfirmar: 'sinconfirmar@qa.test',
};
const ALIAS = [...Object.keys(CUENTAS), 'anonimo'];

const MOVIL = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
const ESCRITORIO = { viewport: { width: 1440, height: 900 } };

class NoSePudo extends Error {}

// --- Playwright --------------------------------------------------------------

/** El del repo si algún día está en node_modules; si no, el global de la máquina. */
async function cargarPlaywright() {
  try {
    return await import('playwright');
  } catch { /* sigue con el global */ }
  try {
    const raiz = execSync('npm root -g', { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    const requerir = createRequire(path.join(raiz, 'noop.js'));
    return requerir(path.join(raiz, 'playwright'));
  } catch {
    return null;
  }
}

// --- Rutas y nombres ---------------------------------------------------------

function urlDe(ruta) {
  if (/^https?:\/\//.test(ruta)) return ruta;
  if (ruta.startsWith('#')) return `${BASE}/${ruta}`;
  return `${BASE}${ruta.startsWith('/') ? '' : '/'}${ruta}`;
}

function saneada(ruta) {
  return ruta.replace(/^https?:\/\//, '').replace(/[^a-zA-Z0-9]+/g, '-').replace(/^-+|-+$/g, '')
    .toLowerCase() || 'raiz';
}

// `npm run` corre en la raíz del repo; INIT_CWD es la carpeta desde donde se llamó.
const DESDE = process.env.INIT_CWD || process.cwd();

function relativa(archivo) {
  const rel = path.relative(DESDE, archivo);
  return rel.startsWith('..') ? archivo : rel;
}

// --- Navegador ---------------------------------------------------------------

/**
 * Un contexto por alias y tamaño, que entra una sola vez y se reutiliza. Los
 * hallazgos (errores de consola, de página y respuestas >= 400) se juntan en
 * `hallazgos`, que se vacía antes de cada captura.
 */
class Sesiones {
  constructor(navegador) {
    this.navegador = navegador;
    this.abiertas = new Map();
  }

  async pagina(alias, movil) {
    const clave = `${alias}${movil ? '-movil' : ''}`;
    if (!this.abiertas.has(clave)) this.abiertas.set(clave, this.abrir(alias, movil));
    return this.abiertas.get(clave);
  }

  async abrir(alias, movil) {
    const contexto = await this.navegador.newContext({ ...(movil ? MOVIL : ESCRITORIO), locale: 'es-CL' });
    const pagina = await contexto.newPage();
    const sesion = { alias, movil, contexto, pagina, hallazgos: [] };
    pagina.on('console', (mensaje) => {
      if (mensaje.type() === 'error') sesion.hallazgos.push(`consola: ${mensaje.text()}`);
    });
    pagina.on('pageerror', (error) => sesion.hallazgos.push(`página: ${error.message}`));
    pagina.on('response', (respuesta) => {
      if (respuesta.status() >= 400) {
        sesion.hallazgos.push(`${respuesta.request().method()} ${respuesta.url()} → ${respuesta.status()}`);
      }
    });
    if (alias !== 'anonimo') await entrar(sesion);
    return sesion;
  }

  async cerrar() {
    for (const abierta of this.abiertas.values()) {
      try { await (await abierta).contexto.close(); } catch { /* ya cerrada o nunca abrió */ }
    }
  }
}

async function ir(pagina, url) {
  try {
    await pagina.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 });
  } catch (error) {
    throw new NoSePudo(`no se pudo abrir ${url}: ${error.message.split('\n')[0]}`);
  }
}

async function entrar(sesion) {
  const { alias, pagina } = sesion;
  await ir(pagina, urlDe('/entrar'));
  await pagina.fill('input[name="email"]', CUENTAS[alias]);
  await pagina.fill('input[name="clave"]', CLAVE);
  await Promise.all([
    pagina.waitForNavigation({ waitUntil: 'domcontentloaded', timeout: 20000 }).catch(() => {}),
    pagina.click('form[action="/entrar"] button[type="submit"], form[action="/entrar"] [type="submit"]'),
  ]);
  const camino = new URL(pagina.url()).pathname;
  const aviso = await pagina.locator('.aviso').first().textContent({ timeout: 1000 }).catch(() => null);
  if (camino === '/entrar') {
    const motivo = aviso ? aviso.trim() : 'sin aviso en la página';
    if (alias === 'sinconfirmar') {
      console.log(`  (sinconfirmar no entró, como se espera: ${motivo})`);
      return;
    }
    throw new NoSePudo(`${alias} (${CUENTAS[alias]}) no pudo entrar: ${motivo}`);
  }
  if (alias === 'sinconfirmar') console.log(`  ojo: sinconfirmar entró y no debería (quedó en ${pagina.url()})`);
  // Lo que vio al entrar no es de ninguna captura.
  sesion.hallazgos.length = 0;
}

async function esperar(pagina, selector) {
  if (selector) {
    try {
      await pagina.waitForSelector(selector, { timeout: 15000 });
    } catch {
      console.log(`  aviso: no apareció ${selector} en 15 s; se captura igual`);
    }
    return;
  }
  // La consola sondea los trabajos en curso: puede que nunca quede del todo quieta.
  await pagina.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
  await pagina.waitForTimeout(500);
}

/**
 * Una captura: navega (si hay ruta), corre `antes` (p. ej. abrir un diálogo),
 * espera, saca la foto e imprime lo que vio.
 */
async function capturar(sesiones, { alias, movil, ruta, antes, esperarA, salida, completa }) {
  const sesion = await sesiones.pagina(alias, movil);
  const { pagina } = sesion;
  sesion.hallazgos.length = 0;
  if (ruta) await ir(pagina, urlDe(ruta));
  if (antes) {
    await esperar(pagina, null);
    await antes(pagina);
  }
  await esperar(pagina, esperarA);
  mkdirSync(path.dirname(salida), { recursive: true });
  await pagina.screenshot({ path: salida, fullPage: Boolean(completa) });
  console.log(relativa(salida));
  for (const hallazgo of sesion.hallazgos) console.log(`  ! ${hallazgo}`);
  return sesion.hallazgos.length;
}

/** Los loteos que ve el alias, con su sesión (las cookies del contexto). */
async function proyectos(sesiones, alias, movil) {
  const { contexto } = await sesiones.pagina(alias, movil);
  const respuesta = await contexto.request.get(urlDe('/api/proyectos'));
  if (!respuesta.ok()) throw new NoSePudo(`/api/proyectos contestó ${respuesta.status()}`);
  return respuesta.json();
}

// --- El recorrido ------------------------------------------------------------

const PRADERAS = 'Praderas Demo';

async function praderas(sesiones, movil) {
  const lista = await proyectos(sesiones, 'duenio', movil);
  return lista.find((p) => String(p.nombre).includes(PRADERAS)) ?? null;
}

const RECORRIDO = [
  { nombre: 'entrar', alias: 'anonimo', ruta: async () => '/entrar' },
  { nombre: 'planos', alias: 'duenio', ruta: async () => '#/planos' },
  {
    nombre: 'praderas', alias: 'duenio',
    ruta: async (sesiones, movil) => {
      const proyecto = await praderas(sesiones, movil);
      if (!proyecto) return { salto: `duenio no tiene un loteo "${PRADERAS}"` };
      return `#/planos/${encodeURIComponent(proyecto.slug)}`;
    },
  },
  { nombre: 'kmz', alias: 'duenio', ruta: async () => '#/kmz' },
  { nombre: 'disenos', alias: 'duenio', ruta: async () => '#/disenos' },
  {
    // El back-office es el diálogo "Loteadoras" del menú de la cuenta.
    nombre: 'backoffice', alias: 'plataforma', ruta: async () => '#/planos',
    esperarA: 'dialog#clientes[open]',
    antes: async (pagina) => {
      await pagina.click('#avatar');
      await pagina.click('#loteadoras', { timeout: 5000 });
    },
  },
  {
    nombre: 'publicado', alias: 'duenio',
    ruta: async (sesiones, movil) => {
      const proyecto = await praderas(sesiones, movil);
      if (!proyecto) return { salto: `duenio no tiene un loteo "${PRADERAS}"` };
      if (!proyecto.publicado) return { salto: `"${proyecto.nombre}" no está publicado` };
      return proyecto.url;
    },
  },
];

async function recorrido(sesiones, completa) {
  let fallas = 0;
  let hallazgos = 0;
  const caidos = new Set();       // alias que no pudieron entrar: no se reintenta
  for (const movil of [false, true]) {
    console.log(movil ? '\n— celular —' : '— escritorio —');
    for (const [i, paso] of RECORRIDO.entries()) {
      const numero = String(i + 1).padStart(2, '0');
      const etiqueta = `${numero}-${paso.nombre}`;
      if (caidos.has(paso.alias)) {
        console.log(`${etiqueta}: saltada, ${paso.alias} no entró`);
        continue;
      }
      try {
        const ruta = await paso.ruta(sesiones, movil);
        if (typeof ruta === 'object') {
          console.log(`${etiqueta}: saltada, ${ruta.salto}`);
          continue;
        }
        const salida = path.join(CARPETA, `${etiqueta}${movil ? '-movil' : ''}.png`);
        hallazgos += await capturar(sesiones, {
          alias: paso.alias, movil, ruta, antes: paso.antes, esperarA: paso.esperarA, salida, completa,
        });
      } catch (error) {
        if (error instanceof NoSePudo) {
          fallas += 1;
          if (/no pudo entrar/.test(error.message)) caidos.add(paso.alias);
          console.log(`${etiqueta}: ${error.message}`);
        } else {
          // Un paso que no encuentra lo suyo (un botón que no está) es hallazgo, no caída.
          console.log(`${etiqueta}: no se pudo capturar: ${error.message.split('\n')[0]}`);
        }
      }
    }
  }
  console.log(`\n${hallazgos} hallazgo(s) en el navegador${fallas ? `, ${fallas} paso(s) sin consola o sin entrar` : ''}.`);
  return fallas ? 1 : 0;
}

// --- Principal ---------------------------------------------------------------

async function principal() {
  let opciones;
  try {
    ({ values: opciones } = parseArgs({
      options: {
        como: { type: 'string', default: 'duenio' },
        ruta: { type: 'string' },
        movil: { type: 'boolean', default: false },
        esperar: { type: 'string' },
        salida: { type: 'string' },
        'pagina-completa': { type: 'boolean', default: false },
        ayuda: { type: 'boolean', short: 'h', default: false },
      },
    }));
  } catch (error) {
    console.error(error.message);
    return 2;
  }
  if (opciones.ayuda) {
    console.log('Uso: node qa/captura.mjs [--como <alias>] [--ruta <#/...|/...|http...>] [--movil]\n'
      + '       [--esperar <selector>] [--salida <archivo.png>] [--pagina-completa]\n'
      + `Alias: ${ALIAS.join(', ')}. Sin --ruta saca el recorrido de siempre.`);
    return 0;
  }
  if (!ALIAS.includes(opciones.como)) {
    console.error(`--como debe ser uno de: ${ALIAS.join(', ')}`);
    return 2;
  }

  const playwright = await cargarPlaywright();
  if (!playwright) {
    console.error('No encontré Playwright: ni en node_modules del repo ni el global (`npm root -g`).\n'
      + 'Instálalo con `npm install -g playwright` y su Chromium con `npx playwright install chromium`.');
    return 1;
  }
  let navegador;
  try {
    navegador = await playwright.chromium.launch();
  } catch (error) {
    console.error(`No pude abrir Chromium: ${error.message.split('\n')[0]}\n`
      + '¿Está PLAYWRIGHT_BROWSERS_PATH apuntando a los navegadores de la máquina?');
    return 1;
  }

  const sesiones = new Sesiones(navegador);
  try {
    if (!opciones.ruta) return await recorrido(sesiones, opciones['pagina-completa']);
    const salida = opciones.salida
      ? path.resolve(DESDE, opciones.salida)
      : path.join(CARPETA, `${opciones.como}-${saneada(opciones.ruta)}${opciones.movil ? '-movil' : ''}.png`);
    await capturar(sesiones, {
      alias: opciones.como, movil: opciones.movil, ruta: opciones.ruta,
      esperarA: opciones.esperar, salida, completa: opciones['pagina-completa'],
    });
    return 0;
  } catch (error) {
    console.error(error instanceof NoSePudo ? error.message : error.stack);
    return 1;
  } finally {
    await sesiones.cerrar();
    await navegador.close();
  }
}

process.exitCode = await principal();
