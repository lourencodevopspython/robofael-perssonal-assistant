"""Pipeline de fala em streaming: texto → frases → áudio → alto-falante.

    modelo (stream de texto) ──frases──▶ sintetizador (mp3 → faixa) ──faixas──▶ reprodutor
          thread "pensar"                     thread "sintetizar"             thread de quem chamou

A primeira frase começa a tocar enquanto o modelo ainda escreve as próximas e o sintetizador
prepara a seguinte. Um único `threading.Event` cancela os três estágios."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturoAtrasado
from dataclasses import dataclass

from robofael.aplicacao.barramento import Barramento
from robofael.aplicacao.frases import DivisorFrases
from robofael.dominio.eventos import RespostaParcial
from robofael.i18n import Tradutor
from robofael.portas import Faixa, ReprodutorAudio, SintetizadorVoz

log = logging.getLogger(__name__)

_FIM = object()  # sentinela de fim de fila
SINTESES_SIMULTANEAS = 2  # adianta a próxima frase enquanto uma ainda é sintetizada


@dataclass(frozen=True, slots=True)
class Fala:
    texto: str
    interrompida: bool


class PipelineFala:
    def __init__(self, sintetizador: SintetizadorVoz, reprodutor: ReprodutorAudio, barramento: Barramento,
                 tradutor: Tradutor, ao_comecar_a_tocar: Callable[[], None] = lambda: None):
        self.sintetizador = sintetizador
        self.reprodutor = reprodutor
        self.barramento = barramento
        self.tr = tradutor
        self._ao_comecar_a_tocar = ao_comecar_a_tocar
        self._estagio_anterior: threading.Thread | None = None  # "pensar" de uma fala cancelada
        self._sinteses = ThreadPoolExecutor(SINTESES_SIMULTANEAS, thread_name_prefix="sintese")

    def falar(self, fonte: Iterable[str], cancelar: threading.Event) -> Fala:
        """Transforma o texto (em streaming) em fala, publicando o texto parcial à medida que chega."""
        self._esperar_fala_cancelada()
        frases: queue.SimpleQueue = queue.SimpleQueue()
        faixas: queue.SimpleQueue = queue.SimpleQueue()
        partes: list[str] = []
        pensar = self._iniciar_estagio("pensar", self._pensar, fonte, partes, frases, cancelar)
        sintetizar = self._iniciar_estagio("sintetizar", self._sintetizar, frases, faixas, cancelar)
        self._tocar(faixas, cancelar)
        interrompida = cancelar.is_set()
        if interrompida:
            self._estagio_anterior = pensar  # libera quem chamou na hora; o estágio termina sozinho
        else:
            pensar.join()
            sintetizar.join()
        return Fala("".join(partes).strip(), interrompida)

    def _esperar_fala_cancelada(self) -> None:
        # A resposta cancelada ainda pode estar desfazendo a rodada no modelo: espera para
        # nunca haver duas gerações mexendo no mesmo histórico.
        if self._estagio_anterior is not None:
            self._estagio_anterior.join()
            self._estagio_anterior = None

    @staticmethod
    def _iniciar_estagio(nome: str, alvo: Callable[..., None], *args: object) -> threading.Thread:
        t = threading.Thread(target=alvo, args=args, name=f"pipeline-{nome}", daemon=True)
        t.start()
        return t

    def _pensar(self, fonte: Iterable[str], partes: list[str], frases: queue.SimpleQueue,
                cancelar: threading.Event) -> None:
        divisor = DivisorFrases()
        iterador = iter(fonte)
        try:
            for pedaco in iterador:
                if cancelar.is_set():
                    break
                partes.append(pedaco)
                self.barramento.publicar(RespostaParcial("".join(partes)))
                for frase in divisor.adicionar(pedaco):
                    frases.put(frase)
            else:
                for frase in divisor.finalizar():
                    frases.put(frase)
        except Exception:
            log.exception("Falha ao gerar a resposta")
            falha = self.tr("orq.falha")
            partes.append((" " if partes else "") + falha)
            frases.put(falha)
        finally:
            fechar = getattr(iterador, "close", None)  # geradores: interrompe o streaming no modelo
            if fechar:
                fechar()
            frases.put(_FIM)

    def _sintetizar(self, frases: queue.SimpleQueue, faixas: queue.SimpleQueue, cancelar: threading.Event) -> None:
        """Pede a síntese de cada frase assim que ela fica pronta, até SINTESES_SIMULTANEAS ao mesmo
        tempo (a síntese é uma ida e volta pela rede de ~1 s); a ordem de reprodução é a das frases."""
        while (frase := frases.get()) is not _FIM:
            if not cancelar.is_set():  # cancelado: só esvazia a fila
                faixas.put(self._sinteses.submit(self._sintetizar_frase, frase, cancelar))
        faixas.put(_FIM)

    def _sintetizar_frase(self, frase: str, cancelar: threading.Event) -> bytes | None:
        if cancelar.is_set():
            return None
        try:
            return self.sintetizador.sintetizar(frase)
        except Exception:
            log.exception("Falha ao sintetizar: %r", frase)
            return None

    def _proxima_faixa(self, faixas: queue.SimpleQueue, cancelar: threading.Event) -> Faixa | None | object:
        """A próxima faixa pronta para tocar, _FIM, ou None se a frase falhou ou foi cancelada."""
        while not cancelar.is_set():
            try:
                item = faixas.get(timeout=0.05)
            except queue.Empty:
                continue
            if item is _FIM:
                return _FIM
            while not cancelar.is_set():
                try:
                    audio = item.result(timeout=0.05)
                except FuturoAtrasado:
                    continue
                # Decodificar (~20 ms) fica aqui, numa thread só: o mixer do pygame não é para uso concorrente
                return self.reprodutor.preparar(audio) if audio else None
        return None

    def _tocar(self, faixas: queue.SimpleQueue, cancelar: threading.Event) -> None:
        while not cancelar.is_set():
            try:
                faixa = self._proxima_faixa(faixas, cancelar)
            except Exception:
                log.exception("Falha ao preparar o áudio de uma frase")
                continue
            if faixa is _FIM:
                return
            if faixa is None:
                continue
            self._ao_comecar_a_tocar()
            self.reprodutor.tocar(faixa, cancelar)  # type: ignore[arg-type]
