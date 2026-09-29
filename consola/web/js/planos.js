/**
 * Mis planos: una fila por loteo, con lo que se quiere saber de un vistazo
 * —cuánto queda por vender y desde cuánto— y la puerta a su detalle.
 */
import { $, dinero, estado, etapaDe } from './comun.js';

export function pintarPlanos() {
  const lista = $('#planos');
  if (!estado.proyectos.length) {
    lista.innerHTML = `<li class="vacio"><strong>Todavía no tienes planos</strong>
      <span>Crea el primero con <b>Nuevo master</b>: el KMZ del loteo y las panorámicas del dron.</span></li>`;
    return;
  }
  lista.replaceChildren(...estado.proyectos.map(fila));
}

function fila(proyecto) {
  const item = document.createElement('li');
  const enlace = document.createElement('a');
  enlace.className = 'plano';
  enlace.href = `#/planos/${proyecto.slug}`;

  const portada = document.createElement('div');
  portada.className = 'plano__portada';
  if (proyecto.construido) {
    const imagen = document.createElement('img');
    imagen.src = `/api/proyectos/${proyecto.slug}/portada?v=${encodeURIComponent(proyecto.resumen.generado ?? '')}`;
    imagen.alt = '';
    imagen.loading = 'lazy';
    imagen.width = 320;
    imagen.height = 180;
    imagen.addEventListener('error', () => imagen.remove());
    portada.append(imagen);
  }

  const cuerpo = document.createElement('div');
  cuerpo.className = 'plano__cuerpo';
  const nombre = document.createElement('h2');
  nombre.className = 'plano__nombre';
  nombre.textContent = proyecto.nombre;
  const estadoActual = etapaDe(proyecto);
  const titulo = document.createElement('div');
  titulo.className = 'plano__titulo';
  titulo.append(nombre, estadoActual);

  const cifras = document.createElement('dl');
  cifras.className = 'plano__cifras';
  cifras.append(...cifrasDe(proyecto));
  cuerpo.append(titulo, cifras);

  const flecha = document.createElement('span');
  flecha.className = 'plano__flecha';
  flecha.setAttribute('aria-hidden', 'true');
  flecha.innerHTML = '<svg viewBox="0 0 24 24"><path d="M5 12h14m-6-6 6 6-6 6" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>';

  enlace.append(portada, cuerpo, flecha);
  item.append(enlace);
  return item;
}

function cifrasDe(proyecto) {
  const { resumen } = proyecto;
  const dato = (rotulo, valor) => {
    const div = document.createElement('div');
    const dt = document.createElement('dt');
    const dd = document.createElement('dd');
    dt.textContent = rotulo;
    dd.textContent = valor;
    div.append(dt, dd);
    return div;
  };
  if (!proyecto.construido) {
    const hallado = proyecto.fuentes_encontradas;
    return [dato('Vuelo', hallado.kmz
      ? `${hallado.panoramicas} panorámicas · ${hallado.megas} MB`
      : 'sin subir')];
  }
  const desde = resumen.precio_desde;
  return [
    dato('Disponibles', `${resumen.disponibles ?? 0}/${resumen.parcelas ?? 0}`),
    dato('Precio desde', desde ? dinero(desde.monto, desde.moneda) : 'sin precios'),
  ];
}
