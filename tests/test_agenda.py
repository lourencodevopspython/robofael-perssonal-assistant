from datetime import datetime

import pytest

from conftest import AGORA, RepositorioMemoria
from robofael.dominio.agenda import Agenda, TarefaNaoEncontrada
from robofael.dominio.modelos import DadosAgenda, Lembrete, Tarefa


def test_adiciona_tarefas_com_ids_incrementais_e_horario(agenda):
    a, b = agenda.adicionar_tarefa("Revisar PR"), agenda.adicionar_tarefa("Daily")
    assert (a.id, b.id) == (1, 2)
    assert a.criada == AGORA
    assert [t.texto for t in agenda.pendentes()] == ["Revisar PR", "Daily"]


def test_normaliza_e_rejeita_tarefa_vazia(agenda):
    assert agenda.adicionar_tarefa("  Comprar pão  ").texto == "Comprar pão"
    with pytest.raises(ValueError):
        agenda.adicionar_tarefa("   ")


def test_cada_alteracao_persiste_e_notifica(agenda, repositorio):
    avisos = []
    agenda.observar(lambda: avisos.append(1))
    t = agenda.adicionar_tarefa("x")
    agenda.concluir_tarefa(t.id)
    agenda.remover_tarefa(t.id)
    assert repositorio.salvamentos == 3 and len(avisos) == 3


def test_falha_nao_persiste_nem_notifica(agenda, repositorio):
    avisos = []
    agenda.observar(lambda: avisos.append(1))
    with pytest.raises(TarefaNaoEncontrada):
        agenda.concluir_tarefa(99)
    assert repositorio.salvamentos == 0 and avisos == []


def test_concluir_e_alternar(agenda):
    t = agenda.adicionar_tarefa("A")
    agenda.concluir_tarefa(t.id)
    assert agenda.pendentes() == [] and agenda.tarefas(incluir_concluidas=True) == [t]
    assert agenda.alternar_tarefa(t.id).feita is False
    assert agenda.pendentes() == [t]


@pytest.mark.parametrize("operacao", ["concluir_tarefa", "remover_tarefa", "alternar_tarefa"])
def test_tarefa_inexistente(agenda, operacao):
    with pytest.raises(TarefaNaoEncontrada, match="não encontrada"):
        getattr(agenda, operacao)(42)


def test_lembretes_aceitam_texto_iso_ou_datetime(agenda):
    a = agenda.criar_lembrete("daily", "2026-10-21T17:00")
    b = agenda.criar_lembrete("  ", datetime(2026, 10, 21, 16, 30, 45))
    assert a.quando == datetime(2026, 10, 21, 17, 0)
    assert b.texto == "seu lembrete" and b.quando.second == 0
    assert [l.texto for l in agenda.proximos_lembretes()] == ["seu lembrete", "daily"]
    assert agenda.proximo_vencimento() == b.quando


def test_lembrete_com_data_invalida(agenda):
    with pytest.raises(ValueError):
        agenda.criar_lembrete("x", "amanhã cedo")


def test_remover_lembrete(agenda):
    l = agenda.criar_lembrete("x", AGORA)
    agenda.remover_lembrete(l.id)
    assert agenda.proximos_lembretes() == []
    with pytest.raises(ValueError):
        agenda.remover_lembrete(l.id)


def test_retirar_vencidos_avisa_uma_vez_em_ordem(agenda, relogio, repositorio):
    agenda.criar_lembrete("b", "2026-10-21T16:40")
    agenda.criar_lembrete("a", "2026-10-21T16:30")
    agenda.criar_lembrete("c", "2026-10-21T18:00")
    assert agenda.retirar_vencidos() == []
    relogio.agora = datetime(2026, 10, 21, 16, 45)
    salvos = repositorio.salvamentos
    assert [l.texto for l in agenda.retirar_vencidos()] == ["a", "b"]
    assert repositorio.salvamentos == salvos + 1
    assert agenda.retirar_vencidos() == []
    assert agenda.proximo_vencimento() == datetime(2026, 10, 21, 18, 0)


def test_dados_ida_e_volta_e_formato_v1():
    dados = DadosAgenda([Tarefa(1, "t", AGORA, True)], [Lembrete(2, "l", AGORA)], 3)
    assert DadosAgenda.de_dict(dados.para_dict()) == dados
    v1 = {"tarefas": [{"id": 5, "texto": "antiga", "feita": False, "criada": "2026-10-20T09:00"}],
          "lembretes": [], "prox_id": 2}
    migrado = DadosAgenda.de_dict(v1)
    assert migrado.tarefas[0].texto == "antiga"
    assert migrado.prox_id == 6  # nunca reutiliza um id existente


def test_agenda_carrega_dados_existentes(relogio):
    repo = RepositorioMemoria(DadosAgenda([Tarefa(1, "existente", AGORA)], [], 2))
    agenda = Agenda(repo, relogio)
    assert agenda.adicionar_tarefa("nova").id == 2


# ---------- Auditoria ----------
def tipos(repositorio):
    return [e.tipo for e in repositorio.historico]


def test_cada_operacao_gera_um_registro_de_auditoria(agenda, repositorio, relogio):
    from robofael.dominio.modelos import TipoEvento as T

    t = agenda.adicionar_tarefa("Revisar PR")
    agenda.concluir_tarefa(t.id)
    agenda.concluir_tarefa(t.id)  # já concluída: não repete o evento
    agenda.alternar_tarefa(t.id)  # reabre
    agenda.remover_tarefa(t.id)
    lem = agenda.criar_lembrete("água", AGORA)
    agenda.retirar_vencidos()
    agenda.criar_lembrete("daily", "2026-10-22T09:00")
    agenda.remover_lembrete(lem.id + 1)
    assert tipos(repositorio) == [T.TAREFA_CRIADA, T.TAREFA_CONCLUIDA, T.TAREFA_REABERTA, T.TAREFA_REMOVIDA,
                                  T.LEMBRETE_CRIADO, T.LEMBRETE_AVISADO, T.LEMBRETE_CRIADO, T.LEMBRETE_REMOVIDO]
    assert all(e.ocorrido_em == AGORA for e in repositorio.historico)
    assert repositorio.historico[3].descricao == "Revisar PR"  # guarda a descrição mesmo após remover


def test_conclusao_registra_a_data_e_reabrir_limpa(agenda, relogio):
    t = agenda.adicionar_tarefa("x")
    relogio.agora = datetime(2026, 10, 21, 18, 5, 33)
    assert agenda.concluir_tarefa(t.id).concluida_em == datetime(2026, 10, 21, 18, 5)
    assert agenda.alternar_tarefa(t.id).concluida_em is None


def test_falha_nao_gera_registro(agenda, repositorio):
    with pytest.raises(TarefaNaoEncontrada):
        agenda.concluir_tarefa(99)
    with pytest.raises(ValueError):
        agenda.adicionar_tarefa(" ")
    assert repositorio.historico == []


def test_falha_ao_salvar_descarta_os_eventos_da_transacao(relogio):
    class RepoQueFalha(RepositorioMemoria):
        def salvar(self, dados, eventos=()):
            raise OSError("disco cheio")

    agenda = Agenda(RepoQueFalha(), relogio)
    with pytest.raises(OSError):
        agenda.adicionar_tarefa("x")
    assert agenda._eventos == []
