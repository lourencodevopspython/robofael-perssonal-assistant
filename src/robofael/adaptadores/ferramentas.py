"""Ferramentas (tool use) que o modelo usa para operar a agenda: schemas, validação e execução.

As entradas chegam por streaming (`eager_input_streaming`), então a API não as valida:
a validação contra o schema acontece aqui, antes de qualquer execução."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from robofael.aplicacao.memoria import Memoria
from robofael.aplicacao.programas import ServicoProgramas
from robofael.dominio.agenda import Agenda
from robofael.dominio.periodos import Periodo


def _ferramenta(nome: str, descricao: str, propriedades: dict, obrigatorias: list[str]) -> dict:
    return {
        "name": nome,
        "description": descricao,
        "eager_input_streaming": True,
        "input_schema": {
            "type": "object",
            "properties": propriedades,
            "required": obrigatorias,
            "additionalProperties": False,
        },
    }


FERRAMENTAS: list[dict] = [
    _ferramenta("adicionar_tarefa", "Adiciona uma tarefa à lista do dia.",
                {"texto": {"type": "string", "description": "Descrição da tarefa"}}, ["texto"]),
    _ferramenta("listar_tarefas", "Lista as tarefas. Use incluir_concluidas=false para só as pendentes.",
                {"incluir_concluidas": {"type": "boolean"}}, ["incluir_concluidas"]),
    _ferramenta("concluir_tarefa", "Marca uma tarefa como concluída pelo id (use listar_tarefas para achar o id).",
                {"id": {"type": "integer"}}, ["id"]),
    _ferramenta("remover_tarefa", "Apaga uma tarefa pelo id.", {"id": {"type": "integer"}}, ["id"]),
    _ferramenta("criar_lembrete", "Agenda um lembrete falado para uma data/hora local.",
                {"texto": {"type": "string"},
                 "quando": {"type": "string", "description": "Formato YYYY-MM-DDTHH:MM (hora local)"}},
                ["texto", "quando"]),
    _ferramenta("listar_lembretes", "Lista os lembretes futuros ainda não avisados.", {}, []),
    _ferramenta("consultar_historico",
                "Consulta a memória de longo prazo: tarefas concluídas, tarefas criadas e lembretes avisados "
                "entre duas datas (inclusive). Use para perguntas como 'o que eu fiz ontem/na semana passada/"
                "no dia 20'. Converta a expressão do usuário em datas usando a data atual da mensagem.",
                {"inicio": {"type": "string", "description": "Data inicial YYYY-MM-DD"},
                 "fim": {"type": "string", "description": "Data final YYYY-MM-DD (inclusive)"}},
                ["inicio", "fim"]),
    _ferramenta("abrir_programa",
                "Abre um programa instalado no computador do usuário pelo nome (ex.: 'navegador', 'calculadora', "
                "'firefox', 'configurações'). Se houver mais de uma opção, pergunte qual ele quer.",
                {"nome": {"type": "string", "description": "Nome do programa como o usuário disse"}}, ["nome"]),
    _ferramenta("listar_programas", "Lista os programas instalados, opcionalmente filtrando pelo nome.",
                {"filtro": {"type": "string", "description": "Parte do nome; vazio lista todos"}}, ["filtro"]),
]
_SCHEMAS = {f["name"]: f["input_schema"] for f in FERRAMENTAS}
_TIPOS = {"string": str, "integer": int, "boolean": bool}


class EntradaInvalida(ValueError):
    pass


def validar_entrada(nome: str, entrada: Any) -> dict:
    """Confere tipo, campos obrigatórios e campos extras; devolve a entrada ou levanta EntradaInvalida."""
    schema = _SCHEMAS.get(nome)
    if schema is None:
        raise EntradaInvalida(f"Ferramenta desconhecida: {nome}")
    if not isinstance(entrada, dict):
        raise EntradaInvalida("A entrada deve ser um objeto JSON")
    faltando = [c for c in schema["required"] if c not in entrada]
    extras = [c for c in entrada if c not in schema["properties"]]
    if faltando or extras:
        raise EntradaInvalida(f"Campos faltando: {faltando}; campos inesperados: {extras}")
    for campo, valor in entrada.items():
        tipo = _TIPOS[schema["properties"][campo]["type"]]
        # bool é subclasse de int em Python: não aceitar True como id
        if not isinstance(valor, tipo) or (tipo is int and isinstance(valor, bool)):
            raise EntradaInvalida(f"Campo '{campo}' deve ser {schema['properties'][campo]['type']}")
    return entrada


class ExecutorFerramentas:
    """Executa uma ferramenta pelo nome. Aberto para extensão: uma ferramenta nova é um schema
    em FERRAMENTAS mais um método registrado em `_acoes`, sem mexer no despacho."""

    def __init__(self, agenda: Agenda, memoria: Memoria | None = None, programas: ServicoProgramas | None = None):
        self.agenda = agenda
        self.memoria = memoria
        self.programas = programas
        self._acoes: dict[str, Callable[[dict], dict]] = {
            "adicionar_tarefa": self._adicionar_tarefa,
            "listar_tarefas": self._listar_tarefas,
            "concluir_tarefa": self._concluir_tarefa,
            "remover_tarefa": self._remover_tarefa,
            "criar_lembrete": self._criar_lembrete,
            "listar_lembretes": self._listar_lembretes,
            "consultar_historico": self._consultar_historico,
            "abrir_programa": self._abrir_programa,
            "listar_programas": self._listar_programas,
        }

    def executar(self, nome: str, entrada: Any) -> dict:
        return self._acoes[nome](validar_entrada(nome, entrada))

    # ---------- Agenda ----------
    def _adicionar_tarefa(self, e: dict) -> dict:
        return {"ok": True, "tarefa": self.agenda.adicionar_tarefa(e["texto"]).para_dict()}

    def _listar_tarefas(self, e: dict) -> dict:
        tarefas = self.agenda.tarefas(e["incluir_concluidas"])
        return {"tarefas": [t.para_dict() for t in tarefas], "pendentes": len(self.agenda.pendentes())}

    def _concluir_tarefa(self, e: dict) -> dict:
        return {"ok": True, "tarefa": self.agenda.concluir_tarefa(e["id"]).para_dict()}

    def _remover_tarefa(self, e: dict) -> dict:
        self.agenda.remover_tarefa(e["id"])
        return {"ok": True}

    def _criar_lembrete(self, e: dict) -> dict:
        return {"ok": True, "lembrete": self.agenda.criar_lembrete(e["texto"], e["quando"]).para_dict()}

    def _listar_lembretes(self, _e: dict) -> dict:
        return {"lembretes": [l.para_dict() for l in self.agenda.proximos_lembretes()]}

    # ---------- Memória de longo prazo ----------
    def _consultar_historico(self, e: dict) -> dict:
        if self.memoria is None:
            raise ValueError("Histórico indisponível")
        inicio, fim = date.fromisoformat(e["inicio"]), date.fromisoformat(e["fim"])
        if fim < inicio:
            raise ValueError("A data final é anterior à inicial")
        return self.memoria.resumo(Periodo.dias(inicio, fim, f"de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}")).para_dict()

    # ---------- Programas ----------
    def _servico_programas(self) -> ServicoProgramas:
        if self.programas is None:
            raise ValueError("Abertura de programas indisponível")
        return self.programas

    def _abrir_programa(self, e: dict) -> dict:
        return self._servico_programas().abrir(e["nome"])

    def _listar_programas(self, e: dict) -> dict:
        return self._servico_programas().listar(e["filtro"])
