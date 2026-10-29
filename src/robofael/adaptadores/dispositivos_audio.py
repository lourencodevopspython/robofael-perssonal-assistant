"""Microfones do computador, pelo servidor de áudio (PipeWire ou PulseAudio).

O PyAudio só enxerga dispositivos ALSA, e abrir um `hw:` direto disputa o aparelho com o
PipeWire e exige taxa e canais exatos. Por isso o microfone é aberto sempre pelo dispositivo
padrão, e a escolha vai numa variável de ambiente que o plugin do servidor de áudio lê na
hora de abrir o stream: `PIPEWIRE_NODE` (PipeWire) e `PULSE_SOURCE` (PulseAudio). Se o
microfone escolhido não existir mais, o servidor usa o padrão do sistema."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager

from robofael.portas import Microfone

log = logging.getLogger(__name__)

VARIAVEIS_FONTE = ("PIPEWIRE_NODE", "PULSE_SOURCE")
_trava_ambiente = threading.Lock()


def ler_fontes(saida_pactl: str) -> list[Microfone]:
    """Microfones na saída de `pactl list sources` (em inglês), sem os monitores das saídas de som."""
    microfones, nome, descricao, monitor = [], "", "", False

    def fechar() -> None:
        if nome and not monitor and not nome.endswith(".monitor"):
            microfones.append(Microfone(nome, descricao or nome))

    for linha in saida_pactl.splitlines():
        if linha.startswith("Source #"):
            fechar()
            nome, descricao, monitor = "", "", False
            continue
        chave, _, valor = linha.strip().partition(": ")
        if chave == "Name":
            nome = valor.strip()
        elif chave == "Description":
            descricao = valor.strip()
        elif chave == "Monitor of Sink":
            monitor = valor.strip() not in ("", "n/a")
    fechar()
    return microfones


class DispositivosPulse:
    """Lista os microfones com o `pactl` (funciona no PulseAudio e no PipeWire)."""

    def microfones(self) -> list[Microfone]:
        try:
            saida = subprocess.run(["pactl", "list", "sources"], capture_output=True, text=True, timeout=3,
                                   env=dict(os.environ, LC_ALL="C"), check=True).stdout
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("Não foi possível listar os microfones (pactl): %s", e)
            return []
        return ler_fontes(saida)


@contextmanager
def microfone_escolhido(id_microfone: str | None) -> Iterator[None]:
    """Use em volta da abertura do stream: ele vai para o microfone escolhido.
    A variável fica definida só durante a abertura, para não vazar para os programas que o
    assistente abre; a trava evita que duas aberturas simultâneas se misturem."""
    if not id_microfone:
        yield
        return
    with _trava_ambiente:
        anteriores = {v: os.environ.get(v) for v in VARIAVEIS_FONTE}
        os.environ.update(dict.fromkeys(VARIAVEIS_FONTE, id_microfone))
        try:
            yield
        finally:
            for variavel, valor in anteriores.items():
                if valor is None:
                    os.environ.pop(variavel, None)
                else:
                    os.environ[variavel] = valor
