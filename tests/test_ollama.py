"""Modelo local (Ollama): camadas de resposta, ferramentas seguras, queda para o modo offline e
composição. O cliente HTTP é testado contra um servidor falso que fala o protocolo do Ollama."""

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from robofael import bootstrap
from robofael.adaptadores.ferramentas import ExecutorFerramentas
from robofael.adaptadores.offline import ModeloOffline
from robofael.adaptadores.ollama import (
    ESPERA_APOS_FALHA_S,
    FERRAMENTAS_LOCAIS,
    ClienteOllama,
    ModeloOllama,
    OllamaIndisponivel,
    escolher_modelo,
)
from robofael.configuracao import Configuracao
from robofael.dominio.linguagem import pede_agenda
from robofael.i18n import Idioma, Tradutor

AGORA = datetime(2026, 10, 23, 10, 15)


def texto(*pedacos):
    return [{"message": {"role": "assistant", "content": p}} for p in pedacos] + [{"done": True}]


def chamada(nome, argumentos):
    return [{"message": {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": nome, "arguments": argumentos}}]}}, {"done": True}]


class ClienteFalso:
    """Devolve as respostas roteirizadas, uma por chamada a /api/chat, e guarda os pedidos."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.pedidos: list[dict] = []
        self.fechados = 0

    def conversar(self, corpo):
        self.pedidos.append(json.loads(json.dumps(corpo)))  # cópia: o histórico muda depois
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        try:
            yield from resposta
        finally:
            self.fechados += 1


@pytest.fixture
def montar(agenda):
    def fabrica(*respostas, tradutor=None, monotonico=lambda: 0.0):
        tr = tradutor or Tradutor()
        cliente = ClienteFalso(*respostas)
        reserva = ModeloOffline(agenda, relogio=lambda: AGORA, tradutor=tr)
        modelo = ModeloOllama(cliente, "llama3.2:3b", ExecutorFerramentas(agenda), reserva, "Rafael",
                              tradutor=tr, relogio=lambda: AGORA, monotonico=monotonico)
        return modelo, cliente
    return fabrica


def falar(modelo, fala):
    return "".join(modelo.responder(fala))


# ---------- Camadas ----------
def test_comando_reconhecido_e_atendido_pelo_modo_offline_sem_chamar_o_modelo(montar, agenda):
    modelo, cliente = montar()
    assert falar(modelo, "anota tarefa comprar pão") == "Anotei: comprar pão."
    assert [t.texto for t in agenda.pendentes()] == ["comprar pão"] and cliente.pedidos == []
    assert modelo.historico[-1] == {"role": "assistant", "content": "Anotei: comprar pão."}  # contexto para depois


def test_conversa_vai_ao_modelo_sem_ferramentas_e_em_streaming(montar):
    modelo, cliente = montar(texto("Santos Dumont foi ", "um **inventor** brasileiro."))
    pedacos = list(modelo.responder("quem foi Santos Dumont?"))
    assert pedacos == ["Santos Dumont foi ", "um inventor brasileiro."]  # sem markdown: é falado
    pedido = cliente.pedidos[0]
    assert "tools" not in pedido and pedido["model"] == "llama3.2:3b" and pedido["keep_alive"]
    assert pedido["messages"][0]["role"] == "system" and "Robofael" in pedido["messages"][0]["content"]
    assert pedido["messages"][1]["content"].startswith("[Agora: sexta-feira, 2026-10-23 10:15]")


def test_pedido_de_agenda_livre_usa_so_as_ferramentas_seguras(montar, agenda):
    modelo, cliente = montar(chamada("criar_lembrete", {"texto": "reunião com o time", "quando": "2026-10-24T09:00"}),
                             texto("Combinado, te lembro amanhã às 9."))
    resposta = falar(modelo, "me lembra da reunião com o time no fim do mês")  # sem horário: vai ao modelo
    assert resposta == "Só um instante. Combinado, te lembro amanhã às 9."
    oferecidas = {f["function"]["name"] for f in cliente.pedidos[0]["tools"]}
    assert "criar_lembrete" in oferecidas and oferecidas <= FERRAMENTAS_LOCAIS  # só as seguras...
    assert not oferecidas & {"adicionar_tarefa", "consultar_historico"}  # ...e só as do assunto
    assert [(l.texto, l.quando) for l in agenda.proximos_lembretes()] == [("reunião com o time",
                                                                         datetime(2026, 10, 24, 9, 0))]
    resultado = cliente.pedidos[1]["messages"][-1]
    assert resultado["role"] == "tool" and resultado["tool_name"] == "criar_lembrete"
    assert '"ok": true' in resultado["content"]


def test_ferramenta_fora_da_lista_segura_e_recusada(montar, agenda):
    agenda.adicionar_tarefa("não pode sumir")
    modelo, cliente = montar(chamada("remover_tarefa", {"id": 1}), texto("Tudo bem."))
    falar(modelo, "tenho um compromisso que me deixa cansado")
    assert [t.texto for t in agenda.pendentes()] == ["não pode sumir"]
    assert "indisponível" in cliente.pedidos[1]["messages"][-1]["content"]


def test_entrada_mal_formada_e_corrigida_ou_devolvida_ao_modelo(montar):
    modelo, cliente = montar(chamada("listar_tarefas", {"incluir_concluidas": "false"}),  # texto em vez de booleano
                             chamada("consultar_historico", {"inicio": "ontem", "fim": "hoje"}),
                             texto("Não encontrei nada."))
    falar(modelo, "como está minha agenda?")
    assert '"tarefas"' in cliente.pedidos[1]["messages"][-1]["content"]  # "false" virou False
    assert '"erro"' in cliente.pedidos[2]["messages"][-1]["content"]  # data inválida: o modelo vê o erro


def test_chamada_escrita_como_json_no_texto_e_executada_e_nao_falada(montar, agenda):
    """O llama3.2 às vezes devolve a chamada como texto, em vez de tool_calls."""
    json_falado = '{"name": "criar_lembrete", "parameters": {"texto": "dentista", "quando": "2026-10-24T15:00"}}'
    modelo, cliente = montar(texto(json_falado), texto("Pronto, lembrete criado."))
    pedacos = list(modelo.responder("me lembra do dentista na semana que vem"))
    assert pedacos == ["Só um instante. ", "Pronto, lembrete criado."]  # aviso já; a resposta inteira no fim
    assert [l.texto for l in agenda.proximos_lembretes()] == ["dentista"]
    assert cliente.pedidos[0]["options"]["temperature"] == 0  # JSON estável


def test_json_quebrado_nunca_e_lido_em_voz_alta(montar, agenda):
    modelo, _ = montar(texto('{"name": "criar_lembrete", "parameters": {"quando": "am{'))
    assert falar(modelo, "me lembra da reunião no fim do mês") == "Só um instante. " + Tradutor()("claude.perdido")
    assert agenda.proximos_lembretes() == []


def test_historico_e_compactado_depois_de_usar_ferramentas(montar):
    """Sem JSON de chamadas e resultados nem carimbo de hora: no processador, cada token custa."""
    modelo, cliente = montar(chamada("listar_lembretes", {}), texto("Você não tem lembretes."), texto("De nada!"))
    falar(modelo, "tenho algum lembrete para amanhã?")
    assert modelo.historico == [{"role": "user", "content": "tenho algum lembrete para amanhã?"},
                                {"role": "assistant", "content": "Você não tem lembretes."}]
    falar(modelo, "obrigado")
    assert len(cliente.pedidos[2]["messages"]) == 4  # sistema + troca compactada + fala nova


# ---------- Falhas ----------
def test_ollama_fora_do_ar_responde_pelo_modo_offline_e_espera_antes_de_tentar_de_novo(montar):
    relogio = [100.0]
    modelo, cliente = montar(OllamaIndisponivel("recusou"), texto("De volta!"), monotonico=lambda: relogio[0])
    assert falar(modelo, "me conta uma piada") == Tradutor()("off.ajuda")  # exatamente o modo offline
    assert modelo.historico == []  # a rodada que falhou foi descartada
    assert falar(modelo, "e agora?") == Tradutor()("off.ajuda") and len(cliente.pedidos) == 1  # nem tentou
    relogio[0] += ESPERA_APOS_FALHA_S + 1
    assert falar(modelo, "e agora?") == "De volta!"


def test_queda_no_meio_da_resposta_nao_repete_pelo_modo_offline(montar):
    def corta():
        yield {"message": {"content": "Começando a resposta. "}}
        raise OllamaIndisponivel("caiu")

    modelo, _ = montar(corta())
    assert falar(modelo, "me explica a teoria da relatividade") == "Começando a resposta. " + Tradutor()(
        "local.problema")


def test_interromper_fecha_o_streaming_e_descarta_a_rodada(montar):
    modelo, cliente = montar(texto("Uma frase. ", "Outra frase. ", "Mais uma."))
    resposta = modelo.responder("me conta uma história")
    next(resposta)
    resposta.close()  # o orquestrador fecha o gerador ao interromper
    assert cliente.fechados == 1 and modelo.historico == []


def test_historico_acumula_contexto_e_reinicia(montar):
    modelo, cliente = montar(texto("Oi, Rafael!"), texto("Você disse oi."))
    falar(modelo, "oi")
    falar(modelo, "o que eu acabei de dizer?")
    assert [m["role"] for m in cliente.pedidos[1]["messages"]] == ["system", "user", "assistant", "user"]
    assert falar(modelo, "nova conversa") == Tradutor()("claude.nova_conversa") and modelo.historico == []


def test_troca_de_idioma_muda_instrucoes_e_recomeca(montar):
    tr = Tradutor()
    modelo, cliente = montar(texto("Oi!"), texto("Hi!"), tradutor=tr)
    falar(modelo, "olá")
    tr.idioma = Idioma.EN_US
    assert modelo.historico == []
    falar(modelo, "hello there")
    assert "American English" in cliente.pedidos[1]["messages"][0]["content"]


@pytest.mark.parametrize("fala, esperado", [
    ("amanhã às 9 me lembra da reunião", True), ("preciso anotar uma coisa", True),
    ("o que eu fiz ontem?", True), ("remind me to call mom", True),
    ("me conta uma curiosidade sobre o espaço", False), ("estou cansado hoje, alguma dica?", False),
])
def test_ferramentas_so_quando_a_fala_e_sobre_agenda(fala, esperado):
    assert pede_agenda(fala) is esperado


# ---------- Cliente HTTP (servidor falso com o protocolo do Ollama) ----------
class _Ollama(BaseHTTPRequestHandler):
    modelos = {"llama3.2:3b": ["completion", "tools"], "gemma:2b": ["completion"]}

    def log_message(self, *_a):
        pass

    def _json(self, dados):
        corpo = json.dumps(dados).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        self._json({"models": [{"name": n} for n in self.modelos]})

    def do_POST(self):
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            self._json({"capabilities": self.modelos.get(corpo["model"], [])})
        elif self.path == "/api/generate":
            self._json({"done": True})
        else:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for linha in texto("Olá ", "do servidor."):
                self.wfile.write(json.dumps(linha).encode() + b"\n")


@pytest.fixture
def servidor():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Ollama)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def test_cliente_http_lista_escolhe_e_transmite(servidor):
    cliente = ClienteOllama(servidor, timeout_s=5)
    assert cliente.modelos() == ["llama3.2:3b", "gemma:2b"]
    assert escolher_modelo(cliente, "llama3.2:3b") == "llama3.2:3b"
    assert escolher_modelo(cliente, "mistral") == "llama3.2:3b"  # não instalado: o primeiro com ferramentas
    pedacos = [p["message"]["content"] for p in cliente.conversar({"model": "llama3.2:3b", "messages": []})
               if "message" in p]
    assert pedacos == ["Olá ", "do servidor."]
    cliente.aquecer("llama3.2:3b")  # não levanta


def test_cliente_sem_servidor_levanta_indisponivel():
    cliente = ClienteOllama("http://127.0.0.1:9", timeout_s=2)
    with pytest.raises(OllamaIndisponivel):
        cliente.modelos()
    with pytest.raises(OllamaIndisponivel):
        list(cliente.conversar({"model": "x", "messages": []}))


# ---------- Escolha do cérebro ----------
@pytest.fixture
def nucleo(tmp_path, monkeypatch):
    import robofael.adaptadores.claude as claude

    monkeypatch.setattr(claude, "criar_cliente", lambda t: (_ for _ in ()).throw(TypeError("sem credenciais")))

    def fabrica(**env):
        base = {"ROBOFAEL_DADOS": str(tmp_path / "d"), "ROBOFAEL_CACHE": str(tmp_path / "c")}
        return bootstrap.montar_nucleo(Configuracao.do_ambiente({**base, **env}))
    return fabrica


def test_sem_claude_usa_o_modelo_local(nucleo, servidor):
    modelo = bootstrap._criar_modelo(nucleo(ROBOFAEL_OLLAMA_URL=servidor))
    assert isinstance(modelo, ModeloOllama) and modelo.modelo == "llama3.2:3b" and modelo.online


def test_sem_claude_e_sem_ollama_mantem_o_modo_offline(nucleo):
    modelo = bootstrap._criar_modelo(nucleo(ROBOFAEL_OLLAMA_URL="http://127.0.0.1:9"))
    assert type(modelo) is ModeloOffline and not modelo.online


def test_cerebro_pode_ser_forcado(nucleo, servidor):
    assert type(bootstrap._criar_modelo(nucleo(ROBOFAEL_OLLAMA_URL=servidor, ROBOFAEL_CEREBRO="offline"))) \
        is ModeloOffline
    assert isinstance(bootstrap._criar_modelo(nucleo(ROBOFAEL_OLLAMA_URL=servidor, ROBOFAEL_CEREBRO="ollama")),
                      ModeloOllama)
    assert Configuracao.do_ambiente({"ROBOFAEL_CEREBRO": "chatgpt"}).cerebro == "auto"  # valor inválido


def test_escrever_documento_usa_instrucoes_e_limite_proprios_sem_mexer_no_historico(montar):
    from robofael.adaptadores.ollama import OPCOES, OPCOES_DOCUMENTO

    modelo, cliente = montar(texto("# Energia solar\n\n", "**Painéis** convertem luz."))
    assert "".join(modelo.escrever("Escreva o texto de um documento sobre: energia solar")) == \
        "# Energia solar\n\n**Painéis** convertem luz."  # markdown preservado: vai para arquivo
    pedido = cliente.pedidos[0]
    assert pedido["options"] == OPCOES_DOCUMENTO and OPCOES_DOCUMENTO["num_predict"] > OPCOES["num_predict"]
    assert "documentos" in pedido["messages"][0]["content"] and "tools" not in pedido
    assert modelo.historico == []


def test_data_em_linguagem_natural_na_ferramenta_e_convertida(montar, agenda):
    """Em inglês o llama3.2 mandou quando='tomorrow 09:00' e o lembrete não era criado."""
    modelo, _ = montar(chamada("criar_lembrete", {"texto": ["team", "meeting"], "quando": "tomorrow 09:00"}),
                       texto("Done."))
    falar(modelo, "me lembra da reunião do time no fim do mês")
    criados = [(l.texto, l.quando) for l in agenda.proximos_lembretes()]
    assert criados == [("team meeting", datetime(2026, 10, 24, 9, 0))]


def test_criacao_recusada_nao_vira_mentira(montar, agenda):
    """O modelo dizia "I've set a reminder" mesmo com a ferramenta recusando a entrada."""
    modelo, _ = montar(chamada("criar_lembrete", {"texto": "x", "quando": "someday"}),
                       texto("I've set a reminder for you."))
    resposta = falar(modelo, "me lembra disso no fim do mês")
    assert resposta == "Só um instante. " + Tradutor()("local.nao_criou") and agenda.proximos_lembretes() == []
