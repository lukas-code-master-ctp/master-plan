/**
 * Las fotos de cada referencia (el portón del acceso): en el sitio se abren al tocar
 * su rótulo. Se suben y se quitan al tiro, sin el Guardar del formulario, y se ven
 * en el sitio al reconstruir (`pipeline/construir.py` las achica y las copia).
 */
import { $, avisar, pedir } from './comun.js';

let alCambiar = async () => {};

export function prepararFotosReferencias(opciones) {
  alCambiar = opciones.alCambiar;
  const caja = $('#plano-fotos-referencias');
  // No son datos del formulario: elegir una foto no deja "cambios sin guardar".
  caja.addEventListener('input', (evento) => evento.stopPropagation());
  caja.addEventListener('change', async (evento) => {
    evento.stopPropagation();
    const entrada = evento.target.closest('input[type="file"]');
    if (!entrada?.files.length) return;
    const datos = new FormData();
    datos.append('referencia', entrada.dataset.referencia);
    for (const foto of entrada.files) datos.append('fotos', foto);
    const fila = entrada.closest('.foto-referencia');
    fila.classList.add('foto-referencia--subiendo');
    try {
      await pedir(`/api/proyectos/${caja.dataset.slug}/referencias/fotos`, { method: 'POST', body: datos });
      await alCambiar('Fotos agregadas. Reconstruye para que se vean en el sitio.');
    } catch (error) {
      avisar(error.message);
    } finally {
      entrada.value = '';
      fila.classList.remove('foto-referencia--subiendo');
    }
  });
  caja.addEventListener('click', async (evento) => {
    const quitar = evento.target.closest('[data-quitar-foto]');
    if (!quitar) return;
    if (!confirm('¿Quitar esta foto? Deja de salir en el sitio al reconstruir.')) return;
    try {
      await pedir(`/api/proyectos/${caja.dataset.slug}/referencias/fotos/${quitar.dataset.quitarFoto}`,
        { method: 'DELETE' });
      await alCambiar('Foto quitada. Reconstruye para que se note en el sitio.');
    } catch (error) {
      avisar(error.message);
    }
  });
}

export function pintarFotosReferencias(proyecto) {
  const caja = $('#plano-fotos-referencias');
  const referencias = proyecto.fotos_referencias ?? [];
  caja.dataset.slug = proyecto.slug;
  caja.hidden = !referencias.length;
  const lista = caja.querySelector('.fotos-referencias__lista');
  lista.replaceChildren(...referencias.map((referencia) => fila(proyecto.slug, referencia)));
}

function fila(slug, { referencia, carpeta, fotos }) {
  const nodo = document.createElement('div');
  nodo.className = 'foto-referencia';
  const nombre = document.createElement('b');
  nombre.className = 'foto-referencia__nombre';
  nombre.textContent = referencia;
  const tira = document.createElement('div');
  tira.className = 'foto-referencia__tira';
  for (const archivo of fotos) {
    const caja = document.createElement('figure');
    caja.className = 'foto-referencia__miniatura';
    const imagen = document.createElement('img');
    imagen.src = `/api/proyectos/${slug}/referencias/fotos/${carpeta}/${archivo}`;
    imagen.alt = `${referencia}, foto ${archivo.replace('.jpg', '')}`;
    imagen.loading = 'lazy';
    const quitar = document.createElement('button');
    quitar.type = 'button';
    quitar.className = 'foto-referencia__quitar';
    quitar.dataset.quitarFoto = `${carpeta}/${archivo}`;
    quitar.setAttribute('aria-label', `Quitar ${imagen.alt}`);
    quitar.textContent = '×';
    caja.append(imagen, quitar);
    tira.append(caja);
  }
  const agregar = document.createElement('label');
  agregar.className = 'foto-referencia__agregar';
  const entrada = document.createElement('input');
  entrada.type = 'file';
  entrada.accept = 'image/jpeg,image/png,image/webp';
  entrada.multiple = true;
  entrada.dataset.referencia = referencia;
  entrada.className = 'oculto';
  agregar.append(entrada, fotos.length ? '+ Agregar' : '+ Agregar fotos');
  tira.append(agregar);
  nodo.append(nombre, tira);
  return nodo;
}
