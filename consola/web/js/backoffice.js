/**
 * Back-office: lo que solo ve el equipo de Tu Masterplan.
 *
 * Que los botones estén escondidos no protege nada —el servidor contesta 403
 * igual—; es para que una loteadora no vea puertas que no puede abrir.
 *
 * El diálogo Loteadoras tiene dos vistas: el padrón (arriba, los pedidos por
 * habilitar; abajo, todas las loteadoras) y la ficha de una, con sus loteos, su
 * gente y lo último que pasó.
 */
import { $, $$, abrirDialogo, avisar, estado, json, pedir, pastilla } from './comun.js';
import { fraseDe } from './actividad.js';

let loteadoras = [];
let fichaAbierta = null;      // el id de la loteadora cuya ficha se ve, o null en el padrón
let refrescar = async () => {};

const DIA = new Intl.DateTimeFormat('es-CL', { day: 'numeric', month: 'short', year: 'numeric' });
const DIA_CORTO = new Intl.DateTimeFormat('es-CL', { day: 'numeric', month: 'short' });
const ROLES = { 'dueño': 'Dueño', equipo: 'Equipo', plataforma: 'Equipo CTP' };

// --- lo que se puede probar sin página ------------------------------------------------

/** En qué está un loteo, visto desde el cobro: es lo que el back-office decide. */
export function estadoDelLoteo(loteo) {
  if (loteo.publicado) return { texto: 'Publicado', tono: 'ok' };
  if (loteo.pagado) return { texto: 'Habilitado', tono: 'ok' };
  if (loteo.habilitacion_pedida) {
    return { texto: `Pidió habilitar · ${DIA_CORTO.format(new Date(loteo.habilitacion_pedida))}`, tono: 'aviso' };
  }
  return { texto: 'Sin pagar', tono: null };
}

/** El resumen de una loteadora en el padrón: "3 loteos · 2 cuentas". */
export function resumenDe(cliente) {
  const loteos = `${cliente.loteos} ${cliente.loteos === 1 ? 'loteo' : 'loteos'}`;
  const cuantas = cliente.cuentas.length;
  return `${loteos} · ${cuantas} ${cuantas === 1 ? 'cuenta' : 'cuentas'}`;
}

/** Lo que conviene saber de una cuenta cuando alguien dice que no puede entrar. */
export function marcasDeCuenta(cuenta) {
  const marcas = [{ texto: ROLES[cuenta.rol] ?? cuenta.rol, tono: null }];
  if (!cuenta.activo) marcas.push({ texto: 'Desactivada', tono: 'apagada' });
  else if (!cuenta.email_verificado) marcas.push({ texto: 'Sin confirmar el correo', tono: 'aviso' });
  return marcas;
}

// --- ayudas de DOM --------------------------------------------------------------------

function nodo(etiqueta, clase, texto) {
  const n = document.createElement(etiqueta);
  if (clase) n.className = clase;
  if (texto != null) n.textContent = texto;
  return n;
}

function boton(texto, alClic, clase = 'boton boton--texto') {
  const b = nodo('button', clase, texto);
  b.type = 'button';
  b.addEventListener('click', alClic);
  return b;
}

function chip(texto, tono) {
  return nodo('span', `chip${tono ? ` chip--${tono}` : ''}`, texto);
}

/** Muestra una clave provisional, que no se guarda en claro en ninguna parte. */
function mostrarClave(lineas) {
  const caja = $('#clientes-clave');
  caja.textContent = `${lineas.join('\n')}\n\nCópiala ahora: no se vuelve a mostrar. Pásasela por un canal aparte.`;
  caja.hidden = false;
  caja.scrollIntoView({ block: 'nearest' });
}

/**
 * Un botón "Anotar pago" que, al apretarlo, abre ahí mismo dónde anotar cómo se
 * pagó. Sin pasarela, esa línea es el único registro del cobro.
 */
function anotarPago(loteo) {
  const caja = nodo('div', 'padron__pago');
  const abrir = boton('Anotar pago', () => {
    abrir.hidden = true;
    formulario.hidden = false;
    entrada.focus();
  }, 'boton boton--chico');
  const formulario = nodo('div', 'fila');
  formulario.hidden = true;
  const entrada = nodo('input');
  Object.assign(entrada, { type: 'text', placeholder: 'Cómo se pagó', autocomplete: 'off' });
  entrada.setAttribute('aria-label', `Cómo se pagó ${loteo.nombre}`);
  const listo = boton('Habilitar', async () => {
    const cobro = entrada.value.trim();
    if (!cobro) return avisar('Anota cómo se pagó: es el único registro del cobro.');
    listo.disabled = true;
    try {
      await pedir(`/api/plataforma/proyectos/${loteo.slug}/pago`, json({ nota_cobro: cobro }));
      avisar(`${loteo.nombre} quedó habilitado. Le avisamos por correo a la loteadora.`, 'ok');
      await recargar();
      refrescar().catch(() => {});
    } catch (error) {
      avisar(error.message);
      listo.disabled = false;
    }
  }, 'boton boton--chico');
  entrada.addEventListener('keydown', (e) => { if (e.key === 'Enter') listo.click(); });
  formulario.append(entrada, listo);
  caja.append(abrir, formulario);
  return caja;
}

