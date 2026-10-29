"""Expressões de tempo para lembretes, em português e inglês; e os comandos em inglês no modo offline."""

from datetime import datetime

import pytest

from robofael.adaptadores.offline import ModeloOffline
from robofael.dominio.quando import interpretar_quando, sem_trechos
from robofael.i18n import Idioma, Tradutor

AGORA = datetime(2026, 10, 29, 14, 30)  # quinta-feira, 14:30


@pytest.mark.parametrize("texto, momento, resto", [
    ("remind me to drink water in 5 minutes", "2026-10-29 14:35", "remind me to drink water"),
    ("remind me in five minutes to drink water", "2026-10-29 14:35", "remind me to drink water"),
    ("in an hour stretch", "2026-10-29 15:30", "stretch"),
    ("in 2 hours", "2026-10-29 16:30", ""),
    ("in half an hour", "2026-10-29 15:00", ""),
    ("tomorrow at 9 about the meeting", "2026-10-30 09:00", "about the meeting"),
    ("at 3 pm call mom", "2026-10-29 15:00", "call mom"),
    ("at 3 call mom", "2026-10-29 15:00", "call mom"),  # sem am/pm, 1–7 é tarde
    ("at 15:30", "2026-10-29 15:30", ""),
    ("at 9 standup", "2026-10-30 09:00", "standup"),  # 9h já passou hoje: amanhã
    ("tomorrow 09:00", "2026-10-30 09:00", ""),  # como o modelo local às vezes manda
    ("tonight at 8 take pills", "2026-10-29 20:00", "take pills"),
    ("at 7 am run", "2026-10-30 07:00", "run"),
    ("daqui a 10 minutos beber água", "2026-10-29 14:40", "beber água"),
    ("em uma hora", "2026-10-29 15:30", ""),
    ("daqui a meia hora", "2026-10-29 15:00", ""),
    ("amanhã às 9h30 reunião", "2026-10-30 09:30", "reunião"),
    ("às 3 da tarde ligar", "2026-10-29 15:00", "ligar"),
    ("às 8 da noite", "2026-10-29 20:00", ""),
    ("às 5h acordar", "2026-10-30 05:00", "acordar"),  # "5h" é notação de 24 horas
    ("me lembra amanhã de pagar a conta", "2026-10-30 09:00", "me lembra de pagar a conta"),
    ("remind me about the dentist next friday", "2026-10-30 09:00", "remind me about the dentist"),
    ("on monday at 3 pm call John", "2026-11-02 15:00", "call John"),
    ("thursday at 10", "2026-11-05 10:00", ""),  # hoje é quinta: a próxima
    ("me lembra da reunião na sexta que vem às 10h", "2026-10-30 10:00", "me lembra da reunião"),
    ("na próxima segunda-feira pagar o aluguel", "2026-11-02 09:00", "pagar o aluguel"),
])
def test_interpreta_o_momento(texto, momento, resto):
    q = interpretar_quando(texto, AGORA)
    assert q is not None and q.momento == datetime.fromisoformat(momento)
    assert sem_trechos(texto, q.trechos) == resto


@pytest.mark.parametrize("texto", ["complete task 3", "anota tarefa 2 relatórios", "what are my tasks", "oi"])
def test_sem_momento(texto):
    assert interpretar_quando(texto, AGORA) is None


@pytest.fixture
def offline_en(agenda):
    return ModeloOffline(agenda, relogio=lambda: AGORA, tradutor=Tradutor(Idioma.EN_US))


OK = "Okay, I'll remind you "


@pytest.mark.parametrize("fala, texto, momento, resposta", [
    ("remind me to drink water in 5 minutes", "drink water", "2026-10-29 14:35", OK + "in 5 minutes."),
    ("remind me in five minutes to drink water", "drink water", "2026-10-29 14:35", OK + "in 5 minutes."),
    ("set a reminder in 10 minutes to call mom", "call mom", "2026-10-29 14:40", OK + "in 10 minutes."),
    ("remind me in one hour to stretch", "stretch", "2026-10-29 15:30", OK + "today at 03:30 PM."),
    ("remind me tomorrow at 9 about the team meeting", "the team meeting", "2026-10-30 09:00",
     OK + "tomorrow at 09:00 AM."),
    ("remind me at 3 pm to call the bank", "call the bank", "2026-10-29 15:00", OK + "today at 03:00 PM."),
])
def test_cria_lembretes_em_ingles_em_qualquer_ordem(offline_en, agenda, fala, texto, momento, resposta):
    assert offline_en.tentar(fala) == resposta
    [lembrete] = agenda.proximos_lembretes()
    assert (lembrete.texto, lembrete.quando) == (texto, datetime.fromisoformat(momento))


@pytest.mark.parametrize("fala, texto", [
    ("add task buy milk", "buy milk"), ("add a task to buy milk", "buy milk"),
    ("create a task to review the report", "review the report"), ("make a task to clean the house", "clean the house"),
    ("new task pay the bills", "pay the bills"), ("add a new task called call John", "call John"),
])
def test_cria_tarefas_em_ingles(offline_en, agenda, fala, texto):
    assert offline_en.tentar(fala) == f"Added: {texto}."
    assert [t.texto for t in agenda.pendentes()] == [texto]


def test_pergunta_sobre_lembretes_nao_cria_lembrete(agenda):
    perguntas = ((Idioma.PT_BR, "tenho algum lembrete para amanhã?"),
                 (Idioma.EN_US, "do I have any reminder tomorrow?"))
    for idioma, fala in perguntas:
        ModeloOffline(agenda, relogio=lambda: AGORA, tradutor=Tradutor(idioma)).tentar(fala)
    assert agenda.proximos_lembretes() == []


def test_lembrete_em_portugues_com_horario(agenda):
    modelo = ModeloOffline(agenda, relogio=lambda: AGORA)
    assert modelo.tentar("me lembra amanhã às 9h30 da reunião com o time") == "Combinado, te lembro amanhã às 09:30."
    assert [(l.texto, l.quando) for l in agenda.proximos_lembretes()] == [
        ("reunião com o time", datetime(2026, 10, 30, 9, 30))]
