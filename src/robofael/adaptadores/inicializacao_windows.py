"""Abrir o assistente junto com o Windows e pelo terminal.

- Ao entrar: o valor `Robofael` na chave `Run` do usuário (HKCU), que o Windows executa no login.
- No terminal: um `robofael.cmd` em `%LOCALAPPDATA%\\Microsoft\\WindowsApps`, pasta que o Windows já põe
  no PATH de todo usuário; assim `robofael` funciona no Prompt de Comando e no PowerShell sem mexer no PATH.

O estado é lido do próprio registro e do arquivo, como no Linux: mexer neles por fora aparece na tela."""

from __future__ import annotations

import importlib
import logging
import os
import sys
from pathlib import Path
from typing import Any, Protocol

from robofael.portas import EstadoInicializacao

log = logging.getLogger(__name__)

CHAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOME = "Robofael"


class RegistroRun(Protocol):
    """Os programas que abrem no login (a chave Run do usuário)."""

    def ler(self, nome: str) -> str | None: ...
    def gravar(self, nome: str, valor: str) -> None: ...
    def apagar(self, nome: str) -> None: ...


def _winreg() -> Any:
    return importlib.import_module("winreg")  # só existe no Windows


class RegistroWindows:
    def ler(self, nome: str) -> str | None:
        winreg = _winreg()

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN) as chave:
                return str(winreg.QueryValueEx(chave, nome)[0])
        except OSError:
            return None

    def gravar(self, nome: str, valor: str) -> None:
        winreg = _winreg()

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN) as chave:
            winreg.SetValueEx(chave, nome, 0, winreg.REG_SZ, valor)

    def apagar(self, nome: str) -> None:
        winreg = _winreg()

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN, 0, winreg.KEY_SET_VALUE) as chave:
                winreg.DeleteValue(chave, nome)
        except FileNotFoundError:
            pass


def comando_do_programa() -> str:
    """Como abrir este programa: o executável empacotado ou, no desenvolvimento, `pythonw -m robofael`."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    janela = Path(sys.executable).with_name("pythonw.exe")
    return f'"{janela if janela.exists() else sys.executable}" -m robofael'


class InicializacaoWindows:
    def __init__(self, registro: RegistroRun | None = None, pasta_comandos: Path | None = None,
                 comando: str | None = None):
        self.registro = registro or RegistroWindows()
        local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        self.pasta_comandos = pasta_comandos or Path(local) / "Microsoft" / "WindowsApps"
        self.comando = comando or comando_do_programa()

    @property
    def atalho_terminal(self) -> Path:
        return self.pasta_comandos / "robofael.cmd"

    def _conteudo_atalho(self) -> str:
        # `start ""` solta o terminal na hora (a janela do assistente segue aberta sozinha)
        return f'@echo off\r\nstart "" {self.comando} %*\r\n'

    def estado(self) -> EstadoInicializacao:
        return EstadoInicializacao(abrir_ao_entrar=self.registro.ler(NOME) is not None,
                                   comando_no_terminal=self.atalho_terminal.is_file())

    def aplicar(self, abrir_ao_entrar: bool, comando_no_terminal: bool) -> None:
        atual = self.estado()
        if abrir_ao_entrar and not atual.abrir_ao_entrar:
            self.registro.gravar(NOME, self.comando)
            log.info("Abrir ao entrar no Windows: ligado (%s)", self.comando)
        elif not abrir_ao_entrar and atual.abrir_ao_entrar:
            self.registro.apagar(NOME)
            log.info("Abrir ao entrar no Windows: desligado")
        if comando_no_terminal and not atual.comando_no_terminal:
            self.pasta_comandos.mkdir(parents=True, exist_ok=True)
            self.atalho_terminal.write_text(self._conteudo_atalho(), encoding="utf-8", newline="")
            log.info("Comando no terminal: ligado (%s)", self.atalho_terminal)
        elif not comando_no_terminal and atual.comando_no_terminal:
            # Só apaga o atalho que este programa criou (nunca um arquivo de outra origem)
            if self.atalho_terminal.read_bytes() == self._conteudo_atalho().encode():
                self.atalho_terminal.unlink()
                log.info("Comando no terminal: desligado")
            else:
                log.warning("%s não foi criado por este programa: não apago", self.atalho_terminal)
