"""Dispara os lembretes no horário exato (sem polling): a thread dorme até o próximo
vencimento e é acordada sempre que a agenda muda."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime

from robofael.dominio.agenda import Agenda
from robofael.dominio.modelos import Lembrete

log = logging.getLogger(__name__)

ESPERA_MAXIMA_S = 60.0  # revalida periodicamente (ex.: relógio do sistema ajustado)


class AgendadorLembretes:
    def __init__(self, agenda: Agenda, ao_vencer: Callable[[Lembrete], None],
                 relogio: Callable[[], datetime] = datetime.now):
        self._agenda = agenda
        self._ao_vencer = ao_vencer
        self._relogio = relogio
        self._acordar = threading.Condition()
        self._mudou = False  # evita perder uma notificação entre verificar() e wait()
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        agenda.observar(self.notificar)

    def verificar(self) -> float:
        """Dispara os vencidos e devolve quantos segundos esperar até o próximo."""
        for lembrete in self._agenda.retirar_vencidos():
            try:
                self._ao_vencer(lembrete)
            except Exception:
                log.exception("Falha ao avisar o lembrete %s", lembrete.id)
        proximo = self._agenda.proximo_vencimento()
        if proximo is None:
            return ESPERA_MAXIMA_S
        return min(ESPERA_MAXIMA_S, max(0.0, (proximo - self._relogio()).total_seconds()))

    def notificar(self) -> None:
        with self._acordar:
            self._mudou = True
            self._acordar.notify()

    def iniciar(self) -> None:
        self._thread = threading.Thread(target=self._laco, name="agendador-lembretes", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        self.notificar()

    def _laco(self) -> None:
        while not self._parar.is_set():
            espera = self.verificar()
            with self._acordar:
                if not self._mudou and not self._parar.is_set():
                    self._acordar.wait(timeout=espera + 0.05)
                self._mudou = False
