"""Contrato de persistência que o domínio exige (inversão de dependência).

O serviço de domínio `Agenda` declara aqui do que precisa; a infraestrutura (SQLite) o
implementa. Assim o domínio não conhece banco de dados nenhum."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from robofael.dominio.modelos import DadosAgenda, RegistroAuditoria


class RepositorioAgenda(Protocol):
    def carregar(self) -> DadosAgenda: ...
    def salvar(self, dados: DadosAgenda, eventos: Sequence[RegistroAuditoria] = ()) -> None:
        """Persiste o estado e os registros de auditoria da alteração, atomicamente."""
        ...
