"""Programas instalados no Linux (entradas .desktop, padrão freedesktop/XDG).

Só abre programas que estão registrados no sistema: a fala nunca vira um comando de shell
arbitrário. Procura nos diretórios de `XDG_DATA_HOME` e `XDG_DATA_DIRS` (inclui Snap e
Flatpak) e abre com `gtk-launch` (respeita a entrada .desktop); sem ele, executa o `Exec`
da entrada, sem shell e com os códigos de campo (%u, %f...) removidos."""

from __future__ import annotations

import configparser
import logging
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from robofael.portas import Programa

log = logging.getLogger(__name__)

CACHE_S = 60.0
_CODIGOS_DE_CAMPO = re.compile(r"(?<!%)%[fFuUdDnNickvm]")


def diretorios_padrao(env: dict[str, str] | None = None) -> list[Path]:
    env = dict(os.environ if env is None else env)
    casa = Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    dados = (env.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    extras = ["/var/lib/snapd/desktop", "/var/lib/flatpak/exports/share",
              str(Path.home() / ".local/share/flatpak/exports/share")]
    vistos, pastas = set(), []
    for base in [str(casa), *dados, *extras]:  # usuário primeiro: suas entradas têm prioridade
        pasta = Path(base) / "applications"
        if base and pasta not in vistos:
            vistos.add(pasta)
            pastas.append(pasta)
    return pastas


class _LeitorDesktop(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr  # chaves de .desktop diferenciam maiúsculas (Name, Name[pt_BR]...)


def _localizado(secao: configparser.SectionProxy, chave: str) -> str:
    for sufixo in ("[pt_BR]", "[pt]", ""):
        if valor := secao.get(chave + sufixo):
            return valor.strip()
    return ""


def ler_desktop(arquivo: Path, pasta: Path) -> Programa | None:
    """Uma entrada .desktop visível do tipo Application, ou None."""
    leitor = _LeitorDesktop(interpolation=None, strict=False)
    try:
        leitor.read(arquivo, encoding="utf-8")
    except (configparser.Error, UnicodeDecodeError, OSError):
        return None
    if "Desktop Entry" not in leitor:
        return None
    e = leitor["Desktop Entry"]  # só a seção principal (as "Desktop Action" não são programas)
    if e.get("Type") != "Application" or e.get("NoDisplay", "").lower() == "true" or \
            e.get("Hidden", "").lower() == "true":
        return None
    nome, comando = _localizado(e, "Name"), e.get("Exec", "").strip()
    if not nome or not comando:
        return None
    if (tentar := e.get("TryExec")) and not shutil.which(tentar.strip()):
        return None
    palavras = tuple(p for p in _localizado(e, "Keywords").split(";") if p)
    identificador = str(arquivo.relative_to(pasta)).replace("/", "-").removesuffix(".desktop")
    return Programa(identificador, nome, comando, arquivo, _localizado(e, "GenericName"), palavras)


class LancadorLinux:
    def __init__(self, pastas: list[Path] | None = None, executar: Callable = subprocess.Popen,
                 gtk_launch: str | None = None):
        self.pastas = pastas if pastas is not None else diretorios_padrao()
        self._executar = executar
        self._gtk_launch = gtk_launch if gtk_launch is not None else shutil.which("gtk-launch")
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
            for arquivo in sorted(pasta.rglob("*.desktop")):
                identificador = str(arquivo.relative_to(pasta)).replace("/", "-").removesuffix(".desktop")
                if identificador in encontrados:
                    continue  # a mesma entrada numa pasta de maior prioridade já foi lida
                if programa := ler_desktop(arquivo, pasta):
                    encontrados[identificador] = programa
        log.debug("%d programas encontrados", len(encontrados))
        return sorted(encontrados.values(), key=lambda p: p.nome.lower())

    def navegador_padrao(self) -> Programa | None:
        """O navegador padrão do usuário (xdg-settings), se estiver entre os programas."""
        if not shutil.which("xdg-settings"):
            return None
        try:
            saida = subprocess.run(["xdg-settings", "get", "default-web-browser"], capture_output=True, text=True,
                                   timeout=2, check=False).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
        identificador = saida.removesuffix(".desktop")
        return next((p for p in self.programas() if p.id == identificador), None)

    def abrir(self, programa: Programa) -> None:
        if self._gtk_launch:
            argumentos = [self._gtk_launch, programa.id]
        else:
            argumentos = shlex.split(_CODIGOS_DE_CAMPO.sub("", programa.comando).replace("%%", "%"))
        log.info("Abrindo %s (%s)", programa.nome, " ".join(argumentos))
        self._executar(argumentos, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
