"""Máquina de estados do assistente: só transições válidas são aceitas."""

from __future__ import annotations

import threading
from collections.abc import Callable
from enum import Enum


class Estado(Enum):
    INICIANDO = "iniciando"
    PARADO = "parado"
    OUVINDO = "ouvindo"
    PENSANDO = "pensando"
    FALANDO = "falando"


TRANSICOES: dict[Estado, frozenset[Estado]] = {
    Estado.INICIANDO: frozenset({Estado.PARADO, Estado.FALANDO}),
    Estado.PARADO: frozenset({Estado.OUVINDO, Estado.PENSANDO, Estado.FALANDO}),
    Estado.OUVINDO: frozenset({Estado.PARADO, Estado.PENSANDO}),
    Estado.PENSANDO: frozenset({Estado.FALANDO, Estado.PARADO}),
    Estado.FALANDO: frozenset({Estado.PARADO, Estado.OUVINDO}),
}


class TransicaoInvalida(RuntimeError):
    pass


class MaquinaEstados:
    def __init__(self, ao_mudar: Callable[[Estado], None] | None = None, inicial: Estado = Estado.INICIANDO):
        self._estado = inicial
        self._trava = threading.Lock()
        self._ao_mudar = ao_mudar

    @property
    def atual(self) -> Estado:
        return self._estado

    def ir_para(self, novo: Estado) -> None:
        with self._trava:
            if novo == self._estado:
                return
            if novo not in TRANSICOES[self._estado]:
                raise TransicaoInvalida(f"{self._estado.value} -> {novo.value}")
            self._estado = novo
        if self._ao_mudar:
            self._ao_mudar(novo)

    def em(self, *estados: Estado) -> bool:
        return self._estado in estados
