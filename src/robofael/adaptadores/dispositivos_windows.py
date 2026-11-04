"""Microfones no Windows, pelo PyAudio (PortAudio).

No Linux a escolha vai numa variável do servidor de áudio (dispositivos_audio.py); no Windows não há
servidor intermediário, então o microfone escolhido é aberto pelo índice do dispositivo. O índice muda
quando se conecta ou desconecta um aparelho, por isso o que se guarda é o nome, e o índice é procurado de
novo a cada abertura. Usa só a API MME: ela converte a taxa de amostragem (o reconhecimento pede 16 kHz,
que a WASAPI exclusiva recusa) e lista cada microfone uma única vez."""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from typing import Any

from robofael.portas import Microfone

log = logging.getLogger(__name__)

API_MME = 2  # paMME em `paHostApiTypeId`


def _abrir_pyaudio() -> Any:
    import pyaudio

    return pyaudio.PyAudio()


def entradas(criar: Callable[[], Any] = _abrir_pyaudio) -> list[tuple[int, str]]:
    """(índice, nome) dos dispositivos de entrada da API MME."""
    pa = criar()
    try:
        mme = next((i for i in range(pa.get_host_api_count()) if pa.get_host_api_info_by_index(i)["type"] == API_MME),
                   None)
        encontrados = []
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0 and (mme is None or info.get("hostApi") == mme):
                nome = str(info.get("name", "")).strip()
                if nome and not nome.lower().startswith(("microsoft sound mapper", "mapeador de som")):
                    encontrados.append((i, nome))
        return encontrados
    finally:
        pa.terminate()


class DispositivosWindows:
    def __init__(self, criar: Callable[[], Any] = _abrir_pyaudio):
        self._criar = criar

    def microfones(self) -> list[Microfone]:
        try:
            return [Microfone(nome, nome) for _, nome in entradas(self._criar)]
        except Exception as e:
            log.warning("Não foi possível listar os microfones: %s", e)
            return []


def indice_microfone(id_microfone: str | None, criar: Callable[[], Any] = _abrir_pyaudio,
                     plataforma: str = sys.platform) -> int | None:
    """Índice do microfone escolhido no Windows; None para abrir o padrão (fora do Windows, sem escolha ou
    com o microfone desconectado)."""
    if plataforma != "win32" or not id_microfone:
        return None
    try:
        return next((i for i, nome in entradas(criar) if nome == id_microfone), None)
    except Exception as e:
        log.warning("Não foi possível achar o microfone %s: %s", id_microfone, e)
        return None
