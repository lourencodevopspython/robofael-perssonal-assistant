"""Escuta passiva da frase de ativação com Vosk (reconhecimento 100% local).

Enquanto o assistente está parado, o microfone fica aberto e o Vosk analisa cada fala
localmente; nada sai do computador. Dois modos:

- frase com gramática calibrada (ex.: "ok Fael"): o reconhecedor só escolhe entre as
  variantes aceitas e frases distratoras, o que torna confiável uma frase curta;
- outras frases: transcrição livre + busca fonética (`localizar_ativacao`).

Depois de detectar a frase, espera um instante: se a pessoa continua falando ("ok Fael,
anota tarefa..."), grava o comando até o fim e o devolve para ser transcrito com precisão."""

from __future__ import annotations

import collections
import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import speech_recognition as sr

from robofael.adaptadores.alsa import silenciar_alsa, stderr_nativo_silenciado
from robofael.adaptadores.dispositivos_audio import microfone_escolhido
from robofael.audio.analise import rms_pcm16
from robofael.audio.ganho import GanhoAutomatico, pico_pcm16
from robofael.audio.vad import DetectorFala, StatusFala
from robofael.dominio.ativacao import gramatica_para, limpar_desconhecidas, localizar_ativacao
from robofael.portas import Ativacao

log = logging.getLogger(__name__)

TAXA = 16000  # o modelo do Vosk trabalha a 16 kHz
BLOCO = 1600  # 100 ms
ESPERA_CONTINUACAO_S = 0.9  # silêncio após a frase = só chamou (toca o bipe)
COMANDO_MAX_S = 15.0
CAUDA_S = 1.0  # o reconhecedor fecha a fala da frase com atraso: o comando pode já ter começado
HISTORICO_RUIDO_S = 4.0
# Voz ativa acima disso na fala da frase = o comando veio junto (no modo gramática o
# reconhecedor às vezes devolve só "ok fel" e descarta as palavras de fora da gramática)
FALA_SO_FRASE_MAX_S = 1.5


