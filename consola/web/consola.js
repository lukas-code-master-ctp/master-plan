/**
 * Consola de Tu Masterplan.
 *
 * Una página: la lista de loteos, y por cada uno construir → revisar el calce →
 * publicar. Mientras el pipeline corre se van mostrando sus propias líneas de
 * diagnóstico, que es lo que hay que leer para saber si algo salió raro.
 */

const $ = (sel, raiz = document) => raiz.querySelector(sel);
const $$ = (sel, raiz = document) => [...raiz.querySelectorAll(sel)];

const estado = { proyectos: [], abiertos: new Set(), registros: new Map(), sondeos: new Map() };

// --- API ---------------------------------------------------------------------

async function pedir(ruta, opciones = {}) {
  const respuesta = await fetch(ruta, opciones);
  if (respuesta.status === 204) return null;
  const cuerpo = await respuesta.json().catch(() => ({}));
  if (!respuesta.ok) throw new Error(cuerpo.detail ?? `Error ${respuesta.status}`);
  return cuerpo;
}

const json = (datos) => ({
  method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(datos),
});

function avisar(mensaje) {
  const aviso = $('#aviso');
  aviso.textContent = mensaje ?? '';
  aviso.hidden = !mensaje;
}

// --- Lista -------------------------------------------------------------------

async function refrescar() {
  estado.proyectos = await pedir('/api/proyectos');
  pintar();
  // Un trabajo puede seguir corriendo de una recarga de página: retomarlo.
  for (const proyecto of estado.proyectos) {
    if (proyecto.trabajo && !estado.sondeos.has(proyecto.slug)) seguir(proyecto.slug, proyecto.trabajo.id);
  }
}

function pintar() {
  const lista = $('#lista');
  if (!estado.proyectos.length) {
    lista.innerHTML = `<div class="vacio"><strong>Todavía no hay loteos</strong>
      <span>Sube la carpeta del vuelo —el KMZ y las panorámicas— y la consola hace el resto.</span></div>`;
    return;
  }
  lista.replaceChildren(...estado.proyectos.map(tarjeta));
}

function tarjeta(proyecto) {
  const nodo = $('#plantilla-proyecto').content.cloneNode(true).firstElementChild;
  nodo.dataset.slug = proyecto.slug;
  $('.proyecto__nombre', nodo).textContent = proyecto.nombre;
  $('.proyecto__meta', nodo).replaceChildren(...meta(proyecto));

  const enCurso = Boolean(proyecto.trabajo);
  const construir = $('[data-accion="construir"]', nodo);
  construir.textContent = proyecto.construido ? 'Reconstruir' : 'Construir';
  construir.disabled = enCurso;
  const publicar = $('[data-accion="publicar"]', nodo);
  publicar.disabled = enCurso || !proyecto.construido;

  if (proyecto.construido) pintarCifras($('.cifras', nodo), proyecto);
  if (estado.abiertos.has(proyecto.slug)) abrirAjustes(nodo, proyecto);

  const registro = estado.registros.get(proyecto.slug);
  if (registro) {
    const caja = $('.consola-log', nodo);
    caja.hidden = false;
    caja.replaceChildren(...registro.map(linea));
    caja.scrollTop = caja.scrollHeight;
  }
  if (proyecto.calce.length && !enCurso) pintarCalce(nodo, proyecto);

  nodo.addEventListener('click', (evento) => {
    const accion = evento.target.closest('[data-accion]')?.dataset.accion;
    if (accion) manejar(accion, proyecto, nodo);
  });
  return nodo;
}

function meta(proyecto) {
  const partes = [];
  if (proyecto.etapa) partes.push(pastilla(proyecto.etapa));
  partes.push(proyecto.construido
    ? pastilla('Construido', 'ok')
    : pastilla('Sin construir', 'aviso'));
  if (proyecto.trabajo) {
    partes.push(pastilla(proyecto.trabajo.accion === 'publicar' ? 'Publicando…' : 'Construyendo…'));
  } else if (proyecto.construido) {
    const enlace = document.createElement('span');
    enlace.className = 'pastilla pastilla--ok';
    enlace.innerHTML = `<a href="${proyecto.url}" target="_blank" rel="noopener">Ver sitio ↗</a>`;
    partes.push(enlace);
  }
  const fuentes = document.createElement('span');
  fuentes.className = 'ruta';
  const hallado = proyecto.fuentes_encontradas;
  fuentes.textContent = `${hallado.panoramicas} panorámicas · ${hallado.megas} MB`
    + (hallado.planilla ? ` · planilla ${hallado.planilla}` : ' · datos del CRM');
  partes.push(fuentes);
  return partes;
}

