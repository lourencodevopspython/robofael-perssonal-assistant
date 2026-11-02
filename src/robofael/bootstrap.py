"""Raiz de composição: o único lugar que conhece as implementações concretas.

Aqui só se escolhe e se conecta (injeção de dependências). As regras sobre o que usar
(idioma, voz, ativação, saudação) ficam em `aplicacao/sessao.py`.

`montar_nucleo` é instantâneo (agenda + barramento) e permite abrir a janela na hora;
`iniciar_servicos` faz o trabalho lento — conectar ao Claude, calibrar o microfone, abrir o
áudio — em paralelo, numa thread de fundo, e avisa a interface quando terminar."""

from __future__ import annotations

import dataclasses
import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from robofael.adaptadores.claude import CatalogoClaude
from robofael.adaptadores.dispositivos_audio import DispositivosPulse
from robofael.adaptadores.documentos import PastaDocumentos
from robofael.adaptadores.ferramentas import ExecutorFerramentas
from robofael.adaptadores.inicializacao_linux import InicializacaoLinux
from robofael.adaptadores.offline import ModeloOffline
from robofael.adaptadores.ollama import CatalogoOllama, ClienteOllama
from robofael.adaptadores.programas_linux import LancadorLinux
from robofael.adaptadores.sqlite import BancoSqlite
from robofael.aplicacao.agendador import AgendadorLembretes
from robofael.aplicacao.barramento import Barramento
from robofael.aplicacao.documentos import ServicoDocumentos
from robofael.aplicacao.memoria import Memoria
from robofael.aplicacao.orquestrador import Orquestrador
from robofael.aplicacao.programas import ServicoProgramas
from robofael.aplicacao.sessao import Nucleo, Servicos, idioma_inicial, trocar_idioma, voz_inicial
from robofael.aplicacao.traducao import TraducaoAgenda
from robofael.audio.perfil import carregar_perfil
from robofael.configuracao import Configuracao
from robofael.dominio.agenda import Agenda
from robofael.dominio.eventos import AgendaAtualizada, Aviso, Gravidade, IdiomaMudou, TraducoesAtualizadas
from robofael.i18n import Tradutor
from robofael.portas import (
    CapturaAudio,
    DetectorAtivacao,
    DispositivosAudio,
    InicializacaoSistema,
    LancadorProgramas,
    ModeloLinguagem,
    Preferencias,
    ReconhecedorFala,
)

log = logging.getLogger(__name__)


def montar_nucleo(config: Configuracao, lancador: LancadorProgramas | None = None,
                  dispositivos: DispositivosAudio | None = None,
                  inicializacao: InicializacaoSistema | None = None) -> Nucleo:

    barramento = Barramento()
    if config.banco_escolhido is not None and not config.banco_escolhido.exists():
        # Ex.: pendrive ou disco de rede desconectado. Criar um banco vazio lá esconderia a agenda
        # (e gravaria no ponto de montagem); usa o padrão nesta vez, sem esquecer a escolha.
        log.error("Banco não encontrado em %s; usando %s nesta vez", config.banco_escolhido,
                  config.arquivo_banco_padrao)
        barramento.publicar(Aviso(Tradutor(idioma_inicial(config, Preferencias()))(
            "ui.banco_nao_encontrado", arquivo=str(config.banco_escolhido)), Gravidade.ERRO))
        config = dataclasses.replace(config, banco_escolhido=None)
    banco = BancoSqlite(config.arquivo_banco)
    banco.importar_json(config.arquivo_agenda)  # só na primeira vez (versões anteriores usavam JSON)
    agenda = Agenda(banco)
    agenda.observar(lambda: barramento.publicar(AgendaAtualizada()))
    preferencias = banco.carregar_preferencias()
    tradutor = Tradutor(idioma_inicial(config, preferencias))
    tradutor.observar(lambda idioma: barramento.publicar(IdiomaMudou(idioma)))
    programas = ServicoProgramas(lancador or LancadorLinux(), tradutor)
    traducoes = TraducaoAgenda(agenda, banco, tradutor, lambda: barramento.publicar(TraducoesAtualizadas()))
    return Nucleo(config, barramento, agenda, banco, Memoria(banco, tradutor), programas, preferencias, tradutor,
                  ler_perfil_voz=lambda: carregar_perfil(config.arquivo_perfil_voz),
                  dispositivos=dispositivos or DispositivosPulse(),
                  inicializacao=inicializacao or InicializacaoLinux(),
                  catalogos=(CatalogoClaude(), CatalogoOllama(ClienteOllama(config.url_ollama))),
                  traducoes=traducoes)


