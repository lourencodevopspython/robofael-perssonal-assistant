"""Reprodução de áudio com pygame, publicando volume e timbre em tempo real para a boca."""

from __future__ import annotations

import io
import os
import threading
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
# Sem isto o SDL captura SIGINT/SIGTERM e o programa deixa de fechar com Ctrl+C
os.environ.setdefault("SDL_NO_SIGNAL_HANDLERS", "1")

import numpy as np
import pygame

from robofael.audio.analise import FPS_ENVELOPE, calcular_envelope, interpolar, limites_da_fala
from robofael.portas import Faixa

PASSO_ATUALIZACAO_S = 1 / 120


class ReprodutorPygame:
    def __init__(self) -> None:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        self.taxa = pygame.mixer.get_init()[0]
        self.amplitude = 0.0
        self.forma = 0.0
        self._sinal: Faixa | None = None

    def preparar(self, audio: bytes) -> Faixa:
        """Decodifica o mp3, apara o silêncio das pontas e calcula o envelope da boca.
        Tudo fora da hora de tocar: sem engasgos, e as frases se emendam como na fala natural."""
        pcm = pygame.sndarray.array(pygame.mixer.Sound(file=io.BytesIO(audio)))
        mono = pcm.astype(np.float32) if pcm.ndim == 1 else pcm.astype(np.float32).mean(axis=1)
        inicio, fim = limites_da_fala(mono, self.taxa)
        som = pygame.sndarray.make_sound(np.ascontiguousarray(pcm[inicio:fim]))
        volume, timbre = calcular_envelope(mono[inicio:fim], self.taxa)
        return Faixa(duracao_s=som.get_length(), volume=volume, timbre=timbre, nativo=som)

    def sinal_ativacao(self) -> Faixa:
        """Dois tons curtos e suaves (gerados uma vez): avisa que o assistente está ouvindo."""
        if self._sinal is None:
            t = np.arange(int(self.taxa * 0.09)) / self.taxa
            envelope = np.sin(np.pi * t / t[-1]) ** 2
            tons = [np.sin(2 * np.pi * f * t) * envelope for f in (660, 990)]
            onda = (np.concatenate([tons[0], np.zeros(int(self.taxa * 0.03)), tons[1]]) * 0.35 * 32767)
            canais = pygame.mixer.get_init()[2]
            pcm = np.repeat(onda.astype(np.int16)[:, None], canais, axis=1) if canais > 1 else onda.astype(np.int16)
            som = pygame.sndarray.make_sound(np.ascontiguousarray(pcm))
            self._sinal = Faixa(duracao_s=som.get_length(), volume=[], timbre=[], nativo=som)
        return self._sinal

    def tocar(self, faixa: Faixa, cancelar: threading.Event) -> None:
        canal = faixa.nativo.play()
        inicio = time.monotonic()
        try:
            while canal.get_busy() and not cancelar.is_set():
                pos = (time.monotonic() - inicio) * FPS_ENVELOPE
                self.amplitude = interpolar(faixa.volume, pos)
                i = int(pos)
                self.forma = faixa.timbre[i] if i < len(faixa.timbre) else 0.0
                time.sleep(PASSO_ATUALIZACAO_S)
        finally:
            canal.stop()
            self.amplitude = self.forma = 0.0
