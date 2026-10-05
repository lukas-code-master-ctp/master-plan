/**
 * "Conectar con Cierra": el inventario del loteo sale del CRM de la loteadora.
 *
 * La clave se pega una vez por loteadora; en cada loteo se eligen los proyectos de
 * Cierra que lo alimentan, uno por etapa. Después, construir trae lo último solo,
 * y "Actualizar desde Cierra" lo trae sin tener que reconstruir las fotos.
 */
import { $, abrirDialogo, avisar, fecha, json, pedir } from './comun.js';

const estados = new Map();   // slug → lo que contestó GET /api/proyectos/{slug}/cierra
let slugActual = null;
let nombreDelLoteo = '';
let alTraer = async () => {};

/** `traido(slug)` se llama con el inventario nuevo ya en la carpeta del loteo. */
export function prepararCierra({ traido }) {
  alTraer = traido;
  $('#cierra-guardar-clave').addEventListener('click', guardarClave);
  $('#cierra-otra-clave').addEventListener('click', () => mostrarPaso('clave'));
  $('#cierra-listo').addEventListener('click', conectar);
  $('#cierra-buscar').addEventListener('input', filtrar);
  $('#cierra-lista').addEventListener('change', filtrar);
  // La clave no se queda en la página: ni tras un error ni al cerrar con la ✕.
  $('#cierra').addEventListener('close', () => { $('#cierra-clave').value = ''; });
}

/** Pinta el bloque con lo que se sabe; la primera vez por loteo lo pregunta. */
export function pintarCierra(proyecto) {
  slugActual = proyecto.slug;
  const estado = estados.get(proyecto.slug);
  if (!estado) {
    $('#inventario-cierra').hidden = true;
    cargar(proyecto.slug).then(() => {
      if (slugActual === proyecto.slug) pintarCierra(proyecto);
    });
    return;
  }
  const bloque = $('#inventario-cierra');
  bloque.hidden = !estado.disponible;
  if (!estado.disponible) return;

  const conectado = estado.conectado;
  $('#cierra-estado').textContent = conectado
    ? `Conectado a Cierra: ${estado.proyectos.map((p) => `${p.nombre} (etapa ${p.etapa})`).join(', ')}.`
      + (estado.sincronizado_en ? ` Actualizado ${fecha(estado.sincronizado_en)}.` : '')
    : '¿Llevas las parcelas en Cierra? Conéctalo y los estados y precios llegan solos.';
  const boton = (accion) => $(`[data-accion="${accion}"]`, bloque);
  boton('cierra-conectar').textContent = conectado ? 'Cambiar proyectos' : 'Conectar con Cierra';
  boton('cierra-actualizar').hidden = !conectado;
  boton('cierra-desconectar').hidden = !conectado;
  const ocupado = Boolean(proyecto.trabajo);
  boton('cierra-actualizar').disabled = ocupado;
  boton('cierra-conectar').disabled = ocupado;
  // Conectado, una planilla subida a mano duraría hasta la próxima construcción.
  $('#inventario-subir').hidden = conectado;
}

export async function manejarCierra(accion, proyecto) {
  if (accion === 'cierra-conectar') return abrir(proyecto);
  if (accion === 'cierra-actualizar') {
    const { parcelas } = await pedir(`/api/proyectos/${proyecto.slug}/cierra/actualizar`, json({}));
    avisar(null);
    await cargar(proyecto.slug);
    await alTraer(proyecto.slug, parcelas);
    return undefined;
  }
  if (accion === 'cierra-desconectar') {
    if (!confirm('¿Desconectar este loteo de Cierra? Se queda con los últimos estados y '
      + 'precios que llegaron; puedes volver a conectarlo cuando quieras.')) return undefined;
    await pedir(`/api/proyectos/${proyecto.slug}/cierra`, { method: 'DELETE' });
    await cargar(proyecto.slug);
    pintarCierra(proyecto);
  }
  return undefined;
}

async function cargar(slug) {
  try {
    estados.set(slug, await pedir(`/api/proyectos/${slug}/cierra`));
  } catch {
    estados.set(slug, { disponible: false });
  }
}

// --- El diálogo ------------------------------------------------------------------

async function abrir(proyecto) {
  $('#cierra-clave').value = '';
  nombreDelLoteo = proyecto.nombre ?? '';
  abrirDialogo($('#cierra'));
  const estado = estados.get(proyecto.slug);
  if (!estado?.pista) return mostrarPaso('clave');
  return mostrarProyectos(estado);
}

function mostrarPaso(paso) {
  $('#cierra-paso-clave').hidden = paso !== 'clave';
  $('#cierra-paso-proyectos').hidden = paso !== 'proyectos';
  if (paso === 'clave') $('#cierra-clave').focus();
}

