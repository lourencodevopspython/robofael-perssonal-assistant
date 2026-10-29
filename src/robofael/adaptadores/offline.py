"""Modelo de linguagem offline: comandos de agenda, hora, data, histórico e programas por expressões
regulares. Entende português e inglês; responde no idioma do `Tradutor`."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta

from robofael.aplicacao.memoria import Memoria
from robofael.aplicacao.programas import ServicoProgramas
from robofael.dominio.agenda import Agenda, TarefaNaoEncontrada
from robofael.dominio.linguagem import pergunta_historico
from robofael.dominio.periodos import Periodo, interpretar_periodo
from robofael.dominio.programas import extrair_pedido
from robofael.i18n import Tradutor

_ANOTAR = re.compile(r"(?:adicionar|adiciona|anota|anotar|a nota|nova|add(?: a)?(?: new)?|new|create(?: a)?)"
                     r" (?:tarefa|task):?\s*(.+)", re.I)
_CONCLUIR = re.compile(r"(?:conclu\w*|terminei|feita|complete[ds]?|finish(?:ed)?|done with|mark)"
                       r" (?:a |the )?(?:tarefa|task) (?:number |n[uú]mero )?(\d+)", re.I)
_LEMBRAR = re.compile(r"(?:lembr[\w-]* (?:daqui a |em )|remind me in |reminder in )(\d+) (?:minutos?|minutes?)"
                      r"(?: de| para| to| about| that)?\s*(.*)", re.I)
_TAREFAS = re.compile(r"tarefa|\btasks?\b|to.?do", re.I)
_HORA = re.compile(r"\bhoras?\b|\bwhat time\b|\btime is it\b", re.I)
_DATA = re.compile(r"\b(dia|data)\b|\bwhat day\b|\bthe date\b|\btoday'?s date\b", re.I)


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
            self._historico, self._anotar, self._concluir, self._lembrar, self._abrir_programa,
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
        return self.tr("off.anotei", texto=self.agenda.adicionar_tarefa(m.group(1)).texto)

    def _concluir(self, f: str, _agora: datetime) -> str | None:
        if not (m := _CONCLUIR.search(f)):
            return None
        try:
            return self.tr("off.concluida", texto=self.agenda.concluir_tarefa(int(m.group(1))).texto)
        except TarefaNaoEncontrada:
            return self.tr("off.tarefa_nao_achada")

    def _lembrar(self, f: str, agora: datetime) -> str | None:
        if not (m := _LEMBRAR.search(f)):
            return None
        tr, minutos = self.tr, int(m.group(1))
        self.agenda.criar_lembrete(m.group(2) or tr("off.lembrete_padrao"), agora + timedelta(minutes=minutos))
        return tr("off.lembrete_criado", n=minutos, minutos=tr.plural(minutos, "un.minuto"))

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
