import pytest

from robofael.adaptadores.ferramentas import FERRAMENTAS, EntradaInvalida, ExecutorFerramentas, validar_entrada


def test_todas_as_ferramentas_usam_streaming_de_entrada_e_schema_fechado():
    assert {f["name"] for f in FERRAMENTAS} == {
        "adicionar_tarefa", "listar_tarefas", "concluir_tarefa", "remover_tarefa", "criar_lembrete",
        "listar_lembretes", "consultar_historico", "abrir_programa", "listar_programas", "concluir_todas_tarefas"}
    for f in FERRAMENTAS:
        assert f["eager_input_streaming"] is True
        assert f["input_schema"]["additionalProperties"] is False
        assert set(f["input_schema"]["required"]) <= set(f["input_schema"]["properties"])


@pytest.mark.parametrize("nome, entrada, erro", [
    ("voar", {}, "desconhecida"),
    ("adicionar_tarefa", "texto solto", "objeto"),
    ("adicionar_tarefa", {}, "faltando"),
    ("adicionar_tarefa", {"texto": "x", "extra": 1}, "inesperados"),
    ("concluir_tarefa", {"id": "3"}, "integer"),
    ("concluir_tarefa", {"id": True}, "integer"),  # bool não é id
    ("listar_tarefas", {"incluir_concluidas": "sim"}, "boolean"),
])
def test_entradas_invalidas_sao_barradas(nome, entrada, erro):
    with pytest.raises(EntradaInvalida, match=erro):
        validar_entrada(nome, entrada)


def test_executa_fluxo_completo_na_agenda(agenda):
    ex = ExecutorFerramentas(agenda)
    t = ex.executar("adicionar_tarefa", {"texto": "Revisar PR"})["tarefa"]
    assert t == {"id": 1, "texto": "Revisar PR", "criada": "2026-10-21T16:25", "feita": False, "concluida_em": None}
    assert ex.executar("listar_tarefas", {"incluir_concluidas": False})["pendentes"] == 1
    ex.executar("concluir_tarefa", {"id": 1})
    assert ex.executar("listar_tarefas", {"incluir_concluidas": False}) == {"tarefas": [], "pendentes": 0}
    ex.executar("criar_lembrete", {"texto": "daily", "quando": "2026-10-22T09:00"})
    assert ex.executar("listar_lembretes", {})["lembretes"][0]["quando"] == "2026-10-22T09:00"
    assert ex.executar("remover_tarefa", {"id": 1}) == {"ok": True}
