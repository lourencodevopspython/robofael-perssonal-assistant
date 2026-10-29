"""Entidades da agenda e registros de auditoria."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


@dataclass(slots=True)
class Tarefa:
    id: int
    texto: str
    criada: datetime
    feita: bool = False
    concluida_em: datetime | None = None

    def para_dict(self) -> dict:
        d = asdict(self)
        d["criada"] = self.criada.isoformat(timespec="minutes")
        d["concluida_em"] = self.concluida_em.isoformat(timespec="minutes") if self.concluida_em else None
        return d

    @classmethod
    def de_dict(cls, d: dict) -> Tarefa:
        concluida = d.get("concluida_em")
        return cls(id=int(d["id"]), texto=d["texto"], criada=datetime.fromisoformat(d["criada"]),
                   feita=bool(d.get("feita", False)),
                   concluida_em=datetime.fromisoformat(concluida) if concluida else None)


@dataclass(slots=True)
class Lembrete:
    id: int
    texto: str
    quando: datetime
    avisado: bool = False

    def para_dict(self) -> dict:
        d = asdict(self)
        d["quando"] = self.quando.isoformat(timespec="minutes")
        return d

    @classmethod
    def de_dict(cls, d: dict) -> Lembrete:
        return cls(id=int(d["id"]), texto=d["texto"], quando=datetime.fromisoformat(d["quando"]),
                   avisado=bool(d.get("avisado", False)))


@dataclass(slots=True)
class DadosAgenda:
    """Estado completo persistido da agenda."""

    tarefas: list[Tarefa] = field(default_factory=list)
    lembretes: list[Lembrete] = field(default_factory=list)
    prox_id: int = 1

    VERSAO = 2

    def para_dict(self) -> dict:
        return {
            "versao": self.VERSAO,
            "prox_id": self.prox_id,
            "tarefas": [t.para_dict() for t in self.tarefas],
            "lembretes": [l.para_dict() for l in self.lembretes],
        }

    @classmethod
    def de_dict(cls, d: dict) -> DadosAgenda:
        """Aceita o formato atual (v2) e o da versão 1 (mesmos campos, sem `versao`)."""
        tarefas = [Tarefa.de_dict(t) for t in d.get("tarefas", [])]
        lembretes = [Lembrete.de_dict(l) for l in d.get("lembretes", [])]
        maior_id = max([t.id for t in tarefas] + [l.id for l in lembretes], default=0)
        return cls(tarefas, lembretes, max(int(d.get("prox_id", 1)), maior_id + 1))


class TipoEvento(str, Enum):
    TAREFA_CRIADA = "tarefa_criada"
    TAREFA_CONCLUIDA = "tarefa_concluida"
    TAREFA_REABERTA = "tarefa_reaberta"
    TAREFA_REMOVIDA = "tarefa_removida"
    LEMBRETE_CRIADO = "lembrete_criado"
    LEMBRETE_AVISADO = "lembrete_avisado"
    LEMBRETE_REMOVIDO = "lembrete_removido"

    @property
    def entidade(self) -> str:
        return self.value.split("_", 1)[0]


@dataclass(frozen=True, slots=True)
class RegistroAuditoria:
    """Fato imutável do histórico: o que aconteceu, com qual item e quando.
    Guarda a descrição do item no momento do fato (o item pode ser removido depois)."""

    tipo: TipoEvento
    entidade_id: int
    descricao: str
    ocorrido_em: datetime
    dados: dict[str, Any] = field(default_factory=dict, compare=False, hash=False)
