/**
 * La app de Tu Masterplan: la barra, el router y el arranque.
 *
 * Las pantallas viven en la misma página y se cambian con el hash de la URL
 * (`#/planos`, `#/planos/nuevo`, `#/planos/<slug>`, `#/kmz`, `#/kmz/<slug>[/<paso>]`,
 * `#/disenos`, `#/reservas`, `#/contactos`, `#/loteadoras[/<id>]`). Así el botón
 * atrás funciona, un enlace a un loteo se puede mandar, y no hace falta que el
 * servidor conozca más rutas que la de la página.
 */
import { $, $$, avisar, estado, pedir, ruta } from './comun.js';
import { pintarBackOffice, pintarFicha, pintarLoteadoras, prepararBackOffice } from './backoffice.js';
import { pintarConfiguracion, prepararConfiguracion } from './configuracion.js';
import { pintarCuenta, prepararCuenta, recordarClaveProvisional } from './cuenta.js';
import { abrirNuevo, prepararNuevo } from './nuevo.js';
import { abrirDiseno, pintarDisenos, prepararDisenos } from './disenos.js';
import { pintarKmz, prepararKmz } from './kmz.js';
import { pintarKmzs, prepararKmzs } from './kmzs.js';
import { cerrarDialogos, pintarPlano, prepararPlano, seguir } from './plano.js';
import { marcarSeccion } from './barra.js';
import { pintarCifrasEsqueleto, pintarEsqueleto } from './esqueleto.js';
import { pintarPlanos } from './planos.js';
import { cargarReservas, pintarContador, pintarReservas, prepararReservas } from './reservas.js';
import { cargarContactos, pintarContactos, pintarContadorContactos, prepararContactos } from './contactos.js';

const PANTALLAS = ['planos', 'nuevo', 'plano', 'kmzs', 'kmz', 'disenos', 'diseno', 'reservas', 'contactos',
  'loteadoras', 'loteadora', 'configuracion'];

let anterior = null;
// Se llegó a un loteo que no estaba en la lista y se está trayendo: al pintarlo
// hay que rellenar sus datos como si recién se llegara.
let refrescarAlLlegar = false;

// Las pantallas que, mientras llega la primera carga, muestran su propia forma en gris.
// El resto (un master nuevo, un diseño, un KMZ) espera en una pantalla genérica:
// sus formularios no deben quedar a mano antes de tener con qué llenarse.
const CON_ESQUELETO = ['planos', 'kmzs', 'disenos', 'reservas', 'contactos'];

/**
 * Mientras llega la primera carga: la pantalla a la que se va, con su esqueleto.
 * No anota `anterior`, para que al llegar los datos la pantalla se pinte como recién
 * abierta. Configuración no espera: pide lo suyo por su cuenta.
 */
function mostrarCargando(destino) {
  const propia = CON_ESQUELETO.includes(destino.pantalla) || destino.pantalla === 'plano';
  for (const nombre of PANTALLAS) $(`#pantalla-${nombre}`).hidden = !propia || nombre !== destino.pantalla;
  $('#pantalla-cargando').hidden = propia;
  document.body.classList.toggle('pantalla-ancha', false);
  marcarSeccion(destino.pantalla);
  if (destino.pantalla === 'plano') pintarPlano(destino.slug, { buscando: true });
  else if (propia) pintarEsqueleto(destino.pantalla);
  if (destino.pantalla === 'reservas') pintarCifrasEsqueleto($('#reservas-resumen .resumen-planos__cifras'));
}

function mostrar() {
  let destino = ruta(location.hash);
  // El back-office es solo del equipo de CTP (el servidor igual contesta 403): a una
  // loteadora que llega con el enlace se la deja en sus loteos.
  if (destino.pantalla.startsWith('loteadora') && estado.sesion && estado.sesion.rol !== 'plataforma') {
    destino = { pantalla: 'planos' };
  }
  if (!estado.cargado && destino.pantalla !== 'configuracion') {
    mostrarCargando(destino);
    return;
  }
  $('#pantalla-cargando').hidden = true;
  const clave = `${destino.pantalla}/${destino.slug ?? destino.id ?? destino.kmz ?? ''}`;
  const llegando = clave !== anterior;
  anterior = clave;

  for (const nombre of PANTALLAS) $(`#pantalla-${nombre}`).hidden = nombre !== destino.pantalla;
  // Un KMZ pone el plano y el mapa lado a lado: usa todo el ancho.
  document.body.classList.toggle('pantalla-ancha', destino.pantalla === 'kmz');
  marcarSeccion(destino.pantalla);

  if (llegando) {
    avisar(null);
    cerrarDialogos();
    window.scrollTo(0, 0);
  }
  if (destino.pantalla === 'kmz') {
    pintarKmz(destino.slug, { nuevo: llegando, paso: destino.paso });
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
    planos: 'Mis 360°', nuevo: 'Nuevo master', kmzs: 'Mis KMZ', disenos: 'Mis diseños', diseno: 'Diseño',
    reservas: 'Reservas', contactos: 'Contactos', configuracion: 'Configuración',
    loteadoras: 'Loteadoras', loteadora: 'Loteadora',
  }[destino.pantalla] + ' — Tu Masterplan';
  if (destino.pantalla === 'planos') pintarPlanos({ animar: llegando });
  if (destino.pantalla === 'kmzs') pintarKmzs({ animar: llegando });
  if (destino.pantalla === 'nuevo' && llegando) abrirNuevo({ kmz: destino.kmz });
  if (destino.pantalla === 'disenos') pintarDisenos({ animar: llegando });
  if (destino.pantalla === 'reservas') pintarReservas({ animar: llegando });
  if (destino.pantalla === 'contactos') pintarContactos();
  if (destino.pantalla === 'loteadoras') pintarLoteadoras({ llegando });
  if (destino.pantalla === 'loteadora') pintarFicha(destino.id, { llegando });
  if (destino.pantalla === 'configuracion' && llegando) pintarConfiguracion({ animar: true });
  // El editor se rellena al llegar: un refresco no pisa lo que se está escribiendo.
  if (destino.pantalla === 'diseno' && llegando) abrirDiseno(destino.id);
}

async function refrescar() {
  [estado.proyectos, estado.disenos, estado.kmzs] = await Promise.all([
    pedir('/api/proyectos'), pedir('/api/disenos'), pedir('/api/kmz')]);
  // Después de los loteos: se piden las de cada uno publicado.
  estado.reservas = await cargarReservas(estado.proyectos);
  pintarContador();
  estado.contactos = await cargarContactos();
  pintarContadorContactos();
  estado.cargado = true;
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
  prepararReservas({ refrescar });
  prepararContactos({ refrescar });
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
  // La pantalla aparece de inmediato, con la forma de lo que viene, y no en blanco.
  mostrar();

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
    // Sin datos no hay qué esperar: se muestra lo que haya, con el aviso.
    estado.cargado = true;
    mostrar();
    avisar(error.message);
  }
}

arrancar();
