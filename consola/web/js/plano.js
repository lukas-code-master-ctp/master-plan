/**
 * El detalle de un master: portada, cifras, datos del loteo, construir → revisar
 * el calce → publicar. Mientras el pipeline corre se van mostrando sus propias
 * líneas de diagnóstico, que es lo que hay que leer para saber si algo salió raro.
 */
import {
  $, $$, abrirDialogo, avisar, estado, etapaDe, fecha, json, pastilla, pedir,
} from './comun.js';
import { desdeEntrada, esFoto, esKmz, megas, soltadero, subir, UTILES } from './subida.js';

let refrescar = async () => {};
let actual = null;          // el slug que se está mirando

export function prepararPlano(opciones) {
  refrescar = opciones.refrescar;
  $('#plano').addEventListener('click', (evento) => {
    const accion = evento.target.closest('[data-accion]')?.dataset.accion;
    const proyecto = proyectoActual();
    if (accion && proyecto) manejar(accion, proyecto);
  });
  prepararSubida();
  prepararPago();
}

const proyectoActual = () => estado.proyectos.find((p) => p.slug === actual);

/**
 * Pinta el master. `nuevo` es true al llegar desde otra pantalla; `buscando`,
 * mientras se recarga la lista porque este loteo todavía no estaba en ella.
 */
export function pintarPlano(slug, { nuevo = false, buscando = false } = {}) {
  actual = slug;
  const proyecto = proyectoActual();
  if (!proyecto) {
    $('#plano-nombre').textContent = buscando ? 'Cargando…' : 'Este loteo no existe';
    $('#plano-meta').replaceChildren();
    $('#plano').classList.add('plano-detalle--vacio');
    return;
  }
  $('#plano').classList.remove('plano-detalle--vacio');
  document.title = `${proyecto.nombre} — Tu Masterplan`;
  $('#plano-nombre').textContent = proyecto.nombre;
  $('#plano-meta').replaceChildren(...meta(proyecto));
  pintarAcciones(proyecto);
  pintarPortada(proyecto);
  pintarCifras(proyecto);
  pintarRegistro(slug);
  pintarCalce(proyecto);
  pintarPublicar(proyecto);
  // Los datos se rellenan al llegar, no en cada refresco: pisarían lo que la
  // persona está escribiendo mientras corre una construcción.
  if (nuevo) rellenarAjustes(proyecto);
  if (proyecto.trabajo && !estado.sondeos.has(slug)) seguir(slug, proyecto.trabajo.id);
}

function meta(proyecto) {
  const partes = [];
  if (proyecto.etapa) partes.push(pastilla(proyecto.etapa));
  // Sin teléfono el visor esconde el botón de contacto: el comprador mira, se
  // decide y no tiene a quién escribirle. Se avisa antes de publicar, no después.
  if (proyecto.sin_contacto) partes.push(pastilla('Sin contacto', 'aviso'));
  partes.push(etapaDe(proyecto));
  if (proyecto.publicado) {
    const enlace = document.createElement('a');
    enlace.className = 'pastilla pastilla--enlace';
    enlace.href = proyecto.url;
    enlace.target = '_blank';
    enlace.rel = 'noopener';
    enlace.textContent = 'Ver sitio ↗';
    partes.push(enlace);
  }
  const hallado = proyecto.fuentes_encontradas;
  const fuentes = document.createElement('span');
  fuentes.className = 'ruta';
  fuentes.textContent = `${hallado.panoramicas} panorámicas · ${hallado.megas} MB`
    + (hallado.planilla ? ` · planilla ${hallado.planilla}` : ' · sin planilla');
  partes.push(fuentes);
  return partes;
}

function pintarAcciones(proyecto) {
  const enCurso = Boolean(proyecto.trabajo);
  const conFuentes = Boolean(proyecto.fuentes_encontradas.kmz);
  const construir = $('[data-accion="construir"]');
  construir.textContent = proyecto.construido ? 'Reconstruir' : 'Construir';
  // Sin vuelo no hay nada que construir: ofrecer el botón sería prometer algo que falla.
  construir.disabled = enCurso || !conFuentes;
  construir.className = conFuentes && !proyecto.construido ? 'boton' : 'boton boton--contorno';
  const archivos = $('[data-accion="archivos"]');
  archivos.textContent = conFuentes ? 'Subir archivos' : 'Subir el vuelo';
  archivos.className = conFuentes ? 'boton boton--contorno' : 'boton';
  archivos.disabled = enCurso;
}

