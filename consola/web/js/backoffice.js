/**
 * Back-office: lo que solo ve el equipo de Tu Masterplan.
 *
 * Que los botones estén escondidos no protege nada —el servidor contesta 403
 * igual—; es para que una loteadora no vea puertas que no puede abrir.
 *
 * Dos pantallas: `#/loteadoras` (arriba, los pedidos por habilitar; abajo, todas
 * las loteadoras con buscador) y `#/loteadoras/<id>`, la ficha de una con sus
 * loteos, su gente y lo último que pasó. Tienen dirección propia para poder
 * volver atrás y mandarle el enlace a alguien del equipo.
 */
import { $, $$, abrirDialogo, avisar, estado, json, pedir, pastilla } from './comun.js';
import { fraseDe } from './actividad.js';

let loteadoras = [];
let fichaAbierta = null;      // el id de la loteadora cuya ficha se ve, o null
let refrescar = async () => {};

const DIA = new Intl.DateTimeFormat('es-CL', { day: 'numeric', month: 'short', year: 'numeric' });
const DIA_CORTO = new Intl.DateTimeFormat('es-CL', { day: 'numeric', month: 'short' });
const ROLES = { 'dueño': 'Dueño', equipo: 'Equipo', plataforma: 'Equipo CTP' };
// Cuántas líneas de "Lo último" se muestran, ya juntadas las repeticiones.
const LINEAS_DE_HISTORIAL = 12;

// --- lo que se puede probar sin página ------------------------------------------------

/** En qué está un loteo, visto desde el cobro: es lo que el back-office decide. */
export function estadoDelLoteo(loteo) {
  if (loteo.publicado) return { texto: loteo.pagado ? 'Publicado · pagado aparte' : 'Publicado', tono: 'ok' };
  if (loteo.pagado) return { texto: 'Pagado aparte', tono: 'ok' };
  if (loteo.habilitado) return { texto: 'Habilitado', tono: 'ok' };
  if (loteo.habilitacion_pedida) {
    return { texto: `Pidió habilitar · ${DIA_CORTO.format(new Date(loteo.habilitacion_pedida))}`, tono: 'aviso' };
  }
  return { texto: 'Sin plan', tono: null };
}

