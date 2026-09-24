/**
 * Visor 360.
 *
 * El panorama se dibuja con un solo cuadrilátero a pantalla completa: el shader
 * convierte la dirección de cada píxel a coordenada equirectangular. No hay malla
 * de esfera, no hay costuras, y el overlay SVG usa exactamente la misma cámara,
 * así que imagen y polígonos no pueden desincronizarse.
 */
import { Camara, acotar } from './camara.js';

const VERTICE = `
attribute vec2 aPos;
varying vec2 vNdc;
void main() {
  vNdc = aPos;
  gl_Position = vec4(aPos, 0.0, 1.0);
}`;

const FRAGMENTO = `
precision highp float;
varying vec2 vNdc;
uniform mat3 uBase;
uniform float uTan;
uniform float uAspecto;
uniform float uRumbo0;
uniform sampler2D uTextura;

void main() {
  vec3 dir = normalize(uBase * vec3(vNdc.x * uTan * uAspecto, vNdc.y * uTan, 1.0));
  float az = degrees(atan(dir.x, dir.y));
  float el = degrees(asin(clamp(dir.z, -1.0, 1.0)));
  gl_FragColor = texture2D(uTextura, vec2((az - uRumbo0) / 360.0, (90.0 - el) / 180.0));
}`;

const ARRASTRE_MINIMO_PX = 5;
// Por debajo de esto las pastillas se amontonan y tapan el terreno.
const ANCHO_MINIMO_ETIQUETA_PX = 42;
const SVG_NS = 'http://www.w3.org/2000/svg';

