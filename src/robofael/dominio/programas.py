"""Encontrar o programa que o usuário pediu ("abre o navegador", "abrir o vs code")."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

_ARTIGOS = r"^(?:o|a|os|as|meu|minha|um|uma|the|my|a|an)\s+"
_GENERICOS = r"^(?:programa|aplicativo|app|aplicacao|application|program)\s+(?:do|da|de|for)?\s*"
_PEDIDO = re.compile(
    r"\b(?:abr[ae]|abrir|abra|inici[ae]|iniciar|execut[ae]|executar|rod[ae]|rodar|lanc[ae]|lancar"
    r"|open|launch|start|run)\s+(?P<nome>.+)",
    re.I,
)
LIMIAR = 0.62
EMPATE = 0.04


@dataclass(frozen=True, slots=True)
class Programa:
    """Aplicativo instalado (entrada .desktop do Linux)."""

    id: str
    nome: str
    comando: str
    arquivo: Path | None = None
    descricao: str = ""
    palavras_chave: tuple[str, ...] = ()
# Muitos aplicativos só trazem o nome em inglês no .desktop (a tradução é aplicada pelo
# ambiente gráfico na hora de exibir): "configurações" precisa achar "Settings".
SINONIMOS: dict[str, tuple[str, ...]] = {
    "configuracoes": ("settings",), "configuracao": ("settings",), "ajustes": ("settings",),
    "calculadora": ("calculator",), "calendario": ("calendar",), "agenda": ("calendar",),
    "arquivos": ("files",), "gerenciador de arquivos": ("files",), "pastas": ("files",),
    "navegador": ("web browser", "firefox", "chromium", "google chrome"), "internet": ("web browser",),
    "editor de texto": ("text editor",), "bloco de notas": ("text editor",), "monitor do sistema": ("system monitor",),
    "gerenciador de tarefas": ("system monitor",), "captura de tela": ("screenshot",), "print": ("screenshot",),
    "camera": ("cheese", "camera"), "musica": ("music", "rhythmbox"), "videos": ("videos",), "video": ("videos",),
    "fotos": ("photos", "shotwell"), "imagens": ("image viewer",), "visualizador de imagens": ("image viewer",),
    "documentos": ("document viewer",), "pdf": ("document viewer",), "relogio": ("clocks",), "mapas": ("maps",),
    "loja": ("app center", "software"), "central de aplicativos": ("app center",), "email": ("thunderbird",),
    "e mail": ("thunderbird",), "correio": ("thunderbird",), "discos": ("disks",), "terminal": ("terminal",),
    "vs code": ("visual studio code", "code"), "vscode": ("visual studio code", "code"),
}


def normalizar(texto: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9+ ]", " ", s)
    for cauda in (" pra mim", " por favor", " for me", " please"):
        s = s.split(cauda)[0]
    return s.strip()


def extrair_pedido(fala: str) -> str | None:
    """'pode abrir o firefox pra mim?' -> 'firefox'; None se a fala não pede para abrir algo."""
    m = _PEDIDO.search(normalizar(fala).replace("  ", " "))
    if not m:
        return None
    nome = m["nome"].strip()
    nome = re.sub(_ARTIGOS, "", nome)
    nome = re.sub(_GENERICOS, "", nome)
    nome = re.sub(_ARTIGOS, "", nome).strip()
    return nome or None


@dataclass(frozen=True)
class Candidato:
    programa: Programa
    pontuacao: float


def _pontuar(consulta: str, p: Programa) -> float:
    nome = normalizar(p.nome)
    executavel = normalizar(p.comando.split()[0].rsplit("/", 1)[-1]) if p.comando else ""
    palavras_nome = nome.split()
    if consulta in (nome, executavel):
        return 1.0
    if nome.startswith(consulta + " ") or consulta in palavras_nome:
        return 0.9
    extras = [normalizar(x) for x in (p.descricao, *p.palavras_chave) if x]
    if any(consulta == e or consulta in e.split() for e in extras):
        return 0.8
    if len(consulta) >= 4 and (consulta in nome or any(consulta in e for e in extras)):
        return 0.75
    return SequenceMatcher(None, consulta, nome).ratio() * 0.9


def ranquear(consulta: str, programas: list[Programa]) -> list[Candidato]:
    """Candidatos acima do limiar, do mais provável ao menos provável."""
    consulta = normalizar(consulta)
    if not consulta:
        return []
    alternativas = SINONIMOS.get(consulta, ())

    def pontuar(p: Programa) -> float:  # o sinônimo vale um pouco menos que o nome dito
        return max([_pontuar(consulta, p), *(_pontuar(a, p) * 0.97 for a in alternativas)])

    candidatos = [Candidato(p, pontuar(p)) for p in programas]
    return sorted((c for c in candidatos if c.pontuacao >= LIMIAR), key=lambda c: (-c.pontuacao, c.programa.nome))


def escolher(candidatos: list[Candidato]) -> Programa | list[Programa] | None:
    """Um programa se a escolha é clara; a lista empatada se há ambiguidade; None se nada serve."""
    if not candidatos:
        return None
    melhor = candidatos[0].pontuacao
    empatados = [c.programa for c in candidatos if melhor - c.pontuacao <= EMPATE]
    nomes = {normalizar(p.nome) for p in empatados}
    return empatados[0] if len(nomes) == 1 else empatados[:4]
