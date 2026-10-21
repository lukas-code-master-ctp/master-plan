/**
 * Dónde se apoya el globo de la parcela elegida.
 *
 * La punta de la patita tiene que caer sobre la parcela. Antes se ponía en la
 * columna del centro y a la altura del vértice más alto: en una parcela larga y
 * cruzada en diagonal (Hacienda Vichuquén, la 464) ese vértice queda en una
 * esquina, y la punta caía en el terreno de al lado, como si el número fuera de
 * otra parcela. Ahora la punta va al borde de arriba de la parcela justo bajo el
 * globo, y el globo sube solo lo necesario para no tapar ese tramo de la parcela.
 */

/**
 * @param {[number, number][]} pixeles el contorno de la parcela en pantalla.
 * @param {number} anchoGlobo lo que ocupa el globo a lo ancho, en píxeles.
 * @returns {{x: number, apoyo: number, tope: number} | null} la columna del globo,
 *   dónde toca la punta el borde de la parcela y el borde más alto bajo el globo.
 */
export function apoyoDelGlobo(pixeles, anchoGlobo = 0) {
  if (!pixeles?.length) return null;
  const x = columnaCentral(pixeles);
  const apoyo = bordeSuperiorEn(pixeles, x) ?? Math.min(...pixeles.map(([, y]) => y));
  const medio = anchoGlobo / 2;
  let tope = apoyo;
  for (const borde of [bordeSuperiorEn(pixeles, x - medio), bordeSuperiorEn(pixeles, x + medio)]) {
    if (borde != null) tope = Math.min(tope, borde);
  }
  // Entre los dos costados del globo el contorno es recto salvo en sus vértices.
  for (const [px, py] of pixeles) {
    if (px >= x - medio && px <= x + medio) tope = Math.min(tope, py);
  }
  return { x, apoyo, tope };
}

/**
 * La x del centro de área. El promedio de los vértices se corre hacia donde el
 * dibujo tiene más puntos (una curva del camino trae decenas) y no hacia donde
 * está la parcela.
 */
function columnaCentral(pixeles) {
  let area = 0;
  let suma = 0;
  for (let i = 0; i < pixeles.length; i++) {
    const [x0, y0] = pixeles[i];
    const [x1, y1] = pixeles[(i + 1) % pixeles.length];
    const cruz = x0 * y1 - x1 * y0;
    area += cruz;
    suma += (x0 + x1) * cruz;
  }
  if (Math.abs(area) > 1e-6) return suma / (3 * area);
  return pixeles.reduce((total, [px]) => total + px, 0) / pixeles.length;
}

/** El punto más alto (menor y) del contorno en la columna x, o null si no la cruza. */
function bordeSuperiorEn(pixeles, x) {
  let mejor = null;
  for (let i = 0; i < pixeles.length; i++) {
    const [x0, y0] = pixeles[i];
    const [x1, y1] = pixeles[(i + 1) % pixeles.length];
    if (x < Math.min(x0, x1) || x > Math.max(x0, x1)) continue;
    const y = x0 === x1 ? Math.min(y0, y1) : y0 + ((x - x0) / (x1 - x0)) * (y1 - y0);
    if (mejor == null || y < mejor) mejor = y;
  }
  return mejor;
}
