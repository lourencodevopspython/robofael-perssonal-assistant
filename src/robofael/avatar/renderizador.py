"""Renderização do avatar: recorta o busto em alta resolução, veste uma camisa futurista
e gera os quadros da boca (níveis de abertura x formatos de vogal), com cache em disco."""

from __future__ import annotations

import hashlib
import math
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from robofael.avatar.catalogo import AVATARES

NIVEIS_BOCA = 12
FORMAS = ("redonda", "neutra", "aberta")  # o/u · a · e/i
PROPORCAO_BUSTO = 0.88  # largura / altura do recorte
SUPERAMOSTRAGEM = 2  # trabalha em 2x e reduz no fim: bordas suaves, sem degraus
MARGEM = 24
LANCZOS = Image.Resampling.LANCZOS
CIANO = (0, 229, 255)

Configuracao_Avatar = dict[str, Any]  # entrada do catálogo (pontos do rosto medidos na foto)
Geometria = dict[str, Any]  # pontos do rosto já convertidos para o recorte do busto

if TYPE_CHECKING:
    from robofael.configuracao import Configuracao


def _caixa_busto(cfg: Configuracao_Avatar) -> tuple[float, float, float, float]:
    """Recorte do busto: um pouco acima da cabeça até os ombros, centrado na cabeça."""
    cx, topo = cfg["cabeca"]
    h_cabeca = cfg["queixo"] - topo
    y0 = topo - 0.2 * h_cabeca
    y1 = cfg["queixo"] + 0.95 * h_cabeca
    meia_larg = (y1 - y0) * PROPORCAO_BUSTO / 2
    return (cx - meia_larg, y0, cx + meia_larg, y1)


def _carregar(cfg: Configuracao_Avatar, altura: int, pasta: Path | str | None = None) -> tuple[Image.Image, Geometria]:
    pasta = Path(pasta or _pastas_padrao().pasta_avatares)
    img = Image.open(pasta / cfg["arquivo"]).convert("RGBA")
    fator = 1.0
    if cfg.get("arquivo_hd"):
        # Aplica o recorte (sem fundo) da PNG pequena sobre a foto original em alta resolução
        hd = Image.open(pasta / cfg["arquivo_hd"]).convert("RGB")
        fator = hd.width / img.width
        alfa = img.getchannel("A").resize(hd.size, LANCZOS)
        alfa = alfa.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.GaussianBlur(1.2))  # tira a franja do fundo
        hd.putalpha(alfa)
        img = hd
    caixa = [v * fator for v in _caixa_busto(cfg)]
    x0, y0, x1, y1 = (round(v) for v in caixa)
    img = img.crop((x0, y0, x1, y1))
    escala = altura / img.height
    img = img.resize((round(img.width * escala), altura), LANCZOS)
    k = fator * escala  # pixel da `arquivo` -> pixel de trabalho

    def conv(x: float, y: float) -> tuple[float, float]:
        return ((x * fator - caixa[0]) * escala, (y * fator - caixa[1]) * escala)

    mx, my = conv(*cfg["boca"])
    _, queixo = conv(0, cfg["queixo"])
    _, topo = conv(0, cfg["cabeca"][1])
    pcx, plado = conv(cfg["pescoco"][0], cfg["pescoco"][1])
    _, pfrente = conv(0, cfg["pescoco"][2])
    return img, {
        "mx": mx, "my": my, "mw": cfg["largura_boca"] * k, "queixo": queixo, "topo": topo,
        "abertura_max": cfg["abertura_max"] * k,
        "pescoco": (pcx, plado, pfrente, cfg["pescoco"][3] * k),
    }


# ---------------------------------------------------------------- camisa futurista
@dataclass(frozen=True)
class _Gola:
    """Geometria da gola, derivada da posição do pescoço."""

    cx: float  # centro horizontal do pescoço
    ylado: float  # altura da gola nas laterais
    yfrente: float  # altura da gola na frente (mais baixa)
    hw: float  # meia largura do pescoço

    @property
    def altura(self) -> float:
        return 0.32 * self.hw


