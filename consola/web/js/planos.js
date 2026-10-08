/**
 * Mis planos: arriba, cuánto hay entre todos los loteos; abajo, una tarjeta por
 * loteo con su foto desde el dron, lo que queda por vender y desde cuánto, y la
 * puerta a su detalle.
 *
 * La página se mueve para que se sienta viva, no para adornar: las cifras cuentan
 * hasta su valor, las barras se llenan y la foto de cada loteo deriva despacio,
 * como el dron que la tomó. Todo eso solo al llegar a la pantalla —un refresco
 * mientras se construye algo no repite la entrada— y nada si el sistema pide
 * menos movimiento.
 */
import { $, dinero, estado, etapaDe } from './comun.js';

// El orden del rubro, de lo que se puede comprar a lo que no.
const ORDEN = ['disponible', 'reservado', 'vendido', 'no_disponible'];
const ROTULOS = { disponible: 'Disponibles', reservado: 'Reservadas', vendido: 'Vendidas', no_disponible: 'No disponibles' };
const CUENTA_MS = 1400;
const NUMERO = new Intl.NumberFormat('es-CL');
const FLECHA = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-6-6 6 6-6 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const MAS = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>';

/** Lo que suman los loteos construidos; null si no hay ninguno. */
export function resumenDe(proyectos) {
  const construidos = proyectos.filter((p) => p.construido && p.resumen?.por_estado);
  if (!construidos.length) return null;
  const por_estado = {};
  for (const proyecto of construidos) {
    for (const [nombre, cantidad] of Object.entries(proyecto.resumen.por_estado)) {
      por_estado[nombre] = (por_estado[nombre] ?? 0) + cantidad;
    }
  }
  return {
    masters: construidos.length,
    parcelas: construidos.reduce((suma, p) => suma + (p.resumen.parcelas ?? 0), 0),
    por_estado,
  };
}

/** Los tramos de la barra de estados. "No en venta" se cuenta con "no disponible". */
export function segmentos(porEstado, total) {
  const cuentas = { ...porEstado, no_disponible: (porEstado.no_disponible ?? 0) + (porEstado.no_en_venta ?? 0) };
  return ORDEN.filter((nombre) => cuentas[nombre] > 0).map((nombre) => ({
    estado: nombre,
    cantidad: cuentas[nombre],
    porcentaje: (100 * cuentas[nombre]) / total,
  }));
}

/**
 * El orden de las tarjetas: primero lo publicado, después lo construido y al
 * final lo que falta construir. El destacado tiene que ser un loteo con foto.
 * Dentro de cada grupo se respeta el orden que trae la lista.
 */
export function ordenarParaLista(proyectos) {
  const peso = (p) => (p.publicado ? 0 : p.construido ? 1 : 2);
  return proyectos.map((p, i) => [p, i]).sort(([a, i], [b, j]) => peso(a) - peso(b) || i - j).map(([p]) => p);
}

/**
 * Cómo se reparte la rejilla: con tres o más, el primero destacado y dos a su
 * lado, y el resto de a tres; uno solo, a lo ancho; dos, mitad y mitad.
 */
export function formaDeTarjeta(indice, cantidad) {
  if (cantidad === 1) return 'ancha';
  if (cantidad === 2) return 'mitad';
  if (indice === 0) return 'destacada';
  return indice <= 2 ? 'lateral' : 'tercio';
}

export function pintarPlanos({ animar = false } = {}) {
  const movimiento = animar && !matchMedia('(prefers-reduced-motion: reduce)').matches;
  pintarResumen(resumenDe(estado.proyectos), movimiento);

  const lista = $('#planos');
  lista.classList.toggle('planos--entrando', movimiento);
  const proyectos = ordenarParaLista(estado.proyectos);
  const cantidad = proyectos.length;
  lista.replaceChildren(
    ...proyectos.map((proyecto, indice) => tarjeta(proyecto, indice, formaDeTarjeta(indice, cantidad))),
    tarjetaNueva(cantidad),
  );
}

// --- El resumen de arriba -------------------------------------------------------------

function pintarResumen(resumen, movimiento) {
  const caja = $('#planos-resumen');
  caja.hidden = !resumen;
  if (!resumen) return;
  caja.classList.toggle('resumen-planos--entrando', movimiento);

  const cifras = [
    { rotulo: 'Parcelas', valor: resumen.parcelas, estado: 'total' },
    ...['disponible', 'reservado', 'vendido'].map((nombre) => ({
      rotulo: ROTULOS[nombre], valor: resumen.por_estado[nombre] ?? 0, estado: nombre,
    })),
  ];
  const lista = $('.resumen-planos__cifras', caja);
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
  $('.resumen-planos__barra', caja).replaceChildren(...barra(resumen.por_estado, resumen.parcelas));
  $('.resumen-planos__pie', caja).textContent =
    `${NUMERO.format(resumen.parcelas)} parcelas en ${resumen.masters} ${resumen.masters === 1 ? 'master' : 'masters'}`;
  if (movimiento) contar([...lista.querySelectorAll('dd')]);
}

/** Las cifras suben de cero a su valor, frenando al final. */
export function contar(nodos) {
  const inicio = performance.now();
  const paso = (ahora) => {
    const t = Math.min(1, (ahora - inicio) / CUENTA_MS);
    const avance = 1 - (1 - t) ** 3;
    for (const nodo of nodos) nodo.textContent = NUMERO.format(Math.round(Number(nodo.dataset.valor) * avance));
    if (t < 1 && nodos[0].isConnected) requestAnimationFrame(paso);
  };
  requestAnimationFrame(paso);
}

