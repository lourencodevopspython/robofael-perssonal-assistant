"""Suporte ao Windows: microfones, inicialização, programas, pastas do executável e a verificação do pacote.

Rodam em qualquer sistema com dublês; os marcados com `so_windows` usam o registro de verdade e só rodam
no Windows (no CI, o job que gera o executável)."""

import sys
from pathlib import Path

import pytest

from robofael import bootstrap, configuracao
from robofael.adaptadores import microfone as mod_microfone
from robofael.adaptadores.dispositivos_windows import DispositivosWindows, indice_microfone
from robofael.adaptadores.inicializacao_windows import InicializacaoWindows, RegistroWindows
from robofael.adaptadores.programas_windows import LancadorWindows
from robofael.aplicacao.programas import ServicoProgramas
from robofael.configuracao import Configuracao
from robofael.portas import Microfone

so_windows = pytest.mark.skipif(sys.platform != "win32", reason="usa o registro do Windows")


# ---------- Microfones ----------
class PyAudioFalso:
    APIS = [{"type": 2}, {"type": 13}]  # MME, WASAPI
    DISPOSITIVOS = [
        {"name": "Microsoft Sound Mapper - Input", "maxInputChannels": 2, "hostApi": 0},
        {"name": "Microfone (Realtek Audio)", "maxInputChannels": 2, "hostApi": 0},
        {"name": "Alto-falantes (Realtek Audio)", "maxInputChannels": 0, "hostApi": 0},
        {"name": "Headset USB", "maxInputChannels": 1, "hostApi": 0},
        {"name": "Microfone (Realtek Audio)", "maxInputChannels": 2, "hostApi": 1},  # o mesmo, pela WASAPI
    ]

    def __init__(self):
        self.encerrado = False

    def get_host_api_count(self):
        return len(self.APIS)

    def get_host_api_info_by_index(self, i):
        return self.APIS[i]

    def get_device_count(self):
        return len(self.DISPOSITIVOS)

    def get_device_info_by_index(self, i):
        return self.DISPOSITIVOS[i]

    def terminate(self):
        self.encerrado = True


def test_microfones_do_windows_sem_saidas_mapeador_nem_repetidos():
    assert DispositivosWindows(PyAudioFalso).microfones() == [
        Microfone("Microfone (Realtek Audio)", "Microfone (Realtek Audio)"), Microfone("Headset USB", "Headset USB")]

    def quebrado():
        raise OSError("sem PortAudio")

    assert DispositivosWindows(quebrado).microfones() == []


def test_microfone_escolhido_e_aberto_pelo_indice_so_no_windows():
    assert indice_microfone("Headset USB", PyAudioFalso, "win32") == 3
    assert indice_microfone("Desconectado", PyAudioFalso, "win32") is None  # abre o padrão
    assert indice_microfone(None, PyAudioFalso, "win32") is None
    assert indice_microfone("Headset USB", PyAudioFalso, "linux") is None  # Linux: pelo servidor de áudio


def test_reconhecedor_abre_o_microfone_do_indice(monkeypatch):
    abertos = []

    class MicFalso:
        def __init__(self, device_index=None, **_kw):
            self.indice = device_index

        def __enter__(self):
            abertos.append(self.indice)
            return self

        def __exit__(self, *_a):
            pass

    monkeypatch.setattr(mod_microfone.sr, "Microphone", MicFalso)
    monkeypatch.setattr(mod_microfone, "indice_microfone", lambda escolhido: {"Headset USB": 3}.get(escolhido))
    mic = mod_microfone.MicrofoneGoogle.__new__(mod_microfone.MicrofoneGoogle)  # sem abrir o hardware
    mic._mic, mic._escolhido = MicFalso(), lambda: "Headset USB"
    with mic._aberto() as fonte:
        assert fonte.indice == 3
    mic._escolhido = lambda: None
    with mic._aberto() as fonte:
        assert fonte is mic._mic
    assert abertos == [3, None]


