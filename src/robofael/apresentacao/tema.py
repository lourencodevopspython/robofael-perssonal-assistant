"""Identidade visual: paleta, cores por estado, interpolação de cores e halo."""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter

from robofael.dominio.estados import Estado

FUNDO = "#0b0f1a"
SUPERFICIE = "#0f1524"
CARTAO = "#141c30"
BORDA = "#1e2a44"
TEXTO = "#e8f6ff"
TEXTO_SUAVE = "#8fb3d9"
TEXTO_APAGADO = "#5d7491"
DESTAQUE = "#00e5ff"
PRIMARIA = "#1f6feb"
ERRO = "#ff6b6b"
FONTE = "Helvetica"

CORES: dict[Estado, str] = {
    Estado.INICIANDO: "#7a8ca8",
    Estado.PARADO: "#3aa0ff",
    Estado.OUVINDO: "#2ee59d",
    Estado.PENSANDO: "#ffc94a",
    Estado.FALANDO: "#00e5ff",
}
CHAVES_ESTADO: dict[Estado, str] = {e: f"estado.{e.value}" for e in Estado}  # textos no catálogo (i18n)
ROTULOS: dict[Estado, str] = {  # português, para quem não usa o tradutor
    Estado.INICIANDO: "Iniciando...",
    Estado.PARADO: "Pressione ESPAÇO para falar",
    Estado.OUVINDO: "Ouvindo... (ESPAÇO cancela)",
    Estado.PENSANDO: "Pensando...",
    Estado.FALANDO: "Falando... (ESPAÇO interrompe)",
}

Cor = tuple[float, float, float]


def hex_para_rgb(cor: str) -> Cor:
    return tuple(float(int(cor[i:i + 2], 16)) for i in (1, 3, 5))  # type: ignore[return-value]


def rgb_para_hex(rgb: Cor) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c))):02x}" for c in rgb)


def misturar(cor_a: str, cor_b: str, proporcao_a: float) -> str:
    a, b = hex_para_rgb(cor_a), hex_para_rgb(cor_b)
    return rgb_para_hex(tuple(x * proporcao_a + y * (1 - proporcao_a) for x, y in zip(a, b, strict=True)))  # type: ignore[arg-type]


def aproximar(atual: Cor, alvo: Cor, fator: float) -> Cor:
    """Um passo de interpolação de `atual` em direção a `alvo` (transições suaves de cor)."""
    return tuple(a + (b - a) * fator for a, b in zip(atual, alvo, strict=True))  # type: ignore[return-value]


NIVEIS_HALO = 8  # intensidades pré-renderizadas do halo (pulsação)


def imagem_halo(cor_hex: str, intensidade: float, tam: int = 600, fundo: str | None = FUNDO) -> Image.Image:
    """Halo circular desfocado na cor do estado; `intensidade` em 0..1.

    Por padrão já vem misturado com a cor de fundo (imagem opaca): o Tk desenha imagens opacas
    copiando os pixels, enquanto as com transparência ele mistura pixel a pixel em software, o que
    custava ~8 ms a cada redesenho da área do avatar. Com `fundo=None`, devolve a versão RGBA."""
    r, g, b = (int(c) for c in hex_para_rgb(cor_hex))
    img = Image.new("RGBA", (tam, tam), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    raio, c = tam * 0.36, tam / 2
    d.ellipse((c - raio, c - raio, c + raio, c + raio), outline=(r, g, b, int(90 + 140 * intensidade)), width=10)
    d.ellipse((c - raio * 0.8, c - raio * 0.8, c + raio * 0.8, c + raio * 0.8),
              fill=(r, g, b, int(25 + 30 * intensidade)))
    halo = img.filter(ImageFilter.GaussianBlur(18))
    if fundo is None:
        return halo
    base = Image.new("RGBA", halo.size, tuple(int(v) for v in hex_para_rgb(fundo)) + (255,))
    return Image.alpha_composite(base, halo).convert("RGB")


def gerar_halos(primeiro: Estado = Estado.INICIANDO) -> dict[Estado, list[Image.Image]]:
    """Todos os halos (estados x intensidades), começando pelo estado `primeiro`.
    Só usa Pillow: pode rodar fora da thread da interface."""
    ordem = [primeiro, *(e for e in CORES if e is not primeiro)]
    return {e: [imagem_halo(CORES[e], i / (NIVEIS_HALO - 1)) for i in range(NIVEIS_HALO)] for e in ordem}
