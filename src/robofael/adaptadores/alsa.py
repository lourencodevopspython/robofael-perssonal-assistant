"""Silencia o ruído das bibliotecas nativas de áudio no terminal.

O PyAudio procura o servidor JACK e o ALSA tenta dispositivos inexistentes a cada vez que o
microfone é aberto; essas bibliotecas C escrevem direto no descritor 2 (stderr), por fora
do `logging`. Aqui o ALSA ganha um tratador vazio e as aberturas do microfone rodam com o
stderr nativo redirecionado para /dev/null."""

from __future__ import annotations

import ctypes
import os
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager

_handler = None
_trava = threading.Lock()


def silenciar_alsa() -> None:
    global _handler
    if _handler is not None:
        return
    try:
        tipo = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p)
        _handler = tipo(lambda *_args: None)  # manter referência viva
        ctypes.cdll.LoadLibrary("libasound.so.2").snd_lib_error_set_handler(_handler)
    except OSError:
        pass  # não é Linux/ALSA


@contextmanager
def stderr_nativo_silenciado() -> Iterator[None]:
    """Redireciona o fd 2 para /dev/null durante o bloco (inclui mensagens do JACK).

    Usar só em trechos curtos (abrir/fechar o microfone): durante o bloco, qualquer outra
    escrita em stderr do processo também é descartada."""
    try:
        fd = sys.stderr.fileno()
    except (AttributeError, OSError, ValueError):  # stderr substituído (ex.: pytest)
        yield
        return
    with _trava:
        sys.stderr.flush()
        copia = os.dup(fd)
        nulo = os.open(os.devnull, os.O_WRONLY)
        os.dup2(nulo, fd)
        os.close(nulo)
        try:
            yield
        finally:
            sys.stderr.flush()
            os.dup2(copia, fd)
            os.close(copia)
