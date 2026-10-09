"""Poner al día el visor de los loteos ya publicados, al arrancar la consola.

Cada loteo en línea lleva su propia copia del visor, hecha al construirlo: un
arreglo mergeado no llega a ninguno hasta que alguien lo vuelve a subir. Esto lo
hace solo: compara la huella del visor actual con la que quedó anotada al
publicar cada loteo y republica los que quedaron atrás.

Solo los que ya están en línea, pagados y construidos: nunca pone en línea uno
que hoy no lo está, ni crea proyectos en el hosting. Va de a uno y por los mismos
`Trabajos` que usan las rutas, así que respeta el bloqueo por loteo. Lo que pasa
se escribe en el log del proceso, que en Cloud Run va a Cloud Logging: no hay
pantalla para esto.

Si la instancia se recicla a mitad de camino no se pierde nada: los hechos
quedaron anotados y el próximo arranque sigue con los que faltan.
"""
from __future__ import annotations

import json

from .proyectos import Proyecto, Vista

PREFIJO = "[republicar]"

# Un loteo no debería tardar ni cerca de esto en subirse; si pasa, se deja
# corriendo y se sigue con los demás en vez de quedarse pegado para siempre.
TOPE_POR_LOTEO = 30 * 60


def pendientes(vista: Vista, huella: str) -> list[Proyecto]:
    """Los publicados, pagados y construidos cuyo visor no es el actual (o no se sabe)."""
    return sorted((p for p in vista.listar()
                   if p.publicado and p.pagado and p.construido
                   and p.visor_publicado != huella),
                  key=lambda p: p.slug)


def republicar(vista: Vista, trabajos, comandos, disenos, huella: str,
               avisar=print) -> dict:
    """Recorre los pendientes de a uno. Un loteo que falla no detiene a los demás.

    Devuelve cuántos quedaron hechos, cuántos fallaron y cuántos se saltaron:
    lo que se escribe al final en el log, y lo que miran las pruebas.
    """
    def decir(texto: str) -> None:
        avisar(f"{PREFIJO} {texto}")

    cuenta = {"hechos": 0, "fallidos": 0, "saltados": 0}
    lista = pendientes(vista, huella)
    decir(f"{len(lista)} loteo(s) con un visor distinto de {huella[:12]}")
    for proyecto in lista:
        try:
            resultado = _uno(vista, trabajos, comandos, disenos, huella, proyecto, decir)
        except Exception as error:          # noqa: BLE001 - que siga con los demás
            decir(f"{proyecto.slug}: error inesperado ({error!r})")
            resultado = "fallidos"
        cuenta[resultado] += 1
    decir(f"listo: {cuenta['hechos']} al día, {cuenta['fallidos']} fallaron, "
          f"{cuenta['saltados']} saltados")
    return cuenta


def _uno(vista: Vista, trabajos, comandos, disenos, huella: str,
         proyecto: Proyecto, decir) -> str:
    slug = proyecto.slug
    # Sin el nombre en el hosting no hay a dónde subirlo, y adivinarlo con
    # `--crear` podría dejar un sitio nuevo en una URL que nadie conoce.
    if not proyecto.vercel_proyecto:
        decir(f"{slug}: publicado sin nombre de proyecto en el hosting; se salta")
        return "saltados"
    if trabajos.corriendo(slug):
        decir(f"{slug}: tiene un trabajo en curso; queda para el próximo arranque")
        return "saltados"

    # El diseño va como está hoy, igual que al publicar a mano.
    disenos.escribir_en_sitio(proyecto.diseno_id, proyecto.salida.datos)
    try:
        # Copiar el visor y subirlo es liviano: no espera en la cola de las construcciones.
        identificador = trabajos.lanzar(
            slug, "actualizar-visor",
            comandos.actualizar_visor(proyecto, proyecto.vercel_proyecto), pesado=False)
    except RuntimeError:
        # Alguien lanzó algo entre la pregunta de arriba y ahora.
        decir(f"{slug}: tiene un trabajo en curso; queda para el próximo arranque")
        return "saltados"

    decir(f"{slug}: actualizando el visor en {proyecto.vercel_proyecto}")
    trabajo = trabajos.esperar(identificador, tope=TOPE_POR_LOTEO)
    if trabajo.estado != "listo":
        ultima = trabajo.lineas[-1] if trabajo.lineas else ""
        estado = trabajo.estado if trabajo.terminado else "sigue corriendo"
        decir(f"{slug}: {estado} (código {trabajo.codigo}) {ultima}".rstrip())
        return "fallidos"

    # La URL que devolvió el hosting, no la que suponemos.
    rastro = proyecto.salida.base / "publicacion.json"
    datos = json.loads(rastro.read_text(encoding="utf-8")) if rastro.is_file() else {}
    url = datos.get("url") or proyecto.url_publicada
    vista.anotar_publicacion(slug, vercel_proyecto=datos.get("proyecto") or proyecto.vercel_proyecto,
                             url=url)
    vista.anotar_visor(slug, huella)
    decir(f"{slug}: al día en {url}")
    return "hechos"
