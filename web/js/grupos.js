/**
 * Grupos de parcelas vecinas.
 *
 * En un loteo de cientos de parcelas, de lejos los números no caben: se encimaban
 * o desaparecían sin aviso. Cuando los de un grupo no caben, el grupo se muestra
 * como una burbuja con su rango y cuántas quedan disponibles; al acercarse vuelven
 * los números. Los grupos se arman una vez, sobre el terreno, y no en pantalla:
 * así no cambian de forma cada vez que se mueve la cámara.
 */

const TAMANO_POR_DEFECTO = 12;
// Un lote de media hectárea mide ~50 m de frente: dos seguidos están a menos de
// esto. Más lejos, el que sigue está en otra fila o en otro sector.
const SALTO_M = 120;
const METROS_POR_GRADO = 111320;
// Con más de esta fracción de números escondidos el grupo se colapsa; para volver a
// abrirse tiene que bajar de la segunda. La distancia entre las dos evita que la
// burbuja parpadee mientras se hace zoom justo en el límite.
const COLAPSAR_SOBRE = 0.4;
const ABRIR_BAJO = 0.2;
const ORDEN_NATURAL = new Intl.Collator('es', { numeric: true });

/**
 * Arma grupos de a lo más `tamano` parcelas siguiendo la numeración: los loteos se
 * numeran a lo largo de los caminos, así que lotes seguidos suelen ser vecinos y el
 * grupo tiene un rango que se entiende ("120–131"). Se corta antes si el lote que
 * sigue queda a más de `saltoM` del anterior: es otra fila u otro sector. Las
 * parcelas sin polígono no entran.
 *
 * @returns {{id: string, ids: string[], centroide: [number, number],
 *            caja: [[number, number], [number, number]]}[]}
 */
export function agruparParcelas(parcelas, { tamano = TAMANO_POR_DEFECTO, saltoM = SALTO_M } = {}) {
  const puntos = parcelas
    .filter((p) => p.centroide)
    .map((p) => ({ id: p.id, rotulo: String(p.rotulo ?? p.id), lon: p.centroide[0], lat: p.centroide[1] }))
    // El orden de llegada no puede cambiar los grupos: manda la numeración.
    .sort((a, b) => ORDEN_NATURAL.compare(a.rotulo, b.rotulo) || ORDEN_NATURAL.compare(a.id, b.id));
  if (!puntos.length) return [];
  const escalaLon = Math.cos((promedio(puntos.map((p) => p.lat)) * Math.PI) / 180);
  const distanciaM = (a, b) => Math.hypot((a.lon - b.lon) * escalaLon, a.lat - b.lat) * METROS_POR_GRADO;

  const tramos = [];
  let actual = [];
  for (const punto of puntos) {
    const previo = actual.at(-1);
    if (actual.length >= tamano || (previo && distanciaM(previo, punto) > saltoM)) {
      tramos.push(actual);
      actual = [];
    }
    actual.push(punto);
  }
  tramos.push(actual);

  return tramos.map((tramo, indice) => {
    const lons = tramo.map((p) => p.lon);
    const lats = tramo.map((p) => p.lat);
    return {
      id: `g${indice}`,
      ids: tramo.map((p) => p.id),
      centroide: [promedio(lons), promedio(lats)],
      caja: [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
    };
  });
}

/** "9–160": del rótulo menor al mayor, en orden natural. */
export function rangoDe(rotulos) {
  const ordenados = [...rotulos].sort(ORDEN_NATURAL.compare);
  const [primero, ultimo] = [ordenados[0], ordenados.at(-1)];
  return primero === ultimo ? primero : `${primero}–${ultimo}`;
}

/**
 * Lo que dice la burbuja: el rango y cuántas quedan disponibles, contando solo
 * las parcelas que dejan ver los filtros.
 */
export function resumenDeGrupo(grupo, { parcela, esDisponible, visible = () => true }) {
  const miembros = grupo.ids.filter(visible).map(parcela).filter(Boolean);
  const rotulos = miembros.map((p) => p.rotulo ?? p.id);
  return {
    rango: !miembros.length ? '' : (sonSeguidos(rotulos) ? rangoDe(rotulos) : `${miembros.length} parcelas`),
    total: miembros.length,
    disponibles: miembros.filter(esDisponible).length,
  };
}

/**
 * ¿Los números del grupo van más o menos seguidos? Un grupo es de vecinas en el
 * terreno, y a veces junta dos filas enfrentadas (120 a 125 y 300 a 305): el rango
 * "120–305" haría creer que están todas las de en medio.
 */
function sonSeguidos(rotulos) {
  const numeros = rotulos.map((r) => Number(/(\d+)\D*$/.exec(String(r))?.[1]));
  if (numeros.some(Number.isNaN)) return false;
  return Math.max(...numeros) - Math.min(...numeros) + 1 <= numeros.length * 2;
}

/** ¿Se muestra el grupo como burbuja? Con histéresis: ver COLAPSAR_SOBRE. */
export function debeColapsar(ocultas, total, estabaColapsado) {
  if (total < 2) return false;
  const fraccion = ocultas / total;
  return estabaColapsado ? fraccion >= ABRIR_BAJO : fraccion > COLAPSAR_SOBRE;
}

function promedio(valores) {
  return valores.reduce((suma, v) => suma + v, 0) / valores.length;
}


