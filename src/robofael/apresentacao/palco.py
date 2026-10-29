"""Palco do avatar: busto animado, halo, anéis, barras de áudio, status e legendas.

Tudo é desenhado num Canvas e atualizado por `quadro(dt)`. As cores mudam suavemente entre os
estados (interpolação), a boca segue o áudio e as barras mostram o nível real do microfone.

Desempenho: as atualizações passam por uma `CenaCanvas`, que só envia ao Tk o que mudou; o halo
é opaco (o Tk não precisa misturar transparência); e `fps_desejado` informa ao laço de quadros
quando dá para desacelerar (assistente parado, sem transição de cor em andamento)."""

from __future__ import annotations

import math
import tkinter as tk

from PIL import ImageTk

from robofael.apresentacao.cena import CenaCanvas
from robofael.apresentacao.tema import (
    CHAVES_ESTADO,
    CORES,
    FONTE,
    FUNDO,
    NIVEIS_HALO,
    TEXTO,
    TEXTO_SUAVE,
    Cor,
    aproximar,
    hex_para_rgb,
    misturar,
    rgb_para_hex,
)
from robofael.avatar.animacao import NEUTRA, SeletorForma, nivel_boca, suavizar_boca
from robofael.dominio.estados import Estado
from robofael.i18n import Tradutor

RAIO_ANEL = 214
N_BARRAS = 28
LIMITE_LEGENDA = 210  # caracteres visíveis da resposta (mostra o final, que é o que está sendo dito)
FPS_ATIVO, FPS_REPOUSO = 60, 30
ESTADOS_ATIVOS = frozenset({Estado.OUVINDO, Estado.PENSANDO, Estado.FALANDO})
TOLERANCIA_COR = 0.5  # diferença (0..255) abaixo da qual a transição de cor terminou

VELOCIDADE_ARCOS = {Estado.INICIANDO: 160, Estado.PARADO: 20, Estado.OUVINDO: 90,
                    Estado.PENSANDO: 220, Estado.FALANDO: 60}  # graus por segundo


