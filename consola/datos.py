"""La base de la consola: quién es cliente, quién entra y qué loteo es de quién.

Son cuatro tablas y un puñado de consultas, así que se usa SQLAlchemy Core y no el
ORM: no hace falta identidad de objetos ni carga perezosa, y el SQL queda a la vista.
Corre igual sobre SQLite (este computador y las pruebas) y sobre Postgres (el
servidor), que es lo único que se le pide.

**No hay RLS.** Cierra sí lo usa, y ahí corresponde: son 41 tablas y decenas de rutas
donde olvidar un filtro es cuestión de tiempo. Acá el aislamiento se logra con un solo
lugar que filtra —este módulo— y una consulta que no acepta buscar sin decir de quién.
Un proyecto de otro cliente no da "prohibido" sino `NoEncontrado`: decir "existe pero
no es tuyo" ya es contar algo.
"""
from __future__ import annotations

import os
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone

from passlib.context import CryptContext
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, MetaData, String, Table,
    Text, UniqueConstraint, create_engine, delete, func, insert, select, update,
)
from sqlalchemy.exc import IntegrityError

CLAVES = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Sin caracteres que se confundan al dictarla por teléfono.
ALFABETO_CLAVE = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
LARGO_CLAVE = 14

ROLES = ("plataforma", "dueño", "equipo")

metadatos = MetaData()

clientes = Table(
    "clientes", metadatos,
    Column("id", Integer, primary_key=True),
    Column("slug", String(60), nullable=False, unique=True),
    Column("nombre", String(160), nullable=False),
    Column("estado", String(20), nullable=False, default="activo"),
    Column("creado_en", DateTime(timezone=True), nullable=False),
)

usuarios = Table(
    "usuarios", metadatos,
    Column("id", Integer, primary_key=True),
    # Siempre apunta a un cliente real, incluso el equipo de CTP. Un NULL que
    # significara "plataforma" es la forma clásica de que una comparación de
    # propiedad falle abierta.
    Column("cliente_id", Integer, ForeignKey("clientes.id"), nullable=False, index=True),
    Column("email", String(200), nullable=False, unique=True),
    Column("nombre", String(160), nullable=False),
    Column("clave_hash", String(200), nullable=False),
    Column("rol", String(20), nullable=False, default="equipo"),
    Column("activo", Boolean, nullable=False, default=True),
    Column("debe_cambiar_clave", Boolean, nullable=False, default=True),
    # Revocación sin tabla de sesiones: una galleta firmada antes de esta marca
    # deja de valer. Cambiar la clave o desactivar al usuario la adelanta.
    Column("sesiones_validas_desde", DateTime(timezone=True), nullable=False),
    Column("creado_en", DateTime(timezone=True), nullable=False),
)

proyectos = Table(
    "proyectos", metadatos,
    Column("id", Integer, primary_key=True),
    Column("cliente_id", Integer, ForeignKey("clientes.id"), nullable=False, index=True),
    # Único en TODO el sistema, no por cliente: también es el nombre del proyecto
    # en el hosting y el de su carpeta de salida.
    Column("slug", String(80), nullable=False, unique=True),
    Column("nombre", String(160), nullable=False),
    # De dónde salen las fuentes. Vacío significa "lo que subieron", que vive en
    # `proyectos/<slug>/` y se arma con el slug; una ruta absoluta es una carpeta
    # que ya estaba en el disco y se vinculó sin copiar. Se guarda solo en ese
    # caso para que la base siga sirviendo si los datos cambian de lugar.
    Column("carpeta", Text, nullable=True),
    Column("vercel_proyecto", String(120), nullable=True, unique=True),
    Column("url_publicada", String(300), nullable=True),
    Column("publicado_en", DateTime(timezone=True), nullable=True),
    # El cobro: un hecho con fecha, no un estado. El resto del avance (construido,
    # publicado) se deduce de los archivos, que nunca mienten.
    Column("pagado_en", DateTime(timezone=True), nullable=True),
    Column("nota_cobro", Text, nullable=True),
    Column("creado_en", DateTime(timezone=True), nullable=False),
    UniqueConstraint("cliente_id", "nombre", name="un_nombre_por_cliente"),
)

eventos = Table(
    "eventos", metadatos,
    Column("id", Integer, primary_key=True),
    Column("cliente_id", Integer, ForeignKey("clientes.id"), nullable=True, index=True),
    Column("usuario_id", Integer, ForeignKey("usuarios.id"), nullable=True),
    Column("que", String(60), nullable=False),
    Column("detalle", Text, nullable=True),
    Column("cuando", DateTime(timezone=True), nullable=False),
)


