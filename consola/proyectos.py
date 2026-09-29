"""Los loteos que conoce la consola.

Un loteo es una carpeta con el KMZ, las panorámicas y un `proyecto.json`. Puede
venir de dos lados: subida desde el navegador (se guarda en `proyectos/<slug>/`) o
una carpeta que ya está en el disco, que se vincula sin copiar nada —las
panorámicas pesan cientos de megas y no tiene sentido duplicarlas.

De quién es cada loteo lo dice la base; qué hay construido lo dicen sus archivos.
Esa división importa: el avance nunca se guarda, se mira, y así la consola no
puede mentir sobre lo que existe.

**Las rutas no usan `Registro` directo.** Piden `registro.para(sesion)` y reciben
una `Vista` que solo alcanza los loteos de esa loteadora. El cliente no es un
argumento que se pueda olvidar: es parte de quién creó la vista.
"""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from pipeline import config

from .acceso import Sesion
from .datos import Base, NoEncontrado, ProyectoGuardado
from .portada import portada

CARPETA_SUBIDAS = config.DATOS / "proyectos"

EXTENSIONES_FOTO = (".jpg", ".jpeg")

# La planilla de precios y estados, cuando llega por el campo "Inventario" y no
# dentro de la carpeta del vuelo. El pipeline la busca por este nombre.
INVENTARIO_CSV = "inventario.csv"

# Lo que se guarda en `proyecto.json`, que es lo que lee el pipeline. El resto
# —de quién es, dónde quedó publicado— vive en la base y no se duplica acá.
CAMPOS_DEL_PIPELINE = ("nombre", "etapa", "whatsapp", "parcelacion", "despegue", "referencias")


MEGA = 1024 * 1024


@dataclass(frozen=True)
class Limites:
    """Cuánto puede gastar una loteadora antes de pagar.

    Crear un master ya no exige pago, así que sin topes cualquier cuenta podría
    llenar el disco o tener el servidor construyendo para nada. No aplican al
    equipo de CTP.
    """
    # Masters sin pagar que puede tener a la vez.
    sin_pagar: int = 3
    # Lo que puede ocupar un loteo subido. Un vuelo real pesa entre 200 MB y
    # 1,5 GB (panorámicas de ~65 MB); 3 GB deja holgura sin dejar la puerta abierta.
    megas_por_loteo: int = 3072
    # Construcciones corriendo a la vez. El servidor tiene 2 CPU: una por
    # cliente deja lugar a otro.
    construcciones: int = 1

    @classmethod
    def desde_el_entorno(cls) -> Limites:
        def entero(nombre: str, defecto: int) -> int:
            valor = os.environ.get(nombre, "").strip()
            return int(valor) if valor else defecto
        return cls(
            sin_pagar=entero("CONSOLA_MAX_SIN_PAGAR", cls.sin_pagar),
            megas_por_loteo=entero("CONSOLA_MAX_MEGAS_POR_LOTEO", cls.megas_por_loteo),
            construcciones=entero("CONSOLA_MAX_CONSTRUCCIONES", cls.construcciones),
        )


class LimiteAlcanzado(Exception):
    """Lo que se pidió pasa un tope de `Limites`. El mensaje es para la persona."""


@dataclass(frozen=True)
class Subida:
    """Un archivo que llega del navegador, con su ruta relativa dentro de la carpeta.

    El contenido puede ser bytes o un archivo abierto: una panorámica pesa ~65 MB
    y un vuelo entero cientos, así que en el servidor se copia del temporal al
    destino sin cargarlo en memoria.
    """
    ruta: str
    contenido: bytes | BinaryIO
    tamano: int | None = None

    @property
    def bytes(self) -> int:
        if self.tamano is not None:
            return self.tamano
        if isinstance(self.contenido, bytes):
            return len(self.contenido)
        posicion = self.contenido.tell()
        self.contenido.seek(0, os.SEEK_END)
        total = self.contenido.tell()
        self.contenido.seek(posicion)
        return total

    def guardar(self, destino: Path) -> None:
        if isinstance(self.contenido, bytes):
            destino.write_bytes(self.contenido)
            return
        self.contenido.seek(0)
        with destino.open("wb") as salida:
            shutil.copyfileobj(self.contenido, salida, length=4 * MEGA)


