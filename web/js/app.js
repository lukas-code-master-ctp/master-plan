/** Orquestador: conecta datos, visor, mapa, ficha y filtros. */
import { rumboCardinal, rumboCorto } from './camara.js';
import { Catalogo, ErrorDeDatos, buscar, conteoPorEstado, filtrar, romano } from './datos.js';
import { aplicarMarca, ponerLogo } from './marca.js';
import { mensajeWhatsapp, renderizarFicha } from './ficha.js';
import { agruparParcelas, resumenDeGrupo } from './grupos.js';
import { abrirFormulario } from './reserva.js';
import { estaInsertado, pistaDelVisor } from './insertado.js';
import { Mapa } from './mapa.js';
import {
  construirPerspectivas, marcarPerspectiva, pintarMiniPlano, pintarMiniatura,
} from './perspectivas.js';
import { Visor } from './visor.js';

const $ = (selector) => document.querySelector(selector);

// Cuánto del alto del cuadro se corre la parcela elegida hacia arriba cuando la
// ficha del teléfono tapa la parte de abajo.
const SUBIDA_CON_FICHA = 0.2;
// Cuánto esperar, con la primera vista ya en pantalla, antes de dejar bajando las
// demás: la foto en alta de la vista que se mira va primero.
const PRECARGA_MS = 2500;

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
  /** Hacia dónde mira la vista aérea: lo que muestra la miniatura de Entrar a 360°. */
  camara: null,
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
  // Con marca propia el sitio es de la loteadora: ni la brújula ni el nombre
  // de Tu Masterplan en la pestaña.
  const { diseno } = catalogo;
  aplicarMarca(document.documentElement, diseno);
  if (diseno?.logo) ponerLogo($('.marca__hito'), `datos/${diseno.logo}`, catalogo.meta.proyecto);
  document.title = diseno ? catalogo.meta.proyecto : `${catalogo.meta.proyecto} — Tu Masterplan`;

  estado.visibles = new Set(catalogo.parcelas.map((p) => p.id));

  estado.visor = new Visor($('#visor'), {
    rotuloDe: (id) => catalogo.rotulo(id),
    alElegirParcela: (id) => seleccionar(id),
    alPasarSobreParcela: (id) => destacar(id),
    alMoverCamara: (camara) => {
      // Gira en torno al centro de la rosa (su viewBox es de 100 × 100).
      $('#brujula-aguja').setAttribute('transform', `rotate(${-camara.azimut} 50 50)`);
      estado.camara = camara;
      $('#capsula-aguja').setAttribute('transform', `rotate(${camara.azimut} 10 10)`);
      // En el teléfono la brújula es un botón redondo: cabe "SO", no "Suroeste 211°".
      $('#capsula-texto').textContent = rumboCorto(camara.azimut);
      $('.capsula-rumbo').title = `${rumboCardinal(camara.azimut)} ${Math.round(camara.azimut)}°`;
      estado.mapa?.actualizarCono(estado.vista, camara);
    },
  });

  estado.mapa = new Mapa($('#mapa'), catalogo, {
    alElegirParcela: (id) => seleccionar(id, { enfocarEnVisor: true }),
    alPasarSobreParcela: (id) => destacar(id),
    alElegirVista: (posicion) => irAPosicion(posicion),
  });

  // De lejos, los grupos de parcelas vecinas cuyos números no caben se muestran
  // como una burbuja con su rango y sus disponibles (grupos.js).
  const grupos = agruparParcelas(catalogo.parcelas);
  const resumenDe = (grupo) => resumenDeGrupo(grupo, {
    parcela: (id) => catalogo.porId.get(id),
    esDisponible: (parcela) => Boolean(catalogo.estados[parcela.estado]?.vendible) && !parcela.apartada,
    visible: (id) => estado.visibles.has(id),
  });
  estado.visor.ponerGrupos(grupos, resumenDe);
  estado.mapa.ponerGrupos(grupos, resumenDe);

  construirLeyenda();
  construirFiltros();
  construirControles();
  construirPerspectivas($('#perspectivas-fila'), $('#perspectivas-conteo'), catalogo, irAPosicion);
  pintarMiniPlano($('#ver-plano-miniatura'), catalogo);
  conectarAccionesRapidas();
  conectarBuscador();
  conectarPaneles();
  mostrarPanel('visor');
  refrescarEstilos();

  const inicial = leerUrl();
  await cambiarVista(inicial.vista ?? catalogo.vistaInicial);
  if (inicial.lote) seleccionar(inicial.lote, { enfocarEnVisor: true });
  precargarVistas();

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
  const mostrada = await estado.visor.mostrarVista(vista, overlay, {
    avisar: mostrarCarga,
    referencias: estado.catalogo.referenciasDe(vista.id),
  });
  // Mientras cargaba eligieron otra vista: esa se encarga del resto.
  if (!mostrada) return;
  if (reencuadrar) estado.visor.encuadrarParcelas();
  estado.visor.aplicarEstilos(estiloDe);
  estado.visor.marcarSeleccionada(estado.seleccionada);
  estado.mapa.marcarVista(vista);
  marcarPerspectiva($('#perspectivas-fila'), vista.posicion);
  $('#entrar-360-punto').textContent = `${estado.catalogo.nombrePunto(vista.posicion)} · ${vista.altura_m} m`;
  actualizarControles();
  sincronizarUrl();
}

