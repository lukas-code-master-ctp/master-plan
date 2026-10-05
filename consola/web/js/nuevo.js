/**
 * Nuevo master: nombre, KMZ, panorámicas, inventario y diseño → Construir.
 *
 * Construir es tres pasos: crear el loteo, subirle los archivos y lanzar la
 * construcción. Si se corta a mitad de camino, el loteo ya creado queda en Mis
 * planos para terminar de subir desde su detalle: nada se pierde.
 *
 * El KMZ se sube como archivo o se elige de Mis KMZ (los terminados). Elegido de
 * Mis KMZ, se pone en el master con `POST /api/proyectos/<slug>/kmz` ANTES de subir
 * las fotos: la subida exige que el master tenga su KMZ al terminar.
 */
import { $, avisar, estado, json, pedir } from './comun.js';
import { opcionesDeDiseno } from './disenos.js';
import { cierraDisponible, elegirParaNuevo } from './cierra.js';
import { comoInventario } from './inventario.js';
import { cuantosLotes, terminados } from './kmzs.js';
import { desdeEntrada, esFoto, esKmz, esPlanilla, megas, soltadero, subir } from './subida.js';

// `mio`: el slug de un KMZ de Mis KMZ elegido en vez de subir el archivo.
const eleccion = { kmz: null, mio: '', fotos: [], inventario: null, cierra: null };
let enCurso = false;

export function prepararNuevo({ alCrear }) {
  const form = $('#nuevo-master');

  const elegirCierra = () => elegirParaNuevo({
    nombre: $('#nuevo-nombre').value.trim(),
    elegidos: eleccion.cierra ?? [],
    alElegir: (proyectos) => {
      eleccion.cierra = proyectos;
      eleccion.inventario = null;     // o Cierra o planilla: las dos se pisarían
      pintar();
    },
  }).catch((error) => avisar(error.message));
  $('#nuevo-cierra-elegir').addEventListener('click', elegirCierra);
  $('#nuevo-cierra-cambiar').addEventListener('click', elegirCierra);
  $('#nuevo-cierra-quitar').addEventListener('click', () => {
    eleccion.cierra = null;
    $('#nuevo-con-cierra').hidden = false;
    pintar();
  });

  $('#nuevo-kmz').addEventListener('change', (e) => tomar(desdeEntrada(e.target)));
  $('#nuevo-fotos').addEventListener('change', (e) => tomar(desdeEntrada(e.target)));
  $('#nuevo-carpeta').addEventListener('change', (e) => tomar(desdeEntrada(e.target)));
  $('#nuevo-inventario').addEventListener('change', (e) => {
    const [elegido] = desdeEntrada(e.target);
    if (elegido) eleccion.inventario = elegido;
    pintar();
  });
  for (const caja of ['#caja-kmz', '#caja-fotos', '#caja-inventario']) soltadero($(caja), tomar);

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    if (enCurso) return;
    await construir(alCrear);
  });

  $('#nuevo-mio').addEventListener('change', (e) => {
    eleccion.mio = e.target.value;
    pintar();
  });

  $('#vincular').addEventListener('click', async () => {
    const ruta = $('#ruta').value.trim();
    if (!ruta) return;
    try {
      const vinculado = await pedir('/api/proyectos/vincular', json({ ruta }));
      await alCrear(vinculado.slug);
    } catch (error) { avisar(error.message); }
  });
}

/**
 * Al entrar a la pantalla se parte de cero. `kmz` es un KMZ de Mis KMZ ya elegido
 * (llega de "Usar en un master" → "Nuevo master con este KMZ").
 */
export function abrirNuevo({ kmz = null } = {}) {
  if (enCurso) return;
  $('#nuevo-master').reset();
  eleccion.kmz = null;
  eleccion.fotos = [];
  eleccion.inventario = null;
  eleccion.cierra = null;
  // "Conéctalo con Cierra" solo si la consola tiene Cierra configurado.
  $('#nuevo-con-cierra').hidden = true;
  cierraDisponible().then((hay) => { $('#nuevo-con-cierra').hidden = !hay || Boolean(eleccion.cierra); });
  const listos = terminados(estado.kmzs);
  eleccion.mio = listos.some((k) => k.slug === kmz) ? kmz : '';
  opcionesDeMisKmz($('#nuevo-mio'), listos, eleccion.mio);
  $('#nuevo-progreso').hidden = true;
  $('#carpeta-local').hidden = !(estado.sesion?.rol === 'plataforma' && estado.sesion?.puede_vincular);
  opcionesDeDiseno($('#nuevo-diseno'), null);
  // Con el KMZ elegido, el nombre del master parte con el del KMZ.
  const elegido = listos.find((k) => k.slug === eleccion.mio);
  if (elegido) $('#nuevo-nombre').value = elegido.nombre;
  pintar();
  $('#nuevo-nombre').focus();
}