function enlaceAlLoteo(loteo) {
  const a = nodo('a', 'padron__enlace', loteo.nombre);
  a.href = `#/planos/${loteo.slug}`;
  return a;
}

// --- el padrón ------------------------------------------------------------------------

async function cargarLoteadoras() {
  loteadoras = await pedir('/api/plataforma/clientes');
  $('#clientes-lista').replaceChildren(...loteadoras.map(filaLoteadora));
  // Sin loteadora elegida de partida: la primera de la lista es la propia (CTP) y
  // habilitar a nombre de otra por no tocar el selector deja el loteo mal puesto.
  const elegir = new Option('Elige una loteadora', '', true, true);
  elegir.disabled = true;
  $('#habilitar-cliente').replaceChildren(elegir, ...loteadoras.map((c) => {
    const suspendida = c.estado !== 'activo';
    const opcion = new Option(suspendida ? `${c.nombre} · suspendida` : c.nombre, c.id);
    // Su gente no puede entrar: el loteo quedaría donde nadie lo ve.
    opcion.disabled = suspendida;
    return opcion;
  }));
}

async function cargarPorHabilitar() {
  const pedidos = await pedir('/api/plataforma/por-habilitar');
  $('#por-habilitar').hidden = !pedidos.length;
  $('#por-habilitar-cuenta').textContent = pedidos.length;
  $('#por-habilitar-lista').replaceChildren(...pedidos.map((loteo) => {
    const fila = nodo('div', 'padron__fila padron__fila--pedido');
    const texto = nodo('div', 'padron__texto');
    const detalle = nodo('span', 'ayuda',
      `${loteo.cliente} · pidió el ${DIA.format(new Date(loteo.habilitacion_pedida))}`);
    texto.append(enlaceAlLoteo(loteo), detalle);
    fila.append(texto, anotarPago(loteo));
    return fila;
  }));
}

function filaLoteadora(cliente) {
  const fila = nodo('div', 'padron__fila');
  const abrir = nodo('button', 'padron__abrir');
  abrir.type = 'button';
  abrir.setAttribute('aria-label', `Ver la ficha de ${cliente.nombre}`);
  const titulo = nodo('span', 'padron__nombre');
  titulo.append(nodo('strong', null, cliente.nombre));
  if (cliente.id === estado.sesion?.cliente_id) titulo.append(chip('La tuya'));
  if (cliente.estado !== 'activo') titulo.append(chip('Suspendida', 'apagada'));
  if (cliente.por_habilitar) titulo.append(chip(`${cliente.por_habilitar} por habilitar`, 'aviso'));
  abrir.append(titulo, nodo('span', 'ayuda', resumenDe(cliente)));
  abrir.addEventListener('click', () => abrirFicha(cliente.id));
  fila.append(abrir, nodo('span', 'padron__flecha', '›'));
  return fila;
}

/** Vuelve a pedir lo que se está viendo: el padrón entero o la ficha abierta. */
async function recargar() {
  if (fichaAbierta != null) {
    await Promise.all([pintarFicha(fichaAbierta), cargarLoteadoras(), cargarPorHabilitar()]);
  } else {
    await Promise.all([cargarLoteadoras(), cargarPorHabilitar()]);
  }
}

function verPadron() {
  fichaAbierta = null;
  $('#padron-ficha').hidden = true;
  $('#padron-todas').hidden = false;
  $('#clientes-clave').hidden = true;
  avisar(null);
}

// --- la ficha -------------------------------------------------------------------------

async function abrirFicha(clienteId) {
  try {
    await pintarFicha(clienteId);
  } catch (error) { return avisar(error.message); }
  fichaAbierta = clienteId;
  $('#clientes-clave').hidden = true;
  avisar(null);
  $('#padron-todas').hidden = true;
  $('#padron-ficha').hidden = false;
  $('#clientes').scrollTop = 0;
}

