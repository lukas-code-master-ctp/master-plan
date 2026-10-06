/**
 * El detalle de un master: portada, cifras, datos del loteo, construir → revisar
 * el calce → publicar. Mientras el pipeline corre se van mostrando sus propias
 * líneas de diagnóstico, que es lo que hay que leer para saber si algo salió raro.
 */
import {
  $, $$, abrirDialogo, avisar, estado, etapaDe, fecha, json, pastilla, pedir,
} from './comun.js';
import { anotarResultado, manejarCierra, pintarCierra, prepararCierra } from './cierra.js';
import { opcionesDeDiseno } from './disenos.js';
import { abrirElegirKmz } from './kmzs.js';
import { pintarVuelo } from './vuelo.js';
import { comoInventario, pintarInventario, prepararInventario } from './inventario.js';
import { desdeEntrada, esFoto, esKmz, megas, soltadero, subir, UTILES } from './subida.js';
import { textoInterrumpido, trasFalloDeSondeo } from './sondeo.js';

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
  prepararInventario({ alSubir: inventarioSubido });
  prepararCierra({ traido: traidoDeCierra });
}

/**
 * Una planilla nueva: los estados y precios se ponen al día en segundos, sin
 * reconstruir. Solo si trae parcelas que el plano no tiene hace falta construir.
 */
async function inventarioSubido(slug) {
  await refrescar();
  const proyecto = estado.proyectos.find((p) => p.slug === slug);
  if (!proyecto?.construido || proyecto.trabajo) return;
  const respuesta = await pedir(`/api/proyectos/${slug}/inventario/actualizar`, json({}));
  if (respuesta.requiere_reconstruir) await reconstruirDatos(slug, { publicar: false });
  else await refrescar();
}

/**
 * Lo que llegó de Cierra ya quedó al día en el servidor, y si el loteo está en
 * línea y algo cambió, ya se está publicando: acá solo se sigue ese trabajo. Si
 * Cierra trajo lotes que el plano no tiene, se reconstruye (y se publica).
 */
async function traidoDeCierra(slug, respuesta) {
  anotarResultado(slug, respuesta);
  if (respuesta.publicando) {
    estado.registros.set(slug, []);
    estado.trabajos.set(slug, { accion: 'publicar', estado: 'corriendo', terminado: false });
    await refrescar();
    seguir(slug, respuesta.publicando);
    return;
  }
  if (respuesta.requiere_reconstruir) return reconstruirDatos(slug, { publicar: true });
  return refrescar();
}

/** Construir sin generar imágenes; con `publicar`, si ya está en línea, también publica. */
async function reconstruirDatos(slug, { publicar }) {
  await refrescar();
  const proyecto = estado.proyectos.find((p) => p.slug === slug);
  if (proyecto?.construido && !proyecto.trabajo) {
    await lanzar(proyecto, 'construir', { sin_imagenes: true, publicar });
  }
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
  pintarInventario(proyecto);
  pintarCierra(proyecto);
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
    + (hallado.planilla ? ` · planilla ${hallado.planilla}` : proyecto.con_crm ? ' · precios del CRM' : ' · sin planilla');
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
  // Un KMZ de Mis KMZ en vez de subir el archivo. No mientras construye: el servidor
  // no le cambia el KMZ por debajo a una construcción.
  $('[data-accion="usar-kmz"]').disabled = enCurso;
}

function pintarPortada(proyecto) {
  const figura = $('#plano-portada');
  if (!proyecto.construido) {
    figura.className = 'portada portada--vacia';
    figura.innerHTML = '';
    const texto = document.createElement('figcaption');
    texto.textContent = proyecto.fuentes_encontradas.kmz
      ? 'Todavía no está construido. Aprieta Construir para ver el loteo sobre las fotos.'
      : 'Sube el KMZ y las panorámicas del dron para empezar. ¿No tienes el KMZ? Créalo desde el plano aprobado en Mis KMZ y úsalo acá.';
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
  // Ya en línea, lo que más se hace es ir a verlo: ese pasa a ser el botón
  // principal, y volver a publicar queda al lado, en segundo plano.
  const ver = $('#plano-ver-sitio');
  ver.hidden = !proyecto.publicado;
  if (proyecto.publicado) ver.href = proyecto.url;
  boton.classList.toggle('boton--contorno', proyecto.publicado);
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
  opcionesDeDiseno(form.elements.diseno, proyecto.diseno_id);
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
    diseno_id: form.elements.diseno.value || null,
  }, 'PATCH'));
  await refrescar();
  const antes = proyecto.diseno_id ?? null;
  const despues = proyectoActual();
  rellenarAjustes(despues);
  // El diseño, el nombre, la etapa y el WhatsApp se aplican al publicar. La
  // parcelación, el despegue y los hitos cambian el cálculo: esos piden reconstruir.
  const igual = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  const pideReconstruir = !igual(proyecto.parcelacion, despues.parcelacion)
    || !igual(proyecto.despegue, despues.despegue) || !igual(proyecto.referencias, despues.referencias);
  const alPublicar = !igual(antes, despues.diseno_id)
    || ['nombre', 'etapa', 'whatsapp'].some((campo) => !igual(proyecto[campo], despues[campo]));
  let aviso = 'Guardado.';
  if (proyecto.construido && pideReconstruir) aviso = 'Guardado. Reconstruye para que se vea en el sitio.';
  else if (proyecto.construido && alPublicar) {
    aviso = proyecto.publicado ? 'Guardado. Vuelve a publicar para que se vea en el sitio.'
      : 'Guardado. Se aplica al publicar.';
  }
  $('#plano-guardado').textContent = aviso;
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
    if (accion.startsWith('cierra-')) return await manejarCierra(accion, proyecto);
    if (accion === 'archivos') return abrirSubida(proyecto);
    if (accion === 'usar-kmz') return abrirElegirKmz(proyecto);
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
  estado.trabajos.set(proyecto.slug, { accion, estado: 'corriendo', terminado: false });
  const { id, aviso } = await pedir(`/api/proyectos/${proyecto.slug}/${accion}`, json(cuerpo));
  // P. ej. Cierra no contestó: se construye igual, con el último inventario.
  if (aviso) avisar(aviso);
  await refrescar();
  seguir(proyecto.slug, id);
}