async function guardarClave() {
  const clave = $('#cierra-clave').value.trim();
  if (!clave) return avisar('Pega la clave de API de Cierra.');
  const boton = $('#cierra-guardar-clave');
  boton.disabled = true;
  try {
    avisar(null);
    await pedir(`/api/proyectos/${slugActual}/cierra/clave`, json({ clave }, 'PUT'));
    await cargar(slugActual);
    await mostrarProyectos(estados.get(slugActual));
  } catch (error) {
    avisar(error.message);
  } finally {
    $('#cierra-clave').value = '';
    boton.disabled = false;
  }
  return undefined;
}

async function mostrarProyectos(estado) {
  const lista = $('#cierra-lista');
  lista.replaceChildren();
  $('#cierra-pista').textContent = `Usando la clave que termina en …${estado.pista}.`;
  mostrarPaso('proyectos');
  let opciones;
  try {
    ({ proyectos: opciones } = await pedir(`/api/proyectos/${slugActual}/cierra/opciones`));
  } catch (error) {
    return avisar(error.message);
  }
  const elegidos = new Map(estado.proyectos.map((p) => [p.id, p.etapa]));
  if (!opciones.length) return avisar('Esa clave no ve ningún proyecto en Cierra.');
  lista.replaceChildren(...opciones.map((opcion) => fila(opcion, elegidos)));
  // Se abre ya buscando el loteo: en Cierra hay decenas de proyectos y los de
  // este casi siempre llevan su nombre. Si nada calza, se ven todos.
  const nombres = opciones.map((o) => o.nombre);
  $('#cierra-buscar').value = nombres.some((n) => coincide(n, nombreDelLoteo)) ? nombreDelLoteo : '';
  filtrar();
  return undefined;
}

/** Sin tildes ni mayúsculas: "Praderas de Cauquenes" encuentra "PRADERAS DE CAUQUENES ET2". */
export function normalizar(texto) {
  return String(texto ?? '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase().trim();
}

/** Cada palabra de la búsqueda tiene que estar en el nombre, en cualquier orden. */
export function coincide(nombre, consulta) {
  const donde = normalizar(nombre);
  return normalizar(consulta).split(/\s+/).filter(Boolean).every((palabra) => donde.includes(palabra));
}

/** Muestra lo que calza con la búsqueda; lo marcado no se esconde nunca. */
function filtrar() {
  const consulta = $('#cierra-buscar').value;
  let visibles = 0;
  let marcados = 0;
  for (const li of $('#cierra-lista').children) {
    const marcado = $('input[type=checkbox]', li).checked;
    li.hidden = !marcado && !coincide(li.dataset.nombre, consulta);
    if (!li.hidden) visibles += 1;
    if (marcado) marcados += 1;
  }
  const total = $('#cierra-lista').children.length;
  const marcadosTexto = marcados ? `${marcados} marcado${marcados === 1 ? '' : 's'} · ` : '';
  $('#cierra-cuenta').textContent = visibles === marcados && consulta.trim()
    ? `${marcadosTexto}Ningún otro proyecto calza con "${consulta.trim()}".`
    : `${marcadosTexto}${visibles} de ${total} proyectos`;
}

function fila(opcion, elegidos) {
  const li = document.createElement('li');
  li.dataset.id = opcion.id;
  li.dataset.nombre = opcion.nombre;
  const etiqueta = document.createElement('label');
  const marca = document.createElement('input');
  marca.type = 'checkbox';
  marca.checked = elegidos.has(opcion.id);
  const nombre = document.createElement('span');
  nombre.textContent = opcion.nombre;
  const cifras = document.createElement('small');
  cifras.textContent = `${opcion.parcelas_disponibles} de ${opcion.parcelas_total} disponibles`;
  nombre.append(document.createElement('br'), cifras);
  etiqueta.append(marca, nombre);

  const etapa = document.createElement('label');
  etapa.className = 'cierra-etapa';
  etapa.textContent = 'Etapa';
  const numero = document.createElement('input');
  numero.type = 'number';
  numero.min = '1';
  numero.max = '50';
  numero.value = elegidos.get(opcion.id) ?? opcion.etapa_sugerida;
  etapa.append(numero);
  li.append(etiqueta, etapa);
  return li;
}

async function conectar() {
  const proyectos = [...$('#cierra-lista').children]
    .filter((li) => $('input[type=checkbox]', li).checked)
    .map((li) => ({ id: Number(li.dataset.id), etapa: Number($('input[type=number]', li).value) }));
  if (!proyectos.length) return avisar('Marca al menos un proyecto de Cierra.');
  const boton = $('#cierra-listo');
  boton.disabled = true;
  const slug = slugActual;
  try {
    avisar(null);
    const { parcelas } = await pedir(`/api/proyectos/${slug}/cierra`, json({ proyectos }, 'PUT'));
    $('#cierra').close();
    await cargar(slug);
    await alTraer(slug, parcelas);
  } catch (error) {
    avisar(error.message);
  } finally {
    boton.disabled = false;
  }
  return undefined;
}
