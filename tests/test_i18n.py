"""Internacionalização: catálogo, idioma configurável e respostas em inglês de ponta a ponta."""

import string
from datetime import date, datetime

import anthropic
import httpx2
import pytest

from conftest import AGORA, ClienteFalso, Relogio, RepositorioMemoria, bloco_texto, resposta
from robofael import bootstrap
from robofael.adaptadores.claude import ModeloClaude
from robofael.adaptadores.ferramentas import ExecutorFerramentas
from robofael.adaptadores.offline import ModeloOffline
from robofael.aplicacao import sessao
from robofael.aplicacao.memoria import Memoria
from robofael.aplicacao.programas import ServicoProgramas
from robofael.configuracao import Configuracao
from robofael.dominio.agenda import Agenda
from robofael.dominio.linguagem import eh_despedida, pede_nova_conversa, pergunta_historico
from robofael.dominio.periodos import Periodo, interpretar_periodo
from robofael.dominio.programas import extrair_pedido
from robofael.i18n import CATALOGO, VOZES, Idioma, Tradutor
from robofael.portas import Preferencias, Programa

PT, EN = Idioma.PT_BR, Idioma.EN_US
HOJE = date(2026, 10, 22)  # quinta-feira


def campos(texto: str) -> set[str]:
    return {nome for _, nome, _, _ in string.Formatter().parse(texto) if nome}


# ---------- Catálogo ----------
@pytest.mark.parametrize("chave", sorted(CATALOGO))
def test_toda_mensagem_existe_nos_dois_idiomas_com_os_mesmos_campos(chave):
    textos = CATALOGO[chave]
    assert set(textos) == {PT, EN}, f"{chave}: faltando idioma"
    pt, en = textos[PT], textos[EN]
    assert type(pt) is type(en)
    if isinstance(pt, tuple):
        assert len(pt) == len(en) == 2 and all(pt) and all(en)
    else:
        assert pt.strip() and en.strip() and campos(pt) == campos(en), f"{chave}: campos diferentes"


def test_cada_idioma_tem_vozes_e_voz_padrao_valida():
    for idioma in Idioma:
        assert idioma.voz_padrao in VOZES[idioma]
        assert all(v.startswith(idioma.value) for v in VOZES[idioma])


@pytest.mark.parametrize("texto, esperado", [
    ("en", EN), ("EN_us", EN), ("english", EN), ("pt", PT), ("pt-br", PT), (None, PT), ("fr", PT)])
def test_idioma_de_texto(texto, esperado):
    assert Idioma.de_texto(texto) is esperado


def test_tradutor_formata_plurais_listas_datas_e_avisa_quem_observa():
    tr = Tradutor(EN)
    mudancas = []
    tr.observar(mudancas.append)
    assert tr("off.anotei", texto="x") == "Added: x."
    assert (tr.plural(1, "un.tarefa"), tr.plural(2, "un.tarefa")) == ("task", "tasks")
    assert tr.juntar(["a", "b", "c"]) == "a, b and c"
    assert (tr.data(AGORA), tr.dia_mes(AGORA), tr.dia_semana(AGORA)) == ("10/21/2026", "10/21", "Wednesday")
    tr.idioma = EN  # mesmo idioma: não avisa
    tr.idioma = PT
    assert mudancas == [PT] and tr.juntar(["a", "b"]) == "a e b" and tr.data(AGORA) == "21/10/2026"


# ---------- Entender os dois idiomas ----------
@pytest.mark.parametrize("texto", ["what did I do yesterday?", "What have I done this week", "my history"])
def test_perguntas_de_historico_em_ingles(texto):
    assert pergunta_historico(texto)


def test_despedida_e_nova_conversa_em_ingles():
    assert eh_despedida("ok, goodbye") and eh_despedida("stop listening")
    assert pede_nova_conversa("let's start over") and pede_nova_conversa("new conversation")


@pytest.mark.parametrize("fala, pedido", [
    ("open the calculator", "calculator"), ("can you launch firefox for me please", "firefox"),
    ("start the app terminal", "terminal"), ("run my text editor", "text editor")])
def test_pedidos_para_abrir_programas_em_ingles(fala, pedido):
    assert extrair_pedido(fala) == pedido


