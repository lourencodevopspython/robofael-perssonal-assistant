import threading
import time

import pytest

from conftest import ReconhecedorFalso, ReprodutorFalso, SintetizadorFalso
from robofael.aplicacao.barramento import Barramento
from robofael.aplicacao.orquestrador import MSG_FALHA, Orquestrador
from robofael.dominio.estados import Estado
from robofael.dominio.eventos import (
    Aviso,
    EstadoMudou,
    FalaReconhecida,
    Gravidade,
    NivelMicrofone,
    RespostaConcluida,
    RespostaParcial,
)


class ModeloRoteirizado:
    """Gera os pedaços dados; registra se o gerador foi fechado (cancelamento)."""

    online = True

    def __init__(self, *pedacos, antes_de=None):
        self.pedacos = pedacos
        self.antes_de = antes_de or {}  # índice -> callable executado antes de entregar o pedaço
        self.fechado = False
        self.falas: list[str] = []

    def reiniciar(self):
        pass

    def responder(self, fala):
        self.falas.append(fala)
        try:
            for i, p in enumerate(self.pedacos):
                if i in self.antes_de:
                    self.antes_de[i]()
                yield p
        finally:
            self.fechado = True


class Cenario:
    def __init__(self, modelo, reconhecedor=None, continuo=False, sintetizador=None, reprodutor=None):
        self.barramento = Barramento()
        self.eventos: list = []
        for tipo in (EstadoMudou, FalaReconhecida, RespostaParcial, RespostaConcluida, NivelMicrofone, Aviso):
            self.barramento.assinar(tipo, self.eventos.append)
        self.modelo = modelo
        self.sintetizador = sintetizador or SintetizadorFalso()
        self.reprodutor = reprodutor or ReprodutorFalso()
        self.orq = Orquestrador(modelo, self.sintetizador, self.reprodutor, self.barramento, reconhecedor, continuo)
        self.orq.estados.ir_para(Estado.PARADO)

    def concluir(self, timeout=20.0):
        limite = time.monotonic() + timeout
        while self.orq.ocupado and time.monotonic() < limite:
            time.sleep(0.005)
        self.orq.aguardar()
        assert not self.orq.ocupado, "a interação não terminou"
        self.barramento.despachar()
        return self

    def de_tipo(self, tipo):
        return [e for e in self.eventos if isinstance(e, tipo)]

    @property
    def estados(self):
        return [e.estado for e in self.de_tipo(EstadoMudou)]


def test_texto_vira_fala_frase_a_frase_com_estados_corretos():
    c = Cenario(ModeloRoteirizado("Anotei a tarefa de revisar o PR. ", "Quer que eu crie um lembrete? "))
    assert c.orq.enviar_texto("anota revisar o PR")
    c.concluir()
    assert c.reprodutor.tocadas == ["Anotei a tarefa de revisar o PR.", "Quer que eu crie um lembrete?"]
    assert c.estados == [Estado.PARADO, Estado.PENSANDO, Estado.FALANDO, Estado.PARADO]
    assert c.de_tipo(FalaReconhecida)[0].texto == "anota revisar o PR"
    assert c.de_tipo(RespostaParcial)[-1].texto.startswith("Anotei")
    final = c.de_tipo(RespostaConcluida)[0]
    assert final.texto.endswith("lembrete?") and not final.interrompida


def test_primeira_frase_toca_antes_de_o_modelo_terminar():
    """Pipeline: o modelo só entrega a 2ª frase depois que a 1ª começou a tocar.
    Num fluxo serial isso travaria (e o teste estouraria o tempo)."""
    primeira_tocou = threading.Event()
    reprodutor = ReprodutorFalso()
    reprodutor.ao_tocar = lambda texto: primeira_tocou.set()
    modelo = ModeloRoteirizado("Esta é a primeira frase da resposta. ", "E esta é a segunda frase.",
                               antes_de={1: lambda: primeira_tocou.wait(3) or pytest.fail("sem pipeline")})
    c = Cenario(modelo, reprodutor=reprodutor)
    c.orq.enviar_texto("oi")
    c.concluir()
    assert len(reprodutor.tocadas) == 2


