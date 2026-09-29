/** El avatar de la barra: quién entró, cambiar la contraseña y salir. */
import { $, abrirDialogo, avisar, estado, iniciales, json, pedir } from './comun.js';

export function prepararCuenta() {
  const boton = $('#avatar');
  const menu = $('#menu-cuenta');

  const cerrar = () => { menu.hidden = true; boton.setAttribute('aria-expanded', 'false'); };
  boton.addEventListener('click', () => {
    const abrir = menu.hidden;
    menu.hidden = !abrir;
    boton.setAttribute('aria-expanded', String(abrir));
    if (abrir) menu.querySelector('[role="menuitem"]:not([hidden])')?.focus();
  });
  document.addEventListener('click', (evento) => {
    if (!evento.target.closest('.cuenta')) cerrar();
  });
  menu.addEventListener('keydown', (evento) => {
    if (evento.key === 'Escape') { cerrar(); boton.focus(); }
  });
  // Elegir algo del menú lo cierra: lo que sigue es un diálogo o salir.
  menu.addEventListener('click', (evento) => {
    if (evento.target.closest('[role="menuitem"]')) cerrar();
  });

  $('#abrir-clave').addEventListener('click', () => {
    $('#clave-actual').value = '';
    $('#clave-nueva').value = '';
    abrirDialogo($('#clave'));
  });
  $('#clave-listo').addEventListener('click', cambiarClave);
}

export function pintarCuenta() {
  const { sesion } = estado;
  const equipo = sesion.rol === 'plataforma';
  $('#avatar').textContent = iniciales(sesion.quien);
  $('#quien').textContent = sesion.quien;
  // Quién eres acá. Sin esto no se distingue la app del equipo —que ve y opera
  // todas las loteadoras— de la de un cliente, que ve lo mismo con menos botones.
  $('#rol').textContent = equipo ? `Operación · ${sesion.cliente}` : sesion.cliente;
  $('#avatar').classList.toggle('avatar--equipo', equipo);
}

/** Se dice después de pintar la primera pantalla, que limpia los avisos al llegar. */
export function recordarClaveProvisional() {
  if (estado.sesion.debe_cambiar_clave) {
    avisar('Estás usando la contraseña provisional. Cámbiala desde tu cuenta, arriba a la derecha.');
  }
}

async function cambiarClave() {
  const actual = $('#clave-actual').value;
  const nueva = $('#clave-nueva').value;
  if (nueva.length < 10) return avisar('La contraseña nueva tiene que tener al menos 10 caracteres.');
  try {
    await pedir('/api/clave', json({ actual, nueva }));
    // El servidor cortó todas las sesiones, esta también: se vuelve a entrar.
    location.href = '/entrar';
  } catch (error) {
    avisar(error.message);
  }
}