@dataclass(frozen=True)
class Proyecto:
    slug: str
    nombre: str
    etapa: str
    whatsapp: str
    despegue: tuple[float, float] | None
    referencias: tuple
    fuentes: Path
    salida: config.Salida
    # El export comercial de ESTE cliente, si lo tiene. Nunca uno global: un
    # cliente sin planilla no puede terminar leyendo los precios de otro.
    crm: Path | None = None
    # Cómo se llama el loteo en el hosting y dónde quedó. Se guardan al publicar
    # por primera vez, leídos de lo que respondió el hosting: adivinarlos era lo
    # que hacía que dos clientes con el mismo nombre se pisaran el sitio.
    vercel_proyecto: str | None = None
    url_publicada: str | None = None
    # Sin pago se puede subir y construir, pero no publicar.
    pagado: bool = True
    # Subido desde el navegador (sus archivos son nuestros) o carpeta vinculada
    # del disco (no lo son).
    subido: bool = False
    # El nombre del loteo en el CRM tal como se escribió. Vacío es "el nombre en
    # mayúsculas", que es lo que asume el pipeline; no se rellena acá para que
    # renombrar el loteo no deje pegado el nombre viejo.
    parcelacion: str = ""
    # De quién es, y con qué marca se publica (None = la de Tu Masterplan).
    cliente_id: int = 0
    diseno_id: int | None = None
    # La huella del visor con que quedó publicado; None si nunca se anotó.
    visor_publicado: str | None = None

    @property
    def publicado(self) -> bool:
        return bool(self.url_publicada)

    @property
    def construido(self) -> bool:
        return (self.salida.datos / "parcelas.json").is_file()

    def resumen(self) -> dict:
        """Lo que quedó de la última construcción, leído de su propia salida."""
        archivo = self.salida.datos / "parcelas.json"
        if not archivo.is_file():
            return {}
        datos = json.loads(archivo.read_text(encoding="utf-8"))
        vistas = json.loads((self.salida.datos / "vistas.json").read_text(encoding="utf-8"))
        por_estado = datos["resumen"]["por_estado"]
        return {
            "generado": datos.get("generado"),
            "parcelas": datos["resumen"]["total"],
            "por_estado": por_estado,
            "disponibles": por_estado.get("disponible", 0),
            "precio_desde": precio_desde(datos.get("parcelas", [])),
            "vistas": len(vistas["vistas"]),
            "calce": [
                {"vista": v["id"], "error_sol": v["diagnostico"]["error_elevacion"],
                 "mejora": v["diagnostico"].get("calibracion", {}).get("mejora", 0)}
                for v in vistas["vistas"]
            ],
        }

    def portada(self) -> Path | None:
        return portada(self.salida)

    def control_de_calce(self) -> list[str]:
        if not self.salida.qa.is_dir():
            return []
        return sorted(p.name for p in self.salida.qa.glob("*.jpg"))

    def fuentes_encontradas(self) -> dict:
        """Qué hay en la carpeta, para mostrarlo antes de construir.

        Las fotos repetidas se cuentan una vez: el volcado de la tarjeta suele dejar
        la misma toma en dos carpetas y el pipeline también la toma una sola vez.
        Acá alcanza con mirar nombre y tamaño; el pipeline, que sí tiene que acertar,
        compara la hora, el GPS y la altura del XMP.
        """
        if not self.fuentes.is_dir():
            return {"kmz": None, "panoramicas": 0, "megas": 0, "planilla": None}
        kmz = sorted(p.name for p in self.fuentes.rglob("*.kmz"))
        planillas = sorted(p.name for p in self.fuentes.rglob("*.xlsx") if not p.name.startswith("~$"))
        if not planillas and (self.fuentes / INVENTARIO_CSV).is_file():
            planillas = [INVENTARIO_CSV]
        fotos: dict[tuple[str, int], int] = {}
        for ruta in self.fuentes.rglob("*"):
            if ruta.suffix.lower() in EXTENSIONES_FOTO:
                tamano = ruta.stat().st_size
                fotos[(ruta.name, tamano)] = tamano
        return {
            "kmz": kmz[0] if kmz else None,
            "panoramicas": len(fotos),
            "megas": round(sum(fotos.values()) / 1048576),
            "planilla": planillas[0] if planillas else None,
        }


