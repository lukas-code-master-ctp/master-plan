/**
 * La ficha en el celular es una hoja que sube desde abajo, con tres alturas:
 * entera, media (la parcela elegida se sigue viendo arriba) y asomada (solo la
 * cabecera, para mirar el campo sin soltar la parcela). Las tres son la misma hoja
 * corrida con transform, sin cambiar de alto: el movimiento es uno solo, sigue al
 * dedo desde cualquier altura y al soltar termina donde iba el gesto.
 *
 * Antes cada altura era otro max-height y el arrastre se dibujaba distinto según
 * desde dónde partía, así que al soltar la hoja saltaba. Bajarla nunca la cierra:
 * para eso está la ×.
 */

// A media altura la hoja deja ver esta fracción de la pantalla.
const FRACCION_MEDIA = 0.52;
// Al soltar, la hoja sigue el impulso del dedo por este tiempo antes de elegir
// altura: un tirón corto pero rápido cuenta como uno largo.
const PROYECCION_MS = 160;
const VELOCIDAD_MAXIMA = 3;
// Pasado el tope, el dedo arrastra con freno: se siente el borde sin que choque.
const RESISTENCIA = 0.35;
// Menos que esto es un toque, no un arrastre: los botones de la hoja siguen andando.
const UMBRAL_ARRASTRE_PX = 6;
// La velocidad se mide sobre lo último que hizo el dedo, no sobre todo el gesto.
const VENTANA_VELOCIDAD_MS = 100;
// Lo que se ve de la hoja asomada, debajo de su cabecera.
const AIRE_BAJO_LA_CABECERA_PX = 14;

const MOVIL = globalThis.matchMedia?.('(max-width: 62rem)');

/** Cuánto se corre la hoja hacia abajo en cada altura, en px (entera = 0). */
export function nivelesDeLaHoja(alto, altoVentana, asomo) {
  const minima = Math.max(0, alto - asomo);
  const media = Math.min(minima, Math.max(0, alto - Math.round(altoVentana * FRACCION_MEDIA)));
  return { entera: 0, media, minima };
}

/** La altura donde termina la hoja soltada en `posicion` con `velocidad` (px/ms, + hacia abajo). */
export function destinoAlSoltar(posicion, velocidad, niveles) {
  const impulso = Math.max(-VELOCIDAD_MAXIMA, Math.min(VELOCIDAD_MAXIMA, velocidad));
  const proyectada = posicion + impulso * PROYECCION_MS;
  let destino = 'media';
  for (const [nivel, y] of Object.entries(niveles)) {
    if (Math.abs(y - proyectada) < Math.abs(niveles[destino] - proyectada)) destino = nivel;
  }
  return destino;
}

export function conResistencia(y, minimo, maximo) {
  if (y < minimo) return minimo - (minimo - y) * RESISTENCIA;
  if (y > maximo) return maximo + (y - maximo) * RESISTENCIA;
  return y;
}

// --- La hoja en la página --------------------------------------------------------

const hojas = new WeakMap();

/**
 * Prepara `contenedor` como hoja y la deja a media altura. Si estaba cerrada, sube
 * desde abajo; si ya estaba abierta (se eligió otra parcela), se acomoda sin salir.
 * Hay que llamarla después de cada dibujo de la ficha.
 */
export function abrirHoja(contenedor, { venia }) {
  if (!MOVIL?.matches) return;
  let hoja = hojas.get(contenedor);
  if (!hoja) {
    hoja = crearHoja(contenedor);
    hojas.set(contenedor, hoja);
  }
  if (!venia) hoja.mover(contenedor.offsetHeight, false);
  hoja.poner('media');
}