/**
 * Con la primera vista ya en pantalla, se dejan bajando las parcelas y la foto
 * liviana de las demás: así cambiar de punto es casi inmediato. Se espera un rato
 * para no competir con la foto en alta de la vista que se está mirando, y no se
 * hace si el teléfono pide ahorrar datos.
 */
function precargarVistas() {
  if (navigator.connection?.saveData) return;
  setTimeout(async () => {
    for (const vista of estado.catalogo.vistas) {
      if (vista.id === estado.vista?.id) continue;
      try {
        await estado.catalogo.overlayDe(vista.id);
        await precargarImagen(vista.imagenes?.previa);
      } catch {
        // Si una no baja, se carga al elegirla, como antes.
      }
    }
  }, PRECARGA_MS);
}

function precargarImagen(ruta) {
  if (!ruta) return Promise.resolve();
  return new Promise((listo) => {
    const imagen = new Image();
    imagen.onload = imagen.onerror = () => listo();
    imagen.src = ruta;
  });
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
    alReservar: (elegida) => abrirFormulario($('#reserva'), {
      catalogo: estado.catalogo,
      parcela: elegida,
      // Apartada: al pago. Sin link, el formulario ya le dijo que la contactarán.
      alTerminar: (link) => { if (link) location.assign(link); },
    }),
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
  // En el teléfono la ficha ocupa la mitad de abajo: la parcela se ve arriba.
  const fichaAbierta = !ESCRITORIO.matches && !$('#ficha').hidden;
  estado.visor.enfocarParcela(parcela.id, { subir: fichaAbierta ? SUBIDA_CON_FICHA : 0 });
  estado.visor.marcarSeleccionada(parcela.id);
}

function destacar(id) {
  // El nombre que se abrió al pasar sobre la vista aérea se cierra al salir: si
  // no, quedaban decenas abiertos en el plano. El de la elegida es fijo y se queda.
  const anterior = estado.mapa.formas.get(estado.destacada);
  if (anterior && estado.destacada !== estado.seleccionada) anterior.closeTooltip();
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
    // Cuando no caben todos los números, primero los de lo que se vende.
    prioridad: estado.catalogo.estados[parcela?.estado]?.vendible ? 1 : 0,
  };
}

function refrescarEstilos() {
  estado.visor?.aplicarEstilos(estiloDe);
  estado.mapa?.aplicarEstilos(estiloDe);
}

// --- Controles de vuelo -------------------------------------------------------

/**
 * En escritorio, una píldora con el color de la marca se desliza hasta el punto de
 * vuelo elegido, como la isla de secciones de la consola. Se mide sobre el botón
 * mismo; la primera vez aparece donde va, sin viajar.
 */
let pildoraUbicada = false;
function ubicarPildora({ animar = pildoraUbicada } = {}) {
  const puntos = $('.puntos');
  const activo = $('#controles-posicion [aria-pressed="true"]');
  if (!activo || !activo.offsetWidth) return;
  const pildora = $('.puntos__pildora');
  pildora.classList.toggle('puntos__pildora--quieta', !animar);
  // El botón se mide contra la isla, que es donde vive la píldora.
  const x = activo.getBoundingClientRect().left - puntos.getBoundingClientRect().left - puntos.clientLeft;
  puntos.style.setProperty('--pildora-x', `${x}px`);
  puntos.style.setProperty('--pildora-ancho', `${activo.offsetWidth}px`);
  pildoraUbicada = true;
}
addEventListener('resize', () => ubicarPildora({ animar: false }));
document.fonts?.ready.then(() => ubicarPildora({ animar: false }));

