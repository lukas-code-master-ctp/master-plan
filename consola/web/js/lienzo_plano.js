/**
 * Crea tu KMZ: el plano en un canvas, con arrastre y zoom.
 *
 * Muestra la página girada según `rotacion` y habla en píxeles de página (ver
 * `kmz_geometria.js`). Quien lo usa pinta encima en `alDibujar` y escucha:
 * - `alTocar(x, y)`: un clic (o toque) sin arrastrar;
 * - `alRectangulo([x0, y0, x1, y1])`: con la herramienta "rectangulo", un arrastre.
 *
 * Arrastrar mueve el plano (con la herramienta "rectangulo", dibuja; ahí se mueve
 * con el botón del medio o el derecho, o manteniendo la barra espaciadora). La
 * rueda y el pellizco acercan donde está el puntero.
 *
 * En Ubicar el plano además se muestra girado `giro` grados (horario, en torno al centro
 * del lienzo) para que se vea con el norte arriba, como el mapa. La vista
 * ({escala, dx, dy}) sigue sin girar: el giro se aplica al pintar y se deshace al leer el
 * puntero, así los clics siguen llegando en px de página.
 */
import {
  aPagina, aPantalla, cajaGirada, centrarEn, girarEnPantalla, matrizRotacion, rectanguloDe, tamanoRotado, vistaAjustada, zoomEn,
} from './kmz_geometria.js';

const UMBRAL_ARRASTRE = 4;      // px de pantalla: menos que esto es un clic

export class LienzoPlano {
  constructor(contenedor, canvas) {
    this.contenedor = contenedor;
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.imagen = null;
    this.ancho = 0;
    this.alto = 0;
    this.rotacion = 0;
    this.giro = 0;
    this.vista = { escala: 1, dx: 0, dy: 0 };
    this.ajustada = false;
    this.herramienta = 'mover';
    this.borrador = null;
    this.alDibujar = () => {};
    this.alTocar = () => {};
    this.alRectangulo = () => {};
    this.punteros = new Map();
    this.gesto = null;
    this.espacio = false;
    this.pendiente = 0;
    this.url = null;

    new ResizeObserver(() => this.medir()).observe(contenedor);
    canvas.addEventListener('pointerdown', (e) => this.bajar(e));
    canvas.addEventListener('pointermove', (e) => this.mover(e));
    canvas.addEventListener('pointerup', (e) => this.subir(e));
    canvas.addEventListener('pointercancel', (e) => this.soltar(e));
    canvas.addEventListener('wheel', (e) => this.rueda(e), { passive: false });
    canvas.addEventListener('contextmenu', (e) => e.preventDefault());
    canvas.addEventListener('keydown', (e) => this.tecla(e));
    window.addEventListener('keydown', (e) => { if (e.code === 'Space' && e.target === canvas) this.espacio = true; });
    window.addEventListener('keyup', (e) => { if (e.code === 'Space') this.espacio = false; });
  }

  /** La página a mostrar: url de la imagen sin rotar, su tamaño y la rotación. */
  cargar(url, ancho, alto, rotacion) {
    const misma = url === this.url;
    this.ancho = ancho;
    this.alto = alto;
    if (this.rotacion !== rotacion || !misma) this.ajustada = false;
    this.rotacion = rotacion;
    if (misma && this.imagen) {
      this.ajustarSiHaceFalta();
      return Promise.resolve();
    }
    this.url = url;
    this.imagen = null;
    this.redibujar();
    return new Promise((listo, fallo) => {
      const imagen = new Image();
      imagen.decoding = 'async';
      imagen.onload = () => {
        if (this.url !== url) return listo();
        this.imagen = imagen;
        this.ajustarSiHaceFalta();
        this.redibujar();
        listo();
      };
      imagen.onerror = () => fallo(new Error('No se pudo cargar la imagen de la página.'));
      imagen.src = url;
    });
  }

  get pagina() { return tamanoRotado(this.ancho, this.alto, this.rotacion); }

  /** El centro del lienzo (px CSS): en torno a él se gira el plano. */
  get centro() { return [this.contenedor.clientWidth / 2, this.contenedor.clientHeight / 2]; }