/** "Subir un archivo" y después los KMZ terminados de la loteadora. */
function opcionesDeMisKmz(select, listos, elegido) {
  const opciones = [{ slug: '', texto: 'No: subo el archivo' },
    ...listos.map((k) => ({ slug: k.slug, texto: [k.nombre, cuantosLotes(k.lotes)].filter(Boolean).join(' · ') }))];
  select.replaceChildren(...opciones.map(({ slug, texto }) => {
    const opcion = document.createElement('option');
    opcion.value = slug;
    opcion.textContent = texto;
    return opcion;
  }));
  select.value = elegido;
  $('#nuevo-mio-caja').hidden = !listos.length;
  $('#nuevo-mio-vacio').hidden = listos.length > 0;
}

/**
 * Reparte lo elegido o soltado entre los campos. Da lo mismo en cuál se suelte
 * la carpeta del vuelo: el KMZ va al KMZ, las fotos a panorámicas y la planilla
 * al inventario, que es lo que uno esperaría.
 */
function tomar(encontrados) {
  const fotos = encontrados.filter(({ ruta }) => esFoto(ruta));
  const kmz = encontrados.find(({ ruta }) => esKmz(ruta));
  const planilla = encontrados.find(({ ruta }) => esPlanilla(ruta) && !ruta.split('/').pop().startsWith('~$'));
  // Con uno de Mis KMZ elegido, el KMZ que traiga la carpeta no lo pisa.
  if (kmz && !eleccion.mio) eleccion.kmz = { archivo: kmz.archivo, ruta: kmz.archivo.name };
  if (fotos.length) eleccion.fotos = fotos;
  if (planilla) eleccion.inventario = planilla;
  pintar();
}

function pintar() {
  // Elegido de Mis KMZ, no hay archivo que subir.
  $('#caja-kmz').hidden = Boolean(eleccion.mio);
  $('#nuevo-mio-rotulo').textContent = eleccion.mio ? 'De Mis KMZ' : 'o elige uno de Mis KMZ';
  const marcar = (caja, texto, lleno) => {
    $(`#texto-${caja}`).textContent = texto;
    $(`#caja-${caja}`).classList.toggle('archivo--lleno', lleno);
  };
  marcar('kmz', eleccion.kmz ? eleccion.kmz.archivo.name : 'Subir el plano (.kmz)', Boolean(eleccion.kmz));
  marcar('fotos', eleccion.fotos.length
    ? `${eleccion.fotos.length} panorámicas · ${megas(eleccion.fotos).toFixed(0)} MB`
    : 'Arrastra la carpeta del vuelo o elige las fotos', eleccion.fotos.length > 0);
  // Con Cierra elegido, la planilla sobra: el inventario llega de allá.
  const conCierra = Boolean(eleccion.cierra);
  $('#caja-inventario').hidden = conCierra;
  $('#nuevo-inventario-nota').hidden = conCierra;
  $('#nuevo-cierra').hidden = !conCierra;
  if (conCierra) {
    $('#nuevo-con-cierra').hidden = true;
    $('#nuevo-cierra-texto').textContent = 'De Cierra: '
      + eleccion.cierra.map((p) => `${p.nombre} (etapa ${p.etapa})`).join(', ');
  }
  marcar('inventario', eleccion.inventario
    ? eleccion.inventario.archivo.name
    : 'Subir la planilla de precios (.xlsx o .csv)', Boolean(eleccion.inventario));
}

/** El inventario va en la raíz, con el nombre que el pipeline pone primero. */
function archivosASubir() {
  const lista = [...(eleccion.mio ? [] : [eleccion.kmz]), ...eleccion.fotos.map(({ archivo, ruta }) => ({
    archivo, ruta: `panoramicas/${ruta}` }))];
  if (eleccion.inventario) lista.push(comoInventario(eleccion.inventario));
  return lista;
}

