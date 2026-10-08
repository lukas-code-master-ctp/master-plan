/**
 * Qué hacer cuando falla el sondeo de un trabajo (`GET /api/trabajos/{id}`). Puro, sin
 * DOM, para poder probarlo.
 *
 * Los trabajos viven en la memoria de la consola. Si la instancia de Cloud Run se cae
 * (p. ej. se quedó sin memoria a media digitalización) la reemplaza otra que no los
 * conoce: el sondeo recibe 404 y, mientras arranca, errores de red o 502/503/504. Antes
 * la pantalla se quedaba pegada en "30 de 96" para siempre.
 *
 * Se aguanta cerca de un minuto de errores pasajeros: la instancia nueva del 2026-10-08
 * tardó ~20 s en quedar lista, y rendirse antes deja la pantalla diciendo "se interrumpió"
 * mientras la consola ya retomó la lectura. Una lectura retomada es otro trabajo (otro
 * id): `relevo` dice cuál seguir cuando el que se seguía ya no existe.
 */

/**
 * Cuántos errores pasajeros seguidos se aguantan antes de dar el trabajo por perdido.
 * Con las esperas de `trasFalloDeSondeo` (1, 2, … 8, 8, 8 s) suman 60 s.
 */
export const FALLOS_SEGUIDOS_MAX = 12;

/** La espera entre reintentos crece de a un segundo hasta este tope. */
export const ESPERA_MAX_MS = 8000;

/** Errores que pueden ser pasajeros: la instancia está arrancando o se cortó la red. */
const PASAJEROS = new Set([502, 503, 504]);

/**
 * `error` es lo que lanzó `pedir` (trae `estado` si el servidor contestó; un error de
 * red no lo trae) y `fallos` los errores pasajeros seguidos que ya hubo. Devuelve
 * `{ que, fallos, espera }`:
 * - 'interrumpido': el trabajo ya no existe (404) o el servidor no vuelve tras
 *   FALLOS_SEGUIDOS_MAX intentos. Se deja de sondear: se busca un relevo y, si no lo
 *   hay, se muestra como fallido.
 * - 'reintentar': otro intento en `espera` ms (cada vez más largo, hasta ESPERA_MAX_MS).
 * - 'detener': cualquier otro error (sesión vencida, 500…): se deja de sondear y se
 *   avisa el error, como siempre.
 */
export function trasFalloDeSondeo(error, fallos = 0) {
  const estadoHttp = error?.estado;
  if (estadoHttp === 404) return { que: 'interrumpido', fallos: 0, espera: 0 };
  if (estadoHttp === undefined || PASAJEROS.has(estadoHttp)) {
    const seguidos = fallos + 1;
    if (seguidos >= FALLOS_SEGUIDOS_MAX) return { que: 'interrumpido', fallos: seguidos, espera: 0 };
    return { que: 'reintentar', fallos: seguidos, espera: Math.min(1000 * seguidos, ESPERA_MAX_MS) };
  }
  return { que: 'detener', fallos: 0, espera: 0 };
}

/** La primera línea del trabajo con que la consola, al arrancar, retoma una lectura. */
const RETOMA = /^Se retoma la lectura/;

/**
 * El trabajo que hay que seguir ahora que `perdido` (un id, o los ids ya perdidos) no
 * existe, o null. `kmz` es la respuesta de `GET /api/kmz/<slug>`; su `trabajo` es el
 * último que la consola conoce para ese KMZ. Como los trabajos viven en memoria, si el
 * nuestro se perdió, ese es posterior al reinicio: la lectura retomada (o una que lanzó
 * otra persona). Se sigue si corre o si es una retomada que ya alcanzó a terminar: así
 * la pantalla muestra cómo terminó de verdad y no "se interrumpió". Uno de los ids ya
 * perdidos no se vuelve a seguir, para no dar vueltas.
 */
export function relevo(kmz, perdido) {
  const trabajo = kmz?.trabajo;
  const perdidos = new Set([perdido].flat());
  if (!trabajo?.id || perdidos.has(trabajo.id)) return null;
  if (!trabajo.terminado) return trabajo.id;
  return RETOMA.test(String(trabajo.lineas?.[0] ?? '')) ? trabajo.id : null;
}

/**
 * Desde qué línea seguir el trabajo `id` y si se conservan las que ya muestra el registro.
 * `previo` es `estado.registroDe` de la clave: de qué trabajo son esas líneas. El mismo
 * trabajo (se recargó la lista, se volvió a la pantalla) sigue donde iba. Otro empieza
 * desde su primera línea: debajo de las del perdido si lo retoma (la consola volvió
 * después de que la pantalla diera la lectura por interrumpida), y si no, en limpio, que
 * las líneas de un trabajo anterior confundirían la barra (toma el paso más avanzado).
 */
export function retomarRegistro(previo, id) {
  if (previo && previo.id === id) return { desde: previo.total, conservar: true };
  return { desde: 0, conservar: Boolean(previo?.perdido) };
}

/** Lo que se le dice a la persona cuando su trabajo se perdió con el servidor. */
export function textoInterrumpido(clave, tipo) {
  if (String(clave).startsWith('kmz:') || tipo === 'digitalizar-plano') {
    return 'La lectura del plano se interrumpió (el servidor se reinició). Vuelve a intentarlo.';
  }
  const nombre = { construir: 'La construcción', publicar: 'La publicación' }[tipo] ?? 'El trabajo';
  return `${nombre} se interrumpió (el servidor se reinició). Vuelve a intentarlo.`;
}
