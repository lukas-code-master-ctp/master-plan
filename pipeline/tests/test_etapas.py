"""El contorno de cada etapa encierra sus parcelas aunque las separe un camino."""
import pytest

from pipeline import geo
from pipeline.etapas import contornos

LON, LAT = -72.48, -36.72


def cuadrado(este, norte, lado=50.0):
    return [geo.desde_metros(xy, (LON, LAT)) for xy in
            ((este, norte), (este + lado, norte), (este + lado, norte + lado), (este, norte + lado))]


def test_una_etapa_con_un_camino_al_medio_queda_en_un_solo_contorno():
    # Etapa 1: dos parcelas separadas por un camino de 12 m. Etapa 2: más allá.
    parcelas = [(1, cuadrado(0, 0)), (1, cuadrado(62, 0)), (2, cuadrado(0, 300)), (2, cuadrado(60, 300))]

    resultado = dict(contornos(parcelas))

    assert sorted(resultado) == [1, 2]
    assert len(resultado[1]) == 1
    este = [geo.a_metros(p, (LON, LAT))[0] for p in resultado[1][0]]
    norte = [geo.a_metros(p, (LON, LAT))[1] for p in resultado[1][0]]
    assert min(este) == pytest.approx(0, abs=1.0) and max(este) == pytest.approx(112, abs=1.0)
    assert min(norte) == pytest.approx(0, abs=1.0) and max(norte) == pytest.approx(50, abs=1.0)


def test_con_una_sola_etapa_no_hay_nada_que_separar():
    assert contornos([(1, cuadrado(0, 0)), (1, cuadrado(60, 0)), (None, cuadrado(0, 200))]) == []