class Registro:
    """Todos los loteos del sistema, y dónde viven sus archivos.

    Las rutas no lo usan directo salvo el back-office: piden `para(sesion)`.
    """

    def __init__(self, base: Base, subidas: Path = CARPETA_SUBIDAS,
                 salidas: Path = config.SALIDAS, crm_por_defecto: Path | None = None,
                 limites: Limites | None = None):
        self.base = base
        self.limites = limites or Limites()
        self.subidas = Path(subidas)
        self.salidas = Path(salidas)
        # Un export comercial para los loteos que no traen el suyo. Tiene sentido
        # en el computador del dueño, donde hay un solo dueño; en el servidor se
        # deja en None para que nadie herede los precios de otro.
        self.crm_por_defecto = Path(crm_por_defecto) if crm_por_defecto else None

    def para(self, sesion: Sesion) -> Vista:
        """Los loteos que esta sesión puede tocar. Plataforma los ve todos."""
        return Vista(registro=self, duenio=sesion.cliente_id,
                     filtro=None if sesion.es_plataforma else sesion.cliente_id)

    def todos(self) -> Vista:
        """Todos los loteos, sin sesión: para los trabajos internos de la consola
        (como poner al día el visor al arrancar). Nunca para una ruta: ahí manda
        `para(sesion)`.

        No crea ni vincula loteos: no hay nadie a cuyo nombre dejarlos.
        """
        return _VistaInterna(registro=self, duenio=0, filtro=None)

    # --- alta de un loteo --------------------------------------------------------

    def habilitar(self, cliente_id: int, nombre: str, *,
                  nota_cobro: str | None = None) -> Proyecto:
        """Le da de alta un loteo a una loteadora, ya pagado. Lo usa el back-office."""
        return self._nacer(cliente_id, nombre, nota_cobro=nota_cobro, pagado=True)

    def crear(self, cliente_id: int, nombre: str) -> Proyecto:
        """El loteo que se crea el propio cliente: nace sin pagar.

        Puede subir, construir y mirar el resultado cuantas veces quiera. El cobro
        se controla en un solo lugar, al publicar, que es cuando el loteo empieza
        a servirle a alguien más que a quien lo armó.
        """
        return self._nacer(cliente_id, nombre, pagado=False)

    def _nacer(self, cliente_id: int, nombre: str, *, pagado: bool,
               nota_cobro: str | None = None) -> Proyecto:
        guardado = self.base.crear_proyecto(cliente_id, nombre, nota_cobro=nota_cobro,
                                            pagado=pagado)
        carpeta = self.subidas / guardado.slug
        carpeta.mkdir(parents=True, exist_ok=True)
        self._escribir_json(carpeta, guardado.slug, {"nombre": nombre})
        return self._leer(guardado)

    # --- interno, compartido con las vistas ------------------------------------

    def _leer(self, guardado: ProyectoGuardado) -> Proyecto:
        carpeta = (Path(guardado.carpeta) if guardado.carpeta
                   else self.subidas / guardado.slug)
        datos = config.cargar_proyecto(carpeta)
        return Proyecto(
            slug=guardado.slug,
            nombre=guardado.nombre,
            etapa=datos.etapa,
            whatsapp=datos.whatsapp,
            parcelacion=str(_leer_json(carpeta / "proyecto.json").get("parcelacion") or ""),
            despegue=datos.despegue,
            referencias=datos.referencias,
            fuentes=carpeta,
            salida=config.Salida(self.salidas / guardado.slug),
            crm=self._crm_de(carpeta),
            vercel_proyecto=guardado.vercel_proyecto,
            url_publicada=guardado.url_publicada,
            pagado=guardado.pagado,
            subido=guardado.carpeta is None,
            cliente_id=guardado.cliente_id,
            diseno_id=guardado.diseno_id,
            visor_publicado=guardado.visor_publicado,
        )

    def _escribir_json(self, carpeta: Path, slug: str, campos: dict) -> None:
        """Deja en la carpeta lo que el pipeline necesita leer, sin tocar lo demás."""
        archivo = carpeta / "proyecto.json"
        datos = _leer_json(archivo)
        datos.update(campos)
        datos["slug"] = slug
        archivo.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")

    def _crm_de(self, carpeta: Path) -> Path | None:
        propio = carpeta / "crm.csv"
        if propio.is_file():
            return propio
        return (self.crm_por_defecto
                if self.crm_por_defecto and self.crm_por_defecto.is_file() else None)


