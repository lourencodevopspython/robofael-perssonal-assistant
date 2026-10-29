"""Escolha do microfone e inicialização junto com o computador / pelo terminal."""

import os
import subprocess
from types import SimpleNamespace

import pytest

from robofael import bootstrap
from robofael.adaptadores import dispositivos_audio
from robofael.adaptadores.dispositivos_audio import DispositivosPulse, ler_fontes, microfone_escolhido
from robofael.adaptadores.inicializacao_linux import InicializacaoLinux, _citar
from robofael.aplicacao import sessao
from robofael.apresentacao.configuracoes import encurtar, rotulos_microfones
from robofael.configuracao import Configuracao
from robofael.i18n import Idioma, Tradutor
from robofael.portas import EstadoInicializacao, Microfone, Preferencias

SAIDA_PACTL = """\
Source #57
\tState: SUSPENDED
\tName: alsa_input.usb-Jieli_Technology_USB_Composite_Device-02.mono-fallback
\tDescription: USB Composite Device Mono
\tMonitor of Sink: n/a
\tProperties:
\t\tdevice.class = "sound"
Source #58
\tName: alsa_output.pci-0000_00_1f.3.HiFi__hw_sofhdadsp__sink.monitor
\tDescription: Monitor of Speaker + Headphones
\tMonitor of Sink: alsa_output.pci-0000_00_1f.3.HiFi__hw_sofhdadsp__sink
Source #63
\tName: alsa_input.pci-0000_00_1f.3.HiFi__hw_sofhdadsp_6__source
\tDescription: Tiger Lake-LP Smart Sound Technology Audio Controller Digital Microphone
\tMonitor of Sink: n/a
"""

USB = Microfone("alsa_input.usb-Jieli_Technology_USB_Composite_Device-02.mono-fallback", "USB Composite Device Mono")
INTERNO = Microfone("alsa_input.pci-0000_00_1f.3.HiFi__hw_sofhdadsp_6__source",
                    "Tiger Lake-LP Smart Sound Technology Audio Controller Digital Microphone")


# ---------- Listar e escolher o microfone ----------
def test_lista_os_microfones_sem_os_monitores_das_saidas_de_som():
    assert ler_fontes(SAIDA_PACTL) == [USB, INTERNO]
    assert ler_fontes("") == []


def test_sem_pactl_a_lista_fica_vazia(monkeypatch):
    def falhar(*_a, **_k):
        raise FileNotFoundError("pactl")

    monkeypatch.setattr(subprocess, "run", falhar)
    assert DispositivosPulse().microfones() == []


def test_lista_pelo_pactl_em_ingles(monkeypatch):
    chamadas = []

    def rodar(comando, **kw):
        chamadas.append((comando, kw["env"]["LC_ALL"]))
        return SimpleNamespace(stdout=SAIDA_PACTL)

    monkeypatch.setattr(subprocess, "run", rodar)
    assert DispositivosPulse().microfones() == [USB, INTERNO]
    assert chamadas == [(["pactl", "list", "sources"], "C")]  # descrições e chaves sem tradução


def test_microfone_escolhido_so_vale_durante_a_abertura(monkeypatch):
    monkeypatch.delenv("PIPEWIRE_NODE", raising=False)
    monkeypatch.setenv("PULSE_SOURCE", "antes")
    with microfone_escolhido(USB.id):
        assert os.environ["PIPEWIRE_NODE"] == os.environ["PULSE_SOURCE"] == USB.id
    # não vaza para os programas que o assistente abre depois
    assert "PIPEWIRE_NODE" not in os.environ and os.environ["PULSE_SOURCE"] == "antes"
    with microfone_escolhido(None):  # padrão do sistema: não mexe em nada
        assert "PIPEWIRE_NODE" not in os.environ
    assert not dispositivos_audio._trava_ambiente.locked()


