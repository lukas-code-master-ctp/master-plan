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
 * Varios lugares en casi la misma dirección (en Fundo Atalaya, cinco hacia la
 * costa) se escalonaban uno sobre otro, cada uno con su alfiler: los alfileres de
 * arriba cruzaban el texto de los de abajo y los puntos quedaban a un píxel uno
 * del otro. Ahora el lugar cuyo punto cae bajo la píldora de otro (casi la
 * misma dirección) se suma a la columna de ese, que lleva un solo alfiler, el más
 * cercano abajo. Las columnas que igual chocan con otra suben de escalón.
 *
 * @param {{id: string, x: number, y: number, ancho: number, distancia: number}[]} rotulos
 *   dónde cae en pantalla el punto de cada lugar, el ancho de su píldora y sus km.
 * @param {{alto?: number, cercania?: number, aire?: number, maximo?: number}} opciones
 *   alto de un escalón, a cuántos px de alto dos puntos son "el mismo sitio", aire lateral
 *   entre columnas y hasta qué escalón se sube buscando lugar.
 * @returns {Map<string, {x: number, y: number, escalon: number, conAlfiler: boolean, columna: number}>}
 *   para cada rótulo, el punto donde se para (el de su columna), su escalón, si
 *   dibuja el alfiler y el punto, y el orden de su columna (abajo primero).
 */
export function acomodarReferencias(rotulos, { alto = 32, cercania = 24, aire = 6, maximo = 8 } = {}) {
  const columnas = [];
  for (const rotulo of [...rotulos].sort((a, b) => a.distancia - b.distancia)) {
    const suya = columnas.find(({ base }) =>
      Math.abs(base.x - rotulo.x) < base.ancho / 2 && Math.abs(base.y - rotulo.y) < cercania);
    if (suya) suya.miembros.push(rotulo);
    else columnas.push({ base: rotulo, miembros: [rotulo] });
  }
  const puestas = [];
  const resultado = new Map();
  // De abajo hacia arriba en pantalla: la columna más baja queda en el escalón 0.
  for (const columna of columnas.sort((a, b) => b.base.y - a.base.y)) {
    const { x, y } = columna.base;
    const ancho = Math.max(...columna.miembros.map((m) => m.ancho));
    const pisos = columna.miembros.length;
    let escalon = 0;
    const choca = (otra) => Math.abs(otra.x - x) < (otra.ancho + ancho) / 2 + aire
      && Math.abs(otra.y - y) < alto
      && escalon < otra.escalon + otra.pisos && otra.escalon < escalon + pisos;
    while (escalon < maximo && puestas.some(choca)) escalon += 1;
    puestas.push({ x, y, ancho, pisos, escalon });
    columna.miembros.forEach((miembro, piso) => {
      resultado.set(miembro.id, { x, y, escalon: escalon + piso, conAlfiler: piso === 0, columna: piso });
    });
  }
  return resultado;
}
