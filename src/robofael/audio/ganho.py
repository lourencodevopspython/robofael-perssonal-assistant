"""Ganho automático (AGC) para microfones com volume de entrada baixo.

Mede o pico típico da fala (média móvel dos blocos com voz) e amplifica o áudio enviado aos
reconhecedores até um nível adequado. Não substitui um bom volume de entrada: amplifica a
voz e o ruído juntos. Por isso também avisa quando a voz chega baixa demais."""

from __future__ import annotations

import numpy as np

ALVO_PICO = 8000.0  # pico de fala desejado após o ganho (int16)
GANHO_MAXIMO = 8.0
PICO_BAIXO = 1000.0  # abaixo disso, na média, a voz chega fraca demais para um bom reconhecimento
SUAVIZACAO = 0.15


class GanhoAutomatico:
    def __init__(self, rms_ruido: float = 0.0, alvo: float = ALVO_PICO, maximo: float = GANHO_MAXIMO):
        self.alvo, self.maximo = alvo, maximo
        self.pico_fala: float | None = None
        # Sem nenhuma fala medida ainda: parte de um ganho que leva o ruído a ~80 (sala silenciosa)
        self._inicial = float(np.clip(80.0 / rms_ruido, 1.0, maximo)) if rms_ruido > 0 else 1.0

    @property
    def ganho(self) -> float:
        if self.pico_fala is None:
            return self._inicial
        return float(np.clip(self.alvo / max(self.pico_fala, 1.0), 1.0, self.maximo))

    @property
    def voz_baixa(self) -> bool:
        return self.pico_fala is not None and self.pico_fala < PICO_BAIXO

    def observar_fala(self, pico: float) -> None:
        """Informa o pico de um bloco que contém voz (antes do ganho)."""
        if self.pico_fala is None:
            self.pico_fala = pico
            return
        pico = min(pico, self.pico_fala * 3)  # uma batida no microfone não derruba o ganho
        self.pico_fala += (pico - self.pico_fala) * SUAVIZACAO

    def aplicar(self, bloco: bytes) -> bytes:
        ganho = self.ganho
        if ganho <= 1.0 or len(bloco) < 2:
            return bloco
        x = np.frombuffer(bloco[: len(bloco) // 2 * 2], dtype=np.int16).astype(np.float32) * ganho
        return np.clip(x, -32768, 32767).astype(np.int16).tobytes()


def pico_pcm16(bloco: bytes) -> float:
    if len(bloco) < 2:
        return 0.0
    return float(np.abs(np.frombuffer(bloco[: len(bloco) // 2 * 2], dtype=np.int16).astype(np.int32)).max())
