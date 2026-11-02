"""Configurações de avatar e voz, preferências salvas e janela de tamanho fixo."""

import json
import time

import pytest

from conftest import ReconhecedorFalso, ReprodutorFalso, SintetizadorFalso, requer_fotos
from robofael import bootstrap
from robofael.adaptadores.offline import ModeloOffline
from robofael.aplicacao import sessao
from robofael.aplicacao.agendador import AgendadorLembretes
from robofael.aplicacao.orquestrador import Orquestrador
from robofael.apresentacao.configuracoes import (
    FRASE_TESTE,
    AjustesVoz,
    ajustes_iniciais,
    formatar_hz,
    formatar_pct,
    ler_numero,
)
from robofael.configuracao import Configuracao
from robofael.portas import Preferencias


@pytest.mark.parametrize("texto, numero", [("+12Hz", 12), ("-26%", -26), ("0Hz", 0), (None, 0), ("lixo", 0)])
def test_le_numero_de_tom_e_ritmo(texto, numero):
    assert ler_numero(texto) == numero


def test_formata_e_limita_tom_e_ritmo():
    assert (formatar_hz(-21), formatar_hz(80)) == ("-21Hz", "+50Hz")  # limita a ±50 Hz
    assert (formatar_pct(-26), formatar_pct(-99)) == ("-26%", "-30%")  # limita a ±30%
    a = ajustes_iniciais("selfie", "pt-BR-AntonioNeural", "-21Hz", "-26%", True)
    assert a == AjustesVoz("selfie", "pt-BR-AntonioNeural", -21, -26, True)
    assert (a.tom, a.ritmo) == ("-21Hz", "-26%")


@pytest.fixture
def config(tmp_path):
    return Configuracao.do_ambiente({"ROBOFAEL_DADOS": str(tmp_path / "dados"), "ROBOFAEL_CACHE": str(tmp_path / "c")})


class LancadorVazio:
    def programas(self):
        return []

    def abrir(self, programa):
        raise AssertionError


def test_prioridade_da_voz_preferencia_perfil_padrao(config):
    nucleo = bootstrap.montar_nucleo(config, LancadorVazio())
    assert sessao.voz_inicial(nucleo) == ("pt-BR-AntonioNeural", "+0Hz", "+0%")  # padrão
    config.arquivo_perfil_voz.write_text(json.dumps({"voz": "pt-BR-AntonioNeural", "tom": "-21Hz", "ritmo": "-26%"}))
    assert sessao.voz_inicial(nucleo) == ("pt-BR-AntonioNeural", "-21Hz", "-26%")  # perfil gravado
    nucleo.salvar_preferencias(Preferencias(voz="pt-BR-FranciscaNeural", tom="+5Hz"))
    assert sessao.voz_inicial(nucleo) == ("pt-BR-FranciscaNeural", "+5Hz", "-26%")  # preferência vence
    assert bootstrap.montar_nucleo(config, LancadorVazio()).preferencias.tom == "+5Hz"  # persistiu


def test_prioridade_da_ativacao(config):
    nucleo = bootstrap.montar_nucleo(config, LancadorVazio())
    assert sessao.ativacao_inicial(nucleo) is True
    nucleo.salvar_preferencias(Preferencias(ativacao_por_voz=False))
    assert sessao.ativacao_inicial(nucleo) is False


# ---------- Interface ----------
class SintetizadorConfiguravel(SintetizadorFalso):
    voz, tom, ritmo = "pt-BR-AntonioNeural", "+0Hz", "+0%"

    def configurar(self, voz, tom, ritmo, gtts=None):
        self.voz, self.tom, self.ritmo = voz, tom, ritmo
        self.gtts = gtts


class AtivadorParado:
    frase = "ok Fael"

    def aguardar(self, cancelar):
        cancelar.wait(5)


def bombear(raiz, segundos=0.3, ate=None):
    fim = time.monotonic() + segundos
    while time.monotonic() < fim and not (ate and ate()):
        raiz.update()
        time.sleep(0.005)


@pytest.fixture
def janela(raiz, config, monkeypatch):
    from robofael.apresentacao import app as mod_app

    nucleo = bootstrap.montar_nucleo(config, LancadorVazio())
    sint = SintetizadorConfiguravel()

    def servicos(n, continuo=False):
        orq = Orquestrador(ModeloOffline(n.agenda), sint, ReprodutorFalso(), n.barramento, ReconhecedorFalso(),
                           ativador=AtivadorParado())
        return sessao.Servicos(orq, AgendadorLembretes(n.agenda, lambda l: None), False, True, True, sint)

    monkeypatch.setattr(mod_app, "iniciar_servicos", servicos)
    j = mod_app.Janela(raiz, nucleo)
    bombear(raiz, 20, ate=lambda: j.servicos is not None and j.palco.quadros is not None)
    yield j
    j.servicos.encerrar()


@pytest.mark.lento
def test_janela_tem_tamanho_fixo(janela, raiz):
    assert raiz.resizable() == (False, False)
    assert raiz.minsize() == raiz.maxsize()


