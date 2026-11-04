"""Programas instalados no Windows: os atalhos do Menu Iniciar e os aplicativos do próprio sistema.

Como no Linux, só abre o que está registrado (a fala nunca vira um comando arbitrário). Os atalhos (.lnk)
do Menu Iniciar do usuário e de todos os usuários são abertos com `os.startfile`, como um clique duplo.
Aplicativos do sistema como a Calculadora e as Configurações não têm atalho ali (são da Microsoft Store),
então entram por uma lista fixa de comandos conhecidos."""

from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from robofael.portas import Programa

log = logging.getLogger(__name__)

CACHE_S = 60.0
# Desinstaladores, leia-mes e afins também aparecem como atalhos no Menu Iniciar
_IGNORAR = ("uninstall", "desinstalar", "readme", "leia-me", "help", "ajuda", "documentation", "documentação",
            "release notes", "website", "site")
SISTEMA = (  # (id, nome, comando para os.startfile, palavras-chave)
    ("calc", "Calculator", "calc.exe", ("calculadora",)),
    ("notepad", "Notepad", "notepad.exe", ("bloco de notas", "text editor")),
    ("settings", "Settings", "ms-settings:", ("configurações", "ajustes")),
    ("explorer", "File Explorer", "explorer.exe", ("files", "arquivos", "pastas")),
    ("taskmgr", "Task Manager", "taskmgr.exe", ("system monitor", "gerenciador de tarefas")),
    ("snipping", "Snipping Tool", "ms-screenclip:", ("screenshot", "captura de tela")),
    ("paint", "Paint", "mspaint.exe", ("desenho", "imagens")),
    ("cmd", "Terminal", "cmd.exe", ("prompt de comando", "command prompt")),
    ("camera", "Camera", "microsoft.windows.camera:", ("câmera",)),
    ("edge", "Microsoft Edge", "microsoft-edge:", ("web browser", "navegador", "internet")),
)


# ProgId do navegador padrão (registro) -> como o navegador aparece no Menu Iniciar
NAVEGADORES = (("chrome", "google chrome"), ("msedge", "microsoft edge"), ("firefox", "firefox"),
               ("brave", "brave"), ("opera", "opera"), ("vivaldi", "vivaldi"))
CHAVE_NAVEGADOR = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"


def progid_navegador() -> str | None:
    """O ProgId do navegador padrão do usuário (ex.: "ChromeHTML", "MSEdgeHTM")."""
    try:
        winreg = importlib.import_module("winreg")
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_NAVEGADOR) as chave:
            return str(winreg.QueryValueEx(chave, "ProgId")[0])
    except (ImportError, OSError):
        return None


def pastas_padrao(env: dict[str, str] | None = None) -> list[Path]:
    env = dict(os.environ if env is None else env)
    bases = [env.get("APPDATA"), env.get("PROGRAMDATA")]  # usuário primeiro: seus atalhos têm prioridade
    return [Path(b) / "Microsoft" / "Windows" / "Start Menu" / "Programs" for b in bases if b]


class LancadorWindows:
    def __init__(self, pastas: list[Path] | None = None,
                 abrir_arquivo: Callable[[str], None] | None = None,
                 navegador: Callable[[], str | None] = progid_navegador):
        self.pastas = pastas if pastas is not None else pastas_padrao()
        self._abrir = abrir_arquivo or getattr(os, "startfile", None)
        self._progid_navegador = navegador
        self._cache: list[Programa] = []
        self._lido_em = 0.0
        self._trava = threading.Lock()

    def programas(self) -> list[Programa]:
        with self._trava:
            if not self._cache or time.monotonic() - self._lido_em > CACHE_S:
                self._cache = self._varrer()
                self._lido_em = time.monotonic()
            return list(self._cache)

    def _varrer(self) -> list[Programa]:
        encontrados: dict[str, Programa] = {}
        for pasta in self.pastas:
            if not pasta.is_dir():
                continue
            for atalho in sorted(pasta.rglob("*.lnk")):
                nome = atalho.stem.strip()
                chave = nome.lower()
                if not nome or chave in encontrados or any(p in chave for p in _IGNORAR):
                    continue
                encontrados[chave] = Programa(f"lnk:{chave}", nome, str(atalho), atalho,
                                              palavras_chave=(atalho.parent.name,))
        for ident, nome, comando, palavras in SISTEMA:
            encontrados.setdefault(nome.lower(), Programa(ident, nome, comando, None, palavras_chave=palavras))
        log.debug("%d programas encontrados", len(encontrados))
        return sorted(encontrados.values(), key=lambda p: p.nome.lower())

    def navegador_padrao(self) -> Programa | None:
        """O navegador padrão do usuário, se estiver entre os programas ("abre o navegador")."""
        progid = (self._progid_navegador() or "").lower()
        nome = next((nome for chave, nome in NAVEGADORES if chave in progid), None)
        if nome is None:
            return None
        return next((p for p in self.programas() if p.nome.lower() == nome), None)

    def abrir(self, programa: Programa) -> None:
        if self._abrir is None:
            raise OSError("abrir programas só funciona no Windows")
        log.info("Abrindo %s (%s)", programa.nome, programa.comando)
        self._abrir(programa.comando)
