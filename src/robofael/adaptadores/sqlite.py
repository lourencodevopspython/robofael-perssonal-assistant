"""Memória de longo prazo em SQLite: agenda, histórico auditável e preferências.

Garantias do histórico (tabela `historico`):
- **somente acréscimo**: triggers do próprio banco recusam UPDATE e DELETE;
- **à prova de adulteração**: cada registro guarda o SHA-256 do anterior (cadeia de hashes);
  `verificar_integridade()` recalcula a cadeia e aponta o primeiro registro alterado,
  removido ou inserido por fora do sistema;
- **atômico com o estado**: a alteração da agenda e seus registros são gravados na mesma
  transação — nunca existe tarefa concluída sem o registro de que foi concluída.

O esquema é versionado (`PRAGMA user_version`) e migrado na abertura."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from robofael.dominio.modelos import DadosAgenda, Lembrete, RegistroAuditoria, Tarefa, TipoEvento
from robofael.portas import CopiaVerificada, Preferencias

log = logging.getLogger(__name__)

HASH_INICIAL = "0" * 64
_MIGRACOES = [
    # v1
    """
    CREATE TABLE tarefas (
        id INTEGER PRIMARY KEY,
        texto TEXT NOT NULL,
        criada TEXT NOT NULL,
        feita INTEGER NOT NULL DEFAULT 0 CHECK (feita IN (0, 1)),
        concluida_em TEXT
    );
    CREATE TABLE lembretes (
        id INTEGER PRIMARY KEY,
        texto TEXT NOT NULL,
        quando TEXT NOT NULL,
        avisado INTEGER NOT NULL DEFAULT 0 CHECK (avisado IN (0, 1))
    );
    CREATE TABLE meta (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
    CREATE TABLE preferencias (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
    CREATE TABLE historico (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        ocorrido_em TEXT NOT NULL,
        tipo TEXT NOT NULL,
        entidade TEXT NOT NULL,
        entidade_id INTEGER NOT NULL,
        descricao TEXT NOT NULL,
        dados TEXT NOT NULL DEFAULT '{}',
        hash_anterior TEXT NOT NULL,
        hash TEXT NOT NULL UNIQUE
    );
    CREATE INDEX historico_por_data ON historico (ocorrido_em);
    CREATE TRIGGER historico_sem_alteracao BEFORE UPDATE ON historico
    BEGIN SELECT RAISE(ABORT, 'o histórico é somente acréscimo'); END;
    CREATE TRIGGER historico_sem_remocao BEFORE DELETE ON historico
    BEGIN SELECT RAISE(ABORT, 'o histórico é somente acréscimo'); END;
    """,
    # v2: tarefas e lembretes traduzidos para o idioma da interface (cache: fora da cadeia de hashes)
    """
    CREATE TABLE traducoes (
        texto TEXT NOT NULL,
        idioma TEXT NOT NULL,
        traducao TEXT NOT NULL,
        PRIMARY KEY (texto, idioma)
    );
    """,
]


@dataclass(frozen=True)
class Integridade:
    ok: bool
    registros: int
    primeiro_problema: int | None = None  # seq do primeiro registro inconsistente
    motivo: str = ""


def _hash(anterior: str, ocorrido_em: str, tipo: str, entidade_id: int, descricao: str, dados: str) -> str:
    conteudo = json.dumps([anterior, ocorrido_em, tipo, entidade_id, descricao, dados], ensure_ascii=False)
    return hashlib.sha256(conteudo.encode()).hexdigest()


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


class BancoSqlite:
    def __init__(self, arquivo: Path | str):
        self.arquivo = Path(arquivo) if str(arquivo) != ":memory:" else None
        if self.arquivo:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self._trava = threading.RLock()
        with self._trava:
            self._con = self._conectar(str(arquivo))
            self._migrar()

    def _conectar(self, alvo: str) -> sqlite3.Connection:
        # Uma conexão compartilhada, serializada pela trava (o SQLite não aceita a mesma
        # conexão em threads simultâneas); isolation_level=None: transações explícitas.
        con = sqlite3.connect(alvo, check_same_thread=False, isolation_level=None)
        con.row_factory = sqlite3.Row
        if alvo != ":memory:":
            con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    # ---------- Arquivo: mudar de lugar e backup ----------
    def _copiar(self, destino: Path, modo_diario: str) -> CopiaVerificada:
        """Cópia consistente mesmo com o banco em uso (API de backup do SQLite), conferida em seguida."""
        destino.parent.mkdir(parents=True, exist_ok=True)
        copia = sqlite3.connect(str(destino))
        try:
            with self._trava:
                self._con.backup(copia)
            copia.execute(f"PRAGMA journal_mode={modo_diario}")
            problema = copia.execute("PRAGMA integrity_check").fetchone()[0]
            if problema != "ok":
                raise sqlite3.DatabaseError(f"cópia em {destino} falhou na verificação: {problema}")
            registros = copia.execute("SELECT COUNT(*) FROM historico").fetchone()[0]
        except BaseException:
            copia.close()
            destino.unlink(missing_ok=True)
            raise
        copia.close()
        return CopiaVerificada(destino, registros)

    def copiar_para(self, destino: Path) -> CopiaVerificada:
        """Backup num arquivo único (sem -wal), que abre em qualquer leitor de SQLite.
        Um arquivo que já exista no destino é substituído (a tela de salvar já pergunta)."""
        destino = Path(destino)
        if self.arquivo and destino.resolve() == self.arquivo.resolve():
            raise ValueError("o backup não pode substituir o próprio banco")
        destino.unlink(missing_ok=True)
        resultado = self._copiar(destino, "DELETE")
        log.info("Backup do banco em %s (%d registros no histórico)", destino, resultado.registros)
        return resultado

    def mover_para(self, destino: Path) -> Path:
        """Passa a usar o banco em `destino`. O antigo não é apagado: vira `memoria.db.movido-<data>`
        ao lado de onde estava, para dar para voltar atrás. Devolve onde ele ficou."""
        destino = Path(destino)
        if self.arquivo is None:
            raise ValueError("banco em memória não tem arquivo para mover")
        if destino.exists():
            raise FileExistsError(destino)
        with self._trava:  # nada é gravado no meio da mudança
            self._copiar(destino, "WAL")
            antigo = self.arquivo
            self._con.close()  # fecha o antigo: o SQLite incorpora o -wal e apaga os arquivos auxiliares
            self._con = self._conectar(str(destino))
            self.arquivo = destino
            guardado = antigo.with_name(f"{antigo.name}.movido-{datetime.now():%Y%m%d-%H%M%S}")
            antigo.rename(guardado)
        log.info("Banco movido para %s; o anterior ficou em %s", destino, guardado)
        return guardado

    # ---------- Esquema ----------
    def _migrar(self) -> None:
        versao = self._con.execute("PRAGMA user_version").fetchone()[0]
        for numero, script in enumerate(_MIGRACOES[versao:], start=versao + 1):
            self._con.executescript(f"BEGIN; {script}; PRAGMA user_version = {numero}; COMMIT;")
            log.info("Banco migrado para a versão %d", numero)

    @property
    def versao_esquema(self) -> int:
        with self._trava:
            return self._con.execute("PRAGMA user_version").fetchone()[0]

    # ---------- RepositorioAgenda ----------
    def vazio(self) -> bool:
        with self._trava:
            return self._con.execute("SELECT 1 FROM meta WHERE chave = 'prox_id'").fetchone() is None

    def carregar(self) -> DadosAgenda:
        with self._trava:
            tarefas = [Tarefa(r["id"], r["texto"], datetime.fromisoformat(r["criada"]), bool(r["feita"]),
                              datetime.fromisoformat(r["concluida_em"]) if r["concluida_em"] else None)
                       for r in self._con.execute("SELECT * FROM tarefas ORDER BY id")]
            lembretes = [Lembrete(r["id"], r["texto"], datetime.fromisoformat(r["quando"]), bool(r["avisado"]))
                         for r in self._con.execute("SELECT * FROM lembretes ORDER BY id")]
            linha = self._con.execute("SELECT valor FROM meta WHERE chave = 'prox_id'").fetchone()
        maior = max([t.id for t in tarefas] + [l.id for l in lembretes], default=0)
        return DadosAgenda(tarefas, lembretes, max(int(linha[0]) if linha else 1, maior + 1))

    def salvar(self, dados: DadosAgenda, eventos: Sequence[RegistroAuditoria] = ()) -> None:
        with self._trava, self._transacao() as c:
            c.execute("DELETE FROM tarefas")
            c.executemany("INSERT INTO tarefas VALUES (?, ?, ?, ?, ?)", [
                (t.id, t.texto, _iso(t.criada), int(t.feita), _iso(t.concluida_em) if t.concluida_em else None)
                for t in dados.tarefas])
            c.execute("DELETE FROM lembretes")
            c.executemany("INSERT INTO lembretes VALUES (?, ?, ?, ?)", [
                (l.id, l.texto, _iso(l.quando), int(l.avisado)) for l in dados.lembretes])
            c.execute("INSERT INTO meta VALUES ('prox_id', ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                      (str(dados.prox_id),))
            self._acrescentar(c, eventos)

    def _acrescentar(self, c: sqlite3.Connection, eventos: Iterable[RegistroAuditoria]) -> None:
        linha = c.execute("SELECT hash FROM historico ORDER BY seq DESC LIMIT 1").fetchone()
        anterior = linha[0] if linha else HASH_INICIAL
        for e in eventos:
            quando, dados = _iso(e.ocorrido_em), json.dumps(e.dados, ensure_ascii=False, sort_keys=True)
            atual = _hash(anterior, quando, e.tipo.value, e.entidade_id, e.descricao, dados)
            c.execute("INSERT INTO historico (ocorrido_em, tipo, entidade, entidade_id, descricao, dados, "
                      "hash_anterior, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                      (quando, e.tipo.value, e.tipo.entidade, e.entidade_id, e.descricao, dados, anterior, atual))
            anterior = atual

    # ---------- ConsultaHistorico ----------
    def eventos(self, inicio: datetime, fim: datetime,
                tipos: Iterable[TipoEvento] | None = None) -> list[RegistroAuditoria]:
        sql = "SELECT * FROM historico WHERE ocorrido_em >= ? AND ocorrido_em < ?"
        parametros: list = [_iso(inicio), _iso(fim)]
        if tipos is not None:
            tipos = list(tipos)
            sql += f" AND tipo IN ({','.join('?' * len(tipos))})"
            parametros += [t.value for t in tipos]
        with self._trava:
            linhas = self._con.execute(sql + " ORDER BY ocorrido_em, seq", parametros).fetchall()
        return [RegistroAuditoria(TipoEvento(r["tipo"]), r["entidade_id"], r["descricao"],
                                  datetime.fromisoformat(r["ocorrido_em"]), json.loads(r["dados"])) for r in linhas]

    def total_eventos(self) -> int:
        with self._trava:
            return self._con.execute("SELECT COUNT(*) FROM historico").fetchone()[0]

    def verificar_integridade(self) -> Integridade:
        """Recalcula a cadeia de hashes do histórico inteiro."""
        with self._trava:
            linhas = self._con.execute("SELECT * FROM historico ORDER BY seq").fetchall()
        anterior, seq_esperado = HASH_INICIAL, None
        for r in linhas:
            if seq_esperado is not None and r["seq"] != seq_esperado:
                return Integridade(False, len(linhas), r["seq"], "registro removido antes deste")
            if r["hash_anterior"] != anterior:
                return Integridade(False, len(linhas), r["seq"], "encadeamento quebrado")
            if _hash(anterior, r["ocorrido_em"], r["tipo"], r["entidade_id"], r["descricao"], r["dados"]) != r["hash"]:
                return Integridade(False, len(linhas), r["seq"], "conteúdo alterado")
            anterior, seq_esperado = r["hash"], r["seq"] + 1
        return Integridade(True, len(linhas))

    # ---------- Preferências ----------
    def carregar_preferencias(self) -> Preferencias:
        with self._trava:
            valores = {r["chave"]: json.loads(r["valor"]) for r in self._con.execute("SELECT * FROM preferencias")}
        campos = Preferencias.__dataclass_fields__
        return Preferencias(**{k: v for k, v in valores.items() if k in campos})

    def salvar_preferencias(self, preferencias: Preferencias) -> None:
        with self._trava, self._transacao() as c:
            for chave, valor in asdict(preferencias).items():
                if valor is None:
                    c.execute("DELETE FROM preferencias WHERE chave = ?", (chave,))
                else:
                    c.execute("INSERT INTO preferencias VALUES (?, ?) "
                              "ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                              (chave, json.dumps(valor, ensure_ascii=False)))

    # ---------- Traduções ----------
    def traducoes(self, idioma: str) -> dict[str, str]:
        with self._trava:
            return {r["texto"]: r["traducao"]
                    for r in self._con.execute("SELECT texto, traducao FROM traducoes WHERE idioma = ?", (idioma,))}

    def guardar_traducoes(self, idioma: str, traducoes: dict[str, str]) -> None:
        with self._trava, self._transacao() as c:
            c.executemany("INSERT INTO traducoes VALUES (?, ?, ?) "
                          "ON CONFLICT(texto, idioma) DO UPDATE SET traducao = excluded.traducao",
                          [(texto, idioma, traducao) for texto, traducao in traducoes.items()])

    # ---------- Migração do JSON antigo ----------
    def importar_json(self, arquivo_json: Path, agora: datetime | None = None) -> bool:
        """Traz a agenda do `agenda.json` (versões anteriores) para o banco, uma única vez.
        Gera o histórico possível: criação de cada tarefa (com a data original) e conclusões
        com data conhecida. O JSON é renomeado para `.migrado` (nada é apagado)."""
        arquivo_json = Path(arquivo_json)
        if not arquivo_json.exists() or not self.vazio():
            return False
        from robofael.adaptadores.repositorio_json import RepositorioJson

        dados = RepositorioJson(arquivo_json).carregar()
        agora = agora or datetime.now()
        eventos: list[RegistroAuditoria] = []
        for t in dados.tarefas:
            eventos.append(RegistroAuditoria(TipoEvento.TAREFA_CRIADA, t.id, t.texto, t.criada, {"importado": True}))
            if t.feita and t.concluida_em:
                eventos.append(RegistroAuditoria(TipoEvento.TAREFA_CONCLUIDA, t.id, t.texto, t.concluida_em,
                                                 {"importado": True}))
        for l in dados.lembretes:
            eventos.append(RegistroAuditoria(TipoEvento.LEMBRETE_CRIADO, l.id, l.texto, agora,
                                             {"importado": True, "quando": l.quando.isoformat(timespec="minutes")}))
        eventos.sort(key=lambda e: e.ocorrido_em)
        self.salvar(dados, eventos)
        destino = arquivo_json.with_name(f"{arquivo_json.name}.migrado-{agora:%Y%m%d-%H%M%S}")
        arquivo_json.rename(destino)
        log.info("Agenda migrada do JSON para o SQLite (%d tarefas, %d lembretes); original em %s",
                 len(dados.tarefas), len(dados.lembretes), destino.name)
        return True

    # ---------- Infra ----------
    @contextmanager
    def _transacao(self) -> Iterator[sqlite3.Connection]:
        self._con.execute("BEGIN IMMEDIATE")
        try:
            yield self._con
        except BaseException:
            self._con.execute("ROLLBACK")
            raise
        self._con.execute("COMMIT")

    def fechar(self) -> None:
        with self._trava:
            self._con.close()
