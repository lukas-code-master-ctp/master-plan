"""Punto de entrada del pipeline.

    python -m pipeline.construir

Lee KMZ + Excel + panorámicas y deja en web/ todo lo que el sitio necesita.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import config
from .excel import FichaComercial, leer_excel
from .imagenes import generar_niveles
from .kmz import ParcelaGeometrica, leer_kmz
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


def construir(fuentes: config.Fuentes | None = None,
              sin_imagenes: bool = False,
              forzar_imagenes: bool = False) -> dict:
    fuentes = fuentes or config.descubrir_fuentes(config.PROYECTO)
    avisos = Avisos([])

    print(f"Fuentes:\n  KMZ        {fuentes.kmz}\n  planilla   {fuentes.excel}"
          f"\n  panorámicas {fuentes.panoramas}\n")

    print("Leyendo el KMZ...")
    geometrias = leer_kmz(fuentes.kmz)
    con_id = {g.id: g for g in geometrias if g.id}
    sin_id = [g for g in geometrias if not g.id]
    print(f"  {len(con_id)} parcelas con nombre, {len(sin_id)} polígonos sin identificar")

    print("Leyendo la planilla...")
    fichas = leer_excel(fuentes.excel)
    print(f"  {len(fichas)} parcelas en la planilla")

    _revisar_cobertura(fichas, con_id, avisos)

    print("Leyendo las panorámicas...")
    panoramas = buscar_panoramas(fuentes.panoramas)
    print(f"  {len(panoramas)} panorámicas en {len({p.posicion for p in panoramas})} posiciones")

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

    print("Proyectando parcelas sobre cada vista...")
    config.SALIDA_VISTAS.mkdir(parents=True, exist_ok=True)
    apariciones: dict[str, list[tuple[str, float]]] = {}
    resumen_vistas = []

    for panorama, rumbo, vista in vistas:
        proyectadas = proyectar_vista(vista, [(g.id, g.anillo) for g in con_id.values()])
        for parcela in proyectadas:
            puntaje = parcela.area_angular
            if parcela.centro[1] < DEPRESION_INCOMODA:
                puntaje *= PENALIZACION_DEPRESION
            apariciones.setdefault(parcela.id, []).append((vista.id, puntaje))

        _escribir_json(config.SALIDA_VISTAS / f"{vista.id}.json", {
            "id": vista.id,
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
        resumen_vistas.append(_resumen_vista(panorama, rumbo, vista, proyectadas))
        print(f"  {vista.id}: {len(proyectadas)} parcelas visibles")

    if not sin_imagenes:
        print("Generando niveles de imagen...")
        for panorama, _, vista in vistas:
            destino = config.SALIDA_PANORAMAS / vista.id
            generar_niveles(panorama.ruta, destino, forzar=forzar_imagenes)
            print(f"  {vista.id} listo")

    print("Escribiendo los datos...")
    parcelas = _armar_parcelas(fichas, con_id, apariciones)
    _escribir_json(config.SALIDA_DATOS / "parcelas.json", {
        "proyecto": config.NOMBRE_PROYECTO,
        "etapa": config.NOMBRE_ETAPA,
        "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "whatsapp": config.WHATSAPP,
        "estados": config.ESTADOS,
        "resumen": _resumen(parcelas),
        "parcelas": parcelas,
        "otros_poligonos": [
            {"poligono": _redondear_anillo(g.anillo),
             "motivo": "no_en_venta" if not g.en_venta else "sin_identificar"}
            for g in geometrias if not g.id or not g.en_venta
        ],
    })
    _escribir_json(config.SALIDA_DATOS / "vistas.json", {
        "inicial": _vista_inicial(resumen_vistas),
        "vistas": resumen_vistas,
    })

    resultado = {
        "parcelas": len(parcelas),
        "con_geometria": sum(1 for p in parcelas if p["poligono"]),
        "vistas": len(resumen_vistas),
        "avisos": avisos.lineas,
    }
    print()
    print(f"Listo. {resultado['parcelas']} parcelas "
          f"({resultado['con_geometria']} con geometría) en {resultado['vistas']} vistas.")
    if avisos.lineas:
        print(f"{len(avisos.lineas)} aviso(s). Revisa arriba.")
    return resultado


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

        parcelas.append({
            "id": identificador,
            "numero": _orden_lote(identificador),
            "estado": ficha.estado if ficha else (
                "no_en_venta" if geometria and not geometria.en_venta else config.ESTADO_POR_DEFECTO),
            "superficie_m2": ficha.superficie_m2 if ficha else (
                round(geometria.area_m2) if geometria else None),
            "servidumbre_m": ficha.servidumbre_m if ficha else None,
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


def _resumen_vista(panorama: Panorama, rumbo: RumboResuelto,
                   vista: Vista, proyectadas: list) -> dict:
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


def _orden_lote(identificador: str) -> int:
    numeros = re.sub(r"\D", "", identificador)
    return int(numeros) if numeros else 0


def _redondear_punto(punto) -> list[float]:
    return [round(punto[0], config.DECIMALES_COORD), round(punto[1], config.DECIMALES_COORD)]


def _redondear_anillo(anillo) -> list[list[float]]:
    return [_redondear_punto(p) for p in anillo]


def _escribir_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, separators=(",", ":")),
                    encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Construye los datos del masterplan 360.")
    parser.add_argument("--proyecto", type=Path, default=config.PROYECTO,
                        help="carpeta con el KMZ, la planilla y las panorámicas "
                             "(por defecto, la que contiene a masterplan360)")
    parser.add_argument("--sin-imagenes", action="store_true",
                        help="salta la generación de panorámicas (útil para iterar rápido)")
    parser.add_argument("--forzar-imagenes", action="store_true",
                        help="regenera las panorámicas aunque ya estén al día")
    argumentos = parser.parse_args(argv)

    try:
        fuentes = config.descubrir_fuentes(argumentos.proyecto)
    except FileNotFoundError as error:
        print(error, file=sys.stderr)
        return 1

    construir(fuentes,
              sin_imagenes=argumentos.sin_imagenes,
              forzar_imagenes=argumentos.forzar_imagenes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