def _camisa(img: Image.Image, g: Geometria) -> Image.Image:
    """Substitui a roupa por uma camisa futurista: gola alta, placas nos ombros,
    costuras luminosas e emblema no peito, mantendo as dobras do tecido original."""
    largura, altura = img.size
    orig = np.asarray(img).astype(np.float32)
    gola = _Gola(*g["pescoco"])
    yy, xx = np.mgrid[0:altura, 0:largura].astype(np.float32)
    dxn = np.abs(xx - gola.cx) / gola.hw
    curva = np.where(dxn < 1, gola.yfrente - (gola.yfrente - gola.ylado) * dxn ** 2, gola.ylado)
    m = np.clip((yy - curva) / 2.0 + 0.5, 0, 1) * (orig[..., 3] / 255)  # silhueta abaixo da gola

    tecido = _tecido(yy, gola, altura) * _sombreado(orig, m, altura)
    tecido += ((xx + yy) % max(4, gola.hw * 0.09) < 1.2)[..., None] * 6.0  # trama diagonal sutil
    tecido = _placas_dos_ombros(tecido, xx, yy, dxn, gola)
    tecido = _gola_metalica(tecido, yy, dxn, curva, gola)

    rgb = orig[..., :3] * (1 - m[..., None]) + np.clip(tecido, 0, 255) * m[..., None]
    out = Image.fromarray(np.dstack([rgb, orig[..., 3]]).astype(np.uint8), "RGBA")
    linhas, esp = _linhas_luminosas(img.size, gola)
    mascara = Image.fromarray((m * 255).astype(np.uint8))
    linhas.putalpha(ImageChops.multiply(linhas.getchannel("A"), mascara))
    halo = linhas.filter(ImageFilter.GaussianBlur(esp * 2.5))
    out = Image.alpha_composite(out, halo)
    out = Image.alpha_composite(out, halo)
    out = Image.alpha_composite(out, linhas)
    out.putalpha(img.getchannel("A"))  # o brilho não pode vazar para fora da silhueta
    return out


