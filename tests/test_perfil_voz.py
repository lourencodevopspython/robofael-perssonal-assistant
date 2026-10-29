import numpy as np
import pytest

from conftest import salvar_wav, tom_harmonico
from robofael.audio.perfil import (
    LIMITE_RITMO_PCT,
    LIMITE_TOM_HZ,
    carregar_perfil,
    criar_perfil,
    formatar_ritmo,
    formatar_tom,
)

TONS_BASE = {"pt-BR-AntonioNeural": 137.0, "pt-BR-FranciscaNeural": 241.0, "pt-BR-ThalitaMultilingualNeural": 180.0}


class TTSFalso:
    """Simula a voz neural: o ajuste em Hz move o tom em 87,5% (como medido no edge-tts real)
    e o ritmo em % encurta/alonga a fala proporcionalmente."""

    def __init__(self, segundos_por_frase=2.0):
        self.segundos_por_frase = segundos_por_frase
        self.chamadas = []

    def __call__(self, texto, voz, tom="+0Hz", ritmo="+0%"):
        self.chamadas.append((voz, tom, ritmo))
        frases = max(1, texto.count(".") + texto.count("?") + texto.count("!"))
        duracao = self.segundos_por_frase * frases / (1 + int(ritmo[:-1]) / 100)
        return TONS_BASE[voz] + 0.875 * int(tom[:-2]), duracao


def gravacoes(tmp_path, freq, segundos, quantidade=3):
    saida = []
    for i in range(quantidade):
        voz, fs = tom_harmonico(freq, segundos=segundos)
        saida.append((salvar_wav(tmp_path / f"f{i}.wav", voz, fs), f"Frase número {i}."))
    return saida


@pytest.mark.parametrize("valor, esperado", [(-22.4, "-22Hz"), (0, "+0Hz"), (7.6, "+8Hz")])
def test_formata_tom(valor, esperado):
    assert formatar_tom(valor) == esperado


@pytest.mark.parametrize("valor, esperado", [(-14.2, "-14%"), (0, "+0%"), (12.5, "+12%")])
def test_formata_ritmo(valor, esperado):
    assert formatar_ritmo(valor) == esperado


def test_cria_perfil_grave_e_mais_lento_que_a_voz_base(tmp_path):
    arquivo = tmp_path / "perfil.json"
    perfil = criar_perfil(gravacoes(tmp_path, 115, segundos=2.3), arquivo=arquivo,
                          medir_tts=TTSFalso(segundos_por_frase=2.0), progresso=lambda _: None)

    assert perfil["voz"] == "pt-BR-AntonioNeural"  # tom mais próximo de 115 Hz
    assert perfil["tom_usuario_hz"] == pytest.approx(115, abs=2)
    assert int(perfil["tom"][:-2]) < 0  # voz mais grave
    assert perfil["tom_resultante_hz"] == pytest.approx(115, abs=3)  # convergiu na tolerância
    assert int(perfil["ritmo"][:-1]) == pytest.approx(-13, abs=2)  # 2,0 s vs 2,3 s
    assert carregar_perfil(arquivo) == perfil


def test_voz_aguda_escolhe_voz_base_feminina(tmp_path):
    perfil = criar_perfil(gravacoes(tmp_path, 235, segundos=2.0), arquivo=tmp_path / "p.json",
                          medir_tts=TTSFalso(), progresso=lambda _: None)
    assert perfil["voz"] == "pt-BR-FranciscaNeural"
    assert abs(int(perfil["tom"][:-2])) <= 10


def test_ajustes_respeitam_os_limites(tmp_path):
    perfil = criar_perfil(gravacoes(tmp_path, 75, segundos=6.0), arquivo=tmp_path / "p.json",
                          medir_tts=TTSFalso(segundos_por_frase=2.0), progresso=lambda _: None)
    assert int(perfil["tom"][:-2]) == -LIMITE_TOM_HZ
    assert int(perfil["ritmo"][:-1]) == -LIMITE_RITMO_PCT


def test_gravacoes_sem_voz_geram_erro_claro(tmp_path):
    silencio = [(salvar_wav(tmp_path / "s.wav", np.zeros(16000), 16000), "Frase.")]
    with pytest.raises(ValueError, match="Grave de novo"):
        criar_perfil(silencio, arquivo=tmp_path / "p.json", medir_tts=TTSFalso())
    assert not (tmp_path / "p.json").exists()


def test_sem_acesso_as_vozes_gera_erro(tmp_path):
    with pytest.raises(RuntimeError, match="sem internet"):
        criar_perfil(gravacoes(tmp_path, 120, 2.0, 1), arquivo=tmp_path / "p.json",
                     medir_tts=lambda *a: (None, 0.0), progresso=lambda _: None)


def test_carregar_perfil_inexistente_ou_corrompido(tmp_path):
    assert carregar_perfil(tmp_path / "nao_existe.json") is None
    corrompido = tmp_path / "ruim.json"
    corrompido.write_text("{ isto não é json")
    assert carregar_perfil(corrompido) is None
