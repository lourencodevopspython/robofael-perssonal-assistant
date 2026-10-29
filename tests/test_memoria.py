""""O que eu fiz?": interpretação de períodos, resumo do histórico e respostas."""

from datetime import date, datetime

import pytest

from conftest import AGORA, Relogio, RepositorioMemoria
from robofael.adaptadores.ferramentas import ExecutorFerramentas
from robofael.adaptadores.offline import ModeloOffline
from robofael.aplicacao.memoria import Memoria
from robofael.dominio.agenda import Agenda
from robofael.dominio.linguagem import juntar, pergunta_historico
from robofael.dominio.periodos import Periodo, interpretar_periodo

HOJE = date(2026, 10, 22)  # quinta-feira


@pytest.mark.parametrize("texto, inicio, fim, descricao", [
    ("o que eu fiz hoje", "2026-10-22", "2026-10-22", "hoje (22/10)"),
    ("o que fiz ontem?", "2026-10-21", "2026-10-21", "ontem (21/10)"),
    ("e anteontem", "2026-10-20", "2026-10-20", "anteontem (20/10)"),
    ("o que eu fiz na segunda", "2026-10-19", "2026-10-19", "na segunda-feira (19/10)"),
    ("na quinta-feira", "2026-10-15", "2026-10-15", "na quinta-feira (15/10)"),  # hoje é quinta: a anterior
    ("no sábado", "2026-10-17", "2026-10-17", "no sábado (17/10)"),
    ("semana passada", "2026-10-12", "2026-10-18", "na semana passada (12/10 a 18/10)"),
    ("o que concluí nesta semana", "2026-10-19", "2026-10-22", "nesta semana (19/10 a 22/10)"),
    ("nos últimos 7 dias", "2026-10-16", "2026-10-22", "nos últimos 7 dias (16/10 a 22/10)"),
    ("nos últimos três dias", "2026-10-20", "2026-10-22", "nos últimos 3 dias (20/10 a 22/10)"),
    ("no dia 20", "2026-10-20", "2026-10-20", "no dia 20/10"),
    ("no dia 30", "2026-09-30", "2026-09-30", "no dia 30/09"),  # dia 30 ainda não chegou: mês anterior
    ("em 20/10", "2026-10-20", "2026-10-20", "em 20/10/2026"),
    ("em 20/10/2025", "2025-10-20", "2025-10-20", "em 20/10/2025"),
    ("dia 5 de outubro", "2026-10-05", "2026-10-05", "em 05/10/2026"),
    ("25 de dezembro", "2025-12-25", "2025-12-25", "em 25/12/2025"),  # o mais recente no passado
    ("na semana do dia 5/10", "2026-10-05", "2026-10-11", "na semana de 05/10 a 11/10"),
    ("mês passado", "2026-09-01", "2026-09-30", "no mês passado (09/2026)"),
    ("este mês", "2026-10-01", "2026-10-22", "neste mês (10/2026)"),
])
def test_interpreta_periodos_em_portugues(texto, inicio, fim, descricao):
    """`fim` aqui é o último dia incluído; o Periodo guarda o fim exclusivo (dia seguinte, 00:00)."""
    p = interpretar_periodo(texto, HOJE)
    assert p == Periodo.dias(date.fromisoformat(inicio), date.fromisoformat(fim), descricao)


@pytest.mark.parametrize("texto", ["que horas são", "dia 45", "31/02", ""])
def test_sem_periodo_reconhecivel(texto):
    assert interpretar_periodo(texto, HOJE) is None


@pytest.mark.parametrize("texto, esperado", [
    ("o que eu fiz ontem?", True), ("que eu fiz na semana passada", True), ("O que concluí hoje", True),
    ("o que eu terminei dia 20", True), ("meu histórico de segunda", True), ("minhas atividades de ontem", True),
    ("anota tarefa fazer bolo", False), ("o que você faz?", False), ("que horas são", False),
])
def test_reconhece_perguntas_sobre_o_historico(texto, esperado):
    assert pergunta_historico(texto) is esperado


def test_juntar():
    assert juntar([]) == "" and juntar(["a"]) == "a" and juntar(["a", "b", "c"]) == "a, b e c"


