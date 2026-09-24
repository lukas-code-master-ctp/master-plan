"""Punto de entrada del pipeline.

    python -m pipeline.construir --proyecto "ruta/a/la/carpeta"

Lee KMZ + planilla (o CRM) + panorámicas y deja en salidas/<proyecto>/sitio/ un
sitio completo, listo para subir.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config, geo, referencias, terreno
from .crm import leer_crm
from .excel import FichaComercial, leer_planilla
from .calibracion import Ajuste, aplicar, calibrar, mapa_de_caminos
from .imagenes import generar_niveles
from .kmz import ParcelaGeometrica, leer_kmz, leer_lineas
from .panoramas import Panorama, RumboResuelto, a_vista, buscar_panoramas, resolver_rumbo
from .proyeccion import Vista, proyectar_vista

# Por sobre esta diferencia entre la elevación solar calculada y la medida,
# la detección es sospechosa y hay que revisarla a mano.
ERROR_ELEVACION_SOSPECHOSO = 3.0

# Una parcela casi bajo el dron se ve enorme pero al borde del encuadre.
# Se penaliza al elegir la mejor vista, sin descartarla.
DEPRESION_INCOMODA = -70.0
PENALIZACION_DEPRESION = 0.5

# Tope al aporte de una sola parcela al puntaje de encuadre de una vista.
TOPE_AREA_POR_PARCELA = 50.0


@dataclass
class Avisos:
    lineas: list[str]

    def añadir(self, texto: str) -> None:
        self.lineas.append(texto)
        print(f"  aviso: {texto}")


def construir(fuentes: config.Fuentes, proyecto: config.Proyecto, salida: config.Salida,
              sin_imagenes: bool = False, forzar_imagenes: bool = False,
              sin_calibrar: bool = False) -> dict:
    avisos = Avisos([])

    print(f"Proyecto: {proyecto.nombre}"
          f"{' · ' + proyecto.etapa if proyecto.etapa else ''}")
    print(f"Fuentes:\n  KMZ         {fuentes.kmz}\n  planilla    {fuentes.excel or '—'}"
          f"\n  CRM         {fuentes.crm or '—'}\n  panorámicas {fuentes.panoramas}"
          f"\nSalida:       {salida.web}\n")

    print("Leyendo el KMZ...")
    geometrias = leer_kmz(fuentes.kmz)
    con_id = {g.id: g for g in geometrias if g.id}
    sin_id = [g for g in geometrias if not g.id]
    etapas = sorted({g.etapa for g in geometrias if g.etapa is not None})
    print(f"  {len(con_id)} parcelas con nombre, {len(sin_id)} polígonos sin identificar"
          f"{f', {len(etapas)} etapas' if etapas else ''}")

    fichas = _leer_fichas(fuentes, proyecto, avisos)
    _revisar_cobertura(fichas, con_id, avisos)

    print("Leyendo las panorámicas...")
    panoramas = buscar_panoramas(fuentes.panoramas)
    print(f"  {len(panoramas)} panorámicas en {len({p.posicion for p in panoramas})} posiciones")
    _revisar_ids_de_vista(panoramas)

    print("Resolviendo el rumbo de cada panorámica con la posición del sol...")
    vistas: list[tuple[Panorama, RumboResuelto, Vista]] = []
    for panorama in panoramas:
        rumbo = resolver_rumbo(panorama)
        vistas.append((panorama, rumbo, a_vista(panorama, rumbo)))
        marca = "" if rumbo.error_elevacion <= ERROR_ELEVACION_SOSPECHOSO else "  <-- REVISAR"
        print(f"  {panorama.id}  rumbo {rumbo.rumbo0:6.1f}°  "
              f"sol {rumbo.azimut_solar:5.1f}°/{rumbo.elevacion_solar:4.1f}°  "
              f"error elevación {rumbo.error_elevacion:4.1f}°  "
              f"({rumbo.disco.metodo}){marca}")
        if rumbo.error_elevacion > ERROR_ELEVACION_SOSPECHOSO:
            avisos.añadir(
                f"{panorama.id}: el sol detectado está a {rumbo.disco.elevacion_medida:.1f}° "
                f"pero debería estar a {rumbo.elevacion_solar:.1f}°. El rumbo puede estar mal.")

    print("Cargando el modelo de terreno...")
    relieve = _cargar_terreno(geometrias, panoramas, avisos)
    despegue = proyecto.despegue or _despegue_por_defecto(panoramas)
    if relieve:
        print(f"  despegue en ({despegue[0]:.5f}, {despegue[1]:.5f}), cota DEM "
              f"{relieve.cota(despegue):.0f} m"
              f"{'' if proyecto.despegue else '  (supuesto: bajo la primera toma)'}")

    hitos = _resolver_referencias(proyecto, geometrias, avisos)
    cota_despegue = relieve.cota(despegue) if relieve else None

    ajustes: dict[str, Ajuste] = {}
    if sin_calibrar:
        print("Sin calibración fina contra la foto (--sin-calibrar).")
    else:
        print("Calibrando la pose de cada vista contra la foto...")
        lineas = leer_lineas(fuentes.kmz)
        calibradas = []
        for panorama, rumbo, vista in vistas:
            modelo = terreno.modelo_para_vista(relieve, vista, despegue) if relieve else None
            ajuste = calibrar(vista, lineas, modelo, mapa_de_caminos(panorama.ruta))
            ajustes[vista.id] = ajuste
            print(f"  {vista.id}: giro {ajuste.giro:+.2f}°, inclinación E {ajuste.inclinacion_este:+.2f}° "
                  f"/ N {ajuste.inclinacion_norte:+.2f}°, desnivel {ajuste.desnivel:+.1f} m  "
                  f"(calce {100 * ajuste.mejora:+.0f}%){'' if ajuste.aplicado else '  <-- sin cambio'}")
            calibradas.append((panorama, rumbo, aplicar(vista, ajuste)))
        vistas = calibradas

    print("Proyectando parcelas sobre cada vista...")
    _copiar_plantilla_web(salida.web)
    salida.vistas.mkdir(parents=True, exist_ok=True)
    apariciones: dict[str, list[tuple[str, float]]] = {}
    resumen_vistas = []

    for panorama, rumbo, vista in vistas:
        modelo = terreno.modelo_para_vista(relieve, vista, despegue) if relieve else None
        proyectadas = proyectar_vista(vista, [(g.id, g.anillo) for g in con_id.values()],
                                      terreno=modelo)
        for parcela in proyectadas:
            puntaje = parcela.area_angular
            if parcela.centro[1] < DEPRESION_INCOMODA:
                puntaje *= PENALIZACION_DEPRESION
            apariciones.setdefault(parcela.id, []).append((vista.id, puntaje))

        _escribir_json(salida.vistas / f"{vista.id}.json", {
            "id": vista.id,
            "referencias": [
                referencias.proyectar(vista, hito, _cota_en_datum_dron(vista, hito, cota_despegue))
                for hito in hitos
            ],
            "parcelas": [
                {
                    "id": p.id,
                    "anillo": [list(v) for v in p.anillo],
                    "centro": list(p.centro),
                    "distancia_m": p.distancia_m,
                    "area_angular": p.area_angular,
                }
                for p in proyectadas
            ],
        })
        resumen_vistas.append(_resumen_vista(panorama, rumbo, vista, proyectadas,
                                             "dem" if relieve else "plano", despegue,
                                             ajustes.get(vista.id, Ajuste())))
        print(f"  {vista.id}: {len(proyectadas)} parcelas visibles")

    if not sin_imagenes:
        print("Generando niveles de imagen...")
        for panorama, _, vista in vistas:
            destino = salida.panoramas / vista.id
            generar_niveles(panorama.ruta, destino, forzar=forzar_imagenes)
            print(f"  {vista.id} listo")

    print("Escribiendo los datos...")
    parcelas = _armar_parcelas(fichas, con_id, apariciones)
    _escribir_json(salida.datos / "parcelas.json", {
        "proyecto": proyecto.nombre,
        "etapa": proyecto.etapa,
        "etapas": etapas,
        "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "whatsapp": proyecto.whatsapp,
        "referencias": [{"nombre": h.nombre, "lon": h.lon, "lat": h.lat} for h in hitos],
        "estados": config.ESTADOS,
        "resumen": _resumen(parcelas),
        "parcelas": parcelas,
        "otros_poligonos": [
            {"poligono": _redondear_anillo(g.anillo),
             "motivo": "no_en_venta" if not g.en_venta else "sin_identificar"}
            for g in geometrias if not g.id or not g.en_venta
        ],
    })
    _escribir_json(salida.datos / "vistas.json", {
        "inicial": _vista_inicial(resumen_vistas),
        "vistas": resumen_vistas,
    })

    resultado = {
        "parcelas": len(parcelas),
        "con_geometria": sum(1 for p in parcelas if p["poligono"]),
        "vistas": len(resumen_vistas),
        "avisos": avisos.lineas,
        "sitio": salida.web,
    }
    print()
    print(f"Listo. {resultado['parcelas']} parcelas "
          f"({resultado['con_geometria']} con geometría) en {resultado['vistas']} vistas.")
    print(f"Sitio en {salida.web}")
    if avisos.lineas:
        print(f"{len(avisos.lineas)} aviso(s). Revisa arriba.")
    return resultado


def _leer_fichas(fuentes: config.Fuentes, proyecto: config.Proyecto,
                 avisos: Avisos) -> dict[str, FichaComercial]:
    """La planilla del proyecto si la hay; si no, el CRM; si no, nada."""
    if fuentes.excel:
        print("Leyendo la planilla...")
        fichas = leer_planilla(fuentes.excel)
    elif fuentes.crm:
        print(f"Leyendo el CRM ({proyecto.parcelacion})...")
        try:
            fichas = leer_crm(fuentes.crm, proyecto.parcelacion or proyecto.nombre.upper())
        except ValueError as error:
            # Que el loteo no figure en el export no puede tumbar la construcción:
            # casi siempre es el nombre escrito distinto, y el sitio se puede armar
            # igual con las parcelas como no disponibles.
            avisos.añadir(f"{error}; las parcelas salen como no disponibles")
            return {}
    else:
        avisos.añadir("no hay planilla ni export del CRM: todas las parcelas salen "
                      "como no disponibles")
        return {}
    print(f"  {len(fichas)} parcelas con datos comerciales")
    return fichas


def _cargar_terreno(geometrias: list[ParcelaGeometrica], panoramas: list[Panorama],
                    avisos: Avisos) -> terreno.Terreno | None:
    """El DEM que cubre el loteo y las posiciones de vuelo. Sin red y sin caché no
    hay modelo: se avisa y se sigue con terreno plano, que es peor pero no rompe."""
    puntos = [p for g in geometrias for p in g.anillo] + [(p.lon, p.lat) for p in panoramas]
    if not puntos:
        return None
    try:
        relieve = terreno.cargar(geo.caja(puntos), config.CACHE_TERRENO)
    except (OSError, ValueError) as error:
        avisos.añadir(f"no pude cargar el modelo de terreno ({error}); se asume terreno plano")
        return None
    print(f"  {relieve.cotas.shape[1]}×{relieve.cotas.shape[0]} px a "
          f"{relieve.metros_por_pixel:.1f} m/px, cotas {relieve.cotas.min():.0f}–"
          f"{relieve.cotas.max():.0f} m")
    return relieve


def _resolver_referencias(proyecto: config.Proyecto, geometrias: list[ParcelaGeometrica],
                          avisos: Avisos) -> list[referencias.Referencia]:
    """Los hitos del horizonte, con su cota. Sin red se avisa y se sigue sin ellos."""
    if not proyecto.referencias:
        return []
    print("Ubicando los puntos de referencia...")
    puntos = [p for g in geometrias for p in g.anillo]
    centro = (sum(p[0] for p in puntos) / len(puntos), sum(p[1] for p in puntos) / len(puntos))
    try:
        hitos = referencias.resolver(list(proyecto.referencias), centro, config.CACHE_REFERENCIAS)
    except (OSError, ValueError, KeyError) as error:
        avisos.añadir(f"no pude ubicar los puntos de referencia ({error}); se omiten")
        return []
    completos = []
    for hito in hitos:
        if hito.cota is None:
            try:
                hito = referencias.Referencia(hito.nombre, hito.lon, hito.lat,
                                              terreno.cota_en((hito.lon, hito.lat), config.CACHE_TERRENO))
            except (OSError, ValueError):
                pass
        completos.append(hito)
        print(f"  {hito.nombre}: {geo.distancia(centro, (hito.lon, hito.lat)) / 1000:.1f} km"
              f"{f', cota {hito.cota:.0f} m' if hito.cota is not None else ''}")
    return completos


def _cota_en_datum_dron(vista: Vista, hito: referencias.Referencia,
                        cota_despegue: float | None) -> float:
    """La cota del hito en el datum del dron: la del despegue más el desnivel real."""
    if hito.cota is None or cota_despegue is None:
        return vista.terreno_plano()
    return vista.terreno_plano() + (hito.cota - cota_despegue)


def _despegue_por_defecto(panoramas: list[Panorama]) -> geo.Punto:
    """Bajo la primera toma: el piloto sube en vertical y dispara antes de moverse."""
    primera = min(panoramas, key=lambda p: p.momento)
    return (primera.lon, primera.lat)


def _copiar_plantilla_web(destino: Path) -> None:
    """Copia el sitio (html, css, js, vendor) junto a los datos: la carpeta queda
    autocontenida y se sube tal cual."""
    ignorar = shutil.ignore_patterns("datos", "panoramas", "*.test.js", ".DS_Store")
    shutil.copytree(config.PLANTILLA_WEB, destino, ignore=ignorar, dirs_exist_ok=True)


def _revisar_ids_de_vista(panoramas: list[Panorama]) -> None:
    """Corta si dos vistas comparten id, porque una pisaría a la otra en la salida.

    Cada vista escribe `datos/vistas/<id>.json` y su carpeta de panorámicas, así que
    un id repetido no da error: simplemente se pierde una vista. Con las posiciones
    bien asignadas no debería ocurrir; si ocurre es que hay dos tomas en el mismo
    punto y a la misma altura, y eso hay que mirarlo antes de publicar.
    """
    por_id: dict[str, list[Panorama]] = {}
    for panorama in panoramas:
        por_id.setdefault(panorama.id, []).append(panorama)

    repetidos = {i: ps for i, ps in sorted(por_id.items()) if len(ps) > 1}
    if repetidos:
        detalle = "; ".join(f"{i}: {', '.join(p.ruta.name for p in ps)}"
                            for i, ps in repetidos.items())
        raise ValueError(f"hay panorámicas que comparten el id de vista y una "
                         f"sobreescribiría a la otra ({detalle})")


def _revisar_cobertura(fichas: dict[str, FichaComercial],
                       geometrias: dict[str, ParcelaGeometrica],
                       avisos: Avisos) -> None:
    sin_geometria = sorted(set(fichas) - set(geometrias), key=_orden_lote)
    sin_ficha = sorted(set(geometrias) - set(fichas), key=_orden_lote)
    if sin_geometria:
        avisos.añadir(f"{len(sin_geometria)} parcelas de la planilla no están en el KMZ "
                      f"y no tendrán vista aérea: {', '.join(sin_geometria[:8])}"
                      f"{'...' if len(sin_geometria) > 8 else ''}")
    if sin_ficha:
        avisos.añadir(f"{len(sin_ficha)} parcelas del KMZ no están en la planilla: "
                      f"{', '.join(sin_ficha)}")


def _armar_parcelas(fichas: dict[str, FichaComercial],
                    geometrias: dict[str, ParcelaGeometrica],
                    apariciones: dict[str, list[tuple[str, float]]]) -> list[dict]:
    parcelas = []
    for identificador in sorted(set(fichas) | set(geometrias), key=_orden_lote):
        ficha = fichas.get(identificador)
        geometria = geometrias.get(identificador)
        vistas = apariciones.get(identificador, [])
        mejor = max(vistas, key=lambda par: par[1])[0] if vistas else None
        etapa_conocida = (geometria.etapa if geometria and geometria.etapa is not None
                          else ficha.etapa if ficha else None)
        etapa, numero, rotulo = _descomponer(identificador, etapa_conocida)

        parcelas.append({
            "id": identificador,
            "numero": numero,
            "etapa": etapa,
            "rotulo": rotulo,
            "estado": ficha.estado if ficha else (
                "no_en_venta" if geometria and not geometria.en_venta else config.ESTADO_POR_DEFECTO),
            "superficie_m2": ficha.superficie_m2 if ficha else (
                round(geometria.area_m2) if geometria else None),
            "servidumbre_m": ficha.servidumbre_m if ficha else None,
            "servidumbre_m2": ficha.servidumbre_m2 if ficha else None,
            "precio": ficha.precio if ficha else None,
            "moneda": ficha.moneda if ficha else "CLP",
            "link_pago": ficha.link_pago if ficha else None,
            "en_planilla": ficha is not None,
            "area_kmz_m2": round(geometria.area_m2) if geometria else None,
            "centroide": _redondear_punto(geometria.centroide) if geometria else None,
            "poligono": _redondear_anillo(geometria.anillo) if geometria else None,
            "mejor_vista": mejor,
            "vistas": sorted(v for v, _ in vistas),
        })
    return parcelas


def _descomponer(identificador: str, etapa: int | None) -> tuple[int | None, int, str]:
    """(etapa, número, rótulo) de un id.

    El rótulo es lo que va en la pastilla sobre el terreno: el número a secas. Solo
    un id "sector-lote" sin etapas conocidas se rotula entero, porque ahí el primer
    número no es una etapa y quitarlo cambiaría el nombre del lote.
    """
    partes = identificador.split("-")
    numero = int(re.sub(r"\D", "", partes[-1]) or 0)
    if etapa is not None:
        return etapa, numero, str(numero)
    if len(partes) > 1:
        return None, numero, identificador
    return None, numero, str(numero)


def _resumen_vista(panorama: Panorama, rumbo: RumboResuelto, vista: Vista,
                   proyectadas: list, terreno_usado: str, despegue: geo.Punto,
                   ajuste: Ajuste) -> dict:
    return {
        "id": vista.id,
        "posicion": vista.posicion,
        "etiqueta": panorama.etiqueta,
        "altura_m": panorama.altura_nominal,
        "altura_real_m": round(vista.altura_relativa, 1),
        "lon": round(vista.lon, config.DECIMALES_COORD),
        "lat": round(vista.lat, config.DECIMALES_COORD),
        "rumbo0": vista.rumbo0,
        "parcelas_visibles": len(proyectadas),
        "puntaje_encuadre": round(_puntaje_encuadre(proyectadas), 1),
        "imagenes": {
            nombre: f"panoramas/{vista.id}/{nombre}.jpg"
            for nombre in config.NIVELES_IMAGEN
        },
        "diagnostico": {
            "azimut_solar": round(rumbo.azimut_solar, 2),
            "elevacion_solar": round(rumbo.elevacion_solar, 2),
            "elevacion_medida": round(rumbo.disco.elevacion_medida, 2),
            "error_elevacion": round(rumbo.error_elevacion, 2),
            "metodo": rumbo.disco.metodo,
            "pixeles_sol": rumbo.disco.pixeles,
            "gimbal_yaw": panorama.gimbal_yaw,
            "tomada": panorama.momento.isoformat(),
            "terreno": terreno_usado,
            "despegue": [round(despegue[0], config.DECIMALES_COORD),
                         round(despegue[1], config.DECIMALES_COORD)],
            "calibracion": {
                "giro": ajuste.giro,
                "inclinacion_este": ajuste.inclinacion_este,
                "inclinacion_norte": ajuste.inclinacion_norte,
                "desnivel": ajuste.desnivel,
                "mejora": round(ajuste.mejora, 3),
            },
        },
    }


def _puntaje_encuadre(proyectadas: list) -> float:
    """Qué tan bien se aprecia el loteo desde una vista.

    Suma cuánto ocupa cada parcela en el campo visual, con tope: sin él, la
    parcela que queda justo bajo el dron se lleva todo el puntaje y gana una
    vista donde el resto del loteo no se distingue.
    """
    return sum(min(p.area_angular, TOPE_AREA_POR_PARCELA) for p in proyectadas)


def _vista_inicial(resumen_vistas: list[dict]) -> str | None:
    """Con cuál abrir el sitio: la que mejor muestra el loteo."""
    if not resumen_vistas:
        return None
    return max(resumen_vistas, key=lambda v: v["puntaje_encuadre"])["id"]


def _resumen(parcelas: list[dict]) -> dict:
    conteo: dict[str, int] = {}
    for parcela in parcelas:
        conteo[parcela["estado"]] = conteo.get(parcela["estado"], 0) + 1
    return {
        "total": len(parcelas),
        "con_geometria": sum(1 for p in parcelas if p["poligono"]),
        "con_vista_aerea": sum(1 for p in parcelas if p["mejor_vista"]),
        "por_estado": conteo,
    }


def _orden_lote(identificador: str) -> tuple[int, int]:
    """Primero por etapa (o sector) y después por número, para que "1-15" no
    quede entre "2-1" y "2-7"."""
    partes = identificador.split("-")
    numero = int(re.sub(r"\D", "", partes[-1]) or 0)
    etapa = int(re.sub(r"\D", "", partes[0]) or 0) if len(partes) > 1 else 0
    return etapa, numero


def _redondear_punto(punto) -> list[float]:
    return [round(punto[0], config.DECIMALES_COORD), round(punto[1], config.DECIMALES_COORD)]


def _redondear_anillo(anillo) -> list[list[float]]:
    return [_redondear_punto(p) for p in anillo]


def _escribir_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":"), default=str),
                    encoding="utf-8")


def agregar_argumentos_de_proyecto(parser: argparse.ArgumentParser) -> None:
    """Los mismos argumentos para construir y para el control de calce."""
    parser.add_argument("--proyecto", type=Path, default=config.PROYECTO,
                        help="carpeta con el KMZ, las panorámicas y, si hay, la planilla "
                             "y proyecto.json (por defecto, la que contiene a masterplan360)")
    parser.add_argument("--nombre", help="nombre del loteo (pisa el de proyecto.json)")
    parser.add_argument("--etapa", help="subtítulo, por ejemplo 'Etapa 1' o 'Los Pequenes'")
    parser.add_argument("--whatsapp", help="teléfono del botón de WhatsApp, sin +")
    parser.add_argument("--parcelacion", help="nombre del loteo en el CRM")
    parser.add_argument("--despegue", help="lon,lat desde donde despegó el dron")
    parser.add_argument("--referencias", help="pueblos a rotular en el horizonte, separados por coma")
    parser.add_argument("--salida", type=Path,
                        help="carpeta de salida (por defecto salidas/<nombre-del-proyecto>)")


def resolver(argumentos, crm: Path | None = None) -> tuple[config.Fuentes, config.Proyecto, config.Salida]:
    fuentes = config.descubrir_fuentes(argumentos.proyecto, crm=crm,
                                       sin_crm=getattr(argumentos, "sin_crm", False))
    despegue = None
    if getattr(argumentos, "despegue", None):
        lon, lat = (float(v) for v in argumentos.despegue.split(","))
        despegue = [lon, lat]
    referencias_cli = None
    if getattr(argumentos, "referencias", None):
        referencias_cli = [r.strip() for r in argumentos.referencias.split(",") if r.strip()]
    proyecto = config.cargar_proyecto(argumentos.proyecto, nombre=argumentos.nombre,
                                      etapa=argumentos.etapa, whatsapp=argumentos.whatsapp,
                                      parcelacion=argumentos.parcelacion, despegue=despegue,
                                      referencias=referencias_cli)
    return fuentes, proyecto, config.salida_para(proyecto, base=argumentos.salida)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Construye el masterplan 360 de un loteo.")
    agregar_argumentos_de_proyecto(parser)
    parser.add_argument("--crm", type=Path,
                        help="export del CRM (ctp_parcelas_latest.csv) del que sacar la "
                             "planilla cuando el proyecto no trae xlsx")
    parser.add_argument("--sin-crm", action="store_true",
                        help="este loteo no tiene export comercial; no buscar ninguno")
    parser.add_argument("--sin-imagenes", action="store_true",
                        help="salta la generación de panorámicas (útil para iterar rápido)")
    parser.add_argument("--forzar-imagenes", action="store_true",
                        help="regenera las panorámicas aunque ya estén al día")
    parser.add_argument("--sin-calibrar", action="store_true",
                        help="no afina la pose de cada vista contra la foto")
    argumentos = parser.parse_args(argv)

    try:
        fuentes, proyecto, salida = resolver(argumentos, crm=argumentos.crm)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1

    construir(fuentes, proyecto, salida,
              sin_imagenes=argumentos.sin_imagenes,
              forzar_imagenes=argumentos.forzar_imagenes,
              sin_calibrar=argumentos.sin_calibrar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