export function barra(porEstado, total) {
  return segmentos(porEstado, total).map(({ estado: nombre, cantidad, porcentaje }) => {
    const tramo = document.createElement('span');
    tramo.className = `tramo tramo--${nombre}`;
    tramo.style.width = `${porcentaje}%`;
    tramo.title = `${ROTULOS[nombre]}: ${NUMERO.format(cantidad)}`;
    return tramo;
  });
}

// --- Las tarjetas -----------------------------------------------------------------------

function tarjeta(proyecto, indice, forma) {
  const item = document.createElement('li');
  item.className = `planos__item planos__item--${forma}`;
  item.style.setProperty('--orden', indice);

  const enlace = document.createElement('a');
  enlace.className = proyecto.construido ? 'plano' : 'plano plano--sin-foto';
  enlace.href = `#/planos/${proyecto.slug}`;

  const foto = document.createElement('div');
  foto.className = 'plano__foto';
  if (proyecto.construido) {
    const imagen = document.createElement('img');
    imagen.src = `/api/proyectos/${proyecto.slug}/portada?v=${encodeURIComponent(proyecto.resumen.generado ?? '')}`;
    imagen.alt = '';
    imagen.loading = indice < 3 ? 'eager' : 'lazy';
    imagen.width = 1280;
    imagen.height = 720;
    // Cada foto deriva desfasada de las otras, para que no se muevan al unísono.
    imagen.style.animationDelay = `${-indice * 7}s`;
    imagen.addEventListener('error', () => imagen.remove());
    foto.append(imagen);
  }
  const velo = document.createElement('div');
  velo.className = 'plano__velo';

  const arriba = document.createElement('div');
  arriba.className = 'plano__arriba';
  const etapa = etapaDe(proyecto);
  if (proyecto.publicado && !proyecto.trabajo) {
    const vivo = document.createElement('i');
    vivo.className = 'punto-vivo';
    etapa.prepend(vivo);
  }
  arriba.append(etapa);
  if (proyecto.construido && proyecto.resumen.vistas) {
    const vistas = document.createElement('span');
    vistas.className = 'plano__vistas';
    vistas.textContent = `${proyecto.resumen.vistas} ${proyecto.resumen.vistas === 1 ? 'vista aérea' : 'vistas aéreas'}`;
    arriba.append(vistas);
  }

  const abajo = document.createElement('div');
  abajo.className = 'plano__abajo';
  const titulo = document.createElement('div');
  titulo.className = 'plano__titulo';
  const nombre = document.createElement('h2');
  nombre.className = 'plano__nombre';
  nombre.textContent = proyecto.nombre;
  const abrir = document.createElement('span');
  abrir.className = 'plano__abrir';
  abrir.setAttribute('aria-hidden', 'true');
  abrir.innerHTML = `Abrir ${FLECHA}`;
  titulo.append(nombre, abrir);

  const cifras = document.createElement('dl');
  cifras.className = 'plano__cifras';
  cifras.append(...cifrasDe(proyecto));
  abajo.append(titulo, cifras);

  if (proyecto.construido && proyecto.resumen.parcelas) {
    const linea = document.createElement('div');
    linea.className = 'barra-estados';
    linea.style.setProperty('--orden', indice);
    linea.append(...barra(proyecto.resumen.por_estado, proyecto.resumen.parcelas));
    abajo.append(linea);
  }

  enlace.append(foto, velo, arriba, abajo);
  item.append(enlace);
  return item;
}

function cifrasDe(proyecto) {
  const { resumen } = proyecto;
  const dato = (rotulo, valor, total = null) => {
    const div = document.createElement('div');
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    dt.textContent = rotulo;
    dd.textContent = valor;
    if (total !== null) {
      const de = document.createElement('span');
      de.textContent = ` / ${total}`;
      dd.append(de);
    }
    div.append(dt, dd);
    return div;
  };
  if (!proyecto.construido) {
    const hallado = proyecto.fuentes_encontradas;
    return [dato('Vuelo', hallado.kmz
      ? `${hallado.panoramicas} panorámicas · ${hallado.megas} MB`
      : 'sin subir')];
  }
  const desde = resumen.precio_desde;
  return [
    dato('Disponibles', NUMERO.format(resumen.disponibles ?? 0), NUMERO.format(resumen.parcelas ?? 0)),
    dato('Precio desde', desde ? dinero(desde.monto, desde.moneda) : 'sin precios'),
  ];
}

/** La última tarjeta invita al próximo master; sin loteos, es la bienvenida. */
function tarjetaNueva(cantidad) {
  const item = document.createElement('li');
  item.className = 'planos__item planos__item--ancha';
  item.style.setProperty('--orden', cantidad);
  const enlace = document.createElement('a');
  enlace.className = 'plano-nuevo';
  enlace.href = '#/planos/nuevo';
  enlace.innerHTML = `
    <span class="plano-nuevo__icono"><span class="plano-nuevo__orbita"></span>${MAS}</span>
    <span class="plano-nuevo__textos">
      <strong>${cantidad ? 'Crea tu próximo master' : 'Todavía no tienes planos'}</strong>
      <span>Sube el KMZ del loteo y las panorámicas del dron. Lo construimos y lo publicas cuando quieras.</span>
    </span>`;
  item.append(enlace);
  return item;
}
