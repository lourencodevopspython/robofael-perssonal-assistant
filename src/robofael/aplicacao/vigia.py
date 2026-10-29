"""Escuta passiva ("vigia"): espera a frase de ativação ("ok Fael") enquanto o assistente está parado.

A vigia só abre o microfone quando não há interação em andamento e o libera, sob a mesma
trava, assim que uma interação pede (ESPAÇO, texto, lembrete). Depois de algumas falhas
seguidas (ex.: microfone desconectado) ela se desliga e avisa."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from robofael.aplicacao.barramento import Barramento
from robofael.dominio.eventos import Aviso, EscutaPassiva, Gravidade
from robofael.i18n import Tradutor
from robofael.portas import Ativacao, DetectorAtivacao

log = logging.getLogger(__name__)

FALHAS_SEGUIDAS_VIGIA = 3


class VigiaAtivacao:
    def __init__(self, detector: DetectorAtivacao, barramento: Barramento, tradutor: Tradutor,
                 ocupado: Callable[[], bool], ao_ativar: Callable[[Ativacao], object]):
        self.detector = detector
        self.barramento = barramento
        self.tr = tradutor
        self._ocupado = ocupado
        self._ao_ativar = ao_ativar
        self._thread: threading.Thread | None = None
        self._trava = threading.Lock()
        self._cancelar_escuta: threading.Event | None = None
        self._habilitada = threading.Event()
        self._encerrada = threading.Event()
        self.microfone_livre = threading.Event()  # a vigia não está com o microfone aberto
        self.microfone_livre.set()

    @property
    def ligada(self) -> bool:
        return self._habilitada.is_set()

    def ligar(self) -> None:
        self._habilitada.set()
        if self._thread is None:
            self._thread = threading.Thread(target=self._vigiar, name="escuta-passiva", daemon=True)
            self._thread.start()
        self.barramento.publicar(EscutaPassiva(self.detector.frase))

    def desligar(self) -> None:
        self._habilitada.clear()
        self.liberar_microfone()
        self.barramento.publicar(EscutaPassiva(None))

    def liberar_microfone(self) -> None:
        """Interrompe a escuta em andamento (a vigia volta a escutar quando estiver livre)."""
        with self._trava:
            if self._cancelar_escuta is not None:
                self._cancelar_escuta.set()

    def encerrar(self) -> None:
        self._encerrada.set()
        self.liberar_microfone()

    def _vigiar(self) -> None:
        falhas = 0
        while not self._encerrada.is_set():
            if not self._habilitada.wait(0.2):
                continue  # desligada nas configurações
            cancelar = self._reservar_microfone()
            if cancelar is None:
                self._encerrada.wait(0.1)
                continue
            ativacao, falhou = self._escutar(cancelar)
            falhas = falhas + 1 if falhou else 0
            if falhas >= FALHAS_SEGUIDAS_VIGIA:
                self.barramento.publicar(Aviso(self.tr("orq.vigia_desligada"), Gravidade.ERRO))
                self.barramento.publicar(EscutaPassiva(None))
                return
            if falhas:
                self._encerrada.wait(1.0)
            elif ativacao is not None and not cancelar.is_set():
                self._ao_ativar(ativacao)

    def _reservar_microfone(self) -> threading.Event | None:
        """Token de cancelamento da escuta, ou None se uma interação já começou."""
        with self._trava:  # nunca abre o microfone se uma interação já começou
            if self._ocupado() or not self._habilitada.is_set():
                return None
            self._cancelar_escuta = threading.Event()
            self.microfone_livre.clear()
            return self._cancelar_escuta

    def _escutar(self, cancelar: threading.Event) -> tuple[Ativacao | None, bool]:
        try:
            return self.detector.aguardar(cancelar), False
        except Exception:
            log.exception("Falha na escuta passiva")
            return None, True
        finally:
            self.microfone_livre.set()
