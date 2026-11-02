"""Trocar o idioma por voz, tarefas e lembretes traduzidos para o idioma da interface e concluir todas
as tarefas de uma vez."""

import contextlib
import json
import sqlite3
import threading

import pytest

from conftest import ReprodutorFalso, SintetizadorFalso
from robofael import bootstrap
from robofael.adaptadores import traducao_textos
from robofael.adaptadores.ferramentas import ExecutorFerramentas
from robofael.adaptadores.offline import ModeloOffline
from robofael.adaptadores.ollama import ModeloOllama
from robofael.adaptadores.sqlite import BancoSqlite
from robofael.aplicacao import sessao
from robofael.aplicacao.barramento import Barramento
from robofael.aplicacao.orquestrador import Orquestrador
from robofael.aplicacao.traducao import TraducaoAgenda
from robofael.configuracao import Configuracao
from robofael.dominio.estados import Estado
from robofael.dominio.eventos import IdiomaMudou, RespostaConcluida
from robofael.dominio.linguagem import pede_troca_idioma
from robofael.dominio.modelos import TipoEvento
from robofael.i18n import Idioma, Tradutor
from robofael.portas import TradutorTextos

PT, EN = Idioma.PT_BR, Idioma.EN_US


# ---------- Concluir todas as tarefas ----------
def test_concluir_todas_numa_so_transacao(agenda, repositorio, relogio):
    for texto in ("pagar a luz", "comprar pão", "ligar para o dentista"):
        agenda.adicionar_tarefa(texto)
    agenda.concluir_tarefa(2)
    salvamentos = len(repositorio.historico)
    concluidas = agenda.concluir_todas()
    assert [t.texto for t in concluidas] == ["pagar a luz", "ligar para o dentista"]
    assert agenda.pendentes() == [] and all(t.concluida_em == relogio.agora.replace(second=0) for t in concluidas)
    novos = repositorio.historico[salvamentos:]
    assert [(e.tipo, e.entidade_id) for e in novos] == [(TipoEvento.TAREFA_CONCLUIDA, 1),
                                                        (TipoEvento.TAREFA_CONCLUIDA, 3)]
    assert agenda.concluir_todas() == []  # nada pendente: nem transação nem evento
    assert len(repositorio.historico) == salvamentos + 2


@pytest.mark.parametrize("fala", [
    "concluir todas as tarefas", "Conclua todas as minhas tarefas", "marca todas as tarefas como feitas",
    "finalizar todas as tarefas", "complete all tasks", "mark all of my tasks as done", "finish all the tasks"])
def test_comando_concluir_todas(agenda, relogio, fala):
    agenda.adicionar_tarefa("pagar a luz")
    agenda.adicionar_tarefa("comprar pão")
    assert ModeloOffline(agenda, relogio).tentar(fala) == "Pronto! Concluí 2 tarefas."
    assert agenda.pendentes() == []


def test_concluir_todas_sem_pendentes_e_em_ingles(agenda, relogio):
    offline = ModeloOffline(agenda, relogio)
    assert offline.tentar("concluir todas as tarefas") == "Você não tem tarefas pendentes para concluir."
    agenda.adicionar_tarefa("buy milk")
    em_ingles = ModeloOffline(agenda, relogio, tradutor=Tradutor(EN))
    assert em_ingles.tentar("complete all my tasks") == "Done! I completed 1 task."


@pytest.mark.parametrize("fala", ["concluí todas as tarefas?", "quais tarefas eu concluí ontem?",
                                  "concluir a tarefa 1", "anota tarefa revisar todas as tarefas do projeto"])
def test_nao_conclui_todas_por_engano(agenda, relogio, fala):
    agenda.adicionar_tarefa("pagar a luz")
    agenda.adicionar_tarefa("comprar pão")
    ModeloOffline(agenda, relogio).tentar(fala)
    assert len(agenda.pendentes()) >= 1


def test_ferramenta_concluir_todas(agenda):
    agenda.adicionar_tarefa("a")
    agenda.adicionar_tarefa("b")
    saida = ExecutorFerramentas(agenda).executar("concluir_todas_tarefas", {})
    assert saida["ok"] and saida["total"] == 2 and [t["texto"] for t in saida["concluidas"]] == ["a", "b"]
    assert agenda.pendentes() == []


