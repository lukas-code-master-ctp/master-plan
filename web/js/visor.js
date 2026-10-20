/**
 * Visor 360.
 *
 * El panorama se dibuja con un solo cuadrilátero a pantalla completa: el shader
 * convierte la dirección de cada píxel a coordenada equirectangular. No hay malla
 * de esfera, no hay costuras, y el overlay SVG usa exactamente la misma cámara,
 * así que imagen y polígonos no pueden desincronizarse.
 */
import {
  Camara, FOV_MAXIMO, FOV_MINIMO, VELOCIDAD_MINIMA, acotar, escalaDeRotulo, frenar, giroMasCorto,
  suavizar, velocidadAlSoltar,
} from './camara.js';
import { romano, textoReferencia, lejaniaReferencia } from './datos.js';
import { Gesto } from './gesto.js';
import { debeColapsar } from './grupos.js';
import { estaInsertado, ruedaAcerca } from './insertado.js';
import { rotulosSinChoques } from './rotulos.js';

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
const ALTO_PASTILLA = 26;
// La elegida se dibuja agrandada (.parcela--seleccionada en estilos.css): ocupa más.
const ESCALA_ELEGIDA = 1.22;
// El globo de la elegida flota sobre la parcela, unido por una patita, para no
// taparla: de lejos la parcela es más chica que su propio rótulo.
const PATITA_PX = 16;
// Aire mínimo entre dos pastillas para que cada número se lea por separado.
const SEPARACION_PASTILLAS = 3;
// Por debajo de esto las pastillas se amontonan y tapan el terreno.
const ANCHO_MINIMO_ETIQUETA_PX = 42;
// Lo que ocupa en pantalla un botón de punto 360 (la lupa, su nombre y la patita)
// en escritorio, por si el botón todavía no se puede medir. Ningún número de
// parcela se dibuja dentro.
const ANCHO_ZONA_PUNTO = 76;
// El alfiler de los rótulos del horizonte y cuánto sube uno que chocaría con otro
// (el alto de la píldora más un respiro).
const ALFILER_REFERENCIA = 22;
const ALTO_ESCALON_REFERENCIA = 32;
const ALTO_ZONA_PUNTO = 92;
// La burbuja de un grupo: más alta que una pastilla, porque dice más.
const ALTO_BURBUJA = 30;
// Por sobre las pastillas sueltas (que van hasta ~1e7) y bajo la elegida (1e9).
const PRIORIDAD_BURBUJA = 5e8;
const SVG_NS = 'http://www.w3.org/2000/svg';
// Lo que dura el vuelo de un encuadre a otro (al elegir una parcela, una burbuja o
// con las flechas). Más largo se siente lento; sin vuelo, se pierde dónde se estaba.
const VUELO_MS = 550;
// El paso de un punto a otro: sale acercándose y fundiéndose, entra de cerca y se
// abre. La llegada es más lenta: es cuando se mira dónde se está.
const SALIDA_MS = 520;
const LLEGADA_MS = 1100;
const ACERCAMIENTO_VIAJE = 0.5;
const VUELO_TECLA_MS = 180;
// Cuánto tarda el zoom de la rueda en llegar a donde se pidió.
const ZOOM_SUAVE_MS = 90;
const SIN_MOVIMIENTO = typeof window !== 'undefined'
  && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