def test_rotulos_dos_microfones_na_tela():
    tr = Tradutor()
    rotulos = rotulos_microfones([USB, INTERNO], None, tr)
    assert list(rotulos) == ["Padrão do sistema", "USB Composite Device Mono", "…Audio Controller Digital Microphone"]
    assert list(rotulos.values()) == [None, USB.id, INTERNO.id]
    # dois aparelhos iguais continuam distinguíveis
    gemeo = Microfone("outro-usb", USB.nome)
    assert list(rotulos_microfones([USB, gemeo], None, tr))[1:] == ["USB Composite Device Mono",
                                                                     "USB Composite Device Mono (2)"]
    # o escolhido aparece mesmo desconectado, em vez de trocar de microfone sozinho
    ausente = rotulos_microfones([INTERNO], USB.id, Tradutor(Idioma.EN_US))
    assert ausente[f"{encurtar(USB.id + ' (disconnected)')}"] == USB.id


def test_encurtar_corta_o_comeco_numa_palavra_inteira():
    assert encurtar("Microfone USB") == "Microfone USB"
    curto = encurtar(INTERNO.nome)
    assert len(curto) <= 40 and curto.startswith("…") and curto.endswith("Digital Microphone")
    assert encurtar("x" * 50).startswith("…") and len(encurtar("x" * 50)) == 40


# ---------- Política da sessão ----------
class OrquestradorFalso:
    def __init__(self, ligada=True):
        self.vigia_ligada, self.chamadas = ligada, []

    def iniciar_vigia(self):
        self.chamadas.append("ligar")
        self.vigia_ligada = True

    def desligar_vigia(self):
        self.chamadas.append("desligar")
        self.vigia_ligada = False


@pytest.fixture
def nucleo(tmp_path):
    config = Configuracao.do_ambiente({"ROBOFAEL_DADOS": str(tmp_path / "d"), "ROBOFAEL_CACHE": str(tmp_path / "c")})
    return bootstrap.montar_nucleo(config, dispositivos=SimpleNamespace(microfones=lambda: [USB]))


def test_trocar_o_microfone_reabre_a_escuta_passiva(nucleo):
    orq = OrquestradorFalso()
    servicos = SimpleNamespace(orquestrador=orq, ativacao_por_voz=True, sintetizador=None)
    assert nucleo.microfone is None and nucleo.microfones() == [USB]
    sessao.aplicar_preferencias(nucleo, servicos, Preferencias(microfone=USB.id))
    assert nucleo.microfone == USB.id and orq.chamadas == ["desligar", "ligar"]  # reabre no microfone novo
    assert nucleo.banco.carregar_preferencias().microfone == USB.id  # e fica salvo

    orq.chamadas.clear()
    sessao.aplicar_preferencias(nucleo, servicos, Preferencias(microfone=USB.id, ativacao_por_voz=True))
    assert orq.chamadas == ["ligar"]  # mesmo microfone: não precisa reabrir
    orq.chamadas.clear()
    sessao.aplicar_preferencias(nucleo, servicos, Preferencias(ativacao_por_voz=False))
    assert orq.chamadas == ["desligar"] and nucleo.microfone is None  # voltou ao padrão do sistema


def test_trocar_o_microfone_nao_liga_a_escuta_passiva_desligada(nucleo):
    orq = OrquestradorFalso(ligada=False)
    servicos = SimpleNamespace(orquestrador=orq, ativacao_por_voz=True, sintetizador=None)
    sessao.aplicar_preferencias(nucleo, servicos, Preferencias(microfone=USB.id))
    assert orq.chamadas == ["desligar"] and not orq.vigia_ligada


def test_aplicar_inicializacao(nucleo):
    aplicados = []

    class Inicializacao:
        def estado(self):
            return EstadoInicializacao(False, False)

        def aplicar(self, abrir, comando):
            aplicados.append((abrir, comando))
            if comando:
                raise PermissionError("~/.local/bin sem permissão")

    nucleo.inicializacao = Inicializacao()
    assert sessao.aplicar_inicializacao(nucleo, True, False) is True and aplicados == [(True, False)]
    assert sessao.aplicar_inicializacao(nucleo, True, True) is False  # falha vira aviso, não exceção
    nucleo.inicializacao = None
    assert sessao.aplicar_inicializacao(nucleo, True, True) is True


