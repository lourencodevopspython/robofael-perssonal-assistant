"""Fixtures e dublês compartilhados pelos testes."""

from __future__ import annotations

import gc
import threading
import wave
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from robofael.avatar.catalogo import AVATARES
from robofael.configuracao import Configuracao
from robofael.dominio.agenda import Agenda
from robofael.dominio.modelos import DadosAgenda
from robofael.portas import Faixa

AGORA = datetime(2026, 10, 21, 16, 25)  # uma quarta-feira


class Relogio:
    """Relógio controlável."""

    def __init__(self, inicio: datetime = AGORA):
        self.agora = inicio

    def __call__(self) -> datetime:
        return self.agora


class RepositorioMemoria:
    """Repositório em memória que também guarda o histórico (como o SQLite)."""

    def __init__(self, dados: DadosAgenda | None = None):
        self.dados = dados or DadosAgenda()
        self.salvamentos = 0
        self.historico: list = []

    def carregar(self) -> DadosAgenda:
        return self.dados

    def salvar(self, dados: DadosAgenda, eventos=()) -> None:
        self.salvamentos += 1
        self.historico.extend(eventos)

    def eventos(self, inicio, fim, tipos=None):
        return [e for e in self.historico if inicio <= e.ocorrido_em < fim and (tipos is None or e.tipo in tipos)]


@pytest.fixture(autouse=True)
def casa_isolada(tmp_path_factory, monkeypatch):
    """Nenhum teste mexe na pasta pessoal de verdade (atalho de inicialização, comandos em ~/.local/bin)."""
    casa = tmp_path_factory.mktemp("casa")
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(casa / ".config"))
    return casa


@pytest.fixture
def relogio():
    return Relogio()


@pytest.fixture
def repositorio():
    return RepositorioMemoria()


@pytest.fixture
def agenda(repositorio, relogio):
    return Agenda(repositorio, relogio)


# ---------- Claude falso (streaming) ----------
def bloco_texto(texto):
    return SimpleNamespace(type="text", text=texto)


def bloco_ferramenta(nome, entrada, id_="toolu_1"):
    return SimpleNamespace(type="tool_use", name=nome, input=entrada, id=id_)


def resposta(stop_reason, *blocos):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocos))


class StreamFalso:
    def __init__(self, final):
        self.final = final
        # Cada palavra dos blocos de texto vira um evento de streaming
        self.eventos = [SimpleNamespace(type="text", text=palavra + " ")
                        for b in final.content if b.type == "text" for palavra in b.text.split()]

    def __iter__(self):
        return iter(self.eventos)

    def get_final_message(self):
        return self.final


class ClienteFalso:
    """Imita `client.beta.messages.stream(...)`: cada rodada é uma resposta roteirizada
    (ou uma exceção). A última rodada se repete se acabarem."""

    def __init__(self, *rodadas):
        self.rodadas = list(rodadas)
        self.chamadas: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    @contextmanager
    def _stream(self, **kwargs):
        self.chamadas.append({**kwargs, "messages": list(kwargs["messages"])})
        r = self.rodadas.pop(0) if len(self.rodadas) > 1 else self.rodadas[0]
        if isinstance(r, Exception):
            raise r
        yield StreamFalso(r)


@pytest.fixture
def cliente_falso():
    return ClienteFalso


# ---------- Voz falsa ----------
class SintetizadorFalso:
    def __init__(self, atraso: float = 0.0, falhar_em: str | None = None):
        self.textos: list[str] = []
        self.atraso, self.falhar_em = atraso, falhar_em

    def sintetizar(self, texto: str) -> bytes:
        if self.falhar_em and self.falhar_em in texto:
            raise RuntimeError("falha de síntese")
        if self.atraso:
            threading.Event().wait(self.atraso)
        self.textos.append(texto)
        return texto.encode()


