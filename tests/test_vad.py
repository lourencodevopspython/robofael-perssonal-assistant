import pytest

from robofael.audio.vad import DetectorFala, StatusFala, nivel_visual

BLOCO = 0.05  # 50 ms


def rodar(detector, sequencia):
    status = None
    for rms in sequencia:
        status = detector.processar(rms, BLOCO)
    return status


def test_fala_termina_apos_a_pausa():
    d = DetectorFala(limiar=100, pausa_s=0.3)
    assert rodar(d, [10] * 4) is StatusFala.AGUARDANDO
    assert rodar(d, [500] * 10) is StatusFala.FALANDO
    assert rodar(d, [10] * 5) is StatusFala.FALANDO  # pausa curta: ainda falando
    assert rodar(d, [10] * 2) is StatusFala.CONCLUIDO
    assert d.processar(999, BLOCO) is StatusFala.CONCLUIDO  # estado final é estável


def test_estalo_curto_e_ignorado():
    d = DetectorFala(limiar=100, pausa_s=0.2, fala_min_s=0.2)
    assert rodar(d, [500] + [10] * 4) is StatusFala.AGUARDANDO  # 50 ms de ruído não conta


def test_ninguem_falou():
    d = DetectorFala(limiar=100, espera_max_s=0.5)
    assert rodar(d, [10] * 10) is StatusFala.SEM_FALA


def test_frase_muito_longa_e_encerrada():
    d = DetectorFala(limiar=100, frase_max_s=1.0)
    assert rodar(d, [500] * 20) is StatusFala.CONCLUIDO


@pytest.mark.parametrize("ruido, esperado", [([], 150.0), ([10, 20, 30], 150.0), ([100, 200, 300], 500.0)])
def test_calibracao_pela_mediana_do_ruido(ruido, esperado):
    assert DetectorFala.calibrar(ruido) == esperado


def test_nivel_visual_limitado():
    assert nivel_visual(0, 100) == 0.0
    assert nivel_visual(10_000, 100) == 1.0
    assert 0 < nivel_visual(200, 100) < 1
    assert nivel_visual(50, 0) == 0.0
