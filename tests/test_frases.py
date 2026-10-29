import pytest

from robofael.aplicacao.frases import DivisorFrases


def dividir(pedacos, **kw):
    d = DivisorFrases(**kw)
    saida = [f for p in pedacos for f in d.adicionar(p)]
    return saida + d.finalizar()


def test_divide_em_frases_conforme_o_texto_chega():
    d = DivisorFrases()
    assert d.adicionar("Anotei a tarefa de revisar o PR") == []
    assert d.adicionar(". Quer que eu ") == ["Anotei a tarefa de revisar o PR."]
    assert d.adicionar("crie um lembrete também? ") == ["Quer que eu crie um lembrete também?"]
    assert d.finalizar() == []


def test_frases_curtas_sao_juntadas_com_a_seguinte():
    assert dividir(["Ok! Pronto. Anotei a sua tarefa para hoje. "]) == ["Ok! Pronto. Anotei a sua tarefa para hoje."]


def test_nao_corta_numero_decimal_em_pedacos_separados():
    assert dividir(["A temperatura média hoje é de 3", ".5 graus na serra. Leve casaco."]) == [
        "A temperatura média hoje é de 3.5 graus na serra.", "Leve casaco."]


def test_nao_corta_em_abreviacao():
    assert dividir(["A reunião com o Dr. Silva foi remarcada para amanhã cedo. "]) == [
        "A reunião com o Dr. Silva foi remarcada para amanhã cedo."]


def test_primeira_frase_longa_pode_sair_na_virgula_para_reduzir_latencia():
    d = DivisorFrases(primeira_virgula_apos=45)
    primeira = d.adicionar("Hoje você tem três tarefas pendentes e dois lembretes, ")
    assert primeira == ["Hoje você tem três tarefas pendentes e dois lembretes,"]
    # Depois da primeira, só corta no fim de frase
    assert d.adicionar("sendo o primeiro às nove horas, depois ") == []


@pytest.mark.parametrize("pedacos", [["Linha um completa aqui\nLinha dois completa aqui"], ["Sem pontuação final"]])
def test_quebra_de_linha_e_resto_no_final(pedacos):
    resultado = dividir(pedacos, minimo=5)
    assert "".join(resultado).replace(" ", "") == "".join(pedacos).replace("\n", "").replace(" ", "")