/** El plan de una loteadora en una línea: "Pro · 2 de 3 en línea". */
export function resumenDelPlan(plan, planes = []) {
  const nombre = (clave) => planes.find((p) => p.plan === clave)?.nombre ?? clave;
  const pidio = plan?.pedido && plan.pedido !== plan.plan ? ` · pidió ${nombre(plan.pedido)}` : '';
  if (!plan?.plan) return `Sin plan${pidio}`;
  return `${plan.nombre} · ${plan.en_linea} de ${plan.loteos} en línea${pidio}`;
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

/** ¿La loteadora calza con lo que se busca? Por nombre o por el correo de alguien suyo. */
export function calzaCon(cliente, busqueda) {
  const normal = (texto) => String(texto ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
  const buscado = normal(busqueda).trim();
  if (!buscado) return true;
  return [cliente.nombre, cliente.slug, ...cliente.cuentas].some((t) => normal(t).includes(buscado));
}

/**
 * Junta los eventos seguidos que dicen lo mismo el mismo día: publicar siete veces
 * en una tarde es una línea "· 7 veces", no siete líneas iguales que tapan el resto.
 * Devuelve `{ evento, veces }`, en el mismo orden (el más nuevo primero).
 */
export function juntarRepetidos(eventos) {
  const dia = (iso) => new Date(iso).toDateString();
  const lineas = [];
  for (const evento of eventos) {
    const ultima = lineas.at(-1);
    if (ultima && ultima.evento.que === evento.que && ultima.evento.detalle === evento.detalle
        && ultima.evento.quien?.email === evento.quien?.email && dia(ultima.evento.cuando) === dia(evento.cuando)) {
      ultima.veces += 1;
    } else {
      lineas.push({ evento, veces: 1 });
    }
  }
  return lineas;
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
function mostrarClave(caja, lineas) {
  caja.textContent = `${lineas.join('\n')}\n\nCópiala ahora: no se vuelve a mostrar. Pásasela por un canal aparte.`;
  caja.hidden = false;
  caja.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}

/** La caja de la clave de la pantalla que se está viendo. */
const cajaDeClave = () => (fichaAbierta != null ? $('#ficha-clave') : $('#clientes-clave'));

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
  a.href = `#/planos/${encodeURIComponent(loteo.slug)}`;
  return a;
}

// --- el padrón ------------------------------------------------------------------------

async function cargarLoteadoras() {
  loteadoras = await pedir('/api/plataforma/clientes');
  pintarLista();
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

/** La lista, filtrada por el buscador. Se repinta al escribir, sin pedir nada. */
function pintarLista() {
  const busqueda = $('#loteadoras-buscar').value;
  const vistas = loteadoras.filter((c) => calzaCon(c, busqueda));
  $('#clientes-cuenta').textContent = busqueda.trim() ? `${vistas.length} de ${loteadoras.length}` : loteadoras.length;
  $('#clientes-lista').replaceChildren(...vistas.map(filaLoteadora));
  $('#clientes-vacio').hidden = vistas.length > 0;
}

async function cargarPorHabilitar() {
  const pedidos = await pedir('/api/plataforma/por-habilitar');
  $('#por-habilitar').hidden = !pedidos.length;
  $('#por-habilitar-cuenta').textContent = pedidos.length;
  $('#por-habilitar-lista').replaceChildren(...pedidos.map((loteo) => {
    const fila = nodo('div', 'padron__fila padron__fila--pedido');
    const texto = nodo('div', 'padron__texto');
    const quien = nodo('a', 'padron__de', loteo.cliente);
    quien.href = `#/loteadoras/${loteo.cliente_id}`;
    const detalle = nodo('span', 'ayuda');
    detalle.append(quien, ` · pidió el ${DIA.format(new Date(loteo.habilitacion_pedida))}`);
    const plan = nodo('span', 'ayuda', resumenDelPlan(loteo.plan, estado.sesion?.planes));
    texto.append(enlaceAlLoteo(loteo), detalle, plan);
    // El plan se asigna en la ficha, donde se ve cuántos tiene en línea.
    const asignar = nodo('a', 'boton boton--chico', 'Asignar plan');
    asignar.href = `#/loteadoras/${loteo.cliente_id}`;
    fila.append(texto, asignar);
    return fila;
  }));
}

function filaLoteadora(cliente) {
  const fila = nodo('a', 'padron__fila padron__fila--enlace');
  fila.href = `#/loteadoras/${cliente.id}`;
  const texto = nodo('span', 'padron__texto');
  const titulo = nodo('span', 'padron__nombre');
  titulo.append(nodo('strong', null, cliente.nombre));
  if (cliente.id === estado.sesion?.cliente_id) titulo.append(chip('La tuya'));
  if (cliente.estado !== 'activo') titulo.append(chip('Suspendida', 'apagada'));
  if (cliente.plan?.plan) titulo.append(chip(cliente.plan.nombre));
  if (cliente.por_habilitar) titulo.append(chip(`${cliente.por_habilitar} por habilitar`, 'aviso'));
  texto.append(titulo, nodo('span', 'ayuda', resumenDe(cliente)));
  fila.append(texto, nodo('span', 'padron__flecha', '›'));
  return fila;
}

/** Vuelve a pedir lo de la pantalla que se ve: el padrón o la ficha abierta. */
async function recargar() {
  if (fichaAbierta != null) await Promise.all([dibujarFicha(fichaAbierta), cargarLoteadoras()]);
  else await Promise.all([cargarLoteadoras(), cargarPorHabilitar()]);
}

/** Llega a `#/loteadoras`. Solo pide al llegar: un refresco de fondo no borra lo escrito. */
export async function pintarLoteadoras({ llegando }) {
  fichaAbierta = null;
  if (!llegando) return;
  $('#clientes-clave').hidden = true;
  try {
    await Promise.all([cargarLoteadoras(), cargarPorHabilitar()]);
  } catch (error) { avisar(error.message); }
}

// --- la ficha -------------------------------------------------------------------------

/** Llega a `#/loteadoras/<id>`. */
export async function pintarFicha(id, { llegando }) {
  fichaAbierta = id;
  if (!llegando) return;
  $('#ficha-clave').hidden = true;
  $('#padron-ficha').replaceChildren(nodo('p', 'ayuda', 'Cargando…'));
  try {
    await dibujarFicha(id);
  } catch (error) {
    $('#padron-ficha').replaceChildren(nodo('h1', null, 'No encontramos esa loteadora'),
      nodo('p', 'ayuda', error.message));
  }
}

async function dibujarFicha(clienteId) {
  const ficha = await pedir(`/api/plataforma/clientes/${encodeURIComponent(clienteId)}`);
  // Si mientras llegaba se cambió de pantalla, no se pinta encima de otra.
  if (String(fichaAbierta) !== String(clienteId)) return;
  const propia = ficha.id === estado.sesion?.cliente_id;
  const activa = ficha.estado === 'activo';
  document.title = `${ficha.nombre} — Tu Masterplan`;

  const cabeza = nodo('header', 'pantalla__cabecera');
  const titulo = nodo('div');
  const nombre = nodo('h1', null, ficha.nombre);
  nombre.id = 'ficha-titulo';
  const marcas = nodo('p', 'guia');
  marcas.append(`Desde el ${DIA.format(new Date(ficha.creado_en))}`);
  if (propia) marcas.append(' · ', chip('La tuya'));
  if (!activa) marcas.append(' · ', chip('Suspendida', 'apagada'));
  titulo.append(nodo('span', 'antetitulo', 'Loteadora'), nombre, marcas);
  const acciones = nodo('div', 'pantalla__acciones');
  // La propia loteadora no se puede suspender —quedaría la app sin operador y
  // nadie por encima para arreglarlo—, así que el servidor lo rechaza. Ofrecer el
  // botón sería prometer algo que siempre falla.
  if (!propia) acciones.append(boton(activa ? 'Suspender' : 'Reactivar', () => cambiarEstado(ficha)));
  if (activa) acciones.append(boton('Habilitar un loteo', () => abrirHabilitar(ficha.id), 'boton'));
  cabeza.append(titulo, acciones);

  const cuerpo = nodo('div', 'ficha__cuerpo');
  const principal = nodo('div', 'ficha__principal');
  principal.append(seccionPlan(ficha), seccionLoteos(ficha), seccionCuentas(ficha));
  cuerpo.append(principal, seccionHistorial(ficha));

  $('#padron-ficha').replaceChildren(cabeza, cuerpo);
}

function seccion(titulo, cantidad) {
  const s = nodo('section', 'padron__bloque');
  const h = nodo('h2', null, titulo);
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
  const orden = (l) => (!l.habilitado && l.habilitacion_pedida ? 0 : 1);
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
    // Fuera del plan: un loteo de cortesía o cobrado aparte, que no ocupa cupo.
    if (!loteo.pagado && !loteo.publicado && !loteo.habilitado) fila.append(anotarPago(loteo));
    lista.append(fila);
  }
  s.append(lista);
  return s;
}

/**
 * El plan de la loteadora y dónde cambiarlo. Sin pasarela, CTP cobra afuera y lo
 * anota acá: la nota es el registro del cobro, como al anotar el pago de un loteo.
 */
function seccionPlan(ficha) {
  const s = seccion('Plan');
  const planes = estado.sesion?.planes ?? [];
  const plan = ficha.plan;
  s.append(nodo('p', null, resumenDelPlan(plan, planes)));
  if (plan?.plan) {
    const desde = plan.desde ? `Desde el ${DIA.format(new Date(plan.desde))}` : '';
    const cobro = ficha.nota_plan ? `Cobro: ${ficha.nota_plan}` : '';
    s.append(nodo('p', 'ayuda', [desde, cobro].filter(Boolean).join(' · ')));
  }

  const fila = nodo('div', 'fila fila--envuelve');
  const elegir = nodo('select');
  elegir.setAttribute('aria-label', 'Plan');
  elegir.append(new Option('Sin plan', ''),
    ...planes.map((p) => new Option(p.loteos ? `${p.nombre} · ${p.loteos} en línea` : `${p.nombre} · a la medida`, p.plan)));
  // De entrada, lo que pidió; si no pidió nada, el que tiene.
  elegir.value = plan?.pedido ?? plan?.plan ?? '';
  const cupo = nodo('input');
  Object.assign(cupo, { type: 'number', min: 1, max: 500, placeholder: 'Loteos', value: plan?.loteos ?? '' });
  cupo.setAttribute('aria-label', 'Loteos en línea del plan a la medida');
  const nota = nodo('input');
  Object.assign(nota, { type: 'text', placeholder: 'Cómo se pagó', autocomplete: 'off' });
  nota.setAttribute('aria-label', 'Cómo se pagó el plan');
  const aLaMedida = () => planes.find((p) => p.plan === elegir.value)?.loteos === null;
  const mostrar = () => { cupo.hidden = !aLaMedida(); nota.hidden = !elegir.value; };
  elegir.addEventListener('change', mostrar);
  mostrar();
  const guardar = boton('Guardar plan', async () => {
    const clave = elegir.value;
    if (clave && !nota.value.trim()) return avisar('Anota cómo se pagó el plan: es el único registro del cobro.');
    if (!clave && plan?.plan && !confirm(`¿Dejar a ${ficha.nombre} sin plan?\n\n`
      + 'Sus loteos en línea siguen en línea, pero no se pueden volver a publicar.')) return;
    guardar.disabled = true;
    try {
      await pedir(`/api/plataforma/clientes/${ficha.id}/plan`, json({
        plan: clave || null, nota_cobro: nota.value.trim(), loteos: aLaMedida() ? Number(cupo.value) : null,
      }));
      avisar(clave ? `${ficha.nombre} quedó en el plan ${planes.find((p) => p.plan === clave)?.nombre}.`
        : `${ficha.nombre} quedó sin plan.`, 'ok');
      await recargar();
      refrescar().catch(() => {});
    } catch (error) {
      avisar(error.message);
      guardar.disabled = false;
    }
  }, 'boton');
  fila.append(elegir, cupo, nota, guardar);
  s.append(fila);
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
  email.setAttribute('aria-label', 'Correo de la cuenta nueva');
  const nombre = nodo('input');
  Object.assign(nombre, { type: 'text', placeholder: 'nombre', autocomplete: 'off' });
  nombre.setAttribute('aria-label', 'Nombre de la cuenta nueva');
  const crear = boton('Agregar', async () => {
    const correo = email.value.trim();
    if (!correo) return avisar('Escribe el correo de la cuenta nueva.');
    try {
      const nueva = await pedir(`/api/plataforma/clientes/${ficha.id}/usuarios`,
        json({ email: correo, nombre: nombre.value.trim() }));
      await dibujarFicha(ficha.id);
      mostrarClave($('#ficha-clave'), [ficha.nombre, nueva.email, `Clave provisional: ${nueva.clave_provisional}`]);
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
  s.classList.add('ficha__lado');
  if (!ficha.historial.length) {
    s.append(nodo('p', 'ayuda', 'Sin movimientos todavía.'));
    return s;
  }
  const lista = nodo('ul', 'ficha__historial');
  for (const { evento, veces } of juntarRepetidos(ficha.historial).slice(0, LINEAS_DE_HISTORIAL)) {
    const item = nodo('li');
    const texto = nodo('span', null, fraseDe(evento).texto);
    if (veces > 1) texto.append(' ', nodo('span', 'ficha__veces', `· ${veces} veces`));
    item.append(nodo('span', 'ficha__cuando', DIA_CORTO.format(new Date(evento.cuando))), texto);
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
  if (!confirm(`¿Dar una contraseña nueva a ${email}?\n\nSe cierran sus sesiones abiertas.`)) return false;
  try {
    const nueva = await pedir('/api/plataforma/usuarios/clave', json({ email }));
    mostrarClave(cajaDeClave(), [nueva.email, `Clave provisional: ${nueva.clave_provisional}`]);
    return true;
  } catch (error) {
    avisar(error.message);
    return false;
  }
}

// --- habilitar un loteo ---------------------------------------------------------------

async function abrirHabilitar(clienteId = null) {
  try { await cargarLoteadoras(); } catch (error) { return avisar(error.message); }
  if (!loteadoras.length) return avisar('Primero da de alta una loteadora.');
  if (clienteId != null) $('#habilitar-cliente').value = String(clienteId);
  $('#habilitar-nombre').value = '';
  $('#habilitar-cobro').value = '';
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

  $('#loteadoras-buscar').addEventListener('input', pintarLista);
  $('#loteadoras-habilitar').addEventListener('click', () => abrirHabilitar());

  $('#cliente-crear').addEventListener('click', async () => {
    const nombre = $('#cliente-nombre').value.trim();
    const email = $('#cliente-email').value.trim();
    if (!nombre || !email) return avisar('Hacen falta el nombre de la loteadora y el correo del dueño.');
    try {
      const creada = await pedir('/api/plataforma/clientes',
        json({ nombre, email, duenio: $('#cliente-duenio').value.trim() }));
      mostrarClave($('#clientes-clave'), [creada.nombre, email, `Clave provisional: ${creada.clave_provisional}`]);
      for (const campo of ['#cliente-nombre', '#cliente-email', '#cliente-duenio']) $(campo).value = '';
      await cargarLoteadoras();
    } catch (error) { avisar(error.message); }
  });

  $('#clave-nueva-dar').addEventListener('click', async () => {
    const email = $('#clave-nueva-email').value.trim();
    if (!email) return avisar('Escribe el correo de la cuenta.');
    if (await darClaveNueva(email)) $('#clave-nueva-email').value = '';
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