@dataclass(frozen=True)
class Vista:
    """El registro visto por alguien.

    `filtro` es de quién puede ver (None = todos, para el equipo de CTP) y `duenio`
    de quién queda lo que cree. Son distintos a propósito: un operador de CTP mira
    los loteos de cualquiera, pero los que sube quedan a nombre de CTP.
    """
    registro: Registro
    duenio: int
    filtro: int | None

    # --- lectura -------------------------------------------------------------

    def listar(self) -> list[Proyecto]:
        return [self.registro._leer(g)
                for g in self.registro.base.proyectos(cliente_id=self.filtro)]

    def ver(self, slug: str) -> Proyecto:
        """El loteo, o `NoEncontrado` si no existe o no es suyo. No se distingue:
        decir "existe pero no es tuyo" ya es contar algo."""
        return self.registro._leer(self.registro.base.proyecto(slug, cliente_id=self.filtro))

    # --- alta y archivos --------------------------------------------------------

    @property
    def es_equipo(self) -> bool:
        """El equipo de CTP ve todo y no tiene topes."""
        return self.filtro is None

    def crear(self, nombre: str) -> Proyecto:
        """Un loteo nuevo a nombre de quien lo crea, todavía sin pagar."""
        tope = self.registro.limites.sin_pagar
        if not self.es_equipo:
            sin_pagar = [g for g in self.registro.base.proyectos(cliente_id=self.duenio)
                         if not g.pagado]
            if len(sin_pagar) >= tope:
                raise LimiteAlcanzado(
                    f"ya tienes {len(sin_pagar)} masters sin habilitar, que es el máximo. "
                    "Quita uno que no uses o escríbenos para habilitar alguno")
        return self.registro.crear(self.duenio, nombre)

    def subir(self, slug: str, archivos: list[Subida]) -> Proyecto:
        """Guarda los archivos del vuelo dentro de un loteo que ya existe.

        Se puede subir de nuevo para agregar lo que faltó. El tope de tamaño se
        mira antes de escribir nada: una subida que no cabe no deja medio vuelo.
        """
        proyecto = self.ver(slug)
        carpeta = proyecto.fuentes
        destinos = [(archivo, _destino_seguro(carpeta, archivo.ruta)) for archivo in archivos]
        if not self.es_equipo:
            self._revisar_tamano(carpeta, destinos)
        carpeta.mkdir(parents=True, exist_ok=True)
        for archivo, destino in destinos:
            destino.parent.mkdir(parents=True, exist_ok=True)
            archivo.guardar(destino)
        # El KMZ puede venir en esta tanda o de una anterior; lo que no puede es
        # faltar, porque sin él no hay nada que proyectar.
        if not any(carpeta.rglob("*.kmz")):
            raise ValueError("falta el KMZ del loteo entre los archivos")
        return self.ver(slug)

    def vincular(self, carpeta: Path) -> Proyecto:
        """Registra una carpeta que ya está en el disco, sin copiar nada.

        Solo tiene sentido en el computador donde están las fotos; la consola
        desplegada no la ofrece, porque sería leer cualquier ruta del servidor.
        """
        carpeta = Path(carpeta).expanduser().resolve()
        if not carpeta.is_dir():
            raise FileNotFoundError(f"no existe la carpeta {carpeta}")
        if not any(carpeta.rglob("*.kmz")):
            raise ValueError(f"no encontré el KMZ del loteo dentro de {carpeta.name}")

        ya = self._por_carpeta(carpeta)
        if ya is not None:
            return self.registro._leer(ya)

        datos = config.cargar_proyecto(carpeta)
        # Si la carpeta ya trae slug, se respeta: es un loteo construido y quizá
        # publicado, y cambiárselo dejaría su sitio colgando. Lo mismo con dónde
        # quedó publicado: la carpeta se describe a sí misma, así que adoptarla
        # devuelve el loteo entero aunque la base se hubiera perdido.
        suyo = _leer_json(carpeta / "proyecto.json")
        guardado = self.registro.base.crear_proyecto(
            self.duenio, datos.nombre, slug=datos.slug_guardado or None, carpeta=str(carpeta),
            vercel_proyecto=suyo.get("vercel_proyecto") or None,
            url_publicada=suyo.get("url_publicada") or None)
        self.registro._escribir_json(carpeta, guardado.slug, {})
        return self.registro._leer(guardado)

    # --- edición -------------------------------------------------------------

    def ajustar(self, slug: str, campos: dict) -> Proyecto:
        """Reescribe `proyecto.json` con lo que venga, dejando el resto como estaba.

        El slug no cambia aunque cambie el nombre: es la carpeta de salida y la URL
        publicada, y renombrarlo dejaría el sitio anterior colgando.
        """
        proyecto = self.ver(slug)
        limpios = {c: v for c, v in campos.items() if v is not None and c in CAMPOS_DEL_PIPELINE}
        if "nombre" in limpios:
            self.registro.base.renombrar_proyecto(slug, str(limpios["nombre"]))
        self.registro._escribir_json(proyecto.fuentes, slug, limpios)
        return self.ver(slug)

    def asignar_diseno(self, slug: str, diseno_id: int | None) -> Proyecto:
        """Con qué marca se publica. Quién puede usar qué diseño lo decide
        `VistaDisenos.para_el_loteo`; acá solo se anota."""
        self.ver(slug)
        self.registro.base.asignar_diseno(slug, diseno_id)
        return self.ver(slug)

    def anotar_publicacion(self, slug: str, *, vercel_proyecto: str, url: str) -> Proyecto:
        """Guarda con qué nombre y en qué URL quedó publicado el loteo.

        Se escribe en los dos lados: la base es de donde se lee, y la copia en la
        carpeta es lo que permite volver a adoptar el loteo con su identidad si
        algún día hay que rehacer la base.
        """
        proyecto = self.ver(slug)
        self.registro.base.anotar_publicacion(slug, vercel_proyecto, url)
        self.registro._escribir_json(proyecto.fuentes, slug,
                                     {"vercel_proyecto": vercel_proyecto, "url_publicada": url})
        return self.ver(slug)

    def anotar_visor(self, slug: str, huella: str) -> Proyecto:
        """Con qué visor quedó publicado el loteo. Solo en la base: la carpeta no
        necesita saberlo para volver a adoptar el loteo."""
        self.ver(slug)
        self.registro.base.anotar_visor(slug, huella)
        return self.ver(slug)

    def olvidar(self, slug: str) -> None:
        """Saca el loteo de la lista.

        Una carpeta vinculada o un loteo pagado conservan sus archivos: la
        carpeta no es nuestra, y lo pagado quizá está publicado. Un master subido
        y sin pagar se borra entero; si no, quitarlo de la lista sería la forma
        de saltarse el tope de masters sin pagar llenando el disco igual.
        """
        proyecto = self.ver(slug)
        self.registro.base.olvidar_proyecto(slug)
        if proyecto.subido and not proyecto.pagado:
            shutil.rmtree(proyecto.fuentes, ignore_errors=True)
            shutil.rmtree(proyecto.salida.base, ignore_errors=True)

    # --- interno -------------------------------------------------------------

    def _revisar_tamano(self, carpeta: Path, destinos: list[tuple[Subida, Path]]) -> None:
        """Lo que queda en la carpeta después de subir, contando lo que se pisa una vez."""
        tope = self.registro.limites.megas_por_loteo * MEGA
        pisados = {destino for _, destino in destinos}
        ya = sum(p.stat().st_size for p in carpeta.rglob("*")
                 if p.is_file() and p not in pisados) if carpeta.is_dir() else 0
        nuevo = sum(archivo.bytes for archivo, _ in destinos)
        if ya + nuevo > tope:
            raise LimiteAlcanzado(
                f"el loteo quedaría en {round((ya + nuevo) / MEGA)} MB y el máximo es "
                f"{self.registro.limites.megas_por_loteo} MB. Sube solo las panorámicas "
                "del vuelo, sin videos ni fotos sueltas")

    def _por_carpeta(self, carpeta: Path) -> ProyectoGuardado | None:
        for guardado in self.registro.base.proyectos(cliente_id=self.filtro):
            if guardado.carpeta and Path(guardado.carpeta) == carpeta:
                return guardado
        return None


