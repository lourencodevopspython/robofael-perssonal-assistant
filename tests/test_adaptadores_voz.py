"""Sintetizador e reprodutor com rede e pygame substituídos por dublês."""

import threading

import pytest

from robofael.adaptadores import reprodutor as mod_reprodutor
from robofael.adaptadores.sintetizador import SintetizadorEdge
from robofael.portas import Faixa


class EdgeFalso:
    def __init__(self, falhar=False):
        self.chamadas, self.falhar = 0, falhar

    async def __call__(self, texto):
        self.chamadas += 1
        if self.falhar:
            raise ConnectionError("sem rede")
        return f"mp3:{texto}".encode()


@pytest.fixture
def sintetizador(tmp_path, monkeypatch):
    s = SintetizadorEdge("pt-BR-AntonioNeural", "-10Hz", "+5%", tmp_path / "tts", max_itens_cache=3)
    s.edge = EdgeFalso()
    monkeypatch.setattr(s, "_edge", s.edge)
    return s


def test_sintetiza_e_reaproveita_do_cache(sintetizador):
    assert sintetizador.sintetizar("Olá") == "mp3:Olá".encode()
    assert sintetizador.sintetizar("Olá") == "mp3:Olá".encode()
    assert sintetizador.edge.chamadas == 1


def test_cache_considera_voz_tom_e_ritmo(sintetizador, tmp_path, monkeypatch):
    sintetizador.sintetizar("Olá")
    outro = SintetizadorEdge("pt-BR-AntonioNeural", "+0Hz", "+5%", tmp_path / "tts")
    outro_edge = EdgeFalso()
    monkeypatch.setattr(outro, "_edge", outro_edge)
    outro.sintetizar("Olá")
    assert outro_edge.chamadas == 1  # tom diferente: não reaproveita


def test_cache_descarta_os_menos_usados(sintetizador):
    for texto in ("a", "b", "c", "d", "e"):
        sintetizador.sintetizar(texto)
    assert len(list(sintetizador.pasta_cache.glob("*.mp3"))) == 3
    assert not list(sintetizador.pasta_cache.glob("*.tmp"))


def test_sem_rede_usa_gtts_de_reserva(tmp_path, monkeypatch):
    s = SintetizadorEdge("v", pasta_cache=None)
    monkeypatch.setattr(s, "_edge", EdgeFalso(falhar=True))
    monkeypatch.setattr(SintetizadorEdge, "_gtts",
                        staticmethod(lambda texto, lang, tld: f"gtts:{lang}.{tld}:{texto}".encode()))
    assert s.sintetizar("oi") == b"gtts:pt.com.br:oi"
    s.configurar("en-US-AndrewNeural", "+0Hz", "+0%", ("en", "com"))
    assert s.sintetizar("hi") == b"gtts:en.com:hi"


# ---------- Reprodutor ----------
class CanalFalso:
    def __init__(self, reprodutor, quadros, ao_consultar=None):
        self.reprodutor, self.restantes, self.ao_consultar = reprodutor, quadros, ao_consultar
        self.amostras, self.parado = [], False

    def get_busy(self):
        self.amostras.append((self.reprodutor.amplitude, self.reprodutor.forma))
        if self.ao_consultar:
            self.ao_consultar(len(self.amostras))
        self.restantes -= 1
        return self.restantes > 0

    def stop(self):
        self.parado = True


@pytest.fixture
def reprodutor(monkeypatch):
    monkeypatch.setattr(mod_reprodutor.pygame.mixer, "get_init", lambda: (24000, -16, 1))
    monkeypatch.setattr(mod_reprodutor.time, "sleep", lambda s: None)
    return mod_reprodutor.ReprodutorPygame()


def faixa_com(canal):
    som = type("Som", (), {"play": lambda self: canal})()
    return Faixa(duracao_s=1.0, volume=[0.8] * 500, timbre=[-0.6] * 500, nativo=som)


def test_publica_volume_e_timbre_e_zera_no_fim(reprodutor):
    canal = CanalFalso(reprodutor, 5)
    reprodutor.tocar(faixa_com(canal), threading.Event())
    assert any(a == pytest.approx(0.8) and f == -0.6 for a, f in canal.amostras[1:])
    assert (reprodutor.amplitude, reprodutor.forma) == (0.0, 0.0) and canal.parado


def test_cancelamento_para_a_reproducao(reprodutor):
    cancelar = threading.Event()
    canal = CanalFalso(reprodutor, 1000, ao_consultar=lambda n: cancelar.set() if n == 3 else None)
    reprodutor.tocar(faixa_com(canal), cancelar)
    assert len(canal.amostras) == 3 and canal.parado


def test_preparar_decodifica_e_apara_o_silencio_das_pontas(monkeypatch):
    """Com o mixer real (driver de áudio fictício): a faixa sai sem o ~1 s de silêncio da voz sintetizada."""
    import io
    import wave

    import numpy as np

    monkeypatch.setenv("SDL_AUDIODRIVER", "dummy")
    pygame = mod_reprodutor.pygame
    pygame.mixer.quit()
    try:
        pygame.mixer.init(frequency=24000, size=-16, channels=1)
    except pygame.error:
        pytest.skip("mixer indisponível")
    try:
        fs = pygame.mixer.get_init()[0]
        tom = (8000 * np.sin(2 * np.pi * 220 * np.arange(fs) / fs)).astype(np.int16)  # 1 s de "fala"
        pcm = np.concatenate([np.zeros(fs // 4, np.int16), tom, np.zeros(fs, np.int16)])
        arquivo = io.BytesIO()
        with wave.open(arquivo, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(fs)
            w.writeframes(pcm.tobytes())
        faixa = mod_reprodutor.ReprodutorPygame().preparar(arquivo.getvalue())
        assert faixa.duracao_s == pytest.approx(1.0 + 0.03 + 0.15, abs=0.03)  # fala + margens
        assert max(faixa.volume) > 0.9 and len(faixa.volume) > 0
    finally:
        pygame.mixer.quit()