# ---------- Inicialização ----------
class RegistroFalso:
    def __init__(self):
        self.valores = {}

    def ler(self, nome):
        return self.valores.get(nome)

    def gravar(self, nome, valor):
        self.valores[nome] = valor

    def apagar(self, nome):
        self.valores.pop(nome, None)


def test_abrir_com_o_windows_e_comando_no_terminal(tmp_path):
    registro = RegistroFalso()
    ini = InicializacaoWindows(registro, tmp_path / "WindowsApps", r'"C:\Robofael\Robofael.exe"')
    assert ini.estado().abrir_ao_entrar is False and ini.estado().comando_no_terminal is False
    ini.aplicar(True, True)
    assert registro.valores == {"Robofael": r'"C:\Robofael\Robofael.exe"'}
    assert ini.atalho_terminal.read_bytes() == b'@echo off\r\nstart "" "C:\\Robofael\\Robofael.exe" %*\r\n'
    estado = ini.estado()
    assert estado.abrir_ao_entrar and estado.comando_no_terminal and not estado.comando_do_sistema
    ini.aplicar(False, False)
    assert registro.valores == {} and not ini.atalho_terminal.exists()


def test_nao_apaga_um_robofael_cmd_de_outra_origem(tmp_path):
    ini = InicializacaoWindows(RegistroFalso(), tmp_path, r'"C:\Robofael\Robofael.exe"')
    ini.atalho_terminal.write_text("@echo off\r\nfeito por outra pessoa\r\n", encoding="utf-8")
    ini.aplicar(False, False)
    assert ini.atalho_terminal.read_text(encoding="utf-8").startswith("@echo off")


@so_windows
def test_registro_de_verdade():
    registro, nome = RegistroWindows(), "RobofaelTesteAutomatico"
    try:
        registro.gravar(nome, r'"C:\x\Robofael.exe"')
        assert registro.ler(nome) == r'"C:\x\Robofael.exe"'
    finally:
        registro.apagar(nome)
    assert registro.ler(nome) is None
    registro.apagar(nome)  # apagar o que não existe não é erro


# ---------- Programas ----------
def _menu_iniciar(base: Path, *atalhos: str) -> Path:
    pasta = base / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    for atalho in atalhos:
        (pasta / atalho).parent.mkdir(parents=True, exist_ok=True)
        (pasta / atalho).write_bytes(b"")
    return pasta


def test_programas_do_menu_iniciar_e_do_sistema(tmp_path):
    usuario = _menu_iniciar(tmp_path / "usuario", "Spotify.lnk", "FileZilla/FileZilla.lnk")
    todos = _menu_iniciar(tmp_path / "todos", "Google Chrome.lnk", "Spotify.lnk", "FileZilla/Uninstall FileZilla.lnk")
    abertos = []
    lancador = LancadorWindows([usuario, todos], abertos.append, navegador=lambda: "ChromeHTML")
    nomes = [p.nome for p in lancador.programas()]
    assert {"Spotify", "FileZilla", "Google Chrome", "Calculator", "Settings"} <= set(nomes)
    assert nomes.count("Spotify") == 1 and not any("Uninstall" in n for n in nomes)
    spotify = next(p for p in lancador.programas() if p.nome == "Spotify")
    assert spotify.arquivo == usuario / "Spotify.lnk"  # o atalho do usuário tem prioridade

    servico = ServicoProgramas(lancador)
    assert servico.abrir("calculadora")["ok"] and abertos[-1] == "calc.exe"
    assert servico.abrir("filezilla")["ok"] and abertos[-1] == str(usuario / "FileZilla" / "FileZilla.lnk")
    assert servico.abrir("navegador")["programa"] == "Google Chrome"  # o padrão, lido do registro


