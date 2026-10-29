"""Programas instalados: leitura de .desktop, escolha pelo nome falado e abertura segura."""

import subprocess
from pathlib import Path

import pytest

from conftest import Relogio, RepositorioMemoria
from robofael.adaptadores.ferramentas import ExecutorFerramentas
from robofael.adaptadores.offline import ModeloOffline
from robofael.adaptadores.programas_linux import LancadorLinux, diretorios_padrao, ler_desktop
from robofael.aplicacao.programas import ServicoProgramas
from robofael.dominio.agenda import Agenda
from robofael.dominio.programas import escolher, extrair_pedido, ranquear
from robofael.portas import Programa


def desktop(pasta: Path, nome_arquivo: str, conteudo: str) -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / nome_arquivo
    arquivo.write_text("[Desktop Entry]\nType=Application\n" + conteudo.strip() + "\n", encoding="utf-8")
    return arquivo


@pytest.fixture
def pastas(tmp_path):
    usuario, sistema = tmp_path / "usuario" / "applications", tmp_path / "sistema" / "applications"
    desktop(sistema, "firefox.desktop", """
Name=Firefox Web Browser
Name[pt_BR]=Navegador Firefox
GenericName[pt_BR]=Navegador web
Keywords[pt_BR]=internet;web;navegador;
Exec=firefox %u
[Desktop Action new-window]
Name=Open a New Window
Exec=firefox --new-window
""")
    desktop(sistema, "org.gnome.Calculator.desktop", "Name=Calculator\nExec=gnome-calculator\nKeywords=calc;math;")
    desktop(sistema, "org.gnome.Settings.desktop", "Name=Settings\nExec=gnome-control-center")
    desktop(sistema, "code.desktop", "Name=Visual Studio Code\nExec=/usr/share/code/code --unity-launch %F")
    desktop(sistema, "escondido.desktop", "Name=Escondido\nExec=x\nNoDisplay=true")
    desktop(sistema, "oculto.desktop", "Name=Oculto\nExec=x\nHidden=true")
    desktop(sistema, "link.desktop", "Name=Link\nExec=x").write_text("[Desktop Entry]\nType=Link\nName=Link\nURL=x\n")
    desktop(sistema, "sem-binario.desktop", "Name=Fantasma\nExec=fantasma\nTryExec=programa-que-nao-existe-123")
    desktop(sistema, "quebrado.desktop", "").write_text("isto não é um desktop válido\n[[[")
    desktop(sistema / "kde", "dolphin.desktop", "Name=Dolphin\nGenericName=File Manager\nExec=dolphin %u")
    # A mesma entrada na pasta do usuário tem prioridade sobre a do sistema
    desktop(usuario, "org.gnome.Calculator.desktop", "Name=Calculadora Personalizada\nExec=gnome-calculator --x")
    return [usuario, sistema]


@pytest.fixture
def executados():
    return []


@pytest.fixture
def lancador(pastas, executados):
    return LancadorLinux(pastas, executar=lambda args, **kw: executados.append((args, kw)), gtk_launch="")


def nomes(programas):
    return [p.nome for p in programas]


def test_le_apenas_aplicativos_visiveis_e_prioriza_o_usuario(lancador):
    assert nomes(lancador.programas()) == [
        "Calculadora Personalizada", "Dolphin", "Navegador Firefox", "Settings", "Visual Studio Code"]
    firefox = next(p for p in lancador.programas() if p.id == "firefox")
    assert firefox.descricao == "Navegador web" and "navegador" in firefox.palavras_chave
    assert firefox.comando == "firefox %u"  # a "Desktop Action" não sobrescreve a entrada principal
    assert any(p.id == "kde-dolphin" for p in lancador.programas())  # subpastas viram prefixo do id


def test_entrada_invalida_e_ignorada(tmp_path):
    arquivo = desktop(tmp_path, "x.desktop", "Name=Sem exec")
    assert ler_desktop(arquivo, tmp_path) is None


def test_diretorios_seguem_o_padrao_xdg(tmp_path):
    pastas = diretorios_padrao({"XDG_DATA_HOME": str(tmp_path / "casa"), "XDG_DATA_DIRS": "/a:/b"})
    assert pastas[:3] == [tmp_path / "casa" / "applications", Path("/a/applications"), Path("/b/applications")]
    assert Path("/var/lib/snapd/desktop/applications") in pastas


@pytest.mark.parametrize("fala, pedido", [
    ("abre o firefox", "firefox"), ("pode abrir o navegador pra mim?", "navegador"),
    ("abrir a calculadora por favor", "calculadora"), ("inicia o programa do vs code", "vs code"),
    ("Abra as configurações", "configuracoes"), ("executar o dolphin", "dolphin"),
    ("que horas são", None), ("anota tarefa abrir conta no banco", "conta no banco"),
])
def test_extrai_o_nome_do_programa_da_fala(fala, pedido):
    assert extrair_pedido(fala) == pedido


