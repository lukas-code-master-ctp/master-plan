/**
 * Qué pastillas de parcela caben en pantalla sin encimarse.
 *
 * Desde arriba y de lejos, las parcelas del fondo se achican y sus números se
 * apilan unos sobre otros hasta no leerse ninguno. En vez de dibujarlos todos se
 * eligen, de mayor a menor prioridad, los que no chocan con uno ya elegido. Las
 * parcelas que se quedan sin número siguen con su contorno y se pueden tocar.
 */

/**
 * @param {{id: string, x: number, y: number, ancho: number, alto: number, prioridad: number}[]} candidatas
 *   centro, tamaño en pantalla y prioridad de cada pastilla.
 * @param {number} separacion aire mínimo, en píxeles, entre dos pastillas.
 * @returns {Set<string>} los ids de las que se dibujan.
 */
export function rotulosSinChoques(candidatas, separacion = 2) {
  // sort es estable: a igual prioridad se respeta el orden de llegada.
  const ordenadas = [...candidatas].sort((a, b) => b.prioridad - a.prioridad);
  const elegidas = [];
  for (const candidata of ordenadas) {
    if (!elegidas.some((otra) => chocan(candidata, otra, separacion))) elegidas.push(candidata);
  }
  return new Set(elegidas.map((c) => c.id));
}

function chocan(a, b, separacion) {
  return Math.abs(a.x - b.x) < (a.ancho + b.ancho) / 2 + separacion
    && Math.abs(a.y - b.y) < (a.alto + b.alto) / 2 + separacion;
}

/**
 * Dónde va cada rótulo del horizonte ("PLAYA SANTO DOMINGO · 11 km").
 *
 * Un rótulo suelto se para sobre su lugar con un alfiler derecho. Varios lugares
 * en casi la misma dirección (en Fundo Atalaya, cinco hacia la costa) no caben
 * así: escalonados uno sobre otro, los alfileres de arriba cruzaban el texto de
 * los de abajo. Juntarlos con un solo alfiler escondía que cada uno está en otro
 * sitio. Ahora cada lugar conserva su punto, y los rótulos de un grupo se apilan
 * a un costado, unidos a su punto por un alfiler en codo (sube y dobla). Para que
 * ningún codo cruce a otro, el punto más cercano al costado de los rótulos lleva
 * el rótulo más bajo.
 *
 * @param {{id: string, x: number, y: number, ancho: number}[]} rotulos
 *   dónde cae en pantalla el punto de cada lugar y el ancho de su píldora.
 * @param {{anchoPantalla?: number, alto?: number, alfiler?: number, aire?: number, margen?: number}} opciones
 *   ancho de la pantalla, alto de un escalón (píldora más respiro), largo del
 *   alfiler derecho, aire entre píldoras y cuánto se aparta la columna del punto.
 * @returns {Map<string, {cx: number, cy: number, lado: 'centro'|'derecha'|'izquierda', guia: number[][], anchoMaximo?: number}>}
 *   para cada rótulo, el punto donde se ancla la píldora (centro abajo si es
 *   'centro'; borde izquierdo o derecho y mitad de alto si es de costado) y el
 *   alfiler como polilínea desde el lugar; anchoMaximo si la píldora se tiene que
 *   cortar para caber al costado.
 */
export function acomodarReferencias(rotulos, {
  anchoPantalla = Infinity, alto = 32, alfiler = 22, aire = 6, margen = 14,
} = {}) {
  const altoPildora = alto - aire;
  const grupos = agruparPorChoque(rotulos, alfiler, altoPildora, aire);
  const unidades = grupos.map((grupo) => (grupo.length === 1
    ? unidadSuelta(grupo[0], alfiler, altoPildora)
    : unidadDeCostado(grupo, { anchoPantalla, alto, alfiler, altoPildora, margen })));
  // De abajo hacia arriba: la que igual choca con una ya puesta sube un escalón.
  const puestas = [];
  for (const unidad of unidades.sort((a, b) => b.caja.y1 - a.caja.y1)) {
    let subida = 0;
    const choca = (otra) => unidad.caja.x0 < otra.x1 + aire && otra.x0 < unidad.caja.x1 + aire
      && unidad.caja.y0 - subida < otra.y1 + aire && otra.y0 < unidad.caja.y1 - subida + aire;
    while (subida < 8 * alto && puestas.some(choca)) subida += alto;
    puestas.push({ ...unidad.caja, y0: unidad.caja.y0 - subida, y1: unidad.caja.y1 - subida });
    unidad.subir(subida);
  }
  const resultado = new Map();
  for (const unidad of unidades) for (const [id, puesto] of unidad.puestos) resultado.set(id, puesto);
  return resultado;
}