async function pintarFicha(clienteId) {
  const ficha = await pedir(`/api/plataforma/clientes/${clienteId}`);
  const propia = ficha.id === estado.sesion?.cliente_id;
  const activa = ficha.estado === 'activo';

  const volver = boton('← Todas las loteadoras', verPadron, 'boton boton--texto ficha__volver');

  const cabeza = nodo('div', 'ficha__cabeza');
  const titulo = nodo('div');
  titulo.append(nodo('h2', null, ficha.nombre), nodo('p', 'ayuda',
    `Desde el ${DIA.format(new Date(ficha.creado_en))} · ${activa ? 'activa' : 'suspendida'}`));
  const acciones = nodo('div', 'ficha__acciones');
  if (activa) {
    acciones.append(boton('Habilitar un loteo', () => abrirHabilitar(ficha.id), 'boton boton--chico'));
  }
  // La propia loteadora no se puede suspender —quedaría la app sin operador y
  // nadie por encima para arreglarlo—, así que el servidor lo rechaza. Ofrecer el
  // botón sería prometer algo que siempre falla.
  if (!propia) acciones.append(boton(activa ? 'Suspender' : 'Reactivar', () => cambiarEstado(ficha)));
  cabeza.append(titulo, acciones);

  $('#padron-ficha').replaceChildren(volver, cabeza,
    seccionLoteos(ficha), seccionCuentas(ficha), seccionHistorial(ficha));
}

function seccion(titulo, cantidad) {
  const s = nodo('section', 'padron__bloque');
  const h = nodo('h3', null, titulo);
  if (cantidad != null) h.append(' ', nodo('span', 'config__cuenta', String(cantidad)));
  s.append(h);
  return s;
}

function seccionLoteos(ficha) {
  const s = seccion('Loteos', ficha.loteos.length);
  if (!ficha.loteos.length) {
    s.append(nodo('p', 'ayuda', 'Todavía no tiene loteos.'));
    return s;
  }
  // Primero lo que espera algo del equipo; después, el resto por nombre.
  const orden = (l) => (!l.pagado && l.habilitacion_pedida ? 0 : 1);
  const loteos = [...ficha.loteos].sort((a, b) => orden(a) - orden(b) || a.nombre.localeCompare(b.nombre));
  const lista = nodo('div', 'padron');
  for (const loteo of loteos) {
    const fila = nodo('div', 'padron__fila');
    const texto = nodo('div', 'padron__texto');
    const { texto: etiqueta, tono } = estadoDelLoteo(loteo);
    const linea = nodo('span', 'padron__nombre');
    linea.append(enlaceAlLoteo(loteo), pastilla(etiqueta, tono));
    texto.append(linea);
    if (loteo.nota_cobro) texto.append(nodo('span', 'ayuda', `Cobro: ${loteo.nota_cobro}`));
    fila.append(texto);
    if (!loteo.pagado) fila.append(anotarPago(loteo));
    lista.append(fila);
  }
  s.append(lista);
  return s;
}

function seccionCuentas(ficha) {
  const s = seccion('Cuentas', ficha.cuentas.length);
  const lista = nodo('div', 'padron');
  for (const cuenta of ficha.cuentas) {
    const fila = nodo('div', 'padron__fila');
    const texto = nodo('div', 'padron__texto');
    const linea = nodo('span', 'padron__nombre');
    linea.append(nodo('strong', null, cuenta.nombre || cuenta.email),
      ...marcasDeCuenta(cuenta).map((m) => chip(m.texto, m.tono)));
    texto.append(linea);
    if (cuenta.nombre && cuenta.nombre !== cuenta.email) texto.append(nodo('span', 'ayuda', cuenta.email));
    fila.append(texto, boton('Dar clave nueva', () => darClaveNueva(cuenta.email)));
    lista.append(fila);
  }
  s.append(lista);

  const agregar = nodo('details', 'alternativa');
  agregar.append(nodo('summary', null, 'Agregar una cuenta'));
  const fila = nodo('div', 'fila fila--envuelve');
  const email = nodo('input');
  Object.assign(email, { type: 'email', placeholder: 'correo', autocomplete: 'off' });
  const nombre = nodo('input');
  Object.assign(nombre, { type: 'text', placeholder: 'nombre', autocomplete: 'off' });
  const crear = boton('Agregar', async () => {
    const correo = email.value.trim();
    if (!correo) return avisar('Escribe el correo de la cuenta nueva.');
    try {
      const nueva = await pedir(`/api/plataforma/clientes/${ficha.id}/usuarios`,
        json({ email: correo, nombre: nombre.value.trim() }));
      await pintarFicha(ficha.id);
      mostrarClave([ficha.nombre, nueva.email, `Clave provisional: ${nueva.clave_provisional}`]);
    } catch (error) { avisar(error.message); }
  }, 'boton');
  fila.append(email, nombre, crear);
  agregar.append(fila, nodo('p', 'ayuda',
    'Entra con rol de equipo y una clave provisional que se muestra una sola vez.'));
  s.append(agregar);
  return s;
}

function seccionHistorial(ficha) {
  const s = seccion('Lo último');
  if (!ficha.historial.length) {
    s.append(nodo('p', 'ayuda', 'Sin movimientos todavía.'));
    return s;
  }
  const lista = nodo('ul', 'ficha__historial');
  for (const evento of ficha.historial) {
    const item = nodo('li');
    item.append(nodo('span', 'ficha__cuando', DIA_CORTO.format(new Date(evento.cuando))),
      nodo('span', null, fraseDe(evento).texto));
    lista.append(item);
  }
  s.append(lista);
  return s;
}

