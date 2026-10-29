"""Frase de ativação: gramática restrita ("ok Fael"), busca fonética, extração do comando
e escuta passiva no orquestrador."""

import time

import pytest

from conftest import AtivadorFalso, ReconhecedorFalso, ReprodutorFalso
from robofael.dominio.ativacao import (
    extrair_comando,
    gramatica_para,
    limpar_desconhecidas,
    localizar_ativacao,
    normalizar_fonetico,
)
from robofael.dominio.eventos import Aviso, EscutaPassiva, FalaReconhecida
from robofael.portas import Ativacao
from test_orquestrador import Cenario, ModeloRoteirizado

FRASE = "ok robofael"  # busca fonética livre (frases sem gramática calibrada)
FAEL = gramatica_para("ok Fael")


def test_ok_fael_tem_gramatica_calibrada_e_outras_frases_nao():
    assert FAEL is not None and gramatica_para("OK  fael") is FAEL
    assert gramatica_para("ok robofael") is None
    assert "[unk]" in FAEL.frases() and set(FAEL.aceitas) <= set(FAEL.frases())


# Saídas reais do Vosk com a gramática de "ok Fael" (vozes masculinas e femininas)
@pytest.mark.parametrize("saida, resto", [
    ("ok fel", ""), ("o que fel", ""), ("ok fiel", ""), ("ok fel [unk]", "[unk]"),
    ("o que fel que [unk]", "que [unk]"), ("ok fiel anota", "anota"),
])
def test_gramatica_reconhece_ok_fael(saida, resto):
    assert FAEL.analisar(saida) == resto


# Frases comuns e parecidas: o reconhecedor as encaixa nos distratores (0 de 115 dispararam)
@pytest.mark.parametrize("saida", [
    "o que fez", "o que falei", "ok falei", "o fiel", "ok rafael", "o que rafael", "foi o rafael que fez",
    "quero fel", "que fel", "que fiel", "o que", "ok", "ok feito", "o que foi", "o que falta fazer",
    "o que fica", "fala", "", "o que feliz",
])
def test_gramatica_nao_dispara_com_frases_comuns(saida):
    assert FAEL.analisar(saida) is None


def test_limpa_trechos_desconhecidos():
    assert limpar_desconhecidas("[unk] que [unk] horas") == "que horas"


@pytest.mark.parametrize("texto, esperado", [
    ("o que roubou fel", "okerobofel"),
    ("Ok, Robô-Fiel!", "okrobofel"),
    ("Robofael", "robofel"),
])
def test_normalizacao_fonetica(texto, esperado):
    assert normalizar_fonetico(texto) == esperado


# Transcrições reais do Vosk (modelo pequeno pt) para "ok Robofael" em vozes diferentes
@pytest.mark.parametrize("transcricao, comando", [
    ("o que roubou fel", ""),
    ("ok robô fel", ""),
    ("ok roubou fiel", ""),
    ("que roubou fel", ""),
    ("ok roubou", ""),
    ("o que roubou", ""),
    ("ok robofael", ""),
    ("é ok robô fel", ""),
    ("o que roubou a nota tarefa comprar pão", "a nota tarefa comprar pão"),
    ("ok roubou fiel a nota tarefa comprar pão", "a nota tarefa comprar pão"),
    ("Ok Robofael, que horas são?", "que horas são"),
])
def test_reconhece_a_frase_e_separa_o_comando(transcricao, comando):
    assert localizar_ativacao(transcricao, FRASE) == comando


@pytest.mark.parametrize("transcricao", [
    "ok rafael",  # o nome do usuário não pode acordar o assistente
    "o rafael", "o que rafael", "vou falar com o rafael",
    "hoje o robô falou com rafael", "hoje o robô fez tudo",  # parecido, mas no meio da fala
    "o que você roubou", "roubaram o celular", "roubou o filme",
    "roberto falou", "o que roberto falou", "o robô",
    "ok vamos lá", "ok obrigado", "que horas são", "anota tarefa comprar pão", "",
])
def test_nao_dispara_com_frases_parecidas(transcricao):
    assert localizar_ativacao(transcricao, FRASE) is None


# Saídas reais do Google para a voz do usuário dizendo "ok Fael, <comando>"
@pytest.mark.parametrize("google, inclui_frase, esperado", [
    ("Ok Fael a nota tarefa comprar pão", True, "a nota tarefa comprar pão"),
    ("o que Israel anota tarefa comprar pão", True, "anota tarefa comprar pão"),
    ("o que Israel o que tenho hoje", True, "o que tenho hoje"),
    ("Ok Fael Que horas são", True, "Que horas são"),
    ("Fael me lembra daqui a 10 minutos", False, "me lembra daqui a 10 minutos"),  # fim da frase no áudio
    ("me lembra daqui a 10 minutos de beber água", False, "me lembra daqui a 10 minutos de beber água"),
    ("quero saber o que tenho hoje", False, "quero saber o que tenho hoje"),
])
def test_extrai_comando_da_fala_que_comeca_com_ok_fael(google, inclui_frase, esperado):
    assert extrair_comando(google, "", "ok Fael", inclui_frase) == esperado


# Saídas reais do Google para "ok Robofael, <comando>" (busca fonética + alinhamento)
@pytest.mark.parametrize("google, vosk, esperado", [
    ("o que roubo Fael anota tarefa comprar pão", "a nota tarefa comprar pão", "anota tarefa comprar pão"),
    ("Ok Google Fael me lembra daqui a 10 minutos de beber água", "me lembra daqui a dez minutos de beber água",
     "me lembra daqui a 10 minutos de beber água"),
    ("Ok Robofael que horas são", "que horas são", "que horas são"),
    ("texto sem relação nenhuma", "xyz", "texto sem relação nenhuma"),
])
def test_extrai_o_comando_combinando_as_duas_transcricoes(google, vosk, esperado):
    assert extrair_comando(google, vosk, FRASE) == esperado


