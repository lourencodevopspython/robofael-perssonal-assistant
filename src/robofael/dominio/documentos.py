"""Pedido de documento: "gerar doc" salva em arquivo uma resposta do assistente.

- "gerar doc" (ou "gerar doc dessa resposta") → salva a última resposta;
- "gerar doc sobre a história da aviação" → escreve um documento sobre o assunto e o salva.

Entende português e inglês ("generate a doc about…") e variações comuns do reconhecimento de fala
("gerar dock", "gera um documento")."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

_PEDIDO = re.compile(
    r"^\s*(?:por favor,?\s+|please,?\s+)?"
    r"(?:gera|gerar|gere|cria|criar|crie|faz|faça|faca|fazer|escreve|escrever|escreva|monta|montar|"
    r"generate|create|make|write)\s+"
    r"(?:um\s+|uma\s+|o\s+|a\s+|an?\s+|the\s+)?(?:doc|docs|dock|documento|document)\b[\s,:.\-]*(?P<resto>.*)$",
    re.I,
)
_CONECTIVO = re.compile(
    r"^(?:sobre|a respeito de|acerca de|com|de|do|da|dos|das|about|on|of|with|for)\s+", re.I)
# Palavras que, sozinhas, se referem à resposta anterior ("disso", "dessa resposta", "the last answer")
_REFERENCIAS_A_RESPOSTA = frozenset({
    "isso", "disso", "isto", "disto", "esse", "essa", "desse", "dessa", "deste", "desta", "este", "esta", "a", "o",
    "ultima", "última", "anterior", "sua", "resposta", "it", "that", "this", "the", "last", "previous", "your",
    "answer", "reply", "response"})
MAX_TITULO = 80
MAX_NOME_ARQUIVO = 60


@dataclass(frozen=True, slots=True)
class PedidoDocumento:
    assunto: str | None  # None: salvar a última resposta do assistente


def interpretar_pedido_documento(fala: str) -> PedidoDocumento | None:
    """O pedido de documento contido na fala, ou None se a fala não pede um documento."""
    m = _PEDIDO.match(fala)
    if not m:
        return None
    resto = _CONECTIVO.sub("", m["resto"].strip(" .,;:!?")).strip()
    if all(palavra in _REFERENCIAS_A_RESPOSTA for palavra in resto.lower().split()):
        return PedidoDocumento(None)  # inclui o pedido sem assunto ("gerar doc")
    return PedidoDocumento(resto)


def titulo_documento(texto: str) -> str:
    """Título legível: primeira letra maiúscula, sem pontuação final, no máximo MAX_TITULO caracteres."""
    titulo = " ".join(texto.split()).strip(" .,;:!?")
    if len(titulo) > MAX_TITULO:
        titulo = titulo[:MAX_TITULO].rsplit(" ", 1)[0] + "…"
    return titulo[:1].upper() + titulo[1:]


def nome_arquivo(titulo: str, quando: datetime) -> str:
    """'2026-10-29 1015 - historia-da-aviacao' (sem extensão): ordena por data e funciona em qualquer sistema."""
    ascii_ = unicodedata.normalize("NFKD", titulo).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:MAX_NOME_ARQUIVO].rstrip("-") or "documento"
    return f"{quando:%Y-%m-%d %H%M} - {slug}"
