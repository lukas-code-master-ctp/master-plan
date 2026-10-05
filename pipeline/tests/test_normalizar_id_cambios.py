"""normalizar_id antes y después de exigir que la letra de sector esté suelta.

Compara la versión anterior (copiada tal cual en `_viejo`) con la actual sobre un
corpus grande de nombres realistas y exige que cada salida que cambia caiga en uno de
los casos que el spec acepta (docs/specs/2026-10-03-normalizar-id.md):

- `lote_pegado`: LOTE o LOTES pegado al número ("LOTE12" → antes "E12", ahora "12").
- `parcela_como_lote`: PARCELA, PARCELAS, SITIO y SITIOS se leen como LOTE ("Parcela 4"
  → antes "A4", ahora "4"; "Sitio 5" → antes "O5", ahora "5"; "PARCELA-12" → antes
  None, ahora "12").
- `palabra_de_lote_con_otras_palabras`: la letra que antes salía era la cola de LOTE,
  PARCELA o SITIO, pero el texto trae otras palabras: ahora None ("PARCELA12 CASA 3"), o la
  letra suelta que viene después.
- `numero_antes_de_la_letra`: la letra que antes salía venía después de un número (salvo
  "ETAPA n"): era una unidad o un sufijo, no un sector ("1.342 m2" → antes "M2", ahora
  None; "12 A 5" → antes "A5", ahora None).
- `cola_de_otra_palabra`: la letra que antes salía era la cola de otra palabra ("ROL
  273-15" → antes "L273"; "MANZANA 3" → "A3"): ahora None, o la letra suelta que viene
  después ("ETAPA 2 LOTE A 5" → antes "A2", ahora "A5").

En los dos primeros, la nueva da lo mismo que la anterior con LOTE escrito aparte.
"""
from __future__ import annotations

import itertools
import random
import re

from pipeline.kmz import normalizar_id

_LETRA = r"[^\W\d_]"
_PALABRAS_DE_LOTE = {"LOTE", "LOTES", "PARCELA", "PARCELAS", "SITIO", "SITIOS"}
CASOS = ("lote_pegado", "parcela_como_lote", "palabra_de_lote_con_otras_palabras",
         "numero_antes_de_la_letra", "cola_de_otra_palabra")


def _viejo(texto):
    """normalizar_id hasta el commit 13cade8, sin tocar."""
    if texto is None:
        return None
    if isinstance(texto, float) and texto.is_integer():
        texto = int(texto)
    limpio = re.sub(r"\bLOTES?\b", " ", str(texto).strip().upper())

    con_letra = re.search(r"([A-Z])\s*0*(\d+)", limpio)
    if con_letra:
        return f"{con_letra.group(1)}{int(con_letra.group(2))}"

    solo_numeros = re.fullmatch(r"[\s.]*(?:(?<=\s)[-#][\s]*)?(\d+(?:\s*-\s*\d+)*)[\s.]*", limpio)
    if solo_numeros:
        partes = solo_numeros.group(1).replace(" ", "").split("-")
        return "-".join(str(int(p)) for p in partes)
    return None


def corpus(al_azar: int = 20000) -> list:
    """Nombres de lote como vienen en KMZ, planillas y CRM, y basura que convive con ellos,
    más `al_azar` combinaciones al azar (con semilla fija) de los mismos fragmentos."""
    palabras = ["", "LOTE", "Lote", "lote", "LOTES", "PARCELA", "Parcela", "parcela", "PARCELAS",
                "SITIO", "Sitio", "SITIOS"]
    separadores = ["", " ", "  ", "-", " - ", "#", " #", " # ", "_"]
    numeros = ["1", "7", "12", "007", "042", "214", "420", "1000"]
    pares = ["7-1", "8-01", "10-6", "8 - 01", "3-12-1"]
    letras = ["A", "B", "E", "a", "Z"]
    otras = ["ROL", "Rol", "MZ", "Mz", "MANZANA", "Manzana", "ETAPA", "SECTOR", "MICROSITIO",
             "CASA", "LOTEO", "SUBLOTE", "AÑO", "Nº", "N°", "No", "CAMINO", "LOTEA"]
    salida: list = [None, "", " ", "A", "-12", "12-", "LOTE--12", "sin numero"]

    cuerpos = numeros + pares
    for palabra, sep, cuerpo in itertools.product(palabras, separadores, cuerpos):
        salida.append(f"{palabra}{sep}{cuerpo}")
        salida.append(f"  {palabra}{sep}{cuerpo}. ")
    for palabra, letra, sep, num in itertools.product(palabras, letras, ["", " ", "-"], numeros):
        espacio = " " if palabra else ""
        salida.append(f"{palabra}{espacio}{letra}{sep}{num}")
        salida.append(f"{palabra}{letra}{sep}{num}")            # la letra pegada a la palabra
    for otra, sep, cuerpo in itertools.product(otras, ["", " ", "-", ". "], cuerpos + ["273-15", "409-37"]):
        salida.append(f"{otra}{sep}{cuerpo}")
        salida.append(f"LOTE {otra}{sep}{cuerpo}")
    for otra, letra, num in itertools.product(otras, letras, numeros):
        salida.append(f"{otra} {letra} {num}")
        salida.append(f"{otra} 2 LOTE {letra} {num}")
        salida.append(f"ROL 409-37 {otra} {num}")
    salida += ["12/03/2020", "03-12-2020", "2020-03-12", "5,00hás", "5,00 hás", "1.342 m2",
               "1.342,5 m²", "5.000 M2", "0,5 ha", "12 ha", "ROL 273-15", "ROL 409-37 ETAPA 1",
               "SECTOR B 12", "Sector b-12", "A 214", "A214", "a214", "LOTE A 420", "E12",
               "LOTE 8-01", "LOTE-12", "LOTE #12", "Mz 3", "MANZANA 3", "Lote 3A", "3A", "12B",
               "LOTE 12 ETAPA 2", "LOTE A 5 ROL 273-15", "ARRAYÁN 12", "Ñ 3", "1342 M2",
               "12 A 5", "12 A", "LOTEA12", "LOTESA12", "LOTEADORA 12", "PARCELAB3", "LOTE A12"]
    for num, letra, otro in itertools.product(["12", "1.342", "5,00", "3"], letras + ["m", "M", "ha"], numeros):
        salida.append(f"{num} {letra} {otro}")
        salida.append(f"{num}{letra}{otro}")
    salida += [12, 42, 7, 12.0, 42.0, 0.0, 12.5, 3.25]

    azar = random.Random(20261003)
    fragmentos = palabras + otras + letras + separadores + numeros + pares + ["/", ",", ".", "m2", "hás"]
    for _ in range(al_azar):
        salida.append("".join(azar.choice(fragmentos) for _ in range(azar.randint(1, 5))))
    return salida


