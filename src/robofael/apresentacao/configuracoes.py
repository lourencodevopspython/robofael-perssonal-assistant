"""Tela de configurações: idioma, avatar, voz (voz base, tom e ritmo), microfone, ativação por
voz, inicialização (abrir ao entrar no computador e o comando no terminal), o modelo de linguagem
em uso (com os modelos compatíveis do Claude e do Ollama) e onde fica o banco (mudar e backup).

"Ouvir" aplica a voz na hora para você testar; "Cancelar" desfaz; "Salvar" grava as
preferências na memória (SQLite) e elas valem também nas próximas vezes. Trocar o idioma
troca a lista de vozes para as daquele idioma."""

from __future__ import annotations

import re
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk

from robofael.aplicacao.sessao import CerebroEmUso, ModelosDoProvedor
from robofael.apresentacao.tema import (
    CARTAO,
    DESTAQUE,
    ERRO,
    FONTE,
    FUNDO,
    PRIMARIA,
    SUPERFICIE,
    TEXTO,
    TEXTO_SUAVE,
)
from robofael.i18n import CATALOGO, Idioma, Tradutor
from robofael.i18n import VOZES as VOZES_POR_IDIOMA
from robofael.portas import EstadoInicializacao, Microfone

VOZES = {voz: rotulo for vozes in VOZES_POR_IDIOMA.values() for voz, rotulo in vozes.items()}
LIMITE_TOM_HZ = 50
LIMITE_RITMO_PCT = 30
FRASE_TESTE = Tradutor()("cfg.frase_teste")  # em português (o teste usa o idioma escolhido)
MAX_ROTULO_MICROFONE = 40


@dataclass(frozen=True)
class AjustesVoz:
    avatar: str
    voz: str
    tom_hz: int
    ritmo_pct: int
    ativacao_por_voz: bool
    idioma: str = Idioma.PT_BR.value
    microfone: str | None = None  # None = o padrão do sistema
    abrir_ao_entrar: bool = False
    comando_no_terminal: bool = False

    @property
    def tom(self) -> str:
        return formatar_hz(self.tom_hz)

    @property
    def ritmo(self) -> str:
        return formatar_pct(self.ritmo_pct)


@dataclass(frozen=True)
class OpcoesConfiguracoes:
    """O que a tela oferece: avatares, o perfil gravado da sua voz e se há ativação por voz."""

    avatares: list[str]
    perfil: dict | None
    ativacao_disponivel: bool
    frase_ativacao: str
    microfones: list[Microfone] = field(default_factory=list)
    inicializacao: EstadoInicializacao | None = None  # None: o sistema não oferece
    cerebro: CerebroEmUso | None = None  # None: os serviços ainda estão iniciando
    listar_modelos: Callable[[], list[ModelosDoProvedor]] | None = None  # lento (rede): roda numa thread
    local_banco: Callable[[], Path | None] = lambda: None  # onde o banco está agora


@dataclass(frozen=True)
class AcoesConfiguracoes:
    """O que acontece nos botões. A tela só coleta os ajustes; quem os aplica é a aplicação."""

    salvar: Callable[[AjustesVoz], None]
    ouvir: Callable[[AjustesVoz], None]  # testa a voz sem salvar
    cancelar: Callable[[AjustesVoz], None]  # recebe os ajustes iniciais, para desfazer o teste
    # Banco: valem na hora (não esperam o Salvar). Devolvem (deu certo, mensagem para mostrar).
    mover_banco: Callable[[Path], tuple[bool, str]] | None = None
    fazer_backup: Callable[[Path], tuple[bool, str]] | None = None


def ler_numero(texto: str | None) -> int:
    """'+12Hz' -> 12, '-26%' -> -26, None/inválido -> 0."""
    m = re.match(r"^\s*([+-]?\d+)", texto or "")
    return int(m[1]) if m else 0


def formatar_hz(valor: int) -> str:
    return f"{max(-LIMITE_TOM_HZ, min(LIMITE_TOM_HZ, int(valor))):+d}Hz"


def formatar_pct(valor: int) -> str:
    return f"{max(-LIMITE_RITMO_PCT, min(LIMITE_RITMO_PCT, int(valor))):+d}%"


