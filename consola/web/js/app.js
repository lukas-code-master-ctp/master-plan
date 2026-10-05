/**
 * La app de Tu Masterplan: la barra, el router y el arranque.
 *
 * Las pantallas viven en la misma página y se cambian con el hash de la URL
 * (`#/planos`, `#/planos/nuevo`, `#/planos/<slug>`, `#/kmz`, `#/kmz/<slug>`,
 * `#/disenos`). Así el botón
 * atrás funciona, un enlace a un loteo se puede mandar, y no hace falta que el
 * servidor conozca más rutas que la de la página.
 */
import { $, $$, avisar, estado, pedir, ruta } from './comun.js';
import { pintarBackOffice, prepararBackOffice } from './backoffice.js';
import { pintarConfiguracion, prepararConfiguracion } from './configuracion.js';
import { pintarCuenta, prepararCuenta, recordarClaveProvisional } from './cuenta.js';
import { abrirNuevo, prepararNuevo } from './nuevo.js';
import { abrirDiseno, pintarDisenos, prepararDisenos } from './disenos.js';
import { pintarKmz, prepararKmz } from './kmz.js';
import { pintarKmzs, prepararKmzs } from './kmzs.js';
import { cerrarDialogos, pintarPlano, prepararPlano, seguir } from './plano.js';
import { pintarPlanos } from './planos.js';

const PANTALLAS = ['planos', 'nuevo', 'plano', 'kmzs', 'kmz', 'disenos', 'diseno', 'configuracion'];

let anterior = null;
// Se llegó a un loteo que no estaba en la lista y se está trayendo: al pintarlo
// hay que rellenar sus datos como si recién se llegara.
let refrescarAlLlegar = false;

function mostrar() {
  const destino = ruta(location.hash);
  const clave = `${destino.pantalla}/${destino.slug ?? destino.id ?? destino.kmz ?? ''}`;
  const llegando = clave !== anterior;
  anterior = clave;

  for (const nombre of PANTALLAS) $(`#pantalla-${nombre}`).hidden = nombre !== destino.pantalla;
  // Un KMZ pone el plano y el mapa lado a lado: usa todo el ancho.
  document.body.classList.toggle('pantalla-ancha', destino.pantalla === 'kmz');
  const seccion = destino.pantalla.startsWith('diseno') ? 'disenos'
    : destino.pantalla.startsWith('kmz') ? 'kmz' : 'planos';
  for (const enlace of $$('.pestanas a')) {
    if (enlace.dataset.seccion === seccion) enlace.setAttribute('aria-current', 'page');
    else enlace.removeAttribute('aria-current');
  }

  if (llegando) {
    avisar(null);
    cerrarDialogos();
    window.scrollTo(0, 0);
  }
  if (destino.pantalla === 'kmz') {
    pintarKmz(destino.slug, { nuevo: llegando });
    return;
  }
  if (destino.pantalla === 'plano') {
    const conocido = estado.proyectos.some((p) => p.slug === destino.slug);
    // Un loteo creado en otra pestaña, o recién creado acá: la lista que hay
    // todavía no lo trae. Se pide de nuevo una vez antes de decir que no existe.
    if (!conocido && llegando) {
      pintarPlano(destino.slug, { buscando: true });
      refrescarAlLlegar = true;
      refrescar().catch((error) => avisar(error.message));
      return;
    }
    pintarPlano(destino.slug, { nuevo: llegando || refrescarAlLlegar });
    refrescarAlLlegar = false;
    return;
  }
  document.title = {
    planos: 'Mis planos', nuevo: 'Nuevo master', kmzs: 'Mis KMZ', disenos: 'Mis diseños', diseno: 'Diseño',
    configuracion: 'Configuración',
  }[destino.pantalla] + ' — Tu Masterplan';
  if (destino.pantalla === 'planos') pintarPlanos();
  if (destino.pantalla === 'kmzs') pintarKmzs();
  if (destino.pantalla === 'nuevo' && llegando) abrirNuevo({ kmz: destino.kmz });
  if (destino.pantalla === 'disenos') pintarDisenos();
  if (destino.pantalla === 'configuracion' && llegando) pintarConfiguracion();
  // El editor se rellena al llegar: un refresco no pisa lo que se está escribiendo.
  if (destino.pantalla === 'diseno' && llegando) abrirDiseno(destino.id);
}

async function refrescar() {
  [estado.proyectos, estado.disenos, estado.kmzs] = await Promise.all([
    pedir('/api/proyectos'), pedir('/api/disenos'), pedir('/api/kmz')]);
  // Un trabajo puede seguir corriendo de una recarga de página: retomarlo. Los de
  // un KMZ van con la clave del servidor, `kmz:<slug>`, para no chocar con un master.
  for (const proyecto of estado.proyectos) {
    if (proyecto.trabajo && !estado.sondeos.has(proyecto.slug)) seguir(proyecto.slug, proyecto.trabajo.id);
  }
  for (const kmz of estado.kmzs) {
    const clave = `kmz:${kmz.slug}`;
    if (kmz.trabajo && !estado.sondeos.has(clave)) seguir(clave, kmz.trabajo.id);
  }
  mostrar();
}

function pintarGuia() {
  const equipo = estado.sesion.rol === 'plataforma';
  $('#guia').textContent = equipo
    ? 'Los loteos de todas las loteadoras. Los que crees tú quedan a nombre de tu equipo.'
    : 'Subes el vuelo, lo construyes, revisas que las parcelas caigan bien y lo publicas.';
}

async function arrancar() {
  prepararCuenta();
  prepararPlano({ refrescar });
  prepararBackOffice({ refrescar });
  prepararDisenos({ refrescar });
  prepararConfiguracion();
  prepararKmz({ refrescar });
  prepararKmzs({ refrescar });
  prepararNuevo({
    alCrear: async (slug) => {
      location.hash = `#/planos/${encodeURIComponent(slug)}`;
      await refrescar();
    },
  });
  window.addEventListener('hashchange', mostrar);

  try {
    estado.sesion = await pedir('/api/sesion');
  } catch {
    location.href = '/entrar';       // la sesión venció entre carga y carga
    return;
  }
  pintarCuenta();
  pintarBackOffice();
  pintarGuia();
  try {
    await refrescar();
    recordarClaveProvisional();
  } catch (error) {
    mostrar();
    avisar(error.message);
  }
}

arrancar();
