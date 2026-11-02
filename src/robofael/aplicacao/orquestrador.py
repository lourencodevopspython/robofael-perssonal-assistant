"""Orquestra a conversa: ouvir → pensar → falar.

Coordena três colaboradores, cada um com uma única responsabilidade:
- `PipelineFala` transforma o texto do modelo em fala, em streaming (aplicacao/pipeline.py);
- `VigiaAtivacao` espera "ok <nome>" enquanto o assistente está parado (aplicacao/vigia.py);
- `MaquinaEstados` garante transições válidas (PARADO → OUVINDO → PENSANDO → FALANDO).

O orquestrador decide QUANDO cada um age: uma interação por vez, um token de cancelamento
por interação e anúncios (saudação, lembretes) encaixados entre as interações."""

from __future__ import annotations

import logging
import queue
import threading
from collections.abc import Callable, Iterable

from robofael.aplicacao.barramento import Barramento
from robofael.aplicacao.documentos import ServicoDocumentos
from robofael.aplicacao.pipeline import Fala, PipelineFala
from robofael.aplicacao.vigia import FALHAS_SEGUIDAS_VIGIA, VigiaAtivacao
from robofael.dominio.ativacao import extrair_comando
from robofael.dominio.documentos import PedidoDocumento, interpretar_pedido_documento
from robofael.dominio.estados import Estado, MaquinaEstados
from robofael.dominio.eventos import (
    Aviso,
    EscutaPassiva,
    EstadoMudou,
    FalaReconhecida,
    Gravidade,
    NivelMicrofone,
    RespostaConcluida,
    RespostaParcial,
)
from robofael.dominio.linguagem import eh_despedida, pede_troca_idioma
from robofael.i18n import Idioma, Tradutor
from robofael.portas import (
    Ativacao,
    DetectorAtivacao,
    ModeloLinguagem,
    ReconhecedorFala,
    RedatorDocumentos,
    ReprodutorAudio,
    SintetizadorVoz,
)

log = logging.getLogger(__name__)

MSG_FALHA = Tradutor()("orq.falha")  # em português; em execução usa-se o tradutor configurado
__all__ = ["FALHAS_SEGUIDAS_VIGIA", "MSG_FALHA", "Orquestrador"]


