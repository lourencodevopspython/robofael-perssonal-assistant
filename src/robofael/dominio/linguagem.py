"""Regras de linguagem da conversa: intenções reconhecidas por padrão e data/hora por extenso.

O reconhecimento de intenções aceita português e inglês ao mesmo tempo (quem fala não precisa
lembrar em que idioma o assistente está); as respostas usam o idioma do `Tradutor`."""

from __future__ import annotations

import re
from datetime import datetime

from robofael.i18n import DIAS_SEMANA as _DIAS
from robofael.i18n import Idioma

DIAS_SEMANA = _DIAS[Idioma.PT_BR]
_DESPEDIDA = re.compile(r"\b(tchau|até logo|pode parar|encerrar|bye|goodbye|stop listening|that's all)\b", re.I)
_NOVA_CONVERSA = re.compile(
    r"\b(nova conversa|esquece tudo|reiniciar conversa|new conversation|start over|forget everything)\b", re.I)
_HISTORICO = re.compile(
    r"\b(o que|que)\s+(eu\s+)?(fiz|realizei|conclu\w*|terminei|finalizei|completei|entreguei)\b"
    r"|\b(meu|o)\s+hist[oó]rico\b|\b(minhas\s+)?atividades\s+(de|da|do|na|no|em)\b"
    r"|\bwhat\s+(did|have)\s+i\s+(do|done|finish(ed)?|complete[d]?|accomplish(ed)?|get done)\b"
    r"|\bmy\s+(history|activities)\b",
    re.I,
)


def descrever_agora(agora: datetime, idioma: Idioma = Idioma.PT_BR) -> str:
    """Ex.: 'quarta-feira, 2026-10-21 16:25' / 'Wednesday, 2026-10-21 16:25' (contexto para o modelo)."""
    return f"{_DIAS[idioma][agora.weekday()]}, {agora:%Y-%m-%d %H:%M}"


def eh_despedida(texto: str) -> bool:
    return bool(_DESPEDIDA.search(texto))


def pede_nova_conversa(texto: str) -> bool:
    return bool(_NOVA_CONVERSA.search(texto))


def pergunta_historico(texto: str) -> bool:
    """'o que eu fiz ontem?', 'what did I do last week?', 'meu histórico de segunda'..."""
    return bool(_HISTORICO.search(texto))


def plural(n: int, palavra: str) -> str:
    return f"{palavra}{'s' if n != 1 else ''}"


def juntar(itens: list[str], conector: str = "e") -> str:
    """['a', 'b', 'c'] -> 'a, b e c'."""
    if len(itens) <= 1:
        return "".join(itens)
    return ", ".join(itens[:-1]) + f" {conector} " + itens[-1]


_AGENDA = re.compile(
    r"\b(lembr\w*|tarefas?|anot\w*|agenda\w*|compromisso\w*|reuni\w*|pendente\w*|avis\w*|"
    r"remind\w*|reminders?|tasks?|to.?dos?|schedul\w*|appointments?|meetings?)\b", re.I)


def pede_agenda(fala: str) -> bool:
    """A fala é sobre tarefas, lembretes ou o histórico? Decide se um modelo local recebe as ferramentas
    (com elas disponíveis, modelos pequenos tendem a chamá-las até numa conversa casual)."""
    return bool(_AGENDA.search(fala)) or pergunta_historico(fala)
