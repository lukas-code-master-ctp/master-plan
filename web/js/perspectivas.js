/**
 * Moverse entre el plano y la vista aérea, en el teléfono.
 *
 * Sobre el plano flotan dos cosas: la franja de "Perspectivas aéreas" (un botón
 * por punto de vuelo, con sus alturas) y la tarjeta "Entrar a 360°", con una
 * miniatura de la panorámica recortada donde la persona estaba mirando.
 */
import { romano } from './datos.js';

const GRADOS_DE_LA_MINIATURA = 90;

/**
 * Cómo poner la panorámica equirectangular de fondo de una miniatura cuadrada
 * de `lado` px para que su centro sea lo que mira la cámara. Es la misma cuenta
 * que hace el visor en su sombreador: columna = (azimut − rumbo0) / 360 y
 * fila = (90 − elevación) / 180. Devuelve el tamaño de la imagen y su
 * desplazamiento, en px, para background-size y background-position.
 */
export function encuadreMiniatura({ azimut, elevacion }, rumbo0, lado, abertura = GRADOS_DE_LA_MINIATURA) {
  const ancho = (lado * 360) / abertura;
  const alto = ancho / 2;
  const columna = ((((azimut - rumbo0) % 360) + 360) % 360) / 360;
  const fila = (90 - elevacion) / 180;
  return { ancho, alto, x: lado / 2 - columna * ancho, y: lado / 2 - fila * alto };
}

/**
 * El loteo dibujado en una tarjeta de `lado` px, con el norte arriba y los
 * colores de estado: la miniatura de "Ver plano". Se dibuja de los polígonos y no
 * de teselas satelitales, así no depende de la red ni de dónde caiga el loteo en
 * la grilla de teselas. Los grados de longitud se acortan por el coseno de la
 * latitud, para que el loteo no salga estirado.
 */
export function miniPlano(parcelas, lado, colorDe, margen = 4) {
  const conPoligono = parcelas.filter((p) => p.poligono?.length);
  if (!conPoligono.length) return [];
  const vertices = conPoligono.flatMap((p) => p.poligono);
  const latMedia = vertices.reduce((suma, [, lat]) => suma + lat, 0) / vertices.length;
  const factor = Math.cos((latMedia * Math.PI) / 180);
  const xs = vertices.map(([lon]) => lon * factor);
  const ys = vertices.map(([, lat]) => lat);
  const [xMin, xMax, yMin, yMax] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const util = lado - 2 * margen;
  const escala = util / Math.max(xMax - xMin, yMax - yMin);
  // Centrado en la dimensión que sobra.
  const dx = margen + (util - (xMax - xMin) * escala) / 2;
  const dy = margen + (util - (yMax - yMin) * escala) / 2;
  return conPoligono.map((p) => ({
    color: colorDe(p.estado),
    puntos: p.poligono.map(([lon, lat]) => [dx + (lon * factor - xMin) * escala, dy + (yMax - lat) * escala]),
  }));
}

export function textoConteo(cantidad) {
  return `${cantidad} ${cantidad === 1 ? 'punto' : 'puntos'} de vuelo`;
}

/** Un botón por punto de vuelo. Elegir uno lleva a verlo en 360°. */
export function construirPerspectivas(fila, conteo, catalogo, alElegir) {
  const posiciones = catalogo.posiciones();
  conteo.textContent = textoConteo(posiciones.length);
  fila.replaceChildren(...posiciones.map(({ posicion }) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'perspectiva';
    boton.dataset.posicion = posicion;

    const disco = document.createElement('span');
    disco.className = 'perspectiva__disco';
    disco.textContent = romano(posicion);
    const nombre = document.createElement('strong');
    nombre.textContent = catalogo.nombrePunto(posicion);
    const alturas = document.createElement('small');
    alturas.textContent = catalogo.alturasDePunto(posicion);
    const textos = document.createElement('span');
    textos.className = 'perspectiva__textos';
    textos.append(nombre, alturas);

    boton.append(disco, textos);
    boton.addEventListener('click', () => alElegir(posicion));
    return boton;
  }));
}

export function marcarPerspectiva(fila, posicion) {
  for (const boton of fila.children) {
    boton.setAttribute('aria-pressed', String(Number(boton.dataset.posicion) === posicion));
  }
}

/** La miniatura de "Entrar a 360°": la panorámica liviana, donde se estaba mirando. */
export function pintarMiniatura(elemento, vista, camara) {
  if (!vista?.imagenes?.previa) return;
  const lado = elemento.clientWidth || 64;
  const mirada = camara ?? { azimut: vista.rumbo0 ?? 0, elevacion: -25 };
  const { ancho, alto, x, y } = encuadreMiniatura(mirada, vista.rumbo0 ?? 0, lado);
  elemento.style.backgroundImage = `url("${encodeURI(vista.imagenes.previa)}")`;
  elemento.style.backgroundSize = `${ancho}px ${alto}px`;
  elemento.style.backgroundPosition = `${x}px ${y}px`;
}

/** El mini plano de "Ver plano", dibujado una vez: el loteo no cambia de forma. */
export function pintarMiniPlano(svg, catalogo) {
  const lado = Number(svg.viewBox.baseVal?.width) || 56;
  const formas = miniPlano(catalogo.parcelas, lado, (estado) => catalogo.color(estado));
  svg.replaceChildren(...formas.map(({ color, puntos }) => {
    const poligono = document.createElementNS('http://www.w3.org/2000/svg', 'polygon');
    poligono.setAttribute('points', puntos.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' '));
    poligono.setAttribute('fill', color);
    return poligono;
  }));
}