function pastilla(texto, tono) {
  const span = document.createElement('span');
  span.className = 'pastilla' + (tono ? ` pastilla--${tono}` : '');
  span.textContent = texto;
  return span;
}

function pintarCifras(lista, proyecto) {
  const { resumen } = proyecto;
  const peorCalce = Math.max(0, ...(resumen.calce ?? []).map((c) => c.error_sol));
  const dato = (rotulo, valor, nota) => {
    const div = document.createElement('div');
    div.innerHTML = `<dt>${rotulo}</dt><dd>${valor}${nota ? `<small>${nota}</small>` : ''}</dd>`;
    return div;
  };
  const porEstado = Object.entries(resumen.por_estado ?? {})
    .map(([clave, cuantas]) => `${cuantas} ${clave.replace('_', ' ')}`).join(' · ');
  lista.replaceChildren(
    dato('Parcelas', resumen.parcelas ?? '—', porEstado),
    dato('Vistas', resumen.vistas ?? '—'),
    dato('Error del sol', `${peorCalce.toFixed(1)}°`, peorCalce > 3 ? 'revisar el rumbo' : 'dentro de lo normal'),
    dato('Construido', fecha(resumen.generado)),
  );
  lista.hidden = false;
}

function fecha(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function pintarCalce(nodo, proyecto) {
  const seccion = $('.calce', nodo);
  $('.calce__tiras', seccion).replaceChildren(...proyecto.calce.map((archivo) => {
    const enlace = document.createElement('a');
    enlace.href = `/calce/${proyecto.slug}/${archivo}`;
    enlace.target = '_blank';
    enlace.rel = 'noopener';
    enlace.innerHTML = `<img src="/calce/${proyecto.slug}/${archivo}" alt="Calce de ${archivo}" loading="lazy">`;
    return enlace;
  }));
  seccion.hidden = false;
}

function linea(texto) {
  const span = document.createElement('span');
  const bajo = texto.toLowerCase();
  if (bajo.includes('aviso') || bajo.includes('revisar')) span.className = 'aviso-linea';
  else if (bajo.includes('error:') || bajo.includes('traceback') || bajo.includes('no pude')) span.className = 'error-linea';
  span.textContent = texto + '\n';
  return span;
}

// --- Acciones ----------------------------------------------------------------

async function manejar(accion, proyecto, nodo) {
  try {
    avisar(null);
    if (accion === 'ajustes') return alternarAjustes(nodo, proyecto);
    if (accion === 'guardar') return await guardar(nodo, proyecto);
    if (accion === 'olvidar') return await olvidar(proyecto);
    if (accion === 'construir' || accion === 'publicar') {
      // Publicar deja el loteo a la vista de cualquiera con el enlace: se confirma.
      if (accion === 'publicar' && !confirm(
        `Publicar "${proyecto.nombre}" en ${proyecto.url}\n\n`
        + 'Queda a la vista de cualquiera con el enlace, con los precios y estados '
        + 'que muestra el control de calce de arriba.')) return;
      estado.registros.set(proyecto.slug, []);
      const cuerpo = accion === 'publicar' ? { confirmado: true } : {};
      const { id } = await pedir(`/api/proyectos/${proyecto.slug}/${accion}`, json(cuerpo));
      await refrescar();
      seguir(proyecto.slug, id);
    }
  } catch (error) {
    avisar(error.message);
  }
}

function alternarAjustes(nodo, proyecto) {
  if (estado.abiertos.has(proyecto.slug)) estado.abiertos.delete(proyecto.slug);
  else estado.abiertos.add(proyecto.slug);
  $('.ajustes', nodo).hidden = !estado.abiertos.has(proyecto.slug);
  if (estado.abiertos.has(proyecto.slug)) abrirAjustes(nodo, proyecto);
}

function abrirAjustes(nodo, proyecto) {
  const form = $('.ajustes', nodo);
  form.hidden = false;
  form.elements.nombre.value = proyecto.nombre ?? '';
  form.elements.etapa.value = proyecto.etapa ?? '';
  form.elements.whatsapp.value = proyecto.whatsapp ?? '';
  form.elements.parcelacion.value = proyecto.parcelacion ?? '';
  form.elements.despegue.value = proyecto.despegue ? proyecto.despegue.join(', ') : '';
  form.elements.referencias.value = (proyecto.referencias ?? [])
    .map((r) => (typeof r === 'string' ? r : r.nombre)).join(', ');
}

async function guardar(nodo, proyecto) {
  const form = $('.ajustes', nodo);
  const lista = (valor) => valor.split(',').map((t) => t.trim()).filter(Boolean);
  const numeros = lista(form.elements.despegue.value).map(Number);
  if (numeros.length && (numeros.length !== 2 || numeros.some(Number.isNaN))) {
    throw new Error('El despegue va como "lon, lat", por ejemplo -72.27591, -35.86774');
  }
  await pedir(`/api/proyectos/${proyecto.slug}`, {
    method: 'PATCH', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      nombre: form.elements.nombre.value.trim() || null,
      etapa: form.elements.etapa.value.trim(),
      whatsapp: form.elements.whatsapp.value.trim(),
      parcelacion: form.elements.parcelacion.value.trim() || null,
      despegue: numeros.length === 2 ? numeros : null,
      referencias: lista(form.elements.referencias.value),
    }),
  });
  estado.abiertos.delete(proyecto.slug);
  await refrescar();
}

