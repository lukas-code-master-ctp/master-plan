"""Las pruebas no necesitan que bcrypt sea lento.

Doce rondas son lo correcto en producción y un cuarto de segundo por cuenta acá,
que multiplicado por las cuentas que crean estas pruebas es un minuto de espera.
El número real vive en `datos.CLAVES` y no lo toca nadie más.
"""
import pytest

from consola.datos import CLAVES


@pytest.fixture(autouse=True, scope="session")
def bcrypt_rapido():
    CLAVES.update(bcrypt__rounds=4)
