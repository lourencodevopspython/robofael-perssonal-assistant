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
    # Ilustrações de 500x500 com a boca já aberta num sorriso: `boca` fica na fresta entre os dentes
    # de cima e os de baixo, para a fala abrir um vão escuro ali (e não por cima dos dentes)
    "cracha": {
        "arquivo": "cracha.png",
        "cabeca": (255, 6),
        "boca": (244, 162),
        "largura_boca": 56,
        "queixo": 218,
        "abertura_max": 9,
        "pescoco": (250, 222, 280, 42),
        "nitidez": 0.35,
    },
    "selfie": {
        "arquivo": "selfie.png",
        "cabeca": (245, 4),
        "boca": (250, 237),
        "largura_boca": 76,
        "queixo": 316,
        "abertura_max": 12,
        "pescoco": (252, 300, 410, 55),
        "nitidez": 0.35,
    },
}
