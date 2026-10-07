/**
 * Crea tu KMZ: el mapa satelital donde se ubica el plano.
 *
 * Es el mismo Leaflet y las mismas teselas de Esri que usa el visor publicado
 * (`web/js/mapa.js`). Leaflet se pide recién al llegar al paso de ubicar: el resto
 * de la consola no lo necesita.
 */
import { metrosDe } from './kmz_geometria.js';

const TESELAS = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const ATRIBUCION = 'Imágenes © Esri, Maxar, Earthstar Geographics';
const SANTIAGO = [-33.45, -70.66];
// Desde este zoom se ven los vértices para corregirlos (a 17, un lote de 5.000 m² mide
// unos 60 px de lado).
const ZOOM_VERTICES = 17;

export const COLORES = {
  verde: '#16a34a', ambar: '#f59e0b', rojo: '#dc2626', gris: '#a1a1aa', contorno: '#facc15',
};

let cargando = null;

/** Leaflet (y su hoja de estilos), una sola vez. */
export function cargarLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  cargando ??= new Promise((listo, fallo) => {
    const hoja = document.createElement('link');
    hoja.rel = 'stylesheet';
    hoja.href = 'vendor/leaflet.css';
    document.head.append(hoja);
    const guion = document.createElement('script');
    guion.src = 'vendor/leaflet.js';
    guion.onload = () => listo(window.L);
    guion.onerror = () => {
      cargando = null;
      fallo(new Error('No se pudo cargar el mapa. Revisa la conexión y vuelve a intentarlo.'));
    };
    document.head.append(guion);
  });
  return cargando;
}

export class MapaKmz {
  constructor(L, elemento) {
    this.L = L;
    this.mapa = L.map(elemento, { zoomControl: true, attributionControl: true, maxZoom: 21 })
      .setView(SANTIAGO, 12);
    L.tileLayer(TESELAS, { maxZoom: 21, maxNativeZoom: 19, attribution: ATRIBUCION }).addTo(this.mapa);
    this.panel = this.mapa.createPane('kmz-lotes');
    this.panel.style.zIndex = 450;
    this.lotes = L.layerGroup().addTo(this.mapa);
    this.anclas = L.layerGroup().addTo(this.mapa);
    this.vertices = L.layerGroup().addTo(this.mapa);
    this.puntos = [];
    this.marcas = new Map();   // clave del punto → su marcador en el mapa
    this.arrastrada = null;
    this.alCorregir = null;
    // Al mover el mapa solo entran y salen los de la vista: recrear los que están
    // cortaría un arrastre con autoPan o cerraría la ventanita de borrar.
    this.mapa.on('moveend', () => this.pintarVertices(false));
    this.alTocar = () => {};
    this.alArrastrar = () => {};
    this.arrastrable = false;
    this.recienArrastrado = false;
    this.mapa.on('click', (e) => {
      if (this.recienArrastrado) return;
      this.alTocar(e.latlng.lat, e.latlng.lng);
    });
    this.panel.addEventListener('pointerdown', (e) => this.empezarArrastre(e));
  }

  invalidar() { this.mapa.invalidateSize(); }

  ir(lat, lon, zoom = Math.max(this.mapa.getZoom(), 16)) { this.mapa.setView([lat, lon], zoom); }

  /** Encuadra los lotes y las anclas que haya. */
  encuadrar() {
    const caja = this.L.latLngBounds([]);
    const fuera = this.L.latLngBounds([]);
    // Lo dejado fuera del KMZ (el resto de la propiedad) no entra al encuadre: es decenas
    // de veces más grande que los lotes y los deja chicos en una esquina. Solo si no hay
    // nada más se encuadra en él.
    const sumar = (capa) => {
      if (capa.eachLayer && !capa.feature) { capa.eachLayer(sumar); return; }
      const destino = capa.feature?.properties?.fuera ? fuera : caja;
      if (capa.getBounds) destino.extend(capa.getBounds());
      else if (capa.getLatLng) destino.extend(capa.getLatLng());
    };
    for (const grupo of [this.lotes, this.anclas]) grupo.eachLayer(sumar);
    const final = caja.isValid() ? caja : fuera;
    if (final.isValid()) this.mapa.fitBounds(final, { padding: [24, 24], maxZoom: 18 });
    return final.isValid();
  }

  /** Las anclas marcadas: un punto con su nombre; las atípicas, en rojo. */
  ponerAnclas(anclas, atipicas = []) {
    this.anclas.clearLayers();
    for (const a of anclas) {
      const mala = atipicas.includes(a.nombre);
      // Leaflet pone un texto como HTML: el nombre va como nodo de texto (viene de
      // entradas.json, que escribe la loteadora y puede abrir la plataforma).
      const nombre = document.createElement('span');
      nombre.textContent = a.nombre;
      this.L.circleMarker([a.lat, a.lon], {
        radius: 6, weight: 2, color: '#fff', fillColor: mala ? COLORES.rojo : '#2563eb', fillOpacity: 1,
      }).bindTooltip(nombre, {
        permanent: true, direction: 'right', offset: [6, 0], className: `kmz-etiqueta${mala ? ' kmz-etiqueta--mala' : ''}`,
      }).addTo(this.anclas);
    }
  }