function crearHoja(contenedor) {
  let nivel = 'media';
  let posicion = 0;
  let niveles = { entera: 0, media: 0, minima: 0 };
  let gesto = null;

  const medir = () => {
    const cabecera = contenedor.querySelector('.ficha__cabecera');
    // Más el margen de abajo del iPhone (la barra de inicio), que tapa lo último.
    const relleno = parseFloat(getComputedStyle(contenedor).paddingBottom) || 0;
    const raiz = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const margenSeguro = Math.max(0, relleno - 1.25 * raiz);
    const asomo = cabecera
      ? cabecera.offsetTop + cabecera.offsetHeight + AIRE_BAJO_LA_CABECERA_PX + margenSeguro
      : contenedor.offsetHeight;
    niveles = nivelesDeLaHoja(contenedor.offsetHeight, window.innerHeight, asomo);
  };

  const mover = (y, animar) => {
    if (!animar) {
      contenedor.classList.add('ficha--arrastrando');
      contenedor.style.setProperty('--desplazo', `${y}px`);
      // Forzar el estilo para que la animación siguiente parta desde aquí.
      void contenedor.offsetHeight;
    } else {
      contenedor.classList.remove('ficha--arrastrando');
      contenedor.style.setProperty('--desplazo', `${y}px`);
    }
    posicion = y;
  };

  const poner = (destino) => {
    medir();
    // Una hoja corta no tiene media altura: abierta es entera.
    nivel = destino !== 'minima' && niveles[destino] === 0 ? 'entera' : destino;
    if (nivel !== 'entera' && contenedor.scrollTop) contenedor.scrollTo({ top: 0, behavior: 'smooth' });
    contenedor.classList.toggle('ficha--entera', nivel === 'entera');
    contenedor.classList.toggle('ficha--minima', nivel === 'minima');
    const boton = contenedor.querySelector('.ficha__bajar');
    if (boton) {
      boton.setAttribute('aria-label', nivel === 'minima' ? 'Subir la ficha' : 'Bajar la ficha');
      boton.setAttribute('aria-expanded', String(nivel !== 'minima'));
    }
    mover(niveles[nivel], true);
  };

  contenedor.addEventListener('pointerdown', (evento) => {
    if (!MOVIL.matches || contenedor.hidden || evento.button !== 0) return;
    // Entera, el contenido se desplaza con el dedo: la hoja se arrastra desde arriba.
    const desdeArriba = evento.target.closest('.ficha__asa, .ficha__cabecera');
    if (nivel === 'entera' && !desdeArriba) return;
    medir();
    gesto = { id: evento.pointerId, y: evento.clientY, desde: posicion, moviendo: false,
              muestras: [{ y: evento.clientY, t: evento.timeStamp }] };
  });

  contenedor.addEventListener('pointermove', (evento) => {
    if (!gesto || evento.pointerId !== gesto.id) return;
    const delta = evento.clientY - gesto.y;
    if (!gesto.moviendo) {
      if (Math.abs(delta) < UMBRAL_ARRASTRE_PX) return;
      gesto.moviendo = true;
      // Para seguir el dedo aunque salga de la hoja. Si el puntero ya no existe
      // (el sistema lo canceló), se sigue sin captura.
      try { contenedor.setPointerCapture(evento.pointerId); } catch { /* sin captura */ }
    }
    mover(conResistencia(gesto.desde + delta, 0, niveles.minima), false);
    gesto.muestras.push({ y: evento.clientY, t: evento.timeStamp });
    while (gesto.muestras.length > 2 && evento.timeStamp - gesto.muestras[0].t > VENTANA_VELOCIDAD_MS) {
      gesto.muestras.shift();
    }
  });

  const soltar = (evento) => {
    if (!gesto || evento.pointerId !== gesto.id) return;
    const { moviendo, muestras } = gesto;
    gesto = null;
    if (!moviendo) return;
    const [primera, ultima] = [muestras[0], muestras.at(-1)];
    const velocidad = evento.type === 'pointercancel' ? 0
      : (ultima.y - primera.y) / Math.max(1, ultima.t - primera.t);
    poner(destinoAlSoltar(posicion, velocidad, niveles));
    // El dedo que arrastró no aprieta lo que quedó debajo al soltar. El clic, si
    // llega, llega enseguida; después el bloqueo se retira.
    contenedor.addEventListener('click', tragarClic, { capture: true, once: true });
    setTimeout(() => contenedor.removeEventListener('click', tragarClic, { capture: true }), 0);
  };
  contenedor.addEventListener('pointerup', soltar);
  contenedor.addEventListener('pointercancel', soltar);

  // El botón del asa baja la hoja hasta asomarla y la vuelve a subir; asomada,
  // tocar la cabecera también la sube.
  contenedor.addEventListener('click', (evento) => {
    if (evento.target.closest('.ficha__bajar')) {
      poner(nivel === 'minima' ? 'media' : 'minima');
    } else if (nivel === 'minima' && evento.target.closest('.ficha__cabecera')
               && !evento.target.closest('button, a')) {
      poner('media');
    }
  });

  window.addEventListener('resize', () => { if (!contenedor.hidden && MOVIL.matches) poner(nivel); });

  return { mover, poner };
}

function tragarClic(evento) {
  evento.preventDefault();
  evento.stopPropagation();
}
