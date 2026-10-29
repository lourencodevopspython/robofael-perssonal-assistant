"""Gerar documento: transforma uma resposta do assistente num arquivo Markdown.

O serviço lembra a última troca (pergunta e resposta), monta o documento com título, data e pedido,
e o grava pela porta `ArquivoDocumentos`. Quem decide quando falar e quando pensar é o orquestrador."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from robofael.dominio.documentos import nome_arquivo, titulo_documento
from robofael.i18n import Tradutor
from robofael.portas import ArquivoDocumentos


@dataclass(frozen=True, slots=True)
class Troca:
    pergunta: str
    resposta: str


class ServicoDocumentos:
    def __init__(self, arquivos: ArquivoDocumentos, tradutor: Tradutor,
                 relogio: Callable[[], datetime] = datetime.now):
        self.arquivos = arquivos
        self.tr = tradutor
        self.relogio = relogio
        self.ultima_troca: Troca | None = None

    def registrar_troca(self, pergunta: str, resposta: str) -> None:
        if resposta.strip():
            self.ultima_troca = Troca(pergunta, resposta.strip())

    def pedido_ao_modelo(self, assunto: str, online: bool) -> str:
        """Com um modelo de linguagem, pede um texto de documento (mais longo que uma resposta falada);
        no modo offline, o assunto vai como está ("gerar doc das minhas tarefas pendentes")."""
        return self.tr("doc.pedido_modelo", assunto=assunto) if online else assunto

    def salvar(self, pedido: str, conteudo: str) -> Path:
        """Grava o documento e devolve o caminho. O título vem do pedido."""
        quando = self.relogio()
        titulo = titulo_documento(pedido)
        texto = self._limpar(conteudo)
        documento = (f"# {titulo}\n\n"
                     f"*{self.tr('doc.gerado_em', assistente='Robofael', data=self.tr.data(quando), h=quando)}*\n\n"
                     f"**{self.tr('doc.pedido')}:** {pedido.strip()}\n\n"
                     f"{texto}\n")
        return self.arquivos.salvar(nome_arquivo(titulo, quando), documento)

    def _limpar(self, conteudo: str) -> str:
        """Tira o aviso falado que alguns modelos dão antes de pensar ("Só um instante.")."""
        texto = conteudo.strip()
        aviso = self.tr("local.aguarde")
        return texto.removeprefix(aviso).strip() or texto
