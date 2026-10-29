import json

import anthropic
import httpx2
import pytest

from conftest import bloco_ferramenta, bloco_texto, resposta
from robofael.adaptadores.claude import (
    MAX_RODADAS_FERRAMENTAS,
    MSG_NOVA_CONVERSA,
    MSG_PERDIDO,
    MSG_RECUSA,
    ModeloClaude,
)
from robofael.adaptadores.ferramentas import FERRAMENTAS, ExecutorFerramentas

REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


@pytest.fixture
def criar(agenda, relogio):
    def _criar(cliente, **kw):
        return ModeloClaude(cliente, ExecutorFerramentas(agenda), "Rafael", relogio=relogio, **kw)
    return _criar


def falar(modelo, texto):
    return "".join(modelo.responder(texto)).strip()


def test_transmite_texto_em_pedacos_com_parametros_esperados(criar, cliente_falso):
    cliente = cliente_falso(resposta("end_turn", bloco_texto("Bom dia! Tudo certo?")))
    modelo = criar(cliente)
    pedacos = list(modelo.responder("oi"))
    assert len(pedacos) == 4 and "".join(pedacos).strip() == "Bom dia! Tudo certo?"  # streaming real

    chamada = cliente.chamadas[0]
    assert chamada["model"] == "claude-opus-5-5"
    assert chamada["tools"] == FERRAMENTAS
    assert chamada["fallbacks"] == "default" and chamada["betas"] == ["server-side-fallback-2026-07-01"]
    assert chamada["output_config"] == {"effort": "low"}
    assert chamada["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Rafael" in chamada["system"][0]["text"]
    assert chamada["system"][0]["text"].startswith("Você é o Robofael,")
    assert chamada["messages"][0]["content"] == "[Agora: quarta-feira, 2026-10-21 16:25]\noi"


def test_usa_ferramenta_e_continua(criar, cliente_falso, agenda):
    cliente = cliente_falso(
        resposta("tool_use", bloco_texto("Vou anotar."),
                 bloco_ferramenta("adicionar_tarefa", {"texto": "Revisar PR"}, "toolu_9")),
        resposta("end_turn", bloco_texto("Pronto, anotei.")),
    )
    modelo = criar(cliente)
    assert falar(modelo, "anota revisar PR") == "Vou anotar. Pronto, anotei."
    assert [t.texto for t in agenda.pendentes()] == ["Revisar PR"]
    resultado = cliente.chamadas[1]["messages"][-1]["content"][0]
    assert resultado["tool_use_id"] == "toolu_9" and "is_error" not in resultado
    assert json.loads(resultado["content"])["tarefa"]["texto"] == "Revisar PR"
    assert [m["role"] for m in modelo.historico] == ["user", "assistant", "user", "assistant"]


def test_entrada_invalida_da_ferramenta_volta_como_erro_sem_executar(criar, cliente_falso, agenda):
    cliente = cliente_falso(
        resposta("tool_use", bloco_ferramenta("adicionar_tarefa", {"texto": 42})),
        resposta("end_turn", bloco_texto("Ok.")),
    )
    falar(criar(cliente), "anota")
    resultado = cliente.chamadas[1]["messages"][-1]["content"][0]
    assert resultado["is_error"] is True and "INVALID_JSON" in resultado["content"]
    assert agenda.pendentes() == []


def test_erro_de_negocio_da_ferramenta_volta_como_erro(criar, cliente_falso):
    cliente = cliente_falso(resposta("tool_use", bloco_ferramenta("concluir_tarefa", {"id": 7})),
                            resposta("end_turn", bloco_texto("Não achei.")))
    falar(criar(cliente), "conclui a 7")
    resultado = cliente.chamadas[1]["messages"][-1]["content"][0]
    assert resultado["is_error"] is True and "não encontrada" in resultado["content"]


def test_entrada_truncada_por_max_tokens_nao_executa(criar, cliente_falso, agenda):
    cliente = cliente_falso(resposta("max_tokens", bloco_ferramenta("adicionar_tarefa", {"texto": "Rev"})))
    modelo = criar(cliente)
    assert falar(modelo, "anota") == MSG_PERDIDO
    assert agenda.pendentes() == [] and modelo.historico == []


def test_recusa_descarta_a_rodada(criar, cliente_falso):
    modelo = criar(cliente_falso(resposta("refusal")))
    assert falar(modelo, "algo proibido") == MSG_RECUSA
    assert modelo.historico == []


@pytest.mark.parametrize("erro, mensagem", [
    (anthropic.APIConnectionError(request=REQ), "Não consegui me conectar à internet."),
    (anthropic.RateLimitError("x", response=httpx2.Response(429, request=REQ), body=None), "pedidos demais"),
    (anthropic.AuthenticationError("x", response=httpx2.Response(401, request=REQ), body=None), "chave"),
    (anthropic.InternalServerError("x", response=httpx2.Response(500, request=REQ), body=None), "código 500"),
    (ValueError("json ilegível"), MSG_PERDIDO),
])
def test_erros_viram_frase_falada_e_nao_sujam_o_historico(criar, cliente_falso, erro, mensagem):
    modelo = criar(cliente_falso(erro))
    assert mensagem in falar(modelo, "oi")
    assert modelo.historico == []


def test_interromper_no_meio_do_streaming_desfaz_a_rodada(criar, cliente_falso):
    modelo = criar(cliente_falso(resposta("end_turn", bloco_texto("uma resposta bem longa que será cortada"))))
    gerador = modelo.responder("oi")
    next(gerador)
    next(gerador)
    gerador.close()  # é o que o orquestrador faz ao cancelar
    assert modelo.historico == []


def test_limite_de_rodadas_de_ferramentas(criar, cliente_falso):
    cliente = cliente_falso(resposta("tool_use", bloco_ferramenta("listar_lembretes", {})))
    modelo = criar(cliente)
    assert falar(modelo, "?") == MSG_PERDIDO
    assert len(cliente.chamadas) == MAX_RODADAS_FERRAMENTAS and modelo.historico == []


def test_nova_conversa_e_limite_de_historico(criar, cliente_falso):
    modelo = criar(cliente_falso(resposta("end_turn", bloco_texto("ok"))), max_mensagens=4)
    falar(modelo, "um")
    falar(modelo, "dois")
    assert len(modelo.historico) == 4
    falar(modelo, "três")  # atingiu o limite: recomeça em vez de editar o histórico
    assert len(modelo.historico) == 2
    assert falar(modelo, "quero uma nova conversa") == MSG_NOVA_CONVERSA
    assert modelo.historico == []


def test_escrever_documento_sem_ferramentas_e_fora_do_historico(criar, cliente_falso):
    cliente = cliente_falso(resposta("end_turn", bloco_texto("# Energia solar\n\nTexto longo.")))
    modelo = criar(cliente)
    texto = "".join(modelo.escrever("Escreva o texto de um documento sobre: energia solar")).strip()
    assert texto.split() == ["#", "Energia", "solar", "Texto", "longo."]  # o stream falso divide por palavras
    chamada = cliente.chamadas[0]
    assert "tools" not in chamada and chamada["max_tokens"] >= 4000
    assert "documentos" in chamada["system"] and chamada["fallbacks"] == "default"
    assert modelo.historico == []