/** Despliega o pliega los puntos de vuelo (solo cambia algo en el teléfono). */
function desplegarPuntos(abierto) {
  $('.puntos').classList.toggle('puntos--abierto', abierto);
  $('#controles-posicion').setAttribute('aria-expanded', String(abierto));
}

function construirControles() {
  const posiciones = estado.catalogo.posiciones();
  $('#controles-posicion').replaceChildren(...posiciones.map(({ posicion }) => {
    const boton = document.createElement('button');
    boton.type = 'button';
    // "Punto II" en una línea y la altura debajo; en escritorio, solo el romano.
    const nombre = document.createElement('span');
    const palabra = document.createElement('span');
    palabra.className = 'puntos__palabra';
    palabra.textContent = 'Punto ';
    nombre.append(palabra, romano(posicion));
    const altura = document.createElement('small');
    altura.className = 'puntos__altura';
    altura.textContent = estado.catalogo.alturasDePunto(posicion);
    boton.append(nombre, altura);
    boton.title = `${estado.catalogo.nombrePunto(posicion)} · ${estado.catalogo.alturasDePunto(posicion)}`;
    boton.addEventListener('click', () => {
      // En el teléfono los puntos van plegados en una pastilla con el actual: el
      // primer toque los despliega y el segundo elige.
      if (!ESCRITORIO.matches && !$('.puntos').classList.contains('puntos--abierto')) {
        desplegarPuntos(true);
        return;
      }
      desplegarPuntos(false);
      irAPosicion(posicion);
    });
    boton.dataset.posicion = posicion;
    return boton;
  }));
  document.addEventListener('pointerdown', (evento) => {
    if (!evento.target.closest('.puntos')) desplegarPuntos(false);
  });

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

  $('#abrir-plano').addEventListener('click', () => ponerPlano('mini', { alTerminar: enfocarEnElPlano }));
  $('#ampliar-mapa').addEventListener('click', () => {
    ponerPlano(document.body.dataset.plano === 'completo' ? 'mini' : 'completo',
               { alTerminar: enfocarEnElPlano });
  });
  $('#cerrar-plano').addEventListener('click', () => {
    ponerPlano('cerrado');
    $('#abrir-plano').focus();
  });
  document.addEventListener('keydown', (evento) => {
    if (evento.key === 'Escape' && document.body.dataset.plano === 'completo') ponerPlano('mini');
  });

  $('#acercar').addEventListener('click', () => estado.visor.acercar(0.78));
  $('#alejar').addEventListener('click', () => estado.visor.acercar(1.28));
}

function conectarAccionesRapidas() {
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

  // El de la barra (escritorio) y el de la cabecera (teléfono) llevan al mismo chat.
  for (const whatsapp of [$('#accion-whatsapp'), $('#cabecera-whatsapp')]) {
    if (estado.catalogo.meta.whatsapp) {
      whatsapp.href = enlaceWhatsapp();
      whatsapp.hidden = false;
    } else {
      whatsapp.hidden = true;
    }
  }
}

/** El WhatsApp general del loteo (cabecera y barra), con el enlace al sitio sin parcela. */
function enlaceWhatsapp() {
  const url = new URL(location.href);
  url.searchParams.delete('lote');
  const mensaje = mensajeWhatsapp(estado.catalogo, null, url.toString());
  return `https://wa.me/${estado.catalogo.meta.whatsapp}?text=${encodeURIComponent(mensaje)}`;
}

function actualizarControles() {
  const vista = estado.vista;
  for (const boton of $('#controles-posicion').children) {
    boton.setAttribute('aria-pressed', String(Number(boton.dataset.posicion) === vista.posicion));
  }
  ubicarPildora();
  const disponibles = new Set(estado.catalogo.vistas
    .filter((v) => v.posicion === vista.posicion)
    .map((v) => v.altura_m));
  for (const boton of $('#controles-altura').children) {
    const altura = Number(boton.dataset.altura);
    boton.disabled = !disponibles.has(altura);
    boton.setAttribute('aria-pressed', String(altura === vista.altura_m));
  }
  // Con una sola altura no hay nada que elegir: el altímetro solo ocupaba lugar.
  $('.altimetro').hidden = disponibles.size < 2;
}

// --- Leyenda y filtros --------------------------------------------------------

// De lo que se vende a lo que no: es el orden en que le importa al comprador.
const ORDEN_ESTADOS = ['disponible', 'reservado', 'vendido', 'no_disponible', 'no_en_venta'];

function porOrdenDeEstado(a, b) {
  return ORDEN_ESTADOS.indexOf(a) - ORDEN_ESTADOS.indexOf(b);
}