def _sombreado(orig: np.ndarray, m: np.ndarray, altura: int) -> np.ndarray:
    """Luz e sombra da camisa original (sem as estampas), normalizadas em torno de 0,9."""
    lum = orig[..., :3] @ np.array([0.299, 0.587, 0.114], np.float32)
    dentro = m > 0.5
    teto = np.percentile(lum[dentro], 60) if dentro.any() else 128
    lum = np.minimum(lum, teto)
    lum_img = Image.fromarray(np.clip(lum, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(altura * 0.012))
    lum = np.asarray(lum_img).astype(np.float32)
    media, desvio = lum[dentro].mean(), lum[dentro].std() + 1e-3
    return np.clip(0.9 + 0.35 * (lum - media) / desvio, 0.45, 1.3)[..., None]


def _tecido(yy: np.ndarray, gola: _Gola, altura: int) -> np.ndarray:
    """Azul-grafite em degradê vertical."""
    t = np.clip((yy - gola.ylado) / (altura - gola.ylado), 0, 1)[..., None]
    return np.array([38, 46, 66], np.float32) * (1 - t) + np.array([16, 20, 32], np.float32) * t


def _placas_dos_ombros(tecido: np.ndarray, xx: np.ndarray, yy: np.ndarray, dxn: np.ndarray,
                       gola: _Gola) -> np.ndarray:
    """Acima da linha de recorte, um tom mais claro."""
    recorte = gola.ylado + 0.95 * gola.hw + 0.22 * np.maximum(np.abs(xx - gola.cx) - gola.hw, 0)
    placa = (np.clip((recorte - yy) / 2.0 + 0.5, 0, 1) * (dxn > 0.95))[..., None]
    return tecido * (1 - placa) + (tecido * 1.35 + 8) * placa


def _gola_metalica(tecido: np.ndarray, yy: np.ndarray, dxn: np.ndarray, curva: np.ndarray,
                   gola: _Gola) -> np.ndarray:
    faixa = (yy > curva) & (yy < curva + gola.altura) & (dxn < 1.18)
    brilho = np.clip(1 - (yy - curva) / gola.altura, 0, 1)
    metal = np.array([70, 82, 108], np.float32) * (0.6 + 0.6 * brilho[..., None])
    return np.where(faixa[..., None], tecido * 0.6 + metal * 0.64, tecido)


def _linhas_luminosas(tamanho: tuple[int, int], gola: _Gola) -> tuple[Image.Image, int]:
    """Costuras, recortes, LEDs e emblema em ciano, numa camada à parte (recortada depois)."""
    largura, altura = tamanho
    cx, ylado, yfrente, hw = gola.cx, gola.ylado, gola.yfrente, gola.hw
    linhas = Image.new("RGBA", (largura, altura), (0, 0, 0, 0))
    d = ImageDraw.Draw(linhas)
    esp = max(2, round(hw * 0.035))
    xs = np.linspace(cx - 1.18 * hw, cx + 1.18 * hw, 60)
    borda_gola = [(x, yfrente - (yfrente - ylado) * min(1, abs(x - cx) / hw) ** 2 + esp) for x in xs]
    d.line(borda_gola, fill=CIANO + (255,), width=esp)  # borda superior da gola
    externos = [(x, y + gola.altura) for x, y in borda_gola]
    d.line(externos, fill=CIANO + (150,), width=max(1, esp // 2))  # base da gola
    peito = (cx, yfrente + 2.3 * hw)
    for lado in (-1, 1):
        ombro = (cx + lado * 1.05 * hw, ylado + 0.45 * hw)
        d.line([ombro, peito], fill=CIANO + (230,), width=esp)  # costuras em V
        pts = [(cx + lado * (0.95 * hw + i * hw * 0.25), ylado + 0.95 * hw + 0.22 * i * hw * 0.25)
               for i in range(14)]
        d.line(pts, fill=CIANO + (200,), width=esp)  # recorte dos ombros
        for i in (2, 5, 8):  # pequenos LEDs no recorte
            x, y = pts[i]
            d.ellipse((x - esp * 1.4, y - esp * 1.4, x + esp * 1.4, y + esp * 1.4), fill=(200, 250, 255, 255))
    d.line([peito, (cx, altura)], fill=CIANO + (200,), width=esp)  # costura central
    ex, ey, er = cx + 1.35 * hw, yfrente + 1.25 * hw, 0.24 * hw  # emblema no peito
    d.ellipse((ex - er, ey - er, ex + er, ey + er), outline=CIANO + (255,), width=esp)
    d.regular_polygon((ex, ey, er * 0.5), 3, rotation=180, fill=CIANO + (220,))
    return linhas, esp


# ---------------------------------------------------------------- boca
def _suave(t: np.ndarray | float) -> np.ndarray:
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


def _amostrar(arr: np.ndarray, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
    """Amostragem bilinear de `arr` (H, W, C) nas coordenadas fracionárias xs, ys."""
    h, w = arr.shape[:2]
    xs = np.clip(xs, 0, w - 1.001)
    ys = np.clip(ys, 0, h - 1.001)
    x0, y0 = xs.astype(int), ys.astype(int)
    fx, fy = (xs - x0)[..., None], (ys - y0)[..., None]
    a, b = arr[y0, x0], arr[y0, x0 + 1]
    c, e = arr[y0 + 1, x0], arr[y0 + 1, x0 + 1]
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + e * fx) * fy


def _boca(base_arr: np.ndarray, g: Geometria, abertura: float, forma: str) -> np.ndarray:
    """Deforma a região da boca: o lábio de cima sobe um pouco, a mandíbula desce, os
    cantos ficam presos (a abertura vira uma lente) e a boca estreita (o/u) ou alarga (e/i)."""
    out = base_arr.copy()
    if abertura <= 0:
        return out
    mx, my, mw = g["mx"], g["my"], g["mw"]
    queixo = g["queixo"]
    fd, fs = {"redonda": (1.1, 0.84), "neutra": (1.0, 0.97), "aberta": (0.75, 1.07)}[forma]
    d = g["abertura_max"] * abertura * fd  # descida da mandíbula
    u = 0.2 * d  # subida do lábio superior
    s = 1 + (fs - 1) * abertura  # escala horizontal da boca

    x0, x1 = int(mx - 1.7 * mw), int(mx + 1.7 * mw)
    y0, y1 = int(my - 0.9 * mw), int(queixo + 0.7 * mw)
    yy, xx = np.mgrid[y0:y1, x0:x1].astype(np.float32)

    # 1) Horizontal: aproxima (ou afasta) os cantos do centro, com queda radial suave
    r = np.sqrt(((xx - mx) / (1.5 * mw)) ** 2 + ((yy - my) / (0.8 * mw)) ** 2)
    wh = (1 - _suave(r)) ** 1.5
    xs = mx + (xx - mx) * (1 + (1 / s - 1) * wh)

    # 2) Vertical: perfil dos lábios (1 no centro, 0 nos cantos) e da mandíbula (mais largo)
    meia = 0.5 * mw * s
    lab = np.maximum(np.cos(np.clip(np.abs(xs - mx) / meia, 0, 1) * math.pi / 2), 0) ** 1.2
    mand = 1 - _suave((np.abs(xs - mx) - 0.55 * mw) / (0.9 * mw))
    # Transição longa do lábio inferior até o queixo: distribui o esticamento e evita estrias
    t = _suave((yy - my) / max(queixo - my, 0.5 * mw) / 0.9)
    queda = 1 - _suave((yy - queixo) / (0.8 * mw))  # some abaixo do queixo
    desce = d * (lab + (mand - lab) * t) * queda
    sobe = u * lab * (1 - _suave((my - yy) / (0.5 * mw)))
    abaixo = yy >= my
    ys = np.where(abaixo, yy - desce, yy + sobe)

    regiao = _amostrar(base_arr, xs, ys)

    # 3) Interior da boca no vão entre os lábios (borda suave de ~1,5 px)
    vao = np.where(abaixo, np.clip((my - ys) / 1.5, 0, 1), np.clip((ys - my) / 1.5, 0, 1)) * np.clip(lab * 20, 0, 1)
    topo_vao = my - u * lab
    alt_vao = np.maximum((d + u) * lab, 1e-3)
    v = np.clip((yy - topo_vao) / alt_vao, 0, 1)  # 0 = sob os dentes de cima, 1 = lábio de baixo
    # Sombra forte sob os dentes de cima, clareando para o fundo da boca
    cor = np.array([24, 8, 10], np.float32) * (1 - v[..., None]) + np.array([66, 22, 26], np.float32) * v[..., None]
    # Língua: mancha suave no centro e embaixo, só com a boca bem aberta
    lingua = _suave((v - 0.45) / 0.4) * lab ** 2 * _suave((abertura - 0.3) / 0.4)
    cor = cor * (1 - 0.7 * lingua[..., None]) + np.array([128, 58, 62], np.float32) * 0.7 * lingua[..., None]
    # Escurece perto das bordas (sombra dos lábios)
    borda = np.minimum(v, 1 - v) * alt_vao
    cor = cor * (0.55 + 0.45 * _suave(borda / 2.5))[..., None]
    interior = np.dstack([cor, np.full(cor.shape[:2], 255, np.float32)])
    regiao = regiao * (1 - vao[..., None]) + interior * vao[..., None]
    out[y0:y1, x0:x1] = regiao
    return out


# ---------------------------------------------------------------- acabamento
def _moldura(w: int, h: int) -> Image.Image:
    """Máscara oval suave que deixa só o busto, esmaecendo os ombros."""
    oval = Image.new("L", (w, h), 0)
    ImageDraw.Draw(oval).ellipse((w * 0.05, -h * 0.12, w * 0.95, h * 1.05), fill=255)
    oval = oval.filter(ImageFilter.GaussianBlur(w * 0.04))
    h0 = int(h * 0.72)
    fade = Image.new("L", (w, h), 255)
    fade.paste(Image.linear_gradient("L").resize((w, h - h0)).point(lambda v: 255 - v), (0, h0))
    return ImageChops.multiply(oval, fade)


def _halo(alfa: Image.Image) -> Image.Image:
    """Brilho ciano ao redor da cabeça e dos ombros (camada de fundo, com margem)."""
    largura, altura = alfa.width + 2 * MARGEM, alfa.height + 2 * MARGEM
    a = Image.new("L", (largura, altura), 0)
    a.paste(alfa.point(lambda v: 255 if v > 140 else v), (MARGEM, MARGEM))
    contorno = a.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(7))
    h0, h1 = int(altura * 0.55), int(altura * 0.8)
    fade = Image.new("L", (largura, altura), 0)
    fade.paste(255, (0, 0, largura, h0))
    fade.paste(Image.linear_gradient("L").resize((largura, h1 - h0)).point(lambda v: 255 - v), (0, h0))
    brilho = Image.new("RGBA", (largura, altura), (0, 220, 255, 0))
    brilho.putalpha(ImageChops.multiply(contorno.point(lambda v: int(v * 0.5)), fade))
    return brilho


def _nitidez(img: Image.Image, intensidade: float) -> Image.Image:
    rgb = img.convert("RGB").filter(ImageFilter.UnsharpMask(radius=1.6, percent=int(130 * intensidade), threshold=2))
    rgb = ImageEnhance.Contrast(rgb).enhance(1 + 0.06 * intensidade)
    rgb.putalpha(img.getchannel("A"))
    return rgb


def _pastas_padrao() -> Configuracao:
    from robofael.configuracao import Configuracao

    return Configuracao.do_ambiente()


def gerar_quadros(nome: str = "cracha", altura: int = 480, pasta_cache: Path | str | None = None,
                  pasta_imagens: Path | str | None = None,
                  trabalhadores: int | None = None) -> tuple[list[list[Image.Image]], tuple[float, float]]:
    """Gera (ou lê do cache) os quadros do avatar.

    Retorna (quadros, centro): quadros[forma][nivel] são imagens PIL RGBA — forma em
    FORMAS, nivel de 0 (boca fechada) a NIVEIS_BOCA-1 — e centro é o ponto (x, y) da
    imagem que deve ficar no meio do anel da interface (centro visual do busto).

    Desempenho: os quadros são renderizados e lidos em paralelo (numpy e Pillow liberam
    o GIL), o quadro de boca fechada é calculado uma única vez e o resultado fica em cache
    no disco; o cache é invalidado automaticamente quando este código ou o catálogo mudam."""
    if pasta_cache is None or pasta_imagens is None:
        cfg_app = _pastas_padrao()
        pasta_cache = pasta_cache or cfg_app.pasta_cache_avatar
        pasta_imagens = pasta_imagens or cfg_app.pasta_avatares
    cfg = AVATARES[nome]
    origem = Path(__file__).read_text(encoding="utf-8") + repr(sorted(cfg.items())) + nome + str(altura)
    chave = hashlib.sha1(origem.encode()).hexdigest()[:12]
    pasta = Path(pasta_cache) / f"{nome}_{chave}"
    arquivos = [[pasta / f"{f}_{n:02d}.png" for n in range(NIVEIS_BOCA)] for f in FORMAS]

    img, g = _carregar(cfg, altura * SUPERAMOSTRAGEM, pasta_imagens)
    w_final = round(img.width / SUPERAMOSTRAGEM)
    centro = (w_final / 2 + MARGEM, (g["topo"] / SUPERAMOSTRAGEM + altura * 0.8) / 2 + MARGEM)
    tarefas = [(f, n) for f in range(len(FORMAS)) for n in range(NIVEIS_BOCA)]

    with ThreadPoolExecutor(max_workers=trabalhadores or min(8, os.cpu_count() or 2)) as pool:
        if all(a.exists() for linha in arquivos for a in linha):
            def abrir(fn: tuple[int, int]) -> Image.Image:
                return Image.open(arquivos[fn[0]][fn[1]]).convert("RGBA")

            lidos = dict(zip(tarefas, pool.map(abrir, tarefas), strict=True))
            return [[lidos[(f, n)] for n in range(NIVEIS_BOCA)] for f in range(len(FORMAS))], centro

        vestido = _camisa(img, g)
        base_arr = np.asarray(vestido).astype(np.float32)
        moldura = _moldura(w_final, altura)
        halo = _halo(ImageChops.multiply(vestido.getchannel("A").resize((w_final, altura), LANCZOS), moldura))
        pasta.mkdir(parents=True, exist_ok=True)

        def renderizar(f: int, n: int) -> Image.Image:
            abertura = (n / (NIVEIS_BOCA - 1)) ** 1.2
            arr = _boca(base_arr, g, abertura, FORMAS[f])
            q = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGBA").resize((w_final, altura), LANCZOS)
            q = _nitidez(q, cfg["nitidez"])
            q.putalpha(ImageChops.multiply(q.getchannel("A"), moldura))
            final = halo.copy()
            final.alpha_composite(q, (MARGEM, MARGEM))
            final.save(arquivos[f][n], compress_level=1)
            return final

        fechada = renderizar(0, 0)  # boca fechada é igual em todos os formatos
        abertas = [(f, n) for f, n in tarefas if n > 0]
        prontos = dict(zip(abertas, pool.map(lambda fn: renderizar(*fn), abertas), strict=True))
        for f in range(1, len(FORMAS)):
            fechada.save(arquivos[f][0], compress_level=1)
    return [[fechada if n == 0 else prontos[(f, n)] for n in range(NIVEIS_BOCA)] for f in range(len(FORMAS))], centro


def gerar_previa(nome: str, destino: Path | str, **kwargs: Any) -> None:
    """Salva uma tira com boca fechada, "a", "o/u" e "e/i" para conferir o resultado."""
    q, _ = gerar_quadros(nome, **kwargs)
    sel = [q[1][0], q[1][-1], q[0][-1], q[2][-1]]
    w, h = sel[0].size
    tira = Image.new("RGBA", (w * len(sel), h), (11, 15, 26, 255))
    for i, im in enumerate(sel):
        tira.alpha_composite(im, (i * w, 0))
    tira.save(destino)
