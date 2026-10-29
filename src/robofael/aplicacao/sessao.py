"""Sessão do assistente: o que está em uso (núcleo e serviços) e as políticas que valem para ela.

Políticas (decisões do produto, testáveis sem interface nem áudio):
- idioma: preferência salva > configuração (ROBOFAEL_IDIOMA) > português;
- voz: preferência salva > perfil gravado da sua voz > voz padrão, sempre num idioma compatível;
- ativação por voz: preferência salva > configuração;
- microfone: o escolhido nas configurações (vale na próxima escuta) > o padrão do sistema;
- saudação: nome, tarefas pendentes, modo offline e como chamar o assistente.

Depende só de portas: quem monta as peças concretas é a raiz de composição (bootstrap.py)."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from robofael.aplicacao.agendador import AgendadorLembretes
from robofael.aplicacao.barramento import Barramento
from robofael.aplicacao.memoria import Memoria
from robofael.aplicacao.orquestrador import Orquestrador
from robofael.aplicacao.programas import ServicoProgramas
from robofael.configuracao import NOME_BANCO, Configuracao, salvar_local_banco
from robofael.dominio.agenda import Agenda
from robofael.i18n import Idioma, Tradutor
from robofael.portas import (
    CatalogoModelos,
    CopiaVerificada,
    DispositivosAudio,
    InicializacaoSistema,
    Microfone,
    ModeloDisponivel,
    PersistenciaAssistente,
    Preferencias,
    ProvedorIndisponivel,
    SintetizadorConfiguravel,
)

log = logging.getLogger(__name__)

TOM_PADRAO, RITMO_PADRAO = "+0Hz", "+0%"


@dataclass
class Nucleo:
    """Peças disponíveis logo na abertura (instantâneas): agenda, memória, preferências e idioma."""

    config: Configuracao
    barramento: Barramento
    agenda: Agenda
    banco: PersistenciaAssistente
    memoria: Memoria
    programas: ServicoProgramas
    preferencias: Preferencias
    tradutor: Tradutor
    ler_perfil_voz: Callable[[], dict | None] = field(default=lambda: None)
    dispositivos: DispositivosAudio | None = None  # None: não há como listar os microfones
    inicializacao: InicializacaoSistema | None = None  # None: sistema sem suporte
    catalogos: tuple[CatalogoModelos, ...] = ()  # onde procurar modelos de linguagem (Claude, Ollama)

    @property
    def microfone(self) -> str | None:
        """Microfone em uso (consultado pelos adaptadores a cada abertura)."""
        return self.preferencias.microfone

    def microfones(self) -> list[Microfone]:
        return self.dispositivos.microfones() if self.dispositivos else []

    def salvar_preferencias(self, preferencias: Preferencias) -> None:
        self.banco.salvar_preferencias(preferencias)
        self.preferencias = preferencias


@dataclass
class Servicos:
    """Peças lentas de iniciar (modelo, microfone, áudio), prontas em segundo plano."""

    orquestrador: Orquestrador
    agendador: AgendadorLembretes
    online: bool
    microfone: bool
    ativacao_por_voz: bool = False  # há detector disponível (modelo instalado + microfone)
    sintetizador: SintetizadorConfiguravel | None = None

    def encerrar(self) -> None:
        self.agendador.parar()
        self.orquestrador.encerrar()


@dataclass(frozen=True)
class CerebroEmUso:
    provedor: str  # "claude", "ollama" ou "offline"
    modelo: str | None


@dataclass(frozen=True)
class ModelosDoProvedor:
    provedor: str
    modelos: list[ModeloDisponivel]
    erro: ProvedorIndisponivel | None = None  # não deu para listar (sem chave, servidor fora do ar...)


@dataclass(frozen=True)
class ServicosProntos:
    """Evento: os serviços terminaram de iniciar."""

    servicos: Servicos


# ---------- Políticas ----------
def idioma_inicial(config: Configuracao, preferencias: Preferencias) -> Idioma:
    """Preferência salva > ROBOFAEL_IDIOMA (configuração) > português."""
    return Idioma.de_texto(preferencias.idioma, padrao=Idioma.de_texto(config.idioma))


def voz_para_idioma(voz: str | None, idioma: Idioma) -> str:
    """Mantém a voz se ela fala o idioma; senão usa a voz padrão do idioma."""
    return voz if voz and voz.startswith(idioma.value) else idioma.voz_padrao


def voz_inicial(nucleo: Nucleo) -> tuple[str, str, str]:
    """Preferências da tela de configurações > perfil gravado da sua voz > voz padrão."""
    perfil = nucleo.ler_perfil_voz() or {}
    pref = nucleo.preferencias
    voz = voz_para_idioma(pref.voz or perfil.get("voz") or nucleo.config.voz_padrao, nucleo.tradutor.idioma)
    return voz, pref.tom or perfil.get("tom") or TOM_PADRAO, pref.ritmo or perfil.get("ritmo") or RITMO_PADRAO


def ativacao_inicial(nucleo: Nucleo) -> bool:
    pref = nucleo.preferencias.ativacao_por_voz
    return nucleo.config.ativacao_por_voz if pref is None else pref


def saudacao(nucleo: Nucleo, online: bool, ativacao_por_voz: bool = False) -> str:
    tr, cfg, pend = nucleo.tradutor, nucleo.config, len(nucleo.agenda.pendentes())
    texto = tr("fala.saudacao", usuario=cfg.nome_usuario, assistente=cfg.nome_assistente)
    if pend:
        texto += tr("fala.saudacao_pendentes", n=pend, tarefas=tr.plural(pend, "un.tarefa"),
                    pendentes=tr.plural(pend, "un.pendente"))
    if not online:
        texto += tr("fala.saudacao_offline")
    if ativacao_por_voz:
        texto += tr("fala.saudacao_ativacao", frase=cfg.frase_ativacao)
    return texto


# ---------- Mudanças ao vivo ----------
def configurar_voz(servicos: Servicos | None, voz: str, tom: str, ritmo: str, idioma: Idioma) -> None:
    sint = servicos.sintetizador if servicos else None
    if sint is not None:
        sint.configurar(voz, tom, ritmo, idioma.codigo_gtts)


def aplicar_idioma(nucleo: Nucleo, servicos: Servicos | None, idioma: Idioma) -> None:
    """Troca o idioma ao vivo: respostas, reconhecimento de fala, voz e instruções do modelo."""
    nucleo.tradutor.idioma = idioma  # quem observa o tradutor (ex.: o modelo Claude) é notificado
    sint = servicos.sintetizador if servicos else None
    if sint is not None:
        configurar_voz(servicos, voz_para_idioma(sint.voz, idioma), sint.tom, sint.ritmo, idioma)


def aplicar_preferencias(nucleo: Nucleo, servicos: Servicos | None, preferencias: Preferencias) -> None:
    """Salva as preferências e as aplica ao vivo: idioma, voz, microfone e ativação por voz.
    (O avatar é da interface: ela mesma o troca.)"""
    microfone_mudou = preferencias.microfone != nucleo.preferencias.microfone
    nucleo.salvar_preferencias(preferencias)
    idioma = Idioma.de_texto(preferencias.idioma, padrao=nucleo.tradutor.idioma)
    if idioma is not nucleo.tradutor.idioma:
        aplicar_idioma(nucleo, servicos, idioma)
    if preferencias.voz:
        configurar_voz(servicos, preferencias.voz, preferencias.tom or TOM_PADRAO,
                       preferencias.ritmo or RITMO_PADRAO, idioma)
    if not (servicos and servicos.ativacao_por_voz):
        return
    ligar = servicos.orquestrador.vigia_ligada if preferencias.ativacao_por_voz is None \
        else preferencias.ativacao_por_voz
    if microfone_mudou or not ligar:
        servicos.orquestrador.desligar_vigia()  # a escuta passiva fica com o microfone aberto: reabre no novo
    if ligar:
        servicos.orquestrador.iniciar_vigia()


def aplicar_inicializacao(nucleo: Nucleo, abrir_ao_entrar: bool, comando_no_terminal: bool) -> bool:
    """Liga ou desliga abrir junto com o computador e o comando no terminal; False se falhou."""
    if nucleo.inicializacao is None:
        return True
    try:
        nucleo.inicializacao.aplicar(abrir_ao_entrar, comando_no_terminal)
    except OSError as e:
        log.warning("Não foi possível mudar a inicialização: %s", e)
        return False
    return True


# ---------- Modelos de linguagem ----------
def cerebro_em_uso(servicos: Servicos | None) -> CerebroEmUso | None:
    """Quem está gerando as respostas (None enquanto os serviços iniciam)."""
    if servicos is None:
        return None
    modelo = servicos.orquestrador.modelo
    return CerebroEmUso(getattr(modelo, "provedor", "offline"), getattr(modelo, "modelo", None))


def listar_modelos(nucleo: Nucleo) -> list[ModelosDoProvedor]:
    """Modelos compatíveis de cada provedor, consultados em paralelo (rede: chamar fora da interface)."""

    def consultar(catalogo: CatalogoModelos) -> ModelosDoProvedor:
        try:
            return ModelosDoProvedor(catalogo.provedor, catalogo.modelos())
        except ProvedorIndisponivel as e:
            return ModelosDoProvedor(catalogo.provedor, [], e)
        except Exception as e:  # um provedor com defeito não esconde o outro
            log.warning("Falha ao listar os modelos de %s: %s", catalogo.provedor, e)
            return ModelosDoProvedor(catalogo.provedor, [], ProvedorIndisponivel("modelos.erro",
                                                                                 detalhe=type(e).__name__))

    if not nucleo.catalogos:
        return []
    with ThreadPoolExecutor(max_workers=len(nucleo.catalogos), thread_name_prefix="modelos") as pool:
        return list(pool.map(consultar, nucleo.catalogos))


# ---------- Banco de dados ----------
def mover_banco(nucleo: Nucleo, pasta: Path) -> Path:
    """Passa a guardar o banco em `pasta/memoria.db`, com o assistente em uso, e lembra a escolha
    nas próximas aberturas. Devolve onde ficou o arquivo antigo (renomeado, nunca apagado).
    Levanta FileExistsError se já houver um banco na pasta (não sobrescreve dados de ninguém)."""
    destino = Path(pasta).expanduser().resolve() / NOME_BANCO
    antigo = nucleo.banco.mover_para(destino)
    salvar_local_banco(nucleo.config.pasta_dados, destino)
    padrao = destino == nucleo.config.arquivo_banco_padrao.resolve()
    nucleo.config = dataclasses.replace(nucleo.config, banco_escolhido=None if padrao else destino)
    return antigo


def fazer_backup(nucleo: Nucleo, destino: Path) -> CopiaVerificada:
    return nucleo.banco.copiar_para(Path(destino).expanduser())
