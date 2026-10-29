"""Microfone com detecção de fala própria (VAD) + reconhecimento do Google.

Comparado ao `Recognizer.listen()`, a captura própria permite: publicar o nível do microfone
em tempo real (as barras da interface mostram a sua voz de verdade), cancelar a escuta a
qualquer momento e encerrar a frase com uma pausa menor (resposta mais rápida)."""

from __future__ import annotations

import collections
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import speech_recognition as sr

from robofael.adaptadores.alsa import silenciar_alsa, stderr_nativo_silenciado
from robofael.adaptadores.dispositivos_audio import microfone_escolhido
from robofael.audio.analise import rms_pcm16
from robofael.audio.ganho import GanhoAutomatico, pico_pcm16
from robofael.audio.vad import DetectorFala, StatusFala, nivel_visual
from robofael.i18n import Tradutor

log = logging.getLogger(__name__)

PRE_GRAVACAO_S = 0.35  # guarda o início da palavra que disparou a detecção


class ErroReconhecimento(RuntimeError):
    """Falha do serviço de reconhecimento (geralmente falta de internet)."""


class MicrofoneGoogle:
    def __init__(self, idioma: str = "pt-BR", pausa_fim_s: float = 0.7, tradutor: Tradutor | None = None,
                 microfone: Callable[[], str | None] = lambda: None):
        """`microfone` diz, a cada abertura, qual microfone usar (None = o padrão do sistema):
        trocar a escolha vale na próxima escuta, com uma nova calibração."""
        silenciar_alsa()
        self.tr = tradutor
        self._idioma_fixo = idioma
        self.pausa_fim_s = pausa_fim_s
        self._escolhido = microfone
        with stderr_nativo_silenciado():
            self._mic = sr.Microphone()
        self._rec = sr.Recognizer()
        self._calibrar_microfone()

    def _calibrar_microfone(self) -> None:
        self._calibrado_para = self._escolhido()
        self.limiar, ruido = self._calibrar()
        self._ganho = GanhoAutomatico(ruido)
        log.info("Microfone %s calibrado (limiar de fala: %.0f)", self._calibrado_para or "padrão", self.limiar)

    @contextmanager
    def _aberto(self) -> Iterator[sr.Microphone]:
        """Abre o microfone escolhido sem deixar o PyAudio/JACK poluírem o terminal."""
        with stderr_nativo_silenciado(), microfone_escolhido(self._escolhido()):
            fonte = self._mic.__enter__()
        try:
            yield fonte
        finally:
            with stderr_nativo_silenciado():
                self._mic.__exit__(None, None, None)

    def _calibrar(self, segundos: float = 0.8) -> tuple[float, float]:
        """Limiar de fala e ruído típico do ambiente (mediana do RMS)."""
        with self._aberto() as fonte:
            blocos = int(segundos * fonte.SAMPLE_RATE / fonte.CHUNK)
            ruido = sorted(rms_pcm16(fonte.stream.read(fonte.CHUNK)) for _ in range(blocos))
        return DetectorFala.calibrar(ruido), (ruido[len(ruido) // 2] if ruido else 0.0)

    def capturar(self, cancelar: threading.Event, ao_nivel: Callable[[float], None] | None = None,
                 espera_max_s: float = 7.0, frase_max_s: float = 20.0) -> sr.AudioData | None:
        """Grava uma frase completa; None se cancelado ou se ninguém falou."""
        if self._escolhido() != self._calibrado_para:  # outro microfone: outro ruído de fundo
            self._calibrar_microfone()
        with self._aberto() as fonte:
            dur_bloco = fonte.CHUNK / fonte.SAMPLE_RATE
            detector = DetectorFala(self.limiar, self.pausa_fim_s, espera_max_s, frase_max_s)
            pre: collections.deque[bytes] = collections.deque(maxlen=max(1, int(PRE_GRAVACAO_S / dur_bloco)))
            fala: list[bytes] = []
            while not cancelar.is_set():
                bloco = fonte.stream.read(fonte.CHUNK)
                rms = rms_pcm16(bloco)
                if ao_nivel:
                    ao_nivel(nivel_visual(rms, self.limiar))
                status = detector.processar(rms, dur_bloco)
                if rms >= self.limiar:
                    self._ganho.observar_fala(pico_pcm16(bloco))
                if status is StatusFala.SEM_FALA:
                    return None
                if status is StatusFala.AGUARDANDO:
                    if fala:  # era só um ruído curto: descarta
                        fala.clear()
                    pre.append(bloco)
                    continue
                if not fala:
                    fala.extend(pre)
                fala.append(bloco)
                if status is StatusFala.CONCLUIDO:
                    # A detecção usa o áudio bruto (coerente com a calibração); o reconhecimento
                    # recebe o áudio com ganho automático
                    audio = b"".join(self._ganho.aplicar(b) for b in fala)
                    return sr.AudioData(audio, fonte.SAMPLE_RATE, fonte.SAMPLE_WIDTH)
            return None

    def ouvir(self, cancelar: threading.Event, ao_nivel: Callable[[float], None] | None = None) -> str | None:
        audio = self.capturar(cancelar, ao_nivel)
        if audio is None or cancelar.is_set():
            return None
        return self.transcrever(audio)

    @property
    def idioma(self) -> str:
        """Idioma do reconhecimento: segue o tradutor (troca ao vivo) ou o informado na criação."""
        return self.tr.idioma.value if self.tr is not None else self._idioma_fixo

    def transcrever(self, audio: sr.AudioData) -> str | None:
        try:
            return self._rec.recognize_google(audio, language=self.idioma)
        except sr.UnknownValueError:
            return None
        except sr.RequestError as e:
            raise ErroReconhecimento((self.tr or Tradutor())("mic.sem_internet")) from e