function construirLeyenda() {
  const conteo = conteoPorEstado(estado.catalogo.parcelas);
  $('#leyenda').replaceChildren(...[...conteo.keys()].sort(porOrdenDeEstado).map((clave) => {
    const span = document.createElement('span');
    // El color va solo en el punto: "Disponible" es blanco y como texto no se vería.
    const punto = document.createElement('i');
    punto.style.background = estado.catalogo.color(clave);
    span.append(punto, `${estado.catalogo.etiquetaEstado(clave)} (${conteo.get(clave)})`);
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

  // En el teléfono el buscador vive plegado tras la lupa y se abre sobre la cabecera.
  const lupa = $('#abrir-buscador');
  const plegar = () => {
    document.body.classList.remove('buscando');
    lupa.setAttribute('aria-expanded', 'false');
  };
  lupa.addEventListener('click', () => {
    document.body.classList.add('buscando');
    lupa.setAttribute('aria-expanded', 'true');
    entrada.focus();
  });

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
    plegar();
    seleccionar(id, { enfocarEnVisor: true });
  };

  entrada.addEventListener('input', () => {
    resaltada = -1;
    pintar(buscar(estado.catalogo.parcelas, entrada.value));
  });

  entrada.addEventListener('keydown', (evento) => {
    const items = [...lista.children];
    if (evento.key === 'Escape') {
      cerrar();
      plegar();
      return;
    }
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

  entrada.addEventListener('blur', () => setTimeout(() => {
    cerrar();
    plegar();
  }, 120));
}

// --- Paneles (móvil) ----------------------------------------------------------

function conectarPaneles() {
  $('#ver-plano').addEventListener('click', () => {
    mostrarPanel('mapa');
    enfocarEnElPlano();
  });
  $('#entrar-360').addEventListener('click', () => {
    // En escritorio el plano a pantalla completa tapa la vista aérea: se vuelve al minimapa.
    if (document.body.dataset.plano === 'completo') ponerPlano('mini');
    mostrarPanel('visor');
  });
  const pista = $('#pista');
  const insertado = estaInsertado();
  document.documentElement.classList.toggle('insertado', insertado);
  const plataforma = navigator.userAgentData?.platform ?? navigator.platform ?? '';
  pista.textContent = pistaDelVisor(insertado, /mac|iphone|ipad/i.test(plataforma));
  $('#visor').addEventListener('pointerdown', () => pista.classList.add('pista--oculta'),
                               { once: true });
}

// El mismo corte que estilos.css: debajo, plano y vista aérea son pestañas.
const ESCRITORIO = window.matchMedia('(min-width: 62.0625rem)');

/**
 * El plano en escritorio: 'cerrado' (solo el botón flotante), 'mini' (en la
 * esquina) o 'completo' (bajo la cabecera). Lo decide body[data-plano] en
 * estilos.css; en el teléfono el plano es otra pestaña y esto no se ve.
 */
function ponerPlano(modo, { alTerminar } = {}) {
  document.body.dataset.plano = modo;
  const completo = modo === 'completo';
  const ampliar = $('#ampliar-mapa');
  ampliar.setAttribute('aria-pressed', String(completo));
  ampliar.querySelector('.visually-hidden').textContent =
    completo ? 'Volver al minimapa' : 'Plano a pantalla completa';
  if (modo === 'cerrado') return;
  // El botón para volver a la vista aérea muestra dónde se estaba mirando.
  if (completo) pintarMiniatura($('#entrar-360-miniatura'), estado.vista, estado.camara);
  // Leaflet mide su contenedor: hay que esperar a que el cambio de tamaño se pinte.
  requestAnimationFrame(() => requestAnimationFrame(() => {
    estado.mapa?.refrescar();
    alTerminar?.();
  }));
}

/** En el plano, lo que se está mirando: la parcela elegida o el punto de vuelo. */
function enfocarEnElPlano() {
  if (estado.seleccionada) estado.mapa.enfocarParcela(estado.seleccionada);
  else if (estado.vista) estado.mapa.enfocarVista(estado.vista);
}

function mostrarPanel(nombre) {
  // En escritorio conviven los dos; en móvil el atributo del body decide cuál se ve.
  document.body.dataset.panel = nombre;
  if (nombre === 'mapa') {
    estado.mapa?.refrescar();
    // La miniatura se recorta al entrar al plano, no a cada cuadro: mientras el
    // plano está a la vista, la cámara no se mueve.
    pintarMiniatura($('#entrar-360-miniatura'), estado.vista, estado.camara);
  } else {
    estado.visor?.redimensionar();
  }
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
