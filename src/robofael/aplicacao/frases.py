"""Divide o texto que chega em streaming em frases prontas para a síntese de voz.

Falar frase a frase permite começar a tocar a primeira enquanto as seguintes ainda estão
sendo geradas. A primeira frase pode ser cortada mais cedo (numa vírgula) para reduzir a
latência até a primeira palavra; frases curtas demais são juntadas à seguinte para a voz
não ficar picotada."""

from __future__ import annotations

import re

# Só corta quando já chegou o espaço seguinte: "3." pode virar "3.5" no próximo pedaço
_FIM = re.compile(r"[.!?…]+[\"')\]]*(?=\s)|\n+")
_VIRGULA = re.compile(r"[,;:](?=\s)")
_ABREVIACOES = ("sr.", "sra.", "dr.", "dra.", "prof.", "ex.", "etc.", "obs.", "aprox.", "n.º", "nº.")


class DivisorFrases:
    def __init__(self, minimo: int = 24, primeira_virgula_apos: int = 45):
        self.minimo = minimo
        self.primeira_virgula_apos = primeira_virgula_apos
        self._buffer = ""
        self._emitidas = 0

    def adicionar(self, pedaco: str) -> list[str]:
        """Recebe mais texto e devolve as frases que ficaram completas."""
        self._buffer += pedaco
        prontas = []
        while (frase := self._extrair()) is not None:
            prontas.append(frase)
        return prontas

    def finalizar(self) -> list[str]:
        """Devolve o que restou no buffer (fim da resposta)."""
        resto, self._buffer = self._buffer.strip(), ""
        if resto:
            self._emitidas += 1
            return [resto]
        return []

    def _extrair(self) -> str | None:
        inicio = 0
        for m in _FIM.finditer(self._buffer):
            fim = m.end()
            candidata = self._buffer[:fim].strip()
            if self._eh_abreviacao(candidata):
                continue
            if len(candidata) < self.minimo:
                inicio = fim
                continue  # curta demais: junta com a próxima
            return self._emitir(fim)
        if self._emitidas == 0 and len(self._buffer) > self.primeira_virgula_apos:
            for m in _VIRGULA.finditer(self._buffer, max(inicio, self.minimo)):
                return self._emitir(m.end())
        return None

    def _emitir(self, fim: int) -> str:
        frase, self._buffer = self._buffer[:fim].strip(), self._buffer[fim:].lstrip()
        self._emitidas += 1
        return frase

    @staticmethod
    def _eh_abreviacao(candidata: str) -> bool:
        ultima = candidata.rsplit(maxsplit=1)[-1].lower() if candidata else ""
        return ultima in _ABREVIACOES
