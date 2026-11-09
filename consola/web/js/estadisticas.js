/**
 * Las estadísticas de un loteo publicado, en su detalle: cuánta gente entra al
 * sitio, qué parcelas abre y qué hace con ellas (WhatsApp, Reservar, Me interesa).
 *
 * Son cifras sumadas por día que manda el visor; no dicen quién fue. Sirven para
 * ver qué parcela se mira mucho y nadie reserva, o si un aviso trajo gente.
 */
import { $, pedir } from './comun.js';

const NUMERO = new Intl.NumberFormat('es-CL');
const DIA = new Intl.DateTimeFormat('es-CL', { day: 'numeric', month: 'short', timeZone: 'UTC' });
const ESTADO = {
  disponible: 'Disponible', reservado: 'Reservada', vendido: 'Vendida',
  no_disponible: 'No disponible', no_en_venta: 'No en venta',
};
const PARCELAS_A_LA_VISTA = 10;

let actual = { slug: null, dias: 30 };
let pidiendo = 0;

// --- Lo que decide sin DOM -------------------------------------------------------------

const fecha = (iso) => new Date(`${iso}T00:00:00Z`);

/**
 * Las barras del gráfico. Hasta 30 días, una por día; en 90, una por semana
 * (90 barras finas no se leen). La última semana puede venir corta.
 */
export function barras(porDia) {
  if (porDia.length <= 31) {
    return porDia.map((d) => ({ rotulo: DIA.format(fecha(d.dia)), valor: d.visitas, desde: d.dia, hasta: d.dia }));
  }
  const semanas = [];
  for (let i = 0; i < porDia.length; i += 7) {
    const tramo = porDia.slice(i, i + 7);
    semanas.push({
      rotulo: DIA.format(fecha(tramo[0].dia)),
      valor: tramo.reduce((suma, d) => suma + d.visitas, 0),
      desde: tramo[0].dia,
      hasta: tramo.at(-1).dia,
    });
  }
  return semanas;
}

/** "1 de cada 28 visitas", o null si no hay con qué comparar. */
export function unaDeCada(parte, total) {
  if (!parte || !total) return null;
  return `1 de cada ${NUMERO.format(Math.max(1, Math.round(total / parte)))} visitas`;
}

/** Las cinco cifras de arriba: { rotulo, valor, detalle }. */
export function tarjetas({ totales }) {
  const porVisita = totales.visita ? (totales.ficha / totales.visita).toFixed(1).replace('.', ',') : null;
  return [
    { rotulo: 'Visitas al sitio', valor: totales.visita, detalle: 'una por persona y sesión' },
    { rotulo: 'Parcelas abiertas', valor: totales.ficha, detalle: porVisita ? `${porVisita} por visita` : null },
    { rotulo: 'Consultas por WhatsApp', valor: totales.whatsapp, detalle: unaDeCada(totales.whatsapp, totales.visita) },
    { rotulo: 'Me interesa', valor: totales.interesa, detalle: unaDeCada(totales.interesa, totales.visita) },
    { rotulo: 'Reservas', valor: totales.reservas, detalle: `${NUMERO.format(totales.reservar)} clics en Reservar` },
  ];
}

/**
 * Una frase sobre lo que más llama la atención: la parcela disponible que más se
 * abre sin reservas. Si no hay nada que decir, null.
 */
export function lectura({ parcelas }) {
  const mirada = parcelas.find((p) => p.estado === 'disponible' && p.ficha >= 10 && !p.reservas);
  if (!mirada) return null;
  const interesados = mirada.interesa ? ` y ${mirada.interesa} dejaron sus datos` : '';
  return `La ${mirada.parcela} se abrió ${NUMERO.format(mirada.ficha)} veces${interesados}, y no tiene reservas: `
    + 'puede valer la pena llamar a quienes preguntaron o revisar su precio.';
}

// --- La sección ----------------------------------------------------------------------

export function prepararEstadisticas() {
  $('#estadisticas-dias').addEventListener('click', (evento) => {
    const boton = evento.target.closest('button[data-dias]');
    if (!boton || !actual.slug) return;
    cargar(actual.slug, Number(boton.dataset.dias));
  });
}

/**
 * Se llama al pintar el detalle de un loteo. Solo pide al llegar (`nuevo`): un
 * refresco mientras construye no tiene por qué volver a contar.
 */
export function pintarEstadisticas(proyecto, { nuevo = false } = {}) {
  const seccion = $('#plano-estadisticas');
  seccion.hidden = !proyecto.publicado;
  if (!proyecto.publicado) return;
  if (nuevo || actual.slug !== proyecto.slug) cargar(proyecto.slug, actual.slug === proyecto.slug ? actual.dias : 30);
}

