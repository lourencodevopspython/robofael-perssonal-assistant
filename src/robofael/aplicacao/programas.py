"""Caso de uso "abrir um programa instalado": escolhe, desambigua e responde em voz."""

from __future__ import annotations

import logging

from robofael.dominio.programas import escolher, normalizar, ranquear
from robofael.i18n import Tradutor
from robofael.portas import LancadorProgramas, Programa

log = logging.getLogger(__name__)

PEDIDOS_DE_NAVEGADOR = {"navegador", "internet", "browser", "navegador de internet", "navegador web",
                        "web browser"}


class ServicoProgramas:
    def __init__(self, lancador: LancadorProgramas, tradutor: Tradutor | None = None):
        self.lancador = lancador
        self.tr = tradutor or Tradutor()

    def localizar(self, pedido: str) -> Programa | list[Programa] | None:
        programas = self.lancador.programas()
        if normalizar(pedido) in PEDIDOS_DE_NAVEGADOR:
            padrao = getattr(self.lancador, "navegador_padrao", lambda: None)()
            if padrao is not None:
                return padrao
        return escolher(ranquear(pedido, programas))

    def abrir(self, pedido: str) -> dict:
        """Resultado estruturado (para o modelo) com a frase pronta (para o modo offline)."""
        escolha = self.localizar(pedido)
        if escolha is None:
            return {"ok": False, "frase": self.tr("prog.nao_encontrado", pedido=pedido)}
        if isinstance(escolha, list):
            nomes = [p.nome for p in escolha]
            return {"ok": False, "opcoes": nomes,
                    "frase": self.tr("prog.opcoes", lista=self.tr.juntar(nomes))}
        try:
            self.lancador.abrir(escolha)
        except Exception as e:
            log.warning("Falha ao abrir %s: %s", escolha.nome, e)
            return {"ok": False, "frase": self.tr("prog.falha", nome=escolha.nome)}
        return {"ok": True, "programa": escolha.nome, "frase": self.tr("prog.abrindo", nome=escolha.nome)}

    def listar(self, filtro: str = "") -> dict:
        programas = self.lancador.programas()
        if filtro:
            programas = [c.programa for c in ranquear(filtro, programas)]
        nomes = [p.nome for p in programas]
        return {"total": len(nomes), "programas": nomes[:40]}