/**
 * Quién más quiere enterarse del avance de un trabajo, por clave (`estado.sondeos`):
 * la pantalla de un KMZ muestra en vivo su digitalización (`kmz:<slug>`). Se le
 * avisa con cada tanda de líneas y al terminar.
 */
export const oyentes = new Map();

/**
 * Sondea un trabajo y va volcando sus líneas hasta que termina. `slug` es la clave
 * del trabajo: el slug de un master o `kmz:<slug>` para un KMZ.
 */
export function seguir(slug, identificador) {
  clearTimeout(estado.sondeos.get(slug));
  let desde = (estado.registros.get(slug) ?? []).length;
  let fallos = 0;

  const tic = async () => {
    let trabajo;
    try {
      trabajo = await pedir(`/api/trabajos/${identificador}?desde=${desde}`);
    } catch (error) {
      const decision = trasFalloDeSondeo(error, fallos);
      fallos = decision.fallos;
      if (decision.que === 'reintentar') {
        estado.sondeos.set(slug, setTimeout(tic, decision.espera));
        return;
      }
      estado.sondeos.delete(slug);
      if (decision.que === 'interrumpido') {
        await interrumpido(slug);
      } else {
        avisar(error.message);
      }
      return;
    }
    fallos = 0;
    try {
      estado.trabajos.set(slug, {
        accion: trabajo.accion, estado: trabajo.estado, terminado: trabajo.terminado });
      if (trabajo.lineas.length || trabajo.terminado) {
        const registro = estado.registros.get(slug) ?? [];
        registro.push(...trabajo.lineas);
        estado.registros.set(slug, registro);
        desde = trabajo.total;
        if (slug === actual) pintarRegistro(slug);
        if (!trabajo.terminado) oyentes.get(slug)?.(trabajo);
      }
      if (trabajo.terminado) {
        estado.sondeos.delete(slug);
        oyentes.get(slug)?.(trabajo);
        await refrescar();
        if (trabajo.estado === 'falló') {
          avisar(slug.startsWith('kmz:')
            ? 'La digitalización del plano falló. El detalle está en el registro del paso 3.'
            : `El ${trabajo.accion} de ${slug} falló. El detalle está en el registro.`);
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

/**
 * El trabajo se perdió con el servidor (se reinició y no lo conoce): queda como
 * fallido, con la causa al final del registro (la tarjeta la muestra), y quien lo
 * escuchaba se entera de que terminó, para que vuelva a ofrecer el botón.
 */
async function interrumpido(slug) {
  const previo = estado.trabajos.get(slug) ?? {};
  const texto = textoInterrumpido(slug, previo.accion);
  const registro = estado.registros.get(slug) ?? [];
  registro.push(`Error: ${texto}`);
  estado.registros.set(slug, registro);
  const trabajo = {
    accion: previo.accion, estado: 'falló', terminado: true, interrumpido: true,
    lineas: [], total: registro.length,
  };
  estado.trabajos.set(slug, { accion: trabajo.accion, estado: trabajo.estado, terminado: true });
  // Lo que se sabía del servidor ya no corre: si no contesta (todavía arrancando), los
  // botones no pueden quedar apagados esperando un trabajo que no existe.
  for (const item of [...estado.proyectos, ...estado.kmzs]) {
    if ((item.slug === slug || `kmz:${item.slug}` === slug) && item.trabajo) item.trabajo = null;
  }
  if (slug === actual) pintarPlano(slug);
  oyentes.get(slug)?.(trabajo);
  avisar(texto);
  await refrescar().catch(() => {});
}

function pintarRegistro(slug) {
  const caja = $('#plano-registro');
  const registro = estado.registros.get(slug);
  pintarVuelo(registro, estado.trabajos.get(slug));
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
    // La planilla de la carpeta pasa a ser el inventario: si no, uno subido antes
    // le seguiría ganando. Un CSV solo cuenta si está en la raíz.
    const planilla = elegidos.find(({ ruta }) => (
      /\.xlsx$/i.test(ruta) || /^[^/]+\.csv$/i.test(ruta)) && !ruta.split('/').pop().startsWith('~$'));
    const lista = elegidos.filter((e) => e !== planilla && !/\.csv$/i.test(e.ruta));
    if (planilla) lista.push(comoInventario(planilla));
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
