import threading
import time
from datetime import datetime, timedelta

import pytest

from conftest import RepositorioMemoria
from robofael.aplicacao.agendador import ESPERA_MAXIMA_S, AgendadorLembretes
from robofael.dominio.agenda import Agenda


def test_sem_lembretes_espera_o_maximo(agenda, relogio):
    assert AgendadorLembretes(agenda, lambda l: None, relogio).verificar() == ESPERA_MAXIMA_S


def test_calcula_espera_ate_o_proximo(agenda, relogio):
    agenda.criar_lembrete("daily", datetime(2026, 10, 21, 16, 26))
    relogio.agora = datetime(2026, 10, 21, 16, 25, 30)
    assert AgendadorLembretes(agenda, lambda l: None, relogio).verificar() == pytest.approx(30)


def test_dispara_vencidos_em_ordem_e_uma_vez(agenda, relogio):
    avisados = []
    ag = AgendadorLembretes(agenda, lambda l: avisados.append(l.texto), relogio)
    agenda.criar_lembrete("b", datetime(2026, 10, 21, 16, 40))
    agenda.criar_lembrete("a", datetime(2026, 10, 21, 16, 30))
    ag.verificar()
    assert avisados == []
    relogio.agora = datetime(2026, 10, 21, 16, 41)
    ag.verificar()
    ag.verificar()
    assert avisados == ["a", "b"]


def test_falha_ao_avisar_nao_interrompe_os_demais(agenda, relogio):
    avisados = []

    def avisar(l):
        if l.texto == "ruim":
            raise RuntimeError
        avisados.append(l.texto)

    agenda.criar_lembrete("ruim", relogio())
    agenda.criar_lembrete("bom", relogio())
    AgendadorLembretes(agenda, avisar, relogio).verificar()
    assert avisados == ["bom"]


def test_thread_acorda_quando_a_agenda_muda():
    """Com a espera máxima de 60 s, só um 'acordar' imediato faz o aviso chegar a tempo."""
    agenda = Agenda(RepositorioMemoria())  # relógio real
    disparou = threading.Event()
    ag = AgendadorLembretes(agenda, lambda l: disparou.set())
    ag.iniciar()
    try:
        time.sleep(0.1)  # a thread já está dormindo
        agenda.criar_lembrete("agora", datetime.now() - timedelta(seconds=1))
        assert disparou.wait(2.0)
    finally:
        ag.parar()
