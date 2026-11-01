"""Veredito de experimento: regra z-score local primeiro, Jev só na fronteira (calibrado em série sintética)."""
import random

from circulo.decision import Decision
from circulo.veredito_experimento import LIMIARES, Limiares, com_jev, julgar

TRIALS = 4000


def _serie(rng, n, media=0.0, dp=1.0):
    return [rng.gauss(media, dp) for _ in range(n)]


def _taxa_real(efeito, n=LIMIARES.n_minimo, semente=7):
    rng = random.Random(semente)
    reais = sum(julgar(_serie(rng, n, media=efeito), _serie(rng, n)).estado == "real" for _ in range(TRIALS))
    return reais / TRIALS


def test_ruido_puro_da_no_maximo_5_por_cento_de_falso_positivo():
    assert _taxa_real(0.0) <= 0.05


def test_efeito_de_2_desvios_padrao_e_detectado_em_80_por_cento():
    assert _taxa_real(2.0) >= 0.80


def test_amostra_abaixo_do_minimo_nunca_e_evidencia_nem_com_jev_confiante():
    rng = random.Random(3)
    n = LIMIARES.n_minimo - 1
    for _ in range(200):
        v = julgar(_serie(rng, n, media=5.0), _serie(rng, LIMIARES.n_minimo))
        assert v.estado == "sem_dados"
        assert com_jev(v, Decision("experimento_veredito", "noul", 1.0, 1.0, "jev")) == "sem_dados"


def test_minimo_e_limiares_vem_da_config():
    lim = Limiares(n_minimo=5, z_real=3.0, z_ruido=0.5, corte_jev=0.8)
    assert julgar([1, 2, 1, 2, 1], [1, 2, 1, 2, 1], lim).estado == "ruído"
    assert julgar([1, 2, 1], [1, 2, 1, 2, 1], lim).estado == "sem_dados"


def test_so_a_fronteira_vai_ao_jev_e_so_confianca_acima_do_corte_conta():
    antes = [0.0, 1.0] * 30
    fronteira = julgar([x + 0.15 for x in antes], antes)
    assert fronteira.estado == "fronteira" and 1 <= abs(fronteira.z) < 2

    assert com_jev(fronteira, Decision("experimento_veredito", "noul", 0.9, 0.8, "jev")) == "real"
    assert com_jev(fronteira, Decision("experimento_veredito", "noul", 0.1, 0.8, "jev")) == "ruído"
    assert com_jev(fronteira, Decision("experimento_veredito", "noul", 0.8, 0.6, "jev")) == "inconclusivo"
    assert com_jev(fronteira, None) == "inconclusivo"

    real = julgar([x + 1.0 for x in antes], antes)
    assert real.estado == "real"
    assert com_jev(real, Decision("experimento_veredito", "noul", 0.0, 1.0, "jev")) == "real"
