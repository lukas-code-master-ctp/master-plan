/**
 * Las fotos comunes de una referencia (el portón del acceso, la sala de ventas),
 * a pantalla completa. Se abre al tocar el rótulo de una referencia que trae
 * fotos (visor.js); desde el dron no se ve cómo es la entrada, y es lo primero
 * que pregunta quien va a ir a ver el loteo.
 */

// Cuánto hay que arrastrar el dedo para pasar de foto. Menos se confunde con un
// toque que tiembla.
const ARRASTRE_PARA_PASAR_PX = 50;

/** La foto `paso` lugares más allá de `indice`, dando la vuelta en los extremos. */
export function vecina(indice, total, paso) {
  if (!total) return 0;
  return ((indice + paso) % total + total) % total;
}

/** "2 / 6", o nada con una sola foto: un contador de una no dice nada. */
export function textoCuenta(indice, total) {
  return total > 1 ? `${indice + 1} / ${total}` : '';
}

/** Si un arrastre horizontal pasa de foto: -1 a la anterior, 1 a la siguiente, 0 no. */
export function pasoDeArrastre(dx, dy) {
  if (Math.abs(dx) < ARRASTRE_PARA_PASAR_PX || Math.abs(dx) < Math.abs(dy)) return 0;
  return dx < 0 ? 1 : -1;
}

/**
 * Abre la galería en `dialogo` (el <dialog id="galeria"> de index.html) con las
 * fotos de `referencia` ({ nombre, fotos: [rutas] }). Escape la cierra (lo hace el
 * propio <dialog>), las flechas pasan de foto y en el teléfono se pasa arrastrando.
 */
export function abrirGaleria(dialogo, referencia, { alAbrir = () => {} } = {}) {
  const fotos = referencia.fotos ?? [];
  if (!fotos.length) return;
  const imagen = dialogo.querySelector('.galeria__foto');
  const miniaturas = dialogo.querySelector('.galeria__miniaturas');
  const anterior = dialogo.querySelector('.galeria__anterior');
  const siguiente = dialogo.querySelector('.galeria__siguiente');
  const unaSola = fotos.length === 1;
  let indice = 0;

  dialogo.querySelector('.galeria__titulo').textContent = referencia.nombre;
  anterior.hidden = unaSola;
  siguiente.hidden = unaSola;
  miniaturas.hidden = unaSola;
  miniaturas.replaceChildren(...fotos.map((ruta, i) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'galeria__miniatura';
    boton.setAttribute('aria-label', `Foto ${i + 1} de ${fotos.length}`);
    const mini = document.createElement('img');
    mini.src = ruta;
    mini.alt = '';
    mini.loading = 'lazy';
    mini.decoding = 'async';
    boton.append(mini);
    boton.addEventListener('click', () => mostrar(i));
    return boton;
  }));

  function mostrar(nuevo) {
    indice = nuevo;
    imagen.src = fotos[indice];
    imagen.alt = `${referencia.nombre}, foto ${indice + 1} de ${fotos.length}`;
    dialogo.querySelector('.galeria__cuenta').textContent = textoCuenta(indice, fotos.length);
    [...miniaturas.children].forEach((boton, i) => {
      boton.setAttribute('aria-current', i === indice ? 'true' : 'false');
      if (i === indice) boton.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
    });
    // Las vecinas se piden ya: pasar de foto no tiene que esperar la descarga.
    for (const paso of [1, -1]) new Image().src = fotos[vecina(indice, fotos.length, paso)];
  }
  const pasar = (paso) => mostrar(vecina(indice, fotos.length, paso));

  // Cada apertura trae sus propios oyentes y los suelta al cerrar: si no, la
  // segunda vez que se abre las flechas pasarían dos fotos.
  const control = new AbortController();
  const { signal } = control;
  anterior.addEventListener('click', () => pasar(-1), { signal });
  siguiente.addEventListener('click', () => pasar(1), { signal });
  dialogo.querySelector('.galeria__cerrar').addEventListener('click', () => dialogo.close(), { signal });
  dialogo.addEventListener('keydown', (evento) => {
    if (evento.key === 'ArrowRight') pasar(1);
    else if (evento.key === 'ArrowLeft') pasar(-1);
    else return;
    evento.preventDefault();
  }, { signal });
  // Tocar el fondo oscuro, fuera de la foto y los botones, también cierra.
  dialogo.addEventListener('click', (evento) => {
    if (evento.target === dialogo || evento.target.classList.contains('galeria__escenario')) dialogo.close();
  }, { signal });
  const escenario = dialogo.querySelector('.galeria__escenario');
  let inicio = null;
  escenario.addEventListener('pointerdown', (evento) => { inicio = [evento.clientX, evento.clientY]; }, { signal });
  escenario.addEventListener('pointerup', (evento) => {
    if (!inicio || unaSola) return;
    const paso = pasoDeArrastre(evento.clientX - inicio[0], evento.clientY - inicio[1]);
    inicio = null;
    if (paso) pasar(paso);
  }, { signal });
  dialogo.addEventListener('close', () => {
    control.abort();
    imagen.removeAttribute('src');
  }, { signal, once: true });

  mostrar(0);
  dialogo.showModal();
  alAbrir();
}
