/** Ficha comercial de una parcela. */

const NUMERO = new Intl.NumberFormat('es-CL');

export function formatearSuperficie(metros) {
  if (metros == null) return '—';
  if (metros >= 10000) return `${NUMERO.format(metros)} m² <small>(${(metros / 10000).toFixed(2)} ha)</small>`;
  return `${NUMERO.format(metros)} m²`;
}

export function formatearPrecio(precio, moneda) {
  if (precio == null) return null;
  if (moneda === 'UF') return `UF ${NUMERO.format(precio)}`;
  return `$${NUMERO.format(Math.round(precio))}`;
}

/** El ancho en metros si la planilla lo trae; si no, la superficie de la servidumbre. */
export function formatearServidumbre(parcela) {
  if (parcela.servidumbre_m != null) return `${NUMERO.format(parcela.servidumbre_m)} m`;
  if (parcela.servidumbre_m2 != null) return `${NUMERO.format(Math.round(parcela.servidumbre_m2))} m²`;
  return '—';
}

export function renderizarFicha(contenedor, parcela, catalogo, acciones) {
  const estado = parcela.estado;
  const color = catalogo.color(estado);
  const vendible = catalogo.estados[estado]?.vendible;
  const precio = formatearPrecio(parcela.precio, parcela.moneda);

  contenedor.replaceChildren();
  contenedor.hidden = false;
  contenedor.innerHTML = `
    <div class="ficha__cabecera">
      <div>
        <h2 class="ficha__titulo">${catalogo.titulo(parcela)}</h2>
        <div class="ficha__meta">
          <span class="insignia insignia--${estado}"><i style="background:${color}"></i>${catalogo.etiquetaEstado(estado)}</span>
          ${parcela.etapa != null ? `<span class="ficha__etapa">${catalogo.etapaDe(parcela)}</span>` : ''}
        </div>
      </div>
      <button class="ficha__cerrar" type="button" aria-label="Cerrar ficha">✕</button>
    </div>

    <div class="datos">
      <div class="dato">
        <span class="dato__rotulo">Superficie</span>
        <span class="dato__valor">${formatearSuperficie(parcela.superficie_m2)}</span>
      </div>
      <div class="dato">
        <span class="dato__rotulo">Servidumbre</span>
        <span class="dato__valor">${formatearServidumbre(parcela)}</span>
      </div>
      <div class="dato">
        <span class="dato__rotulo">Precio</span>
        <span class="dato__valor">${precio ?? '<small>A consultar</small>'}</span>
      </div>
    </div>

    <div class="acciones"></div>
    <p class="nota" hidden></p>
  `;

  contenedor.querySelector('.ficha__cerrar').addEventListener('click', acciones.alCerrar);

  const zona = contenedor.querySelector('.acciones');

  if (parcela.mejor_vista) {
    zona.append(boton('Ver desde el aire', 'boton boton--contorno', acciones.alVerDesdeAire));
  }

  if (vendible && parcela.link_pago) {
    const enlace = document.createElement('a');
    enlace.className = 'boton';
    enlace.href = parcela.link_pago;
    enlace.target = '_blank';
    enlace.rel = 'noopener';
    enlace.textContent = precio ? 'Comprar' : 'Reservar';
    zona.append(enlace);
  }

  if (vendible && catalogo.meta.whatsapp) {
    const mensaje = encodeURIComponent(
      `Hola, me interesa la ${catalogo.nombre(parcela).toLowerCase()} de ${catalogo.meta.proyecto}.`);
    const enlace = document.createElement('a');
    enlace.className = 'boton boton--whatsapp';
    enlace.href = `https://wa.me/${catalogo.meta.whatsapp}?text=${mensaje}`;
    enlace.target = '_blank';
    enlace.rel = 'noopener';
    enlace.textContent = 'Consultar por WhatsApp';
    zona.append(enlace);
  }

  zona.append(boton('Copiar enlace', 'boton boton--texto', async (evento) => {
    const url = new URL(location.href);
    url.searchParams.set('lote', parcela.id);
    try {
      await navigator.clipboard.writeText(url.toString());
      evento.currentTarget.textContent = 'Enlace copiado';
      setTimeout(() => { evento.currentTarget.textContent = 'Copiar enlace'; }, 1800);
    } catch {
      mostrarNota(contenedor, url.toString());
    }
  }));

  if (!parcela.poligono) {
    mostrarNota(contenedor,
      'Esta parcela todavía no tiene su polígono cargado, así que no aparece en el plano ' +
      'ni en la vista aérea. Los datos comerciales sí están al día.');
  } else if (!parcela.mejor_vista) {
    mostrarNota(contenedor, 'Esta parcela no queda dentro del encuadre de ninguna de las ' +
      'posiciones de vuelo. Puedes verla en el plano.');
  }
}

function boton(texto, clase, alHacerClic) {
  const elemento = document.createElement('button');
  elemento.type = 'button';
  elemento.className = clase;
  elemento.textContent = texto;
  elemento.addEventListener('click', alHacerClic);
  return elemento;
}

function mostrarNota(contenedor, texto) {
  const nota = contenedor.querySelector('.nota');
  nota.textContent = texto;
  nota.hidden = false;
}
