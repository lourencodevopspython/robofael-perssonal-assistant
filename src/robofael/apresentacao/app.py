"""Janela principal do Robofael.

Uso: `robofael [--avatar cracha|selfie] [--continuo] [-v]`

Atalhos: ESPAÇO fala / cancela / interrompe · T troca o avatar · ENTER envia o texto ·
ESC interrompe (ou sai da caixa de texto) · Ctrl+Q fecha
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import signal
import threading
import tkinter as tk
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageTk

from robofael.aplicacao.sessao import (
    Nucleo,
    Servicos,
    ServicosProntos,
    aplicar_idioma,
    aplicar_inicializacao,
    aplicar_preferencias,
    ativacao_inicial,
    cerebro_em_uso,
    configurar_voz,
    fazer_backup,
    listar_modelos,
    mover_banco,
    saudacao,
    voz_inicial,
)
from robofael.apresentacao.configuracoes import (
    AcoesConfiguracoes,
    AjustesVoz,
    JanelaConfiguracoes,
    OpcoesConfiguracoes,
    ajustes_iniciais,
)
from robofael.apresentacao.laco import FilaTrabalhoUI, LacoQuadros
from robofael.apresentacao.painel import PainelAgenda
from robofael.apresentacao.palco import FPS_ATIVO, Palco
from robofael.apresentacao.tema import ERRO, FONTE, FUNDO, PRIMARIA, TEXTO_APAGADO, TEXTO_SUAVE, gerar_halos
from robofael.avatar import AVATARES, gerar_quadros
from robofael.bootstrap import iniciar_servicos, montar_nucleo
from robofael.configuracao import NOME_ASSISTENTE, Configuracao, configurar_logs
from robofael.dominio.estados import Estado
from robofael.dominio.eventos import (
    AgendaAtualizada,
    Aviso,
    EscutaPassiva,
    EstadoMudou,
    FalaReconhecida,
    Gravidade,
    NivelMicrofone,
    RespostaConcluida,
    RespostaParcial,
)
from robofael.i18n import Idioma, Tradutor
from robofael.portas import Preferencias

log = logging.getLogger(__name__)

LARGURA_PALCO, ALTURA_PALCO = 680, 720
LARGURA_PAINEL = 300
ALTURA_AVATAR = 480
CHAVE_BOTAO = {Estado.OUVINDO: "ui.botao_cancelar", Estado.PENSANDO: "ui.botao_parar",
               Estado.FALANDO: "ui.botao_interromper"}


@dataclass(frozen=True)
class AvatarPronto:
    nome: str
    quadros: list[list[Image.Image]]
    centro: tuple[float, float]


@dataclass(frozen=True)
class HalosProntos:
    halos: dict[Estado, list[Image.Image]]


class Janela:
    def __init__(self, raiz: tk.Tk, nucleo: Nucleo, avatar: str | None = None, continuo: bool = False):
        self.raiz = raiz
        self.nucleo = nucleo
        self.continuo = continuo
        self.servicos: Servicos | None = None
        self.encerramento_pedido = False  # Ctrl+C / SIGTERM (tratado no próximo quadro)
        self.tr = nucleo.tradutor
        self._estado = Estado.INICIANDO
        avatar = avatar or nucleo.preferencias.avatar or "cracha"
        self.nome_avatar = avatar if avatar in AVATARES else "cracha"
        self._configuracoes: JanelaConfiguracoes | None = None
        self._resposta = ""
        self.fila_ui = FilaTrabalhoUI()  # trabalho da thread principal, um pouco por quadro
        self._montar()
        self._assinar_eventos()

        threading.Thread(target=self._iniciar_servicos, name="servicos", daemon=True).start()
        threading.Thread(target=self._gerar_halos, name="halos", daemon=True).start()
        self._carregar_avatar(self.nome_avatar)
        self.laco = LacoQuadros(self.raiz.after, self._quadro, self._fps)
        self.laco.iniciar()

    # ---------- Layout ----------
    def _montar(self) -> None:
        r = self.raiz
        r.title(self.tr("ui.titulo_janela", nome=self.nucleo.config.nome_assistente))
        r.configure(bg=FUNDO)
        largura, altura = LARGURA_PALCO + LARGURA_PAINEL + 30, ALTURA_PALCO + 80
        x = max(0, (r.winfo_screenwidth() - largura) // 2)
        y = max(0, (r.winfo_screenheight() - altura) // 3)
        r.geometry(f"{largura}x{altura}+{x}+{y}")
        # Tamanho fixo: o palco é desenhado em coordenadas absolutas; maximizar/tela cheia
        # deixaria o avatar e os anéis fora de lugar.
        r.minsize(largura, altura)
        r.maxsize(largura, altura)
        r.resizable(False, False)

        topo = tk.Frame(r, bg=FUNDO)
        topo.pack(fill="both", expand=True, padx=(0, 14), pady=(0, 6))
        self.canvas = tk.Canvas(topo, width=LARGURA_PALCO, height=ALTURA_PALCO, bg=FUNDO, highlightthickness=0)
        self.canvas.pack(side="left")
        self.palco = Palco(self.canvas, (LARGURA_PALCO // 2, 330), LARGURA_PALCO, self.nucleo.config.nome_assistente,
                           self.tr)
        self.painel = PainelAgenda(topo, self.nucleo.agenda, self.tr, width=LARGURA_PAINEL)
        self.painel.pack(side="right", fill="y", pady=(16, 0))

        barra = tk.Frame(r, bg=FUNDO)
        barra.pack(fill="x", padx=20)
        self.entrada = tk.Entry(barra, bg="#141c30", fg=TEXTO_APAGADO, insertbackground="white", relief="flat",
                                font=(FONTE, 12))
        self.entrada.pack(side="left", fill="x", expand=True, ipady=7)
        self.entrada.insert(0, self.tr("ui.placeholder"))
        self.botao = tk.Button(barra, text=self.tr("ui.botao_falar"), command=self._alternar_microfone,
                               bg=PRIMARIA, fg="white",
                               activebackground="#1a5fd0", activeforeground="white", relief="flat", padx=16,
                               font=(FONTE, 11, "bold"), state="disabled", cursor="hand2")
        self.botao.pack(side="left", padx=(8, 0), ipady=4)
        self.botao_config = tk.Button(barra, text="⚙", command=self.abrir_configuracoes, bg="#2a3550", fg="white",
                                      activebackground="#33405f", activeforeground="white", relief="flat", padx=12,
                                      font=(FONTE, 13), cursor="hand2")
        self.botao_config.pack(side="left", padx=(8, 0), ipady=1)
        self.lbl_atalhos = tk.Label(r, text=self.tr("ui.atalhos"), bg=FUNDO, fg=TEXTO_APAGADO, font=(FONTE, 9))
        self.lbl_atalhos.pack(pady=(4, 6))

        self.entrada.bind("<FocusIn>", self._focar_entrada)
        self.entrada.bind("<FocusOut>", self._desfocar_entrada)
        self.entrada.bind("<Return>", self._enviar_texto)
        self.entrada.bind("<Escape>", self._sair_da_entrada)
        r.bind("<space>", lambda e: None if e.widget is self.entrada else self._alternar_microfone())
        r.bind("<Key-t>", lambda e: None if e.widget is self.entrada else self._trocar_avatar())
        r.bind("<Escape>", lambda _e: self._interromper())
        r.bind("<Control-q>", lambda _e: self.encerrar())
        r.protocol("WM_DELETE_WINDOW", self.encerrar)
        self.canvas.focus_set()

    def _assinar_eventos(self) -> None:
        b = self.nucleo.barramento
        b.assinar(EstadoMudou, self._ao_mudar_estado)
        b.assinar(FalaReconhecida, self._ao_reconhecer_fala)
        b.assinar(RespostaParcial, lambda e: self.palco.legenda_robo(e.texto))
        b.assinar(RespostaConcluida, lambda e: self.palco.legenda_robo(e.texto + (" …" if e.interrompida else "")))
        b.assinar(NivelMicrofone, lambda e: self.palco.definir_nivel_microfone(e.nivel))
        b.assinar(AgendaAtualizada, lambda _e: self.painel.atualizar())
        b.assinar(Aviso, self._ao_aviso)
        b.assinar(EscutaPassiva, lambda e: self.palco.definir_frase_ativacao(e.frase))
        b.assinar(ServicosProntos, self._ao_servicos_prontos)
        b.assinar(AvatarPronto, self._ao_avatar_pronto)
        b.assinar(HalosProntos, self._ao_halos_prontos)

    # ---------- Inicialização em segundo plano ----------
    def _iniciar_servicos(self) -> None:
        try:
            servicos = iniciar_servicos(self.nucleo, self.continuo)
        except Exception:
            log.exception("Falha ao iniciar os serviços de voz")
            self.nucleo.barramento.publicar(Aviso(self.tr("ui.falha_audio"), Gravidade.ERRO))
            return
        self.nucleo.barramento.publicar(ServicosProntos(servicos))

    def _ao_servicos_prontos(self, evento: ServicosProntos) -> None:
        self.servicos = s = evento.servicos
        self.botao.configure(state="normal" if s.microfone else "disabled")
        s.agendador.iniciar()
        s.orquestrador.anunciar(saudacao(self.nucleo, s.online, s.ativacao_por_voz and ativacao_inicial(self.nucleo)))
        if self.continuo and s.microfone:
            self.raiz.after(500, s.orquestrador.ouvir)
        if s.ativacao_por_voz and ativacao_inicial(self.nucleo):
            s.orquestrador.iniciar_vigia()  # começa a esperar a frase de ativação assim que ficar livre

    def _carregar_avatar(self, nome: str) -> None:
        cfg = self.nucleo.config

        def trabalho() -> None:
            try:
                quadros, centro = gerar_quadros(nome, ALTURA_AVATAR, cfg.pasta_cache_avatar, cfg.pasta_avatares)
                self.nucleo.barramento.publicar(AvatarPronto(nome, quadros, centro))
            except Exception:
                log.exception("Falha ao gerar o avatar %s", nome)
                self.nucleo.barramento.publicar(Aviso(self.tr("ui.falha_avatar"), Gravidade.ERRO))

        threading.Thread(target=trabalho, name=f"avatar-{nome}", daemon=True).start()

    def _ao_avatar_pronto(self, evento: AvatarPronto) -> None:
        if evento.nome == self.nome_avatar:  # senão o usuário já trocou de novo
            self.fila_ui.agendar(self._converter_avatar(evento))

    def _converter_avatar(self, evento: AvatarPronto) -> Iterator[None]:
        """Converte os quadros para o Tk aos poucos (um por passo da fila): sem engasgo na troca."""
        convertidos: dict[int, ImageTk.PhotoImage] = {}  # quadros repetidos viram uma única imagem Tk
        quadros: list[list[ImageTk.PhotoImage]] = []
        for linha in evento.quadros:
            quadros.append([])
            for q in linha:
                if id(q) not in convertidos:
                    convertidos[id(q)] = ImageTk.PhotoImage(q)
                    yield
                quadros[-1].append(convertidos[id(q)])
            if evento.nome != self.nome_avatar:
                return  # trocou de avatar no meio da conversão
        self.palco.definir_avatar(quadros, evento.centro)

    def _gerar_halos(self) -> None:
        try:
            self.nucleo.barramento.publicar(HalosProntos(gerar_halos(primeiro=Estado.PARADO)))
        except Exception:
            log.exception("Falha ao gerar os halos")  # o palco funciona sem eles

    def _ao_halos_prontos(self, evento: HalosProntos) -> None:
        def converter() -> Iterator[None]:
            for estado, imagens in evento.halos.items():
                convertidas = []
                for imagem in imagens:
                    convertidas.append(ImageTk.PhotoImage(imagem))
                    yield
                self.palco.definir_halos(estado, convertidas)

        self.fila_ui.agendar(converter())

    # ---------- Interação ----------
    def _alternar_microfone(self) -> None:
        if self.servicos:
            self.servicos.orquestrador.alternar_microfone()

    def _interromper(self) -> None:
        if self.servicos:
            self.servicos.orquestrador.interromper()

    def _enviar_texto(self, _evento: object = None) -> str:
        texto = self.entrada.get().strip()
        enviado = bool(texto) and not self._eh_placeholder(texto) and self.servicos is not None \
            and self.servicos.orquestrador.enviar_texto(texto)
        if enviado:
            self.entrada.delete(0, "end")
        return "break"

    # ---------- Configurações ----------
    def abrir_configuracoes(self) -> JanelaConfiguracoes:
        if self._configuracoes is not None and self._configuracoes.winfo_exists():
            self._configuracoes.lift()
            return self._configuracoes
        s = self.servicos
        sint = s.sintetizador if s else None
        voz, tom, ritmo = (sint.voz, sint.tom, sint.ritmo) if sint else voz_inicial(self.nucleo)
        ativa = s.orquestrador.vigia_ligada if s else ativacao_inicial(self.nucleo)
        inicializacao = self.nucleo.inicializacao.estado() if self.nucleo.inicializacao else None
        opcoes = OpcoesConfiguracoes(list(AVATARES), self.nucleo.ler_perfil_voz(), bool(s and s.ativacao_por_voz),
                                     self.nucleo.config.frase_ativacao, self.nucleo.microfones(), inicializacao,
                                     cerebro_em_uso(s), lambda: listar_modelos(self.nucleo),
                                     lambda: self.nucleo.banco.arquivo)
        acoes = AcoesConfiguracoes(salvar=self._salvar_configuracoes, ouvir=self._testar_voz,
                                   cancelar=self._aplicar_voz, mover_banco=self._mover_banco,
                                   fazer_backup=self._fazer_backup)
        self._configuracoes = JanelaConfiguracoes(
            self.raiz, ajustes_iniciais(self.nome_avatar, voz, tom, ritmo, ativa, self.tr.idioma.value,
                                        self.nucleo.microfone, inicializacao),
            opcoes, acoes, self.tr)
        return self._configuracoes

    def _mover_banco(self, pasta: Path) -> tuple[bool, str]:
        try:
            antigo = mover_banco(self.nucleo, pasta)
        except FileExistsError:
            return False, self.tr("cfg.banco_ja_existe")
        except Exception as e:  # disco cheio, sem permissão, cópia que não passou na verificação...
            log.warning("Não consegui mudar o banco de lugar: %s", e)
            return False, self.tr("cfg.falha_arquivo", erro=str(e))
        return True, self.tr("cfg.banco_movido", antigo=str(antigo))

    def _fazer_backup(self, destino: Path) -> tuple[bool, str]:
        try:
            copia = fazer_backup(self.nucleo, destino)
        except Exception as e:  # disco cheio, sem permissão, cópia que não passou na verificação...
            log.warning("Não consegui fazer o backup: %s", e)
            return False, self.tr("cfg.falha_arquivo", erro=str(e))
        return True, self.tr("cfg.backup_feito", arquivo=str(copia.arquivo), n=copia.registros)

    def _aplicar_voz(self, ajustes: AjustesVoz) -> None:
        configurar_voz(self.servicos, ajustes.voz, ajustes.tom, ajustes.ritmo, Idioma.de_texto(ajustes.idioma))

    def _testar_voz(self, ajustes: AjustesVoz) -> None:
        self._aplicar_voz(ajustes)
        if self.servicos:  # a frase de teste no idioma escolhido (mesmo antes de salvar)
            self.servicos.orquestrador.anunciar(Tradutor(Idioma.de_texto(ajustes.idioma))("cfg.frase_teste"))

    def _salvar_configuracoes(self, ajustes: AjustesVoz) -> None:
        idioma_antes = self.tr.idioma
        aplicar_preferencias(self.nucleo, self.servicos, Preferencias(
            ajustes.avatar, ajustes.voz, ajustes.tom, ajustes.ritmo, ajustes.ativacao_por_voz, ajustes.idioma,
            ajustes.microfone))
        inicializacao_ok = aplicar_inicializacao(self.nucleo, ajustes.abrir_ao_entrar, ajustes.comando_no_terminal)
        if self.tr.idioma is not idioma_antes:
            self._traduzir_interface()
        if ajustes.avatar != self.nome_avatar:
            self.nome_avatar = ajustes.avatar
            self._carregar_avatar(ajustes.avatar)
        if inicializacao_ok:
            self.palco.mostrar_aviso(self.tr("ui.configuracoes_salvas"), TEXTO_SUAVE, 2.5)
        else:
            self.palco.mostrar_aviso(self.tr("ui.falha_inicializacao"), ERRO, 4.0)

    def aplicar_idioma(self, idioma: Idioma) -> None:
        """Troca o idioma ao vivo: respostas, voz, reconhecimento de fala e toda a interface."""
        aplicar_idioma(self.nucleo, self.servicos, idioma)
        self._traduzir_interface()

    def _traduzir_interface(self) -> None:
        self.raiz.title(self.tr("ui.titulo_janela", nome=self.nucleo.config.nome_assistente))
        if self.entrada.get() and self._eh_placeholder(self.entrada.get()):
            self.entrada.delete(0, "end")
            self.entrada.insert(0, self.tr("ui.placeholder"))
        self.lbl_atalhos.configure(text=self.tr("ui.atalhos"))
        self._rotular_botao()
        self.painel.traduzir()
        self.palco.traduzir()

    def _rotular_botao(self) -> None:
        self.botao.configure(text=self.tr(CHAVE_BOTAO.get(self._estado, "ui.botao_falar")))

    def _eh_placeholder(self, texto: str) -> bool:
        return texto in {Tradutor(i)("ui.placeholder") for i in Idioma}

    def _trocar_avatar(self) -> None:
        nomes = list(AVATARES)
        self.nome_avatar = nomes[(nomes.index(self.nome_avatar) + 1) % len(nomes)]
        self.palco.mostrar_aviso(self.tr("ui.trocando_avatar"), TEXTO_SUAVE, 1.5)
        self._carregar_avatar(self.nome_avatar)

    def _focar_entrada(self, _evento: object = None) -> None:
        if self._eh_placeholder(self.entrada.get()):
            self.entrada.delete(0, "end")
            self.entrada.configure(fg="white")

    def _desfocar_entrada(self, _evento: object = None) -> None:
        if not self.entrada.get():
            self.entrada.insert(0, self.tr("ui.placeholder"))
            self.entrada.configure(fg=TEXTO_APAGADO)

    def _sair_da_entrada(self, _evento: object = None) -> str:
        self.entrada.delete(0, "end")
        self.canvas.focus_set()
        return "break"

    def _ao_reconhecer_fala(self, evento: FalaReconhecida) -> None:
        self.palco.legenda_usuario(evento.texto)
        self.palco.legenda_robo("")

    def _ao_mudar_estado(self, evento: EstadoMudou) -> None:
        self.palco.definir_estado(evento.estado)
        self._estado = evento.estado
        self._rotular_botao()

    def _ao_aviso(self, evento: Aviso) -> None:
        cor = ERRO if evento.gravidade is Gravidade.ERRO else TEXTO_SUAVE
        self.palco.mostrar_aviso(evento.mensagem, cor)

    # ---------- Laço de quadros ----------
    def _fps(self) -> int:
        return FPS_ATIVO if not self.fila_ui.vazia else self.palco.fps_desejado

    def _quadro(self, dt: float) -> None:
        if self.encerramento_pedido:
            self.encerrar()
            return
        self.nucleo.barramento.despachar()
        if self.servicos:
            reprodutor = self.servicos.orquestrador.reprodutor
            self.palco.quadro(dt, reprodutor.amplitude, reprodutor.forma)
        else:
            self.palco.quadro(dt, 0.0, 0.0)
        self.fila_ui.executar()

    def encerrar(self) -> None:
        self.laco.parar()
        if self.servicos:
            self.servicos.encerrar()
        self.raiz.destroy()


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="robofael",
                                description=f"{NOME_ASSISTENTE} — assistente pessoal com avatar por voz")
    p.add_argument("--avatar", choices=list(AVATARES), default=None, help="padrão: o salvo nas configurações")
    p.add_argument("--continuo", action="store_true", help="volta a ouvir sozinho após cada resposta")
    p.add_argument("--sem-ativacao", action="store_true", help="desliga a escuta da frase de ativação (\"ok Fael\")")
    p.add_argument("--idioma", choices=[i.value for i in Idioma], help="pt-BR ou en-US (padrão: o salvo)")
    p.add_argument("-v", "--verbose", action="store_true", help="logs de depuração")
    args = p.parse_args(argv)
    configurar_logs(args.verbose)

    config = Configuracao.do_ambiente()
    if args.sem_ativacao:
        config = dataclasses.replace(config, ativacao_por_voz=False)
    if args.idioma:
        config = dataclasses.replace(config, idioma=Idioma.de_texto(args.idioma).value)
    nucleo = montar_nucleo(config)
    if args.idioma:  # a opção da linha de comando vale mais que a preferência salva
        nucleo.tradutor.idioma = Idioma.de_texto(args.idioma)
    if args.sem_ativacao:  # a opção da linha de comando vale mais que a preferência salva
        nucleo.preferencias = dataclasses.replace(nucleo.preferencias, ativacao_por_voz=False)
    raiz = tk.Tk(className="robofael")  # WM_CLASS: o Ubuntu associa a janela ao ícone do .desktop
    janela = Janela(raiz, nucleo, args.avatar, args.continuo)

    def pedir_encerramento(*_sinal: object) -> None:
        janela.encerramento_pedido = True

    signal.signal(signal.SIGINT, pedir_encerramento)  # Ctrl+C no terminal fecha a janela
    signal.signal(signal.SIGTERM, pedir_encerramento)
    raiz.mainloop()


if __name__ == "__main__":
    main()
