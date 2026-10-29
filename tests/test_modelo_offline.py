import pytest

from robofael.adaptadores.offline import ModeloOffline
from robofael.dominio.linguagem import descrever_agora, eh_despedida, pede_nova_conversa
from robofael.i18n import Tradutor


@pytest.fixture
def modelo(agenda, relogio):
    return ModeloOffline(agenda, relogio)


def falar(modelo, texto):
    return "".join(modelo.responder(texto))


def test_hora_e_data(modelo):
    assert falar(modelo, "Que horas são?") == "Agora são 16 horas e 25 minutos."
    assert falar(modelo, "que dia é hoje") == "Hoje é quarta-feira, 21/10/2026."


def test_aceita_a_nota_tarefa_como_o_google_transcreve(modelo, agenda):
    assert falar(modelo, "a nota tarefa comprar pão") == "Anotei: comprar pão."


def test_anota_tarefa_preservando_maiusculas(modelo, agenda):
    assert falar(modelo, "Anota tarefa Revisar PR da API") == "Anotei: Revisar PR da API."
    assert agenda.pendentes()[0].texto == "Revisar PR da API"


@pytest.mark.parametrize("qtd, esperado", [
    (0, "Você não tem tarefas pendentes."),
    (1, "Você tem 1 tarefa pendente. 1: t0."),
    (2, "Você tem 2 tarefas pendentes. 1: t0; 2: t1."),
])
def test_lista_tarefas_com_plural(modelo, agenda, qtd, esperado):
    for i in range(qtd):
        agenda.adicionar_tarefa(f"t{i}")
    assert falar(modelo, "quais são minhas tarefas?") == esperado


def test_conclui_tarefa_pelo_numero(modelo, agenda):
    agenda.adicionar_tarefa("Daily")
    assert falar(modelo, "terminei a tarefa 1") == "Boa! Tarefa Daily concluída."
    assert falar(modelo, "concluí a tarefa 7") == "Não achei essa tarefa."


@pytest.mark.parametrize("fala, resposta, texto, hora", [
    ("me lembra daqui a 1 minuto de beber água", "1 minuto", "beber água", "16:26"),
    ("lembre-me em 40 minutos para ligar pro João", "40 minutos", "ligar pro João", "17:05"),
])
def test_lembrete_relativo(modelo, agenda, fala, resposta, texto, hora):
    assert falar(modelo, fala) == f"Combinado, te lembro daqui a {resposta}."
    lembrete = agenda.proximos_lembretes()[0]
    assert (lembrete.texto, f"{lembrete.quando:%H:%M}") == (texto, hora)


def test_comando_desconhecido_explica_o_modo(modelo):
    assert falar(modelo, "conta uma piada") == Tradutor()("off.ajuda")
    assert modelo.online is False


@pytest.mark.parametrize("texto, esperado", [
    ("tchau, até amanhã", True), ("pode parar", True), ("Encerrar", True), ("paradoxo", False),
])
def test_despedida(texto, esperado):
    assert eh_despedida(texto) is esperado


def test_nova_conversa_e_descricao_de_data(relogio):
    assert pede_nova_conversa("vamos começar uma nova conversa")
    assert not pede_nova_conversa("conversa nova")
    assert descrever_agora(relogio()) == "quarta-feira, 2026-10-21 16:25"