async function olvidar(proyecto) {
  if (!confirm(`¿Quitar "${proyecto.nombre}" de la lista? No se borra ningún archivo.`)) return;
  await pedir(`/api/proyectos/${proyecto.slug}`, { method: 'DELETE' });
  estado.abiertos.delete(proyecto.slug);
  estado.registros.delete(proyecto.slug);
  await refrescar();
}

/** Sondea un trabajo y va volcando sus líneas hasta que termina. */
function seguir(slug, identificador) {
  clearTimeout(estado.sondeos.get(slug));
  let desde = (estado.registros.get(slug) ?? []).length;

  const tic = async () => {
    try {
      const trabajo = await pedir(`/api/trabajos/${identificador}?desde=${desde}`);
      if (trabajo.lineas.length) {
        const registro = estado.registros.get(slug) ?? [];
        registro.push(...trabajo.lineas);
        estado.registros.set(slug, registro);
        desde = trabajo.total;
        volcar(slug, registro);
      }
      if (trabajo.terminado) {
        estado.sondeos.delete(slug);
        if (trabajo.estado === 'falló') avisar(`${slug}: el ${trabajo.accion} falló. Mira el detalle abajo.`);
        return refrescar();
      }
    } catch (error) {
      estado.sondeos.delete(slug);
      return avisar(error.message);
    }
    estado.sondeos.set(slug, setTimeout(tic, 600));
  };
  estado.sondeos.set(slug, setTimeout(tic, 100));
}

function volcar(slug, registro) {
  const caja = $(`.proyecto[data-slug="${slug}"] .consola-log`);
  if (!caja) return;
  caja.hidden = false;
  caja.replaceChildren(...registro.map(linea));
  caja.scrollTop = caja.scrollHeight;
}

// --- Alta de un loteo ---------------------------------------------------------

let archivosElegidos = [];

function prepararAlta() {
  const dialogo = $('#alta');
  const soltadero = $('#soltadero');
  const entrada = $('#archivos');

  $('#nuevo').addEventListener('click', () => {
    archivosElegidos = [];
    $('#nombre').value = '';
    $('#ruta').value = '';
    $('#soltadero-texto').textContent = 'Arrastra la carpeta aquí o haz clic para elegirla';
    $('#progreso').hidden = true;
    $('#subir').disabled = true;
    dialogo.showModal();
  });
  $('#cancelar').addEventListener('click', () => dialogo.close());

  entrada.addEventListener('change', () => tomar([...entrada.files].map(
    (archivo) => ({ archivo, ruta: sinRaiz(archivo.webkitRelativePath || archivo.name) }))));

  for (const evento of ['dragenter', 'dragover']) {
    soltadero.addEventListener(evento, (e) => { e.preventDefault(); soltadero.classList.add('soltadero--encima'); });
  }
  for (const evento of ['dragleave', 'drop']) {
    soltadero.addEventListener(evento, () => soltadero.classList.remove('soltadero--encima'));
  }
  soltadero.addEventListener('drop', async (evento) => {
    evento.preventDefault();
    const entradas = [...evento.dataTransfer.items]
      .map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
    const encontrados = [];
    for (const raiz of entradas) await recorrer(raiz, '', encontrados);
    tomar(encontrados);
  });

  $('#subir').addEventListener('click', subir);
  $('#vincular').addEventListener('click', vincular);
}