// Los rótulos cuyas píldoras, paradas cada una sobre su punto, se pisarían
// (directa o encadenadamente) forman un grupo.
function agruparPorChoque(rotulos, alfiler, altoPildora, aire) {
  const padre = rotulos.map((_, i) => i);
  const raiz = (i) => (padre[i] === i ? i : (padre[i] = raiz(padre[i])));
  for (let i = 0; i < rotulos.length; i += 1) {
    for (let j = i + 1; j < rotulos.length; j += 1) {
      const a = rotulos[i];
      const b = rotulos[j];
      if (Math.abs(a.x - b.x) < (a.ancho + b.ancho) / 2 + aire && Math.abs(a.y - b.y) < altoPildora + alfiler) {
        padre[raiz(i)] = raiz(j);
      }
    }
  }
  const grupos = new Map();
  rotulos.forEach((rotulo, i) => {
    const r = raiz(i);
    if (!grupos.has(r)) grupos.set(r, []);
    grupos.get(r).push(rotulo);
  });
  return [...grupos.values()];
}

function unidadSuelta(rotulo, alfiler, altoPildora) {
  const { id, x, y, ancho } = rotulo;
  const puesto = { cx: x, cy: y - alfiler, lado: 'centro', guia: [[x, y], [x, y - alfiler]] };
  return {
    caja: { x0: x - ancho / 2, x1: x + ancho / 2, y0: y - alfiler - altoPildora, y1: y - alfiler },
    puestos: [[id, puesto]],
    subir(d) { puesto.cy -= d; puesto.guia[1][1] -= d; },
  };
}

// Más angosta que esto la píldora ya no dice nada: mejor que se corra la columna.
const ANCHO_MINIMO_CORTADO = 110;

function unidadDeCostado(grupo, { anchoPantalla, alto, alfiler, altoPildora, margen }) {
  const anchoMayor = Math.max(...grupo.map((r) => r.ancho));
  const xMin = Math.min(...grupo.map((r) => r.x));
  const xMax = Math.max(...grupo.map((r) => r.x));
  // A la derecha si cabe; si no, a la izquierda si cabe. En un celular puede no
  // caber en ninguno: va del lado con más lugar y los nombres largos se cortan
  // con "…" (anchoMaximo), porque correr la columna encima de los puntos dejaba
  // los alfileres asomando entre las píldoras.
  const libreDerecha = anchoPantalla - 8 - (xMax + margen);
  const libreIzquierda = xMin - margen - 8;
  const derecha = libreDerecha >= anchoMayor || (libreIzquierda < anchoMayor && libreDerecha >= libreIzquierda);
  const libre = derecha ? libreDerecha : libreIzquierda;
  let borde = derecha ? xMax + margen : xMin - margen;
  let anchoMaximo;
  if (libre < anchoMayor && libre >= ANCHO_MINIMO_CORTADO) anchoMaximo = libre;
  else if (derecha) borde = Math.max(8, Math.min(borde, anchoPantalla - 8 - anchoMayor));
  else borde = Math.min(anchoPantalla - 8, Math.max(borde, 8 + anchoMayor));
  const anchoColumna = anchoMaximo ?? anchoMayor;
  // El punto más cercano a la columna lleva el rótulo más bajo: así el tramo
  // horizontal de cada codo pasa por sobre los alfileres que quedan más cerca.
  const orden = [...grupo].sort((a, b) => (derecha ? b.x - a.x : a.x - b.x));
  const base = Math.min(...grupo.map((r) => r.y)) - alfiler - altoPildora / 2;
  const puestos = orden.map((r, piso) => {
    const cy = base - piso * alto;
    const puesto = { cx: borde, cy, lado: derecha ? 'derecha' : 'izquierda', guia: [[r.x, r.y], [r.x, cy], [borde, cy]] };
    if (anchoMaximo !== undefined && r.ancho > anchoMaximo) puesto.anchoMaximo = anchoMaximo;
    return [r.id, puesto];
  });
  const altoTotal = (grupo.length - 1) * alto + altoPildora;
  return {
    caja: {
      x0: derecha ? borde : borde - anchoColumna, x1: derecha ? borde + anchoColumna : borde,
      y0: base + altoPildora / 2 - altoTotal, y1: base + altoPildora / 2,
    },
    puestos,
    subir(d) {
      for (const [, p] of puestos) { p.cy -= d; p.guia[1][1] -= d; p.guia[2][1] -= d; }
    },
  };
}