def test_interromper_corta_a_fala_e_fecha_o_streaming():
    reprodutor = ReprodutorFalso(duracao=5.0)
    c = Cenario(ModeloRoteirizado("Primeira frase bem comprida aqui. ", "Segunda frase que não deve tocar. "),
                reprodutor=reprodutor)
    reprodutor.ao_tocar = lambda _: c.orq.interromper()
    inicio = time.monotonic()
    c.orq.enviar_texto("oi")
    c.concluir()
    assert time.monotonic() - inicio < 2.0  # não esperou os 5 s da faixa
    assert reprodutor.tocadas == ["Primeira frase bem comprida aqui."]
    assert c.de_tipo(RespostaConcluida)[0].interrompida
    assert c.estados[-1] is Estado.PARADO
    c.orq.enviar_texto("de novo")  # a próxima interação espera o estágio cancelado terminar
    c.concluir()
    assert c.modelo.fechado


def test_ouvir_publica_nivel_do_microfone_e_responde():
    c = Cenario(ModeloRoteirizado("Agora são quatro horas da tarde. "), ReconhecedorFalso("que horas são"))
    c.orq.ouvir()
    c.concluir()
    assert c.estados[:3] == [Estado.PARADO, Estado.OUVINDO, Estado.PARADO]
    assert Estado.FALANDO in c.estados
    assert any(e.nivel > 0 for e in c.de_tipo(NivelMicrofone))
    assert c.de_tipo(NivelMicrofone)[-1].nivel == 0.0  # medidor zerado ao terminar
    assert c.modelo.falas == ["que horas são"]


def test_silencio_volta_a_parado_sem_chamar_o_modelo():
    rec = ReconhecedorFalso()
    c = Cenario(ModeloRoteirizado("x"), rec)
    c.orq.ouvir()
    time.sleep(0.05)
    c.orq.interromper()  # ESPAÇO de novo: cancela a escuta
    c.concluir()
    assert c.modelo.falas == [] and c.estados[-1] is Estado.PARADO


def test_sem_microfone_avisa():
    c = Cenario(ModeloRoteirizado("x"))
    assert c.orq.ouvir() is False
    c.barramento.despachar()
    assert c.de_tipo(Aviso)[0].gravidade is Gravidade.ERRO


def test_erro_no_reconhecimento_vira_aviso():
    c = Cenario(ModeloRoteirizado("x"), ReconhecedorFalso(RuntimeError("sem internet")))
    c.orq.ouvir()
    c.concluir()
    assert c.de_tipo(Aviso)[0].mensagem == "sem internet"
    assert c.estados[-1] is Estado.PARADO


def test_modo_continuo_conversa_ate_a_despedida():
    rec = ReconhecedorFalso("que dia é hoje", "tchau", "isto não deve ser ouvido")
    c = Cenario(ModeloRoteirizado("Resposta curta mas completa. "), rec, continuo=True)
    c.orq.ouvir()
    c.concluir()
    assert c.modelo.falas == ["que dia é hoje", "tchau"]
    assert rec.chamadas == 2


def test_anuncio_espera_a_interacao_atual_terminar():
    reprodutor = ReprodutorFalso(duracao=0.2)
    c = Cenario(ModeloRoteirizado("Esta é a resposta para você agora. "), reprodutor=reprodutor)
    c.orq.enviar_texto("oi")
    c.orq.anunciar("Rafael, lembrete: beber água.")  # chega no meio da resposta
    c.concluir()
    time.sleep(0.05)
    c.concluir()
    assert reprodutor.tocadas == ["Esta é a resposta para você agora.", "Rafael, lembrete: beber água."]