def _criar_modelo(nucleo: Nucleo) -> ModeloLinguagem:
    """O melhor cérebro disponível: Claude > modelo local (Ollama) > modo offline.
    ROBOFAEL_CEREBRO=claude|ollama|offline restringe a escolha."""
    cfg = nucleo.config
    offline = ModeloOffline(nucleo.agenda, memoria=nucleo.memoria, programas=nucleo.programas,
                            tradutor=nucleo.tradutor)
    candidatos = {"auto": (_criar_claude, _criar_ollama), "claude": (_criar_claude,),
                  "ollama": (_criar_ollama,), "offline": ()}[cfg.cerebro]
    for criar in candidatos:
        if (modelo := criar(nucleo, offline)) is not None:
            return modelo
    log.warning("Usando o modo offline (comandos de agenda, hora, data, histórico e programas).")
    return offline


def _criar_claude(nucleo: Nucleo, _offline: ModeloOffline) -> ModeloLinguagem | None:
    cfg = nucleo.config
    try:
        from robofael.adaptadores.claude import ModeloClaude, criar_cliente

        cliente = criar_cliente(cfg.timeout_api_s)
        cliente.models.retrieve(cfg.modelo)  # confirma credenciais e acesso ao modelo
    except Exception as e:
        # O SDK levanta TypeError quando não encontra nenhuma credencial
        motivo = "sem credenciais: defina ANTHROPIC_API_KEY" if isinstance(e, TypeError) else e.__class__.__name__
        url = os.environ.get("ANTHROPIC_BASE_URL", "")
        if url and "api.anthropic.com" not in url:
            motivo += f"; ANTHROPIC_BASE_URL aponta para {url}, onde o modelo {cfg.modelo} não está disponível"
        log.warning("Claude indisponível (%s).", motivo)
        return None
    log.info("Cérebro: Claude (%s)", cfg.modelo)
    executor = ExecutorFerramentas(nucleo.agenda, nucleo.memoria, nucleo.programas)
    return ModeloClaude(cliente, executor, cfg.nome_usuario, cfg.modelo, cfg.esforco, cfg.max_mensagens_historico,
                        nome_assistente=cfg.nome_assistente, tradutor=nucleo.tradutor)


def _criar_ollama(nucleo: Nucleo, offline: ModeloOffline) -> ModeloLinguagem | None:
    cfg = nucleo.config
    from robofael.adaptadores.ollama import ClienteOllama, ModeloOllama, OllamaIndisponivel, escolher_modelo

    cliente = ClienteOllama(cfg.url_ollama, cfg.timeout_local_s)
    try:
        modelo = escolher_modelo(cliente, cfg.modelo_local)
    except OllamaIndisponivel as e:
        log.warning("Modelo local indisponível (Ollama não respondeu em %s: %s).", cfg.url_ollama, e)
        return None
    if modelo is None:
        log.warning("Ollama sem modelo compatível; instale um com: ollama pull %s", cfg.modelo_local)
        return None
    threading.Thread(target=cliente.aquecer, args=(modelo,), name="aquecer-modelo-local", daemon=True).start()
    log.info("Cérebro: modelo local %s (Ollama em %s); o modo offline atende os comandos diretos", modelo,
             cfg.url_ollama)
    executor = ExecutorFerramentas(nucleo.agenda, nucleo.memoria, nucleo.programas)
    return ModeloOllama(cliente, modelo, executor, offline, cfg.nome_usuario, cfg.nome_assistente,
                        tradutor=nucleo.tradutor)


def _criar_microfone(cfg: Configuracao, tradutor: Tradutor | None = None,
                     microfone: Callable[[], str | None] = lambda: None) -> ReconhecedorFala | None:
    try:
        from robofael.adaptadores.microfone import MicrofoneGoogle

        return MicrofoneGoogle(cfg.idioma, cfg.pausa_fim_fala_s, tradutor, microfone)
    except Exception as e:
        log.warning("Microfone indisponível: %s", e)
        return None