@pytest.mark.parametrize("texto, inicio, fim, descricao", [
    ("what did I do today", "2026-10-22", "2026-10-22", "today (10/22)"),
    ("yesterday", "2026-10-21", "2026-10-21", "yesterday (10/21)"),
    ("the day before yesterday", "2026-10-20", "2026-10-20", "the day before yesterday (10/20)"),
    ("on monday", "2026-10-19", "2026-10-19", "on Monday (10/19)"),
    ("last saturday", "2026-10-17", "2026-10-17", "on Saturday (10/17)"),
    ("last week", "2026-10-12", "2026-10-18", "last week (10/12 to 10/18)"),
    ("this week", "2026-10-19", "2026-10-22", "this week (10/19 to 10/22)"),
    ("in the last 3 days", "2026-10-20", "2026-10-22", "in the last 3 days (10/20 to 10/22)"),
    ("past seven days", "2026-10-16", "2026-10-22", "in the last 7 days (10/16 to 10/22)"),
    ("on the 20th", "2026-10-20", "2026-10-20", "on 10/20"),
    ("on 10/20", "2026-10-20", "2026-10-20", "on 10/20/2026"),  # mês/dia em inglês
    ("on October 5th", "2026-10-05", "2026-10-05", "on 10/05/2026"),
    ("on 5 October 2025", "2025-10-05", "2025-10-05", "on 10/05/2025"),
    ("the week of 10/5", "2026-10-05", "2026-10-11", "in the week of 10/05 to 10/11"),
    ("last month", "2026-09-01", "2026-09-30", "last month (09/2026)"),
])
def test_periodos_em_ingles(texto, inicio, fim, descricao):
    p = interpretar_periodo(texto, HOJE, Tradutor(EN))
    assert p == Periodo.dias(date.fromisoformat(inicio), date.fromisoformat(fim), descricao)


def test_data_numerica_segue_o_idioma():
    assert interpretar_periodo("05/10", HOJE, Tradutor(PT)).inicio.date() == date(2026, 10, 5)
    assert interpretar_periodo("05/10", HOJE, Tradutor(EN)).inicio.date() == date(2026, 5, 10)


# ---------- Responder em inglês ----------
@pytest.fixture
def em_ingles():
    relogio = Relogio(datetime(2026, 10, 21, 16, 25))
    repo = RepositorioMemoria()
    tr = Tradutor(EN)
    agenda = Agenda(repo, relogio)
    return relogio, repo, tr, agenda


def falar(modelo, texto):
    return "".join(modelo.responder(texto))


def test_modo_offline_em_ingles(em_ingles):
    relogio, repo, tr, agenda = em_ingles
    m = ModeloOffline(agenda, relogio, memoria=Memoria(repo, tr), tradutor=tr)
    assert falar(m, "add task buy bread") == "Added: buy bread."
    assert falar(m, "anota tarefa revisar o PR") == "Added: revisar o PR."  # entende português, responde em inglês
    assert falar(m, "what are my tasks?") == "You have 2 pending tasks. 1: buy bread; 2: revisar o PR."
    assert falar(m, "complete task 1") == "Nice! Task buy bread completed."
    assert falar(m, "finish task 9") == "I couldn't find that task."
    assert falar(m, "remind me in 1 minute to stretch") == "Okay, I'll remind you in 1 minute."
    assert agenda.proximos_lembretes()[0].texto == "stretch"
    assert falar(m, "what time is it?") == "It's 04:25 PM."
    assert falar(m, "what day is it") == "Today is Wednesday, 10/21/2026."
    assert falar(m, "what did I do today?") == (
        "Today (10/21) you completed 1 task: buy bread. You also created 2 tasks.")
    assert falar(m, "tell me a joke") == tr("off.ajuda") and "offline mode" in tr("off.ajuda")


def test_memoria_sem_tarefas_em_ingles(em_ingles):
    _, repo, tr, _ = em_ingles
    assert Memoria(repo, tr).responder(interpretar_periodo("last week", HOJE, tr)) == (
        "I didn't find any completed tasks last week (10/12 to 10/18).")


def test_programas_em_ingles(em_ingles):
    *_, tr, agenda = em_ingles
    abertos = []

    class Lancador:
        def programas(self):
            return [Programa("calc", "Calculator", "gnome-calculator")]

        def abrir(self, p):
            abertos.append(p.id)

    s = ServicoProgramas(Lancador(), tr)
    assert s.abrir("calculator")["frase"] == "Opening Calculator."
    assert s.abrir("photoshop")["frase"] == "I couldn't find any installed program called photoshop."
    m = ModeloOffline(agenda, programas=s, tradutor=tr)
    assert falar(m, "open the calculator please") == "Opening Calculator." and abertos == ["calc", "calc"]


def test_claude_em_ingles_e_troca_ao_vivo(em_ingles):
    relogio, _, tr, agenda = em_ingles
    cliente = ClienteFalso(resposta("end_turn", bloco_texto("Good afternoon!")))
    m = ModeloClaude(cliente, ExecutorFerramentas(agenda), "Rafael", relogio=relogio, tradutor=tr)
    assert falar(m, "hi").strip() == "Good afternoon!"
    chamada = cliente.chamadas[0]
    assert chamada["system"][0]["text"].startswith("You are Robofael, Rafael's personal assistant")
    assert "Answer in American English" in chamada["system"][0]["text"]
    assert chamada["messages"][0]["content"] == "[Now: Wednesday, 2026-10-21 16:25]\nhi"
    assert m.historico
    tr.idioma = PT  # trocar de idioma recomeça a conversa
    assert m.historico == [] and m.sistema.startswith("Você é o Robofael")


