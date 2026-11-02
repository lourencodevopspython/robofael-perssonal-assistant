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


# "mudar para inglês", "muda o idioma pra português", "fale em inglês", "switch to Portuguese please".
# O verbo abre a frase e o idioma a fecha: "como se fala cachorro em inglês?" é pergunta, não pedido.
_TROCA_IDIOMA = re.compile(
    r"^\s*(?:(?:ok|okay|ei|hey)(?:\s+\w+)?[,\s]+)?(?:(?:por favor|agora|please|now)[,\s]+)?"
    r"(?:mud\w*|troc\w*|alter\w*|pass[ae]r?|fal[ae]r?|respond\w*|change|switch|speak|talk|answer|reply)\b"
    r"(?:\s+(?:o|a|os|as|de|do|da|seu|sua|idioma|l[ií]ngua|respostas?|comigo|para|pra|em|no|na|"
    r"the|your|language|answers?|with|me|to|in|into|only))*\s+(?P<idioma>ingl[eê]s|english|portugu[eê]s|portuguese)"
    r"(?:[,\s]+(?:por favor|please|agora|now))?\s*[.!]?\s*$", re.I)


def pede_troca_idioma(texto: str) -> Idioma | None:
    """'mudar para inglês' -> Idioma.EN_US; 'change to Portuguese' -> Idioma.PT_BR; outra fala -> None."""
    if not (m := _TROCA_IDIOMA.search(texto)):
        return None
    return Idioma.EN_US if m.group("idioma").lower().startswith(("ingl", "engl")) else Idioma.PT_BR


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
