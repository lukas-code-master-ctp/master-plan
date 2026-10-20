/**
 * Matemática de cámara para el visor 360.
 *
 * Mundo: X al este, Y al norte, Z arriba. Un punto se describe por (azimut,
 * elevación) en grados, igual que en la salida del pipeline. La misma base que
 * usa esta cámara alimenta el shader del panorama y el overlay SVG, así que la
 * imagen y los polígonos no pueden desincronizarse.
 */

const GRADOS = Math.PI / 180;

export const ELEVACION_MAXIMA = 88;
export const FOV_MINIMO = 22;
export const FOV_MAXIMO = 100;

export function direccion(azimut, elevacion) {
  const az = azimut * GRADOS;
  const el = elevacion * GRADOS;
  const c = Math.cos(el);
  return [c * Math.sin(az), c * Math.cos(az), Math.sin(el)];
}

export function anguloEntre(a, b) {
  const [ax, ay, az] = direccion(a[0], a[1]);
  const [bx, by, bz] = direccion(b[0], b[1]);
  const p = Math.max(-1, Math.min(1, ax * bx + ay * by + az * bz));
  return Math.acos(p) / GRADOS;
}

export class Camara {
  constructor({ azimut = 0, elevacion = -25, fov = 70 } = {}) {
    this.azimut = azimut;
    this.elevacion = elevacion;
    this.fov = fov;
  }

  apuntar(azimut, elevacion) {
    this.azimut = ((azimut % 360) + 360) % 360;
    this.elevacion = acotar(elevacion, -ELEVACION_MAXIMA, ELEVACION_MAXIMA);
  }

  girar(deltaAzimut, deltaElevacion) {
    this.apuntar(this.azimut + deltaAzimut, this.elevacion + deltaElevacion);
  }

  acercar(factor) {
    this.fov = acotar(this.fov * factor, FOV_MINIMO, FOV_MAXIMO);
  }

  /** Base ortonormal de la cámara: hacia dónde mira, su derecha y su arriba. */
  base() {
    const adelante = direccion(this.azimut, this.elevacion);
    const derecha = normalizar(cruz(adelante, [0, 0, 1]));
    const arriba = cruz(derecha, adelante);
    return { adelante, derecha, arriba };
  }

  /** Matriz 3x3 en orden de columnas, tal como la espera WebGL. */
  matriz() {
    const { adelante, derecha, arriba } = this.base();
    return new Float32Array([...derecha, ...arriba, ...adelante]);
  }

  tangenteMedioFov() {
    return Math.tan((this.fov / 2) * GRADOS);
  }

  /** (azimut, elevación) → coordenadas de cámara. */
  aCamara(azimut, elevacion) {
    const d = direccion(azimut, elevacion);
    const { adelante, derecha, arriba } = this.base();
    return [punto(d, derecha), punto(d, arriba), punto(d, adelante)];
  }

  /**
   * Proyecta un anillo de (azimut, elevación) a píxeles de pantalla.
   * Devuelve null si queda completamente detrás de la cámara.
   */
  proyectarAnillo(anillo, ancho, alto) {
    const enCamara = anillo.map(([az, el]) => this.aCamara(az, el));
    const recortado = recortarCerca(enCamara);
    if (recortado.length < 3) return null;
    return recortado.map((c) => this.aPantalla(c, ancho, alto));
  }

  aPantalla([x, y, z], ancho, alto) {
    const tan = this.tangenteMedioFov();
    const aspecto = ancho / alto;
    const ndcX = x / (z * tan * aspecto);
    const ndcY = y / (z * tan);
    return [((ndcX + 1) / 2) * ancho, ((1 - ndcY) / 2) * alto];
  }

  /** Píxel de pantalla → (azimut, elevación) del rayo que lo atraviesa. */
  desdePantalla(px, py, ancho, alto) {
    const tan = this.tangenteMedioFov();
    const aspecto = ancho / alto;
    const ndcX = (px / ancho) * 2 - 1;
    const ndcY = 1 - (py / alto) * 2;
    const { adelante, derecha, arriba } = this.base();
    const d = normalizar([
      derecha[0] * ndcX * tan * aspecto + arriba[0] * ndcY * tan + adelante[0],
      derecha[1] * ndcX * tan * aspecto + arriba[1] * ndcY * tan + adelante[1],
      derecha[2] * ndcX * tan * aspecto + arriba[2] * ndcY * tan + adelante[2],
    ]);
    return [
      ((Math.atan2(d[0], d[1]) / GRADOS) + 360) % 360,
      Math.asin(acotar(d[2], -1, 1)) / GRADOS,
    ];
  }

  /** Grados que abarca el ancho de la pantalla. Sirve para descartar rápido. */
  aperturaHorizontal(ancho, alto) {
    return (Math.atan(this.tangenteMedioFov() * (ancho / alto)) / GRADOS) * 2;
  }

  /** ¿Vale la pena proyectar algo centrado en esta dirección? */
  puedeVerse([azimut, elevacion], ancho, alto, margen = 1.35) {
    const radio = (Math.max(this.aperturaHorizontal(ancho, alto), this.fov) / 2) * margen;
    return anguloEntre([this.azimut, this.elevacion], [azimut, elevacion]) < radio + 20;
  }
}

/**
 * Recorta un polígono contra el plano cercano de la cámara (Sutherland-Hodgman).
 *
 * Sin esto, un vértice que queda detrás del observador se proyecta invertido y el
 * polígono aparece dado vuelta cruzando la pantalla.
 */
