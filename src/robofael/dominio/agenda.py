"""Regras de negócio da agenda: tarefas e lembretes, seguras para uso entre threads."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from robofael.dominio.modelos import DadosAgenda, Lembrete, RegistroAuditoria, Tarefa, TipoEvento
from robofael.dominio.repositorios import RepositorioAgenda


class TarefaNaoEncontrada(ValueError):
    pass


class Agenda:
    """Serviço de domínio. Cada alteração é persistida — junto com o registro de auditoria
    do que aconteceu, na mesma transação — e notificada aos observadores (a interface
    redesenha o painel; o agendador recalcula o próximo lembrete)."""

    def __init__(self, repositorio: RepositorioAgenda, relogio: Callable[[], datetime] = datetime.now):
        self._repo = repositorio
        self._relogio = relogio
        self._trava = threading.RLock()
        self._dados = repositorio.carregar()
        self._observadores: list[Callable[[], None]] = []
        self._eventos: list[RegistroAuditoria] = []  # da transação em andamento

    def observar(self, callback: Callable[[], None]) -> None:
        self._observadores.append(callback)

    # ---------- Consultas ----------
    def tarefas(self, incluir_concluidas: bool = False) -> list[Tarefa]:
        with self._trava:
            return [t for t in self._dados.tarefas if incluir_concluidas or not t.feita]

    def pendentes(self) -> list[Tarefa]:
        return self.tarefas(incluir_concluidas=False)

    def proximos_lembretes(self) -> list[Lembrete]:
        with self._trava:
            return sorted((l for l in self._dados.lembretes if not l.avisado), key=lambda l: l.quando)

    def proximo_vencimento(self) -> datetime | None:
        futuros = self.proximos_lembretes()
        return futuros[0].quando if futuros else None

    # ---------- Comandos ----------
    def adicionar_tarefa(self, texto: str) -> Tarefa:
        texto = texto.strip()
        if not texto:
            raise ValueError("A tarefa precisa de uma descrição")
        with self._alterando():
            t = Tarefa(self._novo_id(), texto, self._agora())
            self._dados.tarefas.append(t)
            self._registrar(TipoEvento.TAREFA_CRIADA, t.id, t.texto)
            return t

    def concluir_tarefa(self, id: int, feita: bool = True) -> Tarefa:
        with self._alterando():
            t = self._achar(id)
            if t.feita != feita:  # concluir o que já está concluído não gera evento
                t.feita = feita
                t.concluida_em = self._agora() if feita else None
                self._registrar(TipoEvento.TAREFA_CONCLUIDA if feita else TipoEvento.TAREFA_REABERTA, t.id, t.texto)
            return t

    def concluir_todas(self) -> list[Tarefa]:
        """Conclui de uma vez (numa só transação) todas as tarefas pendentes; devolve as que concluiu."""
        with self._trava:
            pendentes = self.pendentes()
            if not pendentes:
                return []
            with self._alterando():
                agora = self._agora()
                for t in pendentes:
                    t.feita, t.concluida_em = True, agora
                    self._registrar(TipoEvento.TAREFA_CONCLUIDA, t.id, t.texto)
        return pendentes

    def alternar_tarefa(self, id: int) -> Tarefa:
        with self._trava:
            return self.concluir_tarefa(id, not self._achar(id).feita)

    def remover_tarefa(self, id: int) -> None:
        with self._alterando():
            t = self._achar(id)
            self._dados.tarefas.remove(t)
            self._registrar(TipoEvento.TAREFA_REMOVIDA, t.id, t.texto, feita=t.feita)

    def criar_lembrete(self, texto: str, quando: datetime | str) -> Lembrete:
        if isinstance(quando, str):
            quando = datetime.fromisoformat(quando)  # ValueError se o formato for inválido
        texto = texto.strip() or "seu lembrete"
        with self._alterando():
            lem = Lembrete(self._novo_id(), texto, quando.replace(second=0, microsecond=0))
            self._dados.lembretes.append(lem)
            self._registrar(TipoEvento.LEMBRETE_CRIADO, lem.id, lem.texto,
                            quando=lem.quando.isoformat(timespec="minutes"))
            return lem

    def remover_lembrete(self, id: int) -> None:
        with self._alterando():
            lem = next((l for l in self._dados.lembretes if l.id == id), None)
            if lem is None:
                raise ValueError(f"Lembrete {id} não encontrado")
            self._dados.lembretes.remove(lem)
            self._registrar(TipoEvento.LEMBRETE_REMOVIDO, lem.id, lem.texto)

    def retirar_vencidos(self) -> list[Lembrete]:
        """Marca como avisados e devolve os lembretes cujo horário já chegou."""
        agora = self._relogio()
        with self._trava:
            if not any(not l.avisado and l.quando <= agora for l in self._dados.lembretes):
                return []
            with self._alterando():
                vencidos = [l for l in self._dados.lembretes if not l.avisado and l.quando <= agora]
                for l in vencidos:
                    l.avisado = True
                    self._registrar(TipoEvento.LEMBRETE_AVISADO, l.id, l.texto,
                                    quando=l.quando.isoformat(timespec="minutes"))
        return sorted(vencidos, key=lambda l: l.quando)

    # ---------- Internos ----------
    def _achar(self, id: int) -> Tarefa:
        for t in self._dados.tarefas:
            if t.id == id:
                return t
        raise TarefaNaoEncontrada(f"Tarefa {id} não encontrada")

    def _agora(self) -> datetime:
        return self._relogio().replace(second=0, microsecond=0)

    def _registrar(self, tipo: TipoEvento, entidade_id: int, descricao: str, **dados: Any) -> None:
        self._eventos.append(RegistroAuditoria(tipo, entidade_id, descricao, self._relogio(), dados))

    def _novo_id(self) -> int:
        i = self._dados.prox_id
        self._dados.prox_id += 1
        return i

    @contextmanager
    def _alterando(self) -> Iterator[None]:
        """Transação: aplica a alteração, persiste estado + auditoria juntos e só então
        notifica os observadores. Se algo falhar, os eventos da transação são descartados."""
        with self._trava:
            inicio = len(self._eventos)
            try:
                yield
                eventos, self._eventos = self._eventos[inicio:], self._eventos[:inicio]
                self._repo.salvar(self._dados, eventos)
            except BaseException:
                del self._eventos[inicio:]
                raise
        for cb in list(self._observadores):
            cb()


__all__ = ["Agenda", "DadosAgenda", "TarefaNaoEncontrada"]
