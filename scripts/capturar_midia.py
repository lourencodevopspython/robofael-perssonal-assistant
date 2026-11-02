"""Gera os prints e GIFs do README (docs/imagens) a partir do aplicativo real.

Uso: make midia   (ou .venv/bin/python scripts/capturar_midia.py [pasta_destino])

Abre a janela de verdade com dados de exemplo numa pasta temporária (nada dos seus dados aparece) e o
áudio mudo (SDL_AUDIODRIVER=dummy); a voz é sintetizada normalmente, então precisa de internet. Precisa
de servidor gráfico: as imagens são capturadas da tela, então não cubra a janela enquanto ele grava."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

DESTINO = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/imagens")
_TEMP = tempfile.TemporaryDirectory(prefix="robofael-demo-")
os.environ.update(SDL_AUDIODRIVER="dummy", ROBOFAEL_DADOS=str(Path(_TEMP.name) / "dados"))

import tkinter as tk  # noqa: E402

from PIL import Image, ImageDraw, ImageFont, ImageGrab  # noqa: E402

from robofael import bootstrap  # noqa: E402
from robofael.apresentacao import app as mod_app  # noqa: E402
from robofael.avatar.renderizador import gerar_quadros  # noqa: E402
from robofael.configuracao import Configuracao, configurar_logs  # noqa: E402
from robofael.dominio.estados import Estado  # noqa: E402

FONTE = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _caixa(w: tk.Misc) -> tuple[int, int, int, int]:
    x, y = w.winfo_rootx(), w.winfo_rooty()
    return x, y, x + w.winfo_width(), y + w.winfo_height()


class Gravador:
    def __init__(self, raiz: tk.Tk):
        self.raiz = raiz

    def esperar(self, segundos: float, ate=None) -> None:
        fim = time.time() + segundos
        while time.time() < fim and not (ate and ate()):
            self.raiz.update()
            time.sleep(0.01)

    def gravar(self, alvo: tk.Misc, segundos: float, fps: int, ate=None, depois: float = 0.0) -> list[Image.Image]:
        quadros: list[Image.Image] = []
        fim, ultimo = time.time() + segundos, 0.0
        while time.time() < fim:
            self.raiz.update()
            if time.time() - ultimo >= 1 / fps:
                ultimo = time.time()
                quadros.append(ImageGrab.grab(_caixa(alvo)).convert("RGB"))
            if ate is not None and ate():
                fim, ate = min(fim, time.time() + depois), None
            time.sleep(0.003)
        return quadros


def salvar_gif(nome: str, quadros: list[Image.Image], fps: int, largura: int) -> None:
    menores = [q.resize((largura, round(q.height * largura / q.width)), Image.Resampling.LANCZOS) for q in quadros]
    paleta = [q.quantize(colors=160, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for q in menores]
    paleta[0].save(DESTINO / nome, save_all=True, append_images=paleta[1:], duration=round(1000 / fps), loop=0,
                   optimize=True, disposal=1)
    print(f"{nome}: {len(quadros)} quadros, {(DESTINO / nome).stat().st_size // 1024} KB")


def salvar_png(nome: str, imagem: Image.Image) -> None:
    imagem.convert("RGB").save(DESTINO / nome, optimize=True)
    print(f"{nome}: {imagem.width}x{imagem.height}")


def avatares() -> None:
    """Os dois avatares com a boca fechada e nas vogais."""
    fonte = ImageFont.truetype(FONTE, 15)
    rotulos = ("boca fechada", "“a”", "“o / u”", "“e / i”")
    faixas = []
    for nome in ("cracha", "selfie"):
        q, _ = gerar_quadros(nome, 300)
        sel = [q[1][0], q[1][-1], q[0][-1], q[2][-1]]
        w, h = sel[0].size
        faixa = Image.new("RGBA", (w * 4, h + 26), (11, 15, 26, 255))
        d = ImageDraw.Draw(faixa)
        for i, (im, rotulo) in enumerate(zip(sel, rotulos, strict=True)):
            faixa.alpha_composite(im, (i * w, 0))
            d.text((i * w + (w - d.textlength(rotulo, font=fonte)) / 2, h + 2), rotulo, fill=(140, 220, 255),
                   font=fonte)
        faixas.append(faixa)
    tira = Image.new("RGBA", (faixas[0].width, sum(f.height for f in faixas)), (11, 15, 26, 255))
    for i, faixa in enumerate(faixas):
        tira.alpha_composite(faixa, (0, i * faixas[0].height))
    salvar_png("avatares.png", tira)


def main() -> None:
    configurar_logs()
    DESTINO.mkdir(parents=True, exist_ok=True)
    avatares()

    nucleo = bootstrap.montar_nucleo(Configuracao.do_ambiente())
    for tarefa in ("Revisar o PR do pipeline", "Comprar pão", "Enviar o relatório da sprint"):
        nucleo.agenda.adicionar_tarefa(tarefa)
    agora = datetime.now()
    nucleo.agenda.criar_lembrete("Daily com o time", (agora + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"))
    nucleo.agenda.criar_lembrete("Beber água", (agora + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M"))

    raiz = tk.Tk(className="robofael")
    janela = mod_app.Janela(raiz, nucleo, "cracha")
    g = Gravador(raiz)
    g.esperar(120, ate=lambda: janela.servicos is not None and janela.palco.quadros is not None)

    # 1) A saudação: o avatar falando
    g.esperar(20, ate=lambda: janela._estado is Estado.FALANDO)
    quadros = g.gravar(janela.canvas, 12, fps=10, ate=lambda: janela._estado is not Estado.FALANDO, depois=0.5)
    salvar_gif("falando.gif", quadros[:70], fps=10, largura=340)
    g.esperar(1.5)
    salvar_png("janela.png", ImageGrab.grab(_caixa(raiz)))

    # 2) Um pedido digitado, da digitação à resposta falada
    quadros = g.gravar(raiz, 0.6, fps=8)
    texto = "anota tarefa ligar para o dentista"
    janela.entrada.focus_set()
    for i in range(1, len(texto) + 1):
        janela.entrada.delete(0, "end")
        janela.entrada.insert(0, texto[:i])
        quadros += g.gravar(raiz, 0.09, fps=11)
    janela._enviar_texto()
    falou = {"sim": False}

    def terminou() -> bool:
        falou["sim"] |= janela._estado is Estado.FALANDO
        return falou["sim"] and janela._estado is Estado.PARADO

    quadros += g.gravar(raiz, 25, fps=8, ate=terminou, depois=1.2)
    salvar_gif("conversa.gif", quadros, fps=8, largura=620)

    # 3) A tela de configurações, depois de listar os modelos
    dialogo = janela.abrir_configuracoes()
    g.esperar(10, ate=lambda: "…" not in dialogo.lbl_modelos.cget("text"))
    g.esperar(0.5)
    salvar_png("configuracoes.png", ImageGrab.grab(_caixa(dialogo)))
    dialogo.cancelar()
    g.esperar(0.3)
    janela.encerrar()
    _TEMP.cleanup()


if __name__ == "__main__":
    main()
