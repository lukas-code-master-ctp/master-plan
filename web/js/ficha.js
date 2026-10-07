/**
 * Ficha comercial de una parcela, como la pantalla "Ficha de Parcela" de Stitch.
 *
 * En el teléfono es un panel que sube desde abajo y se cierra arrastrándolo; en
 * escritorio, una tarjeta flotante. Lo que dice y en qué orden lo ofrece sale de
 * funciones puras (formatos, tarjetas, financiamiento, acciones, KML) que se
 * prueban sin navegador. Lo que depende de columnas opcionales de la planilla
 * (topografía, rol, pie, cuotas, reserva) no se dibuja vacío: si no viene, no está.
 */
import { TEXTOS_POR_DEFECTO } from './marca.js';
import { conReservas } from './reserva.js';

const NUMERO = new Intl.NumberFormat('es-CL');
const HECTAREAS = new Intl.NumberFormat('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const M2_POR_HECTAREA = 10000;

// Un tercio del panel, o un tirón de más de medio píxel por milisegundo: lo que
// se siente como "lo bajé a propósito". Bajo 24 px es el dedo que tembló.
const FRACCION_PARA_BAJAR = 1 / 3;
const VELOCIDAD_PARA_BAJAR = 0.5;
const ARRASTRE_MINIMO = 24;
// Un toque en el asa (sin arrastrar) alterna entre media altura y entero.
const TOQUE_MAXIMO_PX = 6;
const TOQUE_MAXIMO_MS = 300;

const TRAZO = 'fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"';
const ICONOS = {
  superficie: `<path d="M3.5 3.5v13h13Z M3.5 9.5l7 7 M6.5 13.5h3" ${TRAZO}/>`,
  servidumbre: `<path d="M10 17.5v-6.5L5 6 M10 11l5-5 M5 6V3.5 M5 6h2.5 M15 6V3.5 M15 6h-2.5" ${TRAZO}/>`,
  aire: `<ellipse cx="10" cy="10" rx="8" ry="3.4" ${TRAZO}/><path d="M14.5 5.2A8 8 0 0 0 10 3.5c-2.2 0-4 2.9-4 6.5s1.8 6.5 4 6.5 M12.6 14.6l1.9 1.9-1.9 1.9" ${TRAZO}/>`,
  topografia: `<path d="M1.5 16.5 7 8l3.5 5 2.5-3.5 5.5 7Z" ${TRAZO}/>`,
  rol: `<path d="M10 2.5 16 5v4.5c0 4-2.6 6.8-6 8-3.4-1.2-6-4-6-8V5Z M7.3 10l1.9 1.9 3.6-3.8" ${TRAZO}/>`,
  pago: `<rect x="4" y="9" width="12" height="8.5" rx="1.5" ${TRAZO}/><path d="M6.5 9V6.5a3.5 3.5 0 0 1 7 0V9" ${TRAZO}/>`,
  deslindes: `<path d="M2.5 5 7.5 3l5 2 5-2v12l-5 2-5-2-5 2Z M7.5 3v12 M12.5 5v12" ${TRAZO}/>`,
  enlace: `<path d="M8.5 11.5a3 3 0 0 0 4.2 0l2.6-2.6a3 3 0 0 0-4.2-4.2l-.8.8 M11.5 8.5a3 3 0 0 0-4.2 0l-2.6 2.6a3 3 0 0 0 4.2 4.2l.8-.8" ${TRAZO}/>`,
  compartir: `<circle cx="14.5" cy="4.5" r="2" ${TRAZO}/><circle cx="5.5" cy="10" r="2" ${TRAZO}/><circle cx="14.5" cy="15.5" r="2" ${TRAZO}/><path d="m7.3 9 5.4-3.4 M7.3 11l5.4 3.4" ${TRAZO}/>`,
  // El logo de WhatsApp: el botón tiene su color y su marca, como en el diseño.
  contacto: '<path fill="currentColor" d="M10 1.7a8.3 8.3 0 0 0-7.2 12.4L1.7 18.3l4.3-1.1A8.3 8.3 0 1 0 10 1.7Zm0 15.1a6.8 6.8 0 0 1-3.5-1l-.3-.1-2.5.6.7-2.4-.2-.3A6.8 6.8 0 1 1 10 16.8Zm3.7-5.1c-.2-.1-1.2-.6-1.4-.7-.2-.1-.3-.1-.5.1l-.6.8c-.1.1-.2.2-.4.1a5.6 5.6 0 0 1-2.8-2.4c-.2-.4.2-.3.6-1.1.1-.1 0-.3 0-.4l-.6-1.5c-.2-.4-.3-.3-.5-.3h-.4a.8.8 0 0 0-.6.3 2.4 2.4 0 0 0-.7 1.8 4.2 4.2 0 0 0 .9 2.2 9.5 9.5 0 0 0 3.6 3.2c1.4.6 1.9.6 2.6.5.4-.1 1.2-.5 1.4-1 .2-.5.2-.9.1-1l-.3-.2Z"/>',
};

// El archivo de deslindes de la ficha abierta; se suelta al abrir otra.
let urlKml = null;

const icono = (nombre) => `<svg viewBox="0 0 20 20" aria-hidden="true">${ICONOS[nombre]}</svg>`;

// --- Formatos ------------------------------------------------------------------

export function formatearPrecio(precio, moneda) {
  if (precio == null) return null;
  if (moneda === 'UF') return `UF ${NUMERO.format(precio)}`;
  return `$${NUMERO.format(Math.round(precio))}`;
}

/** Texto de la planilla o del KMZ dentro del HTML o del KML: nunca como marcado. */
export function escapar(texto) {
  return String(texto)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

// --- Qué dice y qué ofrece -------------------------------------------------------

/**
 * Las tarjetas de la cuadrícula: { clave, rotulo, valor, detalle }, en el orden
 * del diseño: superficie, topografía, servidumbre y rol. Cada una aparece solo si
 * la planilla trae su dato; sin ninguna, la cuadrícula no se dibuja.
 */
export function atributosDe(parcela) {
  const tarjetas = [];
  if (parcela.superficie_m2 != null) {
    tarjetas.push({
      clave: 'superficie',
      rotulo: 'Superficie',
      valor: `${NUMERO.format(parcela.superficie_m2)} m²`,
      detalle: `${HECTAREAS.format(parcela.superficie_m2 / M2_POR_HECTAREA)} hectáreas`,
    });
  }
  if (parcela.topografia) {
    tarjetas.push({ clave: 'topografia', rotulo: 'Topografía', valor: parcela.topografia, detalle: null });
  }
  const servidumbre = tarjetaServidumbre(parcela);
  if (servidumbre) tarjetas.push(servidumbre);
  if (parcela.rol) tarjetas.push({ clave: 'rol', rotulo: 'Rol', valor: parcela.rol, detalle: null });
  return tarjetas;
}

/**
 * Las filas bajo el precio: [rótulo, valor]. El pie y la cuota van en la moneda
 * del precio. No se calcula ninguna cuota: se muestra lo que la planilla dice,
 * porque sin la tasa cualquier cálculo sería inventar.
 */
export function financiamientoDe(parcela) {
  const filas = [];
  const moneda = parcela.moneda;
  if (parcela.pie) {
    const porcentaje = parcela.precio ? ` (${Math.round((parcela.pie / parcela.precio) * 100)}%)` : '';
    filas.push(['Pie desde', `${formatearPrecio(parcela.pie, moneda)}${porcentaje}`]);
  }
  if (parcela.cuotas) {
    const valor = parcela.valor_cuota ? ` de ${formatearPrecio(parcela.valor_cuota, moneda)}` : '';
    filas.push(['Cuotas', `${parcela.cuotas} cuotas${valor}`]);
  }
  return filas;
}

/** La superficie de la servidumbre como valor y el ancho del camino como detalle, si están. */
function tarjetaServidumbre({ servidumbre_m: ancho, servidumbre_m2: superficie }) {
  if (ancho == null && superficie == null) return null;
  const textoAncho = ancho != null ? `${NUMERO.format(ancho)} m de ancho` : null;
  if (superficie == null) {
    return { clave: 'servidumbre', rotulo: 'Servidumbre', valor: textoAncho, detalle: null };
  }
  return {
    clave: 'servidumbre',
    rotulo: 'Servidumbre',
    valor: `${NUMERO.format(Math.round(superficie))} m²`,
    detalle: textoAncho ? `Camino de ${textoAncho}` : null,
  };
}

/**
 * Las acciones, en el orden del diseño: escribir por WhatsApp (el canal con que
 * se vende en Chile), después reservar o comprar, y al final verla en 360°. Una
 * parcela que no está a la venta solo se puede mirar. `url` es el enlace a la
 * parcela, que va en el mensaje de WhatsApp.
 */
export function accionesDe(parcela, catalogo, { url = '' } = {}) {
  const vendible = catalogo.estados[parcela.estado]?.vendible;
  const acciones = [];

  if (vendible && catalogo.meta.whatsapp) {
    acciones.push({
      tipo: 'contacto',
      texto: catalogo.diseno?.texto_contacto || TEXTOS_POR_DEFECTO.contacto,
      href: `https://wa.me/${catalogo.meta.whatsapp}?text=${encodeURIComponent(mensajeWhatsapp(catalogo, parcela, url))}`,
    });
  }
  const pago = vendible && pagoDe(parcela, catalogo.meta);
  if (pago) {
    // Con consola, el botón abre el formulario que aparta la parcela antes de pagar.
    acciones.push({ tipo: 'pago', texto: catalogo.diseno?.texto_pago || pago.texto, href: pago.href,
                    formulario: conReservas(catalogo.meta) });
  }
  if (parcela.mejor_vista) acciones.push({ tipo: 'aire', texto: 'Ver en 360°' });
  return acciones;
}

/**
 * Lo que se le escribe al loteo por WhatsApp. Dice que viene del Masterplan,
 * para que quien vende sepa de dónde llegó el contacto, y lleva el enlace a la
 * parcela para que la vea igual que el comprador.
 */
export function mensajeWhatsapp(catalogo, parcela, url = '') {
  const enlace = url ? `: ${url}` : '.';
  const loteo = catalogo.meta.proyecto;
  if (!parcela) return `Hola, vengo del Masterplan de ${loteo} y quiero más información${enlace}`;
  return `Hola, vengo del Masterplan de ${loteo}. Me interesa la ${catalogo.nombre(parcela).toLowerCase()}${enlace}`;
}

/**
 * El botón de pago: el link propio de la parcela (planilla) o, si no tiene, el
 * link de reserva del loteo (consola), con la parcela en el enlace para que quien
 * cobra sepa cuál se reservó. Null si no hay ninguno.
 */
function pagoDe(parcela, meta) {
  if (parcela.link_pago) return { href: parcela.link_pago, texto: textoDePago(parcela) };
  if (!meta.link_reserva) return null;
  const monto = parcela.reserva || meta.monto_reserva;
  return {
    href: conParcela(meta.link_reserva, parcela.id),
    // La reserva va en pesos: así se cobra, aunque el loteo se venda en UF.
    texto: monto ? `Reservar parcela (${formatearPrecio(monto, 'CLP')})` : 'Reservar parcela',
  };
}

/** El link con `parcela=<id>` sumado a lo que ya traía. Un link raro se deja tal cual. */
function conParcela(link, id) {
  try {
    const url = new URL(link);
    url.searchParams.set('parcela', id);
    return url.toString();
  } catch {
    return link;
  }
}

/** "Reservar parcela ($250.000)" si se sabe cuánto; si no, comprar o reservar. */
function textoDePago(parcela) {
  if (parcela.reserva) return `Reservar parcela (${formatearPrecio(parcela.reserva, 'CLP')})`;
  return parcela.precio != null ? 'Comprar' : 'Reservar parcela';
}

/**
 * Los deslindes de la parcela en KML, para abrirlos en Google Earth o en el
 * teléfono en terreno. KML y no KMZ: es texto y no necesita comprimir nada.
 */
export function kmlDeParcela(parcela, nombre, proyecto) {
  if (!parcela.poligono?.length) return null;
  const anillo = [...parcela.poligono, parcela.poligono[0]];
  const coordenadas = anillo.map(([lon, lat]) => `${lon},${lat},0`).join(' ');
  return `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Placemark>
    <name>${escapar(nombre)} · ${escapar(proyecto)}</name>
    <Style><LineStyle><color>ff3d8015</color><width>3</width></LineStyle><PolyStyle><color>403d8015</color></PolyStyle></Style>
    <Polygon><outerBoundaryIs><LinearRing><coordinates>${coordenadas}</coordinates></LinearRing></outerBoundaryIs></Polygon>
  </Placemark>
</kml>
`;
}

/**
 * A qué altura queda el panel al soltar el asa: 'entera', 'media' o 'minima'
 * (asomada solo la cabecera). Abre a media altura para que la foto se siga
 * viendo; subir lo abre entero; bajar con decisión lo deja asomado. Bajarlo nunca
 * lo cierra: en el celular se baja para mirar el campo sin perder la parcela, y
 * para cerrarla está la ×. `desplazamiento` es positivo hacia abajo.
 */
export function destinoDelArrastre(desplazamiento, alto, velocidad, nivel) {
  if (Math.abs(desplazamiento) < ARRASTRE_MINIMO) return nivel;
  if (desplazamiento < 0) return nivel === 'minima' ? 'media' : 'entera';
  if (nivel !== 'media') return nivel === 'entera' ? 'media' : 'minima';
  const decidido = desplazamiento > alto * FRACCION_PARA_BAJAR || velocidad > VELOCIDAD_PARA_BAJAR;
  return decidido ? 'minima' : 'media';
}

// --- Dibujo --------------------------------------------------------------------

export function renderizarFicha(contenedor, parcela, catalogo, acciones) {
  const estado = parcela.estado;
  const precio = formatearPrecio(parcela.precio, parcela.moneda);
  const atributos = atributosDe(parcela);
  const financiamiento = financiamientoDe(parcela);
  const titulo = catalogo.titulo(parcela);

  contenedor.replaceChildren();
  contenedor.hidden = false;
  contenedor.style.transform = '';
  // Cada parcela abre a media altura, aunque la anterior haya quedado entera o asomada.
  contenedor.classList.remove('ficha--entera', 'ficha--minima');
  contenedor.innerHTML = `
    <div class="ficha__asa" aria-hidden="true"></div>
    <div class="ficha__cabecera">
      <div class="ficha__identidad">
        <div class="ficha__meta">
          <span class="insignia insignia--${escapar(estado)}">${escapar(parcela.apartada
            ? 'Reserva en proceso' : catalogo.etiquetaEstado(estado))}</span>
          ${parcela.etapa != null ? `<span class="ficha__etapa">${escapar(catalogo.etapaDe(parcela))}</span>` : ''}
        </div>
        <h2 class="ficha__titulo">${escapar(titulo)} <span class="ficha__proyecto">• ${escapar(catalogo.meta.proyecto)}</span></h2>
      </div>
      <div class="ficha__herramientas">
        <button class="ficha__redondo" type="button" data-accion="compartir" aria-label="Compartir esta parcela">${icono('compartir')}</button>
        <button class="ficha__redondo ficha__cerrar" type="button" aria-label="Cerrar ficha">✕</button>
      </div>
    </div>

    ${atributos.length ? `<ul class="atributos">${atributos.map((a) => `
      <li class="atributo">
        <span class="atributo__icono">${icono(a.clave)}</span>
        <span class="atributo__textos">
          <span class="atributo__rotulo">${escapar(a.rotulo)}</span>
          <strong class="atributo__valor">${escapar(a.valor)}</strong>
          ${a.detalle ? `<span class="atributo__detalle">${escapar(a.detalle)}</span>` : ''}
        </span>
      </li>`).join('')}</ul>` : ''}

    <div class="precio">
      <span class="precio__rotulo">Precio</span>
      ${precio
        ? `<p class="precio__monto"><strong>${precio}</strong>${parcela.moneda === 'UF' ? '' : ' <small>CLP</small>'}</p>`
        : '<p class="precio__monto precio__monto--consultar">A consultar</p>'}
      ${financiamiento.length ? `<dl class="precio__financiamiento">${financiamiento.map(([rotulo, valor]) => `
        <div><dt>${escapar(rotulo)}</dt><dd>${escapar(valor)}</dd></div>`).join('')}</dl>` : ''}
    </div>

    <div class="acciones"></div>
    <div class="enlaces"></div>
    <p class="nota" hidden></p>
  `;

  contenedor.querySelector('.ficha__cerrar').addEventListener('click', acciones.alCerrar);
  contenedor.querySelector('[data-accion="compartir"]')
    .addEventListener('click', () => compartir(contenedor, parcela, `${titulo} · ${catalogo.meta.proyecto}`));

  const lista = accionesDe(parcela, catalogo, { url: urlDeParcela(parcela) });
  pintarBotones(contenedor.querySelector('.acciones'), lista, () => acciones.alReservar?.(parcela));
  pintarEnlaces(contenedor, parcela, catalogo, lista.find((a) => a.tipo === 'aire'), acciones);
  permitirArrastre(contenedor);

  if (!parcela.poligono) {
    mostrarNota(contenedor,
      'Esta parcela todavía no tiene su polígono cargado, así que no aparece en el plano ' +
      'ni en la vista aérea. Los datos comerciales sí están al día.');
  } else if (!parcela.mejor_vista) {
    mostrarNota(contenedor, 'Esta parcela no queda dentro del encuadre de ninguna de las ' +
      'posiciones de vuelo. Puedes verla en el plano.');
  }
}

/** WhatsApp con su verde y, debajo, reservar o comprar en el color de la marca. */
function pintarBotones(zona, lista, alReservar) {
  for (const accion of lista) {
    if (accion.tipo === 'contacto') zona.append(enlace(accion, 'boton boton--whatsapp'));
    if (accion.tipo === 'pago') {
      zona.append(accion.formulario ? boton(accion.texto, 'boton', alReservar, 'pago') : enlace(accion, 'boton'));
    }
  }
}

/** La fila de enlaces chicos: verla en 360°, bajar los deslindes y copiar el enlace. */
function pintarEnlaces(contenedor, parcela, catalogo, aire, { alVerDesdeAire }) {
  const zona = contenedor.querySelector('.enlaces');
  if (aire) zona.append(boton(aire.texto, 'enlace-ficha', alVerDesdeAire, 'aire'));

  const kml = kmlDeParcela(parcela, catalogo.titulo(parcela), catalogo.meta.proyecto);
  if (kml) {
    const descarga = document.createElement('a');
    descarga.className = 'enlace-ficha';
    if (urlKml) URL.revokeObjectURL(urlKml);
    urlKml = URL.createObjectURL(new Blob([kml], { type: 'application/vnd.google-earth.kml+xml' }));
    descarga.href = urlKml;
    descarga.download = `parcela-${parcela.id}.kml`;
    descarga.insertAdjacentHTML('afterbegin', icono('deslindes'));
    descarga.append('Deslindes (KML)');
    zona.append(descarga);
  }

  zona.append(boton('Copiar enlace', 'enlace-ficha', async (evento) => {
    const objetivo = evento.currentTarget;
    const texto = objetivo.lastChild;
    try {
      await navigator.clipboard.writeText(urlDeParcela(parcela));
      texto.textContent = 'Enlace copiado';
      setTimeout(() => { texto.textContent = 'Copiar enlace'; }, 1800);
    } catch {
      mostrarNota(contenedor, urlDeParcela(parcela));
    }
  }, 'enlace'));
}

function urlDeParcela(parcela) {
  const url = new URL(location.href);
  url.searchParams.set('lote', parcela.id);
  return url.toString();
}

/** La hoja de compartir del teléfono; donde no existe, copiar el enlace. */
async function compartir(contenedor, parcela, titulo) {
  const url = urlDeParcela(parcela);
  if (navigator.share) {
    try {
      await navigator.share({ title: titulo, url });
      return;
    } catch {
      // Canceló el diálogo del sistema: se copia como respaldo.
    }
  }
  try {
    await navigator.clipboard.writeText(url);
    mostrarNota(contenedor, 'Enlace copiado.');
  } catch {
    mostrarNota(contenedor, url);
  }
}

/** La altura del panel: 'entera', 'media' o 'minima'. */
function nivelDe(contenedor) {
  if (contenedor.classList.contains('ficha--entera')) return 'entera';
  return contenedor.classList.contains('ficha--minima') ? 'minima' : 'media';
}

function ponerNivel(contenedor, nivel) {
  if (nivel === 'minima') {
    // Asomada queda la cabecera entera (estado, nombre, compartir y la ×), mida lo
    // que mida según el largo del nombre.
    // Más el margen de abajo del iPhone (la barra de inicio), que tapa lo último.
    const cabecera = contenedor.querySelector('.ficha__cabecera');
    const raiz = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const margenSeguro = Math.max(0, (parseFloat(getComputedStyle(contenedor).paddingBottom) || 0) - 1.25 * raiz);
    contenedor.style.setProperty('--asomo', `${cabecera.offsetTop + cabecera.offsetHeight + 14 + margenSeguro}px`);
    contenedor.scrollTop = 0;
  }
  contenedor.classList.toggle('ficha--entera', nivel === 'entera');
  contenedor.classList.toggle('ficha--minima', nivel === 'minima');
}

/**
 * El asa: arrastrarla hacia abajo baja el panel con el dedo y, al soltar, decide
 * destinoDelArrastre. Hacia arriba no se arrastra el dibujo: al soltar, el panel
 * sube. Un toque sube un nivel (entero vuelve a media altura). Asomado, tocar la
 * cabecera también lo vuelve a media altura.
 */
function permitirArrastre(contenedor) {
  const asa = contenedor.querySelector('.ficha__asa');
  let inicio = null;

  asa.addEventListener('pointerdown', (evento) => {
    inicio = { y: evento.clientY, t: evento.timeStamp };
    asa.setPointerCapture(evento.pointerId);
    contenedor.classList.add('ficha--arrastrando');
  });
  asa.addEventListener('pointermove', (evento) => {
    if (!inicio) return;
    const delta = evento.clientY - inicio.y;
    if (nivelDe(contenedor) === 'minima') {
      // Asomado se arrastra desde donde está, y hacia arriba hasta media altura.
      const asomo = parseFloat(contenedor.style.getPropertyValue('--asomo')) || 0;
      const subida = Math.max(delta, -(contenedor.offsetHeight - asomo));
      contenedor.style.transform = `translateY(calc(100% - var(--asomo) + ${subida}px))`;
      return;
    }
    contenedor.style.transform = `translateY(${Math.max(0, delta)}px)`;
  });
  const soltar = (evento) => {
    if (!inicio) return;
    const desplazamiento = evento.clientY - inicio.y;
    const duracion = evento.timeStamp - inicio.t;
    const velocidad = Math.max(0, desplazamiento) / Math.max(1, duracion);
    inicio = null;
    contenedor.classList.remove('ficha--arrastrando');
    contenedor.style.transform = '';
    const nivel = nivelDe(contenedor);
    if (Math.abs(desplazamiento) <= TOQUE_MAXIMO_PX && duracion <= TOQUE_MAXIMO_MS) {
      ponerNivel(contenedor, nivel === 'media' ? 'entera' : 'media');
      return;
    }
    ponerNivel(contenedor, destinoDelArrastre(desplazamiento, contenedor.offsetHeight, velocidad, nivel));
  };
  asa.addEventListener('pointerup', soltar);
  asa.addEventListener('pointercancel', soltar);
  contenedor.querySelector('.ficha__cabecera').addEventListener('click', (evento) => {
    if (nivelDe(contenedor) === 'minima' && !evento.target.closest('button, a')) ponerNivel(contenedor, 'media');
  });
}

function enlace(accion, clase) {
  const elemento = document.createElement('a');
  elemento.className = clase;
  elemento.dataset.tipo = accion.tipo;
  elemento.href = accion.href;
  elemento.target = '_blank';
  elemento.rel = 'noopener';
  elemento.insertAdjacentHTML('afterbegin', icono(accion.tipo));
  elemento.append(accion.texto);
  return elemento;
}

function boton(texto, clase, alHacerClic, tipo) {
  const elemento = document.createElement('button');
  elemento.type = 'button';
  elemento.className = clase;
  if (tipo) {
    elemento.dataset.tipo = tipo;
    elemento.insertAdjacentHTML('afterbegin', icono(tipo));
  }
  elemento.append(texto);
  elemento.addEventListener('click', alHacerClic);
  return elemento;
}

function mostrarNota(contenedor, texto) {
  const nota = contenedor.querySelector('.nota');
  nota.textContent = texto;
  nota.hidden = false;
}
