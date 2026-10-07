/**
 * Qué hacer cuando falla el sondeo de un trabajo (`GET /api/trabajos/{id}`). Puro, sin
 * DOM, para poder probarlo.
 *
 * Los trabajos viven en la memoria de la consola. Si la instancia de Cloud Run se cae
 * (p. ej. se quedó sin memoria a media digitalización) la reemplaza otra que no los
 * conoce: el sondeo recibe 404 y, mientras arranca, errores de red o 502/503/504. Antes
 * la pantalla se quedaba pegada en "30 de 96" para siempre.
 */

/** Cuántos errores pasajeros seguidos se aguantan antes de dar el trabajo por perdido. */
export const FALLOS_SEGUIDOS_MAX = 5;

/** Errores que pueden ser pasajeros: la instancia está arrancando o se cortó la red. */
const PASAJEROS = new Set([502, 503, 504]);

/**
 * `error` es lo que lanzó `pedir` (trae `estado` si el servidor contestó; un error de
 * red no lo trae) y `fallos` los errores pasajeros seguidos que ya hubo. Devuelve
 * `{ que, fallos, espera }`:
 * - 'interrumpido': el trabajo ya no existe (404) o el servidor no vuelve tras
 *   FALLOS_SEGUIDOS_MAX intentos. Se deja de sondear y se muestra como fallido.
 * - 'reintentar': otro intento en `espera` ms (cada vez más largo).
 * - 'detener': cualquier otro error (sesión vencida, 500…): se deja de sondear y se
 *   avisa el error, como siempre.
 */
export function trasFalloDeSondeo(error, fallos = 0) {
  const estadoHttp = error?.estado;
  if (estadoHttp === 404) return { que: 'interrumpido', fallos: 0, espera: 0 };
  if (estadoHttp === undefined || PASAJEROS.has(estadoHttp)) {
    const seguidos = fallos + 1;
    if (seguidos >= FALLOS_SEGUIDOS_MAX) return { que: 'interrumpido', fallos: seguidos, espera: 0 };
    return { que: 'reintentar', fallos: seguidos, espera: 1000 * seguidos };
  }
  return { que: 'detener', fallos: 0, espera: 0 };
}

/** Lo que se le dice a la persona cuando su trabajo se perdió con el servidor. */
export function textoInterrumpido(clave, tipo) {
  if (String(clave).startsWith('kmz:') || tipo === 'digitalizar-plano') {
    return 'La lectura del plano se interrumpió (el servidor se reinició). Vuelve a intentarlo.';
  }
  const nombre = { construir: 'La construcción', publicar: 'La publicación' }[tipo] ?? 'El trabajo';
  return `${nombre} se interrumpió (el servidor se reinició). Vuelve a intentarlo.`;
}