class ReprodutorFalso:
    def __init__(self, duracao: float = 0.0):
        self.amplitude = self.forma = 0.0
        self.tocadas: list[str] = []
        self.duracao = duracao
        self.ao_tocar = None  # gancho para os testes

    def preparar(self, audio: bytes) -> Faixa:
        return Faixa(duracao_s=self.duracao, volume=[0.5], timbre=[0.0], nativo=audio.decode())

    def sinal_ativacao(self) -> Faixa:
        return Faixa(duracao_s=0.0, volume=[], timbre=[], nativo="<sinal>")

    def tocar(self, faixa: Faixa, cancelar: threading.Event) -> None:
        self.tocadas.append(faixa.nativo)
        if self.ao_tocar:
            self.ao_tocar(faixa.nativo)
        cancelar.wait(self.duracao)


class ReconhecedorFalso:
    def __init__(self, *falas, transcricao=None):
        self.falas = list(falas)
        self.chamadas = 0
        self.transcricao = transcricao  # texto (ou exceção) devolvido por transcrever()
        self.ativador = None  # para checar que o microfone nunca é disputado
        self.microfone_disputado = False

    def transcrever(self, audio):
        if isinstance(self.transcricao, Exception):
            raise self.transcricao
        return self.transcricao

    def ouvir(self, cancelar, ao_nivel=None):
        self.chamadas += 1
        if self.ativador is not None and self.ativador.aberto:
            self.microfone_disputado = True
        if ao_nivel:
            ao_nivel(0.7)
        if not self.falas:
            cancelar.wait(5)
            return None
        fala = self.falas.pop(0)
        if isinstance(fala, Exception):
            raise fala
        return fala


# ---------- Áudio ----------
def tom_harmonico(freq, segundos=2.0, fs=16000, amplitude=3000.0):
    """Sinal periódico com 5 harmônicos, parecido com uma vogal sustentada."""
    t = np.arange(int(fs * segundos)) / fs
    return amplitude * sum(np.sin(2 * np.pi * freq * k * t) / k for k in range(1, 6)), fs


def salvar_wav(caminho, amostras, fs):
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        w.writeframes(np.asarray(amostras).astype(np.int16).tobytes())
    return caminho


class AtivadorFalso:
    """Detector de "ok Robofael": devolve as ativações roteirizadas; depois espera o cancelamento."""

    frase = "ok Fael"

    def __init__(self, *ativacoes):
        self.ativacoes = list(ativacoes)
        self.chamadas = 0
        self.aberto = False
        self.cancelamentos = 0

    def aguardar(self, cancelar):
        self.chamadas += 1
        self.aberto = True
        try:
            if self.ativacoes:
                a = self.ativacoes.pop(0)
                if isinstance(a, Exception):
                    raise a
                return a
            if cancelar.wait(5):
                self.cancelamentos += 1
            return None
        finally:
            self.aberto = False


@pytest.fixture
def raiz():
    """Janela Tk oculta para testes de interface (pula sem servidor gráfico)."""
    tk = pytest.importorskip("tkinter")
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("sem servidor gráfico")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass
    # A janela do teste forma ciclos de referência (barramento <-> interface) que seguram imagens
    # Tk. Recolhidos aqui, na thread principal: se o coletor rodasse numa thread de trabalho, o
    # __del__ das imagens chamaria o Tk fora da thread principal e travaria aquela thread.
    gc.collect()


# As fotos do avatar são pessoais e não vão para o repositório público: sem elas (ex.: na CI do GitHub),
# os testes que renderizam o avatar são pulados. Coloque as fotos em assets/avatares para rodá-los.
_PASTA_AVATARES = Configuracao.do_ambiente().pasta_avatares
FOTOS_PRESENTES = all((_PASTA_AVATARES / cfg[chave]).exists()
                      for cfg in AVATARES.values() for chave in ("arquivo", "arquivo_hd") if chave in cfg)
requer_fotos = pytest.mark.skipif(not FOTOS_PRESENTES,
                                  reason="fotos do avatar ausentes (pessoais, fora do repositório): assets/avatares")
