/**
 * Visor 360.
 *
 * El panorama se dibuja con un solo cuadrilátero a pantalla completa: el shader
 * convierte la dirección de cada píxel a coordenada equirectangular. No hay malla
 * de esfera, no hay costuras, y el overlay SVG usa exactamente la misma cámara,
 * así que imagen y polígonos no pueden desincronizarse.
 */
import { Camara, acotar } from './camara.js';
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
// La burbuja de un grupo: más alta que una pastilla, porque dice más.
const ALTO_BURBUJA = 30;
// Por sobre las pastillas sueltas (que van hasta ~1e7) y bajo la elegida (1e9).
const PRIORIDAD_BURBUJA = 5e8;
const SVG_NS = 'http://www.w3.org/2000/svg';

export class Visor {
  constructor(elemento, {
    alElegirParcela, alPasarSobreParcela, alMoverCamara, rotuloDe, rotuloSeleccionadoDe,
  } = {}) {
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
    this.apuntarA(azimut, elevacion - subir * fov, fov);
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
      if (!estilo.atenuada && !elegida) {
        const [x, y] = centro(pixeles);
        enPantalla.push({ id, x, y });
      }
      if ((elegida || anchoEnPantalla >= ANCHO_MINIMO_ETIQUETA_PX) && !estilo.atenuada) {
        const [cx, cy] = centro(pixeles);
        const y = elegida ? this._ponerGlobo(nodo, pixeles) : cy;
        nodo.pastilla.setAttribute('transform', `translate(${cx.toFixed(1)} ${y.toFixed(1)})`);
        nodo.disco.style.fill = estilo.color;
        nodo.numero.style.fill = estilo.texto;
        const escala = elegida ? ESCALA_ELEGIDA : 1;
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
    let mostradas = rotulosSinChoques(candidatas, SEPARACION_PASTILLAS);
    mostradas = this._agruparRotulos(candidatas, mostradas, enPantalla);
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
    this.apuntarA(promedioDe(azimutes), promedioDe(elevaciones), acotar(fov, 22, 90));
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
      // Dentro de un iframe, sin Ctrl/⌘ la rueda sigue bajando por la página.
      if (!ruedaAcerca(evento, this.insertado)) return;
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

function separacionDe(punteros) {
  const [a, b] = [...punteros.values()];
  return Math.hypot(a.x - b.x, a.y - b.y) || 1;
}