export function recortarCerca(puntos, epsilon = 1e-3) {
  if (!puntos.length) return [];
  const salida = [];
  for (let i = 0; i < puntos.length; i++) {
    const actual = puntos[i];
    const previo = puntos[(i - 1 + puntos.length) % puntos.length];
    const dentroActual = actual[2] > epsilon;
    const dentroPrevio = previo[2] > epsilon;

    if (dentroActual !== dentroPrevio) {
      const t = (epsilon - previo[2]) / (actual[2] - previo[2]);
      salida.push([
        previo[0] + (actual[0] - previo[0]) * t,
        previo[1] + (actual[1] - previo[1]) * t,
        epsilon,
      ]);
    }
    if (dentroActual) salida.push(actual);
  }
  return salida;
}

export function acotar(valor, minimo, maximo) {
  return Math.min(maximo, Math.max(minimo, valor));
}

function cruz(a, b) {
  return [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ];
}

function punto(a, b) {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function normalizar(v) {
  const largo = Math.hypot(v[0], v[1], v[2]) || 1;
  return [v[0] / largo, v[1] / largo, v[2] / largo];
}

const RUMBOS = ['Norte', 'Noreste', 'Este', 'Sureste', 'Sur', 'Suroeste', 'Oeste', 'Noroeste'];

const RUMBOS_CORTOS = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'];

const octante = (azimut) => Math.round((((azimut % 360) + 360) % 360) / 45) % RUMBOS.length;

/** "Noreste": el punto cardinal (de ocho) más cercano a un azimut en grados. */
export function rumboCardinal(azimut) {
  return RUMBOS[octante(azimut)];
}

/** "NE": lo mismo, abreviado como en una brújula. */
export function rumboCorto(azimut) {
  return RUMBOS_CORTOS[octante(azimut)];
}

// --- Movimiento ----------------------------------------------------------------
//
// Arrastrar y soltar dejaba la cámara clavada en seco, la rueda saltaba de a
// escalones y tocar una parcela teletransportaba la vista. Lo que sigue es lo que
// hace que se sienta como mover algo con peso: inercia al soltar, zoom que llega
// suave y vuelos cortos de un encuadre a otro.

// Cuánto tarda la inercia en perder dos tercios de su velocidad. Con más se siente
// resbaloso; con menos, que no hubo inercia.
export const FRENADO_MS = 320;
// Solo cuentan los últimos movimientos del dedo: lo de antes ya no es el gesto con
// que se soltó, y un dedo que se detuvo antes de soltar no debe lanzar nada.
export const VENTANA_INERCIA_MS = 90;
// Por debajo de esto (grados por milisegundo) la inercia ya no se nota.
export const VELOCIDAD_MINIMA = 0.004;
// Más rápido que esto es un tirón del dedo y no un giro: se acota.
export const VELOCIDAD_MAXIMA = 0.6;

/**
 * La velocidad con que se soltó el arrastre, en grados por milisegundo, a partir
 * de las muestras {t, azimut, elevacion} (el delta de cada movimiento). Cuentan los
 * movimientos de la última ventana, medidos desde el anterior a ellos: un teléfono
 * lento manda pocos eventos y con uno solo en la ventana igual hay impulso. Cero si
 * el dedo se quedó quieto antes de soltar.
 */
export function velocidadAlSoltar(muestras, ahora, ventana = VENTANA_INERCIA_MS) {
  const primera = muestras.findIndex((m) => ahora - m.t <= ventana);
  if (primera < 0) return { azimut: 0, elevacion: 0 };
  const recientes = muestras.slice(primera);
  // El movimiento anterior sirve de punto de partida si fue parte del mismo gesto;
  // si es de antes de una pausa, se mide desde el primero de la ventana.
  const previa = muestras[primera - 1];
  const conPrevia = Boolean(previa) && recientes[0].t - previa.t <= ventana;
  const desde = conPrevia ? previa.t : recientes[0].t;
  const duracion = Math.max(recientes.at(-1).t - desde, 16);
  const suma = recientes.slice(conPrevia ? 0 : 1).reduce(
    (total, m) => ({ azimut: total.azimut + m.azimut, elevacion: total.elevacion + m.elevacion }),
    { azimut: 0, elevacion: 0 });
  const acotada = (v) => acotar(v / duracion, -VELOCIDAD_MAXIMA, VELOCIDAD_MAXIMA);
  return { azimut: acotada(suma.azimut), elevacion: acotada(suma.elevacion) };
}

/** La velocidad que queda tras `dt` milisegundos de frenado. */
export function frenar(velocidad, dt, frenadoMs = FRENADO_MS) {
  const factor = Math.exp(-dt / frenadoMs);
  return { azimut: velocidad.azimut * factor, elevacion: velocidad.elevacion * factor };
}

/** Diferencia de azimut por el camino corto: de 350° a 10° son +20°, no −340°. */
export function giroMasCorto(desde, hasta) {
  return ((((hasta - desde) % 360) + 540) % 360) - 180;
}

/** Arranca y llega despacio. t entre 0 y 1. */
export function suavizar(t) {
  const x = acotar(t, 0, 1);
  return x < 0.5 ? 4 * x * x * x : 1 - ((-2 * x + 2) ** 3) / 2;
}

/**
 * El tamaño de las pastillas con los números fijos, como fracción del normal.
 *
 * Todas iguales y siempre del mismo tamaño, como en los masterplan 360 que ya
 * conocen los compradores: cada una a la medida de su parcela daba números enormes
 * adelante e ilegibles atrás. En pantallas angostas (el celular) van un poco más
 * chicas, para que se vea el campo y no solo números.
 */
export function escalaComunDeRotulos(anchoPantallaPx) {
  return anchoPantallaPx <= 640 ? 0.9 : 1;
}