@pytest.mark.parametrize("pedido, esperado", [
    ("firefox", "Navegador Firefox"),
    ("navegador", "Navegador Firefox"),  # nome genérico / palavra-chave
    ("calculadora", "Calculadora Personalizada"),
    ("configurações", "Settings"),  # sinônimo: o .desktop só tem o nome em inglês
    ("vs code", "Visual Studio Code"),
    ("code", "Visual Studio Code"),  # nome do executável
    ("visual studio", "Visual Studio Code"),
    ("gerenciador de arquivos", None),  # "Files" não existe aqui (o Dolphin é "File Manager")
    ("photoshop", None),
])
def test_escolhe_o_programa_certo(lancador, pedido, esperado):
    escolha = escolher(ranquear(pedido, lancador.programas()))
    assert (escolha.nome if isinstance(escolha, Programa) else escolha) == esperado


def test_ambiguidade_devolve_as_opcoes():
    programas = [Programa("a", "Editor de Texto", "gedit"), Programa("b", "Editor de Imagens", "gimp")]
    assert nomes(escolher(ranquear("editor", programas))) == ["Editor de Imagens", "Editor de Texto"]


def test_abre_sem_shell_e_sem_codigos_de_campo(lancador, executados):
    code = next(p for p in lancador.programas() if p.nome == "Visual Studio Code")
    lancador.abrir(code)
    args, kw = executados[0]
    assert args == ["/usr/share/code/code", "--unity-launch"]
    assert kw["start_new_session"] and kw["stdout"] is subprocess.DEVNULL and "shell" not in kw


def test_com_gtk_launch_usa_o_id_da_entrada(pastas, executados):
    l = LancadorLinux(pastas, executar=lambda args, **kw: executados.append(args), gtk_launch="/usr/bin/gtk-launch")
    l.abrir(next(p for p in l.programas() if p.id == "firefox"))
    assert executados == [["/usr/bin/gtk-launch", "firefox"]]


def test_lista_fica_em_cache(lancador, pastas):
    lancador.programas()
    desktop(pastas[1], "novo.desktop", "Name=Novo\nExec=novo")
    assert "Novo" not in nomes(lancador.programas())  # dentro do tempo de cache


# ---------- Caso de uso e integração com o assistente ----------
def test_servico_abre_desambigua_e_avisa(lancador, executados):
    s = ServicoProgramas(lancador)
    assert s.abrir("calculadora") == {"ok": True, "programa": "Calculadora Personalizada",
                                      "frase": "Abrindo Calculadora Personalizada."}
    assert s.abrir("photoshop")["frase"] == "Não encontrei nenhum programa chamado photoshop instalado."
    assert len(executados) == 1
    assert s.listar("firefox") == {"total": 1, "programas": ["Navegador Firefox"]}
    assert s.listar()["total"] == 5


def test_navegador_usa_o_padrao_do_sistema(lancador, executados):
    padrao = Programa("chrome", "Google Chrome", "chrome")
    lancador.navegador_padrao = lambda: padrao
    assert ServicoProgramas(lancador).abrir("navegador")["frase"] == "Abrindo Google Chrome."


def test_falha_ao_abrir_vira_frase(lancador):
    def explodir(*a, **k):
        raise FileNotFoundError("x")

    lancador._executar = explodir
    assert ServicoProgramas(lancador).abrir("firefox")["frase"] == "Não consegui abrir o Navegador Firefox."


def test_modo_offline_abre_programas(lancador, executados):
    relogio = Relogio()
    modelo = ModeloOffline(Agenda(RepositorioMemoria(), relogio), relogio, programas=ServicoProgramas(lancador))
    assert "".join(modelo.responder("abre o firefox pra mim")) == "Abrindo Navegador Firefox."
    # Comandos de agenda têm prioridade: aqui "abrir" faz parte da tarefa
    assert "".join(modelo.responder("anota tarefa abrir conta no banco")) == "Anotei: abrir conta no banco."
    assert "".join(modelo.responder("me lembra daqui a 5 minutos de abrir o forno")) == (
        "Combinado, te lembro daqui a 5 minutos.")
    assert executados == [executados[0]]  # só o firefox foi aberto


def test_ferramentas_do_claude_para_programas(lancador, executados, agenda):
    ex = ExecutorFerramentas(agenda, programas=ServicoProgramas(lancador))
    assert ex.executar("abrir_programa", {"nome": "configurações"})["programa"] == "Settings"
    assert ex.executar("listar_programas", {"filtro": ""})["total"] == 5
    with pytest.raises(ValueError, match="indisponível"):
        ExecutorFerramentas(agenda).executar("abrir_programa", {"nome": "x"})
