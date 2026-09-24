/** Orquestador: conecta datos, visor, mapa, ficha y filtros. */
import { Catalogo, ErrorDeDatos, buscar, filtrar } from './datos.js';
import { renderizarFicha } from './ficha.js';
import { Mapa } from './mapa.js';
import { Visor } from './visor.js';

const ROMANOS = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII'];

const $ = (selector) => document.querySelector(selector);

/** Centro del loteo en grados y minutos, para el rótulo de la marca. */
function coordenadasDelLoteo(vistas) {
  if (!vistas.length) return '';
  const media = (valores) => valores.reduce((a, b) => a + b, 0) / valores.length;
  const lat = media(vistas.map((v) => v.lat));
  const lon = media(vistas.map((v) => v.lon));
  const gm = (valor) => {
    const absoluto = Math.abs(valor);
    const grados = Math.floor(absoluto);
    const minutos = Math.round((absoluto - grados) * 60);
    return minutos === 60 ? `${grados + 1}°00′` : `${grados}°${String(minutos).padStart(2, '0')}′`;
  };
  return `${gm(lat)}${lat < 0 ? 'S' : 'N'} · ${gm(lon)}${lon < 0 ? 'O' : 'E'}`;
}

const estado = {
  catalogo: null,
  visor: null,
  mapa: null,
  vista: null,
  seleccionada: null,
  destacada: null,
  visibles: null,
  filtros: { estados: new Set(), supMin: null, supMax: null, soloConVista: false },
};

arrancar().catch(mostrarErrorFatal);

async function arrancar() {
  estado.catalogo = await Catalogo.cargar();
  const catalogo = estado.catalogo;

  $('#marca-nombre').textContent = catalogo.meta.proyecto;
  $('#marca-etapa').textContent = catalogo.meta.etapa ?? '';
  $('#marca-coord').textContent = coordenadasDelLoteo(catalogo.vistas);
  document.title = `${catalogo.meta.proyecto} — Tu Masterplan`;

  estado.visibles = new Set(catalogo.parcelas.map((p) => p.id));

  estado.visor = new Visor($('#visor'), {
    rotuloDe: (id) => catalogo.rotulo(id),
    alElegirParcela: (id) => seleccionar(id),
    alPasarSobreParcela: (id) => destacar(id),
    alMoverCamara: (camara) => {
      $('#brujula-aguja').setAttribute('transform', `rotate(${-camara.azimut} 20 20)`);
      estado.mapa?.actualizarCono(estado.vista, camara);
    },
  });

  estado.mapa = new Mapa($('#mapa'), catalogo, {
    alElegirParcela: (id) => seleccionar(id, { enfocarEnVisor: true }),
    alPasarSobreParcela: (id) => destacar(id),
    alElegirVista: (posicion) => irAPosicion(posicion),
  });

  construirLeyenda();
  construirFiltros();
  construirControles();
  conectarAccionesRapidas();
  conectarBuscador();
  conectarPestanas();
  mostrarPanel('visor');
  refrescarEstilos();

  const inicial = leerUrl();
  await cambiarVista(inicial.vista ?? catalogo.vistaInicial);
  if (inicial.lote) seleccionar(inicial.lote, { enfocarEnVisor: true });

  window.addEventListener('popstate', async () => {
    const destino = leerUrl();
    if (destino.vista && destino.vista.id !== estado.vista?.id) await cambiarVista(destino.vista);
    seleccionar(destino.lote, { silencioso: true });
  });
}

// --- Vistas -------------------------------------------------------------------

