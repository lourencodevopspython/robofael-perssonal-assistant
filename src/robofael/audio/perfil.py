"""Perfil de voz do usuário: compara as gravações com a voz neural lendo as mesmas frases
e calcula o ajuste de tom (Hz) e ritmo (%) para a voz do assistente soar como a sua."""

import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np

from robofael.audio.analise import analisar_tom, ler_wav

log = logging.getLogger(__name__)

VOZES_CANDIDATAS = ["pt-BR-AntonioNeural", "pt-BR-FranciscaNeural", "pt-BR-ThalitaMultilingualNeural"]
LIMITE_TOM_HZ = 50  # ajustes maiores soam artificiais
LIMITE_RITMO_PCT = 30
TOLERANCIA_TOM_HZ = 3

FRASES = [
    "Bom dia! Hoje vou organizar minhas tarefas e começar pelo mais importante.",
    "Você pode me lembrar da reunião das três horas, por favor?",
    "A integração da API ficou pronta e os testes passaram sem erros.",
    "Que ótimo! Amanhã cedo eu reviso o documento e te mando um retorno.",
    "Antes de sair, preciso beber água, alongar e responder os e-mails.",
]


def formatar_tom(hz: float) -> str:
    return f"{int(round(hz)):+d}Hz"


def formatar_ritmo(pct: float) -> str:
    return f"{int(round(pct)):+d}%"


def medir_tts_edge(texto: str, voz: str, tom: str = "+0Hz", ritmo: str = "+0%") -> tuple[float | None, float]:
    """Sintetiza `texto` com a voz neural (edge-tts) e mede (tom, duração da fala)."""
    import asyncio
    import os
    import tempfile

    import edge_tts
    import pygame

    if not pygame.mixer.get_init():
        pygame.mixer.init()
    fd, caminho = tempfile.mkstemp(suffix=".mp3", prefix="robofael_teste_")
    os.close(fd)
    try:
        asyncio.run(edge_tts.Communicate(texto, voz, rate=ritmo, pitch=tom).save(caminho))
        a = pygame.sndarray.array(pygame.mixer.Sound(caminho)).astype(np.float64)
        if a.ndim > 1:
            a = a.mean(axis=1)
        return analisar_tom(a, pygame.mixer.get_init()[0])
    finally:
        os.remove(caminho)


def criar_perfil(gravacoes: Sequence[tuple[Path, str]], arquivo: Path,
                 medir_tts: Callable[..., tuple[float | None, float]] = medir_tts_edge,
                 vozes: Sequence[str] = VOZES_CANDIDATAS, progresso: Callable[[str], object] = log.info) -> dict:
    """Cria e salva o perfil a partir de [(caminho_wav, texto_lido), ...].

    1. mede o seu tom mediano e a duração da sua fala;
    2. escolhe a voz neural com tom natural mais próximo;
    3. ajusta o ritmo pela razão entre as durações;
    4. ajusta o tom iterativamente, medindo o resultado, até ficar a ±3 Hz."""
    tons, dur_usuario, textos = [], 0.0, []
    for caminho, texto in gravacoes:
        tom, dur = analisar_tom(*ler_wav(caminho))
        if tom:
            tons.append(tom)
            dur_usuario += dur
            textos.append(texto)
    if not tons:
        raise ValueError("Não consegui medir sua voz. Grave de novo, mais perto do microfone.")
    tom_usuario = float(np.median(tons))
    progresso(f"Seu tom médio: {tom_usuario:.0f} Hz")

    amostra = textos[0]
    medidas = {}
    for voz in vozes:
        tom, _ = medir_tts(amostra, voz)
        if tom:
            medidas[voz] = tom
            progresso(f"{voz}: {tom:.0f} Hz")
    if not medidas:
        raise RuntimeError("Não consegui medir as vozes do assistente (sem internet?).")
    voz = min(medidas, key=lambda v: abs(medidas[v] - tom_usuario))

    _, dur_tts = medir_tts(" ".join(textos), voz)
    ritmo = float(np.clip((dur_tts / dur_usuario - 1) * 100, -LIMITE_RITMO_PCT, LIMITE_RITMO_PCT))

    ajuste = float(np.clip(tom_usuario - medidas[voz], -LIMITE_TOM_HZ, LIMITE_TOM_HZ))
    tom_final: float | None = medidas[voz]
    for rodada in range(3):
        tom_final, _ = medir_tts(amostra, voz, formatar_tom(ajuste), formatar_ritmo(ritmo))
        if not tom_final:
            break
        progresso(f"Ajuste {formatar_tom(ajuste)} -> {tom_final:.0f} Hz")
        novo = float(np.clip(ajuste + (tom_usuario - tom_final), -LIMITE_TOM_HZ, LIMITE_TOM_HZ))
        if rodada == 2 or abs(tom_usuario - tom_final) < TOLERANCIA_TOM_HZ or round(novo) == round(ajuste):
            break
        ajuste = novo

    perfil = {
        "voz": voz,
        "tom": formatar_tom(ajuste),
        "ritmo": formatar_ritmo(ritmo),
        "tom_usuario_hz": round(tom_usuario, 1),
        "tom_voz_base_hz": round(medidas[voz], 1),
        "tom_resultante_hz": round(tom_final, 1) if tom_final else None,
    }
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(perfil, ensure_ascii=False, indent=2), encoding="utf-8")
    return perfil


def carregar_perfil(arquivo: Path) -> dict | None:
    """Perfil salvo, ou None se o usuário ainda não gravou a voz (ou o arquivo é inválido)."""
    try:
        return json.loads(Path(arquivo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