class ClienteYaExiste(Exception):
    """Ya hay una loteadora con ese nombre."""


class EmailYaExiste(Exception):
    """Ese correo ya tiene cuenta, en esta loteadora o en otra."""


class ProyectoYaExiste(Exception):
    """Este cliente ya tiene un loteo con ese nombre."""


class NoEncontrado(Exception):
    """No existe, o no es de quien pregunta. A propósito no se distingue."""


@dataclass(frozen=True)
class Cliente:
    id: int
    slug: str
    nombre: str
    estado: str
    creado_en: datetime


@dataclass(frozen=True)
class Usuario:
    id: int
    cliente_id: int
    email: str
    nombre: str
    clave_hash: str
    rol: str
    activo: bool
    debe_cambiar_clave: bool
    sesiones_validas_desde: datetime

    @property
    def es_plataforma(self) -> bool:
        return self.rol == "plataforma"


@dataclass(frozen=True)
class ProyectoGuardado:
    id: int
    cliente_id: int
    slug: str
    nombre: str
    carpeta: str | None
    vercel_proyecto: str | None
    url_publicada: str | None
    publicado_en: datetime | None
    pagado_en: datetime | None
    nota_cobro: str | None

    @property
    def pagado(self) -> bool:
        return self.pagado_en is not None


