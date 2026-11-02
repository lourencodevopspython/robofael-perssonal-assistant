"""Pedido de tradução de tarefas e lembretes, comum ao Claude e ao Ollama: instruções, entrada e leitura
da resposta.

Os itens vão numerados ({"1": ..., "2": ...}) e voltam com os mesmos números: com uma lista simples,
modelos pequenos às vezes pulam ou repetem um item e todos os seguintes saem trocados de lugar."""

from __future__ import annotations

import json

from robofael.i18n import Idioma


def esquema(n: int) -> dict:
    """Esquema JSON da resposta (o Ollama o impõe na geração): uma chave por item."""
    chaves = [str(i) for i in range(1, n + 1)]
    return {"type": "object", "properties": {c: {"type": "string"} for c in chaves}, "required": chaves}


def instrucoes(idioma: str) -> str:
    nome = Idioma.de_texto(idioma).nome
    return (f"You translate short personal to-do items and reminders shown in a task list. The input is a JSON "
            f"object of numbered items. Translate each item into {nome} ({idioma}); if an item is already in that "
            f"language, copy it unchanged. Keep the meaning, names and numbers and the short style of a to-do "
            f"item; never add explanations or quotes. Answer only with a JSON object with the same numbers as keys "
            f"and each translated item as the value.")


def entrada(textos: list[str]) -> str:
    return json.dumps({str(i): t for i, t in enumerate(textos, start=1)}, ensure_ascii=False)


def ler_traducoes(resposta: str, n: int) -> list[str]:
    """Os textos traduzidos, na ordem da entrada; ValueError se faltar algum número ou a resposta não for
    o JSON pedido (aceita cercas de markdown em volta)."""
    inicio, fim = resposta.find("{"), resposta.rfind("}")
    dados = json.loads(resposta[inicio:fim + 1]) if 0 <= inicio < fim else None
    itens = [dados.get(str(i)) for i in range(1, n + 1)] if isinstance(dados, dict) else []
    textos = [i for i in itens if isinstance(i, str)]
    if len(textos) != n:
        raise ValueError(f"resposta de tradução inesperada: {resposta[:200]!r}")
    return textos