@pytest.mark.lento
@requer_fotos
def test_configuracoes_ouvir_cancelar_e_salvar(janela, raiz):
    anunciados = []
    janela.servicos.orquestrador.anunciar = anunciados.append
    sint = janela.servicos.sintetizador
    assert janela.servicos.orquestrador.vigia_ligada  # ativação ligada por padrão

    dialogo = janela.abrir_configuracoes()
    assert janela.abrir_configuracoes() is dialogo  # não abre duas
    assert dialogo.resizable() == (False, False)
    dialogo.var_voz.set("Francisca (feminina)")
    dialogo.var_tom.set(12)
    dialogo.ouvir()
    assert (sint.voz, sint.tom) == ("pt-BR-FranciscaNeural", "+12Hz") and anunciados == [FRASE_TESTE]
    dialogo.cancelar()  # desfaz o teste de voz
    assert (sint.voz, sint.tom) == ("pt-BR-AntonioNeural", "+0Hz")

    dialogo = janela.abrir_configuracoes()
    dialogo.var_avatar.set("selfie")
    dialogo.var_ritmo.set(-26)
    dialogo.var_ativacao.set(False)
    quadros_antigos = janela.palco.quadros
    dialogo.salvar()
    # Espera a renderização do novo avatar terminar (senão ela segue consumindo CPU nos próximos testes)
    bombear(raiz, 30, ate=lambda: janela.palco.quadros is not quadros_antigos)
    assert janela.palco.quadros is not quadros_antigos
    assert janela.nome_avatar == "selfie" and sint.ritmo == "-26%"
    assert not janela.servicos.orquestrador.vigia_ligada
    salvas = janela.nucleo.banco.carregar_preferencias()
    assert salvas == Preferencias("selfie", "pt-BR-AntonioNeural", "+0Hz", "-26%", False, "pt-BR")


@pytest.mark.lento
def test_usar_perfil_gravado(janela, config):
    config.arquivo_perfil_voz.write_text(json.dumps({"voz": "pt-BR-AntonioNeural", "tom": "-21Hz", "ritmo": "-26%"}))
    dialogo = janela.abrir_configuracoes()
    dialogo.usar_perfil()
    assert (dialogo.ajustes().tom_hz, dialogo.ajustes().ritmo_pct) == (-21, -26)
    dialogo.cancelar()


@pytest.mark.lento
def test_trocar_idioma_ao_vivo_retraduz_a_interface(janela, raiz):
    from robofael.i18n import Idioma

    assert janela.botao.cget("text") == "🎤  Falar"
    janela.entrada.delete(0, "end")
    janela.entrada.insert(0, "Digite uma mensagem e pressione Enter…")
    janela.aplicar_idioma(Idioma.EN_US)
    bombear(raiz, 0.2)
    assert janela.botao.cget("text") == "🎤  Talk"
    assert janela.painel.lbl_tarefas.cget("text") == "TASKS"
    assert janela.painel.lista_tarefas.get(0).startswith("No tasks")
    assert janela.lbl_atalhos.cget("text").startswith("SPACE talk")
    assert janela.entrada.get() == "Type a message and press Enter…"
    assert raiz.title() == "Robofael — personal assistant"
    assert janela.palco.rotulo(janela.palco.estado).startswith(("Say", "Press"))
    assert janela.servicos.sintetizador.voz == "en-US-AndrewNeural"
    janela.aplicar_idioma(Idioma.PT_BR)
    assert janela.botao.cget("text") == "🎤  Falar" and janela.servicos.sintetizador.voz == "pt-BR-AntonioNeural"


@pytest.mark.lento
def test_troca_de_idioma_por_voz_retraduz_a_interface_e_o_painel(janela, raiz):
    from robofael.i18n import Idioma

    class Motor:
        def traduzir(self, textos, idioma):
            return [{"comprar pão": "buy bread"}.get(t, t) for t in textos]

    janela.nucleo.agenda.adicionar_tarefa("comprar pão")
    janela.nucleo.traducoes.motor = Motor()
    sessao.trocar_idioma(janela.nucleo, janela.servicos, Idioma.EN_US)  # o que "mudar para inglês" faz
    bombear(raiz, 0.2)
    assert janela.botao.cget("text") == "🎤  Talk" and janela.painel.lbl_tarefas.cget("text") == "TASKS"
    assert janela.painel.lista_tarefas.get(0) == "○  comprar pão"  # a tradução ainda não chegou: o original
    assert janela.nucleo.traducoes.traduzir_pendentes()
    bombear(raiz, 0.2)
    assert janela.painel.lista_tarefas.get(0) == "○  buy bread"
    janela.nucleo.traducoes.motor = None


