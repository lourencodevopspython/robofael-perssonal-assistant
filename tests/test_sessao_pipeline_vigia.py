"""Colaboradores extraídos do orquestrador (pipeline de fala e vigia) e políticas da sessão."""

import threading
import time

from conftest import AtivadorFalso, ReprodutorFalso, SintetizadorFalso
from robofael import bootstrap
from robofael.aplicacao import sessao
from robofael.aplicacao.barramento import Barramento
from robofael.aplicacao.pipeline import PipelineFala
from robofael.aplicacao.vigia import FALHAS_SEGUIDAS_VIGIA, VigiaAtivacao
from robofael.configuracao import Configuracao
from robofael.dominio.eventos import Aviso, EscutaPassiva, RespostaParcial
from robofael.i18n import Idioma, Tradutor
from robofael.portas import Ativacao, Preferencias


def esperar(condicao, timeout=5.0):
    limite = time.monotonic() + timeout
    while not condicao() and time.monotonic() < limite:
        time.sleep(0.005)
    assert condicao()


def eventos(barramento, tipo):
    recebidos = []
    barramento.assinar(tipo, recebidos.append)
    return recebidos


# ---------- PipelineFala ----------
def test_pipeline_fala_frase_a_frase_e_publica_o_texto_parcial():
    barramento, reprodutor, tocando = Barramento(), ReprodutorFalso(), []
    parciais = eventos(barramento, RespostaParcial)
    pipeline = PipelineFala(SintetizadorFalso(), reprodutor, barramento, Tradutor(), lambda: tocando.append(1))
    primeira, segunda = "Bom dia, Rafael, tudo certo por aí? ", "Hoje você tem duas tarefas pendentes na agenda."
    fala = pipeline.falar([primeira, segunda], threading.Event())
    barramento.despachar()
    assert fala.texto == (primeira + segunda).strip() and not fala.interrompida
    assert reprodutor.tocadas == [primeira.strip(), segunda]  # uma faixa por frase
    assert tocando and parciais[-1].texto == fala.texto


def test_pipeline_cancelado_para_de_tocar_e_fecha_o_streaming():
    fechado = threading.Event()

    def fonte():
        try:
            yield "Esta é a primeira frase da resposta. "
            time.sleep(0.2)
            yield "E esta seria a segunda frase da resposta. "
        finally:
            fechado.set()

    cancelar = threading.Event()
    reprodutor = ReprodutorFalso()
    reprodutor.ao_tocar = lambda _faixa: cancelar.set()  # interrompe ao começar a primeira
    pipeline = PipelineFala(SintetizadorFalso(), reprodutor, Barramento(), Tradutor())
    fala = pipeline.falar(fonte(), cancelar)
    assert fala.interrompida and reprodutor.tocadas == ["Esta é a primeira frase da resposta."]
    pipeline.falar([], threading.Event())  # a próxima fala espera o estágio cancelado terminar
    assert fechado.is_set()


def test_pipeline_transforma_falha_do_modelo_em_frase_falada():
    def fonte():
        yield "Começando. "
        raise RuntimeError("caiu a conexão")

    reprodutor = ReprodutorFalso()
    fala = PipelineFala(SintetizadorFalso(), reprodutor, Barramento(), Tradutor()).falar(fonte(), threading.Event())
    assert reprodutor.tocadas[-1] == Tradutor()("orq.falha") and fala.texto.endswith(Tradutor()("orq.falha"))


# ---------- VigiaAtivacao ----------
def test_vigia_entrega_a_ativacao_e_nao_abre_o_microfone_durante_uma_interacao():
    ocupado, ativacoes = threading.Event(), []
    detector = AtivadorFalso(Ativacao("que horas são"))
    vigia = VigiaAtivacao(detector, Barramento(), Tradutor(), ocupado.is_set, ativacoes.append)
    vigia.ligar()
    esperar(lambda: ativacoes)
    assert ativacoes[0].comando == "que horas são"
    ocupado.set()  # começou uma interação: a vigia libera o microfone e não volta a abri-lo
    vigia.liberar_microfone()
    chamadas = detector.chamadas
    time.sleep(0.3)
    assert detector.chamadas <= chamadas + 1 and vigia.microfone_livre.is_set()
    vigia.encerrar()