function pintarPortada(proyecto) {
  const figura = $('#plano-portada');
  if (!proyecto.construido) {
    figura.className = 'portada portada--vacia';
    figura.innerHTML = '';
    const texto = document.createElement('figcaption');
    texto.textContent = proyecto.fuentes_encontradas.kmz
      ? 'Todavía no está construido. Aprieta Construir para ver el loteo sobre las fotos.'
      : 'Sube el KMZ y las panorámicas del dron para empezar.';
    figura.append(texto);
    return;
  }
  const src = `/api/proyectos/${proyecto.slug}/portada?v=${encodeURIComponent(proyecto.resumen.generado ?? '')}`;
  if (figura.querySelector('img')?.getAttribute('src') === src) return;
  figura.className = 'portada';
  const imagen = document.createElement('img');
  imagen.src = src;
  imagen.alt = `El loteo ${proyecto.nombre} visto desde el dron`;
  imagen.width = 1280;
  imagen.height = 720;
  imagen.addEventListener('error', () => { figura.className = 'portada portada--vacia'; imagen.remove(); });
  figura.replaceChildren(imagen);
}

function pintarCifras(proyecto) {
  const lista = $('#plano-cifras');
  if (!proyecto.construido) { lista.hidden = true; return; }
  const { resumen } = proyecto;
  const peorCalce = Math.max(0, ...(resumen.calce ?? []).map((c) => c.error_sol));
  const dato = (rotulo, valor, nota) => {
    const div = document.createElement('div');
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    dt.textContent = rotulo;
    dd.textContent = valor;
    if (nota) {
      const small = document.createElement('small');
      small.textContent = nota;
      dd.append(small);
    }
    div.append(dt, dd);
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

function pintarCalce(proyecto) {
  const seccion = $('#plano-calce');
  if (!proyecto.calce.length || proyecto.trabajo) { seccion.hidden = true; return; }
  $('.calce__tiras', seccion).replaceChildren(...proyecto.calce.map((archivo) => {
    const enlace = document.createElement('a');
    enlace.href = `/calce/${proyecto.slug}/${archivo}`;
    enlace.target = '_blank';
    enlace.rel = 'noopener';
    const imagen = document.createElement('img');
    imagen.src = enlace.href;
    imagen.alt = `Control de calce de la vista ${archivo.replace('.jpg', '')}`;
    imagen.loading = 'lazy';
    enlace.append(imagen);
    return enlace;
  }));
  seccion.hidden = false;
}

function pintarPublicar(proyecto) {
  const boton = $('[data-accion="publicar"]');
  const nota = $('#plano-publicar-nota');
  const pago = $('[data-accion="pago"]');
  const equipo = estado.sesion?.rol === 'plataforma';
  boton.textContent = proyecto.publicado ? 'Volver a publicar' : 'Publicar';
  boton.disabled = Boolean(proyecto.trabajo) || !proyecto.construido || !proyecto.pagado;
  pago.hidden = !(equipo && !proyecto.pagado);

  if (!proyecto.pagado) {
    nota.textContent = 'Puedes construir y revisar cuantas veces quieras. Para publicarlo, '
      + 'escríbenos y lo habilitamos.';
  } else if (!proyecto.construido) {
    nota.textContent = 'Se publica una vez construido y revisado el control de calce.';
  } else if (proyecto.publicado) {
    nota.textContent = `Publicado en ${proyecto.url}`;
  } else {
    nota.textContent = `Va a quedar en ${proyecto.url}`;
  }
}

// --- Datos del loteo ---------------------------------------------------------

function rellenarAjustes(proyecto) {
  const form = $('#plano-ajustes');
  form.elements.nombre.value = proyecto.nombre ?? '';
  form.elements.etapa.value = proyecto.etapa ?? '';
  form.elements.whatsapp.value = proyecto.whatsapp ?? '';
  form.elements.parcelacion.value = proyecto.parcelacion ?? '';
  // Vacío es "el nombre en mayúsculas": se muestra como sugerencia, no como valor.
  form.elements.parcelacion.placeholder = (proyecto.nombre ?? '').toUpperCase();
  form.elements.despegue.value = proyecto.despegue ? proyecto.despegue.join(', ') : '';
  form.elements.referencias.value = (proyecto.referencias ?? [])
    .map((r) => (typeof r === 'string' ? r : r.nombre)).join(', ');
  $('#plano-guardado').textContent = '';
}

async function guardar(proyecto) {
  const form = $('#plano-ajustes');
  const lista = (valor) => valor.split(',').map((t) => t.trim()).filter(Boolean);
  const numeros = lista(form.elements.despegue.value).map(Number);
  if (numeros.length && (numeros.length !== 2 || numeros.some(Number.isNaN))) {
    throw new Error('El despegue va como "lon, lat", por ejemplo -72.27591, -35.86774');
  }
  await pedir(`/api/proyectos/${proyecto.slug}`, json({
    nombre: form.elements.nombre.value.trim() || null,
    etapa: form.elements.etapa.value.trim(),
    whatsapp: form.elements.whatsapp.value.trim(),
    parcelacion: form.elements.parcelacion.value.trim(),
    despegue: numeros.length === 2 ? numeros : null,
    referencias: lista(form.elements.referencias.value),
  }, 'PATCH'));
  await refrescar();
  rellenarAjustes(proyectoActual());
  $('#plano-guardado').textContent = proyecto.construido
    ? 'Guardado. Reconstruye para que se vea en el sitio.' : 'Guardado.';
}

async function olvidar(proyecto) {
  // Uno subido y sin pagar se borra entero: si no, quitarlo sería la forma de
  // saltarse el tope de masters sin pagar. Hay que decirlo antes.
  const borra = proyecto.subido && !proyecto.pagado;
  if (!confirm(borra
    ? `¿Quitar "${proyecto.nombre}"? Se borran también el vuelo subido y lo construido. No se puede deshacer.`
    : `¿Quitar "${proyecto.nombre}" de la lista? No se borra ningún archivo.`)) return;
  await pedir(`/api/proyectos/${proyecto.slug}`, { method: 'DELETE' });
  estado.registros.delete(proyecto.slug);
  location.hash = '#/planos';
  await refrescar();
}

// --- Acciones ----------------------------------------------------------------

async function manejar(accion, proyecto) {
  try {
    avisar(null);
    if (accion === 'archivos') return abrirSubida(proyecto);
    if (accion === 'guardar') return await guardar(proyecto);
    if (accion === 'olvidar') return await olvidar(proyecto);
    if (accion === 'pago') return abrirPago(proyecto);
    if (accion === 'construir') return await lanzar(proyecto, 'construir', {});
    if (accion === 'publicar') {
      // Publicar deja el loteo a la vista de cualquiera con el enlace: se confirma.
      if (!confirm(
        `Publicar "${proyecto.nombre}" en ${proyecto.url}\n\n`
        + 'Queda a la vista de cualquiera con el enlace, con los precios y estados '
        + 'que muestra el control de calce.'
        + (proyecto.sin_contacto
          ? '\n\nOJO: este loteo no tiene WhatsApp. El visor esconde el botón de '
            + 'contacto, así que el comprador no va a tener a quién escribirle. '
            + 'Ponlo en los datos antes de publicar.'
          : ''))) return;
      return await lanzar(proyecto, 'publicar', { confirmado: true });
    }
  } catch (error) {
    avisar(error.message);
  }
}

async function lanzar(proyecto, accion, cuerpo) {
  estado.registros.set(proyecto.slug, []);
  const { id } = await pedir(`/api/proyectos/${proyecto.slug}/${accion}`, json(cuerpo));
  await refrescar();
  seguir(proyecto.slug, id);
}

/** Sondea un trabajo y va volcando sus líneas hasta que termina. */
export function seguir(slug, identificador) {
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
        if (slug === actual) pintarRegistro(slug);
      }
      if (trabajo.terminado) {
        estado.sondeos.delete(slug);
        await refrescar();
        if (trabajo.estado === 'falló') {
          avisar(`El ${trabajo.accion} de ${slug} falló. El detalle está en el registro.`);
        }
        return;
      }
    } catch (error) {
      estado.sondeos.delete(slug);
      avisar(error.message);
      return;
    }
    estado.sondeos.set(slug, setTimeout(tic, 600));
  };
  estado.sondeos.set(slug, setTimeout(tic, 100));
}