  /** Gira el plano en pantalla `grados` (horario). Con `ajustar`, lo vuelve a encuadrar. */
  ponerGiro(grados, ajustar = false) {
    const nuevo = Number.isFinite(grados) ? grados : 0;
    if (nuevo === this.giro && !ajustar) return;
    this.giro = nuevo;
    if (ajustar) this.ajustar(); else this.redibujar();
  }

  medir() {
    const { clientWidth: W, clientHeight: H } = this.contenedor;
    if (!W || !H) return;
    const dpr = window.devicePixelRatio || 1;
    this.canvas.width = Math.round(W * dpr);
    this.canvas.height = Math.round(H * dpr);
    this.canvas.style.width = `${W}px`;
    this.canvas.style.height = `${H}px`;
    this.ajustarSiHaceFalta();
    this.redibujar();
  }

  ajustarSiHaceFalta() {
    if (!this.ajustada && this.ancho && this.contenedor.clientWidth) this.ajustar();
  }

  ajustar() {
    const [w, h] = this.pagina;
    const [W, H] = [this.contenedor.clientWidth, this.contenedor.clientHeight];
    if (!w || !W) return;
    if (this.giro) {
      // Girada, la página ocupa su caja girada: se encuadra esa, con el centro en el centro.
      const [cw, ch] = cajaGirada(w, h, this.giro);
      const { escala } = vistaAjustada(cw, ch, W, H);
      this.vista = { escala, dx: W / 2 - (w / 2) * escala, dy: H / 2 - (h / 2) * escala };
    } else {
      this.vista = vistaAjustada(w, h, W, H);
    }
    this.ajustada = true;
    this.redibujar();
  }

  acercar(factor, sx = this.contenedor.clientWidth / 2, sy = this.contenedor.clientHeight / 2) {
    this.vista = zoomEn(this.vista, factor, sx, sy, this.escalaMinima(), 16);
    this.redibujar();
  }

  /** Pone (x, y) de página en el centro, con al menos `escala`. */
  centrar(x, y, escala = this.vista.escala) {
    this.vista = centrarEn(this.vista, x, y, this.contenedor.clientWidth, this.contenedor.clientHeight, escala);
    this.redibujar();
  }

  escalaMinima() {
    const [w, h] = this.pagina;
    return w ? 0.25 * Math.min(this.contenedor.clientWidth / w, this.contenedor.clientHeight / h) : 0.01;
  }

  /** px de página → px de pantalla (CSS), para pintar encima. */
  aPantalla(x, y) { return girarEnPantalla(...aPantalla(this.vista, x, y), this.giro, ...this.centro); }

  redibujar() {
    if (this.pendiente) return;
    this.pendiente = requestAnimationFrame(() => {
      this.pendiente = 0;
      this.pintar();
    });
  }

