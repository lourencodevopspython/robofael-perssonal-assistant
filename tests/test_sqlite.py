"""Memória de longo prazo em SQLite: persistência, histórico auditável, migração e preferências."""

import json
import sqlite3
import threading
from datetime import datetime, timedelta

import pytest

from conftest import AGORA
from robofael.adaptadores.repositorio_json import RepositorioJson
from robofael.adaptadores.sqlite import BancoSqlite
from robofael.dominio.agenda import Agenda
from robofael.dominio.modelos import DadosAgenda, Lembrete, RegistroAuditoria, Tarefa, TipoEvento
from robofael.portas import Preferencias


@pytest.fixture
def banco(tmp_path):
    b = BancoSqlite(tmp_path / "memoria.db")
    yield b
    b.fechar()


def evento(tipo, id_, texto, quando):
    return RegistroAuditoria(tipo, id_, texto, quando, {"x": 1})


def test_banco_novo_tem_esquema_versionado_e_vazio(banco):
    assert banco.versao_esquema == 2 and banco.vazio()
    assert banco.carregar() == DadosAgenda()


def test_reabrir_nao_reaplica_migracao(tmp_path):
    BancoSqlite(tmp_path / "m.db").fechar()
    assert BancoSqlite(tmp_path / "m.db").versao_esquema == 2


def test_salva_e_recarrega_estado_completo(tmp_path):
    arquivo = tmp_path / "memoria.db"
    dados = DadosAgenda([Tarefa(1, "Revisar PR", AGORA, True, AGORA + timedelta(hours=1)), Tarefa(2, "Daily", AGORA)],
                        [Lembrete(3, "água", AGORA, avisado=True)], 4)
    b = BancoSqlite(arquivo)
    b.salvar(dados)
    b.fechar()
    assert BancoSqlite(arquivo).carregar() == dados


def test_estado_e_historico_sao_gravados_juntos(banco):
    banco.salvar(DadosAgenda([Tarefa(1, "x", AGORA)], [], 2), [evento(TipoEvento.TAREFA_CRIADA, 1, "x", AGORA)])
    assert len(banco.carregar().tarefas) == 1 and banco.total_eventos() == 1


def test_falha_no_meio_desfaz_estado_e_historico(banco):
    banco.salvar(DadosAgenda([Tarefa(1, "original", AGORA)], [], 2))
    duplicadas = DadosAgenda([Tarefa(5, "a", AGORA), Tarefa(5, "b", AGORA)], [], 6)  # id repetido: erro
    with pytest.raises(sqlite3.IntegrityError):
        banco.salvar(duplicadas, [evento(TipoEvento.TAREFA_CRIADA, 5, "a", AGORA)])
    assert [t.texto for t in banco.carregar().tarefas] == ["original"]
    assert banco.total_eventos() == 0


@pytest.mark.parametrize("sql", ["UPDATE historico SET descricao = 'falso'", "DELETE FROM historico"])
def test_historico_e_somente_acrescimo(banco, sql):
    banco.salvar(DadosAgenda(), [evento(TipoEvento.TAREFA_CRIADA, 1, "x", AGORA)])
    with pytest.raises(sqlite3.IntegrityError, match="somente acréscimo"):
        banco._con.execute(sql)
    assert banco.total_eventos() == 1


def test_cadeia_de_hashes_integra(banco):
    for i in range(5):
        banco.salvar(DadosAgenda(), [evento(TipoEvento.TAREFA_CRIADA, i, f"t{i}", AGORA + timedelta(minutes=i))])
    resultado = banco.verificar_integridade()
    assert resultado.ok and resultado.registros == 5


def _adulterar(banco, sql):
    """Simula alguém mexendo no arquivo por fora: derruba as travas e altera."""
    banco._con.executescript("DROP TRIGGER historico_sem_alteracao; DROP TRIGGER historico_sem_remocao;")
    banco._con.execute(sql)


@pytest.mark.parametrize("sql, motivo, seq", [
    ("UPDATE historico SET descricao = 'outra coisa' WHERE seq = 3", "conteúdo alterado", 3),
    ("UPDATE historico SET ocorrido_em = '2020-01-01T00:00:00' WHERE seq = 2", "conteúdo alterado", 2),
    ("DELETE FROM historico WHERE seq = 2", "registro removido antes deste", 3),
    ("UPDATE historico SET hash_anterior = 'x' WHERE seq = 4", "encadeamento quebrado", 4),
])
def test_adulteracao_e_detectada(banco, sql, motivo, seq):
    for i in range(5):
        banco.salvar(DadosAgenda(), [evento(TipoEvento.TAREFA_CRIADA, i, f"t{i}", AGORA)])
    _adulterar(banco, sql)
    resultado = banco.verificar_integridade()
    assert not resultado.ok and resultado.motivo == motivo and resultado.primeiro_problema == seq


