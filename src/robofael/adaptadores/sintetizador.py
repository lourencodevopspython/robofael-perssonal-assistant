"""Síntese de voz: edge-tts (voz neural, com o perfil de tom do usuário) e gTTS de reserva,
com cache em disco das falas já sintetizadas (saudações e lembretes saem instantâneos).

Cada frase é sintetizada à parte, então uma falha passageira do edge-tts no meio de uma resposta
trocaria a voz (o gTTS só tem voz feminina) só naquela frase. Por isso o edge-tts é tentado de novo
antes de cair na reserva; se ele cair de vez, a reserva segue por PAUSA_RESERVA em vez de alternar
frase a frase; e o áudio da reserva nunca entra no cache (senão a frase sairia sempre na outra voz)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
import time
from pathlib import Path

log = logging.getLogger(__name__)

ESPERAS_EDGE = (0.3, 0.8)  # entre as tentativas do edge-tts (3 tentativas ao todo)
PAUSA_RESERVA = 60.0  # s usando só a reserva depois que o edge-tts falha em todas as tentativas
VERSAO_CACHE = "2"  # a 1 podia guardar áudio da reserva com a chave da voz neural


class SintetizadorEdge:
    def __init__(self, voz: str, tom: str = "+0Hz", ritmo: str = "+0%",
                 pasta_cache: Path | None = None, max_itens_cache: int = 300):
        self.voz, self.tom, self.ritmo = voz, tom, ritmo
        self.pasta_cache = Path(pasta_cache) if pasta_cache else None
        self.max_itens_cache = max_itens_cache
        self.gtts = ("pt", "com.br")  # (lang, tld) da voz de reserva
        self._reserva_ate = 0.0  # time.monotonic() até quando o edge-tts é dado como fora

    def configurar(self, voz: str, tom: str, ritmo: str, gtts: tuple[str, str] | None = None) -> None:
        """Troca a voz em uso (o cache considera voz/tom/ritmo, então nada antigo é reaproveitado)."""
        self.voz, self.tom, self.ritmo = voz, tom, ritmo
        if gtts:
            self.gtts = gtts

    def sintetizar(self, texto: str) -> bytes:
        arquivo = self._arquivo_cache(texto)
        if arquivo and arquivo.exists():
            os.utime(arquivo)  # marca como usado recentemente (LRU)
            return arquivo.read_bytes()
        audio = self._edge_com_tentativas(texto) if time.monotonic() >= self._reserva_ate else None
        if audio is None:
            return self._gtts(texto, *self.gtts)
        if arquivo:
            self._guardar(arquivo, audio)
        return audio

    def _edge_com_tentativas(self, texto: str) -> bytes | None:
        """O áudio da voz neural, ou None se o edge-tts falhou em todas as tentativas."""
        for tentativa, espera in enumerate((*ESPERAS_EDGE, None), start=1):
            try:
                audio = asyncio.run(self._edge(texto))
                if audio:
                    return audio
                erro: Exception = RuntimeError("edge-tts não devolveu áudio")
            except Exception as e:
                erro = e
            if espera is None:
                break
            log.info("edge-tts falhou (tentativa %d: %s); tentando de novo", tentativa, erro)
            time.sleep(espera)
        self._reserva_ate = time.monotonic() + PAUSA_RESERVA
        log.warning("edge-tts indisponível (%s); usando gTTS por %.0f s", erro, PAUSA_RESERVA)
        return None

    async def _edge(self, texto: str) -> bytes:
        import edge_tts

        buffer = io.BytesIO()
        async for parte in edge_tts.Communicate(texto, self.voz, rate=self.ritmo, pitch=self.tom,
                                                  connect_timeout=5, receive_timeout=15).stream():
            if parte["type"] == "audio":
                buffer.write(parte["data"])
        return buffer.getvalue()

    @staticmethod
    def _gtts(texto: str, lang: str = "pt", tld: str = "com.br") -> bytes:
        from gtts import gTTS

        buffer = io.BytesIO()
        gTTS(texto, lang=lang, tld=tld).write_to_fp(buffer)
        return buffer.getvalue()

    # ---------- Cache ----------
    def _arquivo_cache(self, texto: str) -> Path | None:
        if not self.pasta_cache:
            return None
        chave = hashlib.sha1(f"{VERSAO_CACHE}|{self.voz}|{self.tom}|{self.ritmo}|{texto}".encode()).hexdigest()
        return self.pasta_cache / f"{chave}.mp3"

    def _guardar(self, arquivo: Path, audio: bytes) -> None:
        try:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            temporario = arquivo.with_suffix(".tmp")
            temporario.write_bytes(audio)
            os.replace(temporario, arquivo)
            self._podar()
        except OSError as e:
            log.debug("Cache de voz indisponível: %s", e)

    def _podar(self) -> None:
        if self.pasta_cache is None:
            return
        itens = sorted(self.pasta_cache.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
        for velho in itens[: max(0, len(itens) - self.max_itens_cache)]:
            velho.unlink(missing_ok=True)
