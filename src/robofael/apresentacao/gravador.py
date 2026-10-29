"""Tela para registrar a voz do usuário e criar o perfil de tom do assistente.

Uso: `robofael-gravar-voz`. Usa o mesmo microfone com detecção de fala do assistente (com
medidor de nível) e, como a janela principal, só toca no Tk pela thread principal."""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from typing import Any, Literal

from robofael.apresentacao.tema import CARTAO, DESTAQUE, ERRO, FONTE, FUNDO, PRIMARIA, TEXTO, TEXTO_SUAVE
from robofael.audio import perfil as pv
from robofael.audio.analise import analisar_tom, ler_wav
from robofael.bootstrap import criar_captura_audio, falar_amostra
from robofael.configuracao import Configuracao, configurar_logs
from robofael.portas import CapturaAudio

log = logging.getLogger(__name__)

MINIMO_FRASES = 3
TESTE = "Oi! Agora eu falo com um tom parecido com o seu. Vamos organizar o seu dia?"


class Gravador:
    def __init__(self, raiz: tk.Tk, config: Configuracao):
        self.raiz, self.config = raiz, config
        self.indice = 0
        self.gravados = {i: c for i, _ in enumerate(pv.FRASES)
                         if (c := config.pasta_gravacoes / f"frase_{i + 1}.wav").exists()}
        self.ocupado = True
        self.microfone: CapturaAudio | None = None  # criado em segundo plano
        self._nivel = 0.0
        self._fila: queue.SimpleQueue[Callable[[], None]] = queue.SimpleQueue()
        self._cancelar = threading.Event()
        self._montar()
        self._na_ui(lambda: self._status("Preparando o microfone..."))
        self._em_segundo_plano(self._preparar_microfone)
        self._laco()

    # ---------- Layout ----------
    def _montar(self) -> None:
        r = self.raiz
        r.title(f"{self.config.nome_assistente} — registrar minha voz")
        r.configure(bg=FUNDO, padx=24, pady=20)
        r.geometry("940x500")
        tk.Label(r, text="Registrar minha voz", bg=FUNDO, fg=TEXTO, font=(FONTE, 20, "bold")).pack(anchor="w")
        tk.Label(r, text=f"Leia cada frase em voz alta, no seu jeito natural de falar (mínimo {MINIMO_FRASES}). "
                 "A gravação termina sozinha quando você para de falar.", bg=FUNDO, fg=TEXTO_SUAVE,
                 font=(FONTE, 11), wraplength=880, justify="left").pack(anchor="w", pady=(4, 14))

        cartao = tk.Frame(r, bg=CARTAO, padx=20, pady=18)
        cartao.pack(fill="x")
        self.lbl_num = tk.Label(cartao, bg=CARTAO, fg=DESTAQUE, font=(FONTE, 11, "bold"))
        self.lbl_num.pack(anchor="w")
        self.lbl_frase = tk.Label(cartao, bg=CARTAO, fg=TEXTO, font=(FONTE, 17), wraplength=860, justify="left")
        self.lbl_frase.pack(anchor="w", pady=(6, 0))

        self.medidor = tk.Canvas(r, height=10, bg=CARTAO, highlightthickness=0)
        self.medidor.pack(fill="x", pady=(10, 0))
        self.barra_nivel = self.medidor.create_rectangle(0, 0, 0, 10, fill=DESTAQUE, width=0)

        self.lbl_status = tk.Label(r, bg=FUNDO, fg=TEXTO_SUAVE, font=(FONTE, 12), wraplength=880, justify="left")
        self.lbl_status.pack(anchor="w", pady=12)

        botoes = tk.Frame(r, bg=FUNDO)
        botoes.pack(anchor="w")
        estilo: dict[str, Any] = {"relief": "flat", "padx": 16, "pady": 6, "font": (FONTE, 11, "bold"), "fg": "white",
                  "activeforeground": "white", "cursor": "hand2"}
        nav: dict[str, Any] = {"bg": "#2a3550", "activebackground": "#33405f", **estilo}
        self.btn_gravar = tk.Button(botoes, text="● Gravar", bg="#d93f3f", activebackground="#b33",
                                    command=self.gravar, **estilo)
        self.btn_ant = tk.Button(botoes, text="◀ Anterior", command=lambda: self.ir(-1), **nav)
        self.btn_prox = tk.Button(botoes, text="Próxima ▶", command=lambda: self.ir(1), **nav)
        self.btn_criar = tk.Button(botoes, text="✔ Criar meu perfil de voz", bg=PRIMARIA,
                                   activebackground="#1a5fd0", command=self.criar, **estilo)
        self.btn_ouvir = tk.Button(botoes, text="▶ Ouvir o assistente", bg="#178a5a", activebackground="#12704a",
                                   command=self.ouvir_teste, **estilo)
        for i, b in enumerate((self.btn_gravar, self.btn_ant, self.btn_prox, self.btn_criar, self.btn_ouvir)):
            b.pack(side="left", padx=(0 if i == 0 else 8, 0))

        self.lbl_progresso = tk.Label(r, bg=FUNDO, fg="#9fb4c8", font=("Courier", 10), justify="left")
        self.lbl_progresso.pack(anchor="w", pady=(14, 0))
        r.bind("<space>", lambda _e: self.gravar())
        r.bind("<Left>", lambda _e: self.ir(-1))
        r.bind("<Right>", lambda _e: self.ir(1))
        self._atualizar()

    # ---------- Infra de threads ----------
    def _na_ui(self, acao: Callable[[], None]) -> None:
        self._fila.put(acao)

    def _em_segundo_plano(self, trabalho: Callable[[], None]) -> None:
        def executar() -> None:
            try:
                trabalho()
            except Exception as e:
                log.exception("Falha no gravador")
                mensagem = f"Erro: {e}"

                def mostrar_erro() -> None:
                    self._status(mensagem, ERRO)

                self._na_ui(mostrar_erro)
            finally:
                self.ocupado = False
                self._na_ui(self._atualizar)

        self.ocupado = True
        self._atualizar()
        threading.Thread(target=executar, daemon=True).start()

    def _laco(self) -> None:
        while not self._fila.empty():
            self._fila.get()()
        largura = self.medidor.winfo_width()
        self.medidor.coords(self.barra_nivel, 0, 0, largura * self._nivel, 10)
        self._nivel *= 0.85
        self.raiz.after(33, self._laco)

    # ---------- Ações ----------
    def _preparar_microfone(self) -> None:
        self.microfone = criar_captura_audio(self.config, pausa_fim_s=1.0)
        self._na_ui(lambda: self._status("Pronto. Clique em ● Gravar (ou ESPAÇO) e leia a frase."))

    def gravar(self) -> None:
        microfone = self.microfone
        if self.ocupado or microfone is None:
            return
        i = self.indice
        self._status("🔴 Gravando... leia a frase agora.", ERRO)
        self._em_segundo_plano(lambda: self._gravar(microfone, i))

    def _gravar(self, microfone: CapturaAudio, i: int) -> None:
        audio = microfone.capturar(self._cancelar, self._ao_nivel, espera_max_s=8.0)
        if audio is None:
            self._na_ui(lambda: self._status("Não ouvi nada. Clique em ● Gravar e fale a frase.", ERRO))
            return
        self.config.pasta_gravacoes.mkdir(parents=True, exist_ok=True)
        caminho = self.config.pasta_gravacoes / f"frase_{i + 1}.wav"
        caminho.write_bytes(audio.get_wav_data(convert_rate=16000, convert_width=2))
        tom, dur = analisar_tom(*ler_wav(caminho))
        if not tom or dur < 1.0:
            self._na_ui(lambda: self._status(
                "Não deu para medir sua voz nessa gravação. Tente de novo, mais perto do microfone.", ERRO))
            return
        self.gravados[i] = caminho

        def concluido() -> None:
            self._status(f"✔ Gravado ({dur:.1f} s de fala, tom {tom:.0f} Hz).")
            if i == self.indice and i < len(pv.FRASES) - 1:
                self.raiz.after(700, lambda: self.ir(1))

        self._na_ui(concluido)

    def _ao_nivel(self, nivel: float) -> None:
        self._nivel = max(self._nivel, nivel)

    def criar(self) -> None:
        if self.ocupado or len(self.gravados) < MINIMO_FRASES:
            return
        linhas: list[str] = []

        def progresso(texto: str) -> None:
            linhas.append(texto)
            def mostrar() -> None:
                self.lbl_progresso.configure(text="\n".join(linhas[-6:]))

            self._na_ui(mostrar)

        def trabalho() -> None:
            gravacoes = [(self.gravados[i], pv.FRASES[i]) for i in sorted(self.gravados)]
            p = pv.criar_perfil(gravacoes, self.config.arquivo_perfil_voz, progresso=progresso)
            self._na_ui(lambda: self._status(
                f"✔ Perfil salvo! Seu tom: {p['tom_usuario_hz']:.0f} Hz · voz base {p['voz']} · ajuste "
                f"{p['tom']} · ritmo {p['ritmo']}. O {self.config.nome_assistente} vai falar assim "
                "na próxima vez que abrir."))

        self._status("Analisando sua voz e comparando com a voz do assistente (precisa de internet)...")
        self._em_segundo_plano(trabalho)

    def ouvir_teste(self) -> None:
        perfil = pv.carregar_perfil(self.config.arquivo_perfil_voz)
        if self.ocupado or not perfil:
            return

        self._em_segundo_plano(lambda: falar_amostra(TESTE, perfil["voz"], perfil["tom"], perfil["ritmo"]))

    # ---------- Tela ----------
    def ir(self, delta: int) -> None:
        if not self.ocupado:
            self.indice = max(0, min(len(pv.FRASES) - 1, self.indice + delta))
            self._atualizar()

    def _status(self, texto: str, cor: str = TEXTO_SUAVE) -> None:
        self.lbl_status.configure(text=texto, fg=cor)

    def _atualizar(self) -> None:
        feito = "  ✔ gravada" if self.indice in self.gravados else ""
        self.lbl_num.configure(text=f"FRASE {self.indice + 1} DE {len(pv.FRASES)}{feito}   ·   "
                                    f"{len(self.gravados)} gravada(s) — mínimo {MINIMO_FRASES}")
        self.lbl_frase.configure(text=pv.FRASES[self.indice])
        livre: Literal["disabled", "normal"] = "disabled" if self.ocupado else "normal"
        self.btn_gravar.configure(state=livre if self.microfone else "disabled",
                                  text="● Regravar" if self.indice in self.gravados else "● Gravar")
        self.btn_ant.configure(state=livre if self.indice > 0 else "disabled")
        self.btn_prox.configure(state=livre if self.indice < len(pv.FRASES) - 1 else "disabled")
        self.btn_criar.configure(state=livre if len(self.gravados) >= MINIMO_FRASES else "disabled")
        tem_perfil = pv.carregar_perfil(self.config.arquivo_perfil_voz) is not None
        self.btn_ouvir.configure(state=livre if tem_perfil else "disabled")


def main() -> None:
    configurar_logs()
    raiz = tk.Tk(className="robofael")  # WM_CLASS: o Ubuntu associa a janela ao ícone do .desktop
    Gravador(raiz, Configuracao.do_ambiente())
    raiz.mainloop()


if __name__ == "__main__":
    main()
