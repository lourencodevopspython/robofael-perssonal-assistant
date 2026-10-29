"""Composição (bootstrap) e interface Tk com serviços simulados."""

import time

import pytest

from conftest import ReconhecedorFalso, ReprodutorFalso, SintetizadorFalso, requer_fotos
from robofael import bootstrap
from robofael.adaptadores.offline import ModeloOffline
from robofael.aplicacao import sessao
from robofael.aplicacao.orquestrador import Orquestrador
from robofael.configuracao import Configuracao
from robofael.dominio.estados import Estado
from robofael.dominio.eventos import AgendaAtualizada


@pytest.fixture
def config(tmp_path):
    # Ollama apontado para uma porta sem servidor: o teste não depende do que está instalado na máquina
    return Configuracao.do_ambiente({"ROBOFAEL_DADOS": str(tmp_path / "dados"), "ROBOFAEL_CACHE": str(tmp_path / "c"),
                                     "ROBOFAEL_USUARIO": "Ana", "ROBOFAEL_OLLAMA_URL": "http://127.0.0.1:9"})


def test_nucleo_publica_mudancas_da_agenda(config):
    nucleo = bootstrap.montar_nucleo(config)
    recebidos = []
    nucleo.barramento.assinar(AgendaAtualizada, recebidos.append)
    nucleo.agenda.adicionar_tarefa("x")
    nucleo.barramento.despachar()
    assert len(recebidos) == 1 and config.arquivo_banco.exists()
    assert nucleo.banco.total_eventos() == 1  # o histórico registrou a criação


def test_saudacao(config):
    nucleo = bootstrap.montar_nucleo(config)
    assert sessao.saudacao(nucleo, online=True) == "Olá, Ana! Eu sou o Robofael, seu assistente do dia a dia."
    nucleo.agenda.adicionar_tarefa("a")
    nucleo.agenda.adicionar_tarefa("b")
    assert "Você tem 2 tarefas pendentes. Estou no modo offline" in sessao.saudacao(nucleo, online=False)
    assert sessao.saudacao(nucleo, True, ativacao_por_voz=True).endswith("Para me chamar, é só dizer: ok Fael.")


def test_iniciar_servicos_compoe_e_cai_para_offline(config, monkeypatch):
    import robofael.adaptadores.claude as claude
    import robofael.adaptadores.reprodutor as reprodutor

    monkeypatch.setattr(claude, "criar_cliente", lambda t: (_ for _ in ()).throw(RuntimeError("sem chave")))
    monkeypatch.setattr(bootstrap, "_criar_microfone", lambda *a: None)
    monkeypatch.setattr(bootstrap, "_criar_ativador", lambda *a: pytest.fail("sem microfone, sem ativador"))
    monkeypatch.setattr(reprodutor, "ReprodutorPygame", ReprodutorFalso)
    nucleo = bootstrap.montar_nucleo(config)
    servicos = bootstrap.iniciar_servicos(nucleo)
    assert isinstance(servicos.orquestrador.modelo, ModeloOffline)
    assert (servicos.online, servicos.microfone, servicos.ativacao_por_voz) == (False, False, False)
    anunciados = []
    monkeypatch.setattr(servicos.orquestrador, "anunciar", anunciados.append)
    nucleo.agenda.criar_lembrete("beber água", "2000-01-01T00:00")
    servicos.agendador.verificar()
    assert anunciados == ["Ana, lembrete: beber água."]


# ---------- Interface ----------
def bombear(raiz, segundos=0.3, ate=None):
    fim = time.monotonic() + segundos
    while time.monotonic() < fim and not (ate and ate()):
        raiz.update()
        time.sleep(0.005)


@pytest.mark.lento
@requer_fotos
def test_janela_completa_com_servicos_simulados(raiz, config, monkeypatch):
    from robofael.apresentacao import app as mod_app

    nucleo = bootstrap.montar_nucleo(config)

    def servicos_falsos(n, continuo=False):
        orq = Orquestrador(ModeloOffline(n.agenda), SintetizadorFalso(), ReprodutorFalso(duracao=0.05),
                           n.barramento, ReconhecedorFalso("anota tarefa testar a interface"), continuo)
        from robofael.aplicacao.agendador import AgendadorLembretes
        return sessao.Servicos(orq, AgendadorLembretes(n.agenda, lambda l: None), False, True)

    monkeypatch.setattr(mod_app, "iniciar_servicos", servicos_falsos)
    janela = mod_app.Janela(raiz, nucleo, "cracha")
    # Espera pelo que a TELA mostra (eventos já despachados), não só pelo estado interno
    bombear(raiz, 20, ate=lambda: janela.servicos is not None and janela.palco.quadros is not None
            and not janela.servicos.orquestrador.ocupado and janela.palco.estado is Estado.PARADO)
    assert janela.palco.quadros is not None
    assert janela.palco.estado is Estado.PARADO  # saudação já foi falada

    janela._alternar_microfone()  # ESPAÇO
    bombear(raiz, 10, ate=lambda: "testar a interface" in janela.painel.lista_tarefas.get(0)
            and janela.palco.estado is Estado.PARADO)
    assert [t.texto for t in nucleo.agenda.pendentes()] == ["testar a interface"]
    assert "testar a interface" in janela.painel.lista_tarefas.get(0)  # painel atualizado por evento

    janela.painel.lista_tarefas.selection_set(0)
    janela.painel._alternar_tarefa()  # duplo clique conclui
    bombear(raiz, 5, ate=lambda: janela.painel.lista_tarefas.get(0).startswith("✓"))
    assert nucleo.agenda.pendentes() == [] and janela.painel.lista_tarefas.get(0).startswith("✓")

    janela.entrada.focus_force()
    janela._focar_entrada()
    janela.entrada.insert(0, "que dia é hoje")
    janela._enviar_texto()
    bombear(raiz, 10, ate=lambda: "Hoje é" in janela.canvas.itemcget(janela.palco.txt_robo, "text"))
    assert "Hoje é" in janela.canvas.itemcget(janela.palco.txt_robo, "text")
    janela.encerrar()