async function cambiarEstado(cliente) {
  const nuevo = cliente.estado === 'activo' ? 'suspendido' : 'activo';
  if (nuevo === 'suspendido' && !confirm(
    `Suspender a ${cliente.nombre}\n\nSu gente queda afuera en la petición siguiente.`)) return;
  try {
    await pedir(`/api/plataforma/clientes/${cliente.id}/estado`, json({ estado: nuevo }));
    await recargar();
  } catch (error) { avisar(error.message); }
}

async function darClaveNueva(email) {
  if (!confirm(`¿Dar una contraseña nueva a ${email}?\n\nSe cierran sus sesiones abiertas.`)) return;
  try {
    const nueva = await pedir('/api/plataforma/usuarios/clave', json({ email }));
    mostrarClave([nueva.email, `Clave provisional: ${nueva.clave_provisional}`]);
  } catch (error) { avisar(error.message); }
}

// --- habilitar un loteo ---------------------------------------------------------------

async function abrirHabilitar(clienteId = null) {
  try { await cargarLoteadoras(); } catch (error) { return avisar(error.message); }
  if (!loteadoras.length) return avisar('Primero da de alta una loteadora.');
  if (clienteId != null) $('#habilitar-cliente').value = String(clienteId);
  $('#habilitar-nombre').value = '';
  $('#habilitar-cobro').value = '';
  if ($('#clientes').open) $('#clientes').close();
  abrirDialogo($('#habilitar'));
}

// --- arranque -------------------------------------------------------------------------

export function pintarBackOffice() {
  const equipo = estado.sesion?.rol === 'plataforma';
  $('#loteadoras').hidden = !equipo;
  $('#nuevo').hidden = !equipo;
  $('#pestana-contactos').hidden = !equipo;
}

export function prepararBackOffice(opciones) {
  refrescar = opciones.refrescar;

  for (const b of $$('[data-cerrar]')) {
    b.addEventListener('click', () => b.closest('dialog').close());
  }

  $('#loteadoras').addEventListener('click', async () => {
    verPadron();
    try { await recargar(); } catch (error) { return avisar(error.message); }
    abrirDialogo($('#clientes'));
  });

  $('#cliente-crear').addEventListener('click', async () => {
    const nombre = $('#cliente-nombre').value.trim();
    const email = $('#cliente-email').value.trim();
    if (!nombre || !email) return avisar('Hacen falta el nombre de la loteadora y el correo del dueño.');
    try {
      const creada = await pedir('/api/plataforma/clientes',
        json({ nombre, email, duenio: $('#cliente-duenio').value.trim() }));
      mostrarClave([creada.nombre, email, `Clave provisional: ${creada.clave_provisional}`]);
      for (const campo of ['#cliente-nombre', '#cliente-email', '#cliente-duenio']) $(campo).value = '';
      await cargarLoteadoras();
    } catch (error) { avisar(error.message); }
  });

  $('#clave-nueva-dar').addEventListener('click', async () => {
    const email = $('#clave-nueva-email').value.trim();
    if (!email) return avisar('Escribe el correo de la cuenta.');
    await darClaveNueva(email);
    $('#clave-nueva-email').value = '';
  });

  $('#nuevo').addEventListener('click', () => abrirHabilitar());

  $('#habilitar-listo').addEventListener('click', async () => {
    const cliente = $('#habilitar-cliente').value;
    const nombre = $('#habilitar-nombre').value.trim();
    const cobro = $('#habilitar-cobro').value.trim();
    if (!cliente) return avisar('Elige a qué loteadora va el loteo.');
    if (!nombre) return avisar('Ponle un nombre al loteo.');
    if (!cobro) return avisar('Anota cómo se pagó: es el único registro del cobro.');
    try {
      const creado = await pedir(`/api/plataforma/clientes/${cliente}/proyectos`,
        json({ nombre, nota_cobro: cobro }));
      const duenia = loteadoras.find((c) => String(c.id) === String(cliente))?.nombre;
      $('#habilitar').close();
      await refrescar();
      // Se lleva al loteo recién nacido, que es donde sigue el trabajo (subir el
      // vuelo y el KMZ). Al cambiar de pantalla se borran los avisos, así que el
      // de "listo" se pone después de llegar.
      window.addEventListener('hashchange', () => avisar(
        `${creado.nombre} quedó habilitado${duenia ? ` para ${duenia}` : ''}: ya lo ven en su Mis 360°.`,
        'ok'), { once: true });
      location.hash = `#/planos/${creado.slug}`;
    } catch (error) { avisar(error.message); }
  });
}
