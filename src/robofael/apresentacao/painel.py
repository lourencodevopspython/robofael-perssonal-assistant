"""Painel lateral interativo: relógio, tarefas e lembretes.

Duplo clique (ou ENTER) conclui/reabre uma tarefa; DELETE remove o item selecionado.
O painel só é redesenhado quando a agenda muda (evento), não a cada segundo."""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from typing import Any

from robofael.aplicacao.traducao import FEITAS_VISIVEIS
from robofael.apresentacao.tema import BORDA, CARTAO, DESTAQUE, FONTE, SUPERFICIE, TEXTO, TEXTO_APAGADO, TEXTO_SUAVE
from robofael.dominio.agenda import Agenda
from robofael.i18n import Tradutor

log = logging.getLogger(__name__)


class PainelAgenda(tk.Frame):
    def __init__(self, mestre: tk.Misc, agenda: Agenda, tradutor: Tradutor | None = None,
                 exibir: Callable[[str], str] = lambda texto: texto, **kw: Any) -> None:
        super().__init__(mestre, bg=SUPERFICIE, highlightbackground=BORDA, highlightthickness=2, **kw)
        self.agenda = agenda
        self.tr = tradutor or Tradutor()
        self.exibir = exibir  # o texto de cada item no idioma atual (traduzido, se já houver tradução)
        self._ids_tarefas: list[int] = []
        self._ids_lembretes: list[int] = []

        self.lbl_hora = tk.Label(self, bg=SUPERFICIE, fg=TEXTO, font=(FONTE, 28, "bold"))
        self.lbl_hora.pack(pady=(14, 0))
        self.lbl_data = tk.Label(self, bg=SUPERFICIE, fg=TEXTO_SUAVE, font=(FONTE, 11))
        self.lbl_data.pack(pady=(0, 10))

        self.lbl_tarefas, self.lista_tarefas = self._secao(DESTAQUE, altura=13)
        self.lbl_lembretes, self.lista_lembretes = self._secao("#ffc94a", altura=7)
        self.lbl_dica = tk.Label(self, bg=SUPERFICIE, fg=TEXTO_APAGADO, font=(FONTE, 9))
        self.lbl_dica.pack(side="bottom", pady=(0, 8))
        self._rotular()

        for evento in ("<Double-Button-1>", "<Return>"):
            self.lista_tarefas.bind(evento, self._alternar_tarefa)
        self.lista_tarefas.bind("<Delete>", self._remover_tarefa)
        self.lista_lembretes.bind("<Delete>", self._remover_lembrete)
        self.atualizar()
        self._tique()

    def _rotular(self) -> None:
        self.lbl_tarefas.configure(text=self.tr("painel.tarefas"))
        self.lbl_lembretes.configure(text=self.tr("painel.lembretes"))
        self.lbl_dica.configure(text=self.tr("painel.dica"))

    def traduzir(self) -> None:
        self._rotular()
        self.atualizar()

    def _secao(self, cor: str, altura: int) -> tuple[tk.Label, tk.Listbox]:
        rotulo = tk.Label(self, bg=SUPERFICIE, fg=cor, font=(FONTE, 11, "bold"), anchor="w")
        rotulo.pack(fill="x", padx=16, pady=(8, 4))
        lista = tk.Listbox(self, height=altura, bg=CARTAO, fg=TEXTO, font=(FONTE, 11), relief="flat",
                           highlightthickness=0, selectbackground="#22345a", selectforeground=TEXTO,
                           activestyle="none", borderwidth=6)
        lista.pack(fill="x", padx=14)
        return rotulo, lista

    def atualizar(self) -> None:
        pendentes = self.agenda.pendentes()
        feitas = [t for t in self.agenda.tarefas(incluir_concluidas=True) if t.feita][-FEITAS_VISIVEIS:]
        self._preencher(self.lista_tarefas, self._ids_tarefas,
                        [(t.id, f"○  {self.exibir(t.texto)}", TEXTO) for t in pendentes]
                        + [(t.id, f"✓  {self.exibir(t.texto)}", TEXTO_APAGADO) for t in feitas],
                        vazio=self.tr("painel.sem_tarefas"))
        self._preencher(self.lista_lembretes, self._ids_lembretes,
                        [(l.id, f"{l.quando.strftime(self.tr('fmt.lembrete'))}   {self.exibir(l.texto)}", TEXTO)
                         for l in self.agenda.proximos_lembretes()],
                        vazio=self.tr("painel.sem_lembretes"))

    @staticmethod
    def _preencher(lista: tk.Listbox, ids: list[int], itens: list[tuple[int, str, str]], vazio: str) -> None:
        selecionado = ids[lista.curselection()[0]] if lista.curselection() and ids else None
        lista.delete(0, "end")
        ids.clear()
        if not itens:
            lista.insert("end", vazio)
            lista.itemconfigure(0, fg=TEXTO_APAGADO)
            return
        for i, (id_, texto, cor) in enumerate(itens):
            lista.insert("end", texto)
            lista.itemconfigure(i, fg=cor)
            ids.append(id_)
            if id_ == selecionado:
                lista.selection_set(i)

    def _selecionado(self, lista: tk.Listbox, ids: list[int]) -> int | None:
        sel = lista.curselection()
        return ids[sel[0]] if sel and sel[0] < len(ids) else None

    def _alternar_tarefa(self, _evento: object = None) -> None:
        if (id_ := self._selecionado(self.lista_tarefas, self._ids_tarefas)) is not None:
            self.agenda.alternar_tarefa(id_)

    def _remover_tarefa(self, _evento: object = None) -> None:
        if (id_ := self._selecionado(self.lista_tarefas, self._ids_tarefas)) is not None:
            self.agenda.remover_tarefa(id_)

    def _remover_lembrete(self, _evento: object = None) -> None:
        if (id_ := self._selecionado(self.lista_lembretes, self._ids_lembretes)) is not None:
            self.agenda.remover_lembrete(id_)

    def _tique(self) -> None:
        agora = datetime.now()
        self.lbl_hora.configure(text=f"{agora:%H:%M}")
        dia = self.tr.dia_semana(agora)
        self.lbl_data.configure(text=f"{dia[0].upper()}{dia[1:]}, {self.tr.data(agora)}")
        self.after(1000 - agora.microsecond // 1000 + 5, self._tique)  # alinhado à virada do segundo
