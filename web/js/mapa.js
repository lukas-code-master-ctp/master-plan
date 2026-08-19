/** Plano del loteo sobre imagen satelital, sincronizado con el visor. */

const TESELAS = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const ATRIBUCION = 'Imágenes © Esri, Maxar, Earthstar Geographics';
const RADIO_CONO_M = 700;
const METROS_POR_GRADO_LAT = 111320;

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

    this.mapa = L.map(elemento, { zoomControl: true, attributionControl: true });
    L.tileLayer(TESELAS, { maxZoom: 19, attribution: ATRIBUCION }).addTo(this.mapa);

    this._dibujarOtrosPoligonos();
    this._dibujarParcelas();
    this._dibujarPuntosDeVuelo();
    this._crearCono();
    this._encuadrar();
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

      forma.bindTooltip(`Parcela ${parcela.id}`, { direction: 'top', sticky: true });
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
      const marcador = L.marker([vista.lat, vista.lon], {
        icon: L.divIcon({
          className: '',
          html: `<div class="punto-vuelo">${posicion}</div>`,
          iconSize: [26, 26],
          iconAnchor: [13, 13],
        }),
        title: `Posición de vuelo ${posicion}`,
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

  _encuadrar() {
    const puntos = this.catalogo.parcelas
      .filter((p) => p.centroide)
      .map((p) => [p.centroide[1], p.centroide[0]]);
    const vuelos = this.catalogo.vistas.map((v) => [v.lat, v.lon]);
    const todos = [...puntos, ...vuelos];
    if (todos.length) this.mapa.fitBounds(L.latLngBounds(todos).pad(0.06));
    else this.mapa.setView([-34.793, -72.0], 14);
  }

  aplicarEstilos(estiloParcela) {
    this.estiloParcela = estiloParcela;
    for (const [id, forma] of this.formas) {
      const estilo = estiloParcela(id);
      const seleccionada = id === this.seleccionada;
      forma.setStyle({
        // El seleccionado va en ocre: el blanco ya es el color por defecto.
        color: seleccionada ? '#c07a2c' : estilo.color,
        weight: seleccionada ? 3 : 1,
        fillColor: estilo.color,
        fillOpacity: estilo.atenuada ? 0.05 : (seleccionada ? 0.6 : 0.28),
        opacity: estilo.atenuada ? 0.2 : 0.9,
      });
    }
  }

  marcarSeleccionada(id) {
    this.seleccionada = id;
    this.aplicarEstilos(this.estiloParcela);
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

  refrescar() {
    this.mapa.invalidateSize();
  }
}

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