def _cola_de_palabra(texto: str, viejo: str):
    """La palabra (en mayúsculas) cuya última letra dio el sector `viejo` en la versión
    anterior, o None si esa letra estaba suelta."""
    limpio = re.sub(r"\bLOTES?\b", " ", texto.strip().upper())
    m = re.search(r"([A-Z])\s*0*(\d+)", limpio)
    if not m or f"{m.group(1)}{int(m.group(2))}" != viejo:
        return None
    palabra = re.search(rf"{_LETRA}*$", limpio[:m.end(1)]).group(0)
    return palabra if len(palabra) > 1 else None


def _numero_antes(texto: str, viejo: str) -> bool:
    """Si la letra que dio `viejo` en la versión anterior tenía un número antes (sin
    contar "ETAPA n")."""
    limpio = re.sub(r"\bLOTES?\b", " ", texto.strip().upper())
    m = re.search(r"([A-Z])\s*0*(\d+)", limpio)
    if not m or f"{m.group(1)}{int(m.group(2))}" != viejo:
        return False
    return bool(re.search(r"\d", re.sub(r"\bETAPA\s*\d+", " ", limpio[:m.start()])))


def _como_lote(texto: str) -> str:
    """El texto con PARCELA(S) o SITIO(S) escrito LOTE(S) y la palabra separada del
    número: lo que la versión anterior ya leía bien."""
    t = re.sub(r"\b(?:PARCELA|SITIO)(S?)", r"LOTE\1", texto.upper())
    return re.sub(rf"\b(LOTES?)(?!{_LETRA})", r" \1 ", t)


def clasificar(entrada, viejo, nuevo) -> str | None:
    """El caso aceptado al que pertenece un cambio, o None si no está en la lista."""
    texto = str(entrada)
    if nuevo == _viejo(_como_lote(texto)):
        como_parcela = re.search(r"PARCELA|SITIO", texto.upper())
        return "parcela_como_lote" if como_parcela else "lote_pegado"
    if viejo and nuevo is None and _numero_antes(texto, viejo):
        return "numero_antes_de_la_letra"
    palabra = _cola_de_palabra(texto, viejo) if viejo else None
    if palabra:
        # Ahora None, o la letra suelta que viene después de esa palabra.
        resto = texto.strip().upper()
        resto = resto[resto.find(palabra) + len(palabra):]
        despues = re.search(rf"(?<!{_LETRA})([A-Z])(?!{_LETRA})\s*0*(\d+)", resto)
        if nuevo is None or (despues and nuevo == f"{despues.group(1)}{int(despues.group(2))}"):
            return ("palabra_de_lote_con_otras_palabras" if palabra in _PALABRAS_DE_LOTE
                    else "cola_de_otra_palabra")
    return None


def cambios(entradas) -> list[tuple]:
    """(entrada, viejo, nuevo, caso) de cada entrada cuya salida cambia."""
    salida = []
    for e in entradas:
        v, n = _viejo(e), normalizar_id(e)
        if v != n:
            salida.append((e, v, n, clasificar(e, v, n)))
    return salida


def test_cada_cambio_esta_en_la_lista_aceptada():
    lista = cambios(corpus())
    fuera = [c for c in lista if c[3] is None]
    assert not fuera, f"{len(fuera)} cambios fuera de la lista, p. ej. {fuera[:10]}"
    # El corpus ejercita todos los casos (si no, la prueba no prueba nada).
    assert {c[3] for c in lista} == set(CASOS)


def test_lo_que_no_es_esos_casos_no_cambia():
    for entrada in ["A214", "A 214", "LOTE A 420", "SECTOR B 12", "E12", "7-1", "LOTE 8-01",
                    "LOTE-12", "LOTE #12", 12.0, "12/03/2020", "5,00hás", "LOTEA12",
                    "Sitio A 12", "SITIOA12"]:
        assert normalizar_id(entrada) == _viejo(entrada)