def test_uma_interacao_por_vez_e_texto_novo_interrompe_a_atual():
    """Digitar durante a resposta interrompe e atende o pedido novo, em sequência (nunca em paralelo)."""
    c = Cenario(ModeloRoteirizado("Uma resposta qualquer de exemplo. "), reprodutor=ReprodutorFalso(duracao=0.3))
    simultaneas, maximo = [0], [0]
    original = c.modelo.responder

    def responder(fala):
        simultaneas[0] += 1
        maximo[0] = max(maximo[0], simultaneas[0])
        try:
            yield from original(fala)
        finally:
            simultaneas[0] -= 1

    c.modelo.responder = responder
    assert c.orq.enviar_texto("primeira")
    assert c.orq.enviar_texto("segunda")  # aceito: interrompe a primeira
    assert not c.orq.enviar_texto("   ")
    c.concluir()
    assert c.modelo.falas == ["primeira", "segunda"] and maximo[0] == 1
    concluidas = c.de_tipo(RespostaConcluida)
    assert concluidas[0].interrompida and not concluidas[-1].interrompida


def test_so_o_pedido_mais_recente_digitado_durante_a_fala_e_atendido():
    c = Cenario(ModeloRoteirizado("Uma resposta qualquer de exemplo. "), reprodutor=ReprodutorFalso(duracao=0.3))
    c.orq.enviar_texto("primeira")
    c.orq.enviar_texto("segunda")
    c.orq.enviar_texto("terceira")
    c.concluir()
    assert c.modelo.falas == ["primeira", "terceira"]


def test_texto_durante_a_escuta_cancela_o_microfone_e_e_atendido():
    rec = ReconhecedorFalso()  # sem falas: fica ouvindo até ser cancelado
    c = Cenario(ModeloRoteirizado("Pronto, anotado. "), reconhecedor=rec)
    assert c.orq.ouvir()
    esperar_estado = time.monotonic() + 5
    while c.orq.estados.atual is not Estado.OUVINDO and time.monotonic() < esperar_estado:
        time.sleep(0.005)
    assert c.orq.enviar_texto("anota tarefa revisar o PR")
    c.concluir()
    assert c.modelo.falas == ["anota tarefa revisar o PR"]


def test_falha_do_modelo_vira_frase_de_desculpas():
    def explodir():
        raise RuntimeError("boom")

    c = Cenario(ModeloRoteirizado("Começando a responder sua pergunta. ", "nunca", antes_de={1: explodir}))
    c.orq.enviar_texto("oi")
    c.concluir()
    assert c.reprodutor.tocadas == ["Começando a responder sua pergunta.", MSG_FALHA]
    assert c.estados[-1] is Estado.PARADO


def test_falha_de_sintese_pula_a_frase_e_segue():
    c = Cenario(ModeloRoteirizado("Frase que vai falhar na síntese. ", "Frase que deve tocar normalmente. "),
                sintetizador=SintetizadorFalso(falhar_em="falhar"))
    c.orq.enviar_texto("oi")
    c.concluir()
    assert c.reprodutor.tocadas == ["Frase que deve tocar normalmente."]


def test_resposta_vazia_nao_trava_em_pensando():
    c = Cenario(ModeloRoteirizado())
    c.orq.enviar_texto("oi")
    c.concluir()
    assert c.estados == [Estado.PARADO, Estado.PENSANDO, Estado.PARADO]


def test_alternar_microfone_interrompe_quando_falando():
    reprodutor = ReprodutorFalso(duracao=5.0)
    c = Cenario(ModeloRoteirizado("Uma resposta longa sendo falada agora. "), ReconhecedorFalso(),
                reprodutor=reprodutor)
    reprodutor.ao_tocar = lambda _: c.orq.alternar_microfone()
    c.orq.enviar_texto("oi")
    c.concluir()
    assert c.de_tipo(RespostaConcluida)[0].interrompida


def test_interromper_logo_apos_comecar_nunca_se_perde():
    """ESPAÇO duas vezes bem rápido: o cancelamento vale mesmo se a thread ainda nem começou."""
    for _ in range(50):
        c = Cenario(ModeloRoteirizado("x"), ReconhecedorFalso())  # ouviria por 5 s se não cancelasse
        c.orq.ouvir()
        c.orq.interromper()
        inicio = time.monotonic()
        c.concluir()
        assert time.monotonic() - inicio < 1.0
