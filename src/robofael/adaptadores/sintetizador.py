"""Síntese de voz: edge-tts (voz neural, com o perfil de tom do usuário) e gTTS de reserva,
com cache em disco das falas já sintetizadas (saudações e lembretes saem instantâneos)."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


class SintetizadorEdge:
    def __init__(self, voz: str, tom: str = "+0Hz", ritmo: str = "+0%",
                 pasta_cache: Path | None = None, max_itens_cache: int = 300):
        self.voz, self.tom, self.ritmo = voz, tom, ritmo
        self.pasta_cache = Path(pasta_cache) if pasta_cache else None
        self.max_itens_cache = max_itens_cache
        self.gtts = ("pt", "com.br")  # (lang, tld) da voz de reserva

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
        try:
            audio = asyncio.run(self._edge(texto))
            if not audio:
                raise RuntimeError("edge-tts não devolveu áudio")
        except Exception as e:
            log.warning("edge-tts indisponível (%s); usando gTTS", e)
            audio = self._gtts(texto, *self.gtts)
        if arquivo:
            self._guardar(arquivo, audio)
        return audio

    async def _edge(self, texto: str) -> bytes:
        import edge_tts

        buffer = io.BytesIO()
        async for parte in edge_tts.Communicate(texto, self.voz, rate=self.ritmo, pitch=self.tom).stream():
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
        chave = hashlib.sha1(f"{self.voz}|{self.tom}|{self.ritmo}|{texto}".encode()).hexdigest()
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