export class Visor {
  constructor(elemento, { alElegirParcela, alPasarSobreParcela, alMoverCamara, rotuloDe } = {}) {
    this.elemento = elemento;
    this.lienzo = elemento.querySelector('canvas');
    this.svg = elemento.querySelector('svg');
    this.alElegirParcela = alElegirParcela ?? (() => {});
    this.alPasarSobreParcela = alPasarSobreParcela ?? (() => {});
    this.alMoverCamara = alMoverCamara ?? (() => {});

    this.camara = new Camara();
    this.vista = null;
    this.overlay = new Map();
    this.referencias = [];
    this.nodosReferencia = [];
    this.capaReferencias = null;
    this.nodos = new Map();
    this.seleccionada = null;
    this.estiloParcela = () => ({ color: '#ffffff', texto: '#1c1a17', atenuada: false });
    this.rotuloDe = rotuloDe ?? ((id) => id.replace(/^A/, ''));
    this.cargaEnCurso = 0;
    this.cuadroPedido = false;

    this._iniciarWebgl();
    this._conectarEntradas();

    this.observador = new ResizeObserver(() => this.redimensionar());
    this.observador.observe(elemento);

    // En una pestaña de fondo el navegador no corre ResizeObserver ni
    // requestAnimationFrame, así que el visor quedaría en blanco hasta que el
    // usuario la mire. Al volverse visible se redimensiona y se repinta.
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) this.redimensionar();
    });

    this.redimensionar();
  }

  // --- WebGL -----------------------------------------------------------------

  _iniciarWebgl() {
    const gl = this.lienzo.getContext('webgl', {
      antialias: false,
      alpha: false,
      powerPreference: 'high-performance',
    });
    if (!gl) throw new Error('Tu navegador no tiene WebGL disponible.');
    this.gl = gl;

    const programa = crearPrograma(gl, VERTICE, FRAGMENTO);
    gl.useProgram(programa);
    this.programa = programa;

    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const aPos = gl.getAttribLocation(programa, 'aPos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    this.uniformes = {
      base: gl.getUniformLocation(programa, 'uBase'),
      tan: gl.getUniformLocation(programa, 'uTan'),
      aspecto: gl.getUniformLocation(programa, 'uAspecto'),
      rumbo0: gl.getUniformLocation(programa, 'uRumbo0'),
    };

    this.textura = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.textura);
    // Sin mipmaps: el visor casi siempre amplía, y los mipmaps producirían una
    // costura visible en el meridiano donde la derivada de u salta.
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, 1, 1, 0, gl.RGB, gl.UNSIGNED_BYTE,
                  new Uint8Array([12, 16, 22]));

    this.maxTextura = gl.getParameter(gl.MAX_TEXTURE_SIZE);
  }

  /** Niveles que conviene pedir en este dispositivo, del más liviano al mejor. */
  _nivelesUtiles(imagenes) {
    const niveles = ['previa', 'media'];
    const anchoUtil = this.elemento.clientWidth * (window.devicePixelRatio || 1);
    if (this.maxTextura >= 8192 && anchoUtil >= 900 && imagenes.alta) niveles.push('alta');
    return niveles.filter((n) => imagenes[n]);
  }

  // --- Vista -----------------------------------------------------------------

  async mostrarVista(vista, overlay, { avisar, referencias = [] } = {}) {
    this.vista = vista;
    this.overlay = overlay;
    this.referencias = referencias;
    this._limpiarNodos();
    this._pintar();

    const token = ++this.cargaEnCurso;
    const niveles = this._nivelesUtiles(vista.imagenes);

    for (const nivel of niveles) {
      avisar?.(nivel === niveles.at(-1) ? null : 'Cargando vista…');
      let imagen;
      try {
        imagen = await cargarImagen(vista.imagenes[nivel]);
      } catch (error) {
        if (nivel === niveles[0]) throw error;
        break;   // un nivel de más calidad que falla no es motivo para romper nada
      }
      if (token !== this.cargaEnCurso) return;   // cambiaron de vista mientras cargaba
      this._subirTextura(imagen);
      this._pintar();
    }
    avisar?.(null);
  }

  _subirTextura(imagen) {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.textura);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, imagen);
  }

  // --- Cámara ----------------------------------------------------------------

  apuntarA(azimut, elevacion = this.camara.elevacion, fov = this.camara.fov) {
    this.camara.apuntar(azimut, elevacion);
    this.camara.fov = acotar(fov, 22, 100);
    this._pintar();
  }

  /** Factor menor que 1 acerca; mayor que 1 aleja. */
  acercar(factor) {
    this.camara.acercar(factor);
    this._pintar();
  }

  /**
   * Apunta la cámara hacia donde están las parcelas de esta vista.
   *
   * Sin esto el visor abre mirando al norte, y desde varias posiciones de vuelo
   * eso es un cerro vacío: las parcelas quedan todas hacia otro lado.
   */
  encuadrarParcelas() {
    if (!this.overlay.size) return false;

    let x = 0;
    let y = 0;
    let elevacion = 0;
    let peso = 0;
    for (const parcela of this.overlay.values()) {
      // Raíz del área: pondera hacia lo que se ve grande sin que la parcela
      // que está justo bajo el dron se lleve todo el encuadre.
      const w = Math.sqrt(Math.max(parcela.area_angular, 0.01));
      const azimut = (parcela.centro[0] * Math.PI) / 180;
      x += Math.cos(azimut) * w;
      y += Math.sin(azimut) * w;
      elevacion += parcela.centro[1] * w;
      peso += w;
    }

    const azimut = (Math.atan2(y, x) * 180) / Math.PI;
    // Se acota para dejar el horizonte dentro del cuadro: es lo que da la
    // sensación de estar volando y no de mirar el suelo.
    this.apuntarA(azimut, acotar(elevacion / peso, -42, -9), 75);
    return true;
  }

  /** Centra la cámara en una parcela y ajusta el zoom para que llene el encuadre. */
  enfocarParcela(id) {
    const parcela = this.overlay.get(id);
    if (!parcela) return false;
    const [azimut, elevacion] = parcela.centro;
    const diametro = 2 * Math.sqrt(Math.max(parcela.area_angular, 0.5) / Math.PI);
    this.apuntarA(azimut, elevacion, acotar(diametro * 3.2, 25, 90));
    return true;
  }

  redimensionar() {
    const proporcion = Math.min(window.devicePixelRatio || 1, 2);
    const ancho = this.elemento.clientWidth;
    const alto = this.elemento.clientHeight;
    if (!ancho || !alto) {
      // Todavía sin layout. Se reintenta en vez de quedarse en blanco para siempre.
      clearTimeout(this.reintentoMedida);
      this.reintentoMedida = setTimeout(() => this.redimensionar(), 120);
      return;
    }
    this.lienzo.width = Math.round(ancho * proporcion);
    this.lienzo.height = Math.round(alto * proporcion);
    this.svg.setAttribute('viewBox', `0 0 ${ancho} ${alto}`);
    this.ancho = ancho;
    this.alto = alto;
    this._pintar();
  }

  // --- Dibujo ----------------------------------------------------------------

  _pintar() {
    if (this.cuadroPedido) return;
    this.cuadroPedido = true;
    requestAnimationFrame(() => {
      this.cuadroPedido = false;
      this._dibujarPanorama();
      this._dibujarOverlay();
      this.alMoverCamara(this.camara);
    });
  }

  _dibujarPanorama() {
    const gl = this.gl;
    if (!this.lienzo.width) return;
    gl.viewport(0, 0, this.lienzo.width, this.lienzo.height);
    gl.useProgram(this.programa);
    gl.uniformMatrix3fv(this.uniformes.base, false, this.camara.matriz());
    gl.uniform1f(this.uniformes.tan, this.camara.tangenteMedioFov());
    gl.uniform1f(this.uniformes.aspecto, this.lienzo.width / this.lienzo.height);
    gl.uniform1f(this.uniformes.rumbo0, this.vista?.rumbo0 ?? 0);
    gl.bindTexture(gl.TEXTURE_2D, this.textura);
    gl.drawArrays(gl.TRIANGLES, 0, 3);
  }

  _dibujarOverlay() {
    const { ancho, alto } = this;
    if (!ancho) return;
    this._dibujarReferencias(ancho, alto);

    for (const [id, parcela] of this.overlay) {
      const nodo = this._nodoDe(id);
      if (!this.camara.puedeVerse(parcela.centro, ancho, alto)) {
        nodo.grupo.style.display = 'none';
        continue;
      }
      const pixeles = this.camara.proyectarAnillo(parcela.anillo, ancho, alto);
      if (!pixeles || fueraDePantalla(pixeles, ancho, alto)) {
        nodo.grupo.style.display = 'none';
        continue;
      }

      const estilo = this.estiloParcela(id);
      nodo.grupo.style.display = '';
      nodo.grupo.style.color = estilo.color;
      nodo.grupo.classList.toggle('parcela--atenuada', estilo.atenuada);
      nodo.grupo.classList.toggle('parcela--seleccionada', id === this.seleccionada);
      nodo.forma.setAttribute('d', aRuta(pixeles));

      // La pastilla es el objetivo de clic real: un número redondo se acierta
      // mucho mejor que el borde de un polígono, sobre todo con el dedo.
      const anchoEnPantalla = extension(pixeles, 0);
      if (anchoEnPantalla >= ANCHO_MINIMO_ETIQUETA_PX && !estilo.atenuada) {
        const [cx, cy] = centro(pixeles);
        nodo.pastilla.setAttribute('transform', `translate(${cx.toFixed(1)} ${cy.toFixed(1)})`);
        nodo.disco.style.fill = estilo.color;
        nodo.numero.style.fill = estilo.texto;
        nodo.pastilla.style.display = '';
      } else {
        nodo.pastilla.style.display = 'none';
      }
    }
  }

  _nodoDe(id) {
    let nodo = this.nodos.get(id);
    if (nodo) return nodo;

    const grupo = document.createElementNS(SVG_NS, 'g');
    grupo.setAttribute('class', 'parcela');
    const forma = document.createElementNS(SVG_NS, 'path');
    forma.setAttribute('class', 'parcela__forma');

    const pastilla = document.createElementNS(SVG_NS, 'g');
    pastilla.setAttribute('class', 'parcela__pastilla');
    const disco = document.createElementNS(SVG_NS, 'circle');
    disco.setAttribute('class', 'parcela__disco');
    const numero = document.createElementNS(SVG_NS, 'text');
    numero.setAttribute('class', 'parcela__numero');
    numero.setAttribute('dy', '0.34em');
    numero.textContent = this.rotuloDe(id);
    pastilla.append(disco, numero);

    grupo.append(forma, pastilla);

    grupo.addEventListener('pointerenter', () => this.alPasarSobreParcela(id));
    grupo.addEventListener('pointerleave', () => this.alPasarSobreParcela(null));
    this.svg.append(grupo);

    nodo = { grupo, forma, pastilla, disco, numero };
    this.nodos.set(id, nodo);
    return nodo;
  }

  _limpiarNodos() {
    this.svg.replaceChildren();
    this.nodos.clear();
    this.nodosReferencia = [];
    this.capaReferencias = null;
  }

  // Hitos del horizonte ("CAUQUENES · 12 KM"): un tick y un rótulo, sin interacción.
  _dibujarReferencias(ancho, alto) {
    this.referencias.forEach((referencia, indice) => {
      const nodo = this._nodoReferencia(indice, referencia);
      const [x, y, z] = this.camara.aCamara(referencia.az, referencia.el);
      if (z <= 0.05 || !this.camara.puedeVerse([referencia.az, referencia.el], ancho, alto, 1.0)) {
        nodo.style.display = 'none';
        return;
      }
      const [px, py] = this.camara.aPantalla([x, y, z], ancho, alto);
      nodo.style.display = '';
      nodo.setAttribute('transform', `translate(${px.toFixed(1)} ${py.toFixed(1)})`);
    });
  }

  _nodoReferencia(indice, referencia) {
    let nodo = this.nodosReferencia[indice];
    if (nodo) return nodo;
    nodo = document.createElementNS(SVG_NS, 'g');
    nodo.setAttribute('class', 'referencia');
    const tick = document.createElementNS(SVG_NS, 'line');
    tick.setAttribute('class', 'referencia__tick');
    tick.setAttribute('y1', '-3');
    tick.setAttribute('y2', '-22');
    const texto = document.createElementNS(SVG_NS, 'text');
    texto.setAttribute('class', 'referencia__texto');
    texto.setAttribute('y', '-28');
    texto.textContent = `${referencia.nombre} · ${Math.round(referencia.distancia_km)} km`.toUpperCase();
    nodo.append(tick, texto);
    // Van en su propia capa, antes que las parcelas: quedan debajo y nadie que
    // recorra los hijos del overlay buscando parcelas se los encuentra.
    if (!this.capaReferencias) {
      this.capaReferencias = document.createElementNS(SVG_NS, 'g');
      this.capaReferencias.setAttribute('class', 'referencias');
      this.svg.prepend(this.capaReferencias);
    }
    this.capaReferencias.append(nodo);
    this.nodosReferencia[indice] = nodo;
    return nodo;
  }

  marcarSeleccionada(id) {
    this.seleccionada = id;
    this._pintar();
  }

  aplicarEstilos(estiloParcela) {
    this.estiloParcela = estiloParcela;
    this._pintar();
  }

  // --- Entradas --------------------------------------------------------------

  _conectarEntradas() {
    const punteros = new Map();
    let arrastre = null;
    let separacionPrevia = 0;

    const elemento = this.elemento;

    elemento.addEventListener('pointerdown', (evento) => {
      try {
        elemento.setPointerCapture(evento.pointerId);
      } catch {
        // Sin captura el arrastre solo deja de seguir al puntero si sale del
        // visor. No es motivo para abortar el resto del manejador.
      }
      punteros.set(evento.pointerId, { x: evento.clientX, y: evento.clientY });
      if (punteros.size === 1) {
        arrastre = { x: evento.clientX, y: evento.clientY, recorrido: 0 };
      }
      separacionPrevia = 0;
    });

    elemento.addEventListener('pointermove', (evento) => {
      if (!punteros.has(evento.pointerId)) return;
      punteros.set(evento.pointerId, { x: evento.clientX, y: evento.clientY });

      if (punteros.size >= 2) {
        const separacion = separacionDe(punteros);
        if (separacionPrevia) this.camara.acercar(separacionPrevia / separacion);
        separacionPrevia = separacion;
        this._pintar();
        return;
      }

      if (!arrastre) return;
      const dx = evento.clientX - arrastre.x;
      const dy = evento.clientY - arrastre.y;
      arrastre.recorrido += Math.hypot(dx, dy);
      arrastre.x = evento.clientX;
      arrastre.y = evento.clientY;

      const gradosPorPixel = this.camara.fov / Math.max(this.alto, 1);
      this.camara.girar(-dx * gradosPorPixel, dy * gradosPorPixel);
      this._pintar();
    });

    const soltar = (evento) => {
      punteros.delete(evento.pointerId);
      if (punteros.size < 2) separacionPrevia = 0;
      if (punteros.size === 0 && arrastre) {
        if (arrastre.recorrido < ARRASTRE_MINIMO_PX) this._clic(evento);
        arrastre = null;
      }
    };
    elemento.addEventListener('pointerup', soltar);
    elemento.addEventListener('pointercancel', soltar);

    elemento.addEventListener('wheel', (evento) => {
      evento.preventDefault();
      this.camara.acercar(Math.exp(evento.deltaY * 0.0012));
      this._pintar();
    }, { passive: false });

    elemento.tabIndex = 0;
    elemento.addEventListener('keydown', (evento) => {
      const paso = evento.shiftKey ? 15 : 5;
      const acciones = {
        ArrowLeft: () => this.camara.girar(-paso, 0),
        ArrowRight: () => this.camara.girar(paso, 0),
        ArrowUp: () => this.camara.girar(0, paso),
        ArrowDown: () => this.camara.girar(0, -paso),
        '+': () => this.camara.acercar(0.85),
        '=': () => this.camara.acercar(0.85),
        '-': () => this.camara.acercar(1.18),
      };
      const accion = acciones[evento.key];
      if (!accion) return;
      evento.preventDefault();
      accion();
      this._pintar();
    });
  }

  _clic(evento) {
    const objetivo = document.elementFromPoint(evento.clientX, evento.clientY);
    const grupo = objetivo?.closest?.('.parcela');
    if (!grupo) {
      this.alElegirParcela(null);
      return;
    }
    for (const [id, nodo] of this.nodos) {
      if (nodo.grupo === grupo) {
        this.alElegirParcela(id);
        return;
      }
    }
  }
}

