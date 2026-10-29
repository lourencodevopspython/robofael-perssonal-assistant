import numpy as np
import pytest

from conftest import salvar_wav, tom_harmonico
from robofael.audio.analise import analisar_tom, calcular_envelope, interpolar, ler_wav


@pytest.mark.parametrize("freq", [90, 115, 137, 220])
def test_mede_o_tom_de_um_sinal_periodico(freq):
    tom, duracao = analisar_tom(*tom_harmonico(freq))
    assert tom == pytest.approx(freq, rel=0.02)
    assert duracao == pytest.approx(2.0, abs=0.1)


def test_silencio_ou_ruido_nao_tem_tom():
    fs = 16000
    assert analisar_tom(np.zeros(fs), fs)[0] is None
    ruido = np.random.default_rng(0).normal(0, 1000, fs)
    assert analisar_tom(ruido, fs)[0] is None


@pytest.mark.parametrize("amostras", [np.array([]), np.ones(100)])
def test_sinal_curto_demais(amostras):
    assert analisar_tom(amostras, 16000) == (None, 0.0)


def test_mede_apenas_os_trechos_com_fala():
    voz, fs = tom_harmonico(120, segundos=1.0)
    com_pausa = np.concatenate([voz, np.zeros(fs), voz])
    tom, duracao = analisar_tom(com_pausa, fs)
    assert tom == pytest.approx(120, rel=0.02)
    assert duracao == pytest.approx(2.0, abs=0.15)  # a pausa de 1 s não conta


def test_le_wav(tmp_path):
    voz, fs = tom_harmonico(150, segundos=0.5)
    amostras, taxa = ler_wav(salvar_wav(tmp_path / "v.wav", voz, fs))
    assert taxa == fs and len(amostras) == len(voz)
    assert np.allclose(amostras, voz.astype(np.int16))


def test_envelope_tem_um_valor_por_quadro_e_acompanha_o_volume():
    fs = 16000
    alto, _ = tom_harmonico(200, segundos=0.5, fs=fs, amplitude=8000)
    baixo, _ = tom_harmonico(200, segundos=0.5, fs=fs, amplitude=800)
    volume, timbre = calcular_envelope(np.concatenate([alto, np.zeros(fs // 2), baixo]), fs, fps=60)

    assert len(volume) == len(timbre) == 90
    assert all(0 <= v <= 1 for v in volume) and all(-1 <= t <= 1 for t in timbre)
    v = np.array(volume)
    assert v[5:25].mean() > 0.8  # trecho alto
    assert v[35:55].max() == 0  # silêncio: boca fechada
    assert v[65:85].mean() < v[5:25].mean()  # trecho baixo abre menos


def test_timbre_distingue_vogal_fechada_de_aberta():
    """Energia em 250–1000 Hz (o/u) deve dar timbre menor que energia em 1–3 kHz (e/i)."""
    fs = 16000
    t = np.arange(fs // 2) / fs
    fechada = 5000 * np.sin(2 * np.pi * 400 * t)
    aberta = 5000 * np.sin(2 * np.pi * 2000 * t)
    _, timbre = calcular_envelope(np.concatenate([fechada, aberta, fechada, aberta]), fs, fps=60)
    timbre = np.array(timbre)
    assert timbre[5:25].mean() < -0.5
    assert timbre[35:55].mean() > 0.5


def test_envelope_de_audio_vazio():
    assert calcular_envelope(np.array([]), 16000) == ([], [])


@pytest.mark.parametrize("posicao, esperado", [(0, 0.0), (0.5, 0.5), (1.25, 0.75), (2.5, 0.0), (-1, 0.0)])
def test_interpolacao_linear_entre_quadros(posicao, esperado):
    assert interpolar([0.0, 1.0, 0.0], posicao) == pytest.approx(esperado)


def test_rms_de_bloco_pcm16():
    from robofael.audio.analise import rms_pcm16

    bloco = (np.ones(512, dtype=np.int16) * 1000).tobytes()
    assert rms_pcm16(bloco) == pytest.approx(1000)
    assert rms_pcm16(b"") == 0.0
    assert rms_pcm16(bloco + b"\x01") == pytest.approx(1000)  # byte solto ignorado


# ---------- Corte do silêncio das pontas ----------
def test_corta_o_silencio_das_pontas_com_margens():
    from robofael.audio.analise import MARGEM_FIM_S, MARGEM_INICIO_S, limites_da_fala

    fs = 16000
    t = np.arange(int(fs * 1.0)) / fs
    fala = 8000 * np.sin(2 * np.pi * 180 * t)
    audio = np.concatenate([np.zeros(int(fs * 0.25)), fala, np.zeros(int(fs * 1.2))])  # como sai do edge-tts
    inicio, fim = limites_da_fala(audio, fs)
    assert inicio == pytest.approx(fs * (0.25 - MARGEM_INICIO_S), abs=fs * 0.011)
    assert fim == pytest.approx(fs * (1.25 + MARGEM_FIM_S), abs=fs * 0.011)


def test_consoante_fraca_no_inicio_nao_e_cortada():
    from robofael.audio.analise import limites_da_fala

    fs = 16000
    sibilante = 400 * np.random.default_rng(1).standard_normal(int(fs * 0.12))  # "s" de "São", ~-26 dB
    vogal = 8000 * np.sin(2 * np.pi * 180 * np.arange(int(fs * 0.5)) / fs)
    audio = np.concatenate([np.zeros(int(fs * 0.3)), sibilante, vogal])
    inicio, _ = limites_da_fala(audio, fs)
    assert inicio <= fs * 0.3


@pytest.mark.parametrize("audio", [np.zeros(16000), np.zeros(10), np.array([])])
def test_sem_fala_devolve_o_audio_inteiro(audio):
    from robofael.audio.analise import limites_da_fala

    assert limites_da_fala(audio, 16000) == (0, len(audio))
