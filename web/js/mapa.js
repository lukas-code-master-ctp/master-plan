/** Plano del loteo sobre imagen satelital, sincronizado con el visor. */
import { romano } from './datos.js';

const TESELAS = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const ATRIBUCION = 'Imágenes © Esri, Maxar, Earthstar Geographics';
const RADIO_CONO_M = 700;
const METROS_POR_GRADO_LAT = 111320;
// El nombre al pasar el cursor, solo con mouse: en pantallas táctiles el toque lo
// dejaba abierto y se acumulaban decenas de rótulos encima del plano.
const CON_CURSOR = window.matchMedia('(hover: hover)');

export class Mapa {
  constructor(elemento, catalogo, { alElegirParcela, alPasarSobreParcela, alElegirVista } = {}) {
    this.catalogo = catalogo;
    this.alElegirParcela = alElegirParcela ?? (() => {});
    this.alPasarSobreParcela = alPasarSobreParcela ?? (() => {});
    this.alElegirVista = alElegirVista ?? (() => {});
    this.formas = new Map();
    this.marcadores = new Map();
    this.seleccionada = null;
    this.estiloParcela = () => ({ color: '#ffffff', atenuada: false });

    // El zoom abajo a la derecha, donde llega el pulgar. Arriba, en el teléfono,
    // flota la leyenda.
    this.mapa = L.map(elemento, { zoomControl: false, attributionControl: true });
    L.control.zoom({ position: 'bottomright', zoomInTitle: 'Acercar', zoomOutTitle: 'Alejar' })
      .addTo(this.mapa);
    L.tileLayer(TESELAS, { maxZoom: 19, attribution: ATRIBUCION }).addTo(this.mapa);

    this._dibujarOtrosPoligonos();
    this._dibujarParcelas();
    this._dibujarPuntosDeVuelo();
    this._crearCono();
    this.encuadrado = this._encuadrar();
  }

  _dibujarOtrosPoligonos() {
    for (const otro of this.catalogo.otrosPoligonos) {
      L.polygon(aLatLng(otro.poligono), {
        color: '#6b6559', weight: 0.8, opacity: 0.5,
        fillColor: '#6b6559', fillOpacity: 0.1, interactive: false,
      }).addTo(this.mapa);
    }
  }

  _dibujarParcelas() {
    for (const parcela of this.catalogo.parcelas) {
      if (!parcela.poligono) continue;
      const forma = L.polygon(aLatLng(parcela.poligono), {
        className: 'parcela-mapa', weight: 1, fillOpacity: 0.28,
      }).addTo(this.mapa);

      if (CON_CURSOR.matches) forma.bindTooltip(this.catalogo.nombre(parcela), ETIQUETA_AL_PASAR);
      forma.on('click', () => this.alElegirParcela(parcela.id));
      forma.on('mouseover', () => this.alPasarSobreParcela(parcela.id));
      forma.on('mouseout', () => this.alPasarSobreParcela(null));
      this.formas.set(parcela.id, forma);
    }
  }

  _dibujarPuntosDeVuelo() {
    const porPosicion = new Map();
    for (const vista of this.catalogo.vistas) {
      if (!porPosicion.has(vista.posicion)) porPosicion.set(vista.posicion, vista);
    }
    for (const [posicion, vista] of porPosicion) {
      const nombre = this.catalogo.nombrePunto(posicion);
      const alturas = this.catalogo.alturasDePunto(posicion);
      // Sin tamaño: la pastilla mide lo que su texto. El disco del romano queda
      // centrado donde estaba el dron al fotografiar (ver .punto-vuelo).
      const marcador = L.marker([vista.lat, vista.lon], {
        icon: L.divIcon({
          className: 'punto-vuelo-ancla',
          html: `<div class="punto-vuelo"><span class="punto-vuelo__disco">${romano(posicion)}</span>`
            + `<span class="punto-vuelo__rotulo">${alturas}</span></div>`,
          iconSize: null,
        }),
        title: `${nombre} · ${alturas}`,
      }).addTo(this.mapa);
      marcador.on('click', () => this.alElegirVista(posicion));
      this.marcadores.set(posicion, marcador);
    }
  }

  _crearCono() {
    this.cono = L.polygon([], {
      color: '#d99a4e', weight: 1, opacity: 0.85,
      fillColor: '#d99a4e', fillOpacity: 0.14, interactive: false,
    }).addTo(this.mapa);
  }

  /**
   * Encuadra el loteo, y avisa si pudo.
   *
   * Leaflet calcula el zoom con el tamaño que tenga el contenedor en ese momento.
   * En móvil el plano nace escondido detrás de la vista aérea: mide 0×0, no hay
   * zoom que pueda contener nada, y el mapa se queda mirando el planeta entero.
   * Por eso devuelve si el encuadre valió, y `refrescar` lo reintenta cuando el
   * contenedor por fin tiene tamaño.
   */
  _encuadrar() {
    const puntos = this.catalogo.parcelas
      .filter((p) => p.centroide)
      .map((p) => [p.centroide[1], p.centroide[0]]);
    const vuelos = this.catalogo.vistas.map((v) => [v.lat, v.lon]);
    const todos = [...puntos, ...vuelos];
    if (todos.length) this.mapa.fitBounds(L.latLngBounds(todos).pad(0.06));
    else this.mapa.setView([-34.793, -72.0], 14);
    return this.mapa.getSize().x > 0;
  }

