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
