/**
 * El inventario de un master: qué planilla manda, bajar la plantilla y subir una
 * nueva.
 *
 * La plantilla sale prellenada con las parcelas del KMZ en cuanto el loteo está
 * construido: el error más común era escribir el lote distinto del dibujo, y ese
 * lote quedaba "no disponible" sin que nadie supiera por qué.
 */
import { $, avisar } from './comun.js';
import { subir } from './subida.js';

/** Con qué nombre se guarda: el pipeline le da prioridad a este sobre cualquier otro. */
export const comoInventario = ({ archivo }) => ({
  archivo, ruta: /\.csv$/i.test(archivo.name) ? 'inventario.csv' : 'inventario.xlsx' });

let slugActual = null;

/** `alSubir(slug)` se llama con el inventario ya en el servidor. */
export function prepararInventario({ alSubir }) {
  const boton = $('#inventario-subir');
  boton.addEventListener('click', () => $('#inventario-archivo').click());
  $('#inventario-archivo').addEventListener('change', async (evento) => {
    const [archivo] = evento.target.files;
    evento.target.value = '';
    if (!archivo || !slugActual) return;
    const slug = slugActual;
    boton.disabled = true;
    boton.textContent = 'Subiendo…';
    const listo = () => { boton.textContent = 'Subir inventario'; boton.disabled = false; };
    try {
      avisar(null);
      await subir(slug, [comoInventario({ archivo })]);
      // Antes de actualizar: al repintar, la construcción que se lance lo apaga.
      listo();
      await alSubir(slug);
    } catch (error) {
      listo();
      avisar(error.message);
    }
  });
}

export function pintarInventario(proyecto) {
  slugActual = proyecto.slug;
  const seccion = $('#plano-inventario');
  // Sin KMZ no hay parcelas a las que ponerles precio todavía.
  seccion.hidden = !proyecto.fuentes_encontradas.kmz;
  if (seccion.hidden) return;

  const { planilla } = proyecto.fuentes_encontradas;
  const total = proyecto.construido ? proyecto.resumen.parcelas : 0;
  const disponibles = total ? ` ${proyecto.resumen.disponibles} de ${total} parcelas disponibles.` : '';
  // El orden es el del pipeline: la planilla subida, después el export del CRM.
  if (planilla) {
    $('#inventario-estado').textContent = `Estados y precios de ${planilla}.${disponibles}`;
  } else if (proyecto.con_crm) {
    $('#inventario-estado').textContent = `Estados y precios del export del CRM.${disponibles}`
      + ' Si subes una planilla, manda la planilla.';
  } else {
    $('#inventario-estado').textContent = 'Sin inventario: todas las parcelas se ven como no disponibles.';
  }

  const plantilla = $('#inventario-plantilla');
  plantilla.href = `/api/proyectos/${proyecto.slug}/plantilla`;
  plantilla.textContent = total ? `Descargar plantilla con tus ${total} parcelas` : 'Descargar plantilla';
  // Mientras construye, un inventario nuevo llegaría a medias a esa construcción.
  $('#inventario-subir').disabled = Boolean(proyecto.trabajo);
  // Lo vuelve a esconder cierra.js si el loteo está conectado con Cierra.
  $('#inventario-subir').hidden = false;
}
