"""Catálogo de avatares: arquivos de imagem e pontos do rosto medidos em cada foto."""

from typing import Any

# Coordenadas em pixels da imagem `arquivo` (pasta assets/avatares/):
#   cabeca        centro x e topo da cabeça
#   boca          centro da boca (linha entre os dentes)
#   largura_boca  largura da boca de canto a canto
#   queixo        altura (y) da ponta do queixo
#   abertura_max  descida máxima da mandíbula
#   pescoco       (centro x, altura da gola nas laterais, altura da gola na frente, meia largura)
#   nitidez       intensidade do filtro de nitidez (0..1)
# `arquivo_hd` (opcional) é a mesma foto em resolução maior, ainda com fundo: o recorte
# de `arquivo` é aplicado sobre ela.
AVATARES: dict[str, dict[str, Any]] = {
    "cracha": {
        "arquivo": "cracha.png",
        "cabeca": (246, 39),
        "boca": (232, 158),
        "largura_boca": 46,
        "queixo": 194,
        "abertura_max": 10,
        "pescoco": (246, 184, 224, 50),
        "nitidez": 1.0,
    },
    "selfie": {
        "arquivo": "selfie.png",
        "arquivo_hd": "selfie_hd.jpeg",
        "cabeca": (142, 135),
        "boca": (149, 259),
        "largura_boca": 58,
        "queixo": 296,
        "abertura_max": 12,
        "pescoco": (152, 280, 315, 52),
        "nitidez": 0.45,
    },
}
