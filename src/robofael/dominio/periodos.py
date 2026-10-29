"""Interpretação de períodos ditos em português ou inglês ("ontem", "last week", "dia 20/10"...).

Usado para responder "o que eu fiz ...?" consultando a memória de longo prazo. Sempre se
refere ao passado: "segunda"/"monday" é a mais recente antes de hoje; "dia 30" num dia 22 é o
dia 30 do mês anterior. Datas numéricas seguem o idioma: 05/10 é 5 de outubro em português e
10 de maio em inglês. A descrição do período sai no idioma do `Tradutor`."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from robofael.i18n import Idioma, Tradutor

DIAS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6,
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
         "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
         "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
         "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
_NUMEROS = {"dois": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
            "dez": 10, "quinze": 15, "trinta": 30, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
            "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "thirty": 30}
_MES = "|".join(MESES)
SABADO = DIAS["sabado"]
_TRADUTOR_PADRAO = Tradutor()


@dataclass(frozen=True, slots=True)
class Periodo:
    inicio: datetime  # inclusivo
    fim: datetime  # exclusivo
    descricao: str  # como falar o período: "ontem (21/10)", "last week (10/12 to 10/18)"

    @classmethod
    def dias(cls, primeiro: date, ultimo: date, descricao: str) -> Periodo:
        return cls(datetime.combine(primeiro, time.min), datetime.combine(ultimo + timedelta(days=1), time.min),
                   descricao)


def _normalizar(texto: str) -> str:
    sem_acento = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", sem_acento.replace("-feira", "")).strip()


def _data_passada(dia: int, mes: int | None, ano: int | None, hoje: date) -> date | None:
    """Monta a data; sem mês/ano, escolhe a ocorrência mais recente que não esteja no futuro."""
    try:
        if ano is not None and mes is not None:
            return date(ano if ano > 99 else 2000 + ano, mes, dia)
        if mes is not None:
            d = date(hoje.year, mes, dia)
            return d if d <= hoje else date(hoje.year - 1, mes, dia)
        d = date(hoje.year, hoje.month, dia)
        if d <= hoje:
            return d
        mes_anterior = hoje.replace(day=1) - timedelta(days=1)
        return date(mes_anterior.year, mes_anterior.month, dia)
    except ValueError:
        return None


def _semana_de(d: date) -> tuple[date, date]:
    segunda = d - timedelta(days=d.weekday())
    return segunda, segunda + timedelta(days=6)


def _data_explicita(t: str, hoje: date, numerica: Callable[[str, str, str | None], date | None]) -> date | None:
    """'20/10', '20/10/2025', '5 de outubro', 'October 5th, 2025', '5 October'."""
    if m := re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", t):
        return numerica(m[1], m[2], m[3])
    if m := re.search(r"\b(\d{1,2})(?:st|nd|rd|th)? (?:de |of )?(" + _MES + r")(?:,? (?:de )?(\d{4}))?\b", t):
        return _data_passada(int(m[1]), MESES[m[2]], int(m[3]) if m[3] else None, hoje)
    if m := re.search(r"\b(" + _MES + r") (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?\b", t):
        return _data_passada(int(m[2]), MESES[m[1]], int(m[3]) if m[3] else None, hoje)
    return None


@dataclass(frozen=True, slots=True)
class _Contexto:
    """O que cada interpretador precisa: o texto normalizado, a data de hoje e o idioma."""

    texto: str
    hoje: date
    tr: Tradutor

    def numerica(self, a: str, b: str, ano: str | None) -> date | None:
        """'05/10': dia/mês em português, mês/dia em inglês."""
        dia, mes = (int(b), int(a)) if self.tr.idioma is Idioma.EN_US else (int(a), int(b))
        return _data_passada(dia, mes, int(ano) if ano else None, self.hoje)

    def semana(self, d: date, chave: str) -> Periodo:
        ini, fim = _semana_de(d)
        return Periodo.dias(ini, fim, self.tr(chave, i=self.tr.dia_mes(ini), f=self.tr.dia_mes(fim)))


def _semana_de_data(c: _Contexto) -> Periodo | None:
    m = re.search(r"(?:semana (?:do dia |de |do )?|week of (?:the )?)(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?",
                  c.texto)
    alvo = c.numerica(m[1], m[2], m[3]) if m else None
    return c.semana(alvo, "per.semana_de") if alvo else None


def _semana_passada(c: _Contexto) -> Periodo | None:
    if re.search(r"\b(semana passada|ultima semana|semana anterior|last week|previous week|past week)\b", c.texto):
        return c.semana(c.hoje - timedelta(days=7), "per.semana_passada")
    return None


def _esta_semana(c: _Contexto) -> Periodo | None:
    if not re.search(r"\b(esta|essa|nesta|nessa) semana\b|\bsemana atual\b|\bthis week\b", c.texto):
        return None
    ini, _ = _semana_de(c.hoje)
    return Periodo.dias(ini, c.hoje, c.tr("per.esta_semana", i=c.tr.dia_mes(ini), f=c.tr.dia_mes(c.hoje)))


def _ultimos_dias(c: _Contexto) -> Periodo | None:
    if not (m := re.search(r"\b(?:ultimos|last|past) (\d+|" + "|".join(_NUMEROS) + r") (?:dias|days)\b", c.texto)):
        return None
    n = int(m[1]) if m[1].isdigit() else _NUMEROS[m[1]]
    ini = c.hoje - timedelta(days=n - 1)
    return Periodo.dias(ini, c.hoje, c.tr("per.ultimos_dias", n=n, i=c.tr.dia_mes(ini), f=c.tr.dia_mes(c.hoje)))


def _mes_passado(c: _Contexto) -> Periodo | None:
    if not re.search(r"\b(mes passado|ultimo mes|last month|previous month)\b", c.texto):
        return None
    fim = c.hoje.replace(day=1) - timedelta(days=1)
    return Periodo.dias(fim.replace(day=1), fim, c.tr("per.mes_passado", m=f"{fim:%m/%Y}"))


def _este_mes(c: _Contexto) -> Periodo | None:
    if not re.search(r"\b(este|esse|neste|nesse) mes\b|\bthis month\b", c.texto):
        return None
    return Periodo.dias(c.hoje.replace(day=1), c.hoje, c.tr("per.este_mes", m=f"{c.hoje:%m/%Y}"))


_DIAS_RELATIVOS = (("per.anteontem", r"\b(anteontem|day before yesterday)\b", 2),
                   ("per.ontem", r"\b(ontem|yesterday)\b", 1), ("per.hoje", r"\b(hoje|today)\b", 0))


def _dia_relativo(c: _Contexto) -> Periodo | None:
    for chave, padrao, atras in _DIAS_RELATIVOS:
        if re.search(padrao, c.texto):
            d = c.hoje - timedelta(days=atras)
            return Periodo.dias(d, d, c.tr(chave, d=c.tr.dia_mes(d)))
    return None


def _data_completa(c: _Contexto) -> Periodo | None:
    data = _data_explicita(c.texto, c.hoje, c.numerica)
    return Periodo.dias(data, data, c.tr("per.data", d=c.tr.data(data))) if data else None


def _dia_do_mes(c: _Contexto) -> Periodo | None:
    m = re.search(r"\bdia (\d{1,2})\b|\bthe (\d{1,2})(?:st|nd|rd|th)\b", c.texto)
    data = _data_passada(int(m[1] or m[2]), None, None, c.hoje) if m else None
    return Periodo.dias(data, data, c.tr("per.dia", d=c.tr.dia_mes(data))) if data else None


def _dia_da_semana(c: _Contexto) -> Periodo | None:
    if not (m := re.search(r"\b(" + "|".join(DIAS) + r")\b", c.texto)):
        return None
    atras = (c.hoje.weekday() - DIAS[m[1]]) % 7 or 7  # sempre a mais recente ANTES de hoje
    d = c.hoje - timedelta(days=atras)
    chave = "per.dia_util" if d.weekday() < SABADO else "per.fim_de_semana"
    return Periodo.dias(d, d, c.tr(chave, nome=c.tr.dia_semana(d), d=c.tr.dia_mes(d)))


# Do mais específico para o mais genérico: "semana do dia 20/10" antes de "20/10"; "dia 20" depois das datas.
_INTERPRETADORES = (_semana_de_data, _semana_passada, _esta_semana, _ultimos_dias, _mes_passado, _este_mes,
                    _dia_relativo, _data_completa, _dia_do_mes, _dia_da_semana)


def interpretar_periodo(texto: str, hoje: date, tradutor: Tradutor | None = None) -> Periodo | None:
    contexto = _Contexto(_normalizar(texto), hoje, tradutor or _TRADUTOR_PADRAO)
    return next((p for interpretar in _INTERPRETADORES if (p := interpretar(contexto)) is not None), None)