async function cambiarVista(vista) {
  if (!vista) return;
  // Cambiar de altura mantiene hacia dónde estabas mirando; cambiar de posición
  // reencuadra, porque la orientación anterior ya no significa nada.
  const reencuadrar = estado.vista?.posicion !== vista.posicion;
  estado.vista = vista;
  const overlay = await estado.catalogo.overlayDe(vista.id);
  await estado.visor.mostrarVista(vista, overlay, {
    avisar: mostrarCarga,
    referencias: estado.catalogo.referenciasDe(vista.id),
  });
  if (reencuadrar) estado.visor.encuadrarParcelas();
  estado.visor.aplicarEstilos(estiloDe);
  estado.visor.marcarSeleccionada(estado.seleccionada);
  estado.mapa.marcarVista(vista);
  actualizarControles();
  sincronizarUrl();
}

function irAPosicion(posicion) {
  const destino = estado.catalogo.vistaCercana(posicion, estado.vista?.altura_m ?? 100);
  if (destino) cambiarVista(destino);
  mostrarPanel('visor');
}

function irAAltura(altura) {
  const destino = estado.catalogo.vistas.find(
    (v) => v.posicion === estado.vista.posicion && v.altura_m === altura);
  if (destino) cambiarVista(destino);
}

// --- Selección ----------------------------------------------------------------

function seleccionar(id, { enfocarEnVisor = false, silencioso = false } = {}) {
  const parcela = id ? estado.catalogo.porId.get(id) : null;
  estado.seleccionada = parcela?.id ?? null;

  estado.visor.marcarSeleccionada(estado.seleccionada);
  estado.mapa.marcarSeleccionada(estado.seleccionada);

  if (!parcela) {
    $('#ficha').hidden = true;
    if (!silencioso) sincronizarUrl();
    estado.mapa.refrescar();
    return;
  }

  renderizarFicha($('#ficha'), parcela, estado.catalogo, {
    alCerrar: () => seleccionar(null),
    alVerDesdeAire: () => verDesdeElAire(parcela),
  });
  estado.mapa.refrescar();

  if (enfocarEnVisor && parcela.mejor_vista) verDesdeElAire(parcela);
  if (!silencioso) sincronizarUrl();
}

async function verDesdeElAire(parcela) {
  if (!parcela.mejor_vista) return;
  mostrarPanel('visor');
  const enLaVistaActual = parcela.vistas?.includes(estado.vista?.id);
  if (!enLaVistaActual) {
    await cambiarVista(estado.catalogo.vistaPorId.get(parcela.mejor_vista));
  }
  estado.visor.enfocarParcela(parcela.id);
  estado.visor.marcarSeleccionada(parcela.id);
}

function destacar(id) {
  estado.destacada = id;
  const forma = estado.mapa.formas.get(id);
  if (forma) forma.openTooltip();
}

// --- Estilos ------------------------------------------------------------------

function estiloDe(id) {
  const parcela = estado.catalogo.porId.get(id);
  return {
    color: estado.catalogo.color(parcela?.estado),
    texto: estado.catalogo.contraste(parcela?.estado),
    atenuada: !estado.visibles.has(id),
  };
}

function refrescarEstilos() {
  estado.visor?.aplicarEstilos(estiloDe);
  estado.mapa?.aplicarEstilos(estiloDe);
}

// --- Controles de vuelo -------------------------------------------------------