class Base:
    def __init__(self, url: str | None = None):
        url = url or url_por_defecto()
        # El pool va corto a propósito: en el servidor esta base comparte instancia
        # con la de Cierra, que ya se quedó una vez sin conexiones por no acotarlo.
        # SQLite no tiene pool que configurar.
        opciones = {} if url.startswith("sqlite") else {"pool_size": 2, "max_overflow": 2}
        self.motor = create_engine(url, future=True, **opciones)
        metadatos.create_all(self.motor)

    # --- clientes ---------------------------------------------------------------

    def clientes(self) -> list[Cliente]:
        with self.motor.connect() as con:
            return [_cliente(f) for f in con.execute(select(clientes).order_by(clientes.c.slug))]

    def cliente(self, cliente_id: int) -> Cliente:
        with self.motor.connect() as con:
            fila = con.execute(select(clientes).where(clientes.c.id == cliente_id)).first()
        if fila is None:
            raise NoEncontrado(f"no existe el cliente {cliente_id}")
        return _cliente(fila)

    def crear_cliente(self, nombre: str, email_duenio: str,
                      nombre_duenio: str) -> tuple[Cliente, str]:
        """Crea la loteadora y su dueño. Devuelve la clave provisional, que se
        muestra una sola vez y no vuelve a estar disponible."""
        ahora = _ahora()
        clave = _clave_provisional()
        with self.motor.begin() as con:
            if con.execute(select(usuarios.c.id)
                           .where(func.lower(usuarios.c.email) == email_duenio.lower())).first():
                raise EmailYaExiste(f"{email_duenio} ya tiene cuenta")
            try:
                cliente_id = con.execute(insert(clientes).values(
                    slug=_slug(nombre), nombre=nombre.strip(),
                    estado="activo", creado_en=ahora)).inserted_primary_key[0]
            except IntegrityError as error:
                raise ClienteYaExiste(f"ya hay una loteadora llamada {nombre!r}") from error
            con.execute(insert(usuarios).values(
                cliente_id=cliente_id, email=email_duenio.strip().lower(),
                nombre=nombre_duenio.strip(), clave_hash=CLAVES.hash(clave),
                rol="dueño", activo=True, debe_cambiar_clave=True,
                sesiones_validas_desde=ahora, creado_en=ahora))
        return self.cliente(cliente_id), clave

    def suspender(self, cliente_id: int) -> None:
        self._estado_cliente(cliente_id, "suspendido")

    def reactivar(self, cliente_id: int) -> None:
        self._estado_cliente(cliente_id, "activo")

    # --- usuarios ----------------------------------------------------------------

    def usuario_por_email(self, email: str) -> Usuario | None:
        with self.motor.connect() as con:
            fila = con.execute(select(usuarios)
                               .where(func.lower(usuarios.c.email) == email.strip().lower())).first()
        return _usuario(fila) if fila else None

    def usuario(self, usuario_id: int) -> Usuario | None:
        with self.motor.connect() as con:
            fila = con.execute(select(usuarios).where(usuarios.c.id == usuario_id)).first()
        return _usuario(fila) if fila else None

    def usuarios_de(self, cliente_id: int) -> list[Usuario]:
        with self.motor.connect() as con:
            return [_usuario(f) for f in con.execute(
                select(usuarios).where(usuarios.c.cliente_id == cliente_id)
                .order_by(usuarios.c.email))]

    def crear_usuario(self, cliente_id: int, email: str, nombre: str,
                      rol: str = "equipo") -> tuple[Usuario, str]:
        """Una cuenta más dentro de una loteadora que ya existe."""
        if rol not in ROLES:
            raise ValueError(f"rol desconocido: {rol!r}")
        ahora = _ahora()
        clave = _clave_provisional()
        with self.motor.begin() as con:
            if con.execute(select(usuarios.c.id)
                           .where(func.lower(usuarios.c.email) == email.strip().lower())).first():
                raise EmailYaExiste(f"{email} ya tiene cuenta")
            con.execute(insert(usuarios).values(
                cliente_id=cliente_id, email=email.strip().lower(), nombre=nombre.strip(),
                clave_hash=CLAVES.hash(clave), rol=rol, activo=True,
                debe_cambiar_clave=True, sesiones_validas_desde=ahora, creado_en=ahora))
        encontrado = self.usuario_por_email(email)
        assert encontrado is not None
        return encontrado, clave

    def clave_valida(self, usuario: Usuario, intento: str) -> bool:
        return CLAVES.verify(intento, usuario.clave_hash) if intento else False

    def verificar_en_vano(self) -> None:
        """Gasta el mismo tiempo que verificar una clave de verdad.

        Sin esto, un correo sin cuenta contesta al instante y uno con cuenta tarda
        lo que tarda bcrypt: probar correos diría cuáles están registrados.
        """
        CLAVES.dummy_verify()

    def desactivar_usuario(self, email: str) -> None:
        """Le quita la cuenta y corta lo que tuviera abierto."""
        with self.motor.begin() as con:
            con.execute(update(usuarios)
                        .where(func.lower(usuarios.c.email) == email.strip().lower())
                        .values(activo=False, sesiones_validas_desde=_ahora()))

    def cambiar_clave(self, email: str, nueva: str) -> None:
        """Cambiar la clave corta también lo que estuviera abierto."""
        with self.motor.begin() as con:
            con.execute(update(usuarios)
                        .where(func.lower(usuarios.c.email) == email.strip().lower())
                        .values(clave_hash=CLAVES.hash(nueva), debe_cambiar_clave=False,
                                sesiones_validas_desde=_ahora()))

    def ascender_a_plataforma(self, email: str) -> None:
        with self.motor.begin() as con:
            con.execute(update(usuarios)
                        .where(func.lower(usuarios.c.email) == email.strip().lower())
                        .values(rol="plataforma"))

    # --- proyectos -----------------------------------------------------------------

    def proyectos(self, cliente_id: int | None = None) -> list[ProyectoGuardado]:
        consulta = select(proyectos).order_by(proyectos.c.slug)
        if cliente_id is not None:
            consulta = consulta.where(proyectos.c.cliente_id == cliente_id)
        with self.motor.connect() as con:
            return [_proyecto(f) for f in con.execute(consulta)]

    def proyecto(self, slug: str, cliente_id: int | None = None) -> ProyectoGuardado:
        """Sin `cliente_id` busca en todo el sistema: solo para plataforma."""
        consulta = select(proyectos).where(proyectos.c.slug == slug)
        if cliente_id is not None:
            consulta = consulta.where(proyectos.c.cliente_id == cliente_id)
        with self.motor.connect() as con:
            fila = con.execute(consulta).first()
        if fila is None:
            raise NoEncontrado(f"no existe el loteo {slug!r}")
        return _proyecto(fila)

    def crear_proyecto(self, cliente_id: int, nombre: str, *, slug: str | None = None,
                       carpeta: str | None = None, nota_cobro: str | None = None,
                       vercel_proyecto: str | None = None,
                       url_publicada: str | None = None) -> ProyectoGuardado:
        """Un loteo nace pagado: solo se crea cuando CTP ya cobró.

        Con `slug` se adopta un loteo que ya existía afuera, con su identidad intacta.
        """
        ahora = _ahora()
        with self.motor.begin() as con:
            elegido = slug or _slug_libre(con, nombre)
            try:
                con.execute(insert(proyectos).values(
                    cliente_id=cliente_id, slug=elegido, nombre=nombre.strip(),
                    carpeta=carpeta, vercel_proyecto=vercel_proyecto,
                    url_publicada=url_publicada,
                    publicado_en=ahora if url_publicada else None,
                    pagado_en=ahora, nota_cobro=nota_cobro, creado_en=ahora))
            except IntegrityError as error:
                raise ProyectoYaExiste(f"ya hay un loteo llamado {nombre!r}") from error
        return self.proyecto(elegido)

    def renombrar_proyecto(self, slug: str, nombre: str) -> None:
        """El nombre cambia; el slug no. El slug es la carpeta de salida y la URL
        publicada, y cambiarlo dejaría el sitio anterior colgando."""
        with self.motor.begin() as con:
            try:
                con.execute(update(proyectos).where(proyectos.c.slug == slug)
                            .values(nombre=nombre.strip()))
            except IntegrityError as error:
                raise ProyectoYaExiste(f"ya hay un loteo llamado {nombre!r}") from error

    def anotar_publicacion(self, slug: str, vercel_proyecto: str, url: str) -> None:
        with self.motor.begin() as con:
            con.execute(update(proyectos).where(proyectos.c.slug == slug).values(
                vercel_proyecto=vercel_proyecto, url_publicada=url, publicado_en=_ahora()))

    def olvidar_proyecto(self, slug: str) -> None:
        with self.motor.begin() as con:
            con.execute(delete(proyectos).where(proyectos.c.slug == slug))

    # --- interno ---------------------------------------------------------------------

    def _estado_cliente(self, cliente_id: int, estado: str) -> None:
        with self.motor.begin() as con:
            con.execute(update(clientes).where(clientes.c.id == cliente_id).values(estado=estado))