def test_consulta_por_periodo_e_tipo(banco):
    eventos = [evento(TipoEvento.TAREFA_CRIADA, 1, "ontem", datetime(2026, 10, 20, 23, 59)),
               evento(TipoEvento.TAREFA_CONCLUIDA, 1, "dentro", datetime(2026, 10, 21, 0, 0)),
               evento(TipoEvento.LEMBRETE_AVISADO, 2, "dentro2", datetime(2026, 10, 21, 22, 0)),
               evento(TipoEvento.TAREFA_CRIADA, 3, "amanha", datetime(2026, 10, 22, 0, 0))]
    banco.salvar(DadosAgenda(), eventos)
    dia = (datetime(2026, 10, 21), datetime(2026, 10, 22))
    assert [e.descricao for e in banco.eventos(*dia)] == ["dentro", "dentro2"]  # fim exclusivo
    assert [e.descricao for e in banco.eventos(*dia, tipos=[TipoEvento.TAREFA_CONCLUIDA])] == ["dentro"]
    assert banco.eventos(*dia)[0].dados == {"x": 1}


def test_agenda_real_sobre_o_sqlite(banco, relogio):
    agenda = Agenda(banco, relogio)
    t = agenda.adicionar_tarefa("Revisar PR")
    agenda.concluir_tarefa(t.id)
    recarregada = Agenda(banco, relogio)
    assert recarregada.tarefas(incluir_concluidas=True)[0].concluida_em == AGORA
    assert [e.tipo for e in banco.eventos(AGORA, AGORA + timedelta(minutes=1))] == [
        TipoEvento.TAREFA_CRIADA, TipoEvento.TAREFA_CONCLUIDA]
    assert banco.verificar_integridade().ok


def test_escritas_concorrentes_mantem_a_cadeia(banco):
    agenda = Agenda(banco)
    threads = [threading.Thread(target=lambda i=i: agenda.adicionar_tarefa(f"t{i}")) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(banco.carregar().tarefas) == 20 and banco.total_eventos() == 20
    assert banco.verificar_integridade().ok


def test_importa_o_json_antigo_uma_unica_vez(tmp_path, banco):
    antigo = tmp_path / "agenda.json"
    RepositorioJson(antigo).salvar(DadosAgenda(
        [Tarefa(1, "antiga", datetime(2026, 10, 1, 9)), Tarefa(2, "feita", datetime(2026, 10, 2, 9), True,
                                                               datetime(2026, 10, 3, 10))],
        [Lembrete(3, "daily", datetime(2026, 10, 30, 9))], 4))
    assert banco.importar_json(antigo, agora=AGORA)
    assert not antigo.exists() and list(tmp_path.glob("agenda.json.migrado-*"))  # nada apagado
    assert [t.texto for t in banco.carregar().tarefas] == ["antiga", "feita"]
    tipos = [e.tipo for e in banco.eventos(datetime(2026, 1, 1), datetime(2027, 1, 1))]
    assert tipos == [TipoEvento.TAREFA_CRIADA, TipoEvento.TAREFA_CRIADA, TipoEvento.TAREFA_CONCLUIDA,
                     TipoEvento.LEMBRETE_CRIADO]
    RepositorioJson(antigo).salvar(DadosAgenda([Tarefa(9, "x", AGORA)], [], 10))
    assert not banco.importar_json(antigo)  # banco já tem dados: não importa de novo


def test_sem_json_nao_importa(tmp_path, banco):
    assert not banco.importar_json(tmp_path / "nao_existe.json")


def test_preferencias(banco):
    assert banco.carregar_preferencias() == Preferencias()
    banco.salvar_preferencias(Preferencias(avatar="selfie", voz="pt-BR-AntonioNeural", tom="-21Hz",
                                           ativacao_por_voz=False))
    assert banco.carregar_preferencias() == Preferencias("selfie", "pt-BR-AntonioNeural", "-21Hz", None, False)
    banco.salvar_preferencias(Preferencias(avatar="cracha"))  # None remove o ajuste
    assert banco.carregar_preferencias() == Preferencias(avatar="cracha")
    linhas = banco._con.execute("SELECT valor FROM preferencias").fetchall()
    assert [json.loads(r[0]) for r in linhas] == ["cracha"]
