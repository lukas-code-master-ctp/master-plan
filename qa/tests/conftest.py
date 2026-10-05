"""Las pruebas de QA tampoco necesitan que bcrypt sea lento: la siembra crea cinco
cuentas y cada prueba que siembra las vuelve a crear. Mismo truco que
`consola/tests/conftest.py`."""
import pytest

from consola.datos import CLAVES


@pytest.fixture(autouse=True, scope="session")
def bcrypt_rapido():
    CLAVES.update(bcrypt__rounds=4)
