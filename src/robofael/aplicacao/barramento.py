"""Barramento de eventos thread-safe.

Qualquer thread publica; quem consome (a interface, na thread principal) chama `despachar()`
a cada quadro. Assim nenhuma thread de trabalho toca no Tkinter."""

from __future__ import annotations

import logging
import queue
from collections import defaultdict
from collections.abc import Callable

log = logging.getLogger(__name__)


class Barramento:
    def __init__(self) -> None:
        self._fila: queue.SimpleQueue = queue.SimpleQueue()
        self._assinantes: dict[type, list[Callable]] = defaultdict(list)

    def assinar(self, tipo: type, tratador: Callable) -> None:
        self._assinantes[tipo].append(tratador)

    def publicar(self, evento: object) -> None:
        self._fila.put(evento)

    def despachar(self, limite: int = 200) -> int:
        """Entrega os eventos pendentes, em ordem; um tratador com erro não derruba os demais."""
        entregues = 0
        while entregues < limite:
            try:
                evento = self._fila.get_nowait()
            except queue.Empty:
                break
            for tratador in self._assinantes.get(type(evento), ()):
                try:
                    tratador(evento)
                except Exception:
                    log.exception("Erro ao tratar %s", type(evento).__name__)
            entregues += 1
        return entregues