function construirControles() {
  const posiciones = estado.catalogo.posiciones();
  $('#controles-posicion').replaceChildren(...posiciones.map(({ posicion }) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.textContent = ROMANOS[posicion] ?? posicion;
    boton.title = `Punto de vuelo ${posicion}`;
    boton.addEventListener('click', () => irAPosicion(posicion));
    boton.dataset.posicion = posicion;
    return boton;
  }));

  // El altímetro se lee de arriba hacia abajo, como un instrumento de vuelo.
  // Las alturas salen del vuelo, no de una lista fija: cada loteo se vuela a las
  // suyas y una lista escrita a mano deja el control muerto en cuanto no calzan.
  const alturas = [...new Set(estado.catalogo.vistas.map((v) => v.altura_m))]
    .sort((a, b) => a - b);
  $('#controles-altura').replaceChildren(...[...alturas].reverse().map((altura) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    boton.title = `${altura} metros de altura`;
    boton.dataset.altura = altura;

    const tic = document.createElement('span');
    tic.className = 'altimetro__tic';
    const valor = document.createElement('span');
    valor.textContent = `${altura}`;

    boton.append(valor, tic);
    boton.addEventListener('click', () => irAAltura(altura));
    return boton;
  }));

  $('#ampliar-mapa').addEventListener('click', (evento) => {
    const amplia = $('#carta').classList.toggle('carta--amplia');
    evento.currentTarget.setAttribute('aria-pressed', String(amplia));
    // Leaflet necesita saber que cambió de tamaño, y la transición dura 420 ms.
    setTimeout(() => estado.mapa?.refrescar(), 460);
  });

  $('#acercar').addEventListener('click', () => estado.visor.acercar(0.78));
  $('#alejar').addEventListener('click', () => estado.visor.acercar(1.28));
}

function conectarAccionesRapidas() {
  $('#accion-plano').addEventListener('click', () => {
    mostrarPanel('mapa');
    if (estado.seleccionada) estado.mapa.enfocarParcela(estado.seleccionada);
  });

  const compartir = $('#accion-compartir');
  compartir.addEventListener('click', async () => {
    const etiqueta = compartir.querySelector('.accion__texto');
    const original = etiqueta.textContent;
    const url = location.href;
    const titulo = `${estado.catalogo.meta.proyecto} — Tu Masterplan`;

    if (navigator.share) {
      try {
        await navigator.share({ title: titulo, url });
        return;
      } catch {
        // El usuario canceló el diálogo del sistema: se copia como respaldo.
      }
    }
    try {
      await navigator.clipboard.writeText(url);
      etiqueta.textContent = 'Copiado';
      setTimeout(() => { etiqueta.textContent = original; }, 1800);
    } catch {
      etiqueta.textContent = 'Copia la barra de direcciones';
      setTimeout(() => { etiqueta.textContent = original; }, 2600);
    }
  });

  const whatsapp = $('#accion-whatsapp');
  if (estado.catalogo.meta.whatsapp) {
    whatsapp.href = enlaceWhatsapp();
  } else {
    whatsapp.hidden = true;
  }
}

function enlaceWhatsapp(parcela) {
  const mensaje = parcela
    ? `Hola, me interesa la ${estado.catalogo.nombre(parcela).toLowerCase()} de ${estado.catalogo.meta.proyecto}.`
    : `Hola, quiero información sobre ${estado.catalogo.meta.proyecto}.`;
  return `https://wa.me/${estado.catalogo.meta.whatsapp}?text=${encodeURIComponent(mensaje)}`;
}

function actualizarControles() {
  const vista = estado.vista;
  for (const boton of $('#controles-posicion').children) {
    boton.setAttribute('aria-pressed', String(Number(boton.dataset.posicion) === vista.posicion));
  }
  const disponibles = new Set(estado.catalogo.vistas
    .filter((v) => v.posicion === vista.posicion)
    .map((v) => v.altura_m));
  for (const boton of $('#controles-altura').children) {
    const altura = Number(boton.dataset.altura);
    boton.disabled = !disponibles.has(altura);
    boton.setAttribute('aria-pressed', String(altura === vista.altura_m));
  }
}

// --- Leyenda y filtros --------------------------------------------------------

// De lo que se vende a lo que no: es el orden en que le importa al comprador.
const ORDEN_ESTADOS = ['disponible', 'reservado', 'vendido', 'no_disponible', 'no_en_venta'];

function porOrdenDeEstado(a, b) {
  return ORDEN_ESTADOS.indexOf(a) - ORDEN_ESTADOS.indexOf(b);
}

