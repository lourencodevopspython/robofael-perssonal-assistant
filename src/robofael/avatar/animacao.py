"""Lógica de animação da boca, independente da interface (pura e testável)."""

from robofael.avatar.renderizador import FORMAS

REDONDA, NEUTRA, ABERTA = range(len(FORMAS))


def suavizar_boca(atual: float, alvo: float, dt: float = 1 / 60, ataque: float = 0.45, liberacao: float = 0.2) -> float:
    """Persegue o volume da voz: abre rápido (ataque) e fecha devagar (liberação), como numa
    fala real. Os fatores valem por quadro a 60 fps e são corrigidos pelo `dt` real, então o
    movimento não muda se a taxa de quadros oscilar."""
    fator = ataque if alvo > atual else liberacao
    fator = 1 - (1 - fator) ** (dt * 60)
    return atual + (alvo - atual) * fator


def nivel_boca(abertura: float, niveis: int) -> int:
    """Converte a abertura contínua (0..1) no índice do quadro mais próximo."""
    return max(0, min(niveis - 1, round(abertura * (niveis - 1))))


class SeletorForma:
    """Escolhe o formato da boca pelo timbre da vogal, com histerese e tempo mínimo
    em cada formato para não ficar alternando a cada quadro."""

    def __init__(self, limiar_redonda: float = -0.45, limiar_aberta: float = 0.55, permanencia: float = 0.09,
                 boca_fechada: float = 0.08) -> None:
        self.limiar_redonda = limiar_redonda
        self.limiar_aberta = limiar_aberta
        self.permanencia = permanencia
        self.boca_fechada = boca_fechada
        self.forma = NEUTRA
        self.desde = float("-inf")

    def atualizar(self, timbre: float, abertura: float, t: float) -> int:
        """`timbre` em -1..1 (o/u .. e/i), `abertura` em 0..1 e `t` em segundos."""
        if abertura < self.boca_fechada:
            alvo = NEUTRA
        elif timbre < self.limiar_redonda:
            alvo = REDONDA
        elif timbre > self.limiar_aberta:
            alvo = ABERTA
        else:
            alvo = NEUTRA
        # Saltos entre extremos (o -> e) acontecem logo; trocas vizinhas esperam a permanência
        if alvo != self.forma and (t - self.desde >= self.permanencia or abs(alvo - self.forma) == 2):
            self.forma, self.desde = alvo, t
        return self.forma