class _VistaInterna(Vista):
    """La de `Registro.todos()`: ve todo y no da de alta nada."""

    def crear(self, nombre: str) -> Proyecto:
        raise TypeError("la vista interna no crea loteos")

    def vincular(self, carpeta: Path) -> Proyecto:
        raise TypeError("la vista interna no vincula loteos")


def _leer_json(archivo: Path) -> dict:
    return json.loads(archivo.read_text(encoding="utf-8")) if archivo.is_file() else {}


def _destino_seguro(carpeta: Path, relativa: str) -> Path:
    """Impide que un nombre con `..` escriba fuera de la carpeta del proyecto."""
    destino = (carpeta / relativa).resolve()
    if carpeta.resolve() not in destino.parents:
        raise ValueError(f"ruta inválida en la subida: {relativa!r}")
    return destino


def precio_desde(parcelas: list[dict]) -> dict | None:
    """El precio más bajo entre las parcelas disponibles, o None si no hay ninguno.

    Pesos y UF no se comparan entre sí: si el loteo mezcla monedas, manda la que
    tiene más parcelas disponibles con precio, que es la que el comprador va a ver
    más en el visor.
    """
    por_moneda: dict[str, list[float]] = {}
    for parcela in parcelas:
        precio = parcela.get("precio")
        if parcela.get("estado") != "disponible" or not precio:
            continue
        por_moneda.setdefault(parcela.get("moneda") or "CLP", []).append(float(precio))
    if not por_moneda:
        return None
    moneda, precios = max(por_moneda.items(), key=lambda par: len(par[1]))
    return {"monto": min(precios), "moneda": moneda}


def fecha_legible(iso: str | None) -> str:
    if not iso:
        return ""
    return datetime.fromisoformat(iso).strftime("%d/%m/%Y %H:%M")


__all__ = ["CARPETA_SUBIDAS", "INVENTARIO_CSV", "LimiteAlcanzado", "Limites", "NoEncontrado", "Proyecto", "Registro", "Subida", "Vista",
           "fecha_legible", "precio_desde"]
