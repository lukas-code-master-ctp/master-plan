/**
 * Primeros pasos: lo que ve una loteadora que llega sola, arriba de Mis 360°, hasta
 * que publica su primer master. Cuatro pasos que se marcan solos con lo que ya hay
 * en la cuenta, para que nadie tenga que adivinar qué preparar ni qué viene después.
 *
 * El equipo de CTP no lo ve: ve los loteos de todas.
 */
import { $, estado } from './comun.js';

const CHECK = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>';

/**
 * Los pasos con su estado. Puro: recibe lo que hay en la cuenta y no toca la página.
 * `null` si ya no hacen falta (hay algo publicado, o es el equipo de CTP).
 */
export function pasosDe({ proyectos = [], disenos = [], preferencias = {}, plataforma = false } = {}) {
  if (plataforma || proyectos.some((p) => p.publicado)) return null;
  const construido = proyectos.find((p) => p.construido);
  const empezado = proyectos[0];
  const enlaceDe = (proyecto) => `#/planos/${encodeURIComponent(proyecto.slug)}`;
  const pedido = construido && !construido.pagado && construido.habilitacion_pedida;

  return [
    {
      clave: 'whatsapp',
      titulo: 'Tu WhatsApp',
      texto: 'El número al que te escriben los compradores desde el sitio. Se pone solo en cada master nuevo.',
      // El de la loteadora o el de algún master: el primero que se escribe en Nuevo
      // master queda como el de la loteadora, y la sesión no se entera hasta recargar.
      hecho: Boolean(preferencias?.whatsapp) || proyectos.some((p) => p.whatsapp),
      accion: { texto: 'Ponerlo', href: '#/configuracion' },
    },
    {
      clave: 'marca',
      titulo: 'Tu marca',
      opcional: true,
      texto: 'Tu logo y tu color en el sitio. Sin marca, sale con la de Tu Masterplan.',
      hecho: disenos.length > 0,
      accion: { texto: 'Crear tu diseño', href: '#/disenos' },
    },
    {
      clave: 'master',
      titulo: 'Tu primer master',
      texto: 'Ten a mano el KMZ del loteo (o el PDF del plano aprobado, para crearlo en Mis KMZ), '
        + 'las panorámicas 360° del dron tal como salen de la cámara y, si quieres, la planilla de precios.',
      hecho: Boolean(construido),
      accion: empezado
        ? { texto: 'Seguir con el master', href: enlaceDe(empezado) }
        : { texto: 'Nuevo master', href: '#/planos/nuevo' },
    },
    {
      clave: 'publicar',
      titulo: 'Publicarlo',
      texto: construido?.pagado
        ? 'Ya está habilitado: publícalo cuando quieras y comparte el enlace con tus compradores.'
        : pedido
          ? 'Ya pediste habilitarlo: te escribimos y te avisamos por correo cuando puedas publicarlo.'
          : 'Construir y revisar es gratis. Cuando te guste cómo quedó, pides que lo habilitemos y lo publicas.',
      hecho: false,
      accion: construido && !pedido ? { texto: 'Ir a publicar', href: enlaceDe(construido) } : null,
    },
  ];
}

export function pintarPrimerosPasos() {
  const caja = $('#primeros-pasos');
  const pasos = pasosDe({
    proyectos: estado.proyectos,
    disenos: estado.disenos,
    preferencias: estado.sesion?.preferencias,
    plataforma: estado.sesion?.rol === 'plataforma',
  });
  caja.hidden = !pasos;
  if (!pasos) return false;
  // El primero sin hacer es el que toca: va destacado.
  const siguiente = pasos.find((p) => !p.hecho && !p.opcional) ?? pasos.find((p) => !p.hecho);
  $('#primeros-pasos-lista').replaceChildren(...pasos.map((paso, indice) => {
    const item = document.createElement('li');
    item.className = 'primer-paso'
      + (paso.hecho ? ' primer-paso--hecho' : '') + (paso === siguiente ? ' primer-paso--siguiente' : '');
    const marca = document.createElement('span');
    marca.className = 'primer-paso__marca';
    if (paso.hecho) {
      marca.innerHTML = CHECK;
      marca.setAttribute('role', 'img');
      marca.setAttribute('aria-label', 'Listo');
    } else {
      marca.textContent = String(indice + 1);
      marca.setAttribute('aria-hidden', 'true');
    }

    const cuerpo = document.createElement('div');
    cuerpo.className = 'primer-paso__cuerpo';
    const titulo = document.createElement('strong');
    titulo.textContent = paso.titulo;
    if (paso.opcional) {
      const opcional = document.createElement('i');
      opcional.textContent = ' opcional';
      titulo.append(opcional);
    }
    const texto = document.createElement('p');
    texto.textContent = paso.texto;
    cuerpo.append(titulo, texto);
    item.append(marca, cuerpo);

    if (paso.accion && !paso.hecho) {
      const enlace = document.createElement('a');
      enlace.className = paso === siguiente ? 'boton' : 'boton boton--contorno';
      enlace.href = paso.accion.href;
      enlace.textContent = paso.accion.texto;
      item.append(enlace);
    }
    return item;
  }));
  return true;
}
