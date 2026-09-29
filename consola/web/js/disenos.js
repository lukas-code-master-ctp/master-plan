/**
 * Mis diseños: la lista y el editor, con una vista previa que usa el mismo
 * código que aplica la marca en el sitio publicado (`marca.js`, del visor).
 */
import { $, avisar, estado, json, pedir } from './comun.js';
import { aplicarMarca, paleta, TEXTOS_POR_DEFECTO } from './marca.js';

const POR_DEFECTO = '#27272a';
let refrescar = async () => {};
let actual = null;          // el id del diseño en edición, o null si es nuevo
let logoElegido = null;     // un archivo elegido y todavía sin subir
let urlDePrevia = null;

export function prepararDisenos(opciones) {
  refrescar = opciones.refrescar;
  const form = $('#diseno-form');

  form.addEventListener('input', pintarPrevia);
  $('#diseno-color').addEventListener('input', () => {
    $('#diseno-hex').value = $('#diseno-color').value;
    pintarPrevia();
  });
  $('#diseno-hex').addEventListener('input', () => {
    const hex = $('#diseno-hex').value.trim();
    if (/^#[0-9a-f]{6}$/i.test(hex)) $('#diseno-color').value = hex.toLowerCase();
    pintarPrevia();
  });
  $('#diseno-logo').addEventListener('change', (evento) => {
    [logoElegido] = evento.target.files;
    pintarLogo();
  });
  $('#diseno-quitar-logo').addEventListener('click', quitarLogo);
  $('#diseno-borrar').addEventListener('click', borrar);
  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    await guardar();
  });
}

// --- La lista --------------------------------------------------------------------

export function pintarDisenos() {
  const lista = $('#disenos');
  if (!estado.disenos.length) {
    lista.innerHTML = `<li class="vacio"><strong>Todavía no tienes diseños</strong>
      <span>Sin uno, tus loteos se publican con el diseño de Tu Masterplan. Crea el tuyo
      con <b>Nuevo diseño</b>.</span></li>`;
    return;
  }
  lista.replaceChildren(...estado.disenos.map(filaDeDiseno));
}

function filaDeDiseno(diseno) {
  const item = document.createElement('li');
  const enlace = document.createElement('a');
  enlace.className = 'diseno';
  enlace.href = `#/disenos/${diseno.id}`;

  const muestra = document.createElement('span');
  muestra.className = 'diseno__muestra';
  // El color va siempre a la vista: de fondo sin logo, como franja con logo.
  muestra.style.setProperty('--muestra', paleta(diseno.color)['--marca-700']);
  if (diseno.logo) {
    const logo = document.createElement('img');
    logo.src = `/api/disenos/${diseno.id}/logo`;
    logo.alt = '';
    muestra.append(logo);
  }

  const nombre = document.createElement('span');
  nombre.className = 'diseno__nombre';
  nombre.textContent = diseno.nombre;

  const usos = estado.proyectos.filter((p) => p.diseno_id === diseno.id).length;
  const detalle = document.createElement('span');
  detalle.className = 'diseno__usos';
  detalle.textContent = usos ? `${usos} ${usos === 1 ? 'loteo' : 'loteos'}` : 'sin usar';

  const lapiz = document.createElement('span');
  lapiz.className = 'diseno__editar';
  lapiz.setAttribute('aria-hidden', 'true');
  lapiz.innerHTML = '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16v4Zm11-15 4 4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/></svg>';

  enlace.append(muestra, nombre, detalle, lapiz);
  item.append(enlace);
  return item;
}

/** Las opciones de un `<select>` de diseño, con el por defecto primero. */
export function opcionesDeDiseno(select, elegido) {
  const opciones = [{ id: '', nombre: 'Tu Masterplan (por defecto)' }, ...estado.disenos];
  select.replaceChildren(...opciones.map((d) => {
    const opcion = document.createElement('option');
    opcion.value = d.id;
    opcion.textContent = d.nombre;
    return opcion;
  }));
  select.value = elegido ?? '';
}

// --- El editor -------------------------------------------------------------------

/** Abre el editor con un diseño, o vacío para uno nuevo. Devuelve false si no existe. */
export function abrirDiseno(id) {
  const diseno = id === 'nuevo' ? null : estado.disenos.find((d) => String(d.id) === String(id));
  if (id !== 'nuevo' && !diseno) {
    $('#diseno-titulo').textContent = 'Este diseño no existe';
    return false;
  }
  actual = diseno?.id ?? null;
  logoElegido = null;
  const form = $('#diseno-form');
  form.reset();
  $('#diseno-titulo').textContent = diseno ? diseno.nombre : 'Nuevo diseño';
  form.elements.nombre.value = diseno?.nombre ?? '';
  $('#diseno-color').value = diseno?.color ?? POR_DEFECTO;
  $('#diseno-hex').value = diseno?.color ?? POR_DEFECTO;
  $('#diseno-tipografia').value = diseno?.tipografia ?? 'jakarta';
  form.elements.texto_contacto.value = diseno?.texto_contacto ?? '';
  form.elements.texto_pago.value = diseno?.texto_pago ?? '';
  $('#diseno-borrar').hidden = !diseno;
  pintarLogo();
  pintarPrevia();
  form.elements.nombre.focus();
  return true;
}

