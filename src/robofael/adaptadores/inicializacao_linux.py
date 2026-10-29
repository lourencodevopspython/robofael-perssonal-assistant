"""Abrir o assistente junto com o computador e pelo terminal, no Linux (padrão XDG).

- Ao entrar: um atalho em `~/.config/autostart/robofael.desktop`, que o GNOME (e os outros
  ambientes gráficos) abrem quando o usuário entra na sessão.
- No terminal: atalhos `robofael` e `robofael-gravar-voz` em `~/.local/bin`, pasta que o
  `~/.profile` do Ubuntu já põe no PATH. Instalado pelo .deb, o comando já existe em
  `/usr/bin` e não há nada a fazer.

O estado é lido dos próprios arquivos (não de uma preferência salva), então mexer neles
por fora também aparece na tela de configurações."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from robofael.portas import EstadoInicializacao

log = logging.getLogger(__name__)

COMANDOS = ("robofael", "robofael-gravar-voz")
COMANDO_DO_PACOTE = Path("/usr/bin/robofael")
ATRASO_S = 5  # espera o servidor de áudio e a rede subirem antes de abrir


def _citar(caminho: Path) -> str:
    """Caminho no campo Exec de um .desktop (aspas se tiver espaço ou caractere especial)."""
    texto = str(caminho)
    if not any(c in texto for c in ' \t"\'\\$`'):
        return texto
    return '"' + texto.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'


class InicializacaoLinux:
    def __init__(self, casa: Path | None = None, config_xdg: Path | None = None,
                 pasta_programa: Path | None = None, comando_do_pacote: Path = COMANDO_DO_PACOTE):
        casa = casa or Path.home()
        config_xdg = config_xdg or Path(os.environ.get("XDG_CONFIG_HOME") or casa / ".config")
        self.atalho_sessao = config_xdg / "autostart" / "robofael.desktop"
        self.pasta_comandos = casa / ".local" / "bin"
        # Onde ficam os comandos do ambiente em uso (ex.: .venv/bin no desenvolvimento)
        self.pasta_programa = pasta_programa or Path(sys.executable).parent
        self.comando_do_pacote = comando_do_pacote

    @property
    def _do_sistema(self) -> bool:
        return self.comando_do_pacote.exists()

    def _executavel(self, nome: str = "robofael") -> Path:
        """O lançador do pacote define as pastas de dados: tem prioridade sobre o do ambiente."""
        if self._do_sistema:
            return self.comando_do_pacote.with_name(nome)
        return self.pasta_programa / nome

    def estado(self) -> EstadoInicializacao:
        return EstadoInicializacao(
            abrir_ao_entrar=self.atalho_sessao.is_file(),
            comando_no_terminal=self._do_sistema or (self.pasta_comandos / COMANDOS[0]).exists(),
            comando_do_sistema=self._do_sistema)

    def aplicar(self, abrir_ao_entrar: bool, comando_no_terminal: bool) -> None:
        atual = self.estado()
        if abrir_ao_entrar and not atual.abrir_ao_entrar:
            self._criar_atalho_sessao()
        elif not abrir_ao_entrar and atual.abrir_ao_entrar:
            self.atalho_sessao.unlink(missing_ok=True)
            log.info("Abrir ao entrar no computador: desligado")
        if atual.comando_do_sistema or comando_no_terminal == atual.comando_no_terminal:
            return
        if comando_no_terminal:
            self._criar_comandos()
        else:
            self._remover_comandos()

    def _criar_atalho_sessao(self) -> None:
        self.atalho_sessao.parent.mkdir(parents=True, exist_ok=True)
        self.atalho_sessao.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=Robofael\n"
            "Comment=Assistente pessoal com avatar que ouve e responde por voz\n"
            f"TryExec={_citar(self._executavel())}\n"  # programa removido: o atalho é ignorado, sem erro
            f"Exec={_citar(self._executavel())}\n"
            "Icon=robofael\n"
            "Terminal=false\n"
            "X-GNOME-Autostart-enabled=true\n"
            f"X-GNOME-Autostart-Delay={ATRASO_S}\n", encoding="utf-8")
        log.info("Abrir ao entrar no computador: ligado (%s)", self.atalho_sessao)

    def _criar_comandos(self) -> None:
        self.pasta_comandos.mkdir(parents=True, exist_ok=True)
        for nome in COMANDOS:
            destino, link = self._executavel(nome), self.pasta_comandos / nome
            if destino.exists() and not link.exists() and not link.is_symlink():
                link.symlink_to(destino)
        log.info("Comando no terminal: ligado (%s)", self.pasta_comandos / COMANDOS[0])

    def _remover_comandos(self) -> None:
        """Só apaga os atalhos que apontam para este programa (nunca um arquivo de outra origem)."""
        for nome in COMANDOS:
            link = self.pasta_comandos / nome
            if link.is_symlink() and Path(os.readlink(link)) == self._executavel(nome):
                link.unlink()
        log.info("Comando no terminal: desligado")
