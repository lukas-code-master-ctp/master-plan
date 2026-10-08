/**
 * Lo que se ve del detalle de un loteo, aparte de construir y publicar (eso sigue
 * en plano.js): el estado sobre la portada, las cifras con su barra, el medidor
 * del sol y las tarjetas del control de calce.
 */
import { $, etapaDe, fecha, pastilla } from './comun.js';
import { barra, contar } from './planos.js';

// Sobre esta diferencia entre la elevación del sol calculada y la medida, el
// rumbo puede estar mal (pipeline/construir.py, ERROR_ELEVACION_SOSPECHOSO).
const ERROR_SOL_SOSPECHOSO = 3;
// Un ajuste fino que mejora menos que esto no se aplica (pipeline/calibracion.py).
const MEJORA_MINIMA = 0.03;
const NUMERO = new Intl.NumberFormat('es-CL');
const UN_DECIMAL = new Intl.NumberFormat('es-CL', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const ROMANOS = [[10, 'X'], [9, 'IX'], [5, 'V'], [4, 'IV'], [1, 'I']];
const ROTULOS = { disponible: 'Disponibles', reservado: 'Reservadas', vendido: 'Vendidas', no_disponible: 'No disponibles' };

function romano(numero) {
  let resto = numero;
  let texto = '';
  for (const [valor, letras] of ROMANOS) {
    while (resto >= valor) { texto += letras; resto -= valor; }
  }
  return texto;
}

/** "p04-500.jpg" → "Punto IV · 500 m", como en el visor. */
export function nombreDeVista(archivo) {
  const id = archivo.replace(/\.jpg$/, '');
  const partes = /^p(\d+)-(-?\d+)$/.exec(id);
  if (!partes) return id;
  const altura = Number(partes[2]);
  return `Punto ${romano(Number(partes[1]))} · ${altura < 0 ? `−${-altura}` : altura} m`;
}

/** El peor error del sol entre las vistas y cuánto llena del medidor (hasta el límite). */
export function medicionDelSol(calce) {
  if (!calce?.length) return null;
  const peor = Math.max(...calce.map((c) => c.error_sol));
  return { peor, revisar: peor > ERROR_SOL_SOSPECHOSO, fraccion: Math.min(1, peor / ERROR_SOL_SOSPECHOSO) };
}

// --- Sobre la portada -------------------------------------------------------------------

/** Arriba a la derecha: en qué está el loteo y, si está en línea, el atajo al sitio. */
export function pintarEstado(proyecto) {
  const partes = [];
  // Sin teléfono el visor esconde el botón de contacto: el comprador mira, se
  // decide y no tiene a quién escribirle. Se avisa antes de publicar, no después.
  if (proyecto.sin_contacto) partes.push(pastilla('Sin contacto', 'aviso'));
  const etapa = etapaDe(proyecto);
  if (proyecto.publicado && !proyecto.trabajo) {
    const vivo = document.createElement('i');
    vivo.className = 'punto-vivo';
    etapa.prepend(vivo);
  }
  partes.push(etapa);
  if (proyecto.publicado) {
    const enlace = document.createElement('a');
    enlace.className = 'pastilla pastilla--enlace';
    enlace.href = proyecto.url;
    enlace.target = '_blank';
    enlace.rel = 'noopener';
    enlace.textContent = 'Ver sitio ↗';
    partes.push(enlace);
  }
  $('#plano-estado').replaceChildren(...partes);
}

/** Bajo el nombre: la etapa, de dónde salen los datos y cuándo se construyó. */
export function meta(proyecto) {
  const hallado = proyecto.fuentes_encontradas;
  const textos = [];
  if (proyecto.etapa) textos.push(proyecto.etapa);
  textos.push(`${hallado.panoramicas} panorámicas · ${hallado.megas} MB`);
  textos.push(hallado.planilla ? `Planilla ${hallado.planilla}` : proyecto.con_crm ? 'Precios del CRM' : 'Sin planilla');
  if (proyecto.construido && proyecto.resumen.generado) textos.push(`Construido el ${fecha(proyecto.resumen.generado)}`);
  return textos.map((texto) => {
    const span = document.createElement('span');
    span.className = 'meta__dato';
    span.textContent = texto;
    return span;
  });
}

// --- Cifras ---------------------------------------------------------------------------

export function pintarCifras(proyecto, { animar = false } = {}) {
  const seccion = $('#plano-cifras');
  if (!proyecto.construido) { seccion.hidden = true; return; }
  const movimiento = animar && !matchMedia('(prefers-reduced-motion: reduce)').matches;
  seccion.classList.toggle('cifras--entrando', movimiento);
  const { resumen } = proyecto;
  const porEstado = resumen.por_estado ?? {};

  const cifras = [
    { rotulo: 'Parcelas', valor: resumen.parcelas ?? 0, estado: 'total' },
    ...['disponible', 'reservado', 'vendido', 'no_disponible'].map((nombre) => ({
      rotulo: ROTULOS[nombre],
      valor: (porEstado[nombre] ?? 0) + (nombre === 'no_disponible' ? porEstado.no_en_venta ?? 0 : 0),
      estado: nombre,
    })),
  ];
  const lista = $('.cifras__lista', seccion);
  lista.replaceChildren(...cifras.map(({ rotulo, valor, estado: nombre }) => {
    const div = document.createElement('div');
    const dt = document.createElement('dt');
    const punto = document.createElement('i');
    punto.className = `punto-estado punto-estado--${nombre}`;
    dt.append(punto, rotulo);
    const dd = document.createElement('dd');
    dd.dataset.valor = valor;
    dd.textContent = NUMERO.format(movimiento ? 0 : valor);
    div.append(dt, dd);
    return div;
  }));
  $('.cifras__barra', seccion).replaceChildren(...barra(porEstado, resumen.parcelas || 1));

  const sol = medicionDelSol(resumen.calce);
  $('.cifras__sol', seccion).hidden = !sol;
  if (sol) {
    $('#sol-grados').textContent = `${UN_DECIMAL.format(sol.peor)}°`;
    $('#sol-nota').textContent = sol.revisar ? 'Revisa el rumbo' : 'Dentro de lo normal';
    $('.cifras__sol', seccion).classList.toggle('cifras__sol--revisar', sol.revisar);
    seccion.style.setProperty('--sol', String(sol.fraccion));
    const vistas = resumen.vistas ?? resumen.calce.length;
    $('#sol-detalle').textContent = vistas > 1
      ? `El peor de los ${vistas} puntos de vuelo. Sobre ${ERROR_SOL_SOSPECHOSO}° hay que revisarlo.`
      : `Sobre ${ERROR_SOL_SOSPECHOSO}° hay que revisarlo.`;
  }
  seccion.hidden = false;
  if (movimiento) contar([...lista.querySelectorAll('dd')]);
}

// --- Control de calce -------------------------------------------------------------------

export function pintarCalce(proyecto) {
  const seccion = $('#plano-calce');
  if (!proyecto.calce.length || proyecto.trabajo) { seccion.hidden = true; return; }
  const porVista = new Map((proyecto.resumen.calce ?? []).map((c) => [c.vista, c]));
  $('.calce__tiras', seccion).replaceChildren(...proyecto.calce.map((archivo) => {
    const nombre = nombreDeVista(archivo);
    const datos = porVista.get(archivo.replace(/\.jpg$/, ''));
    const enlace = document.createElement('a');
    enlace.className = 'tira';
    enlace.href = `/calce/${proyecto.slug}/${archivo}`;
    enlace.target = '_blank';
    enlace.rel = 'noopener';
    const marco = document.createElement('span');
    marco.className = 'tira__foto';
    const imagen = document.createElement('img');
    imagen.src = enlace.href;
    imagen.alt = `Control de calce del ${nombre}`;
    imagen.loading = 'lazy';
    marco.append(imagen);
    const pie = document.createElement('span');
    pie.className = 'tira__pie';
    const titulo = document.createElement('strong');
    titulo.textContent = nombre;
    pie.append(titulo);
    if (datos) {
      const fichas = document.createElement('span');
      fichas.className = 'tira__fichas';
      const sol = document.createElement('span');
      sol.className = `ficha-calce${datos.error_sol > ERROR_SOL_SOSPECHOSO ? ' ficha-calce--aviso' : ' ficha-calce--ok'}`;
      sol.textContent = `Sol ${UN_DECIMAL.format(datos.error_sol)}°`;
      const ajuste = document.createElement('span');
      ajuste.className = 'ficha-calce';
      ajuste.textContent = datos.mejora >= MEJORA_MINIMA ? 'Con ajuste fino' : 'Sin ajuste fino';
      fichas.append(sol, ajuste);
      pie.append(fichas);
    }
    enlace.append(marco, pie);
    return enlace;
  }));
  seccion.hidden = false;
}