// --- Utilidades ---------------------------------------------------------------

function crearPrograma(gl, fuenteVertice, fuenteFragmento) {
  const programa = gl.createProgram();
  for (const [tipo, fuente] of [[gl.VERTEX_SHADER, fuenteVertice],
                                [gl.FRAGMENT_SHADER, fuenteFragmento]]) {
    const shader = gl.createShader(tipo);
    gl.shaderSource(shader, fuente);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error(`Shader: ${gl.getShaderInfoLog(shader)}`);
    }
    gl.attachShader(programa, shader);
  }
  gl.linkProgram(programa);
  if (!gl.getProgramParameter(programa, gl.LINK_STATUS)) {
    throw new Error(`Programa: ${gl.getProgramInfoLog(programa)}`);
  }
  return programa;
}

function cargarImagen(ruta) {
  return new Promise((resolver, rechazar) => {
    const imagen = new Image();
    imagen.decoding = 'async';
    imagen.onload = () => resolver(imagen);
    imagen.onerror = () => rechazar(new Error(`No pude cargar ${ruta}`));
    imagen.src = ruta;
  });
}

function aRuta(pixeles) {
  let ruta = `M${pixeles[0][0].toFixed(1)} ${pixeles[0][1].toFixed(1)}`;
  for (let i = 1; i < pixeles.length; i++) {
    ruta += `L${pixeles[i][0].toFixed(1)} ${pixeles[i][1].toFixed(1)}`;
  }
  return `${ruta}Z`;
}

function extension(pixeles, eje) {
  let minimo = Infinity;
  let maximo = -Infinity;
  for (const punto of pixeles) {
    minimo = Math.min(minimo, punto[eje]);
    maximo = Math.max(maximo, punto[eje]);
  }
  return maximo - minimo;
}

function centro(pixeles) {
  let x = 0;
  let y = 0;
  for (const punto of pixeles) {
    x += punto[0];
    y += punto[1];
  }
  return [x / pixeles.length, y / pixeles.length];
}

function fueraDePantalla(pixeles, ancho, alto) {
  const margen = Math.max(ancho, alto);
  return pixeles.every(([x, y]) =>
    x < -margen || x > ancho + margen || y < -margen || y > alto + margen);
}

function separacionDe(punteros) {
  const [a, b] = [...punteros.values()];
  return Math.hypot(a.x - b.x, a.y - b.y) || 1;
}