export class Visor {
  constructor(elemento, {
    alElegirParcela, alPasarSobreParcela, alMoverCamara, alElegirPunto, rotuloDe, rotuloSeleccionadoDe,
    numerosFijos = false,
  } = {}) {
    this.elemento = elemento;
    this.lienzo = elemento.querySelector('canvas');
    this.svg = elemento.querySelector('svg');
    this.alElegirParcela = alElegirParcela ?? (() => {});
    this.alPasarSobreParcela = alPasarSobreParcela ?? (() => {});
    this.alMoverCamara = alMoverCamara ?? (() => {});
    this.alElegirPunto = alElegirPunto ?? (() => {});
    // Todos los números a la vista, achicándose, sin burbujas (proyecto.json).
    this.numerosFijos = numerosFijos;

    this.camara = new Camara();
    this.vista = null;
    this.overlay = new Map();
    this.referencias = [];
    this.nodosReferencia = [];
    this.caminos = [];
    this.nodosCamino = [];
    this.capaCaminos = null;
    // Los otros puntos de vuelo, para saltar a su 360 tocándolos en la foto. Son
    // botones de HTML sobre el SVG: quedan encima de las parcelas y se pueden
    // alcanzar con el teclado.
    this.puntos = [];
    // Los esteros: una línea azul con su nombre, bajo las parcelas.
    this.aguas = [];
    this.nodosAgua = [];
    this.capaAguas = null;
    this.capaPuntos = document.createElement('div');
    this.capaPuntos.className = 'puntos-360';
    elemento.append(this.capaPuntos);
    // Los hitos del horizonte, en HTML para que cada rótulo sea una píldora del
    // ancho de su texto: sobre cielo con nubes un texto suelto se perdía.
    this.capaReferencias = document.createElement('div');
    this.capaReferencias.className = 'referencias';
    elemento.append(this.capaReferencias);
    // La animación en curso (inercia, zoom suave o vuelo) y lo que la mueve.
    this.animacion = null;
    this.fovObjetivo = null;
    this.halo = null;
    this.nodos = new Map();
    // Grupos de parcelas vecinas (grupos.js): cuáles se ven como burbuja y cuál
    // abrió la persona tocándola.
    this.grupos = new Map();
    this.grupoDe = new Map();
    this.resumenDe = () => null;
    this.colapsados = new Set();
    this.grupoAbierto = null;
    this.nodosGrupo = new Map();
    this.seleccionada = null;
    this.estiloParcela = () => ({ color: '#ffffff', texto: '#1c1a17', atenuada: false });
    this.rotuloDe = rotuloDe ?? ((id) => id.replace(/^A/, ''));
    /** La elegida dice más (su precio): es la que la persona está mirando. */
    this.rotuloSeleccionadoDe = rotuloSeleccionadoDe ?? this.rotuloDe;
    this.cargaEnCurso = 0;
    this.cuadroPedido = false;
    this.insertado = estaInsertado();

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

  /**
   * Cambia a otra vista. Resuelve apenas está la primera calidad de la foto
   * (la previa, liviana): ahí ya se puede encuadrar. Las calidades mejores siguen
   * bajando por detrás y reemplazan la textura cuando llegan.
   *
   * La foto nueva y sus parcelas entran juntas: antes las parcelas de la vista
   * nueva se dibujaban un momento sobre la foto anterior. Devuelve false si
   * mientras tanto se pidió otra vista.
   */
  async mostrarVista(vista, overlay, {
    avisar, referencias = [], caminos = [], puntos = [], aguas = [],
  } = {}) {
    const token = ++this.cargaEnCurso;
    const niveles = this._nivelesUtiles(vista.imagenes);
    avisar?.('Cargando vista…');
    if (this.vista) this.lienzo.classList.add('cambiando');
    let primera;
    try {
      primera = await cargarImagen(vista.imagenes[niveles[0]]);
    } finally {
      if (token === this.cargaEnCurso) this.lienzo.classList.remove('cambiando');
    }
    if (token !== this.cargaEnCurso) return false;

    this.vista = vista;
    this.overlay = overlay;
    this.referencias = referencias;
    this.caminos = caminos;
    this.puntos = puntos;
    this.aguas = aguas;
    this._detener();
    this._limpiarNodos();
    this._crearPuntos();
    this._subirTextura(primera);
    this._pintar();
    avisar?.(null);
    this._mejorarCalidad(vista, niveles.slice(1), token);
    return true;
  }

  async _mejorarCalidad(vista, niveles, token) {
    for (const nivel of niveles) {
      let imagen;
      try {
        imagen = await cargarImagen(vista.imagenes[nivel]);
      } catch {
        return;   // un nivel de más calidad que falla no es motivo para romper nada
      }
      if (token !== this.cargaEnCurso) return;   // cambiaron de vista mientras cargaba
      this._subirTextura(imagen);
      this._pintar();
    }
  }

  _subirTextura(imagen) {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.textura);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGB, gl.RGB, gl.UNSIGNED_BYTE, imagen);
  }

  // --- Cámara ----------------------------------------------------------------

  /**
   * Lleva la cámara a ese encuadre. Con `animar` vuela hasta ahí, girando por el
   * camino corto: un salto en seco hace perder de vista dónde se estaba.
   */
  apuntarA(azimut, elevacion = this.camara.elevacion, fov = this.camara.fov, { animar = false, duracion = VUELO_MS } = {}) {
    this._detener();
    const destino = { azimut, elevacion, fov: acotar(fov, FOV_MINIMO, FOV_MAXIMO) };
    if (!animar || SIN_MOVIMIENTO) {
      this.camara.apuntar(destino.azimut, destino.elevacion);
      this.camara.fov = destino.fov;
      this._pintar();
      return;
    }
    const origen = { azimut: this.camara.azimut, elevacion: this.camara.elevacion, fov: this.camara.fov };
    const giro = giroMasCorto(origen.azimut, destino.azimut);
    let transcurrido = 0;
    this._animar((dt) => {
      transcurrido += dt;
      const t = suavizar(transcurrido / duracion);
      this.camara.apuntar(origen.azimut + giro * t, origen.elevacion + (destino.elevacion - origen.elevacion) * t);
      this.camara.fov = origen.fov + (destino.fov - origen.fov) * t;
      return transcurrido < duracion;
    });
  }

  /** Factor menor que 1 acerca; mayor que 1 aleja. Llega suave, como la rueda. */
  acercar(factor) {
    this._acercarSuave(factor);
  }

  // --- Animación -------------------------------------------------------------

  /**
   * Corre `paso(dt)` en cada cuadro hasta que devuelva false. Una sola animación a
   * la vez: la nueva reemplaza a la anterior.
   */
  _animar(paso) {
    this._detener();
    const animacion = { paso, previo: null, id: 0 };
    const cuadro = (ahora) => {
      if (this.animacion !== animacion) return;
      // El primer cuadro no sabe cuánto pasó; los demás, a lo más 50 ms, para que
      // una pestaña que vuelve del fondo no haga saltar la cámara.
      const dt = animacion.previo == null ? 16 : Math.min(ahora - animacion.previo, 50);
      animacion.previo = ahora;
      const sigue = paso(dt);
      this._pintar();
      if (sigue) animacion.id = requestAnimationFrame(cuadro);
      else this.animacion = null;
    };
    this.animacion = animacion;
    animacion.id = requestAnimationFrame(cuadro);
  }

  _detener() {
    if (this.animacion) cancelAnimationFrame(this.animacion.id);
    this.animacion = null;
    this.fovObjetivo = null;
  }

  /** Al soltar un arrastre con impulso, la vista sigue girando y se frena sola. */
  _lanzar(velocidad) {
    if (SIN_MOVIMIENTO) return;
    if (Math.hypot(velocidad.azimut, velocidad.elevacion) < VELOCIDAD_MINIMA) return;
    let actual = velocidad;
    this._animar((dt) => {
      this.camara.girar(actual.azimut * dt, actual.elevacion * dt);
      actual = frenar(actual, dt);
      return Math.hypot(actual.azimut, actual.elevacion) >= VELOCIDAD_MINIMA;
    });
  }

  /**
   * El zoom de la rueda y de los botones: se acumula en un objetivo y la cámara
   * llega a él en unos cuadros. Varios golpes de rueda seguidos suman, sin saltos.
   */
  _acercarSuave(factor) {
    const objetivo = acotar((this.fovObjetivo ?? this.camara.fov) * factor, FOV_MINIMO, FOV_MAXIMO);
    if (SIN_MOVIMIENTO) {
      this.camara.fov = objetivo;
      this._pintar();
      return;
    }
    if (this.fovObjetivo === null) {
      this._animar((dt) => {
        const k = 1 - Math.exp(-dt / ZOOM_SUAVE_MS);
        this.camara.fov += (this.fovObjetivo - this.camara.fov) * k;
        if (Math.abs(this.fovObjetivo - this.camara.fov) < 0.02) {
          this.camara.fov = this.fovObjetivo;
          this.fovObjetivo = null;
          return false;
        }
        return true;
      });
    }
    this.fovObjetivo = objetivo;
  }

  /**
   * Apunta la cámara hacia donde están las parcelas de esta vista.
   *
   * Sin esto el visor abre mirando al norte, y desde varias posiciones de vuelo
   * eso es un cerro vacío: las parcelas quedan todas hacia otro lado.
   */
  encuadrarParcelas() {
    const encuadre = this.encuadreDeParcelas();
    if (!encuadre) return false;
    this.apuntarA(...encuadre);
    return true;
  }

  /** [azimut, elevación, fov] que muestra las parcelas de la vista, o null si no hay. */
  encuadreDeParcelas() {
    if (!this.overlay.size) return null;

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
    return [azimut, acotar(elevacion / peso, -42, -9), 75];
  }

  /**
   * Primera mitad del paso a otro punto: la cámara se acerca hacia donde está ese
   * punto y la foto se funde, como si el dron saliera volando hacia allá. Resuelve
   * cuando terminó; sin movimiento (o con el sistema pidiendo menos), al tiro.
   */
  salirHacia(azimut, elevacion) {
    if (SIN_MOVIMIENTO) return Promise.resolve();
    this.elemento.classList.add('viajando');
    this.apuntarA(azimut, elevacion, this.camara.fov * ACERCAMIENTO_VIAJE, { animar: true, duracion: SALIDA_MS });
    return new Promise((listo) => setTimeout(listo, SALIDA_MS));
  }

  /**
   * Segunda mitad: la vista nueva entra de cerca mirando en la dirección del viaje
   * y se abre hasta su encuadre. Sin `azimut` (no hubo viaje) solo se asegura de
   * que la foto quede visible.
   */
  llegar(azimut, encuadre) {
    const viajando = this.elemento.classList.contains('viajando');
    this.elemento.classList.remove('viajando');
    if (azimut == null || !viajando || SIN_MOVIMIENTO) return;
    const [destino, elevacion, fov] = encuadre;
    this.apuntarA(azimut, elevacion, fov * ACERCAMIENTO_VIAJE);
    this.apuntarA(destino, elevacion, fov, { animar: true, duracion: LLEGADA_MS });
  }

  /**
   * Centra la cámara en una parcela y ajusta el zoom para que llene el encuadre.
   *
   * `subir` es qué fracción del alto del cuadro se corre la parcela hacia arriba:
   * en el teléfono la ficha tapa la mitad de abajo, y una parcela centrada
   * quedaba escondida justo detrás de ella.
   */
  enfocarParcela(id, { subir = 0 } = {}) {
    const parcela = this.overlay.get(id);
    if (!parcela) return false;
    const [azimut, elevacion] = parcela.centro;
    const diametro = 2 * Math.sqrt(Math.max(parcela.area_angular, 0.5) / Math.PI);
    const fov = acotar(diametro * 3.2, 25, 90);
    // Mirar más abajo sube lo mirado en el cuadro; fov es el ángulo vertical.
    this.apuntarA(azimut, elevacion - subir * fov, fov, { animar: true });
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
    this._dibujarCaminos(ancho, alto);
    this._dibujarAguas(ancho, alto);
    this._dibujarPuntos(ancho, alto);

    const candidatas = [];
    const enPantalla = [];
    let rutaElegida = null;
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
      const elegida = id === this.seleccionada;
      nodo.grupo.classList.toggle('parcela--seleccionada', elegida);
      nodo.forma.setAttribute('d', aRuta(pixeles));
      ponerRotulo(nodo, elegida ? this.rotuloSeleccionadoDe(id) : this.rotuloDe(id));
      if (elegida) rutaElegida = { d: nodo.forma.getAttribute('d'), color: estilo.color };

      // La pastilla es el objetivo de clic real: un número redondo se acierta
      // mucho mejor que el borde de un polígono, sobre todo con el dedo. La de la
      // elegida se muestra aunque la parcela se vea chica: es la que se busca.
      const anchoEnPantalla = extension(pixeles, 0);
      nodo.pastilla.style.display = 'none';
      // Sin número (la planilla lo apagó) solo se rotula si la eligen: ahí el
      // globo dice su precio y es lo que se está mirando.
      const conNumero = elegida || !estilo.sinNumero;
      if (!estilo.atenuada && !elegida && conNumero) {
        const [x, y] = centro(pixeles);
        enPantalla.push({ id, x, y });
      }
      const cabe = this.numerosFijos || anchoEnPantalla >= ANCHO_MINIMO_ETIQUETA_PX;
      if ((elegida || cabe) && conNumero && !estilo.atenuada) {
        const [cx, cy] = centro(pixeles);
        const y = elegida ? this._ponerGlobo(nodo, pixeles) : cy;
        // Con los números fijos se achican con la parcela en vez de esconderse.
        const achique = this.numerosFijos && !elegida ? escalaDeRotulo(anchoEnPantalla) : 1;
        nodo.pastilla.setAttribute('transform', `translate(${cx.toFixed(1)} ${y.toFixed(1)})`
          + (achique < 1 ? ` scale(${achique.toFixed(3)})` : ''));
        nodo.disco.style.fill = estilo.color;
        nodo.numero.style.fill = estilo.texto;
        const escala = elegida ? ESCALA_ELEGIDA : achique;
        candidatas.push({
          id, x: cx, y,
          ancho: Number(nodo.disco.getAttribute('width')) * escala,
          alto: ALTO_PASTILLA * escala,
          // Primero la elegida; después lo que se vende; después lo más cercano,
          // que es lo que se ve más grande.
          prioridad: (elegida ? 1e9 : 0) + (estilo.prioridad ?? 0) * 1e6 + anchoEnPantalla,
        });
      }
    }

    // Solo las pastillas que caben sin encimarse: de lejos, las del fondo se
    // apilaban y no se leía ninguna.
    // Con los números fijos se muestran todos: se achican en vez de esconderse.
    let mostradas = this.numerosFijos
      ? new Set(candidatas.map((c) => c.id))
      : rotulosSinChoques(candidatas, SEPARACION_PASTILLAS);
    if (!this.numerosFijos) mostradas = this._agruparRotulos(candidatas, mostradas, enPantalla);
    // Los botones de los otros puntos van primero: un número encima los escondía,
    // y la parcela se sigue leyendo por su forma y por sus vecinas. La elegida no cede.
    for (const candidata of candidatas) {
      if (candidata.id !== this.seleccionada && this._tapaUnPunto(candidata)) mostradas.delete(candidata.id);
    }
    for (const id of mostradas) {
      this.nodos.get(id).pastilla.style.display = '';
    }
    this._dibujarHalo(rutaElegida, this.nodos.get(this.seleccionada));
  }

  /**
   * Sube la pastilla de la elegida por sobre el borde de arriba de la parcela y
   * tiende la patita hasta él. Devuelve dónde queda el centro de la pastilla.
   */
  _ponerGlobo(nodo, pixeles) {
    let tope = Infinity;
    for (const [, py] of pixeles) tope = Math.min(tope, py);
    const medioAlto = (ALTO_PASTILLA * ESCALA_ELEGIDA) / 2;
    // Pegada al borde de la pantalla no puede subir más: ahí tapa un poco, pero se lee.
    const y = Math.max(tope - PATITA_PX - medioAlto, medioAlto + 4);
    const largo = Math.max(tope - y, medioAlto);
    nodo.patita.setAttribute('y1', medioAlto.toFixed(1));
    nodo.patita.setAttribute('y2', largo.toFixed(1));
    nodo.punta.setAttribute('cy', largo.toFixed(1));
    return y;
  }

  /**
   * Los grupos cuyos números no caben pasan a ser una burbuja con su rango y sus
   * disponibles (grupos.js). Devuelve qué pastillas sueltas se dibujan al final.
   */
  _agruparRotulos(candidatas, mostradas, enPantalla) {
    const porGrupo = new Map();
    for (const { id, x, y } of enPantalla) {
      const grupoId = this.grupoDe.get(id);
      if (!grupoId) continue;
      const cuenta = porGrupo.get(grupoId) ?? { total: 0, ocultas: 0, x: 0, y: 0 };
      cuenta.total += 1;
      cuenta.ocultas += mostradas.has(id) ? 0 : 1;
      cuenta.x += x;
      cuenta.y += y;
      porGrupo.set(grupoId, cuenta);
    }
    const colapsados = new Set();
    for (const [grupoId, cuenta] of porGrupo) {
      if (grupoId === this.grupoAbierto) continue;
      if (debeColapsar(cuenta.ocultas, cuenta.total, this.colapsados.has(grupoId))) colapsados.add(grupoId);
    }
    this.colapsados = colapsados;

    const segunda = candidatas.filter((c) => c.id === this.seleccionada
                                             || !colapsados.has(this.grupoDe.get(c.id)));
    const burbujas = new Map();
    for (const grupoId of colapsados) {
      const cuenta = porGrupo.get(grupoId);
      const resumen = this.resumenDe(this.grupos.get(grupoId));
      if (!resumen?.total) continue;
      const nodo = this._nodoGrupo(grupoId);
      ponerTextoBurbuja(nodo, resumen);
      const posicion = { x: cuenta.x / cuenta.total, y: cuenta.y / cuenta.total };
      burbujas.set(`grupo:${grupoId}`, { grupoId, ...posicion });
      segunda.push({
        id: `grupo:${grupoId}`, ...posicion, ancho: nodo.ancho, alto: ALTO_BURBUJA,
        prioridad: PRIORIDAD_BURBUJA + resumen.disponibles * 1e3 + resumen.total,
      });
    }
    if (!burbujas.size) {
      for (const nodo of this.nodosGrupo.values()) nodo.grupo.style.display = 'none';
      return mostradas;
    }

    const elegidas = rotulosSinChoques(segunda, SEPARACION_PASTILLAS);
    for (const [grupoId, nodo] of this.nodosGrupo) {
      const burbuja = burbujas.get(`grupo:${grupoId}`);
      const visible = Boolean(burbuja) && elegidas.has(`grupo:${grupoId}`);
      nodo.grupo.style.display = visible ? '' : 'none';
      if (visible) {
        nodo.grupo.setAttribute('transform', `translate(${burbuja.x.toFixed(1)} ${burbuja.y.toFixed(1)})`);
      }
    }
    return new Set([...elegidas].filter((id) => !burbujas.has(id)));
  }

  _nodoGrupo(grupoId) {
    let nodo = this.nodosGrupo.get(grupoId);
    if (nodo) return nodo;
    const grupo = document.createElementNS(SVG_NS, 'g');
    grupo.setAttribute('class', 'burbuja');
    // El dedo necesita 44 px; la burbuja mide 30. Un rectángulo invisible da el resto.
    const toque = document.createElementNS(SVG_NS, 'rect');
    toque.setAttribute('class', 'burbuja__toque');
    const fondo = document.createElementNS(SVG_NS, 'rect');
    fondo.setAttribute('class', 'burbuja__fondo');
    const texto = document.createElementNS(SVG_NS, 'text');
    texto.setAttribute('class', 'burbuja__texto');
    texto.setAttribute('dy', '0.34em');
    const rango = document.createElementNS(SVG_NS, 'tspan');
    rango.setAttribute('class', 'burbuja__rango');
    const disponibles = document.createElementNS(SVG_NS, 'tspan');
    disponibles.setAttribute('class', 'burbuja__disponibles');
    texto.append(rango, disponibles);
    grupo.append(toque, fondo, texto);
    this.svg.append(grupo);
    nodo = { grupo, toque, fondo, texto, rango, disponibles, ancho: ALTO_BURBUJA, firma: '' };
    this.nodosGrupo.set(grupoId, nodo);
    return nodo;
  }

  /** Los grupos de parcelas vecinas y cómo resumir uno (rango, disponibles). */
  ponerGrupos(grupos, resumenDe) {
    this.grupos = new Map(grupos.map((g) => [g.id, g]));
    this.grupoDe = new Map(grupos.flatMap((g) => g.ids.map((id) => [id, g.id])));
    this.resumenDe = resumenDe;
    this._pintar();
  }

  /**
   * Acerca la cámara al grupo y lo deja abierto: sus números se ven aunque haya
   * que esconder los de al lado. Un grupo muy lejano puede no caber ni con el
   * zoom al máximo, y tocar la burbuja tiene que mostrar algo.
   */
  enfocarGrupo(grupoId) {
    const centros = (this.grupos.get(grupoId)?.ids ?? [])
      .map((id) => this.overlay.get(id)?.centro).filter(Boolean);
    if (!centros.length) return;
    const [azimutBase] = centros[0];
    // Relativos al primero, para no partir el grupo en el corte 0°/360°.
    const azimutes = centros.map(([a]) => azimutBase + ((((a - azimutBase) % 360) + 540) % 360) - 180);
    const elevaciones = centros.map(([, e]) => e);
    const aspecto = this.ancho / Math.max(this.alto, 1) || 1;
    const fov = Math.max(extensionDe(elevaciones), extensionDe(azimutes) / aspecto) * 1.8;
    this.grupoAbierto = grupoId;
    this.apuntarA(promedioDe(azimutes), promedioDe(elevaciones), acotar(fov, 22, 90), { animar: true });
  }

  /**
   * El brillo que late alrededor de la elegida (.parcela-halo en estilos.css). Va
   * sobre las demás parcelas, justo debajo de la elegida, y sin clic: es solo luz. Un filtro SVG y no `filter: drop-shadow`
   * de CSS, que Safari no aplica a los elementos de dentro de un SVG.
   */
  _dibujarHalo(ruta, elegida) {
    if (!this.halo) {
      const defs = document.createElementNS(SVG_NS, 'defs');
      defs.innerHTML = '<filter id="brillo-parcela" x="-25%" y="-25%" width="150%" height="150%">'
        + '<feGaussianBlur stdDeviation="4"/></filter>';
      this.halo = document.createElementNS(SVG_NS, 'path');
      this.halo.setAttribute('class', 'parcela-halo');
      this.halo.setAttribute('filter', 'url(#brillo-parcela)');
      this.svg.append(defs, this.halo);
    }
    this.halo.style.display = ruta ? '' : 'none';
    if (!ruta) return;
    // Al final del SVG: el brillo sobre las demás parcelas y la elegida al frente,
    // sobre su brillo; si no, los contornos de las vecinas cruzaban su globo. Solo
    // se mueven si algo quedó encima (una parcela o una burbuja recién creadas).
    if (elegida && (this.svg.lastChild !== elegida.grupo || elegida.grupo.previousSibling !== this.halo)) {
      this.svg.append(this.halo, elegida.grupo);
    }
    this.halo.setAttribute('d', ruta.d);
    this.halo.style.color = ruta.color;
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
    // Rectángulo redondeado y no círculo: con varias etapas el rótulo es "4-35" y
    // en un círculo de radio fijo el texto se sale por los lados. Con un solo
    // dígito queda igual de redondo que antes.
    const disco = document.createElementNS(SVG_NS, 'rect');
    disco.setAttribute('class', 'parcela__disco');
    // La patita y la punta del globo: solo se ven en la elegida (estilos.css).
    const patita = document.createElementNS(SVG_NS, 'line');
    patita.setAttribute('class', 'parcela__patita');
    const punta = document.createElementNS(SVG_NS, 'circle');
    punta.setAttribute('class', 'parcela__punta');
    punta.setAttribute('r', '3.5');
    const numero = document.createElementNS(SVG_NS, 'text');
    numero.setAttribute('class', 'parcela__numero');
    numero.setAttribute('dy', '0.34em');
    numero.textContent = this.rotuloDe(id);
    pastilla.append(patita, punta, disco, numero);

    grupo.append(forma, pastilla);

    grupo.addEventListener('pointerenter', () => this.alPasarSobreParcela(id));
    grupo.addEventListener('pointerleave', () => this.alPasarSobreParcela(null));
    this.svg.append(grupo);

    nodo = { grupo, forma, pastilla, disco, numero, patita, punta };
    this.nodos.set(id, nodo);
    dimensionarPastilla(nodo);
    return nodo;
  }

  _limpiarNodos() {
    this.svg.replaceChildren();
    this.halo = null;
    this.nodosGrupo.clear();
    this.colapsados = new Set();
    this.grupoAbierto = null;
    this.nodos.clear();
    this.nodosReferencia = [];
    this.capaReferencias.replaceChildren();
    this.nodosCamino = [];
    this.capaCaminos = null;
    this.nodosAgua = [];
    this.capaAguas = null;
  }

  // Los accesos del KMZ: una franja amarilla bajo las parcelas, sin interacción.
  _dibujarCaminos(ancho, alto) {
    this.caminos.forEach((anillos, indice) => {
      const nodo = this._nodoCamino(indice);
      const contorno = this.camara.proyectarAnillo(anillos[0], ancho, alto);
      if (!contorno || fueraDePantalla(contorno, ancho, alto)) {
        nodo.style.display = 'none';
        return;
      }
      // Los huecos son los lotes que encierra un camino que da la vuelta.
      const huecos = anillos.slice(1).map((a) => this.camara.proyectarAnillo(a, ancho, alto)).filter(Boolean);
      nodo.style.display = '';
      nodo.setAttribute('d', [contorno, ...huecos].map(aRuta).join(''));
    });
  }

  _nodoCamino(indice) {
    let nodo = this.nodosCamino[indice];
    if (nodo) return nodo;
    nodo = document.createElementNS(SVG_NS, 'path');
    nodo.setAttribute('class', 'camino');
    // En su propia capa y al fondo, como los hitos: las parcelas quedan encima y
    // nadie que recorra el overlay buscando parcelas se los encuentra.
    if (!this.capaCaminos) {
      this.capaCaminos = document.createElementNS(SVG_NS, 'g');
      this.capaCaminos.setAttribute('class', 'caminos');
      this.svg.prepend(this.capaCaminos);
    }
    this.capaCaminos.append(nodo);
    this.nodosCamino[indice] = nodo;
    return nodo;
  }

  /**
   * Los esteros: líneas abiertas, así que no se recortan como un polígono sino que
   * se cortan donde pasan detrás de la cámara. El nombre va en el tramo visible más
   * cerca del centro de la pantalla, que es donde se está mirando.
   */
  _dibujarAguas(ancho, alto) {
    this.aguas.forEach((agua, indice) => {
      const nodo = this._nodoAgua(indice, agua.nombre);
      const corridas = [];
      for (const tramo of agua.tramos) {
        let actual = [];
        for (const [az, el] of tramo) {
          const enCamara = this.camara.aCamara(az, el);
          if (enCamara[2] > 0.05) {
            actual.push(this.camara.aPantalla(enCamara, ancho, alto));
          } else if (actual.length) {
            corridas.push(actual);
            actual = [];
          }
        }
        if (actual.length >= 2) corridas.push(actual);
      }
      const visibles = corridas.filter((c) => c.length >= 2 && !fueraDePantalla(c, ancho, alto));
      if (!visibles.length) {
        nodo.grupo.style.display = 'none';
        return;
      }
      nodo.grupo.style.display = '';
      const d = visibles.map((c) => `M${c.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join('L')}`).join('');
      nodo.linea.setAttribute('d', d);
      nodo.borde.setAttribute('d', d);
      let mejor = null;
      for (const corrida of visibles) {
        for (const [x, y] of corrida) {
          if (x < 0 || x > ancho || y < 0 || y > alto) continue;
          const lejania = Math.hypot(x - ancho / 2, y - alto / 2);
          if (!mejor || lejania < mejor.lejania) mejor = { x, y, lejania };
        }
      }
      nodo.nombre.style.display = mejor ? '' : 'none';
      if (mejor) nodo.nombre.setAttribute('transform', `translate(${mejor.x.toFixed(1)} ${(mejor.y - 8).toFixed(1)})`);
    });
  }

  _nodoAgua(indice, nombre) {
    let nodo = this.nodosAgua[indice];
    if (nodo) return nodo;
    const grupo = document.createElementNS(SVG_NS, 'g');
    grupo.setAttribute('class', 'agua');
    const borde = document.createElementNS(SVG_NS, 'path');
    borde.setAttribute('class', 'agua__borde');
    const linea = document.createElementNS(SVG_NS, 'path');
    linea.setAttribute('class', 'agua__linea');
    const texto = document.createElementNS(SVG_NS, 'text');
    texto.setAttribute('class', 'agua__nombre');
    texto.textContent = nombre;
    grupo.append(borde, linea, texto);
    // Sobre los caminos y bajo las parcelas, como los hitos: nadie que recorra el
    // overlay buscando parcelas se lo encuentra.
    if (!this.capaAguas) {
      this.capaAguas = document.createElementNS(SVG_NS, 'g');
      this.capaAguas.setAttribute('class', 'aguas');
      this.svg.prepend(this.capaAguas);
    }
    this.capaAguas.append(grupo);
    nodo = { grupo, borde, linea, nombre: texto };
    this.nodosAgua[indice] = nodo;
    return nodo;
  }

  /**
   * Un botón por cada otro punto de vuelo, parado en el suelo bajo el dron: "estoy
   * en el I y el III queda allá". Tocarlo lleva a la 360 de ese punto.
   */
  _crearPuntos() {
    this.capaPuntos.replaceChildren(...this.puntos.map((punto) => {
      const boton = document.createElement('button');
      boton.type = 'button';
      boton.className = 'punto-360';
      boton.dataset.posicion = String(punto.posicion);
      boton.setAttribute('aria-label', `Ver la vista 360 del punto ${romano(punto.posicion)}`);
      boton.innerHTML = '<span class="punto-360__icono" aria-hidden="true">'
        + '<svg viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m15.5 15.5 5 5"/></svg></span>'
        + `<span class="punto-360__nombre">Punto ${romano(punto.posicion)}</span>`;
      // El toque lo resuelve _clic, como el de una parcela; esto es para el teclado.
      boton.addEventListener('click', (evento) => {
        if (evento.detail === 0) this.alElegirPunto(punto.posicion);
      });
      return boton;
    }));
  }

  _dibujarPuntos(ancho, alto) {
    // Dónde quedó cada botón, para que ningún número de parcela se le ponga encima.
    this.zonasPuntos = [];
    [...this.capaPuntos.children].forEach((boton, indice) => {
      const punto = this.puntos[indice];
      const [x, y, z] = this.camara.aCamara(punto.az, punto.el);
      if (z <= 0.05 || !this.camara.puedeVerse([punto.az, punto.el], ancho, alto, 1.0)) {
        boton.hidden = true;
        return;
      }
      const [px, py] = this.camara.aPantalla([x, y, z], ancho, alto);
      boton.hidden = px < -40 || px > ancho + 40 || py < -40 || py > alto + 40;
      boton.style.transform = `translate(${px.toFixed(1)}px, ${py.toFixed(1)}px)`;
      if (!boton.hidden) {
        // El botón se para sobre el suelo: crece hacia arriba desde (px, py). Se mide
        // porque en el celular es más chico y no debe esconder números de más.
        const anchoZona = boton.offsetWidth || ANCHO_ZONA_PUNTO;
        const altoZona = boton.offsetHeight || ALTO_ZONA_PUNTO;
        this.zonasPuntos.push({
          x0: px - anchoZona / 2, x1: px + anchoZona / 2, y0: py - altoZona, y1: py,
        });
      }
    });
  }

  /** Si la pastilla (centrada en x, y) pisa algún botón de punto 360. */
  _tapaUnPunto({ x, y, ancho, alto }) {
    return (this.zonasPuntos ?? []).some((zona) =>
      x + ancho / 2 > zona.x0 && x - ancho / 2 < zona.x1 && y + alto / 2 > zona.y0 && y - alto / 2 < zona.y1);
  }

  // Hitos del horizonte ("CAUQUENES · 12 KM"): un tick y un rótulo, sin interacción.
  _dibujarReferencias(ancho, alto) {
    const visibles = [];
    this.referencias.forEach((referencia, indice) => {
      const nodo = this._nodoReferencia(indice, referencia);
      // Tapada por un cerro, el rótulo se para sobre la cumbre: si no, su alfiler
      // caía en la ladera y el pueblo parecía estar en el cerro.
      const elevacion = referencia.tapada ? referencia.el_cumbre : referencia.el;
      const [x, y, z] = this.camara.aCamara(referencia.az, elevacion);
      if (z <= 0.05 || !this.camara.puedeVerse([referencia.az, elevacion], ancho, alto, 1.0)) {
        nodo.hidden = true;
        return;
      }
      const [px, py] = this.camara.aPantalla([x, y, z], ancho, alto);
      nodo.hidden = false;
      nodo.style.transform = `translate(${px.toFixed(1)}px, ${py.toFixed(1)}px)`;
      // El ancho se mide una vez: leerlo en cada cuadro forzaría a recalcular la página.
      if (!nodo.anchoMedido) nodo.anchoMedido = nodo.offsetWidth;
      visibles.push({ nodo, x: px, y: py, ancho: nodo.anchoMedido });
    });
    // Dos lugares en la misma dirección (Bulnes y Los Ángeles) se pisaban: el más
    // lejano sube un escalón, con un alfiler más largo, hasta que no choque.
    const puestos = [];
    for (const rotulo of visibles.sort((a, b) => b.y - a.y)) {
      let escalon = 0;
      const choca = (otro) => otro.escalon === escalon
        && Math.abs(otro.x - rotulo.x) < (otro.ancho + rotulo.ancho) / 2 + 6
        && Math.abs(otro.y - rotulo.y) < ALTO_ESCALON_REFERENCIA;
      while (escalon < 4 && puestos.some(choca)) escalon += 1;
      puestos.push({ ...rotulo, escalon });
      rotulo.nodo.style.setProperty('--alfiler', `${ALFILER_REFERENCIA + escalon * ALTO_ESCALON_REFERENCIA}px`);
    }
  }

  _nodoReferencia(indice, referencia) {
    let nodo = this.nodosReferencia[indice];
    if (nodo) return nodo;
    nodo = document.createElement('div');
    nodo.className = referencia.tapada ? 'referencia referencia--detras' : 'referencia';
    nodo.setAttribute('aria-label', textoReferencia(referencia) + (referencia.tapada ? ', detrás del cerro' : ''));
    const pildora = document.createElement('span');
    pildora.className = 'referencia__pildora';
    if (referencia.tapada) {
      // Un cerro con una flecha que lo cruza: "está más allá de esto".
      pildora.insertAdjacentHTML('beforeend', '<svg class="referencia__detras" viewBox="0 0 20 14" aria-hidden="true">'
        + '<path d="M1 13 7 4l3 4 2-2 7 7Z"/><path class="referencia__flecha" d="M9 2h9m-3-2 3 2-3 2"/></svg>');
    }
    const nombre = document.createElement('b');
    nombre.textContent = referencia.nombre;
    const lejania = document.createElement('span');
    lejania.className = 'referencia__lejania';
    lejania.textContent = lejaniaReferencia(referencia);
    pildora.append(nombre, lejania);
    nodo.append(pildora);
    this.capaReferencias.append(nodo);
    this.nodosReferencia[indice] = nodo;
    return nodo;
  }

  marcarSeleccionada(id) {
    this.seleccionada = id;
    // Con una elegida, las demás se apagan y pierden el rótulo (estilos.css).
    this.svg.classList.toggle('overlay--con-seleccion', Boolean(id));
    this._pintar();
  }

  aplicarEstilos(estiloParcela) {
    this.estiloParcela = estiloParcela;
    this._pintar();
  }

  // --- Entradas --------------------------------------------------------------

  _conectarEntradas() {
    const gesto = new Gesto(ARRASTRE_MINIMO_PX);
    const elemento = this.elemento;
    // Los últimos giros del arrastre, para saber con qué impulso se soltó.
    let muestras = [];

    elemento.addEventListener('pointerdown', (evento) => {
      try {
        elemento.setPointerCapture(evento.pointerId);
      } catch {
        // Sin captura el arrastre solo deja de seguir al puntero si sale del
        // visor. No es motivo para abortar el resto del manejador.
      }
      gesto.bajar(evento.pointerId, evento.clientX, evento.clientY);
      // Tocar la vista la detiene: es lo que se espera de algo que se mueve solo.
      this._detener();
      muestras = [];
    });

    elemento.addEventListener('pointermove', (evento) => {
      const paso = gesto.mover(evento.pointerId, evento.clientX, evento.clientY);
      if (!paso) return;
      if (paso.tipo === 'pellizco') {
        this.camara.acercar(paso.factor);
        muestras = [];
      } else {
        const gradosPorPixel = this.camara.fov / Math.max(this.alto, 1);
        const azimut = -paso.dx * gradosPorPixel;
        const elevacion = paso.dy * gradosPorPixel;
        this.camara.girar(azimut, elevacion);
        muestras.push({ t: evento.timeStamp, azimut, elevacion });
        if (muestras.length > 12) muestras.shift();
      }
      this._pintar();
    });

    elemento.addEventListener('pointerup', (evento) => {
      const quedan = gesto.punteros.size - 1;
      if (gesto.soltar(evento.pointerId)) {
        this._clic(evento);
      } else if (quedan === 0) {
        this._lanzar(velocidadAlSoltar(muestras, evento.timeStamp));
      }
      muestras = [];
    });
    elemento.addEventListener('pointercancel', (evento) => {
      gesto.soltar(evento.pointerId, { cancelado: true });
      muestras = [];
    });

    elemento.addEventListener('wheel', (evento) => {
      // Dentro de un iframe, sin Ctrl/⌘ la rueda sigue bajando por la página.
      if (!ruedaAcerca(evento, this.insertado)) return;
      evento.preventDefault();
      // Un mouse con ruedita da golpes de ~100; un trackpad, muchos chicos. Los dos
      // llegan suave porque se suman a un objetivo (_acercarSuave).
      const delta = evento.deltaMode === 1 ? evento.deltaY * 33 : evento.deltaY;
      this._acercarSuave(Math.exp(acotar(delta, -300, 300) * 0.0012));
    }, { passive: false });

    elemento.tabIndex = 0;
    elemento.addEventListener('keydown', (evento) => {
      // Un botón de punto 360 con el foco usa Enter y espacio para sí.
      if (evento.target !== elemento) return;
      const paso = evento.shiftKey ? 15 : 5;
      const { azimut, elevacion, fov } = this.camara;
      const girar = (dAz, dEl) => () => this.apuntarA(azimut + dAz, elevacion + dEl, fov,
                                                       { animar: true, duracion: VUELO_TECLA_MS });
      const acciones = {
        ArrowLeft: girar(-paso, 0),
        ArrowRight: girar(paso, 0),
        ArrowUp: girar(0, paso),
        ArrowDown: girar(0, -paso),
        '+': () => this._acercarSuave(0.85),
        '=': () => this._acercarSuave(0.85),
        '-': () => this._acercarSuave(1.18),
      };
      const accion = acciones[evento.key];
      if (!accion) return;
      evento.preventDefault();
      accion();
    });
  }

  _clic(evento) {
    const objetivo = document.elementFromPoint(evento.clientX, evento.clientY);
    const punto = objetivo?.closest?.('.punto-360');
    if (punto) {
      this.alElegirPunto(Number(punto.dataset.posicion));
      return;
    }
    const burbuja = objetivo?.closest?.('.burbuja');
    if (burbuja) {
      for (const [grupoId, nodo] of this.nodosGrupo) {
        if (nodo.grupo === burbuja) this.enfocarGrupo(grupoId);
      }
      return;
    }
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

/** Cambia el texto de la pastilla, y la vuelve a medir solo si cambió. */
function ponerRotulo(nodo, texto) {
  if (nodo.numero.textContent === texto) return;
  nodo.numero.textContent = texto;
  dimensionarPastilla(nodo);
}

/**
 * Ajusta la pastilla al texto que lleva dentro.
 *
 * Se mide al crear el nodo y cada vez que cambia el rótulo (al elegirla y al
 * soltarla). Si el navegador
 * todavía no puede medir —el SVG oculto, la tipografía sin cargar— se estima por
 * cantidad de caracteres, que para "4-35" se equivoca en un par de píxeles.
 */
function dimensionarPastilla(nodo) {
  const ALTO = ALTO_PASTILLA;
  const RESPIRO = 9;
  let ancho = 0;
  try {
    ancho = nodo.numero.getComputedTextLength();
  } catch { /* todavía sin layout */ }
  if (!ancho) ancho = nodo.numero.textContent.length * 6.5;

  const w = Math.max(ALTO, Math.round(ancho) + RESPIRO * 2);
  nodo.disco.setAttribute('x', (-w / 2).toFixed(1));
  nodo.disco.setAttribute('y', (-ALTO / 2).toFixed(1));
  nodo.disco.setAttribute('width', w);
  nodo.disco.setAttribute('height', ALTO);
  nodo.disco.setAttribute('rx', ALTO / 2);
}

/** Rango y disponibles en la burbuja; se mide de nuevo solo si cambió el texto. */
function ponerTextoBurbuja(nodo, { rango, disponibles }) {
  const detalle = disponibles ? ` · ${disponibles} disp.` : ' · sin disp.';
  const firma = rango + detalle;
  if (nodo.firma === firma) return;
  nodo.firma = firma;
  nodo.rango.textContent = rango;
  nodo.disponibles.textContent = detalle;
  nodo.disponibles.classList.toggle('burbuja__disponibles--hay', disponibles > 0);
  const w = Math.round(anchoDeTexto(rango, 700) + anchoDeTexto(detalle, 600)) + 24;
  nodo.ancho = w;
  nodo.fondo.setAttribute('x', (-w / 2).toFixed(1));
  nodo.fondo.setAttribute('y', (-ALTO_BURBUJA / 2).toFixed(1));
  nodo.fondo.setAttribute('width', w);
  nodo.fondo.setAttribute('height', ALTO_BURBUJA);
  nodo.fondo.setAttribute('rx', ALTO_BURBUJA / 2);
  nodo.toque.setAttribute('x', (-w / 2 - 7).toFixed(1));
  nodo.toque.setAttribute('y', '-22');
  nodo.toque.setAttribute('width', w + 14);
  nodo.toque.setAttribute('height', 44);
}

/**
 * Ancho del texto de una burbuja, medido en un canvas aparte. `getComputedTextLength`
 * obliga a recalcular el SVG entero (cientos de parcelas) cada vez que aparece una
 * burbuja; el canvas no toca el documento.
 */
let medidor = null;
let familia = 'sans-serif';
function anchoDeTexto(texto, peso) {
  if (!medidor) {
    medidor = document.createElement('canvas').getContext('2d');
    familia = getComputedStyle(document.documentElement).getPropertyValue('--sans').trim() || familia;
  }
  medidor.font = `${peso} 12px ${familia}`;
  return medidor.measureText(texto).width || texto.length * 6.8;
}

function extensionDe(valores) {
  return Math.max(...valores) - Math.min(...valores);
}

function promedioDe(valores) {
  return valores.reduce((suma, v) => suma + v, 0) / valores.length;
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

