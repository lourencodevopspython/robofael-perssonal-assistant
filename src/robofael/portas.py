"""Portas (interfaces) da arquitetura hexagonal.

A aplicação depende apenas destes contratos; os adaptadores em `robofael.adaptadores`
os implementam com tecnologias concretas (Claude, Google Speech, Vosk, edge-tts, pygame, SQLite).
Cada porta é pequena (segregação de interfaces): quem só consulta o histórico depende de
`ConsultaHistorico`, não do banco inteiro."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from robofael.dominio.modelos import RegistroAuditoria, TipoEvento
from robofael.dominio.programas import Programa
from robofael.dominio.repositorios import RepositorioAgenda

# Entidades e contratos do domínio, reexportados para quem pensa em "portas"
__all__ = ["Programa", "RepositorioAgenda"]


class ConsultaHistorico(Protocol):
    """Memória de longo prazo: o histórico auditável do que aconteceu na agenda."""

    def eventos(self, inicio: datetime, fim: datetime,
                tipos: Iterable[TipoEvento] | None = None) -> list[RegistroAuditoria]:
        """Registros com inicio <= ocorrido_em < fim, em ordem cronológica."""
        ...

    def total_eventos(self) -> int: ...


@dataclass(frozen=True, slots=True)
class Preferencias:
    """Ajustes feitos pelo usuário na tela de configurações (None = usar o padrão)."""

    avatar: str | None = None
    voz: str | None = None
    tom: str | None = None
    ritmo: str | None = None
    ativacao_por_voz: bool | None = None
    idioma: str | None = None  # "pt-BR" ou "en-US"
    microfone: str | None = None  # id de `DispositivosAudio.microfones()`; None = o padrão do sistema


class RepositorioPreferencias(Protocol):
    def carregar_preferencias(self) -> Preferencias: ...
    def salvar_preferencias(self, preferencias: Preferencias) -> None: ...


@dataclass(frozen=True, slots=True)
class CopiaVerificada:
    arquivo: Path
    registros: int  # eventos no histórico da cópia (conferida com PRAGMA integrity_check)


class ArquivoBanco(Protocol):
    """Onde o banco está, mudar de lugar e copiar (backup), com o assistente em uso."""

    @property
    def arquivo(self) -> Path | None: ...  # None: banco em memória
    def mover_para(self, destino: Path) -> Path:
        """Copia para `destino` (que não pode existir), passa a usá-lo e devolve onde ficou o antigo."""
        ...

    def copiar_para(self, destino: Path) -> CopiaVerificada: ...


class CacheTraducoes(Protocol):
    """Traduções já feitas de tarefas e lembretes, por idioma ("pt-BR", "en-US")."""

    def traducoes(self, idioma: str) -> dict[str, str]:
        """{texto original: tradução} de tudo o que já foi traduzido para `idioma`."""
        ...

    def guardar_traducoes(self, idioma: str, traducoes: dict[str, str]) -> None: ...


class PersistenciaAssistente(RepositorioAgenda, ConsultaHistorico, RepositorioPreferencias, ArquivoBanco,
                             CacheTraducoes, Protocol):
    """Tudo o que o assistente guarda: agenda, histórico auditável e preferências (ex.: SQLite).
    Os serviços dependem só da parte de que precisam (segregação de interfaces)."""


class LancadorProgramas(Protocol):
    def programas(self) -> list[Programa]: ...
    def abrir(self, programa: Programa) -> None: ...


@dataclass(frozen=True, slots=True)
class Microfone:
    id: str  # identificador estável no servidor de áudio (sobrevive a reinícios e a trocas de porta USB)
    nome: str  # descrição para mostrar na tela


class DispositivosAudio(Protocol):
    def microfones(self) -> list[Microfone]:
        """Microfones conectados agora (vazio se não for possível listar)."""
        ...


@dataclass(frozen=True, slots=True)
class EstadoInicializacao:
    abrir_ao_entrar: bool  # abre sozinho quando o usuário entra no computador
    comando_no_terminal: bool  # `robofael` funciona em qualquer terminal
    comando_do_sistema: bool = False  # o comando vem do pacote instalado: não dá para desligar


class InicializacaoSistema(Protocol):
    """Como o assistente é aberto pelo sistema operacional (sessão gráfica e terminal)."""

    def estado(self) -> EstadoInicializacao: ...
    def aplicar(self, abrir_ao_entrar: bool, comando_no_terminal: bool) -> None: ...


@dataclass(frozen=True, slots=True)
class ModeloDisponivel:
    nome: str  # o identificador usado na API (ex.: "claude-opus-5-5", "llama3.2:3b")
    detalhe: str = ""  # ex.: nome de exibição ou tamanho ("3.2B")


class ProvedorIndisponivel(Exception):
    """Não deu para listar os modelos; `chave` é a mensagem no catálogo de textos (i18n)."""

    def __init__(self, chave: str, **campos: str):
        super().__init__(chave, campos)
        self.chave, self.campos = chave, campos


class CatalogoModelos(Protocol):
    provedor: str  # "claude" ou "ollama"

    def modelos(self) -> list[ModeloDisponivel]:
        """Modelos que este assistente consegue usar (conversa + ferramentas); levanta ProvedorIndisponivel."""
        ...


@runtime_checkable
class ModeloLinguagem(Protocol):
    """Gera a resposta em pedaços de texto (streaming), executando ferramentas se preciso."""

    @property
    def online(self) -> bool: ...
    @property
    def provedor(self) -> str: ...  # "claude", "ollama" ou "offline"
    @property
    def modelo(self) -> str | None: ...  # o modelo em uso (None no modo offline)
    def responder(self, fala: str) -> Iterator[str]: ...
    def reiniciar(self) -> None: ...


class CapturaAudio(Protocol):
    def capturar(self, cancelar: threading.Event, ao_nivel: Callable[[float], None] | None = None,
                 espera_max_s: float = 7.0, frase_max_s: float = 20.0) -> Any:
        """Grava uma frase completa (sem transcrever); None se cancelado ou se ninguém falou."""
        ...


class ReconhecedorFala(Protocol):
    def ouvir(self, cancelar: threading.Event, ao_nivel: Callable[[float], None] | None = None) -> str | None:
        """Escuta uma frase e devolve o texto (None se nada foi dito/entendido)."""
        ...

    def transcrever(self, audio: Any) -> str | None:
        """Transcreve um áudio já gravado (ex.: a fala que continha a frase de ativação)."""
        ...


@dataclass(frozen=True, slots=True)
class Ativacao:
    """A frase de ativação foi ouvida. `comando` é a transcrição local (aproximada) do que veio
    depois dela, se houver; `audio` é a gravação com o comando, para transcrição precisa.
    Ambos vazios: só chamou ("ok Fael") e o comando ainda vai ser dito."""

    comando: str
    audio: Any = None
    audio_inclui_frase: bool = False  # a gravação começa com a própria frase de ativação


class DetectorAtivacao(Protocol):
    frase: str

    def aguardar(self, cancelar: threading.Event) -> Ativacao | None:
        """Escuta passivamente até ouvir a frase de ativação; None se cancelado."""
        ...


class SintetizadorVoz(Protocol):
    def sintetizar(self, texto: str) -> bytes:
        """Devolve o áudio codificado (mp3) da fala."""
        ...


class SintetizadorConfiguravel(SintetizadorVoz, Protocol):
    """Sintetizador cuja voz pode ser trocada ao vivo (tela de configurações, troca de idioma)."""

    voz: str
    tom: str
    ritmo: str

    def configurar(self, voz: str, tom: str, ritmo: str, gtts: tuple[str, str] | None = None) -> None: ...


@dataclass(slots=True)
class Faixa:
    """Áudio pronto para tocar: decodificado, com o envelope da boca já calculado."""

    duracao_s: float
    volume: list[float]
    timbre: list[float]
    nativo: Any = field(repr=False, default=None)  # objeto do reprodutor (ex.: pygame.Sound)


class ReprodutorAudio(Protocol):
    amplitude: float  # 0..1 — abertura da boca no instante atual
    forma: float  # -1 (o/u) .. +1 (e/i) — formato da boca no instante atual

    def preparar(self, audio: bytes) -> Faixa: ...
    def tocar(self, faixa: Faixa, cancelar: threading.Event) -> None: ...
    def sinal_ativacao(self) -> Faixa | None:
        """Som curto de "estou ouvindo" após a frase de ativação (None se não houver)."""
        ...


class ArquivoDocumentos(Protocol):
    def salvar(self, nome: str, conteudo: str) -> Path:
        """Grava o documento (sem sobrescrever outro) e devolve o caminho do arquivo criado."""
        ...


@runtime_checkable
class RedatorDocumentos(Protocol):
    """Modelo que também escreve textos longos para arquivo ("gerar doc sobre…"), com outras instruções e
    outro limite de tamanho que as respostas faladas, e sem mexer no histórico da conversa."""

    def escrever(self, pedido: str) -> Iterator[str]: ...


@runtime_checkable
class TradutorTextos(Protocol):
    """Modelo que traduz textos curtos (tarefas e lembretes) para exibição, fora do histórico da conversa."""

    def traduzir(self, textos: list[str], idioma: str) -> list[str]:
        """Um texto por entrada, na mesma ordem, em `idioma` ("pt-BR"/"en-US"); os que já estão nele voltam
        iguais. Levanta exceção se não conseguir (sem conexão, resposta ilegível...)."""
        ...
