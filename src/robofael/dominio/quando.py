"""Quando? Interpreta expressões de tempo futuras em português e inglês, para lembretes.

Relativas: "in 5 minutes", "in five minutes", "in an hour", "in half an hour", "daqui a 10 minutos",
"em uma hora", "daqui a meia hora".
Absolutas: "at 3 pm", "at 15:30", "tomorrow at 9", "tonight at 8", "às 15h", "amanhã às 9h30",
"às 3 da tarde", "9 am", "tomorrow 09:00".

Sem dia explícito, um horário que já passou hoje vira amanhã; "amanhã" sem horário vira 9h.
Devolve também os trechos reconhecidos, para tirá-los do texto do lembrete."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta

HORA_PADRAO = time(9, 0)  # "me lembra amanhã de pagar a conta"
ULTIMA_HORA_AMBIGUA_TARDE = 7  # sem am/pm: 1–7 é tarde/noite; 8–12, manhã/meio-dia

_NUMEROS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
    "forty": 40, "forty-five": 45, "fifty": 50, "sixty": 60,
    "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "três": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
    "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "quinze": 15, "vinte": 20, "trinta": 30,
    "quarenta": 40, "quarenta e cinco": 45, "cinquenta": 50, "sessenta": 60,
}
_NUM = r"(?P<n>\d+|" + "|".join(sorted((re.escape(k) for k in _NUMEROS), key=len, reverse=True)) + r")"

_RELATIVO = re.compile(
    r"\b(?:in|within|after|daqui\s+a|daqui|em|dentro\s+de)\s+(?:about\s+|uns\s+|umas\s+)?" + _NUM +
    r"\s+(?P<u>minutos?|minutes?|mins?|horas?|hours?|hrs?)\b", re.I)
_MEIA_HORA = re.compile(r"\b(?:in\s+half\s+an\s+hour|(?:daqui\s+a|em|dentro\s+de)\s+meia\s+hora)\b", re.I)
_DIA = re.compile(r"\b(?P<d>tomorrow|tonight|today|amanh[ãa]|hoje|hoje\s+à\s+noite|depois\s+de\s+amanh[ãa])\b", re.I)
_HORARIO = re.compile(
    r"(?:\b(?:at|às|as|a\s+las|pelas|by)\s+)?"
    r"\b(?P<h>\d{1,2})(?:(?::|h|\.)(?P<m>\d{2}))?\s*"
    r"(?P<s>a\.?m\.?|p\.?m\.?|h(?:oras?)?\b|o'?clock)?"
    r"(?:\s*(?P<p>da\s+manh[ãa]|da\s+tarde|da\s+noite|in\s+the\s+morning|in\s+the\s+afternoon|"
    r"in\s+the\s+evening|at\s+night))?", re.I)


@dataclass(frozen=True, slots=True)
class Quando:
    momento: datetime
    trechos: tuple[tuple[int, int], ...]  # posições reconhecidas no texto (para removê-las)
    relativo_min: int | None = None  # "daqui a N minutos": a resposta fala em minutos


def _numero(texto: str) -> int:
    return int(texto) if texto.isdigit() else _NUMEROS[texto.lower()]


def _relativo(texto: str, agora: datetime) -> Quando | None:
    if m := _MEIA_HORA.search(texto):
        return Quando(agora + timedelta(minutes=30), (m.span(),), 30)
    if not (m := _RELATIVO.search(texto)):
        return None
    n = _numero(m["n"])
    minutos = n * 60 if m["u"].lower().startswith(("h", "hr")) else n
    return Quando(agora + timedelta(minutes=minutos), (m.span(),), minutos)


def _horario(texto: str) -> tuple[time, tuple[int, int]] | None:
    """O primeiro horário explícito: precisa de "at/às", minutos, am/pm, "h" ou período do dia."""
    for m in _HORARIO.finditer(texto):
        tem_prefixo = m.group(0).strip().lower().startswith(("at", "às", "as", "a las", "pelas", "by"))
        if not (tem_prefixo or m["m"] or m["s"] or m["p"]):
            continue  # um número solto ("tarefa 3") não é horário
        h, minuto = int(m["h"]), int(m["m"] or 0)
        sufixo, periodo = (m["s"] or "").lower().replace(".", ""), (m["p"] or "").lower()
        tarde = sufixo == "pm" or any(p in periodo for p in ("tarde", "noite", "afternoon", "evening", "night"))
        manha = sufixo == "am" or any(p in periodo for p in ("manh", "morning"))
        if h < 12 and (tarde or (1 <= h <= ULTIMA_HORA_AMBIGUA_TARDE and not manha and m["s"] is None)):
            h += 12  # "às 3" sem am/pm nem período: 15h (ninguém marca lembrete para as 3 da madrugada)
        elif sufixo == "am" and h == 12:
            h = 0
        if h > 23 or minuto > 59:
            continue
        return time(h, minuto), m.span()
    return None


_DIAS_SEMANA = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
                "segunda": 0, "terça": 1, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sábado": 5, "sabado": 5,
                "domingo": 6}
_DIA_SEMANA = re.compile(
    r"\b(?:(?:next|this|on|coming)\s+|(?:na|no|nesta|neste|na\s+pr[óo]xima|no\s+pr[óo]ximo|pr[óo]xim[ao])\s+)?"
    r"(?P<d>" + "|".join(_DIAS_SEMANA) + r")(?:-feira)?(?:\s+que\s+vem)?\b", re.I)


@dataclass(frozen=True, slots=True)
class _Dia:
    dias: int  # a partir de hoje
    trecho: tuple[int, int]
    noite: bool = False


def _dia(texto: str, agora: datetime) -> _Dia | None:
    """'amanhã', 'tonight', 'next friday', 'na sexta que vem'… (dia da semana: sempre o próximo, depois de hoje)."""
    if m := _DIA.search(texto):
        nome = m["d"].lower()
        dias = 2 if "depois" in nome else 1 if nome.startswith(("tomorrow", "amanh")) else 0
        return _Dia(dias, m.span(), noite="noite" in nome or nome == "tonight")
    if m := _DIA_SEMANA.search(texto):
        return _Dia((_DIAS_SEMANA[m["d"].lower()] - agora.weekday() - 1) % 7 + 1, m.span())
    return None


def interpretar_quando(texto: str, agora: datetime) -> Quando | None:
    """O momento futuro descrito no texto, ou None se não houver um."""
    if relativo := _relativo(texto, agora):
        return relativo
    dia = _dia(texto, agora)
    horario = _horario(texto)
    if not dia and not horario:
        return None
    trechos = ((dia.trecho,) if dia else ()) + ((horario[1],) if horario else ())
    noite = dia is not None and dia.noite
    hora = horario[0] if horario else (time(20, 0) if noite else HORA_PADRAO)
    if horario and noite and hora.hour < 12:
        hora = time(hora.hour + 12, hora.minute)
    momento = datetime.combine(agora.date() + timedelta(days=dia.dias if dia else 0), hora)
    if not dia and momento <= agora:
        momento += timedelta(days=1)  # "às 9" depois das 9: amanhã
    return Quando(momento, trechos)


def sem_trechos(texto: str, trechos: tuple[tuple[int, int], ...]) -> str:
    """O texto sem os trechos de tempo reconhecidos."""
    partes, inicio = [], 0
    for a, b in sorted(trechos):
        partes.append(texto[inicio:a])
        inicio = max(inicio, b)
    partes.append(texto[inicio:])
    return " ".join("".join(partes).split())
