/**
 * Nuevo master: nombre, KMZ, panorámicas, inventario y diseño → Construir.
 *
 * Construir es tres pasos: crear el loteo, subirle los archivos y lanzar la
 * construcción. Si se corta a mitad de camino, el loteo ya creado queda en Mis
 * planos para terminar de subir desde su detalle: nada se pierde.
 */
import { $, avisar, estado, json, pedir } from './comun.js';
import { opcionesDeDiseno } from './disenos.js';
import { desdeEntrada, esFoto, esKmz, esPlanilla, megas, soltadero, subir } from './subida.js';

const eleccion = { kmz: null, fotos: [], inventario: null };
let enCurso = false;

export function prepararNuevo({ alCrear }) {
  const form = $('#nuevo-master');

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

  $('#vincular').addEventListener('click', async () => {
    const ruta = $('#ruta').value.trim();
    if (!ruta) return;
    try {
      const vinculado = await pedir('/api/proyectos/vincular', json({ ruta }));
      await alCrear(vinculado.slug);
    } catch (error) { avisar(error.message); }
  });
}

/** Al entrar a la pantalla se parte de cero. */
export function abrirNuevo() {
  if (enCurso) return;
  $('#nuevo-master').reset();
  eleccion.kmz = null;
  eleccion.fotos = [];
  eleccion.inventario = null;
  $('#nuevo-progreso').hidden = true;
  $('#carpeta-local').hidden = !(estado.sesion?.rol === 'plataforma' && estado.sesion?.puede_vincular);
  opcionesDeDiseno($('#nuevo-diseno'), null);
  pintar();
  $('#nuevo-nombre').focus();
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
  if (kmz) eleccion.kmz = { archivo: kmz.archivo, ruta: kmz.archivo.name };
  if (fotos.length) eleccion.fotos = fotos;
  if (planilla) eleccion.inventario = planilla;
  pintar();
}

function pintar() {
  const marcar = (caja, texto, lleno) => {
    $(`#texto-${caja}`).textContent = texto;
    $(`#caja-${caja}`).classList.toggle('archivo--lleno', lleno);
  };
  marcar('kmz', eleccion.kmz ? eleccion.kmz.archivo.name : 'Subir el plano (.kmz)', Boolean(eleccion.kmz));
  marcar('fotos', eleccion.fotos.length
    ? `${eleccion.fotos.length} panorámicas · ${megas(eleccion.fotos).toFixed(0)} MB`
    : 'Arrastra la carpeta del vuelo o elige las fotos', eleccion.fotos.length > 0);
  marcar('inventario', eleccion.inventario
    ? eleccion.inventario.archivo.name
    : 'Subir la planilla de precios (.xlsx o .csv)', Boolean(eleccion.inventario));
}

/** El inventario va en la raíz; un CSV, con el nombre que busca el pipeline. */
function archivosASubir() {
  const lista = [eleccion.kmz, ...eleccion.fotos.map(({ archivo, ruta }) => ({
    archivo, ruta: `panoramicas/${ruta}` }))];
  if (eleccion.inventario) {
    const { archivo } = eleccion.inventario;
    const csv = /\.csv$/i.test(archivo.name);
    lista.push({ archivo, ruta: csv ? 'inventario.csv' : archivo.name });
  }
  return lista;
}

function faltante() {
  if (!$('#nuevo-nombre').value.trim()) return ['Ponle un nombre al loteo.', '#nuevo-nombre'];
  if (!eleccion.kmz) return ['Falta el KMZ del loteo: es el plano que se dibuja sobre las fotos.', '#nuevo-kmz'];
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
  try {
    paso('Creando el loteo…', 0);
    slug = (await pedir('/api/proyectos', json({
      nombre: $('#nuevo-nombre').value.trim(),
      diseno_id: $('#nuevo-diseno').value || null,
    }))).slug;
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
      avisar(`${error.message} El loteo quedó creado: sube lo que falte desde su detalle.`);
    } else {
      avisar(error.message);
    }
  } finally {
    enCurso = false;
    boton.disabled = false;
  }
}
