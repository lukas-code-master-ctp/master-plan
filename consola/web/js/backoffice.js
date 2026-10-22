/**
 * Back-office: lo que solo ve el equipo de Tu Masterplan.
 *
 * Que los botones estén escondidos no protege nada —el servidor contesta 403
 * igual—; es para que una loteadora no vea puertas que no puede abrir.
 */
import { $, $$, abrirDialogo, avisar, estado, json, pedir } from './comun.js';

let loteadoras = [];
let refrescar = async () => {};

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

function filaLoteadora(cliente) {
  const fila = document.createElement('div');
  fila.className = 'padron__fila';
  const texto = document.createElement('div');
  const nombre = document.createElement('strong');
  const detalle = document.createElement('span');
  detalle.className = 'ayuda';
  nombre.textContent = cliente.nombre;
  const loteos = `${cliente.loteos} ${cliente.loteos === 1 ? 'loteo' : 'loteos'}`;
  detalle.textContent = `${loteos} · ${cliente.cuentas.join(', ')}`
    + (cliente.estado === 'activo' ? '' : ' · SUSPENDIDA');
  texto.append(nombre, detalle);
  fila.append(texto);

  // La propia loteadora no se puede suspender —quedaría la app sin operador y
  // nadie por encima para arreglarlo—, así que el servidor lo rechaza. Ofrecer el
  // botón sería prometer algo que siempre falla.
  if (cliente.id === estado.sesion?.cliente_id) {
    const nota = document.createElement('span');
    nota.className = 'ayuda';
    nota.textContent = 'la tuya';
    fila.append(nota);
    return fila;
  }

  const boton = document.createElement('button');
  boton.className = 'boton boton--texto';
  boton.type = 'button';
  boton.textContent = cliente.estado === 'activo' ? 'Suspender' : 'Reactivar';
  boton.addEventListener('click', async () => {
    const nuevo = cliente.estado === 'activo' ? 'suspendido' : 'activo';
    if (nuevo === 'suspendido' && !confirm(
      `Suspender a ${cliente.nombre}\n\nSu gente queda afuera en la petición siguiente.`)) return;
    try {
      await pedir(`/api/plataforma/clientes/${cliente.id}/estado`, json({ estado: nuevo }));
      await cargarLoteadoras();
    } catch (error) { avisar(error.message); }
  });
  fila.append(boton);
  return fila;
}

export function pintarBackOffice() {
  const equipo = estado.sesion?.rol === 'plataforma';
  $('#loteadoras').hidden = !equipo;
  $('#nuevo').hidden = !equipo;
  $('#pestana-contactos').hidden = !equipo;
}

export function prepararBackOffice(opciones) {
  refrescar = opciones.refrescar;

  for (const boton of $$('[data-cerrar]')) {
    boton.addEventListener('click', () => boton.closest('dialog').close());
  }

  $('#loteadoras').addEventListener('click', async () => {
    $('#clientes-clave').hidden = true;
    try { await cargarLoteadoras(); } catch (error) { return avisar(error.message); }
    abrirDialogo($('#clientes'));
  });

  $('#cliente-crear').addEventListener('click', async () => {
    const nombre = $('#cliente-nombre').value.trim();
    const email = $('#cliente-email').value.trim();
    if (!nombre || !email) return avisar('Hacen falta el nombre de la loteadora y el correo del dueño.');
    try {
      const creada = await pedir('/api/plataforma/clientes',
        json({ nombre, email, duenio: $('#cliente-duenio').value.trim() }));
      // La clave no se guarda en claro en ninguna parte: si se pierde acá, se pierde.
      const caja = $('#clientes-clave');
      caja.textContent = `${creada.nombre}\n${email}\nClave provisional: ${creada.clave_provisional}\n\n`
        + 'Cópiala ahora: no se vuelve a mostrar. Pásasela por un canal aparte.';
      caja.hidden = false;
      for (const campo of ['#cliente-nombre', '#cliente-email', '#cliente-duenio']) $(campo).value = '';
      await cargarLoteadoras();
    } catch (error) { avisar(error.message); }
  });

  $('#clave-nueva-dar').addEventListener('click', async () => {
    const email = $('#clave-nueva-email').value.trim();
    if (!email) return avisar('Escribe el correo de la cuenta.');
    if (!confirm(`¿Dar una contraseña nueva a ${email}?\n\nSe cierran sus sesiones abiertas.`)) return;
    try {
      const nueva = await pedir('/api/plataforma/usuarios/clave', json({ email }));
      // La clave no se guarda en claro en ninguna parte: si se pierde acá, se pierde.
      const caja = $('#clientes-clave');
      caja.textContent = `${nueva.email}\nClave provisional: ${nueva.clave_provisional}\n\n`
        + 'Cópiala ahora: no se vuelve a mostrar. Pásasela por un canal aparte.';
      caja.hidden = false;
      $('#clave-nueva-email').value = '';
    } catch (error) { avisar(error.message); }
  });

  $('#nuevo').addEventListener('click', async () => {
    try { await cargarLoteadoras(); } catch (error) { return avisar(error.message); }
    if (!loteadoras.length) return avisar('Primero da de alta una loteadora.');
    $('#habilitar-nombre').value = '';
    $('#habilitar-cobro').value = '';
    abrirDialogo($('#habilitar'));
  });

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