/** Quita el nombre de la carpeta que se soltó: dentro del proyecto no aporta. */
function sinRaiz(ruta) {
  const partes = ruta.split('/');
  return partes.length > 1 ? partes.slice(1).join('/') : ruta;
}

async function recorrer(entrada, prefijo, encontrados) {
  if (entrada.isFile) {
    const archivo = await new Promise((ok, mal) => entrada.file(ok, mal));
    if (!archivo.name.startsWith('.')) encontrados.push({ archivo, ruta: prefijo + archivo.name });
    return;
  }
  const lector = entrada.createReader();
  for (;;) {
    const tanda = await new Promise((ok, mal) => lector.readEntries(ok, mal));
    if (!tanda.length) return;
    // La raíz que se soltó no cuenta como carpeta: sus hijos van en la primera capa.
    for (const hija of tanda) await recorrer(hija, prefijo ? `${prefijo}${entrada.name}/` : '', encontrados);
  }
}

function tomar(encontrados) {
  const utiles = encontrados.filter(({ ruta }) => /\.(kmz|jpe?g|xlsx|json)$/i.test(ruta));
  archivosElegidos = utiles;
  const megas = utiles.reduce((total, { archivo }) => total + archivo.size, 0) / 1048576;
  const kmz = utiles.filter(({ ruta }) => ruta.toLowerCase().endsWith('.kmz')).length;
  const fotos = utiles.filter(({ ruta }) => /\.jpe?g$/i.test(ruta)).length;
  $('#soltadero-texto').textContent = utiles.length
    ? `${kmz} KMZ · ${fotos} panorámicas · ${megas.toFixed(0)} MB`
    : 'No encontré ni KMZ ni panorámicas en esa carpeta';
  if (!$('#nombre').value && encontrados.length) {
    const raiz = encontrados[0].archivo.webkitRelativePath?.split('/')[0];
    if (raiz) $('#nombre').value = raiz.replace(/[_-]+/g, ' ');
  }
  $('#subir').disabled = !(kmz && fotos);
}

function subir() {
  const nombre = $('#nombre').value.trim();
  if (!nombre) return avisar('Ponle un nombre al loteo.');

  const cuerpo = new FormData();
  cuerpo.append('nombre', nombre);
  for (const { archivo, ruta } of archivosElegidos) cuerpo.append('archivos', archivo, ruta);

  const barra = $('#progreso');
  barra.hidden = false;
  $('#subir').disabled = true;

  // XHR y no fetch: es la única forma de ver el avance de una subida de 200 MB.
  const peticion = new XMLHttpRequest();
  peticion.open('POST', '/api/proyectos');
  peticion.upload.addEventListener('progress', (evento) => {
    if (evento.lengthComputable) $('i', barra).style.width = `${(evento.loaded / evento.total) * 100}%`;
  });
  peticion.addEventListener('load', async () => {
    $('#subir').disabled = false;
    if (peticion.status === 201) { $('#alta').close(); await refrescar(); return; }
    let detalle = `Error ${peticion.status}`;
    try { detalle = JSON.parse(peticion.responseText).detail ?? detalle; } catch { /* sin cuerpo */ }
    avisar(detalle);
  });
  peticion.addEventListener('error', () => { $('#subir').disabled = false; avisar('Se cortó la subida.'); });
  peticion.send(cuerpo);
}

async function vincular() {
  const ruta = $('#ruta').value.trim();
  if (!ruta) return;
  try {
    await pedir('/api/proyectos/vincular', json({ ruta }));
    $('#alta').close();
    await refrescar();
  } catch (error) {
    avisar(error.message);
  }
}

// --- Arranque ------------------------------------------------------------------

// Quién entró, y qué puede hacer. Vincular una carpeta del disco solo tiene
// sentido en el computador donde están las fotos: desplegada, el servidor lo
// rechaza, así que ni se ofrece.
fetch('/api/sesion').then((r) => r.json()).then((sesion) => {
  $('#salir').hidden = false;
  $('#quien').textContent = `${sesion.cliente} · ${sesion.quien}`;
  $('#carpeta-local').hidden = !sesion.puede_vincular;
}).catch(() => { /* sin sesión: la puerta ya redirigió */ });

prepararAlta();
refrescar().catch((error) => avisar(error.message));