function construirLeyenda() {
  const presentes = new Set(estado.catalogo.parcelas.map((p) => p.estado));
  $('#leyenda').replaceChildren(...[...presentes].sort(porOrdenDeEstado).map((clave) => {
    const span = document.createElement('span');
    // El color va solo en el punto: "Disponible" es blanco y como texto no se vería.
    const punto = document.createElement('i');
    punto.style.background = estado.catalogo.color(clave);
    span.append(punto, estado.catalogo.etiquetaEstado(clave));
    return span;
  }));
}

function construirFiltros() {
  const presentes = [...new Set(estado.catalogo.parcelas.map((p) => p.estado))]
    .sort(porOrdenDeEstado);
  $('#filtro-estados').replaceChildren(...presentes.map((clave) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.setAttribute('aria-pressed', 'false');
    const punto = document.createElement('i');
    punto.style.background = estado.catalogo.color(clave);
    chip.append(punto, estado.catalogo.etiquetaEstado(clave));
    chip.addEventListener('click', () => {
      const activo = chip.getAttribute('aria-pressed') === 'true';
      chip.setAttribute('aria-pressed', String(!activo));
      if (activo) estado.filtros.estados.delete(clave);
      else estado.filtros.estados.add(clave);
      aplicarFiltros();
    });
    return chip;
  }));

  $('#sup-min').addEventListener('input', leerRangos);
  $('#sup-max').addEventListener('input', leerRangos);
  $('#solo-con-vista').addEventListener('change', (evento) => {
    estado.filtros.soloConVista = evento.target.checked;
    aplicarFiltros();
  });

  $('#abrir-filtros').addEventListener('click', () => {
    const panel = $('#filtros');
    panel.hidden = !panel.hidden;
    $('#abrir-filtros').setAttribute('aria-expanded', String(!panel.hidden));
  });

  $('#limpiar-filtros').addEventListener('click', () => {
    estado.filtros = { estados: new Set(), supMin: null, supMax: null, soloConVista: false };
    for (const chip of $('#filtro-estados').children) chip.setAttribute('aria-pressed', 'false');
    $('#sup-min').value = '';
    $('#sup-max').value = '';
    $('#solo-con-vista').checked = false;
    aplicarFiltros();
  });
}

function leerRangos() {
  const numero = (valor) => (valor === '' ? null : Number(valor));
  estado.filtros.supMin = numero($('#sup-min').value);
  estado.filtros.supMax = numero($('#sup-max').value);
  aplicarFiltros();
}

function aplicarFiltros() {
  estado.visibles = filtrar(estado.catalogo.parcelas, estado.filtros);
  refrescarEstilos();

  const total = estado.catalogo.parcelas.length;
  $('#conteo-filtros').textContent = `${estado.visibles.size} de ${total} parcelas`;

  const activos = estado.filtros.estados.size
    + (estado.filtros.supMin != null ? 1 : 0)
    + (estado.filtros.supMax != null ? 1 : 0)
    + (estado.filtros.soloConVista ? 1 : 0);
  const pastilla = $('#filtros-activos');
  pastilla.textContent = activos;
  pastilla.hidden = activos === 0;
}

// --- Buscador -----------------------------------------------------------------