class Palco:
    def __init__(self, canvas: tk.Canvas, centro: tuple[int, int], largura: int, titulo: str = "Robofael",
                 tradutor: Tradutor | None = None):
        self.cv = canvas
        self.cena = CenaCanvas(canvas)
        self.cx, self.cy = centro
        self.largura = largura
        self.estado = Estado.INICIANDO
        self.cor: Cor = hex_para_rgb(CORES[self.estado])
        self.boca = 0.0
        self.mic = 0.0
        self.seletor = SeletorForma()
        self.quadros: list[list[ImageTk.PhotoImage]] | None = None
        self.halos: dict[Estado, list[ImageTk.PhotoImage]] = {}  # chegam aos poucos (ver Janela)
        self.centro_avatar = (0.0, 0.0)
        self.t = 0.0
        self.titulo = titulo
        self.tr = tradutor or Tradutor()
        self.frase_ativacao: str | None = None
        self._status_temporario: tuple[str, str, float] | None = None
        self._montar()

    def _montar(self) -> None:
        cv, cx, cy = self.cv, self.cx, self.cy
        self.item_halo = cv.create_image(cx, cy, state="hidden")
        self.anel = cv.create_oval(cx - RAIO_ANEL, cy - RAIO_ANEL, cx + RAIO_ANEL, cy + RAIO_ANEL, width=2)
        self.arcos = []
        for k in range(3):
            r = 228 + k * 14
            self.arcos.append(cv.create_arc(cx - r, cy - r, cx + r, cy + r, style="arc", width=3, extent=40 + k * 25))
        self.item_avatar = cv.create_image(cx, cy, anchor="nw")
        self.txt_carregando = cv.create_text(cx, cy, text=self.tr("ui.preparando_avatar"), fill=TEXTO_SUAVE,
                                             font=(FONTE, 13))
        self.barras = [cv.create_rectangle(0, 0, 0, 0, width=0) for _ in range(N_BARRAS)]
        cv.create_text(cx, 28, text=self.titulo, fill=TEXTO, font=(FONTE, 22, "bold"))
        self.txt_status = cv.create_text(cx, 58, text=self.rotulo(self.estado), font=(FONTE, 12))
        largura_texto = self.largura - 60
        self.txt_usuario = cv.create_text(cx, 636, text="", fill="#9fb4c8", width=largura_texto,
                                          font=(FONTE, 12, "italic"))
        self.txt_robo = cv.create_text(cx, 664, text="", fill="#ffffff", width=largura_texto,
                                       font=(FONTE, 14), anchor="n")

    # ---------- Entradas ----------
    def definir_avatar(self, quadros: list[list[ImageTk.PhotoImage]], centro: tuple[float, float]) -> None:
        self.quadros, self.centro_avatar = quadros, centro
        self.cena.configurar(self.txt_carregando, state="hidden")

    def definir_halos(self, estado: Estado, imagens: list[ImageTk.PhotoImage]) -> None:
        self.halos[estado] = imagens

    def definir_estado(self, estado: Estado) -> None:
        self.estado = estado
        if estado is not Estado.OUVINDO:
            self.mic = 0.0

    def definir_nivel_microfone(self, nivel: float) -> None:
        self.mic += (nivel - self.mic) * 0.5

    def legenda_usuario(self, texto: str) -> None:
        self.cena.configurar(self.txt_usuario, text=self.tr("ui.voce", texto=texto) if texto else "")

    def legenda_robo(self, texto: str) -> None:
        if len(texto) > LIMITE_LEGENDA:
            texto = "…" + texto[-LIMITE_LEGENDA:].split(" ", 1)[-1]
        self.cena.configurar(self.txt_robo, text=texto)

    def definir_frase_ativacao(self, frase: str | None) -> None:
        """Em repouso, ensina como chamar o assistente."""
        self.frase_ativacao = frase

    def rotulo(self, estado: Estado) -> str:
        if estado is Estado.PARADO and self.frase_ativacao:
            return self.tr("estado.parado_ativacao", frase=self.frase_ativacao)
        return self.tr(CHAVES_ESTADO[estado])

    def traduzir(self) -> None:
        self.cena.configurar(self.txt_carregando, text=self.tr("ui.preparando_avatar"))

    def mostrar_aviso(self, texto: str, cor: str, segundos: float = 4.0) -> None:
        self._status_temporario = (texto, cor, self.t + segundos)

    @property
    def fps_desejado(self) -> int:
        """60 FPS quando há movimento rápido (ouvindo, pensando, falando, cor em transição); 30 em repouso."""
        alvo = hex_para_rgb(CORES[self.estado])
        em_transicao = max(abs(a - b) for a, b in zip(self.cor, alvo, strict=True)) > TOLERANCIA_COR
        return FPS_ATIVO if self.estado in ESTADOS_ATIVOS or em_transicao or self.boca > 0.01 else FPS_REPOUSO

    # ---------- Animação ----------
    def quadro(self, dt: float, amplitude: float, forma: float) -> None:
        self.t += dt
        self.cor = aproximar(self.cor, hex_para_rgb(CORES[self.estado]), 1 - math.exp(-dt * 9))
        cor = rgb_para_hex(self.cor)
        falando = self.estado is Estado.FALANDO
        self.boca = suavizar_boca(self.boca, amplitude if falando else 0.0, dt)
        self._desenhar_avatar(falando, forma)
        self._desenhar_halo()
        self._desenhar_arcos(cor)
        self._desenhar_barras(cor)
        self._desenhar_status(cor)

    def _desenhar_avatar(self, falando: bool, forma: float) -> None:
        if not self.quadros:
            return
        forma_idx = self.seletor.atualizar(forma, self.boca, self.t) if falando else NEUTRA
        linha = self.quadros[forma_idx]
        self.cena.configurar(self.item_avatar, image=linha[nivel_boca(self.boca, len(linha))])
        # Centro visual do busto no centro do anel, com "respiração" e balanço sutis
        dy = math.sin(self.t * 1.4) * 2.5
        dx = math.sin(self.t * 0.6) * 1.2
        self.cena.coords(self.item_avatar, self.cx - self.centro_avatar[0] + dx, self.cy - self.centro_avatar[1] + dy)

    def _desenhar_halo(self) -> None:
        halos = self.halos.get(self.estado)
        if not halos:
            return
        t = self.t
        pulso = {
            Estado.INICIANDO: 0.3 + 0.2 * math.sin(t * 3),
            Estado.PARADO: 0.25 + 0.15 * math.sin(t * 1.5),
            Estado.OUVINDO: 0.35 + 0.65 * self.mic,
            Estado.PENSANDO: 0.5 + 0.5 * math.sin(t * 7),
            Estado.FALANDO: 0.3 + 0.7 * self.boca,
        }[self.estado]
        nivel = max(0, min(NIVEIS_HALO - 1, round(pulso * (NIVEIS_HALO - 1))))
        self.cena.configurar(self.item_halo, image=halos[nivel], state="normal")

    def _desenhar_arcos(self, cor: str) -> None:
        vel = VELOCIDADE_ARCOS[self.estado]
        for k, arco in enumerate(self.arcos):
            inicio = round((self.t * vel * (1 if k % 2 else -1) + k * 120) % 360)
            self.cena.configurar(arco, start=inicio, outline=cor)
        self.cena.configurar(self.anel, outline=misturar(cor, FUNDO, 0.35))

    def _desenhar_barras(self, cor: str) -> None:
        n, base_y, larg = N_BARRAS, 600, 10
        x0 = self.cx - n * (larg + 4) / 2
        t = self.t
        for i, b in enumerate(self.barras):
            centro = 1 - abs(i - n / 2) / n
            if self.estado is Estado.FALANDO:
                onda = 0.55 + 0.45 * math.sin(t * 11 + i * 0.9) * math.sin(t * 7 - i * 0.4)
                h = 3 + self.boca * 40 * onda * centro
            elif self.estado is Estado.OUVINDO:
                onda = 0.6 + 0.4 * math.sin(t * 9 + i * 1.3)
                h = 3 + 4 * abs(math.sin(t * 2 + i * 0.4)) + self.mic * 42 * onda * centro
            else:
                h = 3
            x = x0 + i * (larg + 4)
            self.cena.coords(b, x, base_y - h, x + larg, base_y + h)
            self.cena.configurar(b, fill=cor)

    def _desenhar_status(self, cor: str) -> None:
        if self._status_temporario and self.t < self._status_temporario[2]:
            texto, cor_status, _ = self._status_temporario
        else:
            self._status_temporario = None
            texto, cor_status = self.rotulo(self.estado), cor
        self.cena.configurar(self.txt_status, text=texto, fill=cor_status)
