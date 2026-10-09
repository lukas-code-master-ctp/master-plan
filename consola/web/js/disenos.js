/**
 * Mis diseños: la lista y el editor, con una vista previa que usa el mismo
 * código que aplica la marca en el sitio publicado (`marca.js`, del visor).
 */
import { $, avisar, estado, fotoDeFondo, json, pedir } from './comun.js';
import { aplicarMarca, paleta, TEXTOS_POR_DEFECTO } from './marca.js';

const POR_DEFECTO = '#27272a';
// Colores para elegir de un toque: tinta, y tonos sobrios que se leen bien con
// texto blanco y sobre la foto del campo. El selector sigue para cualquier otro.
const COLORES_RAPIDOS = [
  ['#27272a', 'Tinta'], ['#166534', 'Bosque'], ['#0f766e', 'Petróleo'], ['#1d4ed8', 'Azul'],
  ['#6d28d9', 'Ciruela'], ['#9f1239', 'Burdeo'], ['#b45309', 'Terracota'], ['#a16207', 'Trigo'],
];
const ICONO_MAS = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
const BRUJULA = `<svg viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M16 4v6M16 22v6M4 16h6M22 16h6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
  <path d="M16 10.5 21.5 16 16 21.5 10.5 16Z" fill="currentColor"/></svg>`;

const portadaDe = (slug) => (slug ? `/api/proyectos/${slug}/portada` : null);
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
  $('#diseno-colores').replaceChildren(...COLORES_RAPIDOS.map(([hex, nombre]) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'muestra-color';
    boton.style.setProperty('--muestra', hex);
    boton.title = nombre;
    boton.setAttribute('aria-label', `Color ${nombre}`);
    boton.addEventListener('click', () => {
      $('#diseno-color').value = hex;
      $('#diseno-hex').value = hex;
      pintarPrevia();
    });
    return boton;
  }));
  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    await guardar();
  });
}

// --- La lista --------------------------------------------------------------------

/**
 * Una tarjeta por diseño con su muestra: el sitio en chico, con la marca puesta
 * sobre la foto de uno de tus loteos. Al final, la invitación a crear otro.
 */
export function pintarDisenos({ animar = false } = {}) {
  const lista = $('#disenos');
  lista.classList.toggle('disenos--entrando', animar && !matchMedia('(prefers-reduced-motion: reduce)').matches);
  lista.replaceChildren(...estado.disenos.map(tarjetaDeDiseno), tarjetaNueva(estado.disenos.length));
  [...lista.children].forEach((item, i) => item.style.setProperty('--orden', i));
}

function tarjetaDeDiseno(diseno) {
  const item = document.createElement('li');
  const enlace = document.createElement('a');
  enlace.className = 'diseno';
  enlace.href = `#/disenos/${diseno.id}`;

  const vista = document.createElement('span');
  vista.className = 'diseno__vista';
  // La marca solo sobre la muestra: el resto de la tarjeta sigue con la letra de la consola.
  aplicarMarca(vista, diseno);
  const foto = portadaDe(fotoDeFondo(estado.proyectos, diseno.id));
  if (foto) vista.style.backgroundImage = `url("${foto}")`;
  const isla = document.createElement('span');
  isla.className = 'diseno__isla';
  if (diseno.logo) {
    const logo = document.createElement('img');
    logo.src = `/api/disenos/${diseno.id}/logo`;
    logo.alt = '';
    isla.append(logo);
  } else {
    isla.insertAdjacentHTML('beforeend', `<span class="diseno__hito">${BRUJULA}</span>`);
  }
  const titulo = document.createElement('strong');
  titulo.textContent = diseno.nombre;
  isla.append(titulo);
  const boton = document.createElement('span');
  boton.className = 'diseno__boton';
  boton.textContent = diseno.texto_pago || 'Comprar';
  vista.append(isla, boton);

  const pie = document.createElement('span');
  pie.className = 'diseno__pie';
  const nombre = document.createElement('strong');
  nombre.className = 'diseno__nombre';
  nombre.textContent = diseno.nombre;
  const usos = estado.proyectos.filter((p) => p.diseno_id === diseno.id).length;
  const detalle = document.createElement('span');
  detalle.className = 'diseno__usos';
  detalle.textContent = usos ? `${usos} ${usos === 1 ? 'loteo' : 'loteos'}` : 'Sin usar todavía';
  const color = document.createElement('span');
  color.className = 'diseno__color';
  color.style.setProperty('--muestra', paleta(diseno.color)['--marca-700']);
  color.textContent = diseno.color;
  pie.append(nombre, detalle, color);

  enlace.append(vista, pie);
  item.append(enlace);
  return item;
}

/** La última tarjeta invita a crear otro diseño; sin ninguno, cuenta qué pasa sin él. */
function tarjetaNueva(cantidad) {
  const item = document.createElement('li');
  item.innerHTML = `
    <a class="diseno diseno--nuevo" href="#/disenos/nuevo">
      <span class="diseno__nuevo-icono"><span class="plano-nuevo__orbita"></span>${ICONO_MAS}</span>
      <strong>${cantidad ? 'Nuevo diseño' : 'Crea tu primer diseño'}</strong>
      <span>${cantidad ? 'Tu logo, tu color y tu letra en los sitios que publiques.'
        : 'Sin uno, tus loteos se publican con el diseño de Tu Masterplan.'}</span>
    </a>`;
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
  form.elements.tipografia.value = diseno?.tipografia ?? 'jakarta';
  // La foto de la vista previa: un loteo con este diseño o cualquiera construido.
  const foto = portadaDe(fotoDeFondo(estado.proyectos, diseno?.id ?? null));
  $('.previa__foto').style.backgroundImage = foto ? `url("${foto}")` : '';
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
    tipografia: form.elements.tipografia.value || 'jakarta',
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
  $('#previa-titulo').textContent = datos.nombre || 'Tu loteo';
  // El color elegido, marcado entre los rápidos si es uno de ellos.
  for (const boton of $('#diseno-colores').children) {
    boton.setAttribute('aria-pressed', String(boton.style.getPropertyValue('--muestra') === datos.color));
  }

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