def encurtar(nome: str, limite: int = MAX_ROTULO_MICROFONE) -> str:
    """Nomes de placas de som são longos e o que distingue fica no fim
    ("Tiger Lake-LP ... Controller Digital Microphone"): corta o começo, numa palavra inteira."""
    if len(nome) <= limite:
        return nome
    fim = nome[-(limite - 1):]
    return "…" + (fim.split(" ", 1)[1] if " " in fim else fim)


def rotulos_microfones(microfones: list[Microfone], escolhido: str | None, tr: Tradutor) -> dict[str, str | None]:
    """Rótulo na tela -> id do microfone, começando pelo padrão do sistema. O escolhido aparece
    mesmo desconectado (para não trocar de microfone sem o usuário pedir)."""
    rotulos: dict[str, str | None] = {tr("cfg.microfone_padrao"): None}
    ids = {m.id for m in microfones}
    if escolhido and escolhido not in ids:
        microfones = [*microfones, Microfone(escolhido, tr("cfg.microfone_desconectado", nome=escolhido))]
    for m in microfones:
        rotulo, n = encurtar(m.nome), 2
        while rotulo in rotulos:  # dois aparelhos iguais
            rotulo, n = f"{encurtar(m.nome, MAX_ROTULO_MICROFONE - 4)} ({n})", n + 1
        rotulos[rotulo] = m.id
    return rotulos


