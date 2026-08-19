/** Carga y consulta de los datos que produce el pipeline. */

const RUTA_DATOS = 'datos';

export class Catalogo {
  constructor(parcelas, vistas) {
    this.meta = parcelas;
    this.parcelas = parcelas.parcelas;
    this.estados = parcelas.estados;
    this.otrosPoligonos = parcelas.otros_poligonos ?? [];
    this.vistas = vistas.vistas;

    this.porId = new Map(this.parcelas.map((p) => [p.id, p]));
    this.vistaPorId = new Map(this.vistas.map((v) => [v.id, v]));
    /** Con cuál abrir: la que mejor muestra el loteo, según el pipeline. */
    this.vistaInicial = this.vistaPorId.get(vistas.inicial) ?? this.vistas[0];
    this.overlays = new Map();
  }

  static async cargar() {
    const [parcelas, vistas] = await Promise.all([
      pedirJson(`${RUTA_DATOS}/parcelas.json`),
      pedirJson(`${RUTA_DATOS}/vistas.json`),
    ]);
    return new Catalogo(parcelas, vistas);
  }

  /** Overlay de una vista. Se pide una sola vez y queda en memoria. */
  async overlayDe(idVista) {
    if (!this.overlays.has(idVista)) {
      const datos = await pedirJson(`${RUTA_DATOS}/vistas/${idVista}.json`);
      this.overlays.set(idVista, new Map(datos.parcelas.map((p) => [p.id, p])));
    }
    return this.overlays.get(idVista);
  }

  posiciones() {
    const vistas = new Map();
    for (const vista of this.vistas) {
      if (!vistas.has(vista.posicion)) vistas.set(vista.posicion, []);
      vistas.get(vista.posicion).push(vista);
    }
    return [...vistas.entries()]
      .sort(([a], [b]) => a - b)
      .map(([posicion, lista]) => ({
        posicion,
        alturas: lista.sort((a, b) => a.altura_m - b.altura_m),
      }));
  }

  /** La vista de la misma posición cuya altura sea la más parecida a la pedida. */
  vistaCercana(posicion, alturaDeseada) {
    const candidatas = this.vistas.filter((v) => v.posicion === posicion);
    if (!candidatas.length) return null;
    return candidatas.reduce((mejor, v) =>
      Math.abs(v.altura_m - alturaDeseada) < Math.abs(mejor.altura_m - alturaDeseada) ? v : mejor);
  }

  color(estado) {
    return this.estados[estado]?.color ?? '#8d8d8d';
  }

  /** Color de texto que se lee sobre el color del estado. */
  contraste(estado) {
    return luminancia(this.color(estado)) > 0.55 ? '#1c1a17' : '#ffffff';
  }

  etiquetaEstado(estado) {
    return this.estados[estado]?.etiqueta ?? estado;
  }
}

/** Filtro sobre el catálogo. Devuelve el conjunto de ids que pasan. */
export function filtrar(parcelas, filtros) {
  const { estados, supMin, supMax, soloConVista } = filtros;
  return new Set(
    parcelas
      .filter((p) => {
        if (estados.size && !estados.has(p.estado)) return false;
        if (supMin != null && (p.superficie_m2 ?? 0) < supMin) return false;
        if (supMax != null && (p.superficie_m2 ?? Infinity) > supMax) return false;
        if (soloConVista && !p.mejor_vista) return false;
        return true;
      })
      .map((p) => p.id),
  );
}

/** Búsqueda por número de lote. "314" y "a314" encuentran la parcela A314. */
export function buscar(parcelas, consulta, limite = 8) {
  const texto = consulta.trim().toUpperCase().replace(/^LOTES?\s*/, '').replace(/\s+/g, '');
  if (!texto) return [];
  const digitos = texto.replace(/\D/g, '');

  const coincide = (p) => {
    if (p.id === texto || p.id === `A${digitos}`) return 3;
    if (digitos && String(p.numero) === digitos) return 3;
    if (p.id.includes(texto)) return 2;
    if (digitos && String(p.numero).startsWith(digitos)) return 1;
    return 0;
  };

  return parcelas
    .map((p) => ({ parcela: p, puntaje: coincide(p) }))
    .filter((r) => r.puntaje > 0)
    .sort((a, b) => b.puntaje - a.puntaje || a.parcela.numero - b.parcela.numero)
    .slice(0, limite)
    .map((r) => r.parcela);
}

/** Luminancia relativa (WCAG) de un color #rrggbb, entre 0 y 1. */
export function luminancia(hex) {
  const canal = (i) => {
    const v = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * canal(0) + 0.7152 * canal(1) + 0.0722 * canal(2);
}

async function pedirJson(ruta) {
  let respuesta;
  try {
    respuesta = await fetch(ruta);
  } catch (causa) {
    throw new ErrorDeDatos(ruta, causa);
  }
  if (!respuesta.ok) throw new ErrorDeDatos(ruta, new Error(`HTTP ${respuesta.status}`));
  return respuesta.json();
}

export class ErrorDeDatos extends Error {
  constructor(ruta, causa) {
    super(`No pude cargar ${ruta}: ${causa.message}`);
    this.ruta = ruta;
    this.causa = causa;
  }
}