function faltante() {
  if (!$('#nuevo-nombre').value.trim()) return ['Ponle un nombre al loteo.', '#nuevo-nombre'];
  if (!eleccion.kmz && !eleccion.mio) {
    return ['Falta el KMZ del loteo: es el plano que se dibuja sobre las fotos. Súbelo o elige uno de Mis KMZ.',
      $('#nuevo-mio-caja').hidden ? '#nuevo-kmz' : '#nuevo-mio'];
  }
  if (!eleccion.fotos.length) return ['Faltan las panorámicas del dron.', '#nuevo-fotos'];
  // El servidor lo rechaza igual, pero después de recibir todo: mejor decirlo
  // antes de mandar un giga.
  const tope = estado.sesion?.limites?.megas_por_loteo;
  const total = megas(archivosASubir());
  if (tope && total > tope) {
    return [`Son ${Math.round(total)} MB y el máximo por loteo es ${tope} MB. `
      + 'Sube solo las panorámicas del vuelo, sin videos ni fotos sueltas.', '#nuevo-fotos'];
  }
  return null;
}

/** Los mensajes del servidor no siempre terminan en punto, y aquí sigue otra frase. */
const conPunto = (texto) => (/[.!?…]$/.test(texto) ? texto : `${texto}.`);

async function construir(alCrear) {
  avisar(null);
  const falta = faltante();
  if (falta) {
    avisar(falta[0]);
    $(falta[1]).focus();
    return;
  }

  enCurso = true;
  const boton = $('#construir-nuevo');
  boton.disabled = true;
  const paso = (texto, fraccion) => {
    $('#nuevo-progreso').hidden = false;
    $('#nuevo-paso').textContent = texto;
    $('#nuevo-progreso i').style.width = `${Math.round(fraccion * 100)}%`;
  };

  let slug = null;
  let poniendoKmz = false;
  try {
    paso('Creando el loteo…', 0);
    slug = (await pedir('/api/proyectos', json({
      nombre: $('#nuevo-nombre').value.trim(),
      diseno_id: $('#nuevo-diseno').value || null,
    }))).slug;
    if (eleccion.cierra) {
      // Conectado antes de construir: la construcción trae lo de Cierra sola.
      paso('Conectando con Cierra…', 0);
      await pedir(`/api/proyectos/${encodeURIComponent(slug)}/cierra`,
        json({ proyectos: eleccion.cierra.map(({ id, etapa }) => ({ id, etapa })) }, 'PUT'));
    }
    if (eleccion.mio) {
      // Antes que las fotos: la subida pide que el master ya tenga su KMZ.
      paso('Poniendo el KMZ de Mis KMZ…', 0);
      poniendoKmz = true;
      await pedir(`/api/proyectos/${encodeURIComponent(slug)}/kmz`, json({ kmz: eleccion.mio }));
      poniendoKmz = false;
    }
    const lista = archivosASubir();
    const total = megas(lista);
    await subir(slug, lista, (fraccion) =>
      paso(`Subiendo ${Math.round(fraccion * total)} de ${Math.round(total)} MB…`, fraccion));
    paso('Empezando a construir…', 1);
    await pedir(`/api/proyectos/${slug}/construir`, json({}));
    await alCrear(slug);
  } catch (error) {
    if (slug) {
      // El loteo ya existe: se sigue desde su detalle, donde se puede reintentar.
      // Si ni eso se puede (se cortó la red), igual hay que decir qué pasó.
      try { await alCrear(slug); } catch { /* el aviso de abajo basta */ }
      avisar(poniendoKmz
        // Sin KMZ no se subió nada: se elige de nuevo desde el detalle (o se borra el master).
        ? `No se pudo poner el KMZ de Mis KMZ: ${conPunto(error.message)} El master quedó creado sin KMZ ni fotos: `
          + 'usa "Usar un KMZ de Mis KMZ" o sube el archivo desde aquí, o quítalo de la lista si no lo necesitas.'
        : `${conPunto(error.message)} El loteo quedó creado: sube lo que falte desde su detalle.`);
    } else {
      avisar(error.message);
    }
  } finally {
    enCurso = false;
    boton.disabled = false;
  }
}