def test_erros_do_claude_em_ingles(em_ingles):
    relogio, _, tr, agenda = em_ingles
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    m = ModeloClaude(ClienteFalso(anthropic.APIConnectionError(request=req)), ExecutorFerramentas(agenda),
                     "Rafael", relogio=relogio, tradutor=tr)
    assert falar(m, "hi") == "I couldn't connect to the internet."


# ---------- Configuração e composição ----------
@pytest.fixture
def config(tmp_path):
    return Configuracao.do_ambiente({"ROBOFAEL_DADOS": str(tmp_path / "d"), "ROBOFAEL_IDIOMA": "en"})


class LancadorVazio:
    def programas(self):
        return []

    def abrir(self, p):
        raise AssertionError


def test_idioma_pela_variavel_de_ambiente_e_pela_preferencia(config, tmp_path):
    assert config.idioma == "en-US"
    assert Configuracao.do_ambiente({}).idioma == "pt-BR"
    nucleo = bootstrap.montar_nucleo(config, LancadorVazio())
    assert nucleo.tradutor.idioma is EN
    nucleo.salvar_preferencias(Preferencias(idioma="pt-BR"))
    assert bootstrap.montar_nucleo(config, LancadorVazio()).tradutor.idioma is PT  # a preferência vence


def test_saudacao_e_voz_em_ingles(config):
    nucleo = bootstrap.montar_nucleo(config, LancadorVazio())
    nucleo.agenda.adicionar_tarefa("x")
    assert sessao.saudacao(nucleo, online=False, ativacao_por_voz=True) == (
        "Hi, Rafael! I'm Robofael, your everyday assistant. You have 1 pending task. "
        "I'm in offline mode, with basic commands. To call me, just say: ok Fael.")
    assert sessao.voz_inicial(nucleo)[0] == "en-US-AndrewNeural"  # a voz em português não serve


def test_voz_para_idioma():
    assert sessao.voz_para_idioma("pt-BR-AntonioNeural", EN) == "en-US-AndrewNeural"
    assert sessao.voz_para_idioma("en-US-JennyNeural", EN) == "en-US-JennyNeural"
    assert sessao.voz_para_idioma(None, PT) == "pt-BR-AntonioNeural"


def test_aplicar_idioma_ao_vivo(config):
    nucleo = bootstrap.montar_nucleo(config, LancadorVazio())

    class Sint:
        voz, tom, ritmo, gtts = "en-US-AndrewNeural", "-21Hz", "-26%", ("en", "com")

        def configurar(self, voz, tom, ritmo, gtts=None):
            self.voz, self.tom, self.ritmo, self.gtts = voz, tom, ritmo, gtts

    servicos = sessao.Servicos(None, None, False, False, sintetizador=Sint())  # type: ignore[arg-type]
    sessao.aplicar_idioma(nucleo, servicos, PT)
    sint = servicos.sintetizador
    assert nucleo.tradutor.idioma is PT and nucleo.memoria.tr.idioma is PT and nucleo.programas.tr.idioma is PT
    assert (sint.voz, sint.tom, sint.ritmo, sint.gtts) == ("pt-BR-AntonioNeural", "-21Hz", "-26%", ("pt", "com.br"))


def test_lembrete_anunciado_em_ingles(config, monkeypatch):
    import robofael.adaptadores.claude as claude
    import robofael.adaptadores.reprodutor as reprodutor
    from conftest import ReprodutorFalso

    monkeypatch.setattr(claude, "criar_cliente", lambda t: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(bootstrap, "_criar_microfone", lambda *a: None)
    monkeypatch.setattr(reprodutor, "ReprodutorPygame", ReprodutorFalso)
    nucleo = bootstrap.montar_nucleo(config, LancadorVazio())
    servicos = bootstrap.iniciar_servicos(nucleo)
    anunciados = []
    monkeypatch.setattr(servicos.orquestrador, "anunciar", anunciados.append)
    nucleo.agenda.criar_lembrete("drink water", "2000-01-01T00:00")
    servicos.agendador.verificar()
    assert anunciados == ["Rafael, reminder: drink water."]
    assert servicos.sintetizador.gtts == ("en", "com")


def test_microfone_reconhece_no_idioma_do_tradutor():
    from robofael.adaptadores.microfone import MicrofoneGoogle

    mic = MicrofoneGoogle.__new__(MicrofoneGoogle)  # sem abrir o hardware
    mic.tr, mic._idioma_fixo = Tradutor(EN), "pt-BR"
    assert mic.idioma == "en-US"
    mic.tr.idioma = PT
    assert mic.idioma == "pt-BR"
