"""Análise de sinal de áudio (somente numpy): tom de voz, envelope de volume e timbre da vogal."""

import wave
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from numpy.typing import ArrayLike

FPS_ENVELOPE = 60


def ler_wav(caminho: Path) -> tuple[np.ndarray, int]:
    """Lê um WAV PCM 16 bits e devolve (amostras mono em float, taxa de amostragem)."""
    with wave.open(str(caminho), "rb") as w:
        fs = w.getframerate()
        dados = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64)
        if w.getnchannels() > 1:
            dados = dados.reshape(-1, w.getnchannels()).mean(axis=1)
    return dados, fs


def analisar_tom(amostras: ArrayLike, fs: int) -> tuple[float | None, float]:
    """Devolve (tom mediano em Hz ou None, segundos de fala ativa).

    Usa autocorrelação normalizada por quadro de 40 ms (60–400 Hz) e só considera
    quadros com energia e periodicidade suficientes (trechos com voz)."""
    x = np.asarray(amostras, dtype=np.float64)
    if len(x) == 0:
        return None, 0.0
    x = x - x.mean()
    quadro, passo = int(fs * 0.04), int(fs * 0.01)
    if len(x) < quadro:
        return None, 0.0
    n = 1 + (len(x) - quadro) // passo
    quadros = np.lib.stride_tricks.as_strided(x, (n, quadro), (x.strides[0] * passo, x.strides[0]))
    rms = np.sqrt((quadros ** 2).mean(axis=1))
    limiar = 0.12 * np.percentile(rms, 95)
    ativos = rms > max(limiar, 1e-9)

    lag_min, lag_max = int(fs / 400), int(fs / 60)
    janela = np.hanning(quadro)
    tons = []
    for q in quadros[ativos]:
        espectro = np.fft.rfft(q * janela, 2 * quadro)
        ac = np.fft.irfft(np.abs(espectro) ** 2)[:quadro]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        lag = lag_min + int(np.argmax(ac[lag_min:lag_max]))
        if ac[lag] < 0.45:
            continue  # quadro sem voz (consoante, ruído)
        if 1 <= lag < len(ac) - 1:  # interpolação parabólica do pico
            a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
            if a - 2 * b + c:
                lag = lag + 0.5 * (a - c) / (a - 2 * b + c)
        tons.append(fs / lag)
    tom = float(np.median(tons)) if len(tons) >= 10 else None
    return tom, float(ativos.sum() * passo / fs)


def calcular_envelope(amostras: ArrayLike, fs: int, fps: int = FPS_ENVELOPE) -> tuple[list[float], list[float]]:
    """Por quadro de 1/fps s devolve (volume, timbre), ambos como listas:

    - volume em 0..1 — controla a abertura da boca;
    - timbre em -1..1 — negativo = vogal "fechada" (o/u, boca arredondada),
      positivo = "aberta" (e/i, boca larga). Vogais abertas concentram energia
      em 1–3 kHz; fechadas, em 250–1000 Hz."""
    x = np.asarray(amostras, dtype=np.float32)
    passo = max(1, int(fs // fps))
    n = len(x) // passo
    if n == 0:
        return [], []
    quadros = x[: n * passo].reshape(n, passo)
    rms = np.sqrt((quadros ** 2).mean(axis=1))
    rms = np.convolve(rms, np.ones(3) / 3, mode="same")  # tira picos isolados
    topo = np.percentile(rms, 95) or 1.0
    volume = np.clip(rms / topo, 0, 1)
    volume = np.clip((volume - 0.08) / 0.92, 0, 1) ** 0.75  # corta ruído de fundo, realça sílabas

    espectro = np.abs(np.fft.rfft(quadros * np.hanning(passo), axis=1)) ** 2
    freqs = np.fft.rfftfreq(passo, 1 / fs)
    graves = espectro[:, (freqs >= 250) & (freqs < 1000)].sum(axis=1) + 1e-6
    agudos = espectro[:, (freqs >= 1000) & (freqs < 3000)].sum(axis=1) + 1e-6
    razao = np.log(agudos / graves)
    sonoros = volume > 0.2
    if sonoros.sum() > 5:
        razao = (razao - np.median(razao[sonoros])) / (razao[sonoros].std() + 1e-6)
    else:
        razao = np.zeros_like(razao)
    timbre = np.tanh(np.convolve(razao, np.ones(5) / 5, mode="same"))
    return volume.tolist(), timbre.tolist()


MARGEM_INICIO_S = 0.03  # o ataque da primeira sílaba não pode ser cortado
MARGEM_FIM_S = 0.15  # respiro natural entre uma frase e a próxima
LIMIAR_SILENCIO = 0.02  # fração do pico (RMS em janelas de 10 ms) abaixo da qual é silêncio


def limites_da_fala(amostras: ArrayLike, fs: int, margem_inicio_s: float = MARGEM_INICIO_S,
                    margem_fim_s: float = MARGEM_FIM_S, limiar: float = LIMIAR_SILENCIO) -> tuple[int, int]:
    """Índices [início, fim) do trecho com fala, com margens; o áudio inteiro se não houver silêncio.

    A voz sintetizada traz ~0,25 s de silêncio antes e ~1 s depois de cada frase. Como a resposta
    é tocada frase a frase, esse silêncio virava pausas artificiais de mais de um segundo entre
    as frases e atrasava a primeira palavra."""
    x = np.abs(np.asarray(amostras, dtype=np.float32))
    janela = max(1, int(fs * 0.01))
    n = len(x) // janela
    if n == 0:
        return 0, len(x)
    rms = np.sqrt((x[: n * janela].reshape(n, janela) ** 2).mean(axis=1))
    ativos = np.flatnonzero(rms > rms.max() * limiar)
    if len(ativos) == 0:
        return 0, len(x)
    inicio = max(0, ativos[0] * janela - int(fs * margem_inicio_s))
    fim = min(len(x), (ativos[-1] + 1) * janela + int(fs * margem_fim_s))
    return int(inicio), int(fim)


def interpolar(valores: Sequence[float], posicao: float) -> float:
    """Valor interpolado linearmente em `posicao` (índice fracionário); 0 fora do intervalo."""
    i = int(posicao)
    if posicao < 0 or i + 1 >= len(valores):
        return 0.0
    return valores[i] + (valores[i + 1] - valores[i]) * (posicao - i)


def rms_pcm16(dados: bytes) -> float:
    """Volume (RMS) de um bloco PCM de 16 bits."""
    if len(dados) < 2:
        return 0.0
    x = np.frombuffer(dados[: len(dados) // 2 * 2], dtype=np.int16).astype(np.float32)
    return float(np.sqrt((x * x).mean()))
