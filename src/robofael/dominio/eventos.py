"""Eventos publicados pela aplicação e consumidos pela interface (via barramento)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from robofael.dominio.estados import Estado
from robofael.i18n import Idioma


@dataclass(frozen=True, slots=True)
class EstadoMudou:
    estado: Estado


@dataclass(frozen=True, slots=True)
class FalaReconhecida:
    texto: str


@dataclass(frozen=True, slots=True)
class RespostaParcial:
    """Texto acumulado da resposta enquanto ela ainda está sendo gerada."""

    texto: str


@dataclass(frozen=True, slots=True)
class RespostaConcluida:
    texto: str
    interrompida: bool = False


@dataclass(frozen=True, slots=True)
class NivelMicrofone:
    nivel: float  # 0..1


@dataclass(frozen=True, slots=True)
class EscutaPassiva:
    """A ativação por voz ligou (frase) ou desligou (None)."""

    frase: str | None


@dataclass(frozen=True, slots=True)
class AgendaAtualizada:
    pass


@dataclass(frozen=True, slots=True)
class IdiomaMudou:
    """O idioma mudou (pela tela de configurações ou por voz: "mudar para inglês")."""

    idioma: Idioma


@dataclass(frozen=True, slots=True)
class TraducoesAtualizadas:
    """Chegaram traduções novas de tarefas ou lembretes: o painel deve ser redesenhado."""


class Gravidade(Enum):
    INFO = "info"
    ERRO = "erro"


@dataclass(frozen=True, slots=True)
class Aviso:
    mensagem: str
    gravidade: Gravidade = Gravidade.INFO
