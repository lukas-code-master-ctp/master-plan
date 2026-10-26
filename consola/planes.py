"""Los planes de suscripción y cuántos loteos en línea deja tener cada uno.

La landing vende un plan mensual a la loteadora, no un pago por loteo: los planes
solo se diferencian en cuántos loteos puede tener publicados a la vez. Acá vive esa
lista y la única regla que se cobra: si un loteo se puede publicar.

Construir y revisar sigue siendo gratis. Lo que ocupa cupo es estar en línea,
porque es lo que le sirve a alguien más que a quien armó el master.

Los loteos que se pagaron de a uno (el modelo anterior, `pagado_en`) se respetan:
se pueden publicar y actualizar sin plan y no ocupan cupo.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    clave: str
    nombre: str
    # Loteos en línea a la vez. None: se fija a mano para cada loteadora.
    loteos: int | None
    # Pesos chilenos al mes, como en la landing. None: a la medida.
    precio_mensual: int | None


# Los mismos números que la sección Planes de landing/index.html: si cambian allá,
# cambian acá.
PLANES: dict[str, Plan] = {
    "fly": Plan("fly", "Fly", 1, 30_000),
    "pro": Plan("pro", "Pro", 3, 80_000),
    "master": Plan("master", "Master", 6, 150_000),
    "enterprise": Plan("enterprise", "Enterprise", None, None),
}

# Un Enterprise sin cupo escrito sería un plan que no deja publicar nada.
MAX_LOTEOS_A_MEDIDA = 500


class PlanInvalido(ValueError):
    """El plan pedido no existe o le falta el cupo. El mensaje es para la persona."""


def validar(clave: str | None, loteos: object = None) -> tuple[str | None, int | None]:
    """El plan y el cupo tal como se guardan. Solo Enterprise guarda su cupo:
    los demás lo toman de `PLANES`, así un cambio de catálogo llega a todos."""
    if clave in (None, ""):
        return None, None
    if clave not in PLANES:
        raise PlanInvalido(f"no existe el plan {clave!r}")
    if PLANES[clave].loteos is not None:
        return clave, None
    try:
        cupo = int(loteos)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise PlanInvalido("di cuántos loteos en línea incluye el plan a la medida") from None
    if not 1 <= cupo <= MAX_LOTEOS_A_MEDIDA:
        raise PlanInvalido(f"el plan a la medida va de 1 a {MAX_LOTEOS_A_MEDIDA} loteos")
    return clave, cupo


def cupo_de(cliente) -> int | None:
    """Cuántos loteos puede tener en línea; None si no tiene plan."""
    if not cliente.plan or cliente.plan not in PLANES:
        return None
    return PLANES[cliente.plan].loteos or cliente.plan_loteos or 0


def ocupa_cupo(guardado) -> bool:
    """Un loteo en línea que no se pagó aparte."""
    return bool(guardado.url_publicada) and not guardado.pagado


def en_linea(guardados) -> int:
    return sum(1 for g in guardados if ocupa_cupo(g))


def por_que_no_publica(guardado, cliente, guardados) -> str | None:
    """Por qué este loteo no se puede publicar ahora, o None si se puede.

    `guardados` son todos los loteos de la misma loteadora. Republicar uno que ya
    está en línea no suma nada, así que basta con tener plan.
    """
    if guardado.pagado:
        return None
    cupo = cupo_de(cliente)
    if cupo is None:
        return "elige un plan para publicar: armar y revisar el master es gratis"
    if guardado.url_publicada:
        return None
    usados = en_linea(guardados)
    if usados >= cupo:
        nombre = PLANES[cliente.plan].nombre
        return (f"tu plan {nombre} incluye {cupo} {_loteos(cupo)} en línea y "
                f"{'ya está ocupado' if cupo == 1 else 'ya están ocupados'}: cambia a un "
                "plan más grande para publicar este")
    return None


def como_json(cliente, guardados) -> dict:
    """Lo que la consola muestra del plan de una loteadora."""
    plan = PLANES.get(cliente.plan or "")
    return {
        "plan": plan.clave if plan else None,
        "nombre": plan.nombre if plan else None,
        "loteos": cupo_de(cliente),
        "en_linea": en_linea(guardados),
        "precio_mensual": plan.precio_mensual if plan else None,
        "desde": cliente.plan_desde.isoformat() if cliente.plan_desde else None,
        "pedido": cliente.plan_pedido,
    }


def catalogo() -> list[dict]:
    return [{"plan": p.clave, "nombre": p.nombre, "loteos": p.loteos,
             "precio_mensual": p.precio_mensual} for p in PLANES.values()]


def _loteos(n: int) -> str:
    return "loteo" if n == 1 else "loteos"
