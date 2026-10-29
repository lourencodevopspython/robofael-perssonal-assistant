"""Ganho automático para microfones com volume de entrada baixo."""

import numpy as np
import pytest

from robofael.audio.ganho import GANHO_MAXIMO, PICO_BAIXO, GanhoAutomatico, pico_pcm16


def bloco(amplitude, n=1600):
    t = np.arange(n) / 16000
    return (np.sin(2 * np.pi * 200 * t) * amplitude).astype(np.int16).tobytes()


def test_sem_fala_medida_usa_ganho_inicial_pelo_ruido():
    assert GanhoAutomatico().ganho == 1.0
    assert GanhoAutomatico(rms_ruido=20).ganho == 4.0  # sala silenciosa / microfone baixo
    assert GanhoAutomatico(rms_ruido=500).ganho == 1.0  # nunca atenua


def test_ganho_leva_a_voz_baixa_ao_nivel_alvo_com_limite():
    g = GanhoAutomatico()
    for _ in range(40):
        g.observar_fala(1000)
    assert g.ganho == pytest.approx(8.0, rel=0.01)
    g2 = GanhoAutomatico()
    for _ in range(40):
        g2.observar_fala(300)
    assert g2.ganho == GANHO_MAXIMO  # limitado: não amplifica ruído sem fim
    g3 = GanhoAutomatico()
    g3.observar_fala(20000)
    assert g3.ganho == 1.0  # voz forte: não mexe


def test_media_movel_nao_oscila_com_um_pico_isolado():
    g = GanhoAutomatico()
    for _ in range(40):
        g.observar_fala(2000)
    g.observar_fala(30000)  # uma batida no microfone
    assert g.ganho > 2.5


def test_aplica_ganho_sem_estourar():
    g = GanhoAutomatico()
    g.observar_fala(1000)
    amplificado = g.aplicar(bloco(1000))
    assert pico_pcm16(amplificado) == pytest.approx(8000, rel=0.02)
    for _ in range(40):
        g.observar_fala(100)
    assert pico_pcm16(g.aplicar(bloco(30000))) >= 32767  # satura em vez de dar a volta
    assert GanhoAutomatico().aplicar(b"\x01") == b"\x01"


def test_detecta_voz_baixa():
    g = GanhoAutomatico()
    assert not g.voz_baixa
    for _ in range(30):
        g.observar_fala(580)  # o nível medido no microfone interno a 37%
    assert g.voz_baixa and g.pico_fala < PICO_BAIXO
    for _ in range(60):
        g.observar_fala(4000)
    assert not g.voz_baixa


def test_pico():
    assert pico_pcm16(bloco(1234)) == pytest.approx(1234, abs=2)
    assert pico_pcm16(b"") == 0.0