class JanelaConfiguracoes(tk.Toplevel):
    def __init__(self, mestre: tk.Misc, inicial: AjustesVoz, opcoes: OpcoesConfiguracoes,
                 acoes: AcoesConfiguracoes, tradutor: Tradutor | None = None):
        super().__init__(mestre, bg=FUNDO, padx=22, pady=18)
        self.inicial, self.perfil, self.opcoes = inicial, opcoes.perfil, opcoes
        self._modelos: list[ModelosDoProvedor] | None = None  # preenchido pela thread de consulta
        self._espera_modelos: str | None = None
        self.tr = tradutor or Tradutor()
        self.acoes = acoes
        self.title(self.tr("cfg.titulo"))
        self.resizable(False, False)
        self.transient(mestre)  # type: ignore[call-overload]
        self.protocol("WM_DELETE_WINDOW", self.cancelar)
        self.bind("<Escape>", lambda _e: self.cancelar())

        self.var_idioma = tk.StringVar(value=Idioma.de_texto(inicial.idioma).nome)
        self.var_avatar = tk.StringVar(value=inicial.avatar)
        self.var_voz = tk.StringVar(value=VOZES.get(inicial.voz, inicial.voz))
        self.var_tom = tk.IntVar(value=inicial.tom_hz)
        self.var_ritmo = tk.IntVar(value=inicial.ritmo_pct)
        self.var_ativacao = tk.BooleanVar(value=inicial.ativacao_por_voz)
        self.microfones = rotulos_microfones(opcoes.microfones, inicial.microfone, self.tr)
        self.var_microfone = tk.StringVar(value=next(r for r, i in self.microfones.items() if i == inicial.microfone))
        self.var_abrir_ao_entrar = tk.BooleanVar(value=inicial.abrir_ao_entrar)
        self.var_comando = tk.BooleanVar(value=inicial.comando_no_terminal)
        self._montar(opcoes)
        self.update_idletasks()
        x = mestre.winfo_rootx() + (mestre.winfo_width() - self.winfo_width()) // 2
        y = mestre.winfo_rooty() + (mestre.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self._tornar_modal()

    def _tornar_modal(self, tentativas: int = 20) -> None:
        """grab_set falha se a janela ainda não apareceu na tela: tenta de novo em seguida."""
        try:
            self.grab_set()
        except tk.TclError:
            if tentativas > 0 and self.winfo_exists():
                self.after(50, self._tornar_modal, tentativas - 1)

    # ---------- Layout ----------
    @staticmethod
    def _titulo(mestre: tk.Misc, texto: str) -> None:
        tk.Label(mestre, text=texto, bg=FUNDO, fg=DESTAQUE, font=(FONTE, 11, "bold"), anchor="w").pack(
            fill="x", pady=(12, 4))

    @staticmethod
    def _dica(mestre: tk.Misc, texto: str, largura: int = 0) -> None:
        tk.Label(mestre, text=texto, bg=FUNDO, fg=TEXTO_SUAVE, font=(FONTE, 9), anchor="w", justify="left",
                 wraplength=largura).pack(fill="x")

    @staticmethod
    def _combo(mestre: tk.Misc, variavel: tk.StringVar, valores: list[str], largura: int = 30) -> ttk.Combobox:
        combo = ttk.Combobox(mestre, textvariable=variavel, values=valores, state="readonly",
                             style="Robofael.TCombobox", font=(FONTE, 11), width=largura)
        combo.pack(anchor="w")
        return combo

    @staticmethod
    def _caixa(mestre: tk.Misc, texto: str, variavel: tk.BooleanVar) -> tk.Checkbutton:
        caixa = tk.Checkbutton(mestre, text=texto, variable=variavel, bg=FUNDO, fg=TEXTO, selectcolor=CARTAO,
                               activebackground=FUNDO, activeforeground=TEXTO, font=(FONTE, 11), anchor="w")
        caixa.pack(fill="x")
        return caixa

    def _montar(self, opcoes: OpcoesConfiguracoes) -> None:
        tk.Label(self, text=self.tr("cfg.titulo"), bg=FUNDO, fg=TEXTO, font=(FONTE, 18, "bold"),
                 anchor="w").pack(fill="x")
        estilo = ttk.Style(self)
        estilo.configure("Robofael.TCombobox", fieldbackground=CARTAO, background=SUPERFICIE, foreground=TEXTO)
        # "readonly" tem cores próprias no tema padrão (texto claro sobre cinza-claro, ilegível)
        estilo.map("Robofael.TCombobox", fieldbackground=[("readonly", CARTAO)], foreground=[("readonly", TEXTO)],
                   selectbackground=[("readonly", CARTAO)], selectforeground=[("readonly", TEXTO)])
        colunas = tk.Frame(self, bg=FUNDO)
        colunas.pack(fill="x")
        esquerda, direita = tk.Frame(colunas, bg=FUNDO), tk.Frame(colunas, bg=FUNDO)
        esquerda.pack(side="left", anchor="n")
        direita.pack(side="left", anchor="n", padx=(28, 0))
        self._montar_idioma_avatar_voz(esquerda, opcoes.avatares)
        self._montar_microfone_ativacao(direita, opcoes.ativacao_disponivel, opcoes.frase_ativacao)
        if opcoes.inicializacao is not None:
            self._montar_inicializacao(direita, opcoes.inicializacao)

        self._montar_cerebro(esquerda)
        self._montar_memoria(direita)

        rodape = tk.Frame(self, bg=FUNDO)
        rodape.pack(fill="x", pady=(18, 0))
        self._botao(rodape, self.tr("cfg.salvar"), self.salvar, PRIMARIA).pack(side="right")
        self._botao(rodape, self.tr("cfg.cancelar"), self.cancelar, "#2a3550").pack(side="right", padx=(0, 8))

    def _montar_idioma_avatar_voz(self, coluna: tk.Frame, avatares: list[str]) -> None:
        tr = self.tr
        self._titulo(coluna, tr("cfg.idioma"))
        self.combo_idioma = self._combo(coluna, self.var_idioma, [i.nome for i in Idioma])
        self.combo_idioma.bind("<<ComboboxSelected>>", lambda _e: self._ao_trocar_idioma())

        self._titulo(coluna, tr("cfg.avatar"))
        linha = tk.Frame(coluna, bg=FUNDO)
        linha.pack(fill="x")
        for nome in avatares:
            rotulo = tr(f"cfg.avatar.{nome}") if f"cfg.avatar.{nome}" in CATALOGO else nome.capitalize()
            tk.Radiobutton(linha, text=rotulo, value=nome, variable=self.var_avatar, bg=FUNDO, fg=TEXTO,
                           selectcolor=CARTAO, activebackground=FUNDO, activeforeground=TEXTO,
                           font=(FONTE, 11)).pack(side="left", padx=(0, 16))

        self._titulo(coluna, tr("cfg.voz"))
        self.combo_voz = self._combo(coluna, self.var_voz, list(VOZES_POR_IDIOMA[self.idioma_escolhido].values()))
        for rotulo, variavel, limite in ((tr("cfg.tom"), self.var_tom, LIMITE_TOM_HZ),
                                         (tr("cfg.ritmo"), self.var_ritmo, LIMITE_RITMO_PCT)):
            quadro = tk.Frame(coluna, bg=FUNDO)
            quadro.pack(fill="x", pady=(6, 0))
            tk.Label(quadro, text=rotulo, bg=FUNDO, fg=TEXTO_SUAVE, width=10, anchor="w",
                     font=(FONTE, 10)).pack(side="left")
            tk.Scale(quadro, from_=-limite, to=limite, orient="horizontal", variable=variavel, length=300,
                     bg=FUNDO, fg=TEXTO, troughcolor=CARTAO, highlightthickness=0, activebackground=DESTAQUE,
                     font=(FONTE, 9)).pack(side="left")
        botoes_voz = tk.Frame(coluna, bg=FUNDO)
        botoes_voz.pack(fill="x", pady=(8, 0))
        self._botao(botoes_voz, tr("cfg.ouvir"), self.ouvir, "#178a5a").pack(side="left")
        self.botao_perfil = self._botao(botoes_voz, tr("cfg.perfil"), self.usar_perfil, "#2a3550")
        self.botao_perfil.pack(side="left", padx=(8, 0))
        if not self.perfil:
            self.botao_perfil.configure(state="disabled")

    def _montar_microfone_ativacao(self, coluna: tk.Frame, ativacao_disponivel: bool, frase: str) -> None:
        tr = self.tr
        self._titulo(coluna, tr("cfg.microfone"))
        self.combo_microfone = self._combo(coluna, self.var_microfone, list(self.microfones),
                                           largura=MAX_ROTULO_MICROFONE)
        self._dica(coluna, tr("cfg.microfone_dica"))

        self._titulo(coluna, tr("cfg.ativacao"))
        self.check_ativacao = self._caixa(coluna, tr("cfg.ativacao_texto", frase=frase), self.var_ativacao)
        if not ativacao_disponivel:
            self.check_ativacao.configure(state="disabled")
            self._dica(coluna, tr("cfg.ativacao_indisponivel"))

    def _montar_inicializacao(self, coluna: tk.Frame, estado: EstadoInicializacao) -> None:
        tr = self.tr
        self._titulo(coluna, tr("cfg.inicializacao"))
        self.check_abrir_ao_entrar = self._caixa(coluna, tr("cfg.abrir_ao_entrar"), self.var_abrir_ao_entrar)
        self.check_comando = self._caixa(coluna, tr("cfg.comando_terminal"), self.var_comando)
        if estado.comando_do_sistema:
            self.check_comando.configure(state="disabled")
            self._dica(coluna, tr("cfg.comando_do_sistema"))
        else:
            self._dica(coluna, tr("cfg.comando_dica"))

    LARGURA_TEXTO = 380  # px: quebra de linha dos textos longos (cabe na coluna)

    def _montar_cerebro(self, coluna: tk.Frame) -> None:
        tr, cerebro = self.tr, self.opcoes.cerebro
        self._titulo(coluna, tr("cfg.cerebro"))
        em_uso = tr("cfg.cerebro_iniciando") if cerebro is None else tr("cfg.cerebro_em_uso", nome=" · ".join(
            filter(None, (tr(f"cerebro.{cerebro.provedor}"), cerebro.modelo))))
        self.lbl_cerebro = tk.Label(coluna, text=em_uso, bg=FUNDO, fg=TEXTO, font=(FONTE, 11), anchor="w",
                                    justify="left", wraplength=self.LARGURA_TEXTO)
        self.lbl_cerebro.pack(fill="x")
        tk.Label(coluna, text=tr("cfg.modelos_compativeis"), bg=FUNDO, fg=TEXTO_SUAVE, font=(FONTE, 10),
                 anchor="w").pack(fill="x", pady=(6, 0))
        self.lbl_modelos = tk.Label(coluna, text=tr("cfg.modelos_procurando"), bg=FUNDO, fg=TEXTO,
                                    font=(FONTE, 10), anchor="w", justify="left", wraplength=self.LARGURA_TEXTO)
        self.lbl_modelos.pack(fill="x")
        self._dica(coluna, tr("cfg.cerebro_dica"), self.LARGURA_TEXTO)
        if self.opcoes.listar_modelos is not None:
            listar = self.opcoes.listar_modelos
            threading.Thread(target=lambda: setattr(self, "_modelos", listar()), name="listar-modelos",
                             daemon=True).start()
            self._espera_modelos = self.after(100, self._mostrar_modelos)
        else:
            self.lbl_modelos.configure(text="—")

    def _mostrar_modelos(self) -> None:
        """Consulta lenta (rede): a thread só calcula; quem mexe nos widgets é a thread da interface."""
        if self._modelos is None:
            self._espera_modelos = self.after(100, self._mostrar_modelos)
            return
        self._espera_modelos = None
        self.lbl_modelos.configure(text=texto_modelos(self._modelos, self.opcoes.cerebro, self.tr))

    def _montar_memoria(self, coluna: tk.Frame) -> None:
        tr = self.tr
        self._titulo(coluna, tr("cfg.memoria"))
        self.lbl_banco = tk.Label(coluna, bg=FUNDO, fg=TEXTO, font=(FONTE, 10), anchor="w", justify="left",
                                  wraplength=self.LARGURA_TEXTO)
        self.lbl_banco.pack(fill="x")
        self._atualizar_local_banco()
        botoes = tk.Frame(coluna, bg=FUNDO)
        botoes.pack(fill="x", pady=(8, 0))
        self.botao_mover = self._botao(botoes, tr("cfg.mudar_local"), self.escolher_local_banco, "#2a3550")
        self.botao_mover.pack(side="left")
        self.botao_backup = self._botao(botoes, tr("cfg.fazer_backup"), self.escolher_backup, "#2a3550")
        self.botao_backup.pack(side="left", padx=(8, 0))
        sem_arquivo = self.opcoes.local_banco() is None
        if self.acoes.mover_banco is None or sem_arquivo:
            self.botao_mover.configure(state="disabled")
        if self.acoes.fazer_backup is None or sem_arquivo:
            self.botao_backup.configure(state="disabled")
        self._dica(coluna, tr("cfg.banco_dica"), self.LARGURA_TEXTO)
        self.lbl_resultado_banco = tk.Label(coluna, text="", bg=FUNDO, fg=TEXTO_SUAVE, font=(FONTE, 9),
                                            anchor="w", justify="left", wraplength=self.LARGURA_TEXTO)
        self.lbl_resultado_banco.pack(fill="x", pady=(4, 0))

    def _atualizar_local_banco(self) -> None:
        local = self.opcoes.local_banco()
        self.lbl_banco.configure(text=str(local) if local else self.tr("cfg.banco_em_memoria"))

    def mover_banco(self, pasta: Path) -> None:
        if self.acoes.mover_banco is not None:
            self._resultado_banco(*self.acoes.mover_banco(pasta))
            self._atualizar_local_banco()

    def fazer_backup(self, destino: Path) -> None:
        if self.acoes.fazer_backup is not None:
            self._resultado_banco(*self.acoes.fazer_backup(destino))

    def _resultado_banco(self, ok: bool, mensagem: str) -> None:
        self.lbl_resultado_banco.configure(text=mensagem, fg=TEXTO_SUAVE if ok else ERRO)

    def escolher_local_banco(self) -> None:
        local = self.opcoes.local_banco()
        pasta = filedialog.askdirectory(parent=self, title=self.tr("cfg.escolher_pasta_banco"), mustexist=False,
                                        initialdir=str(local.parent) if local else None)
        if pasta:
            self.mover_banco(Path(pasta))

    def escolher_backup(self) -> None:
        destino = filedialog.asksaveasfilename(
            parent=self, title=self.tr("cfg.salvar_backup"), defaultextension=".db",
            initialfile=f"robofael-memoria-{datetime.now():%Y-%m-%d-%H%M}.db",
            filetypes=[("SQLite", "*.db"), ("*", "*")])
        if destino:
            self.fazer_backup(Path(destino))

    @staticmethod
    def _botao(mestre: tk.Misc, texto: str, comando: Callable[[], None], cor: str) -> tk.Button:
        return tk.Button(mestre, text=texto, command=comando, bg=cor, fg="white", activebackground=cor,
                         activeforeground="white", relief="flat", padx=14, pady=5, font=(FONTE, 10, "bold"),
                         cursor="hand2")

    # ---------- Ações ----------
    @property
    def idioma_escolhido(self) -> Idioma:
        return next((i for i in Idioma if i.nome == self.var_idioma.get()), Idioma.PT_BR)

    def _ao_trocar_idioma(self) -> None:
        """A lista de vozes passa a ser a do idioma; se a voz atual não serve, usa a padrão dele."""
        idioma = self.idioma_escolhido
        rotulos = VOZES_POR_IDIOMA[idioma]
        self.combo_voz.configure(values=list(rotulos.values()))
        if self.var_voz.get() not in rotulos.values():
            self.var_voz.set(rotulos[idioma.voz_padrao])

    def ajustes(self) -> AjustesVoz:
        rotulo = self.var_voz.get()
        voz = next((k for k, v in VOZES.items() if v == rotulo), rotulo)
        return AjustesVoz(self.var_avatar.get(), voz, int(self.var_tom.get()), int(self.var_ritmo.get()),
                          bool(self.var_ativacao.get()), self.idioma_escolhido.value,
                          self.microfones.get(self.var_microfone.get()), bool(self.var_abrir_ao_entrar.get()),
                          bool(self.var_comando.get()))

    def usar_perfil(self) -> None:
        if self.perfil:
            voz = self.perfil.get("voz", "")
            if voz.startswith(self.idioma_escolhido.value):  # o perfil foi gravado para uma voz em português
                self.var_voz.set(VOZES.get(voz, voz))
            self.var_tom.set(ler_numero(self.perfil.get("tom")))
            self.var_ritmo.set(ler_numero(self.perfil.get("ritmo")))

    def ouvir(self) -> None:
        self.acoes.ouvir(self.ajustes())

    def salvar(self) -> None:
        self.acoes.salvar(self.ajustes())
        self.destroy()

    def cancelar(self) -> None:
        self.acoes.cancelar(self.inicial)
        self.destroy()

    def destroy(self) -> None:
        if self._espera_modelos is not None:
            self.after_cancel(self._espera_modelos)
            self._espera_modelos = None
        super().destroy()
        # Variáveis Tk só podem ser destruídas na thread principal: libera aqui, em vez de
        # deixar o coletor de lixo fazer isso depois numa thread qualquer
        for nome in ("var_idioma", "var_avatar", "var_voz", "var_tom", "var_ritmo", "var_ativacao", "var_microfone",
                     "var_abrir_ao_entrar", "var_comando"):
            self.__dict__.pop(nome, None)


def texto_modelos(resultados: list[ModelosDoProvedor], em_uso: CerebroEmUso | None, tr: Tradutor) -> str:
    """Uma linha por provedor: "Ollama (local): llama3.2:3b (3.2B, em uso), llama3.1 (8.0B)"."""
    linhas = []
    for r in resultados:
        if r.erro is not None:
            descricao = tr(r.erro.chave, **r.erro.campos)
        elif not r.modelos:
            descricao = tr("cfg.modelos_nenhum")
        else:
            nomes = []
            for m in r.modelos:
                usado = em_uso is not None and em_uso.provedor == r.provedor and em_uso.modelo == m.nome
                extras = ", ".join(filter(None, (m.detalhe, tr("cfg.modelo_em_uso") if usado else "")))
                nomes.append(f"{m.nome} ({extras})" if extras else m.nome)
            descricao = ", ".join(nomes)
        linhas.append(f"• {tr(f'cerebro.{r.provedor}')}: {descricao}")
    return "\n".join(linhas) or "—"


def ajustes_iniciais(avatar: str, voz: str, tom: str, ritmo: str, ativacao: bool,
                     idioma: str = Idioma.PT_BR.value, microfone: str | None = None,
                     inicializacao: EstadoInicializacao | None = None) -> AjustesVoz:
    ini = inicializacao or EstadoInicializacao(False, False)
    return AjustesVoz(avatar, voz, ler_numero(tom), ler_numero(ritmo), ativacao, idioma, microfone,
                      ini.abrir_ao_entrar, ini.comando_no_terminal)