# ---------- Trocar o idioma por voz ----------
@pytest.mark.parametrize("fala, idioma", [
    ("mudar para inglês", EN), ("Mudar para Inglês.", EN), ("ok fael, mudar para ingles", EN),
    ("mudar para português", PT), ("muda o idioma pra portugues", PT), ("fale em inglês", EN),
    ("responda em português, por favor", PT), ("change to English", EN), ("switch the language to Portuguese", PT),
    ("speak portuguese please", PT), ("hey fael, change language to english", EN)])
def test_pedidos_de_troca_de_idioma(fala, idioma):
    assert pede_troca_idioma(fala) is idioma


@pytest.mark.parametrize("fala", ["como se fala cachorro em inglês?", "traduz bom dia para inglês",
                                  "anota tarefa estudar inglês", "mudar o horário da aula de inglês",
                                  "how do you say dog in portuguese"])
def test_falas_sobre_idioma_que_nao_sao_pedidos(fala):
    assert pede_troca_idioma(fala) is None


class ModeloEco:
    online = True

    def __init__(self):
        self.falas = []

    def reiniciar(self):
        pass

    def responder(self, fala):
        self.falas.append(fala)
        yield "resposta do modelo"


def _orquestrador(tr, trocar=None):
    barramento = Barramento()
    respostas = []
    barramento.assinar(RespostaConcluida, lambda e: respostas.append(e.texto))
    modelo = ModeloEco()
    orq = Orquestrador(modelo, SintetizadorFalso(), ReprodutorFalso(), barramento, tradutor=tr)
    orq.trocar_idioma = trocar
    orq.estados.ir_para(Estado.PARADO)

    def enviar(texto):
        assert orq.enviar_texto(texto)
        orq.aguardar()
        barramento.despachar()

    return orq, modelo, respostas, enviar


def test_troca_de_idioma_por_voz_confirma_no_idioma_novo():
    tr = Tradutor(PT)
    trocas = []

    def trocar(idioma):
        trocas.append(idioma)
        tr.idioma = idioma

    _orq, modelo, respostas, enviar = _orquestrador(tr, trocar)
    enviar("mudar para inglês")
    assert trocas == [EN] and respostas == ["Okay! From now on I'll speak English."]
    enviar("change to English")
    assert trocas == [EN] and respostas[-1] == "I'm already speaking English."
    enviar("mudar para português")
    assert trocas == [EN, PT] and respostas[-1] == "Pronto! A partir de agora eu falo português."
    assert modelo.falas == []  # nenhum desses pedidos foi ao modelo


def test_sem_quem_troque_o_pedido_vai_ao_modelo():
    _orq, modelo, respostas, enviar = _orquestrador(Tradutor(PT))
    enviar("mudar para inglês")
    assert modelo.falas == ["mudar para inglês"] and respostas == ["resposta do modelo"]


@pytest.fixture
def config(tmp_path):
    return Configuracao.do_ambiente({"ROBOFAEL_DADOS": str(tmp_path / "d"), "ROBOFAEL_CEREBRO": "offline"})


class SintConfiguravel:
    voz, tom, ritmo, gtts = "pt-BR-AntonioNeural", "-10Hz", "+5%", ("pt", "com.br")

    def configurar(self, voz, tom, ritmo, gtts=None):
        self.voz, self.tom, self.ritmo, self.gtts = voz, tom, ritmo, gtts


def test_troca_por_voz_vale_ao_vivo_e_nas_proximas_aberturas(config):
    nucleo = bootstrap.montar_nucleo(config)
    mudancas = []
    nucleo.barramento.assinar(IdiomaMudou, mudancas.append)
    servicos = sessao.Servicos(None, None, False, False, sintetizador=SintConfiguravel())  # type: ignore[arg-type]
    sessao.trocar_idioma(nucleo, servicos, EN)
    nucleo.barramento.despachar()
    assert nucleo.tradutor.idioma is EN and mudancas == [IdiomaMudou(EN)]  # a interface se retraduz
    assert (servicos.sintetizador.voz, servicos.sintetizador.gtts) == ("en-US-AndrewNeural", ("en", "com"))
    assert bootstrap.montar_nucleo(config).tradutor.idioma is EN  # a escolha foi salva


# ---------- Tradução de tarefas e lembretes ----------
class MotorFalso:
    """Traduz por dicionário; registra cada pedido."""

    DICIONARIO = {("comprar pão", "en-US"): "buy bread", ("buy milk", "pt-BR"): "comprar leite",
                  ("Daily com o time", "en-US"): "Team daily"}

    def __init__(self, falhar=False):
        self.pedidos, self.falhar = [], falhar

    def traduzir(self, textos, idioma):
        self.pedidos.append((list(textos), idioma))
        if self.falhar:
            raise ConnectionError("sem rede")
        return [self.DICIONARIO.get((t, idioma), t) for t in textos]