# ---------- Escuta passiva no orquestrador ----------
def cenario_com_vigia(*ativacoes, falas=(), transcricao=None, modelo=None):
    rec = ReconhecedorFalso(*falas, transcricao=transcricao)
    ativador = AtivadorFalso(*ativacoes)
    rec.ativador = ativador
    c = Cenario(modelo or ModeloRoteirizado("Resposta curta mas completa. "), rec)
    c.orq.ativador = ativador
    c.barramento.assinar(EscutaPassiva, c.eventos.append)
    return c, ativador, rec


def esperar(condicao, timeout=5.0):
    limite = time.monotonic() + timeout
    while not condicao() and time.monotonic() < limite:
        time.sleep(0.005)
    assert condicao()


def test_so_a_frase_toca_o_sinal_e_ouve_o_comando():
    c, ativador, rec = cenario_com_vigia(Ativacao(""), falas=["que horas são"])
    c.orq.iniciar_vigia()
    esperar(lambda: c.modelo.falas)
    c.concluir()
    assert c.reprodutor.tocadas[0] == "<sinal>"  # "estou ouvindo"
    assert c.modelo.falas == ["que horas são"]
    assert not rec.microfone_disputado
    c.orq.encerrar()


def test_comando_na_mesma_frase_usa_a_transcricao_precisa():
    c, *_ = cenario_com_vigia(Ativacao("", audio=b"pcm", audio_inclui_frase=True),
                              transcricao="o que Israel anota tarefa comprar pão")
    c.orq.iniciar_vigia()
    esperar(lambda: c.modelo.falas)
    c.concluir()
    assert c.modelo.falas == ["anota tarefa comprar pão"]
    assert "<sinal>" not in c.reprodutor.tocadas  # já veio com o comando: sem bipe
    assert c.de_tipo(FalaReconhecida)[0].texto == "anota tarefa comprar pão"
    c.orq.encerrar()


def test_comando_capturado_mas_inaudivel_vira_bipe_e_escuta():
    c, *_ = cenario_com_vigia(Ativacao("", audio=b"pcm"), falas=["que horas são"], transcricao=None)
    c.orq.iniciar_vigia()
    esperar(lambda: c.modelo.falas)
    c.concluir()
    assert c.reprodutor.tocadas[0] == "<sinal>" and c.modelo.falas == ["que horas são"]
    c.orq.encerrar()


def test_sem_internet_usa_a_transcricao_local_do_comando():
    c, *_ = cenario_com_vigia(Ativacao("a nota tarefa comprar pão", audio=b"pcm"),
                              transcricao=RuntimeError("sem internet"))
    c.orq.iniciar_vigia()
    esperar(lambda: c.modelo.falas)
    c.concluir()
    assert c.modelo.falas == ["a nota tarefa comprar pão"]
    c.orq.encerrar()


def test_espaco_libera_o_microfone_da_vigia_antes_de_ouvir():
    c, ativador, rec = cenario_com_vigia(falas=["oi"])
    c.orq.iniciar_vigia()
    esperar(lambda: ativador.aberto)
    c.orq.ouvir()  # ESPAÇO com a vigia escutando
    c.concluir()
    assert ativador.cancelamentos == 1
    assert rec.chamadas == 1 and not rec.microfone_disputado
    c.orq.encerrar()


def test_vigia_volta_a_escutar_depois_da_interacao():
    c, ativador, _ = cenario_com_vigia(Ativacao(""), falas=["oi"])
    c.orq.iniciar_vigia()
    esperar(lambda: ativador.chamadas >= 2 and ativador.aberto)  # ativou, respondeu e voltou a escutar
    c.orq.encerrar()


def test_lembrete_interrompe_a_vigia_e_e_falado():
    c, ativador, _ = cenario_com_vigia()
    c.orq.reprodutor = ReprodutorFalso()
    c.orq.iniciar_vigia()
    esperar(lambda: ativador.aberto)
    c.orq.anunciar("Rafael, lembrete: beber água.")
    esperar(lambda: "Rafael, lembrete: beber água." in c.orq.reprodutor.tocadas)
    c.orq.encerrar()


def test_falhas_seguidas_desligam_a_escuta_passiva_com_aviso():
    c, ativador, _ = cenario_com_vigia(*[OSError("microfone sumiu")] * 3)
    c.orq.iniciar_vigia()
    esperar(lambda: ativador.chamadas == 3, timeout=8)
    time.sleep(0.05)
    c.barramento.despachar()
    assert EscutaPassiva("ok Fael") in c.eventos and EscutaPassiva(None) in c.eventos
    assert any("desligada" in a.mensagem for a in c.de_tipo(Aviso))
    c.orq.encerrar()


def test_sem_detector_nao_liga_a_vigia():
    c = Cenario(ModeloRoteirizado("x"))
    assert c.orq.iniciar_vigia() is False


def test_desligar_e_religar_a_escuta_passiva():
    c, ativador, _ = cenario_com_vigia()
    c.orq.iniciar_vigia()
    esperar(lambda: ativador.aberto)
    c.orq.desligar_vigia()
    esperar(lambda: not ativador.aberto)
    chamadas = ativador.chamadas
    time.sleep(0.4)
    assert ativador.chamadas == chamadas and not c.orq.vigia_ligada  # não reabre o microfone
    c.orq.iniciar_vigia()
    esperar(lambda: ativador.aberto and ativador.chamadas > chamadas)
    c.barramento.despachar()
    assert c.eventos.count(EscutaPassiva(None)) == 1
    c.orq.encerrar()
