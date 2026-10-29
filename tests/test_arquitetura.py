"""Testes de arquitetura: as regras de dependência e de SOLID verificadas automaticamente.

Se alguém fizer o domínio importar um adaptador, ou a interface montar um adaptador por
conta própria, o teste falha e aponta o arquivo — a arquitetura não se degrada em silêncio."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import robofael
from robofael import portas
from robofael.adaptadores.ferramentas import FERRAMENTAS, ExecutorFerramentas
from robofael.adaptadores.offline import ModeloOffline
from robofael.adaptadores.repositorio_json import RepositorioJson
from robofael.adaptadores.sqlite import BancoSqlite
from robofael.dominio.agenda import Agenda
from robofael.dominio.modelos import DadosAgenda

RAIZ = Path(robofael.__file__).parent

# Regra de dependência: cada camada só pode importar as camadas listadas (além de si mesma).
# i18n e configuracao são transversais (textos e parâmetros), sem dependências de infraestrutura.
PERMITIDAS = {
    "dominio": {"i18n"},
    "portas": {"dominio"},
    "aplicacao": {"dominio", "portas", "i18n", "configuracao"},
    "adaptadores": {"dominio", "portas", "aplicacao", "audio", "i18n"},
    "audio": {"configuracao", "i18n"},
    "avatar": {"configuracao"},
    "i18n": set(),
    "configuracao": {"i18n"},
    "apresentacao": {"dominio", "portas", "aplicacao", "audio", "avatar", "bootstrap", "configuracao", "i18n"},
    # Raízes de composição: as únicas que conhecem as implementações concretas
    "bootstrap": {"dominio", "portas", "aplicacao", "adaptadores", "audio", "configuracao", "i18n"},
    "__main__": {"apresentacao"},
}


def _camada(modulo: str) -> str:
    partes = modulo.split(".")
    return partes[1] if len(partes) > 1 else "__init__"


def _importacoes() -> list[tuple[str, str, int]]:
    """(arquivo, módulo importado, linha) de todo import interno do pacote."""
    encontradas = []
    for arquivo in RAIZ.rglob("*.py"):
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if isinstance(no, ast.ImportFrom) and no.module and no.module.startswith("robofael."):
                encontradas.append((arquivo, no.module, no.lineno))
            elif isinstance(no, ast.Import):
                encontradas += [(arquivo, a.name, no.lineno) for a in no.names if a.name.startswith("robofael.")]
    return encontradas


def _camada_do_arquivo(arquivo: Path) -> str:
    relativo = arquivo.relative_to(RAIZ).with_suffix("")
    return relativo.parts[0]


def test_toda_camada_tem_regra():
    camadas = {_camada_do_arquivo(a) for a in RAIZ.rglob("*.py")} - {"__init__"}
    assert camadas <= set(PERMITIDAS), f"camadas sem regra de dependência: {camadas - set(PERMITIDAS)}"


def test_regra_de_dependencia_entre_camadas():
    violacoes = []
    for arquivo, modulo, linha in _importacoes():
        origem, destino = _camada_do_arquivo(arquivo), _camada(modulo)
        if origem != destino and origem in PERMITIDAS and destino not in PERMITIDAS[origem]:
            violacoes.append(f"{arquivo.relative_to(RAIZ)}:{linha} ({origem} -> {destino})")
    assert not violacoes, "dependências proibidas:\n" + "\n".join(violacoes)


@pytest.mark.parametrize("pacote", ["dominio", "portas"])
def test_nucleo_nao_depende_de_bibliotecas_de_infraestrutura(pacote):
    """Domínio e portas são Python puro: nada de banco, áudio, rede ou interface gráfica."""
    proibidas = {"sqlite3", "tkinter", "PIL", "numpy", "pygame", "anthropic", "speech_recognition", "vosk",
                 "edge_tts", "gtts", "pyaudio", "subprocess"}
    arquivos = list((RAIZ / pacote).rglob("*.py")) if (RAIZ / pacote).is_dir() else [RAIZ / f"{pacote}.py"]
    usadas = set()
    for arquivo in arquivos:
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if isinstance(no, ast.Import):
                usadas |= {a.name.split(".")[0] for a in no.names}
            elif isinstance(no, ast.ImportFrom) and no.module and no.level == 0:
                usadas.add(no.module.split(".")[0])
    assert not usadas & proibidas


# ---------- Inversão de dependência e substituição de Liskov ----------
def _metodos_publicos(protocolo) -> set[str]:
    return {n for n, v in vars(protocolo).items() if callable(v) and not n.startswith("_")}


@pytest.mark.parametrize("protocolo", [portas.RepositorioAgenda, portas.ConsultaHistorico,
                                       portas.RepositorioPreferencias, portas.PersistenciaAssistente])
def test_banco_sqlite_cumpre_os_contratos_de_persistencia(protocolo):
    faltando = {m for c in protocolo.__mro__ if c is not object for m in _metodos_publicos(c)} - set(dir(BancoSqlite))
    assert not faltando


def test_repositorio_json_nao_finge_ser_repositorio_da_agenda():
    """O JSON não guarda o histórico: não pode ter a assinatura que promete guardá-lo (LSP)."""
    assert "eventos" not in inspect.signature(RepositorioJson.salvar).parameters
    assert "eventos" in inspect.signature(portas.RepositorioAgenda.salvar).parameters


def test_agenda_aceita_qualquer_repositorio_que_cumpra_o_contrato():
    """A regra de negócio funciona com um repositório em memória, sem banco (DIP)."""

    class EmMemoria:
        def __init__(self):
            self.salvos = []

        def carregar(self):
            return DadosAgenda()

        def salvar(self, dados, eventos=()):
            self.salvos.append((dados, list(eventos)))

    repo = EmMemoria()
    Agenda(repo).adicionar_tarefa("testar a arquitetura")
    assert len(repo.salvos) == 1 and repo.salvos[0][1][0].descricao == "testar a arquitetura"


# ---------- Aberto/fechado ----------
def test_cada_ferramenta_declarada_tem_uma_acao_e_vice_versa(agenda):
    declaradas = {f["name"] for f in FERRAMENTAS}
    assert declaradas == set(ExecutorFerramentas(agenda)._acoes)


def test_modelo_offline_aceita_intencoes_novas_sem_alterar_o_codigo(agenda):
    """Estender = acrescentar uma intenção à cadeia; nenhuma linha existente muda."""
    modelo = ModeloOffline(agenda)
    modelo.intencoes = (lambda fala, agora: "pong" if fala == "ping" else None, *modelo.intencoes)
    assert modelo.interpretar("ping") == "pong"
    assert modelo.interpretar("que horas são") != "pong"  # as demais continuam valendo


# ---------- Responsabilidade única ----------
def test_orquestrador_delega_pipeline_e_escuta_passiva():
    """O orquestrador coordena; quem transforma texto em fala e quem vigia o microfone são outros."""
    from robofael.aplicacao.orquestrador import Orquestrador
    from robofael.aplicacao.pipeline import PipelineFala
    from robofael.aplicacao.vigia import VigiaAtivacao

    proprios = set(vars(Orquestrador))
    assert not proprios & {"_pensar", "_sintetizar", "_tocar", "_vigiar", "_reservar_microfone"}
    assert {"_pensar", "_sintetizar", "_tocar"} <= set(vars(PipelineFala))
    assert {"_vigiar", "_reservar_microfone"} <= set(vars(VigiaAtivacao))


def test_raiz_de_composicao_nao_contem_regras_do_produto():
    """bootstrap.py só monta e conecta; políticas (voz, idioma, saudação) ficam em aplicacao/sessao.py."""
    from robofael import bootstrap

    for politica in ("voz_inicial", "ativacao_inicial", "saudacao", "aplicar_idioma", "voz_para_idioma"):
        definida_em = getattr(bootstrap, politica, None)
        assert definida_em is None or definida_em.__module__ == "robofael.aplicacao.sessao"


# ---------- Nome técnico ----------
def test_nome_antigo_so_aparece_na_compatibilidade_de_variaveis():
    """Desde a 3.5.0 o pacote é `robofael`; `eurobo` só sobrevive como alternativa às variáveis EUROBO_*."""
    com_nome_antigo = {a.relative_to(RAIZ).as_posix() for a in RAIZ.rglob("*.py")
                       if "eurobo" in a.read_text(encoding="utf-8").lower()}
    assert com_nome_antigo == {"configuracao.py"}
