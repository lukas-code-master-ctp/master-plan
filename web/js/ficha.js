/**
 * Ficha comercial de una parcela.
 *
 * En el teléfono es un panel que sube desde abajo y se cierra arrastrándolo; en
 * escritorio, una tarjeta flotante. Lo que dice y en qué orden lo ofrece sale de
 * funciones puras (formatos, atributos, acciones) que se prueban sin navegador.
 */
import { TEXTOS_POR_DEFECTO } from './marca.js';

const NUMERO = new Intl.NumberFormat('es-CL');
const HECTAREAS = new Intl.NumberFormat('es-CL', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const M2_POR_HECTAREA = 10000;

// Un tercio del panel, o un tirón de más de medio píxel por milisegundo: lo que
// se siente como "lo bajé a propósito". Bajo 24 px es el dedo que tembló.
const FRACCION_PARA_CERRAR = 1 / 3;
const VELOCIDAD_PARA_CERRAR = 0.5;
const ARRASTRE_MINIMO = 24;

const ICONOS = {
  superficie: '<path d="M2.5 13.5 13.5 2.5l4 4-11 11Z M6 10l1.5 1.5 M8.5 7.5 10 9 M11 5l1.5 1.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>',
  servidumbre: '<path d="M7 2.5 4.5 17.5 M13 2.5l2.5 15 M10 4v2.5 M10 9v2.5 M10 14v2.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>',
  aire: '<ellipse cx="10" cy="10" rx="8" ry="3.4" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M14.5 5.2A8 8 0 0 0 10 3.5c-2.2 0-4 2.9-4 6.5s1.8 6.5 4 6.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/><path d="m12.6 14.6 1.9 1.9-1.9 1.9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>',
  contacto: '<path d="M3 17l1-3.4A7 7 0 1 1 6.6 16L3 17Z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M7.4 7.6c0 3 2 5 5 5 .6 0 1-.5 1-1l-1.4-.7-.8.8a5 5 0 0 1-2-2l.8-.8L9.3 7c-.5 0-1 .2-1.4.4a1 1 0 0 0-.5.9Z" fill="currentColor"/>',
};

const icono = (nombre) => `<svg viewBox="0 0 20 20" aria-hidden="true">${ICONOS[nombre]}</svg>`;

// --- Formatos ------------------------------------------------------------------

/** "5.100 m²", o "13.200 m² · 1,32 ha" desde una hectárea. Null si no se sabe. */
export function formatearSuperficie(metros) {
  if (metros == null) return null;
  const m2 = `${NUMERO.format(metros)} m²`;
  return metros >= M2_POR_HECTAREA ? `${m2} · ${HECTAREAS.format(metros / M2_POR_HECTAREA)} ha` : m2;
}

export function formatearPrecio(precio, moneda) {
  if (precio == null) return null;
  if (moneda === 'UF') return `UF ${NUMERO.format(precio)}`;
  return `$${NUMERO.format(Math.round(precio))}`;
}

/** El ancho en metros si la planilla lo trae; si no, la superficie de la servidumbre. */
export function formatearServidumbre(parcela) {
  if (parcela.servidumbre_m != null) return `${NUMERO.format(parcela.servidumbre_m)} m`;
  if (parcela.servidumbre_m2 != null) return `${NUMERO.format(Math.round(parcela.servidumbre_m2))} m²`;
  return null;
}

/** Texto de la planilla o del KMZ dentro del HTML de la ficha: nunca como marcado. */
export function escapar(texto) {
  return String(texto)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

// --- Qué dice y qué ofrece -------------------------------------------------------

/**
 * Las tarjetas bajo el precio. Hoy solo la servidumbre; aquí se suman la
 * topografía y las factibilidades cuando la planilla las traiga. Sin ninguna,
 * la fila no se dibuja.
 */
export function atributosDe(parcela) {
  const servidumbre = formatearServidumbre(parcela);
  return servidumbre ? [{ clave: 'servidumbre', rotulo: 'Servidumbre', valor: servidumbre }] : [];
}

/**
 * Las acciones, en orden de jerarquía: primero lo que convierte una mirada en
 * un contacto (pagar, escribir), después lo que ayuda a mirar mejor. Una parcela
 * que no está a la venta solo se puede mirar.
 */
export function accionesDe(parcela, catalogo) {
  const vendible = catalogo.estados[parcela.estado]?.vendible;
  const acciones = [];

  if (vendible && parcela.link_pago) {
    acciones.push({
      tipo: 'pago',
      texto: catalogo.diseno?.texto_pago || (parcela.precio != null ? 'Comprar' : 'Reservar'),
      href: parcela.link_pago,
    });
  }
  if (vendible && catalogo.meta.whatsapp) {
    const mensaje = `Hola, me interesa la ${catalogo.nombre(parcela).toLowerCase()} de ${catalogo.meta.proyecto}.`;
    acciones.push({
      tipo: 'contacto',
      texto: catalogo.diseno?.texto_contacto || TEXTOS_POR_DEFECTO.contacto,
      href: `https://wa.me/${catalogo.meta.whatsapp}?text=${encodeURIComponent(mensaje)}`,
    });
  }
  if (parcela.mejor_vista) acciones.push({ tipo: 'aire', texto: 'Ver en 360°' });
  return acciones;
}

/** ¿El panel bajó lo suficiente, o con suficiente decisión, para cerrarlo? */
export function debeCerrarAlArrastrar(desplazamiento, alto, velocidad) {
  if (desplazamiento < ARRASTRE_MINIMO) return false;
  return desplazamiento > alto * FRACCION_PARA_CERRAR || velocidad > VELOCIDAD_PARA_CERRAR;
}

// --- Dibujo --------------------------------------------------------------------

export function renderizarFicha(contenedor, parcela, catalogo, acciones) {
  const estado = parcela.estado;
  const precio = formatearPrecio(parcela.precio, parcela.moneda);
  const superficie = formatearSuperficie(parcela.superficie_m2);
  const atributos = atributosDe(parcela);

  contenedor.replaceChildren();
  contenedor.hidden = false;
  contenedor.style.transform = '';
  contenedor.innerHTML = `
    <div class="ficha__asa" aria-hidden="true"></div>
    <div class="ficha__cabecera">
      <div>
        <h2 class="ficha__titulo">${escapar(catalogo.titulo(parcela))}</h2>
        <div class="ficha__meta">
          <span class="insignia insignia--${escapar(estado)}">${escapar(catalogo.etiquetaEstado(estado))}</span>
          ${parcela.etapa != null ? `<span class="ficha__etapa">${escapar(catalogo.etapaDe(parcela))}</span>` : ''}
        </div>
      </div>
      <button class="ficha__cerrar" type="button" aria-label="Cerrar ficha">✕</button>
    </div>

    <div class="ficha__resumen">
      ${superficie ? `<p class="ficha__superficie">${icono('superficie')}
        <span>Superficie <strong>${superficie}</strong></span></p>` : ''}
      <p class="ficha__precio">${precio
        ? `<span class="visually-hidden">Precio </span><strong>${precio}</strong>`
        : '<span class="ficha__consultar">Precio a consultar</span>'}</p>
    </div>

    ${atributos.length ? `<ul class="atributos">${atributos.map((a) => `
      <li class="atributo">${icono(a.clave)}
        <span class="atributo__rotulo">${escapar(a.rotulo)}</span>
        <span class="atributo__valor">${escapar(a.valor)}</span>
      </li>`).join('')}</ul>` : ''}

    <div class="acciones"></div>
    <p class="nota" hidden></p>
  `;

  contenedor.querySelector('.ficha__cerrar').addEventListener('click', acciones.alCerrar);
  pintarAcciones(contenedor.querySelector('.acciones'), accionesDe(parcela, catalogo), acciones);
  agregarCopiarEnlace(contenedor, parcela);
  permitirArrastre(contenedor, acciones.alCerrar);

  if (!parcela.poligono) {
    mostrarNota(contenedor,
      'Esta parcela todavía no tiene su polígono cargado, así que no aparece en el plano ' +
      'ni en la vista aérea. Los datos comerciales sí están al día.');
  } else if (!parcela.mejor_vista) {
    mostrarNota(contenedor, 'Esta parcela no queda dentro del encuadre de ninguna de las ' +
      'posiciones de vuelo. Puedes verla en el plano.');
  }
}

/**
 * El pago, si lo hay, a todo el ancho; debajo, en una fila, mirar en 360° y
 * escribir. El contacto es el botón lleno de esa fila: es lo que el loteo quiere
 * que pase.
 */
function pintarAcciones(zona, lista, { alVerDesdeAire }) {
  const pago = lista.find((a) => a.tipo === 'pago');
  if (pago) zona.append(enlace(pago, 'boton'));

  // El 360° a la izquierda, como en el diseño: el pulgar derecho cae en el contacto.
  const aire = lista.find((a) => a.tipo === 'aire');
  const contacto = lista.find((a) => a.tipo === 'contacto');
  const fila = document.createElement('div');
  fila.className = 'acciones__fila';
  if (aire) fila.append(boton(aire.texto, 'boton boton--suave', alVerDesdeAire, 'aire'));
  // Con un pago arriba, el contacto baja a contorno: dos botones llenos compiten.
  if (contacto) fila.append(enlace(contacto, pago ? 'boton boton--contorno' : 'boton'));
  if (fila.children.length) zona.append(fila);
}

function agregarCopiarEnlace(contenedor, parcela) {
  const copiar = boton('Copiar enlace', 'boton boton--texto', async (evento) => {
    const url = new URL(location.href);
    url.searchParams.set('lote', parcela.id);
    const objetivo = evento.currentTarget;
    try {
      await navigator.clipboard.writeText(url.toString());
      objetivo.textContent = 'Enlace copiado';
      setTimeout(() => { objetivo.textContent = 'Copiar enlace'; }, 1800);
    } catch {
      mostrarNota(contenedor, url.toString());
    }
  });
  contenedor.querySelector('.acciones').append(copiar);
}

/**
 * Arrastrar el asa hacia abajo baja el panel con el dedo; al soltar, se cierra
 * o vuelve a su lugar. Solo hacia abajo: hacia arriba ya muestra todo.
 */
function permitirArrastre(contenedor, alCerrar) {
  const asa = contenedor.querySelector('.ficha__asa');
  let inicio = null;

  asa.addEventListener('pointerdown', (evento) => {
    inicio = { y: evento.clientY, t: evento.timeStamp };
    asa.setPointerCapture(evento.pointerId);
    contenedor.classList.add('ficha--arrastrando');
  });
  asa.addEventListener('pointermove', (evento) => {
    if (!inicio) return;
    const bajada = Math.max(0, evento.clientY - inicio.y);
    contenedor.style.transform = `translateY(${bajada}px)`;
  });
  const soltar = (evento) => {
    if (!inicio) return;
    const bajada = Math.max(0, evento.clientY - inicio.y);
    const velocidad = bajada / Math.max(1, evento.timeStamp - inicio.t);
    inicio = null;
    contenedor.classList.remove('ficha--arrastrando');
    if (debeCerrarAlArrastrar(bajada, contenedor.offsetHeight, velocidad)) alCerrar();
    else contenedor.style.transform = '';
  };
  asa.addEventListener('pointerup', soltar);
  asa.addEventListener('pointercancel', soltar);
}

function enlace(accion, clase, tipo = accion.tipo) {
  const elemento = document.createElement('a');
  elemento.className = clase;
  elemento.dataset.tipo = tipo;
  elemento.href = accion.href;
  elemento.target = '_blank';
  elemento.rel = 'noopener';
  if (tipo === 'contacto') elemento.insertAdjacentHTML('afterbegin', icono('contacto'));
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