  pintar() {
    const { ctx, canvas } = this;
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = '#e4e4e7';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    if (this.imagen) {
      const { escala, dx, dy } = this.vista;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      if (this.giro) {
        const [cx, cy] = this.centro;
        ctx.translate(cx, cy);
        ctx.rotate((this.giro * Math.PI) / 180);
        ctx.translate(-cx, -cy);
      }
      ctx.transform(escala, 0, 0, escala, dx, dy);
      ctx.transform(...matrizRotacion(this.rotacion, this.ancho, this.alto));
      // El centro del píxel está en el entero: el píxel i cubre [i − ½, i + ½].
      ctx.translate(-0.5, -0.5);
      ctx.imageSmoothingEnabled = escala < 2;
      ctx.drawImage(this.imagen, 0, 0);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.alDibujar(ctx, (x, y) => this.aPantalla(x, y), this.vista);
    if (this.borrador) {
      const [x0, y0, x1, y1] = rectanguloDe(...this.borrador);
      const [a, b] = this.aPantalla(x0, y0);
      const [c, d] = this.aPantalla(x1, y1);
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = '#18181b';
      ctx.lineWidth = 1.5;
      ctx.strokeRect(a, b, c - a, d - b);
      ctx.setLineDash([]);
    }
  }

  // --- puntero -------------------------------------------------------------------

  /** El puntero en px de la vista sin girar (lo que entienden `vista` y `aPagina`). */
  posicion(e) {
    const caja = this.canvas.getBoundingClientRect();
    return girarEnPantalla(e.clientX - caja.left, e.clientY - caja.top, -this.giro, ...this.centro);
  }

  bajar(e) {
    this.canvas.focus({ preventScroll: true });
    try { this.canvas.setPointerCapture(e.pointerId); } catch { /* un puntero que ya se fue */ }
    const p = this.posicion(e);
    this.punteros.set(e.pointerId, p);
    if (this.punteros.size === 2) {
      const [a, b] = [...this.punteros.values()];
      this.borrador = null;
      this.gesto = { tipo: 'pellizco', distancia: Math.hypot(a[0] - b[0], a[1] - b[1]) };
      return;
    }
    if (this.punteros.size > 2) return;
    const mover = e.button === 1 || e.button === 2 || this.espacio || this.herramienta !== 'rectangulo';
    this.gesto = { tipo: mover ? 'mover' : 'dibujo', inicio: p, ultimo: p, lejos: false };
  }

  mover(e) {
    if (!this.punteros.has(e.pointerId) || !this.gesto) return;
    const p = this.posicion(e);
    this.punteros.set(e.pointerId, p);
    const g = this.gesto;
    if (g.tipo === 'pellizco') {
      if (this.punteros.size < 2) return;
      const [a, b] = [...this.punteros.values()];
      const distancia = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (g.distancia > 0) this.acercar(distancia / g.distancia, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2);
      g.distancia = distancia;
      return;
    }
    if (!g.lejos && Math.hypot(p[0] - g.inicio[0], p[1] - g.inicio[1]) >= UMBRAL_ARRASTRE) g.lejos = true;
    if (!g.lejos) return;
    if (g.tipo === 'mover') {
      this.vista = { ...this.vista, dx: this.vista.dx + p[0] - g.ultimo[0], dy: this.vista.dy + p[1] - g.ultimo[1] };
    } else {
      this.borrador = [aPagina(this.vista, ...g.inicio), aPagina(this.vista, ...p)];
    }
    g.ultimo = p;
    this.redibujar();
  }

  subir(e) {
    const g = this.gesto;
    const p = this.posicion(e);
    this.soltar(e);
    if (!g || g.tipo === 'pellizco') return;
    if (!g.lejos) {
      this.alTocar(...aPagina(this.vista, ...p), e);
      return;
    }
    if (g.tipo === 'dibujo') {
      const rect = rectanguloDe(aPagina(this.vista, ...g.inicio), aPagina(this.vista, ...p));
      this.borrador = null;
      this.redibujar();
      this.alRectangulo(rect.map((v) => Math.round(v * 10) / 10));
    }
  }

  soltar(e) {
    this.punteros.delete(e.pointerId);
    if (!this.punteros.size) this.gesto = null;
    else if (this.gesto?.tipo === 'pellizco') this.gesto = null;
  }

  rueda(e) {
    e.preventDefault();
    const [sx, sy] = this.posicion(e);
    // Un trackpad manda deltas chicos y seguidos; un mouse, de a 100.
    const delta = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
    this.acercar(Math.exp(-delta * 0.0015), sx, sy);
  }

  tecla(e) {
    if (e.code === 'Space') { e.preventDefault(); return; }     // mover con el espacio, sin bajar la página
    const paso = 60;
    let mover = { ArrowLeft: [paso, 0], ArrowRight: [-paso, 0], ArrowUp: [0, paso], ArrowDown: [0, -paso] }[e.key];
    // Con el plano girado, la flecha mueve lo que se ve, no la vista sin girar.
    if (mover) mover = girarEnPantalla(...mover, -this.giro, 0, 0);
    if (mover) {
      this.vista = { ...this.vista, dx: this.vista.dx + mover[0], dy: this.vista.dy + mover[1] };
      this.redibujar();
    } else if (e.key === '+' || e.key === '=') this.acercar(1.25);
    else if (e.key === '-') this.acercar(0.8);
    else if (e.key === '0') this.ajustar();
    else return;
    e.preventDefault();
  }
}
