/**
 * La marca de la loteadora, aplicada sobre el visor.
 *
 * El diseño trae un color, una tipografía, un logo y los textos de los botones
 * (`datos/diseno.json`, lo escribe la consola). De un solo color se deriva la
 * escala del cromado —botones, foco, selección—, que es la que el visor ya usa
 * como `--marca-*`. Lo que no se toca: el color de cada estado. El verde de
 * "disponible" tiene que significar lo mismo en todos los sitios.
 *
 * Lo usa también la consola, para la vista previa de "Mis diseños": la marca se
 * ve allá igual que se va a ver publicada.
 */

export const TIPOGRAFIAS = {
  jakarta: "'Plus Jakarta Sans', system-ui, -apple-system, 'Segoe UI', sans-serif",
  serif: "Georgia, 'Iowan Old Style', 'Times New Roman', serif",
  sistema: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
};

export const TEXTOS_POR_DEFECTO = {
  contacto: 'Consultar por WhatsApp',
};

// El botón lleva texto blanco encima: por debajo de esto no se lee bien (WCAG AA).
const CONTRASTE_MINIMO = 4.5;

const aRgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
const aHex = (rgb) => `#${rgb.map((c) => Math.round(c).toString(16).padStart(2, '0')).join('')}`;
const mezclar = (rgb, con, cuanto) => rgb.map((c, i) => c + (con[i] - c) * cuanto);
const BLANCO = [255, 255, 255];
const NEGRO = [0, 0, 0];

function luminancia([r, g, b]) {
  const lineal = (c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lineal(r) + 0.7152 * lineal(g) + 0.0722 * lineal(b);
}

export function contraste(hexA, hexB) {
  const [claro, oscuro] = [luminancia(aRgb(hexA)), luminancia(aRgb(hexB))].sort((a, b) => b - a);
  return (claro + 0.05) / (oscuro + 0.05);
}

/**
 * La escala del cromado a partir de un color. El 700 es el del botón: si el
 * color elegido es muy claro para llevar texto blanco, se oscurece lo justo.
 */
export function paleta(hex) {
  let base = aRgb(hex);
  for (let paso = 0; paso < 20 && contraste(aHex(base), '#ffffff') < CONTRASTE_MINIMO; paso += 1) {
    base = mezclar(base, NEGRO, 0.08);
  }
  const [r, g, b] = base.map(Math.round);
  return {
    '--marca-50': aHex(mezclar(base, BLANCO, 0.94)),
    '--marca-100': aHex(mezclar(base, BLANCO, 0.86)),
    '--marca-500': aHex(mezclar(base, BLANCO, 0.25)),
    '--marca-600': aHex(mezclar(base, BLANCO, 0.12)),
    '--marca-700': aHex(base),
    '--marca-800': aHex(mezclar(base, NEGRO, 0.2)),
    '--marca-900': aHex(mezclar(base, NEGRO, 0.4)),
    '--marca-anillo': `rgb(${r} ${g} ${b} / 0.25)`,
  };
}

/** Pone la marca sobre un nodo (el documento en el visor, la vista previa en la consola). */
export function aplicarMarca(nodo, diseno) {
  if (!diseno) return;
  if (/^#[0-9a-f]{6}$/i.test(diseno.color ?? '')) {
    for (const [variable, valor] of Object.entries(paleta(diseno.color))) {
      nodo.style.setProperty(variable, valor);
    }
  }
  const familia = TIPOGRAFIAS[diseno.tipografia];
  if (familia) nodo.style.setProperty('--sans', familia);
}

/** El logo en lugar de la brújula de Tu Masterplan. */
export function ponerLogo(hito, src, alt) {
  if (!hito || !src) return;
  const imagen = document.createElement('img');
  imagen.className = 'marca__logo';
  imagen.src = src;
  imagen.alt = alt;
  hito.replaceWith(imagen);
}
