import threading

import pytest

from robofael.aplicacao.barramento import Barramento
from robofael.dominio.estados import TRANSICOES, Estado, MaquinaEstados, TransicaoInvalida
from robofael.dominio.eventos import AgendaAtualizada, EstadoMudou


def test_transicoes_validas_notificam():
    mudancas = []
    m = MaquinaEstados(mudancas.append)
    for e in (Estado.FALANDO, Estado.PARADO, Estado.OUVINDO, Estado.PENSANDO, Estado.FALANDO, Estado.OUVINDO):
        m.ir_para(e)
    assert mudancas[-1] is Estado.OUVINDO and len(mudancas) == 6
    m.ir_para(Estado.OUVINDO)  # mesmo estado: não notifica de novo
    assert len(mudancas) == 6


@pytest.mark.parametrize("de, para", [(Estado.OUVINDO, Estado.FALANDO), (Estado.PENSANDO, Estado.OUVINDO),
                                      (Estado.PARADO, Estado.INICIANDO)])
def test_transicoes_invalidas_sao_rejeitadas(de, para):
    m = MaquinaEstados(inicial=de)
    with pytest.raises(TransicaoInvalida):
        m.ir_para(para)
    assert m.atual is de


def test_todo_estado_pode_voltar_a_parado_menos_o_proprio():
    for estado, destinos in TRANSICOES.items():
        assert estado is Estado.PARADO or Estado.PARADO in destinos


def test_barramento_entrega_em_ordem_na_thread_que_despacha():
    b = Barramento()
    recebidos, threads = [], set()
    b.assinar(EstadoMudou, lambda e: (recebidos.append(e.estado), threads.add(threading.get_ident())))
    publicadores = [threading.Thread(target=b.publicar, args=(EstadoMudou(Estado.PARADO),)) for _ in range(20)]
    for t in publicadores:
        t.start()
    for t in publicadores:
        t.join()
    assert b.despachar() == 20
    assert len(recebidos) == 20 and threads == {threading.get_ident()}


def test_tratador_com_erro_nao_derruba_os_outros():
    b = Barramento()
    ok = []
    b.assinar(AgendaAtualizada, lambda e: 1 / 0)
    b.assinar(AgendaAtualizada, lambda e: ok.append(e))
    b.publicar(AgendaAtualizada())
    b.publicar(object())  # sem assinantes: ignorado
    assert b.despachar() == 2 and len(ok) == 1


def test_limite_por_despacho():
    b = Barramento()
    for _ in range(10):
        b.publicar(AgendaAtualizada())
    assert b.despachar(limite=4) == 4
    assert b.despachar() == 6
