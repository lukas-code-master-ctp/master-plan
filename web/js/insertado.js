/**
 * El visor dentro de un iframe: la landing de tumasterplan.cl muestra masters de
 * ejemplo así. Ahí el visor es un trozo de una página más larga, y no puede
 * adueñarse de la rueda ni del dedo: quien está bajando por la página tiene que
 * poder seguir bajando aunque pase por encima.
 */

/** ¿Corre dentro de un iframe? Si el navegador no deja ni preguntar, sí. */
export function estaInsertado(ventana = globalThis.window) {
  try {
    return ventana.self !== ventana.top;
  } catch {
    return true;
  }
}

/**
 * Suelto, la rueda acerca. Insertado, la rueda sola es de la página y se acerca
 * con Ctrl o ⌘, como en los mapas insertados. El pellizco del trackpad llega
 * como rueda con Ctrl, así que sigue acercando sin pensarlo.
 */
export function ruedaAcerca(evento, insertado) {
  return !insertado || evento.ctrlKey || evento.metaKey;
}

export function pistaDelVisor(insertado, esMac) {
  if (!insertado) return 'Arrastra para mirar · rueda para acercar';
  return `Arrastra para mirar · ${esMac ? '⌘' : 'Ctrl'} + rueda para acercar`;
}
