"""Gera o ícone do Robofael (rosto do avatar num círculo com o anel ciano) em vários tamanhos.

Uso: python empacotamento/gerar_icone.py <pasta_destino>   -> <pasta>/<N>x<N>/apps/robofael.png
     python empacotamento/gerar_icone.py --windows <pasta>  -> <pasta>/robofael.ico (executável e instalador)
                                                              e <pasta>/robofael.png (ícone da janela)
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from robofael.avatar.catalogo import AVATARES
from robofael.configuracao import Configuracao

TAMANHOS = (48, 64, 128, 256, 512)


def gerar(base: int = 512) -> Image.Image:
    cfg = AVATARES["cracha"]
    foto = Image.open(Configuracao.do_ambiente().pasta_avatares / cfg["arquivo"]).convert("RGBA")
    cx, topo = cfg["cabeca"]
    altura_cabeca = cfg["queixo"] - topo
    lado = int(altura_cabeca * 1.55)  # cabeça + um pouco de ombro
    caixa = (cx - lado // 2, topo - int(altura_cabeca * 0.12), cx + lado // 2, topo - int(altura_cabeca * 0.12) + lado)
    rosto = foto.crop(caixa).resize((int(base * 0.86),) * 2, Image.Resampling.LANCZOS)

    icone = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    fundo = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    ImageDraw.Draw(fundo).ellipse((0, 0, base - 1, base - 1), fill=(11, 15, 26, 255))
    icone.alpha_composite(fundo)
    deslocamento = (base - rosto.width) // 2
    mascara = Image.new("L", (base, base), 0)
    ImageDraw.Draw(mascara).ellipse((base * 0.04, base * 0.04, base * 0.96, base * 0.96), fill=255)
    camada = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    camada.alpha_composite(rosto, (deslocamento, deslocamento + int(base * 0.04)))
    camada.putalpha(Image.composite(camada.getchannel("A"), Image.new("L", (base, base), 0), mascara))
    icone.alpha_composite(camada)
    anel = Image.new("RGBA", (base, base), (0, 0, 0, 0))
    ImageDraw.Draw(anel).ellipse((base * 0.03, base * 0.03, base * 0.97, base * 0.97), outline=(0, 229, 255, 255),
                                 width=max(2, base // 40))
    icone.alpha_composite(anel.filter(ImageFilter.GaussianBlur(base / 200)))
    return icone


def gerar_windows(destino: Path) -> None:
    destino.mkdir(parents=True, exist_ok=True)
    original = gerar()
    original.save(destino / "robofael.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
    original.resize((256, 256), Image.Resampling.LANCZOS).save(destino / "robofael.png")
    print(f"ícones do Windows gerados em {destino}")


if __name__ == "__main__":
    if sys.argv[1] == "--windows":
        gerar_windows(Path(sys.argv[2]))
        sys.exit()
    destino = Path(sys.argv[1])
    original = gerar()
    for n in TAMANHOS:
        pasta = destino / f"{n}x{n}" / "apps"
        pasta.mkdir(parents=True, exist_ok=True)
        original.resize((n, n), Image.Resampling.LANCZOS).save(pasta / "robofael.png")
    print(f"ícones gerados em {destino}")