def test_sem_navegador_padrao_conhecido_procura_pelo_nome(tmp_path):
    lancador = LancadorWindows([], lambda c: None, navegador=lambda: None)
    assert lancador.navegador_padrao() is None
    assert ServicoProgramas(lancador).abrir("navegador")["programa"] == "Microsoft Edge"


def test_abrir_fora_do_windows_avisa():
    lancador = LancadorWindows([], navegador=lambda: None)
    lancador._abrir = None
    assert ServicoProgramas(lancador).abrir("calculadora") == {
        "ok": False, "frase": "Não consegui abrir o Calculator."}


def test_adaptadores_conforme_o_sistema():
    lancador, dispositivos, inicializacao = bootstrap.adaptadores_do_sistema("win32")
    assert (type(lancador).__name__, type(dispositivos).__name__, type(inicializacao).__name__) == \
        ("LancadorWindows", "DispositivosWindows", "InicializacaoWindows")
    assert type(bootstrap.adaptadores_do_sistema("linux")[0]).__name__ == "LancadorLinux"


# ---------- Pastas do executável ----------
def test_executavel_guarda_os_dados_na_pasta_do_usuario(tmp_path, monkeypatch):
    monkeypatch.setattr(configuracao, "EMPACOTADO", True)
    env = {"LOCALAPPDATA": str(tmp_path / "Local")}
    cfg = Configuracao.do_ambiente(env)
    assert cfg.pasta_dados == tmp_path / "Local" / "Robofael" / "dados"
    assert cfg.pasta_cache == tmp_path / "Local" / "Robofael" / "cache"
    assert cfg.pasta_assets == configuracao.RAIZ_RECURSOS / "assets"  # dentro do pacote (só leitura)
    assert Configuracao.do_ambiente({**env, "ROBOFAEL_DADOS": str(tmp_path / "outra")}).pasta_dados == \
        tmp_path / "outra"


def test_no_desenvolvimento_as_pastas_nao_mudam():
    cfg = Configuracao.do_ambiente({})
    assert cfg.pasta_dados == configuracao.RAIZ_PROJETO / "dados"
    assert cfg.pasta_cache == configuracao.RAIZ_PROJETO / ".cache"


# ---------- Verificação do pacote ----------
def test_verificacao_aponta_o_que_falta(tmp_path):
    cfg = Configuracao.do_ambiente({"ROBOFAEL_MODELOS": str(tmp_path / "sem-modelo"),
                                    "ROBOFAEL_ASSETS": str(tmp_path / "sem-assets")})
    problemas = bootstrap.verificar_instalacao(cfg)
    assert any(p.startswith("modelo de voz") for p in problemas)
    assert any(p.startswith("avatares") for p in problemas)
    assert not any(p.startswith("biblioteca") for p in problemas)


def test_opcao_verificar_sai_com_codigo_de_erro(tmp_path, monkeypatch):
    from robofael.apresentacao import app

    monkeypatch.setenv("ROBOFAEL_MODELOS", str(tmp_path / "sem-modelo"))
    with pytest.raises(SystemExit) as saida:
        app.main(["--verificar"])
    assert saida.value.code == 1


def test_cache_do_avatar_funciona_sem_o_codigo_fonte(monkeypatch):
    from robofael.avatar import renderizador

    com_fonte = renderizador._codigo_deste_modulo()
    monkeypatch.setattr(renderizador, "__file__", "/executavel/sem/renderizador.py")  # como no PyInstaller
    sem_fonte = renderizador._codigo_deste_modulo()
    assert com_fonte and sem_fonte and sem_fonte != com_fonte


@pytest.mark.lento
def test_verificacao_desenha_o_avatar_no_tk(raiz):
    from robofael.apresentacao.app import verificar_avatar

    assert verificar_avatar(Configuracao.do_ambiente({})) == []
    assert verificar_avatar(Configuracao.do_ambiente({"ROBOFAEL_ASSETS": "/nao/existe"}))[0].startswith("avatar:")