function datosDelFormulario() {
  const form = $('#diseno-form');
  return {
    nombre: form.elements.nombre.value.trim(),
    color: $('#diseno-hex').value.trim().toLowerCase(),
    tipografia: $('#diseno-tipografia').value,
    texto_contacto: form.elements.texto_contacto.value.trim(),
    texto_pago: form.elements.texto_pago.value.trim(),
  };
}

function pintarPrevia() {
  const datos = datosDelFormulario();
  const previa = $('#diseno-previa');
  const valido = /^#[0-9a-f]{6}$/i.test(datos.color);
  aplicarMarca(previa, { color: valido ? datos.color : POR_DEFECTO, tipografia: datos.tipografia });
  $('#previa-contacto').textContent = datos.texto_contacto || TEXTOS_POR_DEFECTO.contacto;
  $('#previa-pago').textContent = datos.texto_pago || 'Comprar';

  // Un color muy claro no lleva texto blanco encima: el botón se oscurece solo.
  // Se avisa, para que no sorprenda el tono publicado.
  const nota = $('#diseno-color-nota');
  if (!valido) nota.textContent = 'El color va como #RRGGBB.';
  else if (paleta(datos.color)['--marca-700'] !== datos.color) {
    nota.textContent = 'En los botones se oscurece un poco para que el texto se lea.';
  } else nota.textContent = '';
}

function pintarLogo() {
  const diseno = estado.disenos.find((d) => d.id === actual);
  const conLogo = Boolean(logoElegido) || Boolean(diseno?.logo);
  $('#texto-logo').textContent = logoElegido ? logoElegido.name
    : diseno?.logo ? 'Cambiar el logo' : 'Subir el logo (PNG, JPG, WebP o SVG)';
  $('#caja-logo').classList.toggle('archivo--lleno', Boolean(logoElegido));
  $('#diseno-quitar-logo').hidden = !diseno?.logo || Boolean(logoElegido);

  if (urlDePrevia) URL.revokeObjectURL(urlDePrevia);
  urlDePrevia = logoElegido ? URL.createObjectURL(logoElegido) : null;
  const marca = $('#previa-marca');
  const src = urlDePrevia ?? (diseno?.logo ? `/api/disenos/${diseno.id}/logo?v=${Date.now()}` : null);
  marca.classList.toggle('previa__marca--logo', conLogo);
  const imagen = marca.querySelector('img') ?? document.createElement('img');
  if (src) {
    imagen.src = src;
    imagen.alt = 'Logo';
    marca.append(imagen);
  } else {
    imagen.remove();
  }
}

async function guardar() {
  avisar(null);
  const datos = datosDelFormulario();
  if (!datos.nombre) {
    avisar('Ponle un nombre al diseño.');
    return $('#diseno-form').elements.nombre.focus();
  }
  const boton = $('#diseno-guardar');
  boton.disabled = true;
  try {
    const guardado = actual
      ? await pedir(`/api/disenos/${actual}`, json(datos, 'PATCH'))
      : await pedir('/api/disenos', json(datos));
    actual = guardado.id;
    if (logoElegido) {
      const cuerpo = new FormData();
      cuerpo.append('archivo', logoElegido, logoElegido.name);
      try {
        await pedir(`/api/disenos/${guardado.id}/logo`, { method: 'POST', body: cuerpo });
      } catch (error) {
        // El diseño quedó guardado; lo que falló es el logo. Se sigue en el
        // editor para que pueda elegir otro sin perder lo demás.
        await refrescar();
        location.hash = `#/disenos/${guardado.id}`;
        avisar(`${error.message}. El resto del diseño quedó guardado.`);
        return;
      }
    }
    await refrescar();
    location.hash = '#/disenos';
  } catch (error) {
    avisar(error.message);
  } finally {
    boton.disabled = false;
  }
}

async function quitarLogo() {
  try {
    await pedir(`/api/disenos/${actual}/logo`, { method: 'DELETE' });
    await refrescar();
    pintarLogo();
  } catch (error) { avisar(error.message); }
}

async function borrar() {
  const diseno = estado.disenos.find((d) => d.id === actual);
  const usos = estado.proyectos.filter((p) => p.diseno_id === actual).length;
  const aviso = usos === 1
    ? '\n\nUn loteo lo usa: vuelve al diseño de Tu Masterplan la próxima vez que se publique.'
    : usos ? `\n\n${usos} loteos lo usan: vuelven al diseño de Tu Masterplan la próxima vez que se publiquen.`
      : '';
  if (!confirm(`¿Borrar "${diseno?.nombre}"?${aviso}`)) return;
  try {
    await pedir(`/api/disenos/${actual}`, { method: 'DELETE' });
    await refrescar();
    location.hash = '#/disenos';
  } catch (error) { avisar(error.message); }
}

