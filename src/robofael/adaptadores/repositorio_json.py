"""Agenda no formato JSON das versões anteriores (escrita atômica, recuperação de arquivo corrompido).

Hoje serve só para a migração para o SQLite. De propósito, NÃO implementa `RepositorioAgenda`:
o JSON guarda apenas o estado, sem o histórico auditável, então usá-lo no lugar do `BancoSqlite`
perderia a memória de longo prazo em silêncio (violaria a substituição de Liskov). Sem o
parâmetro `eventos`, o verificador de tipos impede essa troca."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from robofael.dominio.modelos import DadosAgenda

log = logging.getLogger(__name__)


class RepositorioJson:
    def __init__(self, arquivo: Path):
        self.arquivo = Path(arquivo)

    def carregar(self) -> DadosAgenda:
        if not self.arquivo.exists():
            return DadosAgenda()
        try:
            return DadosAgenda.de_dict(json.loads(self.arquivo.read_text(encoding="utf-8")))
        except (ValueError, KeyError, TypeError) as e:
            # Nunca apaga os dados do usuário: guarda o arquivo ruim ao lado e começa vazio
            copia = self.arquivo.with_name(f"{self.arquivo.stem}.corrompido-{datetime.now():%Y%m%d-%H%M%S}.json")
            self.arquivo.rename(copia)
            log.warning("Agenda corrompida (%s); cópia guardada em %s", e, copia.name)
            return DadosAgenda()

    def salvar(self, dados: DadosAgenda) -> None:
        """Escreve num temporário e troca com os.replace: o arquivo nunca fica pela metade."""
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        conteudo = json.dumps(dados.para_dict(), ensure_ascii=False, indent=2)
        fd, temporario = tempfile.mkstemp(dir=self.arquivo.parent, prefix=f".{self.arquivo.name}.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(conteudo)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporario, self.arquivo)
        except BaseException:
            Path(temporario).unlink(missing_ok=True)
            raise
