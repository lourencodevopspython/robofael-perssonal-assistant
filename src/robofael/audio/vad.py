"""Detecção de atividade de voz (VAD) por energia, independente do microfone.

Recebe o volume (RMS) de cada bloco de áudio e decide quando a fala começou e terminou.
Ruídos curtos (um clique, uma tosse rápida) são descartados."""

from __future__ import annotations

from enum import Enum, auto

_EPS = 1e-9  # tempo acumulado em float (0,05 x 10 = 0,4999...) precisa alcançar o limite


class StatusFala(Enum):
    AGUARDANDO = auto()  # ainda não começou a falar
    FALANDO = auto()  # fala em andamento (inclui pausas curtas)
    CONCLUIDO = auto()  # fala terminou (silêncio longo o bastante, ou limite de duração)
    SEM_FALA = auto()  # tempo de espera esgotado sem ninguém falar


class DetectorFala:
    def __init__(self, limiar: float, pausa_s: float = 0.7, espera_max_s: float = 7.0,
                 frase_max_s: float = 20.0, fala_min_s: float = 0.2):
        self.limiar = limiar
        self.pausa_s = pausa_s
        self.espera_max_s = espera_max_s
        self.frase_max_s = frase_max_s
        self.fala_min_s = fala_min_s
        self._esperando = 0.0
        self._duracao = 0.0
        self._voz = 0.0
        self._silencio = 0.0
        self.status = StatusFala.AGUARDANDO

    def processar(self, rms: float, duracao_bloco: float) -> StatusFala:
        if self.status in (StatusFala.CONCLUIDO, StatusFala.SEM_FALA):
            return self.status
        alto = rms >= self.limiar
        if self.status is StatusFala.AGUARDANDO:
            self._esperando += duracao_bloco
            if alto:
                self.status = StatusFala.FALANDO
                self._duracao = self._voz = duracao_bloco
                self._silencio = 0.0
            elif self._esperando >= self.espera_max_s - _EPS:
                self.status = StatusFala.SEM_FALA
            return self.status

        self._duracao += duracao_bloco
        if alto:
            self._voz += duracao_bloco
            self._silencio = 0.0
        else:
            self._silencio += duracao_bloco
        if self._duracao >= self.frase_max_s - _EPS:
            self.status = StatusFala.CONCLUIDO
        elif self._silencio >= self.pausa_s - _EPS:
            # Só um estalo? Volta a aguardar em vez de enviar ruído para o reconhecimento
            self.status = StatusFala.CONCLUIDO if self._voz >= self.fala_min_s - _EPS else StatusFala.AGUARDANDO
        return self.status

    @staticmethod
    def calibrar(rms_ruido: list[float], fator: float = 2.5, minimo: float = 150.0) -> float:
        """Limiar a partir do ruído ambiente (mediana dos blocos x fator)."""
        if not rms_ruido:
            return minimo
        ordenados = sorted(rms_ruido)
        return max(minimo, ordenados[len(ordenados) // 2] * fator)


def nivel_visual(rms: float, limiar: float) -> float:
    """Converte o RMS num nível 0..1 agradável para o medidor da interface."""
    if limiar <= 0:
        return 0.0
    return max(0.0, min(1.0, (rms / limiar - 0.5) / 3.5))