@pytest.mark.lento
def test_configuracoes_trocam_idioma_e_lista_de_vozes(janela, raiz):
    from robofael.i18n import Idioma

    anunciados = []
    janela.servicos.orquestrador.anunciar = anunciados.append
    dialogo = janela.abrir_configuracoes()
    assert "Antonio (masculina)" in dialogo.combo_voz.cget("values")
    dialogo.var_idioma.set(Idioma.EN_US.nome)
    dialogo._ao_trocar_idioma()
    assert dialogo.var_voz.get() == "Andrew (male)"  # a voz em português não serve para inglês
    assert "Jenny (female)" in dialogo.combo_voz.cget("values")
    dialogo.ouvir()  # testa a voz e a frase no idioma escolhido, antes de salvar
    assert anunciados == ["Hi! This is the voice I'll use to talk with you."]
    dialogo.salvar()
    bombear(raiz, 0.2)
    assert janela.tr.idioma is Idioma.EN_US and janela.botao.cget("text") == "🎤  Talk"
    assert janela.nucleo.banco.carregar_preferencias().idioma == "en-US"
    assert janela.servicos.sintetizador.voz == "en-US-AndrewNeural"
    assert janela.abrir_configuracoes().title() == "Settings"  # o próprio diálogo já abre em inglês


@pytest.mark.lento
def test_configuracoes_escolhem_microfone_e_inicializacao(janela, raiz):
    from robofael.portas import EstadoInicializacao, Microfone

    usb = Microfone("alsa_input.usb-headset", "Headset USB")
    aplicados = []

    class Inicializacao:
        def estado(self):
            return EstadoInicializacao(*(aplicados[-1] if aplicados else (False, False)))

        def aplicar(self, abrir, comando):
            aplicados.append((abrir, comando))

    class Dispositivos:
        def microfones(self):
            return [usb]

    janela.nucleo.dispositivos, janela.nucleo.inicializacao = Dispositivos(), Inicializacao()
    dialogo = janela.abrir_configuracoes()
    assert dialogo.combo_microfone.cget("values") == ("Padrão do sistema", "Headset USB")
    assert dialogo.var_microfone.get() == "Padrão do sistema"
    assert not dialogo.var_abrir_ao_entrar.get() and not dialogo.var_comando.get()
    dialogo.var_microfone.set("Headset USB")
    dialogo.var_abrir_ao_entrar.set(True)
    dialogo.var_comando.set(True)
    dialogo.salvar()
    bombear(raiz, 0.2)
    assert janela.nucleo.microfone == usb.id and janela.nucleo.banco.carregar_preferencias().microfone == usb.id
    assert aplicados == [(True, True)]

    dialogo = janela.abrir_configuracoes()  # reabre mostrando o que foi salvo
    assert dialogo.var_microfone.get() == "Headset USB"
    assert dialogo.var_abrir_ao_entrar.get() and dialogo.var_comando.get()
    dialogo.cancelar()


@pytest.mark.lento
def test_configuracoes_mostram_o_cerebro_e_cuidam_do_banco(janela, raiz, tmp_path):
    from robofael.portas import ModeloDisponivel, ProvedorIndisponivel

    class Ollama:
        provedor = "ollama"

        def modelos(self):
            return [ModeloDisponivel("llama3.2:3b", "3.2B")]

    class Claude:
        provedor = "claude"

        def modelos(self):
            raise ProvedorIndisponivel("modelos.claude_sem_chave")

    janela.nucleo.catalogos = (Claude(), Ollama())
    janela.nucleo.agenda.adicionar_tarefa("não perder")
    dialogo = janela.abrir_configuracoes()
    assert dialogo.lbl_cerebro.cget("text") == "Em uso: modo offline (comandos básicos, sem modelo de linguagem)"
    bombear(raiz, 5, ate=lambda: "llama" in dialogo.lbl_modelos.cget("text"))
    assert dialogo.lbl_modelos.cget("text").splitlines() == [
        "• Claude (nuvem): sem chave: defina ANTHROPIC_API_KEY", "• Ollama (local): llama3.2:3b (3.2B)"]
    assert dialogo.lbl_banco.cget("text") == str(janela.nucleo.config.arquivo_banco)

    dialogo.fazer_backup(tmp_path / "copia.db")  # (o botão abre a janela de salvar e chega aqui)
    assert dialogo.lbl_resultado_banco.cget("text").startswith("Backup salvo e conferido")
    assert (tmp_path / "copia.db").exists()

    dialogo.mover_banco(tmp_path / "novo")
    assert dialogo.lbl_banco.cget("text") == str((tmp_path / "novo" / "memoria.db").resolve())
    assert dialogo.lbl_resultado_banco.cget("text").startswith("Banco movido")
    dialogo.mover_banco(tmp_path / "novo")  # já há um banco lá: recusa sem estragar nada
    assert dialogo.lbl_resultado_banco.cget("text").startswith("Já existe um memoria.db")
    assert [t.texto for t in janela.nucleo.agenda.pendentes()] == ["não perder"]
    dialogo.cancelar()  # cancelar não desfaz a mudança do banco (ela vale na hora, como a tela avisa)
    assert janela.nucleo.banco.arquivo == (tmp_path / "novo" / "memoria.db").resolve()