def test_vigia_se_desliga_e_avisa_depois_de_falhas_seguidas():
    barramento = Barramento()
    avisos, escutas = eventos(barramento, Aviso), eventos(barramento, EscutaPassiva)
    detector = AtivadorFalso(*[OSError("microfone sumiu")] * FALHAS_SEGUIDAS_VIGIA)
    vigia = VigiaAtivacao(detector, barramento, Tradutor(), lambda: False, lambda _a: None)
    vigia.ligar()
    esperar(lambda: barramento.despachar() >= 0 and avisos, timeout=10)
    assert escutas[-1].frase is None and detector.chamadas == FALHAS_SEGUIDAS_VIGIA
    vigia.encerrar()


# ---------- Políticas da sessão ----------
class VozFalsa(SintetizadorFalso):
    voz, tom, ritmo = "pt-BR-AntonioNeural", "+0Hz", "+0%"

    def configurar(self, voz, tom, ritmo, gtts=None):
        self.voz, self.tom, self.ritmo, self.gtts = voz, tom, ritmo, gtts


class OrquestradorFalso:
    def __init__(self):
        self.vigia_ligada = True

    def iniciar_vigia(self):
        self.vigia_ligada = True

    def desligar_vigia(self):
        self.vigia_ligada = False


class LancadorVazio:
    def programas(self):
        return []

    def abrir(self, programa):
        raise AssertionError


def test_aplicar_preferencias_salva_e_aplica_idioma_voz_e_ativacao(tmp_path):
    config = Configuracao.do_ambiente({"ROBOFAEL_DADOS": str(tmp_path / "d"), "ROBOFAEL_CACHE": str(tmp_path / "c")})
    nucleo = bootstrap.montar_nucleo(config, LancadorVazio())
    voz, orq = VozFalsa(), OrquestradorFalso()
    servicos = sessao.Servicos(orq, None, False, True, True, voz)  # type: ignore[arg-type]

    sessao.aplicar_preferencias(nucleo, servicos, Preferencias("selfie", "en-US-JennyNeural", "+5Hz", "-10%",
                                                                False, "en-US"))
    assert nucleo.tradutor.idioma is Idioma.EN_US
    assert (voz.voz, voz.tom, voz.ritmo, voz.gtts) == ("en-US-JennyNeural", "+5Hz", "-10%", Idioma.EN_US.codigo_gtts)
    assert not orq.vigia_ligada
    assert bootstrap.montar_nucleo(config, LancadorVazio()).preferencias.idioma == "en-US"  # persistiu


def test_sem_servicos_as_preferencias_sao_so_salvas(tmp_path):
    config = Configuracao.do_ambiente({"ROBOFAEL_DADOS": str(tmp_path / "d"), "ROBOFAEL_CACHE": str(tmp_path / "c")})
    nucleo = bootstrap.montar_nucleo(config, LancadorVazio())
    sessao.aplicar_preferencias(nucleo, None, Preferencias(voz="pt-BR-FranciscaNeural", ativacao_por_voz=True))
    assert nucleo.banco.carregar_preferencias().voz == "pt-BR-FranciscaNeural"


def test_pipeline_sintetiza_frases_em_paralelo_e_toca_na_ordem():
    """A síntese é uma ida e volta pela rede: adiantar a próxima frase evita pausas entre frases curtas."""
    from robofael.aplicacao.pipeline import SINTESES_SIMULTANEAS

    class SintetizadorLento(SintetizadorFalso):
        def __init__(self):
            super().__init__()
            self.ativas, self.maximo, self.trava = 0, 0, threading.Lock()

        def sintetizar(self, texto):
            with self.trava:
                self.ativas += 1
                self.maximo = max(self.maximo, self.ativas)
            time.sleep(0.15 if "primeira" in texto else 0.05)  # a primeira demora mais que as seguintes
            with self.trava:
                self.ativas -= 1
            return super().sintetizar(texto)

    frases = ["Esta é a primeira frase da resposta. ", "Esta é a segunda frase da resposta. ",
              "E esta é a terceira frase, a última. "]
    sint, reprodutor = SintetizadorLento(), ReprodutorFalso()
    fala = PipelineFala(sint, reprodutor, Barramento(), Tradutor()).falar(frases, threading.Event())
    assert reprodutor.tocadas == [f.strip() for f in frases]  # a ordem é a das frases, não a de quem ficou pronto
    assert sint.maximo == SINTESES_SIMULTANEAS and not fala.interrompida