  aplicarEstilos(estiloParcela) {
    this.estiloParcela = estiloParcela;
    // Con una elegida, las demás se apagan para que se vea sola.
    const hayElegida = this.seleccionada !== null;
    for (const [id, forma] of this.formas) {
      const estilo = estiloParcela(id);
      const seleccionada = id === this.seleccionada;
      const apagada = estilo.atenuada || (hayElegida && !seleccionada);
      forma.setStyle({
        // El seleccionado va en ocre: el blanco ya es el color por defecto.
        color: seleccionada ? '#c07a2c' : estilo.color,
        weight: seleccionada ? 3 : 1,
        fillColor: estilo.color,
        fillOpacity: apagada ? 0.06 : (seleccionada ? 0.6 : 0.28),
        opacity: apagada ? 0.3 : 0.9,
      });
    }
  }

  marcarSeleccionada(id) {
    const anterior = this.formas.get(this.seleccionada);
    if (anterior) this._etiquetar(anterior, this.seleccionada, false);
    this.seleccionada = id;
    const forma = this.formas.get(id);
    if (forma) this._etiquetar(forma, id, true);
    this.mapa.getContainer().classList.toggle('mapa--con-seleccion', Boolean(forma));
    this.aplicarEstilos(this.estiloParcela);
  }

  /** La elegida lleva su nombre fijo y late (.parcela-mapa--elegida); las demás, al pasar. */
  _etiquetar(forma, id, elegida) {
    forma.unbindTooltip();
    const nombre = this.catalogo.nombre(this.catalogo.porId.get(id));
    if (elegida) {
      forma.bindTooltip(nombre, { permanent: true, direction: 'top', className: 'etiqueta-elegida' })
        .openTooltip();
    } else if (CON_CURSOR.matches) {
      forma.bindTooltip(nombre, ETIQUETA_AL_PASAR);
    }
    forma.getElement()?.classList.toggle('parcela-mapa--elegida', elegida);
  }

  marcarVista(vista) {
    for (const [posicion, marcador] of this.marcadores) {
      const nodo = marcador.getElement()?.querySelector('.punto-vuelo');
      nodo?.classList.toggle('punto-vuelo--activo', posicion === vista?.posicion);
    }
  }

  /** Dibuja hacia dónde está mirando el visor. */
  actualizarCono(vista, camara) {
    if (!vista || !camara) {
      this.cono.setLatLngs([]);
      return;
    }
    const apertura = Math.min(camara.aperturaHorizontal(16, 9), 120);
    const vertices = [[vista.lat, vista.lon]];
    for (let i = 0; i <= 12; i++) {
      const azimut = camara.azimut - apertura / 2 + (apertura * i) / 12;
      vertices.push(desplazar(vista.lat, vista.lon, azimut, RADIO_CONO_M));
    }
    this.cono.setLatLngs(vertices);
  }

  enfocarParcela(id) {
    const forma = this.formas.get(id);
    if (forma) this.mapa.fitBounds(forma.getBounds().pad(2.5), { animate: true });
  }

  /** El punto de vuelo que se está mirando, con su cono, sin perder el loteo de vista. */
  enfocarVista(vista) {
    const cono = this.cono.getLatLngs()[0] ?? [];
    const puntos = [[vista.lat, vista.lon], ...cono];
    this.mapa.fitBounds(L.latLngBounds(puntos).pad(0.15), { animate: true, maxZoom: 17 });
  }

  refrescar() {
    this.mapa.invalidateSize();
    // Recalcular el tamaño no rehace el encuadre: el zoom del planeta entero
    // sigue puesto. Se vuelve a encuadrar la primera vez que el contenedor mide
    // algo, y solo esa vez, para no deshacer el zoom que haya hecho la persona.
    if (!this.encuadrado) this.encuadrado = this._encuadrar();
  }
}

const ETIQUETA_AL_PASAR = { direction: 'top', sticky: true };

function aLatLng(anillo) {
  return anillo.map(([lon, lat]) => [lat, lon]);
}

function desplazar(lat, lon, azimut, metros) {
  const radianes = (azimut * Math.PI) / 180;
  const norte = Math.cos(radianes) * metros;
  const este = Math.sin(radianes) * metros;
  const metrosPorGradoLon = METROS_POR_GRADO_LAT * Math.cos((lat * Math.PI) / 180);
  return [lat + norte / METROS_POR_GRADO_LAT, lon + este / metrosPorGradoLon];
}