  /**
   * Los lotes (GeoJSON en lon/lat). `modo` "contorno" los dibuja finos para
   * calzarlos con la imagen; "nivel", rellenos según el error de área.
   */
  ponerLotes(geojson, modo = 'contorno', alElegir = null) {
    this.lotes.clearLayers();
    this.panel.style.transform = '';
    if (!geojson) return;
    const L = this.L;
    const estilo = (rasgo) => {
      const p = rasgo.properties;
      if (p.fuera) {
        // Lo que ella dejó fuera del KMZ (el resto de la propiedad): gris, ya decidido.
        return { color: COLORES.gris, weight: 1.5, dashArray: '5 4', fill: true, fillColor: COLORES.gris, fillOpacity: 0.1 };
      }
      const marcado = (p.banderas ?? []).length > 0;
      if (modo === 'contorno') {
        return { color: marcado ? COLORES.rojo : COLORES.contorno, weight: 1.5, fill: true, fillOpacity: 0.05 };
      }
      const color = COLORES[p.nivel ?? 'gris'];
      return {
        color: marcado ? COLORES.rojo : '#fff', weight: marcado ? 2.5 : 1,
        dashArray: marcado ? '5 4' : null, fillColor: marcado ? COLORES.rojo : color, fillOpacity: 0.45,
      };
    };
    L.geoJSON(geojson, {
      pane: 'kmz-lotes',
      style: estilo,
      onEachFeature: (rasgo, capa) => {
        if (alElegir) capa.bindPopup(() => alElegir(rasgo.properties));
      },
    }).addTo(this.lotes);
  }

  // --- corrección de vértices en Revisar ------------------------------------------

  /**
   * Los vértices que se pueden corregir: `puntos` [{lon, lat}], `alCorregir` con
   * `mover(punto, a)` y `borrar(punto)`. Sin puntos, se quitan.
   */
  ponerVertices(puntos, alCorregir = null) {
    this.puntos = puntos ?? [];
    this.alCorregir = alCorregir;
    this.pintarVertices(true);
  }

  /** ¿Se ven los vértices? De lejos son demasiados y se tapan entre sí. */
  verticesVisibles() { return this.mapa.getZoom() >= ZOOM_VERTICES; }

  /** `todo`: los puntos cambiaron y se rehacen todos; si no, solo los que entran o
   * salen de la vista. */
  pintarVertices(todo) {
    if (todo) { this.vertices.clearLayers(); this.marcas.clear(); }
    const visibles = this.puntos.length && this.verticesVisibles();
    // Solo los de la vista: un loteo grande tiene miles.
    const vista = visibles ? this.mapa.getBounds().pad(0.2) : null;
    const quedan = new Set();
    for (const punto of visibles ? this.puntos : []) {
      if (!vista.contains([punto.lat, punto.lon])) continue;
      const clave = `${punto.lon.toFixed(9)},${punto.lat.toFixed(9)}`;
      quedan.add(clave);
      if (!this.marcas.has(clave)) this.marcas.set(clave, this.marcaDe(punto).addTo(this.vertices));
    }
    for (const [clave, marca] of this.marcas) {
      // El que se está arrastrando no se saca aunque salga de la vista.
      if (quedan.has(clave) || marca === this.arrastrada) continue;
      this.vertices.removeLayer(marca);
      this.marcas.delete(clave);
    }
  }

  marcaDe(punto) {
    const L = this.L;
    // El círculo se ve de 16 px, pero se toca en 32: el dedo tapa más que eso.
    const icono = L.divIcon({ className: 'kmz-vertice', iconSize: [32, 32] });
    const marca = L.marker([punto.lat, punto.lon], {
      icon: icono, draggable: true, keyboard: false, autoPan: true, title: 'Arrastra para mover',
    });
    marca.on('dragstart', () => { this.arrastrada = marca; });
    marca.on('dragend', () => {
      this.arrastrada = null;
      const { lat, lng } = marca.getLatLng();
      this.alCorregir?.mover(punto, { lon: lng, lat });
    });
    marca.bindPopup(() => {
      const boton = document.createElement('button');
      boton.type = 'button';
      boton.className = 'boton boton--contorno boton--chico';
      boton.textContent = 'Borrar este vértice';
      boton.addEventListener('click', () => {
        this.mapa.closePopup();
        this.alCorregir?.borrar(punto);
      });
      return boton;
    });
    return marca;
  }

  // --- arrastre del ajuste fino ---------------------------------------------------

  empezarArrastre(e) {
    if (!this.arrastrable || e.button !== 0) return;
    // Sin el mousedown de compatibilidad, Leaflet no empieza a mover el mapa.
    e.preventDefault();
    e.stopPropagation();
    this.mapa.dragging.disable();
    const caja = this.mapa.getContainer().getBoundingClientRect();
    const punto = (ev) => this.L.point(ev.clientX - caja.left, ev.clientY - caja.top);
    const inicio = punto(e);
    let fin = inicio;
    const mover = (ev) => {
      fin = punto(ev);
      this.panel.style.transform = `translate(${fin.x - inicio.x}px, ${fin.y - inicio.y}px)`;
    };
    const soltar = (ev) => {
      // Donde se suelta manda: el último pointermove puede haber quedado antes.
      if (ev.type === 'pointerup') fin = punto(ev);
      document.removeEventListener('pointermove', mover);
      document.removeEventListener('pointerup', soltar);
      document.removeEventListener('pointercancel', soltar);
      this.mapa.dragging.enable();
      if (fin.distanceTo(inicio) < 3) { this.panel.style.transform = ''; return; }
      this.recienArrastrado = true;
      setTimeout(() => { this.recienArrastrado = false; }, 0);
      const a = this.mapa.containerPointToLatLng(inicio);
      const b = this.mapa.containerPointToLatLng(fin);
      const { de, dn } = metrosDe(a.lat, b.lat - a.lat, b.lng - a.lng);
      this.alArrastrar(de, dn);
    };
    document.addEventListener('pointermove', mover);
    document.addEventListener('pointerup', soltar);
    document.addEventListener('pointercancel', soltar);
  }
}
