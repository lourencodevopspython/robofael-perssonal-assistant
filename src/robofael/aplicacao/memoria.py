"""Memória de longo prazo: responde "o que eu fiz?" a partir do histórico auditável."""

from __future__ import annotations

from dataclasses import dataclass, field

from robofael.dominio.modelos import RegistroAuditoria, TipoEvento
from robofael.dominio.periodos import Periodo
from robofael.i18n import Tradutor
from robofael.portas import ConsultaHistorico

MAX_ITENS_FALADOS = 6


@dataclass
class ResumoPeriodo:
    periodo: Periodo
    concluidas: list[RegistroAuditoria] = field(default_factory=list)
    criadas: list[RegistroAuditoria] = field(default_factory=list)
    lembretes: list[RegistroAuditoria] = field(default_factory=list)

    @property
    def vazio(self) -> bool:
        return not (self.concluidas or self.criadas or self.lembretes)

    def para_dict(self) -> dict:
        """Formato entregue ao modelo de linguagem (ferramenta consultar_historico)."""
        def itens(regs: list[RegistroAuditoria]) -> list[dict]:
            return [{"id": r.entidade_id, "descricao": r.descricao,
                     "quando": r.ocorrido_em.isoformat(timespec="minutes")} for r in regs]
        return {"periodo": self.periodo.descricao, "inicio": self.periodo.inicio.date().isoformat(),
                "fim_exclusivo": self.periodo.fim.date().isoformat(), "tarefas_concluidas": itens(self.concluidas),
                "tarefas_criadas": itens(self.criadas), "lembretes_avisados": itens(self.lembretes)}


class Memoria:
    def __init__(self, historico: ConsultaHistorico, tradutor: Tradutor | None = None):
        self.historico = historico
        self.tr = tradutor or Tradutor()

    def resumo(self, periodo: Periodo) -> ResumoPeriodo:
        eventos = self.historico.eventos(periodo.inicio, periodo.fim)
        resumo = ResumoPeriodo(periodo)
        concluidas: dict[int, RegistroAuditoria] = {}
        for e in eventos:  # cronológico: uma tarefa reaberta depois de concluída não conta
            if e.tipo is TipoEvento.TAREFA_CONCLUIDA:
                concluidas[e.entidade_id] = e
            elif e.tipo is TipoEvento.TAREFA_REABERTA:
                concluidas.pop(e.entidade_id, None)
            elif e.tipo is TipoEvento.TAREFA_CRIADA:
                resumo.criadas.append(e)
            elif e.tipo is TipoEvento.LEMBRETE_AVISADO:
                resumo.lembretes.append(e)
        resumo.concluidas = sorted(concluidas.values(), key=lambda e: e.ocorrido_em)
        return resumo

    def responder(self, periodo: Periodo) -> str:
        tr, r, quando = self.tr, self.resumo(periodo), periodo.descricao
        if not r.concluidas:
            frase = tr("mem.nenhuma", quando=quando)
            if r.criadas:
                frase += tr("mem.mas_criou", n=len(r.criadas), tarefas=tr.plural(len(r.criadas), "un.tarefa"),
                            lista=self._listar(r.criadas))
            return frase
        n = len(r.concluidas)
        frase = tr("mem.concluiu", quando=quando[0].upper() + quando[1:], n=n, tarefas=tr.plural(n, "un.tarefa"),
                   lista=self._listar(r.concluidas))
        extras = []
        if r.criadas:
            extras.append(tr("mem.criou", n=len(r.criadas), tarefas=tr.plural(len(r.criadas), "un.tarefa")))
        if r.lembretes:
            extras.append(tr("mem.recebeu", n=len(r.lembretes), lembretes=tr.plural(len(r.lembretes), "un.lembrete")))
        if extras:
            frase += tr("mem.tambem", extras=tr.juntar(extras))
        return frase

    def _listar(self, registros: list[RegistroAuditoria]) -> str:
        nomes = [r.descricao for r in registros[:MAX_ITENS_FALADOS]]
        resto = len(registros) - len(nomes)
        if resto:
            nomes.append(self.tr("mem.mais", n=resto))
        return self.tr.juntar(nomes)
