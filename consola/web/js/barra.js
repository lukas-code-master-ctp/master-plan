/**
 * La isla de secciones de la barra: marca la sección en que estás y desliza la
 * píldora de tinta hasta ella. La píldora se mide sobre la pestaña misma, así que
 * sigue al texto aunque cambie la fuente o el ancho de la pantalla.
 */
import { $, $$ } from './comun.js';

/** La sección de la barra a la que pertenece cada pantalla (null: ninguna). */
export function seccionDe(pantalla) {
  if (pantalla.startsWith('diseno')) return 'disenos';
  if (pantalla.startsWith('kmz')) return 'kmz';
  if (pantalla === 'reservas') return 'reservas';
  // Configuración se abre desde el avatar, no desde la isla: ninguna pestaña es suya.
  if (pantalla === 'configuracion') return null;
  return 'planos';
}

let primera = true;

export function marcarSeccion(pantalla) {
  const seccion = seccionDe(pantalla);
  for (const enlace of $$('.pestanas a')) {
    if (enlace.dataset.seccion === seccion) enlace.setAttribute('aria-current', 'page');
    else enlace.removeAttribute('aria-current');
  }
  // La primera vez la píldora aparece donde va, sin viajar desde la izquierda.
  ubicarPildora({ animar: !primera });
  primera = false;
}

function ubicarPildora({ animar }) {
  const isla = $('.pestanas');
  const pildora = $('.pestanas__pildora', isla);
  const activa = $('a[aria-current="page"]', isla);
  pildora.hidden = !activa;
  if (!activa) return;
  pildora.classList.toggle('pestanas__pildora--quieta', !animar);
  isla.style.setProperty('--pildora-x', `${activa.offsetLeft}px`);
  isla.style.setProperty('--pildora-ancho', `${activa.offsetWidth}px`);
}

// Si cambia el ancho (girar el teléfono) o termina de llegar la fuente, las
// pestañas miden otra cosa: la píldora se reubica sin animarse.
// (Fuera del navegador, en las pruebas, no hay ventana ni fuentes.)
globalThis.addEventListener?.('resize', () => ubicarPildora({ animar: false }));
globalThis.document?.fonts?.ready.then(() => ubicarPildora({ animar: false }));
