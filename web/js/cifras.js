/**
 * Las cifras que el sitio le manda a la consola: una visita, una ficha abierta, un
 * clic en WhatsApp y un clic en Reservar. La loteadora las ve sumadas por día y por
 * parcela; no se manda nada que diga quién es el comprador.
 *
 * Para que las cifras digan algo, una persona cuenta una vez: la visita una vez por
 * sesión del navegador y cada ficha una vez por parcela. Los clics sí cuentan todos,
 * porque cada uno es una intención.
 *
 * Los eventos se juntan unos segundos y salen en un solo pedido; al cerrar la
 * pestaña sale lo que quede, con `keepalive` para que el navegador lo termine.
 */

const ESPERA_MS = 4000;
const MAXIMO_POR_PEDIDO = 30;   // el tope de la consola
const CLAVE = 'tumasterplan-cifras';

/** ¿Este evento ya se contó en esta sesión? Visitas y fichas, sí; clics, nunca. */
export function claveDeUnaVez(tipo, parcela) {
  if (tipo === 'visita') return 'visita';
  if (tipo === 'ficha') return `ficha:${parcela}`;
  return null;
}

export class Cifras {
  /**
   * `meta` es el de parcelas.json: sin consola ni loteo no se manda nada. `memoria`
   * es sessionStorage (o null si el navegador no lo deja) y `pedir`, fetch.
   */
  constructor(meta, { memoria = sesion(), pedir = globalThis.fetch?.bind(globalThis), reloj = globalThis } = {}) {
    this.url = meta?.consola && meta?.loteo
      ? `${meta.consola.replace(/\/$/, '')}/api/publico/eventos` : null;
    this.loteo = meta?.loteo;
    this.memoria = memoria;
    this.pedir = pedir;
    this.reloj = reloj;
    this.pendientes = [];
    this.temporizador = null;
    // Por loteo: en el QA local varios sitios comparten el mismo origen.
    this.clave = `${CLAVE}:${this.loteo}`;
    this.contados = new Set(leer(memoria, this.clave));
  }

  /** Anota un evento. Lo que ya se contó en esta sesión se ignora. */
  anotar(tipo, parcela = null) {
    if (!this.url) return;
    const clave = claveDeUnaVez(tipo, parcela);
    if (clave) {
      if (this.contados.has(clave)) return;
      this.contados.add(clave);
      guardar(this.memoria, this.clave, this.contados);
    }
    this.pendientes.push(parcela ? { tipo, parcela } : { tipo });
    if (this.pendientes.length >= MAXIMO_POR_PEDIDO) this.enviar();
    else if (!this.temporizador) this.temporizador = this.reloj.setTimeout(() => this.enviar(), ESPERA_MS);
  }

  /** Manda lo pendiente. No espera respuesta: una cifra perdida no le importa al comprador. */
  enviar() {
    if (this.temporizador) this.reloj.clearTimeout(this.temporizador);
    this.temporizador = null;
    if (!this.pendientes.length || !this.pedir) return;
    const eventos = this.pendientes.splice(0, MAXIMO_POR_PEDIDO);
    try {
      Promise.resolve(this.pedir(this.url, {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain' },
        credentials: 'omit',
        keepalive: true,
        body: JSON.stringify({ loteo: this.loteo, eventos }),
      })).catch(() => {});
    } catch {
      // Sin red o sin fetch: las cifras no pueden romper el visor.
    }
    if (this.pendientes.length) this.enviar();
  }
}

function sesion() {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
}

function leer(memoria, clave) {
  try {
    return JSON.parse(memoria?.getItem(clave) || '[]');
  } catch {
    return [];
  }
}

function guardar(memoria, clave, contados) {
  try {
    memoria?.setItem(clave, JSON.stringify([...contados]));
  } catch {
    // Navegación privada sin almacenamiento: se cuenta igual, solo que sin recordar.
  }
}