def _criar_ativador(cfg: Configuracao, barramento: Barramento | None = None, tradutor: Tradutor | None = None,
                    microfone: Callable[[], str | None] = lambda: None) -> DetectorAtivacao | None:
    try:
        from robofael.adaptadores.ativacao_vosk import AtivacaoVosk

        def avisar(pico: float) -> None:
            if barramento is not None:
                mensagem = (tradutor or Tradutor())("mic.voz_baixa", pico=f"{pico:.0f}")
                barramento.publicar(Aviso(mensagem, Gravidade.ERRO))

        return AtivacaoVosk(cfg.pasta_modelo_ativacao, cfg.frase_ativacao, avisar, microfone)
    except Exception as e:
        log.warning("Ativação por voz indisponível (%s). Rode `make baixar-modelo-voz`.", e)
        return None


def iniciar_servicos(nucleo: Nucleo, continuo: bool = False) -> Servicos:
    from robofael.adaptadores.reprodutor import ReprodutorPygame
    from robofael.adaptadores.sintetizador import SintetizadorEdge

    cfg, tr = nucleo.config, nucleo.tradutor
    voz, tom, ritmo = voz_inicial(nucleo)
    sintetizador = SintetizadorEdge(voz, tom, ritmo, cfg.pasta_cache_tts, cfg.max_itens_cache_tts)
    sintetizador.gtts = tr.idioma.codigo_gtts

    def escolhido() -> str | None:  # o microfone escolhido agora (muda ao salvar as configurações)
        return nucleo.microfone

    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="inicializacao") as pool:
        f_modelo = pool.submit(_criar_modelo, nucleo)
        f_mic = pool.submit(_criar_microfone, cfg, tr, escolhido)
        f_audio = pool.submit(ReprodutorPygame)
        f_ativador = pool.submit(_criar_ativador, cfg, nucleo.barramento, tr, escolhido)
        pool.submit(nucleo.programas.lancador.programas)  # já deixa a lista de programas pronta
        modelo, microfone, reprodutor = f_modelo.result(), f_mic.result(), f_audio.result()
        ativador = f_ativador.result() if microfone is not None else None

    documentos = ServicoDocumentos(PastaDocumentos(cfg.pasta_documentos), tr)
    orquestrador = Orquestrador(modelo, sintetizador, reprodutor, nucleo.barramento, microfone, continuo,
                                ativador=ativador, tradutor=tr, documentos=documentos)
    agendador = AgendadorLembretes(nucleo.agenda, lambda l: orquestrador.anunciar(
        tr("fala.lembrete", usuario=cfg.nome_usuario, texto=nucleo.exibir(l.texto))))
    if microfone is None:
        nucleo.barramento.publicar(Aviso(tr("mic.nao_encontrado"), Gravidade.ERRO))
    servicos = Servicos(orquestrador, agendador, modelo.online, microfone is not None, ativador is not None,
                        sintetizador)
    orquestrador.trocar_idioma = lambda idioma: trocar_idioma(nucleo, servicos, idioma)
    if nucleo.traducoes is not None:
        nucleo.traducoes.ocupado = lambda: orquestrador.ocupado
        nucleo.traducoes.definir_motor(modelo)
    return servicos


# ---------- Gravador de voz (robofael-gravar-voz) ----------
def criar_captura_audio(cfg: Configuracao, pausa_fim_s: float = 1.0) -> CapturaAudio:
    """Microfone com detecção de fala, para gravar amostras da sua voz (o escolhido nas configurações)."""
    from robofael.adaptadores.microfone import MicrofoneGoogle

    escolhido = None
    if cfg.arquivo_banco.exists():  # só lê: não cria um banco vazio (ex.: o escolhido está num disco desconectado)
        banco = BancoSqlite(cfg.arquivo_banco)
        escolhido = banco.carregar_preferencias().microfone
        banco.fechar()
    return MicrofoneGoogle(cfg.idioma, pausa_fim_s=pausa_fim_s, microfone=lambda: escolhido)


def falar_amostra(texto: str, voz: str, tom: str, ritmo: str) -> None:
    """Sintetiza e toca uma frase com a voz dada (bloqueia até terminar)."""
    from robofael.adaptadores.reprodutor import ReprodutorPygame
    from robofael.adaptadores.sintetizador import SintetizadorEdge

    reprodutor = ReprodutorPygame()
    reprodutor.tocar(reprodutor.preparar(SintetizadorEdge(voz, tom, ritmo).sintetizar(texto)), threading.Event())
