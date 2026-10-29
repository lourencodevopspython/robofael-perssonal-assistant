import json

from conftest import AGORA
from robofael.adaptadores.repositorio_json import RepositorioJson
from robofael.dominio.modelos import DadosAgenda, Tarefa


def test_arquivo_inexistente_comeca_vazio(tmp_path):
    assert RepositorioJson(tmp_path / "x.json").carregar() == DadosAgenda()


def test_salva_e_carrega_com_versao(tmp_path):
    repo = RepositorioJson(tmp_path / "sub" / "agenda.json")
    dados = DadosAgenda([Tarefa(1, "Persistir", AGORA)], [], 2)
    repo.salvar(dados)
    assert json.loads(repo.arquivo.read_text())["versao"] == 2
    assert repo.carregar() == dados


def test_escrita_atomica_nao_deixa_temporarios(tmp_path):
    repo = RepositorioJson(tmp_path / "agenda.json")
    for i in range(5):
        repo.salvar(DadosAgenda([Tarefa(i + 1, f"t{i}", AGORA)], [], i + 2))
    assert [p.name for p in tmp_path.iterdir()] == ["agenda.json"]


def test_arquivo_corrompido_e_preservado_ao_lado(tmp_path):
    arquivo = tmp_path / "agenda.json"
    arquivo.write_text("{ quebrado")
    assert RepositorioJson(arquivo).carregar() == DadosAgenda()
    copias = list(tmp_path.glob("agenda.corrompido-*.json"))
    assert len(copias) == 1 and copias[0].read_text() == "{ quebrado"
    assert not arquivo.exists()