function conectarBuscador() {
  const entrada = $('#buscador');
  const lista = $('#sugerencias');
  let resaltada = -1;

  const cerrar = () => { lista.hidden = true; resaltada = -1; };

  const pintar = (resultados) => {
    lista.replaceChildren(...resultados.map((parcela, indice) => {
      const item = document.createElement('li');
      item.role = 'option';
      item.setAttribute('aria-selected', String(indice === resaltada));
      const punto = document.createElement('i');
      punto.style.background = estado.catalogo.color(parcela.estado);
      const medida = document.createElement('small');
      medida.textContent = parcela.superficie_m2 ? `${parcela.superficie_m2} m²` : '';
      item.append(punto, estado.catalogo.nombre(parcela), medida);
      item.addEventListener('mousedown', (evento) => {
        evento.preventDefault();
        elegir(parcela.id);
      });
      return item;
    }));
    lista.hidden = resultados.length === 0;
  };

  const elegir = (id) => {
    entrada.value = '';
    cerrar();
    seleccionar(id, { enfocarEnVisor: true });
  };

  entrada.addEventListener('input', () => {
    resaltada = -1;
    pintar(buscar(estado.catalogo.parcelas, entrada.value));
  });

  entrada.addEventListener('keydown', (evento) => {
    const items = [...lista.children];
    if (evento.key === 'Escape') return cerrar();
    if (!items.length) return;
    if (evento.key === 'ArrowDown' || evento.key === 'ArrowUp') {
      evento.preventDefault();
      resaltada = (resaltada + (evento.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      items.forEach((item, indice) => item.setAttribute('aria-selected', String(indice === resaltada)));
    } else if (evento.key === 'Enter') {
      evento.preventDefault();
      const resultados = buscar(estado.catalogo.parcelas, entrada.value);
      const elegida = resultados[resaltada >= 0 ? resaltada : 0];
      if (elegida) elegir(elegida.id);
    }
  });

  entrada.addEventListener('blur', () => setTimeout(cerrar, 120));
}

// --- Pestañas (móvil) ---------------------------------------------------------

function conectarPestanas() {
  for (const pestana of document.querySelectorAll('.pestana')) {
    pestana.addEventListener('click', () => mostrarPanel(pestana.dataset.panel));
  }
  const pista = $('#pista');
  $('#visor').addEventListener('pointerdown', () => pista.classList.add('pista--oculta'),
                               { once: true });
}

function mostrarPanel(nombre) {
  // En escritorio conviven los dos; en móvil el atributo del body decide cuál se ve.
  document.body.dataset.panel = nombre;
  for (const pestana of document.querySelectorAll('.pestana')) {
    const activa = pestana.dataset.panel === nombre;
    pestana.classList.toggle('pestana--activa', activa);
    pestana.setAttribute('aria-selected', String(activa));
  }
  if (nombre === 'mapa') estado.mapa?.refrescar();
  else estado.visor?.redimensionar();
}

// --- URL ----------------------------------------------------------------------

function leerUrl() {
  const parametros = new URLSearchParams(location.search);
  const lote = parametros.get('lote')?.toUpperCase() ?? null;
  const vista = estado.catalogo.vistaPorId.get(parametros.get('vista')) ?? null;
  return { lote: estado.catalogo.porId.has(lote) ? lote : null, vista };
}

function sincronizarUrl() {
  const url = new URL(location.href);
  if (estado.seleccionada) url.searchParams.set('lote', estado.seleccionada);
  else url.searchParams.delete('lote');
  if (estado.vista) url.searchParams.set('vista', estado.vista.id);
  try {
    history.replaceState(null, '', url);
  } catch {
    // Algunos contextos (un iframe con srcdoc, una extensión) no permiten
    // reescribir la URL. Es una comodidad, no vale romper la aplicación por eso.
  }
}

// --- Estados de carga y error -------------------------------------------------

function mostrarCarga(texto) {
  const caja = $('#cargando');
  caja.hidden = texto == null;
  if (texto) $('#cargando-texto').textContent = texto;
}

function mostrarErrorFatal(error) {
  console.error(error);
  mostrarCarga(null);
  const caja = $('#error-carga');
  caja.hidden = false;
  caja.innerHTML = error instanceof ErrorDeDatos
    ? `<p><strong>No pude cargar los datos del proyecto.</strong></p>
       <p>Esto pasa si abriste <code>index.html</code> con doble clic: el navegador
          bloquea la lectura de archivos locales.</p>
       <p>Levanta un servidor desde la carpeta <code>web/</code>:</p>
       <code>python -m http.server 8000</code>
       <p>y entra a <code>http://localhost:8000</code></p>`
    : `<p><strong>Algo falló al iniciar el visor.</strong></p><code>${error.message}</code>`;
}