class Orquestrador:
    def __init__(self, modelo: ModeloLinguagem, sintetizador: SintetizadorVoz, reprodutor: ReprodutorAudio,
                 barramento: Barramento, reconhecedor: ReconhecedorFala | None = None, continuo: bool = False,
                 estados: MaquinaEstados | None = None, ativador: DetectorAtivacao | None = None,
                 tradutor: Tradutor | None = None, documentos: ServicoDocumentos | None = None):
        self.modelo = modelo
        self.documentos = documentos  # "gerar doc" (None: o pedido vai ao modelo como qualquer outro)
        self.reconhecedor = reconhecedor
        self.barramento = barramento
        self.continuo = continuo
        self.tr = tradutor or Tradutor()
        self.estados = estados or MaquinaEstados(lambda e: barramento.publicar(EstadoMudou(e)))
        self._interacao = threading.Lock()  # uma interação por vez
        self._cancelar = threading.Event()
        self._anuncios: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._threads: list[threading.Thread] = []
        self._texto_pendente: str | None = None  # pedido digitado durante uma interação
        self._trava_pendente = threading.Lock()
        self.pipeline = PipelineFala(sintetizador, reprodutor, barramento, self.tr,
                                     ao_comecar_a_tocar=lambda: self._ir_para(Estado.FALANDO))
        self.vigia: VigiaAtivacao | None = None
        self.ativador = ativador
        # "mudar para inglês": quem troca o idioma de tudo (e salva a escolha); None: o pedido vai ao modelo
        self.trocar_idioma: Callable[[Idioma], None] | None = None

    @property
    def reprodutor(self) -> ReprodutorAudio:
        return self.pipeline.reprodutor

    @reprodutor.setter
    def reprodutor(self, reprodutor: ReprodutorAudio) -> None:
        self.pipeline.reprodutor = reprodutor

    @property
    def sintetizador(self) -> SintetizadorVoz:
        return self.pipeline.sintetizador

    @sintetizador.setter
    def sintetizador(self, sintetizador: SintetizadorVoz) -> None:
        self.pipeline.sintetizador = sintetizador

    @property
    def ativador(self) -> DetectorAtivacao | None:
        return self.vigia.detector if self.vigia else None

    @ativador.setter
    def ativador(self, detector: DetectorAtivacao | None) -> None:
        if self.vigia is not None:
            self.vigia.encerrar()
        self.vigia = VigiaAtivacao(detector, self.barramento, self.tr, lambda: self.ocupado,
                                   lambda ativacao: self._iniciar(None, ativacao=ativacao)) if detector else None

    # ---------- Comandos da interface ----------
    @property
    def ocupado(self) -> bool:
        return self._interacao.locked()

    def alternar_microfone(self) -> None:
        """ESPAÇO / botão: começa a ouvir; se já estiver ouvindo ou falando, interrompe."""
        if self.estados.em(Estado.OUVINDO, Estado.FALANDO, Estado.PENSANDO):
            self.interromper()
        else:
            self.ouvir()

    def ouvir(self) -> bool:
        if self.reconhecedor is None:
            self.barramento.publicar(Aviso(self.tr("orq.sem_microfone"), Gravidade.ERRO))
            return False
        return self._iniciar(None)

    def enviar_texto(self, texto: str) -> bool:
        """Atende o texto agora; se o assistente estiver ocupado (ouvindo, pensando ou falando),
        interrompe o que está fazendo e atende o pedido novo logo em seguida."""
        texto = texto.strip()
        if not texto:
            return False
        if self._iniciar(texto):
            return True
        with self._trava_pendente:
            self._texto_pendente = texto  # um pedido mais novo substitui o anterior
        self.interromper()
        if not self.ocupado:  # a interação terminou entre a tentativa e agora
            self._atender_pendente()
        return True

    def anunciar(self, texto: str) -> None:
        """Fala algo por iniciativa própria (saudação, lembrete) assim que estiver livre."""
        self._anuncios.put(texto)
        self._iniciar(None, so_anuncios=True)

    def interromper(self) -> None:
        self._cancelar.set()

    def iniciar_vigia(self) -> bool:
        """Liga (ou religa) a escuta passiva da frase de ativação, se houver detector."""
        if self.vigia is None:
            return False
        self.vigia.ligar()
        return True

    def desligar_vigia(self) -> None:
        """Desliga a escuta passiva e libera o microfone (pode ser religada depois)."""
        if self.vigia is None:
            self.barramento.publicar(EscutaPassiva(None))
            return
        self.vigia.desligar()

    @property
    def vigia_ligada(self) -> bool:
        return self.vigia is not None and self.vigia.ligada

    def encerrar(self) -> None:
        if self.vigia is not None:
            self.vigia.encerrar()
        self.interromper()

    def aguardar(self, timeout: float = 5.0) -> None:
        """Espera as threads em andamento terminarem (usado em testes e no encerramento)."""
        for t in list(self._threads):
            t.join(timeout)

    # ---------- Ciclo ----------
    def _iniciar(self, texto: str | None, so_anuncios: bool = False, ativacao: Ativacao | None = None) -> bool:
        if not self._interacao.acquire(blocking=False):
            return False
        if self.vigia is not None:
            self.vigia.liberar_microfone()  # a interação usa o microfone
        # Token novo criado aqui (e não na thread): um interromper() logo após o ESPAÇO
        # nunca se perde, e estágios cancelados de antes não são reativados.
        self._cancelar = threading.Event()
        t = threading.Thread(target=self._executar, args=(texto, so_anuncios, ativacao), name="interacao",
                             daemon=True)
        self._threads = [x for x in self._threads if x.is_alive()] + [t]
        t.start()
        return True

    def _executar(self, texto: str | None, so_anuncios: bool, ativacao: Ativacao | None = None) -> None:
        try:
            if self.vigia is not None:
                self.vigia.microfone_livre.wait(2.0)  # a escuta passiva fecha o microfone em ~100 ms
            self._falar_anuncios()
            if not so_anuncios:
                self._ciclo(texto, ativacao)
            self._falar_anuncios()
        except Exception:
            log.exception("Falha na interação")
            self.barramento.publicar(Aviso(self.tr("orq.falha"), Gravidade.ERRO))
        finally:
            self._ir_para(Estado.PARADO)
            self._interacao.release()
        if self._atender_pendente():
            return
        if not self._anuncios.empty():  # chegou um lembrete no finzinho
            self._iniciar(None, so_anuncios=True)

    def _atender_pendente(self) -> bool:
        """Inicia o pedido digitado durante a interação anterior, se houver (no máximo uma vez)."""
        with self._trava_pendente:
            texto, self._texto_pendente = self._texto_pendente, None
        if texto is None:
            return False
        if self._iniciar(texto):
            return True
        with self._trava_pendente:  # outra interação começou antes: atende quando ela terminar
            if self._texto_pendente is None:
                self._texto_pendente = texto
        return False

    def _ciclo(self, texto: str | None, ativacao: Ativacao | None = None) -> None:
        if ativacao is not None:
            texto = self._interpretar_ativacao(ativacao)
        while True:
            if texto is None:
                texto = self._escutar()
                if texto is None:
                    if self.continuo and not self._cancelar.is_set():
                        continue  # silêncio no modo contínuo: segue ouvindo
                    return
            self.barramento.publicar(FalaReconhecida(texto))
            self._ir_para(Estado.PENSANDO)
            idioma = pede_troca_idioma(texto) if self.trocar_idioma else None
            pedido = interpretar_pedido_documento(texto) if self.documentos and idioma is None else None
            if idioma is not None:
                interrompida = self._trocar_idioma(idioma)
            else:
                interrompida = self._gerar_documento(pedido) if pedido else self._responder(texto)
            if interrompida or not self.continuo or eh_despedida(texto) or self.reconhecedor is None:
                return
            self._falar_anuncios()
            texto = None

    def _escutar(self) -> str | None:
        assert self.reconhecedor is not None  # garantido por ouvir()
        self._ir_para(Estado.OUVINDO)
        try:
            texto = self.reconhecedor.ouvir(self._cancelar, lambda n: self.barramento.publicar(NivelMicrofone(n)))
        except Exception as e:
            self.barramento.publicar(Aviso(str(e) or self.tr("orq.falha_microfone"), Gravidade.ERRO))
            texto = None
        self.barramento.publicar(NivelMicrofone(0.0))
        self._ir_para(Estado.PARADO)
        return texto.strip() if texto and texto.strip() else None

    def _interpretar_ativacao(self, ativacao: Ativacao) -> str | None:
        """'ok Fael, anota tarefa X' vira o comando 'anota tarefa X'. Só 'ok Fael':
        toca o sinal sonoro e devolve None (o ciclo passa a ouvir o comando)."""
        texto: str | None = None
        if ativacao.comando or ativacao.audio is not None:
            self._ir_para(Estado.OUVINDO)
            texto = ativacao.comando or None  # transcrição local (aproximada) como reserva
            if ativacao.audio is not None and self.reconhecedor is not None and self.ativador is not None:
                try:
                    completo = self.reconhecedor.transcrever(ativacao.audio)
                except Exception:
                    log.warning("Falha ao transcrever o comando dito com a ativação", exc_info=True)
                    completo = None
                if completo:
                    texto = extrair_comando(completo, ativacao.comando, self.ativador.frase,
                                            ativacao.audio_inclui_frase)
        if texto:
            return texto
        self._ir_para(Estado.OUVINDO)
        sinal = self.reprodutor.sinal_ativacao()
        if sinal is not None:
            self.reprodutor.tocar(sinal, self._cancelar)
        return None

    def _falar_anuncios(self) -> None:
        while not self._anuncios.empty():
            self._cancelar = threading.Event()  # token novo: não reativa estágios cancelados
            self._falar([self._anuncios.get()])

    def _responder(self, texto: str) -> bool:
        """Resposta do modelo, falada em streaming. Devolve True se foi interrompida."""
        fala = self._falar(self.modelo.responder(texto))
        if self.documentos is not None and not fala.interrompida:
            self.documentos.registrar_troca(texto, fala.texto)  # para um "gerar doc" logo depois
        return fala.interrompida

    def _trocar_idioma(self, idioma: Idioma) -> bool:
        """Troca o idioma das respostas, da voz e do reconhecimento e confirma já no idioma novo."""
        assert self.trocar_idioma is not None
        if idioma is self.tr.idioma:
            return self._falar([self.tr("idioma.ja_em_uso")]).interrompida
        self.trocar_idioma(idioma)
        return self._falar([self.tr("idioma.trocado")]).interrompida

    # ---------- Gerar documento ----------
    def _gerar_documento(self, pedido: PedidoDocumento) -> bool:
        """"gerar doc": salva a última resposta; "gerar doc sobre X": escreve sobre X (sem ler o documento
        inteiro em voz alta) e salva. Só a confirmação é falada. Devolve True se foi interrompida."""
        assert self.documentos is not None
        if pedido.assunto is None:
            troca = self.documentos.ultima_troca
            if troca is None:
                return self._falar([self.tr("doc.nada")]).interrompida
            return self._salvar_documento(troca.pergunta, troca.resposta)
        if self._falar([self.tr("doc.escrevendo", assunto=pedido.assunto)]).interrompida:
            return True
        self._ir_para(Estado.PARADO)  # falando -> pensando passa por parado (máquina de estados)
        self._ir_para(Estado.PENSANDO)
        conteudo = self._escrever(self.documentos.pedido_ao_modelo(pedido.assunto, self.modelo.online))
        if conteudo is None:
            return True  # interrompido enquanto escrevia
        if not conteudo.strip():
            return self._falar([self.tr("doc.vazio")]).interrompida
        return self._salvar_documento(pedido.assunto, conteudo)

    def _escrever(self, pedido: str) -> str | None:
        """Texto completo do modelo, sem falar (a legenda mostra o progresso); None se interrompido."""
        partes: list[str] = []
        modelo = self.modelo  # Claude e Ollama escrevem textos longos; o modo offline só responde
        fonte = iter(modelo.escrever(pedido) if isinstance(modelo, RedatorDocumentos) else modelo.responder(pedido))
        try:
            for pedaco in fonte:
                if self._cancelar.is_set():
                    return None
                partes.append(pedaco)
                self.barramento.publicar(RespostaParcial("".join(partes)))
        except Exception:
            log.exception("Falha ao escrever o documento")
            return ""  # vira o aviso "não consegui escrever esse documento"
        finally:
            fechar = getattr(fonte, "close", None)  # geradores: interrompe o streaming no modelo
            if fechar:
                fechar()
        return None if self._cancelar.is_set() else "".join(partes)

    def _salvar_documento(self, pedido: str, conteudo: str) -> bool:
        assert self.documentos is not None
        try:
            caminho = self.documentos.salvar(pedido, conteudo)
        except OSError:
            log.exception("Falha ao salvar o documento")
            return self._falar([self.tr("doc.falha")]).interrompida
        log.info("Documento salvo em %s", caminho)
        self.barramento.publicar(Aviso(self.tr("doc.salvo_aviso", caminho=caminho)))
        pasta = f"{caminho.parent.parent.name}, {caminho.parent.name}" if caminho.parent.parent.name else \
            caminho.parent.name
        return self._falar([self.tr("doc.salvo", pasta=pasta)]).interrompida

    def _falar(self, fonte: Iterable[str]) -> Fala:
        """Fala o texto (em streaming) e publica a resposta concluída."""
        fala = self.pipeline.falar(fonte, self._cancelar)
        if self.estados.atual is Estado.PENSANDO:
            self._ir_para(Estado.PARADO)  # resposta sem áudio (vazia ou só falhas de síntese)
        self.barramento.publicar(RespostaConcluida(fala.texto, fala.interrompida))
        return fala

    def _ir_para(self, estado: Estado) -> None:
        if self.estados.atual is not estado:
            self.estados.ir_para(estado)