# ---------- Resumo a partir do histórico real da agenda ----------
@pytest.fixture
def cenario():
    """Agenda com uma semana de atividades registradas no histórico."""
    relogio = Relogio(datetime(2026, 10, 19, 9, 0))  # segunda
    repo = RepositorioMemoria()
    agenda = Agenda(repo, relogio)
    pr = agenda.adicionar_tarefa("revisar o PR")
    pao = agenda.adicionar_tarefa("comprar pão")
    relogio.agora = datetime(2026, 10, 19, 18, 0)
    agenda.concluir_tarefa(pr.id)
    relogio.agora = datetime(2026, 10, 21, 10, 0)  # quarta
    agenda.concluir_tarefa(pao.id)
    deploy = agenda.adicionar_tarefa("fazer o deploy")
    agenda.concluir_tarefa(deploy.id)
    agenda.alternar_tarefa(deploy.id)  # reaberta no mesmo dia: não conta como feita
    agenda.criar_lembrete("daily", datetime(2026, 10, 21, 9, 0))
    agenda.retirar_vencidos()
    relogio.agora = datetime(2026, 10, 22, 12, 0)  # quinta (hoje)
    return Memoria(repo), agenda, relogio


def test_resumo_de_um_dia(cenario):
    memoria, *_ = cenario
    r = memoria.resumo(interpretar_periodo("ontem", HOJE))
    assert [e.descricao for e in r.concluidas] == ["comprar pão"]  # o deploy foi reaberto
    assert [e.descricao for e in r.criadas] == ["fazer o deploy"]
    assert [e.descricao for e in r.lembretes] == ["daily"]


def test_resposta_de_uma_semana(cenario):
    memoria, *_ = cenario
    assert memoria.responder(interpretar_periodo("nesta semana", HOJE)) == (
        "Nesta semana (19/10 a 22/10) você concluiu 2 tarefas: revisar o PR e comprar pão. "
        "Também criou 3 tarefas e recebeu 1 lembrete.")


def test_periodo_sem_tarefas_concluidas(cenario):
    memoria, *_ = cenario
    assert memoria.responder(interpretar_periodo("semana passada", HOJE)) == (
        "Não encontrei tarefas concluídas na semana passada (12/10 a 18/10).")
    hoje = Periodo.dias(HOJE, HOJE, "hoje (22/10)")
    assert memoria.responder(hoje) == "Não encontrei tarefas concluídas hoje (22/10)."


def test_so_criacoes_no_periodo(cenario):
    memoria, agenda, relogio = cenario
    relogio.agora = datetime(2026, 10, 22, 15, 0)
    agenda.adicionar_tarefa("ligar para o cliente")
    assert memoria.responder(Periodo.dias(HOJE, HOJE, "hoje (22/10)")) == (
        "Não encontrei tarefas concluídas hoje (22/10). Mas você criou 1 tarefa: ligar para o cliente.")


def test_lista_longa_e_resumida():
    relogio = Relogio(AGORA)
    repo = RepositorioMemoria()
    agenda = Agenda(repo, relogio)
    for i in range(9):
        agenda.concluir_tarefa(agenda.adicionar_tarefa(f"t{i}").id)
    resposta = Memoria(repo).responder(Periodo.dias(AGORA.date(), AGORA.date(), "hoje"))
    assert "concluiu 9 tarefas: t0, t1, t2, t3, t4, t5 e mais 3." in resposta


def test_modo_offline_responde_o_que_eu_fiz(cenario):
    memoria, agenda, relogio = cenario
    modelo = ModeloOffline(agenda, relogio, memoria=memoria)
    assert "".join(modelo.responder("o que eu fiz na segunda?")) == (
        "Na segunda-feira (19/10) você concluiu 1 tarefa: revisar o PR. Também criou 2 tarefas.")
    assert "".join(modelo.responder("o que eu fiz?")).startswith("Não encontrei tarefas concluídas hoje")


def test_modo_offline_sem_memoria():
    modelo = ModeloOffline(Agenda(RepositorioMemoria(), Relogio()), Relogio())
    assert "".join(modelo.responder("o que eu fiz ontem")) == "Ainda não tenho acesso ao histórico."


def test_ferramenta_consultar_historico(cenario):
    memoria, agenda, _ = cenario
    ex = ExecutorFerramentas(agenda, memoria)
    r = ex.executar("consultar_historico", {"inicio": "2026-10-19", "fim": "2026-10-21"})
    assert [t["descricao"] for t in r["tarefas_concluidas"]] == ["revisar o PR", "comprar pão"]
    assert r["inicio"] == "2026-10-19" and r["fim_exclusivo"] == "2026-10-22"
    with pytest.raises(ValueError, match="anterior"):
        ex.executar("consultar_historico", {"inicio": "2026-10-21", "fim": "2026-10-19"})
    with pytest.raises(ValueError, match="indisponível"):
        ExecutorFerramentas(agenda).executar("consultar_historico", {"inicio": "2026-10-19", "fim": "2026-10-19"})
