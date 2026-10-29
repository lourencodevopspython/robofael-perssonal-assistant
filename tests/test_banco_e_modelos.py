"""Local do banco (mudar com o assistente em uso), backup e os modelos de linguagem disponíveis."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

from robofael import bootstrap
from robofael.adaptadores.claude import CatalogoClaude
from robofael.adaptadores.ollama import CatalogoOllama, OllamaIndisponivel
from robofael.adaptadores.sqlite import BancoSqlite
from robofael.aplicacao import sessao
from robofael.aplicacao.sessao import CerebroEmUso, ModelosDoProvedor
from robofael.apresentacao.configuracoes import texto_modelos
from robofael.configuracao import ARQUIVO_LOCAL_BANCO, Configuracao, ler_local_banco, salvar_local_banco
from robofael.dominio.eventos import Aviso
from robofael.i18n import Tradutor
from robofael.portas import ModeloDisponivel, ProvedorIndisponivel


def _config(tmp_path, **env):
    return Configuracao.do_ambiente({"ROBOFAEL_DADOS": str(tmp_path / "dados"),
                                     "ROBOFAEL_CACHE": str(tmp_path / "c"), **env})


def _tarefas(arquivo):
    con = sqlite3.connect(arquivo)
    try:
        return [r[0] for r in con.execute("SELECT texto FROM tarefas ORDER BY id")]
    finally:
        con.close()


# ---------- Backup ----------
def test_backup_e_um_arquivo_unico_conferido(tmp_path):
    nucleo = bootstrap.montar_nucleo(_config(tmp_path))
    nucleo.agenda.adicionar_tarefa("pagar a luz")
    destino = tmp_path / "pendrive" / "copia.db"
    copia = sessao.fazer_backup(nucleo, destino)
    assert copia.arquivo == destino and copia.registros == 1
    assert _tarefas(destino) == ["pagar a luz"]
    assert not destino.with_name("copia.db-wal").exists()  # sem -wal: copiar só o .db basta
    nucleo.agenda.adicionar_tarefa("outra")
    assert sessao.fazer_backup(nucleo, destino).registros == 2  # substitui a cópia anterior
    copia_aberta = BancoSqlite(destino)
    assert copia_aberta.verificar_integridade().ok  # a cadeia de hashes continua íntegra na cópia
    copia_aberta.fechar()


def test_backup_nao_substitui_o_proprio_banco(tmp_path):
    nucleo = bootstrap.montar_nucleo(_config(tmp_path))
    with pytest.raises(ValueError):
        sessao.fazer_backup(nucleo, nucleo.config.arquivo_banco)
    assert nucleo.banco.vazio() is not None  # continua aberto e usável


# ---------- Mudar o banco de lugar ----------
def test_mudar_o_banco_de_lugar_com_o_assistente_em_uso(tmp_path):
    config = _config(tmp_path)
    nucleo = bootstrap.montar_nucleo(config)
    nucleo.agenda.adicionar_tarefa("antes de mudar")
    antigo = sessao.mover_banco(nucleo, tmp_path / "nuvem")
    novo = (tmp_path / "nuvem" / "memoria.db").resolve()
    assert nucleo.banco.arquivo == novo and nucleo.config.arquivo_banco == novo
    assert antigo.name.startswith("memoria.db.movido-") and antigo.parent == config.pasta_dados
    assert not config.arquivo_banco_padrao.exists()  # o antigo foi guardado com outro nome, não apagado
    assert _tarefas(antigo) == ["antes de mudar"]
    nucleo.agenda.adicionar_tarefa("depois de mudar")  # continua gravando, agora no novo
    assert _tarefas(novo) == ["antes de mudar", "depois de mudar"]

    # A escolha vale nas próximas aberturas
    reaberto = bootstrap.montar_nucleo(_config(tmp_path))
    assert reaberto.banco.arquivo == novo
    assert [t.texto for t in reaberto.agenda.pendentes()] == ["antes de mudar", "depois de mudar"]
    assert reaberto.banco.verificar_integridade().ok


def test_voltar_para_a_pasta_padrao_apaga_o_registro_do_local(tmp_path):
    config = _config(tmp_path)
    nucleo = bootstrap.montar_nucleo(config)
    sessao.mover_banco(nucleo, tmp_path / "outro")
    assert (config.pasta_dados / ARQUIVO_LOCAL_BANCO).exists()
    sessao.mover_banco(nucleo, config.pasta_dados)  # o antigo dali virou .movido-<data>: dá para voltar
    assert not (config.pasta_dados / ARQUIVO_LOCAL_BANCO).exists()
    assert nucleo.config.banco_escolhido is None
    assert nucleo.banco.arquivo == config.arquivo_banco_padrao.resolve()


def test_nao_sobrescreve_um_banco_que_ja_esta_na_pasta(tmp_path):
    nucleo = bootstrap.montar_nucleo(_config(tmp_path))
    nucleo.agenda.adicionar_tarefa("minha")
    pasta = tmp_path / "de-outra-pessoa"
    pasta.mkdir()
    (pasta / "memoria.db").write_bytes(b"dados de outra pessoa")
    with pytest.raises(FileExistsError):
        sessao.mover_banco(nucleo, pasta)
    assert (pasta / "memoria.db").read_bytes() == b"dados de outra pessoa"
    assert nucleo.banco.arquivo == nucleo.config.arquivo_banco_padrao  # nada mudou
    assert [t.texto for t in nucleo.agenda.pendentes()] == ["minha"]


def test_banco_escolhido_ausente_usa_o_padrao_e_avisa(tmp_path):
    config = _config(tmp_path)
    sumido = tmp_path / "pendrive" / "memoria.db"
    salvar_local_banco(config.pasta_dados, sumido)
    nucleo = bootstrap.montar_nucleo(_config(tmp_path))
    assert nucleo.banco.arquivo == config.arquivo_banco_padrao
    assert not sumido.parent.exists()  # não cria um banco vazio no lugar do pendrive
    avisos = []
    nucleo.barramento.assinar(Aviso, avisos.append)
    nucleo.barramento.despachar()
    assert str(sumido) in avisos[0].mensagem
    assert ler_local_banco(config.pasta_dados) == sumido  # a escolha não é esquecida


def test_registro_do_local_do_banco(tmp_path):
    dados = tmp_path / "dados"
    assert ler_local_banco(dados) is None
    salvar_local_banco(dados, tmp_path / "x" / "memoria.db")
    assert json.loads((dados / ARQUIVO_LOCAL_BANCO).read_text()) == {"arquivo": str(tmp_path / "x" / "memoria.db")}
    assert _config(tmp_path).arquivo_banco == tmp_path / "x" / "memoria.db"
    (dados / ARQUIVO_LOCAL_BANCO).write_text("{quebrado")
    assert ler_local_banco(dados) is None  # arquivo inválido: volta ao padrão em vez de travar
    assert _config(tmp_path).arquivo_banco == dados / "memoria.db"


# ---------- Modelos de linguagem ----------
class ClienteOllamaFalso:
    url = "http://localhost:11434"

    def __init__(self, modelos=None, fora=False):
        self._modelos, self._fora = modelos or {}, fora

    def modelos(self):
        if self._fora:
            raise OllamaIndisponivel("recusou")
        return list(self._modelos)

    def informacoes(self, nome):
        if self._modelos[nome] is None:
            raise RuntimeError("modelo corrompido")
        capacidades, tamanho = self._modelos[nome]
        return {"capabilities": capacidades, "details": {"parameter_size": tamanho}}


def test_catalogo_ollama_so_mostra_modelos_com_ferramentas():
    cliente = ClienteOllamaFalso({"llama3.2:3b": (["completion", "tools"], "3.2B"),
                                  "gemma:2b": (["completion"], "2B"),  # sem ferramentas: não serve
                                  "nomic-embed-text": (["embedding"], "137M"),
                                  "quebrado": None})
    assert CatalogoOllama(cliente).modelos() == [ModeloDisponivel("llama3.2:3b", "3.2B")]
    with pytest.raises(ProvedorIndisponivel) as erro:
        CatalogoOllama(ClienteOllamaFalso(fora=True)).modelos()
    assert erro.value.chave == "modelos.ollama_fora" and erro.value.campos == {"url": "http://localhost:11434"}


def test_catalogo_claude():
    lista = [SimpleNamespace(id="claude-opus-5-5", display_name="Claude Opus 5.5"),
             SimpleNamespace(id="claude-haiku-5-5", display_name="Claude Haiku 5.5")]
    cliente = SimpleNamespace(models=SimpleNamespace(list=lambda limit: iter(lista)))
    assert CatalogoClaude(lambda _t: cliente).modelos() == [ModeloDisponivel("claude-opus-5-5", "Claude Opus 5.5"),
                                                          ModeloDisponivel("claude-haiku-5-5", "Claude Haiku 5.5")]

    def sem_chave(_t):
        raise TypeError("Could not resolve authentication method")

    with pytest.raises(ProvedorIndisponivel) as erro:
        CatalogoClaude(sem_chave).modelos()
    assert erro.value.chave == "modelos.claude_sem_chave"


def test_catalogo_claude_sem_conexao():
    import anthropic
    import httpx2 as httpx

    def listar(limit):
        raise anthropic.APIConnectionError(request=httpx.Request("GET", "https://api.anthropic.com/v1/models"))

    cliente = SimpleNamespace(models=SimpleNamespace(list=listar))
    with pytest.raises(ProvedorIndisponivel) as erro:
        CatalogoClaude(lambda _t: cliente).modelos()
    assert erro.value.chave == "modelos.claude_sem_conexao"


def test_listar_modelos_de_todos_os_provedores(tmp_path):
    class Defeituoso:
        provedor = "claude"

        def modelos(self):
            raise KeyError("resposta inesperada")

    nucleo = bootstrap.montar_nucleo(_config(tmp_path))
    nucleo.catalogos = (Defeituoso(), CatalogoOllama(ClienteOllamaFalso({"llama3.2:3b": (["completion", "tools"],
                                                                                          "3.2B")})))
    claude, ollama = sessao.listar_modelos(nucleo)
    assert (claude.provedor, claude.modelos, claude.erro.chave) == ("claude", [], "modelos.erro")
    assert ollama == ModelosDoProvedor("ollama", [ModeloDisponivel("llama3.2:3b", "3.2B")])
    nucleo.catalogos = ()
    assert sessao.listar_modelos(nucleo) == []


def test_cerebro_em_uso():
    assert sessao.cerebro_em_uso(None) is None  # serviços ainda iniciando
    modelo = SimpleNamespace(provedor="ollama", modelo="llama3.2:3b")
    servicos = SimpleNamespace(orquestrador=SimpleNamespace(modelo=modelo))
    assert sessao.cerebro_em_uso(servicos) == CerebroEmUso("ollama", "llama3.2:3b")
    from robofael.adaptadores.offline import ModeloOffline

    servicos.orquestrador.modelo = ModeloOffline(None)
    assert sessao.cerebro_em_uso(servicos) == CerebroEmUso("offline", None)


def test_texto_dos_modelos_na_tela():
    tr = Tradutor()
    resultados = [ModelosDoProvedor("claude", [], ProvedorIndisponivel("modelos.claude_sem_chave")),
                  ModelosDoProvedor("ollama", [ModeloDisponivel("llama3.2:3b", "3.2B"),
                                               ModeloDisponivel("llama3.1:latest", "8.0B")]),
                  ModelosDoProvedor("ollama", [])]
    assert texto_modelos(resultados, CerebroEmUso("ollama", "llama3.2:3b"), tr).splitlines() == [
        "• Claude (nuvem): sem chave: defina ANTHROPIC_API_KEY",
        "• Ollama (local): llama3.2:3b (3.2B, em uso), llama3.1:latest (8.0B)",
        "• Ollama (local): nenhum compatível instalado",
    ]
    assert texto_modelos([], None, tr) == "—"
