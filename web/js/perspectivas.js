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
