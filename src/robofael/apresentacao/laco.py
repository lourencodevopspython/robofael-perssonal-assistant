"""Laço de quadros da interface e fila de trabalho com orçamento por quadro.

- `LacoQuadros` chama o desenho do quadro no ritmo pedido a cada momento (60 FPS com o
  assistente ativo, 30 FPS em repouso), agendando pelo relógio para não acumular atraso.
- `FilaTrabalhoUI` executa na thread principal tarefas que só ela pode fazer (ex.: converter
  imagens para o Tk), um pouco por quadro, sem estourar o orçamento de tempo: em vez de um
  engasgo de 200 ms, a interface continua fluida enquanto o trabalho avança."""

from __future__ import annotations

import collections
import time
from collections.abc import Callable, Iterator

Relogio = Callable[[], float]
Tarefa = Iterator[None]  # gerador: cada `yield` é um ponto seguro para pausar e continuar no próximo quadro

ORCAMENTO_FILA_S = 0.004  # tempo máximo por quadro gasto com a fila (de ~16 ms a 60 FPS)
ATRASO_MAXIMO_QUADROS = 3  # mais atrasado que isso (ex.: janela minimizada): ressincroniza


class FilaTrabalhoUI:
    def __init__(self, relogio: Relogio = time.perf_counter, orcamento_s: float = ORCAMENTO_FILA_S):
        self._tarefas: collections.deque[Tarefa] = collections.deque()
        self._relogio = relogio
        self.orcamento_s = orcamento_s

    @property
    def vazia(self) -> bool:
        return not self._tarefas

    def agendar(self, tarefa: Tarefa, urgente: bool = False) -> None:
        if urgente:
            self._tarefas.appendleft(tarefa)
        else:
            self._tarefas.append(tarefa)

    def executar(self) -> None:
        """Avança as tarefas até esgotar o orçamento (sempre faz ao menos um passo, para nunca travar)."""
        limite = self._relogio() + self.orcamento_s
        while self._tarefas:
            tarefa = self._tarefas[0]
            try:
                next(tarefa)
            except StopIteration:
                self._tarefas.popleft()
            if self._relogio() >= limite:
                return


class LacoQuadros:
    def __init__(self, agendar: Callable[[int, Callable[[], None]], object], desenhar: Callable[[float], None],
                 fps: Callable[[], int], relogio: Relogio = time.monotonic):
        self._agendar = agendar  # ex.: tk.Tk.after
        self._desenhar = desenhar
        self._fps = fps
        self._relogio = relogio
        self._ultimo = self._proximo = relogio()
        self.ativo = False

    def iniciar(self) -> None:
        self.ativo = True
        self._ultimo = self._proximo = self._relogio()
        self._tique()

    def parar(self) -> None:
        self.ativo = False

    def _tique(self) -> None:
        if not self.ativo:
            return
        agora = self._relogio()
        dt, self._ultimo = min(0.1, agora - self._ultimo), agora
        self._desenhar(dt)
        if not self.ativo:  # o desenho pode ter encerrado a janela
            return
        # Agenda pelo relógio (não "N ms depois"): o ritmo não acumula atraso
        periodo = 1 / max(1, self._fps())
        self._proximo += periodo
        atraso = self._proximo - self._relogio()
        if atraso < -ATRASO_MAXIMO_QUADROS * periodo:
            self._proximo, atraso = self._relogio(), 0.0
        self._agendar(max(1, int(atraso * 1000)), self._tique)