@pytest.fixture
def banco():
    b = BancoSqlite(":memory:")
    yield b
    b.fechar()


@pytest.fixture
def traducoes(agenda, banco):
    tr = Tradutor(EN)
    servico = TraducaoAgenda(agenda, banco, tr, espera_s=60)  # o temporizador não dispara durante o teste
    yield servico
    servico.motor = None
    if servico._temporizador:
        servico._temporizador.cancel()


def test_traduz_o_que_aparece_no_painel_uma_unica_vez(agenda, banco, traducoes):
    agenda.adicionar_tarefa("comprar pão")
    agenda.adicionar_tarefa("buy milk")
    agenda.criar_lembrete("Daily com o time", "2099-01-01T09:00")
    assert traducoes.exibir("comprar pão") == "comprar pão"  # sem tradução ainda: o original
    motor = MotorFalso()
    traducoes.motor = motor
    assert traducoes.traduzir_pendentes()
    assert motor.pedidos == [(["comprar pão", "buy milk", "Daily com o time"], "en-US")]
    assert [traducoes.exibir(t) for t in ("comprar pão", "buy milk", "Daily com o time")] == \
        ["buy bread", "buy milk", "Team daily"]
    assert not traducoes.traduzir_pendentes() and len(motor.pedidos) == 1  # nada novo: não pergunta de novo
    assert banco.traducoes("en-US")["comprar pão"] == "buy bread"  # guardado: vale nas próximas aberturas

    traducoes.tr.idioma = PT
    assert traducoes.exibir("buy milk") == "buy milk"
    traducoes.traduzir_pendentes()
    assert motor.pedidos[-1] == (["comprar pão", "buy milk", "Daily com o time"], "pt-BR")
    assert traducoes.exibir("buy milk") == "comprar leite" and traducoes.exibir("comprar pão") == "comprar pão"


def test_so_as_ultimas_concluidas_e_os_lembretes_futuros(agenda, traducoes):
    for i in range(8):
        agenda.adicionar_tarefa(f"feita {i}")
    agenda.concluir_todas()
    agenda.adicionar_tarefa("pendente")
    lembrete = agenda.criar_lembrete("já avisado", "2000-01-01T00:00")
    agenda.retirar_vencidos()
    assert traducoes.visiveis() == ["pendente", "feita 3", "feita 4", "feita 5", "feita 6", "feita 7"]
    assert lembrete.texto not in traducoes.visiveis()


def test_falha_ao_traduzir_mostra_o_original_e_espera_antes_de_tentar_de_novo(agenda, traducoes):
    agenda.adicionar_tarefa("comprar pão")
    traducoes.motor = motor = MotorFalso(falhar=True)
    assert not traducoes.traduzir_pendentes()
    assert traducoes.exibir("comprar pão") == "comprar pão"
    traducoes.traduzir_pendentes()
    assert len(motor.pedidos) == 1  # em pausa depois da falha


def test_resposta_com_quantidade_errada_nao_e_usada(agenda, traducoes):
    agenda.adicionar_tarefa("comprar pão")
    agenda.adicionar_tarefa("buy milk")

    class MotorQuePula:
        def traduzir(self, textos, idioma):
            return ["buy bread"]

    traducoes.motor = MotorQuePula()
    assert not traducoes.traduzir_pendentes()
    assert traducoes.exibir("buy milk") == "buy milk" and traducoes.exibir("comprar pão") == "comprar pão"


def test_traducao_que_vira_explicacao_fica_com_o_original(agenda, traducoes):
    agenda.adicionar_tarefa("pão")

    class MotorFalador:
        def traduzir(self, textos, idioma):
            return ["Here is the translation of your to-do item into English: it means bread, a common food."]

    traducoes.motor = MotorFalador()
    traducoes.traduzir_pendentes()
    assert traducoes.exibir("pão") == "pão"


def test_conversa_tem_prioridade_sobre_a_traducao(agenda, traducoes):
    agenda.adicionar_tarefa("comprar pão")
    traducoes.motor = motor = MotorFalso()
    traducoes.ocupado = lambda: True
    assert not traducoes.traduzir_pendentes() and motor.pedidos == []
    traducoes.ocupado = lambda: False
    assert traducoes.traduzir_pendentes()


