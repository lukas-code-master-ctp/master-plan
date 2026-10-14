/**
 * Lo que hacen los dedos (o el mouse) sobre el visor: girar, pellizcar o tocar.
 *
 * Un toque solo cuenta como clic si fue un único puntero que casi no se movió y que
 * el navegador no canceló. Pellizcar con dos dedos y soltarlos sin haber girado
 * elegía la parcela bajo el último dedo; y un pointercancel (el navegador se queda
 * con el gesto) no es que la persona haya soltado sobre una parcela.
 */
export class Gesto {
  constructor(umbralPx) {
    this.umbralPx = umbralPx;
    this.punteros = new Map();
    this.recorrido = 0;
    this.descartado = false;
    this.separacionPrevia = 0;
  }

  bajar(id, x, y) {
    if (this.punteros.size === 0) {
      this.recorrido = 0;
      this.descartado = false;
    }
    this.punteros.set(id, { x, y });
    if (this.punteros.size >= 2) this.descartado = true;
    this.separacionPrevia = 0;
  }

  /** {tipo: 'giro', dx, dy}, {tipo: 'pellizco', factor} o null si no hay nada que hacer. */
  mover(id, x, y) {
    const previo = this.punteros.get(id);
    if (!previo) return null;
    this.punteros.set(id, { x, y });

    if (this.punteros.size >= 2) {
      const [a, b] = [...this.punteros.values()];
      const separacion = Math.hypot(a.x - b.x, a.y - b.y) || 1;
      const factor = this.separacionPrevia ? this.separacionPrevia / separacion : 1;
      this.separacionPrevia = separacion;
      return { tipo: 'pellizco', factor };
    }

    // El giro se mide contra la posición anterior de este mismo puntero: al soltar
    // un dedo del pellizco, el que queda no salta a donde estaba el otro.
    const dx = x - previo.x;
    const dy = y - previo.y;
    this.recorrido += Math.hypot(dx, dy);
    return { tipo: 'giro', dx, dy };
  }

  /** Devuelve true si el gesto que termina fue un clic. */
  soltar(id, { cancelado = false } = {}) {
    if (!this.punteros.delete(id)) return false;
    if (cancelado) this.descartado = true;
    if (this.punteros.size < 2) this.separacionPrevia = 0;
    if (this.punteros.size > 0) return false;
    return !this.descartado && this.recorrido < this.umbralPx;
  }
}
