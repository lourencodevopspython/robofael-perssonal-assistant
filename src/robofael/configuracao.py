"""Configuração imutável e tipada, carregada das variáveis de ambiente."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

RAIZ_PROJETO = Path(__file__).resolve().parents[2]
# Empacotado (PyInstaller, o executável do Windows): avatares e o modelo de voz vêm de dentro do pacote,
# que é só leitura; agenda, preferências e caches ficam na pasta do usuário (%LOCALAPPDATA%\Robofael).
EMPACOTADO = bool(getattr(sys, "frozen", False))
RAIZ_RECURSOS = Path(getattr(sys, "_MEIPASS", RAIZ_PROJETO))


def pasta_usuario(env: Mapping[str, str] | None = None) -> Path:
    """Onde o executável guarda os dados do usuário; no desenvolvimento, a própria pasta do projeto."""
    if not EMPACOTADO:
        return RAIZ_PROJETO
    env = os.environ if env is None else env
    base = env.get("LOCALAPPDATA") or env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "Robofael"
PREFIXO_AMBIENTE = "ROBOFAEL_"
PREFIXO_AMBIENTE_LEGADO = "EUROBO_"  # nome antigo (até a 3.4.0), ainda aceito com aviso

_log = logging.getLogger(__name__)

NOME_BANCO = "memoria.db"
# O banco não pode guardar o próprio endereço: o local escolhido fica num arquivo na pasta de dados
ARQUIVO_LOCAL_BANCO = "local_banco.json"


def ler_local_banco(pasta_dados: Path) -> Path | None:
    """O banco escolhido na tela de configurações (None = o padrão, `<dados>/memoria.db`)."""
    ponteiro = pasta_dados / ARQUIVO_LOCAL_BANCO
    if not ponteiro.is_file():
        return None
    try:
        return Path(json.loads(ponteiro.read_text(encoding="utf-8"))["arquivo"]).expanduser()
    except (OSError, ValueError, KeyError, TypeError) as e:
        _log.warning("%s inválido (%s); usando o banco padrão", ponteiro, e)
        return None


def salvar_local_banco(pasta_dados: Path, arquivo: Path) -> None:
    """Grava o local do banco; o padrão apaga o registro (fica como se nunca tivesse mudado)."""
    ponteiro = pasta_dados / ARQUIVO_LOCAL_BANCO
    if Path(arquivo).resolve() == (pasta_dados / NOME_BANCO).resolve():
        ponteiro.unlink(missing_ok=True)
        return
    pasta_dados.mkdir(parents=True, exist_ok=True)
    temporario = ponteiro.with_suffix(".tmp")
    temporario.write_text(json.dumps({"arquivo": str(arquivo)}, ensure_ascii=False), encoding="utf-8")
    temporario.replace(ponteiro)


def _variavel(env: Mapping[str, str], nome: str) -> str | None:
    """Valor de ROBOFAEL_<nome>; sem ele, aceita EUROBO_<nome> e avisa que o nome antigo vai sair."""
    if env.get(PREFIXO_AMBIENTE + nome):
        return env[PREFIXO_AMBIENTE + nome]
    legado = env.get(PREFIXO_AMBIENTE_LEGADO + nome)
    if legado:
        _log.warning("%s%s está obsoleta; use %s%s", PREFIXO_AMBIENTE_LEGADO, nome, PREFIXO_AMBIENTE, nome)
    return legado or None


CEREBROS = ("auto", "claude", "ollama", "offline")


def _cerebro(texto: str | None) -> str:
    valor = (texto or "auto").strip().lower()
    if valor not in CEREBROS:
        _log.warning("ROBOFAEL_CEREBRO=%s desconhecido; usando 'auto' (opções: %s)", texto, ", ".join(CEREBROS))
        return "auto"
    return valor


def pasta_documentos_padrao(env: Mapping[str, str] | None = None) -> Path:
    """<pasta de documentos do usuário>/Robofael. A pasta de documentos vem do padrão XDG
    (~/.config/user-dirs.dirs), que respeita o idioma do sistema ("Documentos", "Documents")."""
    env = os.environ if env is None else env
    casa = Path(env.get("HOME") or Path.home())
    documentos = env.get("XDG_DOCUMENTS_DIR")
    if not documentos:
        try:
            dirs = (casa / ".config" / "user-dirs.dirs").read_text(encoding="utf-8")
            if m := re.search(r'^XDG_DOCUMENTS_DIR="(.+)"', dirs, re.M):
                documentos = m[1].replace("$HOME", str(casa))
        except OSError:
            pass
    pasta = Path(documentos) if documentos else casa / "Documents"
    return pasta / "Robofael"


def _idioma(texto: str | None) -> str:
    from robofael.i18n import Idioma

    return Idioma.de_texto(texto).value
NOME_ASSISTENTE = "Robofael"
FORMATO_LOG = f"%(asctime)s [{NOME_ASSISTENTE}] %(levelname)s %(name)s: %(message)s"


def configurar_logs(detalhado: bool = False, arquivo: Path | None = None) -> None:
    """`detalhado` liga o DEBUG só do próprio projeto; bibliotecas ficam em WARNING
    (senão PIL, httpcore e asyncio inundam o terminal). Sem terminal (o executável do Windows não tem
    console) e com `arquivo`, o log vai para ele."""
    import logging

    if arquivo is not None and sys.stderr is None:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(level=logging.INFO, format=FORMATO_LOG, datefmt="%Y-%m-%d %H:%M:%S",
                            filename=arquivo, encoding="utf-8")
    else:
        logging.basicConfig(level=logging.INFO, format=FORMATO_LOG, datefmt="%H:%M:%S")
    for ruidoso in ("PIL", "httpx", "httpx2", "httpcore", "httpcore2", "anthropic", "asyncio", "websockets",
                    "aiohttp", "urllib3", "gtts"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    logging.getLogger("robofael").setLevel(logging.DEBUG if detalhado else logging.INFO)


@dataclass(frozen=True, slots=True)
class Configuracao:
    pasta_assets: Path
    pasta_dados: Path
    pasta_cache: Path
    nome_usuario: str = "Rafael"
    nome_assistente: str = NOME_ASSISTENTE
    idioma: str = "pt-BR"
    voz_padrao: str = "pt-BR-AntonioNeural"
    modelo: str = "claude-opus-5-5"
    esforco: str = "low"  # respostas faladas e curtas: menor latência
    max_mensagens_historico: int = 60  # acima disso a conversa recomeça (a agenda persiste)
    timeout_api_s: float = 30.0
    pausa_fim_fala_s: float = 0.7  # silêncio que encerra uma frase do usuário
    max_itens_cache_tts: int = 300
    pasta_modelos: Path = RAIZ_RECURSOS / "modelos"
    modelo_ativacao: str = "vosk-model-small-pt-0.3"
    ativacao_por_voz: bool = True  # escuta passiva da frase de ativação
    frase_ativacao: str = "ok Fael"
    # Cérebro: "auto" tenta Claude, depois o modelo local (Ollama) e, por fim, o modo offline
    cerebro: str = "auto"  # auto | claude | ollama | offline
    url_ollama: str = "http://localhost:11434"
    modelo_local: str = "llama3.2:3b"  # rápido o bastante no processador (sem GPU)
    timeout_local_s: float = 120.0  # modelos locais no processador podem demorar
    pasta_documentos: Path = Path.home() / "Documents" / "Robofael"  # "gerar doc" (ver do_ambiente)
    banco_escolhido: Path | None = None  # outro local para o banco (⚙ → Memória); None = pasta de dados

    @property
    def pasta_modelo_ativacao(self) -> Path:
        return self.pasta_modelos / self.modelo_ativacao

    @property
    def pasta_avatares(self) -> Path:
        return self.pasta_assets / "avatares"

    @property
    def arquivo_agenda(self) -> Path:
        return self.pasta_dados / "agenda.json"

    @property
    def arquivo_banco(self) -> Path:
        """Memória de longo prazo (SQLite): agenda, histórico auditável e preferências."""
        return self.banco_escolhido or self.arquivo_banco_padrao

    @property
    def arquivo_banco_padrao(self) -> Path:
        return self.pasta_dados / NOME_BANCO

    @property
    def arquivo_perfil_voz(self) -> Path:
        return self.pasta_dados / "perfil_voz.json"

    @property
    def pasta_gravacoes(self) -> Path:
        return self.pasta_dados / "minha_voz"

    @property
    def pasta_cache_avatar(self) -> Path:
        return self.pasta_cache / "avatar"

    @property
    def pasta_cache_tts(self) -> Path:
        return self.pasta_cache / "tts"

    @classmethod
    def do_ambiente(cls, env: Mapping[str, str] | None = None) -> Configuracao:
        env = os.environ if env is None else env

        def caminho(nome: str, padrao: Path) -> Path:
            valor = _variavel(env, nome)
            return Path(valor).expanduser() if valor else padrao

        opcionais: dict[str, Any] = {campo: valor for campo, nome in (("nome_usuario", "USUARIO"),
                                                                      ("nome_assistente", "ASSISTENTE"),
                                                                      ("frase_ativacao", "FRASE_ATIVACAO"),
                                                                      ("voz_padrao", "VOZ"),
                                                                      ("modelo", "MODELO"),
                                                                      ("url_ollama", "OLLAMA_URL"),
                                                                      ("modelo_local", "OLLAMA_MODELO"))
                                     if (valor := _variavel(env, nome))}
        usuario = pasta_usuario(env)
        pasta_dados = caminho("DADOS", usuario / "dados")
        return cls(
            pasta_assets=caminho("ASSETS", RAIZ_RECURSOS / "assets"),
            pasta_dados=pasta_dados,
            banco_escolhido=ler_local_banco(pasta_dados),
            pasta_cache=caminho("CACHE", usuario / (".cache" if usuario == RAIZ_PROJETO else "cache")),
            pasta_modelos=caminho("MODELOS", RAIZ_RECURSOS / "modelos"),
            ativacao_por_voz=(_variavel(env, "ATIVACAO") or "1").strip().lower() not in ("0", "nao", "não", "false"),
            idioma=_idioma(_variavel(env, "IDIOMA")),
            cerebro=_cerebro(_variavel(env, "CEREBRO")),
            pasta_documentos=caminho("DOCUMENTOS", pasta_documentos_padrao(env)),
            **opcionais,  # ausentes ficam com o padrão declarado no campo
        )