async function cargar(slug, dias) {
  actual = { slug, dias };
  const turno = ++pidiendo;
  for (const boton of document.querySelectorAll('#estadisticas-dias button')) {
    boton.setAttribute('aria-pressed', String(Number(boton.dataset.dias) === dias));
  }
  $('#plano-estadisticas').setAttribute('aria-busy', 'true');
  try {
    const cifras = await pedir(`/api/proyectos/${encodeURIComponent(slug)}/estadisticas?dias=${dias}`);
    // Se cambió de loteo o de período mientras llegaba: esto ya no corresponde.
    if (turno === pidiendo) pintar(cifras);
  } catch {
    if (turno === pidiendo) pintarError();
  } finally {
    if (turno === pidiendo) $('#plano-estadisticas').removeAttribute('aria-busy');
  }
}

function nodo(etiqueta, clase, texto) {
  const elemento = document.createElement(etiqueta);
  if (clase) elemento.className = clase;
  if (texto != null) elemento.textContent = texto;
  return elemento;
}

function pintar(cifras) {
  $('#estadisticas-periodo').textContent =
    `Del ${DIA.format(fecha(cifras.desde))} al ${DIA.format(fecha(cifras.hasta))}`;
  $('#estadisticas-tarjetas').replaceChildren(...tarjetas(cifras).map((t) => {
    const div = nodo('div', 'estadistica');
    div.append(nodo('dt', null, t.rotulo), nodo('dd', null, NUMERO.format(t.valor ?? 0)));
    if (t.detalle) div.append(nodo('small', null, t.detalle));
    return div;
  }));
  pintarGrafico(barras(cifras.por_dia), cifras.dias > 31);
  const frase = lectura(cifras);
  $('#estadisticas-lectura').textContent = frase ?? '';
  $('#estadisticas-lectura').hidden = !frase;
  pintarTabla(cifras.parcelas);
}

function pintarGrafico(lista, porSemana) {
  $('#estadisticas-grafico-titulo').textContent = porSemana ? 'Visitas por semana' : 'Visitas por día';
  const grafico = $('#estadisticas-grafico');
  const maximo = Math.max(1, ...lista.map((b) => b.valor));
  // Rótulos de fecha cada tantas barras: con 30 no caben todos.
  const cada = Math.ceil(lista.length / 8);
  grafico.style.setProperty('--barras', lista.length);
  grafico.replaceChildren(...lista.map((barra, i) => {
    const columna = nodo('div', 'grafico__columna');
    const texto = porSemana && barra.desde !== barra.hasta
      ? `Semana del ${DIA.format(fecha(barra.desde))}: ${NUMERO.format(barra.valor)} visitas`
      : `${DIA.format(fecha(barra.desde))}: ${NUMERO.format(barra.valor)} visitas`;
    columna.tabIndex = 0;
    columna.setAttribute('aria-label', texto);
    columna.dataset.tip = texto;
    const marca = nodo('span', 'grafico__barra');
    marca.style.height = `${(barra.valor / maximo) * 100}%`;
    columna.append(marca, nodo('span', 'grafico__rotulo', i % cada === 0 ? barra.rotulo : ''));
    return columna;
  }));
  $('#estadisticas-maximo').textContent = NUMERO.format(maximo);
  const sinVisitas = lista.every((b) => !b.valor);
  grafico.classList.toggle('grafico--vacio', sinVisitas);
  $('#estadisticas-vacio').hidden = !sinVisitas;
}

function pintarTabla(parcelas) {
  const cuerpo = $('#estadisticas-parcelas');
  const tabla = cuerpo.closest('table');
  tabla.hidden = !parcelas.length;
  $('#estadisticas-sin-parcelas').hidden = Boolean(parcelas.length);
  cuerpo.replaceChildren(...parcelas.slice(0, PARCELAS_A_LA_VISTA).map((p) => {
    const fila = nodo('tr');
    const estado = nodo('td');
    if (p.estado) {
      const insignia = nodo('span', 'estado-parcela');
      insignia.append(nodo('i', `punto-estado punto-estado--${p.estado}`), ESTADO[p.estado] ?? p.estado);
      estado.append(insignia);
    } else {
      estado.append(nodo('span', 'nota', 'Ya no está en el sitio'));
    }
    fila.append(nodo('th', null, p.parcela), estado,
                ...['ficha', 'whatsapp', 'interesa', 'reservar', 'reservas'].map((k) => nodo('td', 'num', NUMERO.format(p[k]))));
    return fila;
  }));
}

function pintarError() {
  $('#estadisticas-tarjetas').replaceChildren(nodo('p', 'nota', 'No pudimos traer las cifras. Prueba recargando la página.'));
  $('#estadisticas-grafico').replaceChildren();
  $('#estadisticas-parcelas').replaceChildren();
}