def es_local() -> bool:
    """¿Esto corre en el computador de uno, o desplegado?

    Es la misma pregunta que se hace `acceso`, y se responde en un solo lugar
    para que no puedan contestarla distinto.
    """
    return os.environ.get("CONSOLA_ENTORNO", "local") == "local"


def url_por_defecto() -> str:
    """`MASTERPLAN_BD`, o un archivo junto a los datos si esto es un computador.

    Desplegada, la carpeta de datos es un bucket montado, y SQLite sobre GCS no
    tiene bloqueo de archivos: la base se corrompería, y adentro van los correos
    y los hashes de clave de los clientes. Así que ahí no se adivina nada —se
    exige una base de verdad— y si falta, esto revienta al arrancar. Una revisión
    que no despliega se ve; una base que se corrompe de a poco, no.
    """
    indicada = os.environ.get("MASTERPLAN_BD")
    if indicada:
        return indicada
    if not es_local():
        raise RuntimeError(
            "Falta MASTERPLAN_BD. Desplegada, la consola necesita una base de "
            "verdad (Postgres): la carpeta de datos es un bucket montado y SQLite "
            "sobre GCS se corrompe.")
    from pipeline import config
    return f"sqlite:///{config.DATOS / 'consola.db'}"


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _clave_provisional() -> str:
    return "".join(secrets.choice(ALFABETO_CLAVE) for _ in range(LARGO_CLAVE))


def _slug(nombre: str) -> str:
    plano = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plano.lower()).strip("-") or "cliente"


def _slug_libre(con, nombre: str) -> str:
    """El slug sugerido, o el siguiente con sufijo. Dos clientes pueden llamar igual
    a su loteo; el que manda es quien llega primero."""
    sugerido = _slug(nombre)
    tomados = {f[0] for f in con.execute(
        select(proyectos.c.slug).where(proyectos.c.slug.like(f"{sugerido}%")))}
    if sugerido not in tomados:
        return sugerido
    siguiente = 2
    while f"{sugerido}-{siguiente}" in tomados:
        siguiente += 1
    return f"{sugerido}-{siguiente}"


def _cliente(fila) -> Cliente:
    return Cliente(id=fila.id, slug=fila.slug, nombre=fila.nombre,
                   estado=fila.estado, creado_en=fila.creado_en)


def _usuario(fila) -> Usuario:
    return Usuario(id=fila.id, cliente_id=fila.cliente_id, email=fila.email,
                   nombre=fila.nombre, clave_hash=fila.clave_hash, rol=fila.rol,
                   activo=fila.activo, debe_cambiar_clave=fila.debe_cambiar_clave,
                   sesiones_validas_desde=fila.sesiones_validas_desde)


def _proyecto(fila) -> ProyectoGuardado:
    return ProyectoGuardado(
        id=fila.id, cliente_id=fila.cliente_id, slug=fila.slug, nombre=fila.nombre,
        carpeta=fila.carpeta,
        vercel_proyecto=fila.vercel_proyecto, url_publicada=fila.url_publicada,
        publicado_en=fila.publicado_en, pagado_en=fila.pagado_en, nota_cobro=fila.nota_cobro)
