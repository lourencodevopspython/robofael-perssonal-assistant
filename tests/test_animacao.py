import pytest

from robofael.avatar.animacao import ABERTA, NEUTRA, REDONDA, SeletorForma, nivel_boca, suavizar_boca


def test_suavizacao_independe_da_taxa_de_quadros():
    a60 = 0.0
    for _ in range(6):
        a60 = suavizar_boca(a60, 1.0, dt=1 / 60)
    a30 = 0.0
    for _ in range(3):
        a30 = suavizar_boca(a30, 1.0, dt=1 / 30)
    assert a30 == pytest.approx(a60)  # mesmo tempo decorrido, mesma abertura


def test_boca_abre_mais_rapido_do_que_fecha():
    abrindo = suavizar_boca(0.0, 1.0)
    fechando = 1.0 - suavizar_boca(1.0, 0.0)
    assert abrindo > fechando > 0


def test_boca_converge_para_o_alvo_sem_ultrapassar():
    valor, historico = 0.0, []
    for _ in range(40):
        valor = suavizar_boca(valor, 0.7)
        historico.append(valor)
    assert historico == sorted(historico) and historico[-1] == pytest.approx(0.7, abs=1e-3)


@pytest.mark.parametrize("abertura, esperado", [(0.0, 0), (0.5, 6), (1.0, 11), (1.7, 11), (-0.3, 0)])
def test_nivel_da_boca_fica_dentro_dos_quadros(abertura, esperado):
    assert nivel_boca(abertura, 12) == esperado


def test_boca_quase_fechada_volta_ao_formato_neutro():
    s = SeletorForma()
    assert s.atualizar(timbre=-0.9, abertura=0.5, t=0.0) == REDONDA
    assert s.atualizar(timbre=-0.9, abertura=0.02, t=1.0) == NEUTRA


@pytest.mark.parametrize("timbre, esperado", [(-0.8, REDONDA), (0.0, NEUTRA), (0.8, ABERTA)])
def test_formato_segue_o_timbre_da_vogal(timbre, esperado):
    assert SeletorForma().atualizar(timbre, abertura=0.6, t=0.0) == esperado


def test_histerese_entre_os_limiares():
    s = SeletorForma(limiar_redonda=-0.45, limiar_aberta=0.55)
    assert s.atualizar(0.5, 0.6, t=0.0) == NEUTRA  # abaixo do limiar de "aberta"
    assert s.atualizar(-0.4, 0.6, t=1.0) == NEUTRA  # acima do limiar de "redonda"


def test_troca_vizinha_espera_tempo_minimo():
    s = SeletorForma(permanencia=0.1)
    assert s.atualizar(0.9, 0.6, t=0.00) == ABERTA
    assert s.atualizar(0.0, 0.6, t=0.05) == ABERTA  # ainda não passou 100 ms
    assert s.atualizar(0.0, 0.6, t=0.11) == NEUTRA


def test_salto_entre_extremos_e_imediato():
    s = SeletorForma(permanencia=0.1)
    assert s.atualizar(0.9, 0.6, t=0.00) == ABERTA
    assert s.atualizar(-0.9, 0.6, t=0.01) == REDONDA  # "e" -> "o" não espera
