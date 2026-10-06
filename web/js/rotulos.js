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