# ---------- Inicialização no Linux ----------
@pytest.fixture
def linux(tmp_path):
    programa = tmp_path / "venv" / "bin"
    programa.mkdir(parents=True)
    for nome in ("robofael", "robofael-gravar-voz"):
        (programa / nome).write_text("#!/bin/sh\n")
    return InicializacaoLinux(casa=tmp_path / "casa", config_xdg=tmp_path / "casa" / ".config",
                              pasta_programa=programa, comando_do_pacote=tmp_path / "usr" / "bin" / "robofael")


def test_abrir_ao_entrar_no_computador(linux, tmp_path):
    assert linux.estado() == EstadoInicializacao(False, False, False)
    linux.aplicar(abrir_ao_entrar=True, comando_no_terminal=False)
    atalho = tmp_path / "casa" / ".config" / "autostart" / "robofael.desktop"
    texto = atalho.read_text()
    assert f"\nExec={tmp_path}/venv/bin/robofael\n" in texto and "Type=Application" in texto
    assert f"TryExec={tmp_path}/venv/bin/robofael\n" in texto  # se o programa sumir, o atalho é ignorado
    assert "X-GNOME-Autostart-enabled=true" in texto
    assert linux.estado().abrir_ao_entrar
    linux.aplicar(abrir_ao_entrar=False, comando_no_terminal=False)
    assert not atalho.exists() and not linux.estado().abrir_ao_entrar


def test_comando_no_terminal(linux, tmp_path):
    linux.aplicar(abrir_ao_entrar=False, comando_no_terminal=True)
    bin_ = tmp_path / "casa" / ".local" / "bin"
    assert os.readlink(bin_ / "robofael") == str(tmp_path / "venv" / "bin" / "robofael")
    assert os.readlink(bin_ / "robofael-gravar-voz") == str(tmp_path / "venv" / "bin" / "robofael-gravar-voz")
    assert linux.estado().comando_no_terminal and not linux.estado().abrir_ao_entrar
    linux.aplicar(abrir_ao_entrar=False, comando_no_terminal=False)
    assert not (bin_ / "robofael").exists() and not linux.estado().comando_no_terminal


def test_comando_no_terminal_nunca_apaga_arquivo_de_outra_origem(linux, tmp_path):
    bin_ = tmp_path / "casa" / ".local" / "bin"
    bin_.mkdir(parents=True)
    (bin_ / "robofael").write_text("#!/bin/sh\necho meu script\n")
    assert linux.estado().comando_no_terminal
    linux.aplicar(abrir_ao_entrar=False, comando_no_terminal=False)
    assert (bin_ / "robofael").read_text().endswith("meu script\n")


def test_instalado_pelo_pacote_o_comando_ja_existe(linux, tmp_path):
    pacote = tmp_path / "usr" / "bin"
    pacote.mkdir(parents=True)
    (pacote / "robofael").write_text("#!/bin/sh\n")
    assert linux.estado() == EstadoInicializacao(False, True, True)
    linux.aplicar(abrir_ao_entrar=True, comando_no_terminal=False)  # não dá para desligar o do pacote
    assert not (tmp_path / "casa" / ".local" / "bin").exists()
    # o lançador do pacote define as pastas de dados: é ele que abre ao entrar
    assert f"Exec={pacote}/robofael\n" in linux.atalho_sessao.read_text()


def test_exec_com_espacos_vai_entre_aspas():
    from pathlib import Path

    assert _citar(Path("/opt/robofael/robofael")) == "/opt/robofael/robofael"
    assert _citar(Path("/home/ana/Meus Projetos/.venv/bin/robofael")) == '"/home/ana/Meus Projetos/.venv/bin/robofael"'
    assert _citar(Path('/tmp/a"b$c')) == '"/tmp/a\\"b\\$c"'
