"""Canvas diferencial: só repassa ao Tk o que realmente mudou desde o último quadro.

No Tk, qualquer `coords`/`itemconfigure` marca a área do item como suja, e o redesenho dessa
área recompõe tudo o que está por baixo — inclusive imagens grandes com transparência, que o
Tk mistura pixel a pixel em software. Reenviar um valor igual custa o mesmo que mudar de verdade.
A cena guarda o último valor enviado de cada item e descarta o que se repete: com o assistente
parado, a maior parte dos quadros não envia nada ao Tk."""

from __future__ import annotations

import tkinter as tk
from typing import Any

_AUSENTE = object()


class CenaCanvas:
    def __init__(self, canvas: tk.Canvas):
        self.canvas = canvas
        self._coords: dict[int, tuple[int, ...]] = {}
        self._opcoes: dict[tuple[int, str], Any] = {}
        self.envios = 0  # chamadas efetivamente feitas ao Tk (diagnóstico e testes)

    def coords(self, item: int, *pontos: float) -> None:
        """Move o item; as coordenadas são arredondadas para pixels inteiros (o Tk desenha em pixels)."""
        inteiros = tuple(round(p) for p in pontos)
        if self._coords.get(item) != inteiros:
            self._coords[item] = inteiros
            self.envios += 1
            self.canvas.coords(item, *inteiros)

    def configurar(self, item: int, **opcoes: Any) -> None:
        """`itemconfigure` só com as opções cujo valor mudou."""
        mudancas = {k: v for k, v in opcoes.items() if self._opcoes.get((item, k), _AUSENTE) != v}
        if mudancas:
            for k, v in mudancas.items():
                self._opcoes[(item, k)] = v
            self.envios += 1
            self.canvas.itemconfigure(item, **mudancas)