def test_agenda_mudou_pede_traducao_em_segundo_plano(agenda, banco):
    pronto = threading.Event()
    servico = TraducaoAgenda(agenda, banco, Tradutor(EN), pronto.set, espera_s=0.01)
    servico.definir_motor(MotorFalso())
    agenda.adicionar_tarefa("comprar pão")
    assert pronto.wait(5) and servico.exibir("comprar pão") == "buy bread"


def test_modo_offline_nao_traduz(agenda, traducoes, relogio):
    traducoes.definir_motor(ModeloOffline(agenda, relogio))
    assert traducoes.motor is None
    assert isinstance(MotorFalso(), TradutorTextos)


def test_cache_de_traducoes_no_sqlite_e_migracao(tmp_path):
    arquivo = tmp_path / "v1.db"
    con = sqlite3.connect(arquivo)  # banco da versão anterior: sem a tabela de traduções
    con.executescript("CREATE TABLE x (y); PRAGMA user_version = 1;")
    con.close()
    with contextlib.suppress(sqlite3.OperationalError):  # só a migração v2 roda sobre o v1
        BancoSqlite(arquivo).fechar()
    banco = BancoSqlite(tmp_path / "novo.db")
    banco.guardar_traducoes("en-US", {"comprar pão": "buy bread", "pagar": "pay"})
    banco.guardar_traducoes("en-US", {"pagar": "pay the bill"})
    banco.guardar_traducoes("pt-BR", {"buy milk": "comprar leite"})
    assert banco.traducoes("en-US") == {"comprar pão": "buy bread", "pagar": "pay the bill"}
    assert banco.traducoes("pt-BR") == {"buy milk": "comprar leite"}
    assert banco.verificar_integridade().ok  # traduções ficam fora da cadeia de hashes do histórico
    banco.fechar()


# ---------- Pedido de tradução aos modelos ----------
def test_itens_vao_e_voltam_numerados():
    assert json.loads(traducao_textos.entrada(["comprar pão", "buy milk"])) == {"1": "comprar pão", "2": "buy milk"}
    assert traducao_textos.esquema(2)["required"] == ["1", "2"]
    resposta = '```json\n{"2": "Buy milk", "1": "Buy bread"}\n```'
    assert traducao_textos.ler_traducoes(resposta, 2) == ["Buy bread", "Buy milk"]  # pela chave, não pela ordem
    for ruim in ('{"1": "Buy bread"}', "não sei", '{"1": "a", "2": 3}', '["a", "b"]'):
        with pytest.raises(ValueError):
            traducao_textos.ler_traducoes(ruim, 2)
    assert "English (US)" in traducao_textos.instrucoes("en-US")


class ClienteOllamaTradutor:
    def __init__(self, resposta):
        self.resposta, self.corpos = resposta, []

    def conversar(self, corpo):
        self.corpos.append(corpo)
        meio = len(self.resposta) // 2
        yield {"message": {"content": self.resposta[:meio]}}
        yield {"message": {"content": self.resposta[meio:]}, "done": True}


def test_ollama_traduz_sem_historico_e_com_esquema(agenda, relogio):
    cliente = ClienteOllamaTradutor('{"1": "Buy bread", "2": "Call the dentist"}')
    modelo = ModeloOllama(cliente, "llama3.2:3b", ExecutorFerramentas(agenda), ModeloOffline(agenda, relogio),
                          "Rafael")
    assert isinstance(modelo, TradutorTextos)
    assert modelo.traduzir(["comprar pão", "ligar para o dentista"], "en-US") == ["Buy bread", "Call the dentist"]
    corpo = cliente.corpos[0]
    assert corpo["format"] == traducao_textos.esquema(2) and corpo["options"]["temperature"] == 0.0
    assert "tools" not in corpo and modelo.historico == []


def test_claude_traduz_fora_do_historico(agenda, cliente_falso):
    from conftest import bloco_texto, resposta
    from robofael.adaptadores.claude import ModeloClaude

    cliente = cliente_falso(resposta("end_turn", bloco_texto('{"1": "comprar leite"}')))
    modelo = ModeloClaude(cliente, ExecutorFerramentas(agenda), "Rafael")
    assert modelo.traduzir(["buy milk"], "pt-BR") == ["comprar leite"]
    assert modelo.historico == []
    assert "tools" not in cliente.chamadas[0]
