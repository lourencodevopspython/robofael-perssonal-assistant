"""Documentos gerados pelo assistente, gravados como Markdown numa pasta do usuário."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

EXTENSAO = ".md"  # texto puro legível em qualquer editor, com títulos e negrito onde há suporte


class PastaDocumentos:
    def __init__(self, pasta: Path):
        self.pasta = Path(pasta)

    def salvar(self, nome: str, conteudo: str) -> Path:
        """Grava sem sobrescrever (acrescenta " (2)", " (3)"…) e de forma atômica: o arquivo nunca
        aparece pela metade."""
        self.pasta.mkdir(parents=True, exist_ok=True)
        destino = self.pasta / f"{nome}{EXTENSAO}"
        n = 2
        while destino.exists():
            destino = self.pasta / f"{nome} ({n}){EXTENSAO}"
            n += 1
        fd, temporario = tempfile.mkstemp(dir=self.pasta, prefix=".robofael-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(conteudo)
            os.replace(temporario, destino)
        except BaseException:
            Path(temporario).unlink(missing_ok=True)
            raise
        return destino
