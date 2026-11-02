"""Tarefas e lembretes no idioma da interface.

Cada item é guardado como foi dito ("comprar pão", "buy milk"); a exibição usa a tradução para o idioma
atual, feita pelo modelo de linguagem em segundo plano e guardada no banco: cada texto é traduzido uma
única vez por idioma. Sem modelo que traduza (modo offline), ou enquanto a tradução não chega, aparece o
texto original."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from robofael.dominio.agenda import Agenda
from robofael.i18n import Tradutor
from robofael.portas import CacheTraducoes, TradutorTextos

log = logging.getLogger(__name__)

FEITAS_VISIVEIS = 5  # o painel mostra as últimas tarefas concluídas, riscadas
LOTE = 8  # textos por pedido: no processador, um lote de 8 leva ~30 s com o modelo local ocupado
ESPERA_S = 1.5  # junta mudanças seguidas da agenda (ex.: "concluir todas") num pedido só
ESPERA_OCUPADO_S = 5.0  # o assistente está atendendo alguém: a conversa tem prioridade sobre o modelo
PAUSA_APOS_FALHA_S = 60.0


class TraducaoAgenda:
    def __init__(self, agenda: Agenda, cache: CacheTraducoes, tradutor: Tradutor,
                 ao_atualizar: Callable[[], None] = lambda: None, espera_s: float = ESPERA_S,
                 monotonico: Callable[[], float] = time.monotonic):
        self._agenda = agenda
        self._cache = cache
        self.tr = tradutor
        self._ao_atualizar = ao_atualizar
        self._espera_s = espera_s
        self._monotonico = monotonico
        self.motor: TradutorTextos | None = None
        self.ocupado: Callable[[], bool] = lambda: False  # o assistente está ouvindo, pensando ou falando
        self._conhecidas: dict[str, dict[str, str]] = {}  # idioma -> {original: tradução}
        self._trava = threading.Lock()
        self._traduzindo = threading.Lock()  # um pedido ao modelo por vez
        self._temporizador: threading.Timer | None = None
        self._pausa_ate = 0.0
        agenda.observar(self.agendar)
        tradutor.observar(lambda _idioma: self.agendar())

    def definir_motor(self, modelo: object) -> None:
        """O modelo em uso, se ele souber traduzir (o modo offline não sabe)."""
        self.motor = modelo if isinstance(modelo, TradutorTextos) else None
        self.agendar()

    def exibir(self, texto: str) -> str:
        """O texto no idioma atual, se já traduzido; senão, como foi dito."""
        return self._do_idioma(self.tr.idioma.value).get(texto, texto)

    def visiveis(self) -> list[str]:
        """Os textos que aparecem no painel: pendentes, as últimas concluídas e os próximos lembretes."""
        tarefas = self._agenda.tarefas(incluir_concluidas=True)
        feitas = [t for t in tarefas if t.feita][-FEITAS_VISIVEIS:]
        textos = [t.texto for t in tarefas if not t.feita] + [t.texto for t in feitas]
        return list(dict.fromkeys(textos + [l.texto for l in self._agenda.proximos_lembretes()]))

    def agendar(self, espera_s: float | None = None) -> None:
        """Pede a tradução do que falta, com um pequeno atraso (para juntar mudanças seguidas)."""
        if self.motor is None:
            return
        with self._trava:
            if self._temporizador is not None:
                self._temporizador.cancel()
            self._temporizador = threading.Timer(self._espera_s if espera_s is None else espera_s,
                                                 self.traduzir_pendentes)
            self._temporizador.daemon = True
            self._temporizador.start()

    def traduzir_pendentes(self) -> bool:
        """Traduz o que está visível e ainda não tem tradução no idioma atual; True se trouxe algo novo."""
        motor = self.motor
        if motor is None or self._monotonico() < self._pausa_ate or not self._traduzindo.acquire(blocking=False):
            return False
        novidade = False
        try:
            while True:
                idioma = self.tr.idioma.value
                conhecidas = self._do_idioma(idioma)
                faltando = [t for t in self.visiveis() if t not in conhecidas][:LOTE]
                if not faltando:
                    return novidade
                if self.ocupado():
                    self.agendar(ESPERA_OCUPADO_S)  # volta quando a conversa terminar
                    return novidade
                try:
                    traduzidos = motor.traduzir(faltando, idioma)
                    if len(traduzidos) != len(faltando):
                        raise ValueError(f"{len(traduzidos)} traduções para {len(faltando)} textos")
                except Exception as e:
                    log.warning("Não consegui traduzir tarefas e lembretes (%s); tento de novo em %.0f s",
                                e, PAUSA_APOS_FALHA_S)
                    self._pausa_ate = self._monotonico() + PAUSA_APOS_FALHA_S
                    return novidade
                novos = {original: _limpar(original, traducao) for original, traducao in zip(faltando, traduzidos,
                                                                                              strict=True)}
                self._cache.guardar_traducoes(idioma, novos)
                with self._trava:
                    self._conhecidas[idioma].update(novos)
                novidade = True
                self._ao_atualizar()
        finally:
            self._traduzindo.release()

    def _do_idioma(self, idioma: str) -> dict[str, str]:
        with self._trava:
            if idioma not in self._conhecidas:
                self._conhecidas[idioma] = dict(self._cache.traducoes(idioma))
            return self._conhecidas[idioma]


def _limpar(original: str, traducao: str) -> str:
    """Uma tradução vazia ou que virou um parágrafo (o modelo explicou em vez de traduzir) fica com o original."""
    traducao = traducao.strip().strip('"').strip()
    return traducao if traducao and len(traducao) <= 2 * len(original) + 40 else original