function pintarRegistro(slug) {
  const caja = $('#plano-registro');
  const registro = estado.registros.get(slug);
  caja.hidden = !registro?.length;
  if (!registro?.length) return;
  caja.replaceChildren(...registro.map(linea));
  caja.scrollTop = caja.scrollHeight;
}

function linea(texto) {
  const span = document.createElement('span');
  const bajo = texto.toLowerCase();
  if (bajo.includes('aviso') || bajo.includes('revisar')) span.className = 'aviso-linea';
  else if (bajo.includes('error:') || bajo.includes('traceback') || bajo.includes('no pude')) span.className = 'error-linea';
  span.textContent = texto + '\n';
  return span;
}

// --- Subir más archivos --------------------------------------------------------

let elegidos = [];

function abrirSubida(proyecto) {
  elegidos = [];
  $('#alta-loteo').textContent = `Loteo: ${proyecto.nombre}`;
  $('#soltadero-texto').textContent = 'Arrastra la carpeta aquí o haz clic para elegirla';
  $('#progreso').hidden = true;
  $('#subir').disabled = true;
  abrirDialogo($('#alta'));
}

function prepararSubida() {
  const tomar = (encontrados) => {
    elegidos = encontrados.filter(({ ruta }) => UTILES.test(ruta));
    const kmz = elegidos.filter(({ ruta }) => esKmz(ruta)).length;
    const fotos = elegidos.filter(({ ruta }) => esFoto(ruta)).length;
    $('#soltadero-texto').textContent = elegidos.length
      ? `${kmz} KMZ · ${fotos} panorámicas · ${megas(elegidos).toFixed(0)} MB`
      : 'No encontré ni KMZ, ni panorámicas, ni planilla en esa carpeta';
    $('#subir').disabled = !elegidos.length;
  };
  $('#archivos').addEventListener('change', (e) => tomar(desdeEntrada(e.target)));
  soltadero($('#soltadero'), tomar);

  $('#subir').addEventListener('click', async () => {
    const barra = $('#progreso');
    barra.hidden = false;
    $('#subir').disabled = true;
    // Un CSV suelto solo se toma como inventario con el nombre que busca el pipeline.
    const lista = elegidos.map(({ archivo, ruta }) => (
      /\.csv$/i.test(ruta) ? { archivo, ruta: 'inventario.csv' } : { archivo, ruta }));
    try {
      await subir(actual, lista, (fraccion) => { $('i', barra).style.width = `${fraccion * 100}%`; });
      $('#alta').close();
      await refrescar();
    } catch (error) {
      avisar(error.message);
    } finally {
      $('#subir').disabled = false;
    }
  });
}

// --- Anotar el pago (equipo) ------------------------------------------------------

function abrirPago(proyecto) {
  $('#pago-loteo').textContent = `Loteo: ${proyecto.nombre}`;
  $('#pago-cobro').value = '';
  abrirDialogo($('#pago'));
}

function prepararPago() {
  $('#pago-listo').addEventListener('click', async () => {
    const cobro = $('#pago-cobro').value.trim();
    if (!cobro) return avisar('Anota cómo se pagó: es el único registro del cobro.');
    try {
      await pedir(`/api/plataforma/proyectos/${actual}/pago`, json({ nota_cobro: cobro }));
      $('#pago').close();
      await refrescar();
    } catch (error) { avisar(error.message); }
  });
}

export const cerrarDialogos = () => $$('dialog[open]').forEach((d) => d.close());
