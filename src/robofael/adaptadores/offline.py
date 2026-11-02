"""Modelo de linguagem offline: comandos de agenda, hora, data, histórico e programas por expressões
regulares. Entende português e inglês; responde no idioma do `Tradutor`."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import datetime

from robofael.aplicacao.memoria import Memoria
from robofael.aplicacao.programas import ServicoProgramas
from robofael.dominio.agenda import Agenda, TarefaNaoEncontrada
from robofael.dominio.linguagem import pergunta_historico
from robofael.dominio.periodos import Periodo, interpretar_periodo
from robofael.dominio.programas import extrair_pedido
from robofael.dominio.quando import interpretar_quando, sem_trechos
from robofael.i18n import Tradutor

_ANOTAR = re.compile(r"\b(?:adicionar|adiciona|adicione|anota|anotar|anote|a nota|nova|cria|criar|crie|"
                     r"add|new|create|make|put)(?: uma| um| a| an| new| nova| novo)* (?:tarefa|task)\b"
                     r"(?: to my list| on my list| na lista| na minha lista)?[:,]?\s*(.+)", re.I)
_SOBRA_TAREFA = re.compile(r"^(?:to|called|named|chamada|:)\s+", re.I)  # "add a task to buy milk"
_CONCLUIR = re.compile(r"(?:conclu\w*|terminei|feita|complete[ds]?|finish(?:ed)?|done with|mark)"
                       r" (?:a |the )?(?:tarefa|task) (?:number |n[uú]mero )?(\d+)", re.I)
# "concluir todas as tarefas", "marca todas as minhas tarefas como feitas", "complete all my tasks"
_CONCLUIR_TODAS = re.compile(
    r"\b(?:conclu\w*|finaliz\w*|termin\w*|marc\w*|fech\w*|complete[ds]?|finish\w*|mark|close|check off)"
    r"(?:\s+[\w']+){0,2}?\s+(?:todas|all)(?:\s+(?:as|of|the|my|minhas|of my|of the))*\s+(?:tarefas|tasks|to.?dos)\b",
    re.I)
_LEMBRETE = re.compile(
    r"\b(?:remind(?: me)?|set (?:a |an )?(?:reminder|alarm)|(?:create|add|make|new) (?:a )?reminder|"
    r"me lembr[ae]r?|lembr[ae]-me|me avis[ae]r?|(?:cri[ae]r?|novo|adiciona) (?:um )?lembrete)\b"
    r"|^\s*(?:um |a |novo |new )?(?:lembrete|reminder)\b", re.I)  # a palavra solta só no começo da frase
_PERGUNTA = re.compile(
    r"\?\s*$|^\s*(?:tenho|tem|quais|qual|quantos|existe|h[áa]|do i|have i|are there|is there|what|which|any)\b",
    re.I)  # "tenho algum lembrete para amanhã?" é consulta, não pedido
_CONECTIVOS_LEMBRETE = re.compile(r"^(?:to|about|that|of|for|me|de|da|do|que|para|pra|sobre|:|,|-)\s*", re.I)
_TAREFAS = re.compile(r"tarefa|\btasks?\b|to.?do", re.I)
_HORA = re.compile(r"\bhoras?\b|\bwhat time\b|\btime is it\b", re.I)
_DATA = re.compile(r"\b(dia|data)\b|\bwhat day\b|\bthe date\b|\btoday'?s date\b", re.I)


def descrever_momento(momento: datetime, agora: datetime, tr: Tradutor) -> str:
    """'hoje às 15:30', 'amanhã às 09:00', 'em 05/11/2026 às 10:00' (no idioma do tradutor)."""
    dias = (momento.date() - agora.date()).days
    chave = {0: "off.quando_hoje", 1: "off.quando_amanha"}.get(dias, "off.quando_data")
    return tr(chave, h=momento, data=tr.data(momento))


Intencao = Callable[[str, datetime], str | None]  # devolve a resposta, ou None se não é com ela


class ModeloOffline:
    """Cadeia de intenções: cada uma tenta reconhecer a fala; a primeira que responder vence.
    Aberto para extensão: uma intenção nova é um método a mais em `intencoes`."""

    online = False
    provedor = "offline"
    modelo: str | None = None

    def __init__(self, agenda: Agenda, relogio: Callable[[], datetime] = datetime.now,
                 memoria: Memoria | None = None, programas: ServicoProgramas | None = None,
                 tradutor: Tradutor | None = None):
        self.agenda = agenda
        self.relogio = relogio
        self.memoria = memoria
        self.programas = programas
        self.tr = tradutor or (memoria.tr if memoria else programas.tr if programas else Tradutor())
        # A ordem importa: comandos de agenda vêm antes de programas ("anota tarefa abrir conta
        # no banco" é uma tarefa) e as consultas genéricas (tarefas, hora, data) ficam por último.
        self.intencoes: tuple[Intencao, ...] = (
            self._historico, self._anotar, self._concluir_todas, self._concluir, self._lembrar, self._abrir_programa,
            self._listar_pendentes, self._hora, self._data,
        )

    def reiniciar(self) -> None:
        pass

    def responder(self, fala: str) -> Iterator[str]:
        yield self.interpretar(fala)

    def interpretar(self, fala: str) -> str:
        resposta = self.tentar(fala)
        return resposta if resposta is not None else self.tr("off.ajuda")

    def tentar(self, fala: str) -> str | None:
        """Resposta de uma intenção reconhecida, ou None se nenhuma reconheceu a fala
        (quem usa o modo offline como primeira camada decide o que fazer com o resto)."""
        f, agora = fala.strip(), self.relogio()
        return next((r for intencao in self.intencoes if (r := intencao(f, agora)) is not None), None)

    # ---------- Intenções ----------
    def _historico(self, f: str, agora: datetime) -> str | None:
        if not pergunta_historico(f):
            return None
        tr = self.tr
        if self.memoria is None:
            return tr("off.sem_historico")
        hoje = agora.date()
        periodo = interpretar_periodo(f, hoje, tr) or Periodo.dias(hoje, hoje, tr("per.hoje", d=tr.dia_mes(hoje)))
        return self.memoria.responder(periodo)

    def _anotar(self, f: str, _agora: datetime) -> str | None:
        if not (m := _ANOTAR.search(f)):
            return None
        texto = _SOBRA_TAREFA.sub("", m.group(1).strip()).strip(" .") or m.group(1)
        return self.tr("off.anotei", texto=self.agenda.adicionar_tarefa(texto).texto)

    def _concluir(self, f: str, _agora: datetime) -> str | None:
        if not (m := _CONCLUIR.search(f)):
            return None
        try:
            return self.tr("off.concluida", texto=self.agenda.concluir_tarefa(int(m.group(1))).texto)
        except TarefaNaoEncontrada:
            return self.tr("off.tarefa_nao_achada")

    def _concluir_todas(self, f: str, _agora: datetime) -> str | None:
        if _PERGUNTA.search(f) or not _CONCLUIR_TODAS.search(f):
            return None
        tr, concluidas = self.tr, self.agenda.concluir_todas()
        if not concluidas:
            return tr("off.nada_a_concluir")
        return tr("off.todas_concluidas", n=len(concluidas), tarefas=tr.plural(len(concluidas), "un.tarefa"))

    def _lembrar(self, f: str, agora: datetime) -> str | None:
        """"remind me to drink water in 5 minutes", "me lembra amanhã às 9 da reunião": o horário pode vir
        em qualquer posição. Sem horário reconhecível, deixa a fala para o modelo de linguagem."""
        if _PERGUNTA.search(f) or not (gatilho := _LEMBRETE.search(f)) or not (quando := interpretar_quando(f, agora)):
            return None
        texto = sem_trechos(f, (gatilho.span(), *quando.trechos))
        while (limpo := _CONECTIVOS_LEMBRETE.sub("", texto, count=1).strip()) != texto:
            texto = limpo
        tr = self.tr
        self.agenda.criar_lembrete(texto.strip(" .!?") or tr("off.lembrete_padrao"), quando.momento)
        if quando.relativo_min is not None and quando.relativo_min < 60:
            n = quando.relativo_min
            return tr("off.lembrete_criado", n=n, minutos=tr.plural(n, "un.minuto"))
        return tr("off.lembrete_criado_em", quando=descrever_momento(quando.momento, agora, tr))

    def _abrir_programa(self, f: str, _agora: datetime) -> str | None:
        if self.programas is None or not (pedido := extrair_pedido(f)):
            return None
        return self.programas.abrir(pedido)["frase"]

    def _listar_pendentes(self, f: str, _agora: datetime) -> str | None:
        if not _TAREFAS.search(f):
            return None
        tr, ts = self.tr, self.agenda.pendentes()
        if not ts:
            return tr("off.sem_pendentes")
        itens = "; ".join(f"{t.id}: {t.texto}" for t in ts[:5])
        return tr("off.pendentes", n=len(ts), tarefas=tr.plural(len(ts), "un.tarefa"),
                  pendentes=tr.plural(len(ts), "un.pendente"), itens=itens)

    def _hora(self, f: str, agora: datetime) -> str | None:
        return self.tr("off.hora", h=agora) if _HORA.search(f) else None

    def _data(self, f: str, agora: datetime) -> str | None:
        return self.tr("off.data", dia=self.tr.dia_semana(agora), data=self.tr.data(agora)) if _DATA.search(f) else None
