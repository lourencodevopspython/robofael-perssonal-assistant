"""Modelo de linguagem Claude com streaming e ferramentas de agenda.

O texto é repassado pedaço a pedaço (`yield`) assim que chega, para a voz começar antes de a
resposta terminar. O histórico só cresce (append-only); se a rodada falhar ou for interrompida,
ela é descartada por inteiro para o histórico nunca ficar inconsistente."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Generator, Iterator
from datetime import datetime
from typing import Any

from robofael.adaptadores import traducao_textos
from robofael.adaptadores.ferramentas import FERRAMENTAS, EntradaInvalida, ExecutorFerramentas
from robofael.dominio.linguagem import descrever_agora, pede_nova_conversa
from robofael.i18n import Tradutor
from robofael.portas import ModeloDisponivel, ProvedorIndisponivel

log = logging.getLogger(__name__)

MAX_RODADAS_FERRAMENTAS = 8


def instrucoes_sistema(nome_usuario: str, nome_assistente: str = "Robofael", tradutor: Tradutor | None = None) -> str:
    return (tradutor or Tradutor())("claude.instrucoes", usuario=nome_usuario, assistente=nome_assistente)


class ModeloClaude:
    online = True
    provedor = "claude"

    def __init__(self, cliente: Any, executor: ExecutorFerramentas, nome_usuario: str,
                 modelo: str = "claude-opus-5-5", esforco: str = "low", max_mensagens: int = 60,
                 relogio: Callable[[], datetime] = datetime.now, nome_assistente: str = "Robofael",
                 tradutor: Tradutor | None = None):
        self.cliente = cliente
        self.executor = executor
        self.modelo = modelo
        self.esforco = esforco
        self.max_mensagens = max_mensagens
        self.relogio = relogio
        self.nome_usuario, self.nome_assistente = nome_usuario, nome_assistente
        self.tr = tradutor or Tradutor()
        self.historico: list[dict] = []
        self.tr.observar(lambda _idioma: self.reiniciar())  # trocou de idioma: conversa nova

    @property
    def sistema(self) -> str:
        return instrucoes_sistema(self.nome_usuario, self.nome_assistente, self.tr)

    def reiniciar(self) -> None:
        self.historico = []

    def responder(self, fala: str) -> Iterator[str]:
        if pede_nova_conversa(fala):
            self.reiniciar()
            yield self.tr("claude.nova_conversa")
            return
        if len(self.historico) >= self.max_mensagens:
            self.reiniciar()  # conversa nova em vez de editar o histórico (a agenda persiste)

        inicio = len(self.historico)
        # Data/hora vai na mensagem (não nas instruções) para o prefixo seguir cacheável
        agora = self.tr("claude.agora", agora=descrever_agora(self.relogio(), self.tr.idioma))
        self.historico.append({"role": "user", "content": f"{agora}\n{fala}"})
        concluida = False
        try:
            for _ in range(MAX_RODADAS_FERRAMENTAS):
                try:
                    final = yield from self._transmitir_rodada()
                except ValueError:
                    log.warning("Entrada de ferramenta ilegível no streaming")
                    yield self.tr("claude.perdido")
                    return
                except Exception as e:  # erros da API viram uma frase falada
                    yield self._mensagem_de_erro(e)
                    return

                if final.stop_reason == "refusal":
                    yield self.tr("claude.recusa")
                    return
                usos = [b for b in final.content if b.type == "tool_use"]
                if usos and final.stop_reason == "max_tokens":
                    yield self.tr("claude.perdido")  # entrada da ferramenta truncada: não executa
                    return
                self.historico.append({"role": "assistant", "content": final.content})
                if not usos:
                    concluida = True
                    return
                self.historico.append({"role": "user", "content": [self._executar(b) for b in usos]})
            yield self.tr("claude.perdido")
        finally:
            if not concluida:
                del self.historico[inicio:]  # descarta a rodada (falha, recusa ou interrupção)

    def escrever(self, pedido: str) -> Iterator[str]:
        """Texto longo para um documento: instruções próprias, sem ferramentas e fora do histórico."""
        with self.cliente.beta.messages.stream(
            model=self.modelo,
            max_tokens=8000,
            system=self.tr("doc.instrucoes"),
            messages=[{"role": "user", "content": pedido}],
            output_config={"effort": self.esforco},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for evento in stream:
                if evento.type == "text" and evento.text:
                    yield evento.text

    def traduzir(self, textos: list[str], idioma: str) -> list[str]:
        """Tarefas e lembretes para o idioma da interface: sem ferramentas e fora do histórico."""
        partes: list[str] = []
        with self.cliente.beta.messages.stream(
            model=self.modelo,
            max_tokens=4000,
            system=traducao_textos.instrucoes(idioma),
            messages=[{"role": "user", "content": traducao_textos.entrada(textos)}],
            output_config={"effort": "low"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for evento in stream:
                if evento.type == "text" and evento.text:
                    partes.append(evento.text)
        return traducao_textos.ler_traducoes("".join(partes), len(textos))

    def _transmitir_rodada(self) -> Generator[str, None, Any]:
        with self.cliente.beta.messages.stream(
            model=self.modelo,
            max_tokens=16000,
            system=[{"type": "text", "text": self.sistema, "cache_control": {"type": "ephemeral"}}],
            tools=FERRAMENTAS,
            messages=self.historico,
            output_config={"effort": self.esforco},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            for evento in stream:
                if evento.type == "text" and evento.text:
                    yield evento.text
            return stream.get_final_message()

    def _executar(self, bloco: Any) -> dict:
        try:
            saida = self.executor.executar(bloco.name, bloco.input)
            return {"type": "tool_result", "tool_use_id": bloco.id, "content": json.dumps(saida, ensure_ascii=False)}
        except EntradaInvalida as e:
            conteudo = json.dumps({"INVALID_JSON": json.dumps(bloco.input, ensure_ascii=False), "erro": str(e)},
                                  ensure_ascii=False)
            return {"type": "tool_result", "tool_use_id": bloco.id, "content": conteudo, "is_error": True}
        except ValueError as e:
            return {"type": "tool_result", "tool_use_id": bloco.id, "content": str(e), "is_error": True}

    def _mensagem_de_erro(self, erro: Exception) -> str:
        import anthropic

        if isinstance(erro, anthropic.RateLimitError):
            return self.tr("claude.limite")
        if isinstance(erro, anthropic.AuthenticationError):
            return self.tr("claude.chave")
        if isinstance(erro, anthropic.APIStatusError):
            return self.tr("claude.erro_api", codigo=erro.status_code)
        if isinstance(erro, anthropic.APIConnectionError):
            return self.tr("claude.sem_internet")
        log.exception("Erro inesperado ao consultar o Claude", exc_info=erro)
        return self.tr("claude.problema")


def criar_cliente(timeout_s: float) -> Any:
    """Cliente oficial; levanta exceção se não houver credenciais válidas."""
    import anthropic

    return anthropic.Anthropic(timeout=timeout_s, max_retries=2)


class CatalogoClaude:
    """Modelos do Claude liberados para esta chave (todos conversam em streaming e usam ferramentas)."""

    provedor = "claude"

    def __init__(self, criar: Callable[[float], Any] = criar_cliente, timeout_s: float = 10.0):
        self._criar, self.timeout_s = criar, timeout_s

    def modelos(self) -> list[ModeloDisponivel]:
        import anthropic

        try:
            cliente = self._criar(self.timeout_s)
            lista = list(cliente.models.list(limit=100))
        except TypeError as e:  # o SDK levanta TypeError quando não encontra credenciais
            raise ProvedorIndisponivel("modelos.claude_sem_chave") from e
        except anthropic.AuthenticationError as e:
            raise ProvedorIndisponivel("modelos.claude_chave_invalida") from e
        except anthropic.APIConnectionError as e:
            raise ProvedorIndisponivel("modelos.claude_sem_conexao") from e
        except anthropic.APIError as e:
            raise ProvedorIndisponivel("modelos.erro", detalhe=type(e).__name__) from e
        return [ModeloDisponivel(m.id, getattr(m, "display_name", "") or "") for m in lista
                if m.id.startswith("claude")]


# Mensagens no idioma padrão (português), mantidas para quem as importa
_PT = Tradutor()
MSG_NOVA_CONVERSA = _PT("claude.nova_conversa")
MSG_RECUSA = _PT("claude.recusa")
MSG_PERDIDO = _PT("claude.perdido")