class AtivacaoVosk:
    def __init__(self, pasta_modelo: Path, frase: str, ao_voz_baixa: Callable[[float], None] | None = None,
                 microfone: Callable[[], str | None] = lambda: None):
        import vosk

        silenciar_alsa()
        vosk.SetLogLevel(-1)
        if not Path(pasta_modelo).is_dir():
            raise FileNotFoundError(f"Modelo do Vosk não encontrado em {pasta_modelo}")
        self._vosk = vosk
        self._modelo = vosk.Model(str(pasta_modelo))
        self.frase = frase
        self._gramatica = gramatica_para(frase)
        self._ao_voz_baixa = ao_voz_baixa
        self._ganho: GanhoAutomatico | None = None  # criado após medir o ruído do ambiente
        self._avisou_voz_baixa = False
        self._escolhido = microfone  # consultado a cada abertura (None = o padrão do sistema)
        self._ganho_de: str | None = None  # microfone em que o ganho foi medido
        with stderr_nativo_silenciado():
            self._mic = sr.Microphone(sample_rate=TAXA, chunk_size=BLOCO)

    def _novo_reconhecedor(self) -> Any:
        if self._gramatica is not None:
            return self._vosk.KaldiRecognizer(self._modelo, TAXA, json.dumps(self._gramatica.frases()))
        return self._vosk.KaldiRecognizer(self._modelo, TAXA)

    def _detectar(self, texto: str) -> str | None:
        """None se não é a frase; senão o resto da fala (pode ter "[unk]" no modo gramática)."""
        if self._gramatica is not None:
            return self._gramatica.analisar(texto)
        return localizar_ativacao(texto, self.frase)

    def aguardar(self, cancelar: threading.Event) -> Ativacao | None:
        """Bloqueia até ouvir a frase de ativação (ou até `cancelar`)."""
        reconhecedor = self._novo_reconhecedor()
        escolhido = self._escolhido()
        if escolhido != self._ganho_de:  # outro microfone: mede o ruído e o ganho de novo
            self._ganho, self._ganho_de, self._avisou_voz_baixa = None, escolhido, False
        with stderr_nativo_silenciado(), microfone_escolhido(escolhido):
            fonte = self._mic.__enter__()
        try:
            fala: list[bytes] = []
            ruido: collections.deque[float] = collections.deque(maxlen=int(HISTORICO_RUIDO_S * TAXA / BLOCO))
            while not cancelar.is_set():
                bloco = fonte.stream.read(BLOCO)
                fala.append(bloco)
                ruido.append(rms_pcm16(bloco))
                ganho = self._medir_ganho(bloco, ruido)
                if not reconhecedor.AcceptWaveform(ganho.aplicar(bloco)):
                    continue
                texto = json.loads(reconhecedor.Result()).get("text", "")
                if texto:
                    pico = max((pico_pcm16(b) for b in fala), default=0.0)
                    log.debug("Escuta passiva ouviu: %r (pico %.0f, ganho automático x%.1f)", texto, pico, ganho.ganho)
                    self._avisar_se_voz_baixa(ganho)
                    resto = self._detectar(texto)
                    if resto is not None:
                        log.info("Ativação por voz (%r)", texto)
                        # Piso de ruído: os blocos mais silenciosos (a própria frase não pode entrar na conta)
                        limiar = DetectorFala.calibrar(sorted(ruido)[: max(1, len(ruido) // 4)])
                        voz_ativa = sum(rms_pcm16(b) >= limiar for b in fala) * BLOCO / TAXA
                        comando_junto = bool(resto) or voz_ativa > FALA_SO_FRASE_MAX_S
                        # Com comando junto, a fala inteira vai para a transcrição; senão, só o
                        # finzinho dela (onde o comando pode ter começado antes do corte)
                        inicio = fala if comando_junto else fala[-max(1, int(CAUDA_S * TAXA / BLOCO)):]
                        continuacao = self._capturar_continuacao(fonte, cancelar, limiar)
                        if continuacao is None and not comando_junto:
                            return Ativacao("")  # só chamou: o orquestrador toca o bipe e ouve
                        audio = b"".join(ganho.aplicar(b) for b in inicio + (continuacao or []))
                        return Ativacao(limpar_desconhecidas(resto), sr.AudioData(audio, TAXA, 2),
                                        audio_inclui_frase=comando_junto)
                fala.clear()  # fim de uma fala sem a frase: descarta o áudio
            return None
        finally:
            with stderr_nativo_silenciado():
                self._mic.__exit__(None, None, None)

    def _medir_ganho(self, bloco: bytes, ruido: collections.deque[float]) -> GanhoAutomatico:
        if self._ganho is None:
            if len(ruido) < 10:  # ~1 s para conhecer o ruído do ambiente
                return GanhoAutomatico()
            self._ganho = GanhoAutomatico(sorted(ruido)[len(ruido) // 2])
        if rms_pcm16(bloco) >= DetectorFala.calibrar(sorted(ruido)[: max(1, len(ruido) // 4)]):
            self._ganho.observar_fala(pico_pcm16(bloco))
        return self._ganho

    def _avisar_se_voz_baixa(self, ganho: GanhoAutomatico) -> None:
        if ganho.voz_baixa and not self._avisou_voz_baixa and ganho.pico_fala is not None:
            self._avisou_voz_baixa = True  # uma vez por sessão
            log.warning("Voz chegando baixa ao microfone (pico ~%.0f): aumente o volume de entrada",
                        ganho.pico_fala)
            if self._ao_voz_baixa:
                self._ao_voz_baixa(ganho.pico_fala)

    def _capturar_continuacao(self, fonte: sr.Microphone, cancelar: threading.Event,
                              limiar: float) -> list[bytes] | None:
        """Depois da frase: se a pessoa segue falando, devolve os blocos até ela parar;
        None se ficou em silêncio (detecção por energia, com o piso de ruído recente)."""
        detector = DetectorFala(limiar, pausa_s=0.7, espera_max_s=ESPERA_CONTINUACAO_S, frase_max_s=COMANDO_MAX_S)
        blocos: list[bytes] = []
        while not cancelar.is_set():
            bloco = fonte.stream.read(BLOCO)
            blocos.append(bloco)
            status = detector.processar(rms_pcm16(bloco), BLOCO / TAXA)
            if status is StatusFala.SEM_FALA:
                return None
            if status is StatusFala.CONCLUIDO:
                return blocos
        return None
