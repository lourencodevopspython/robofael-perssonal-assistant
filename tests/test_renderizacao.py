"""Renderização eficiente: canvas diferencial, fila de trabalho com orçamento e laço de quadros adaptativo.

Os testes usam um canvas falso que registra as chamadas: o custo de desenho do Tk é proporcional
ao que se envia a ele, então "quantas chamadas um quadro em repouso faz" é uma medida de
desempenho determinística (não depende da máquina)."""

import itertools

import pytest

from robofael.apresentacao.cena import CenaCanvas
from robofael.apresentacao.laco import FilaTrabalhoUI, LacoQuadros
from robofael.apresentacao.palco import FPS_ATIVO, FPS_REPOUSO, Palco
from robofael.apresentacao.tema import FUNDO, NIVEIS_HALO, gerar_halos, imagem_halo
from robofael.dominio.estados import Estado


class CanvasFalso:
    """Imita o tk.Canvas o bastante para o Palco, contando as chamadas que mudam algo."""

    def __init__(self):
        self._ids = itertools.count(1)
        self.chamadas: list[tuple] = []

    def _criar(self, *_a, **_k):
        return next(self._ids)

    create_image = create_oval = create_arc = create_text = create_rectangle = _criar

    def coords(self, item, *pontos):
        self.chamadas.append(("coords", item, pontos))

    def itemconfigure(self, item, **opcoes):
        self.chamadas.append(("config", item, opcoes))


# ---------- CenaCanvas ----------
def test_cena_so_envia_o_que_mudou():
    cv = CanvasFalso()
    cena = CenaCanvas(cv)
    cena.coords(1, 10.2, 20.4)
    cena.coords(1, 10.4, 19.6)  # arredonda para os mesmos pixels: nada a enviar
    cena.configurar(1, fill="#fff", text="oi")
    cena.configurar(1, fill="#fff", text="oi")
    cena.configurar(1, fill="#000", text="oi")  # só a opção que mudou
    assert cv.chamadas == [("coords", 1, (10, 20)), ("config", 1, {"fill": "#fff", "text": "oi"}),
                           ("config", 1, {"fill": "#000"})]
    assert cena.envios == 3


def test_cena_distingue_imagens_diferentes():
    cv, a, b = CanvasFalso(), object(), object()
    cena = CenaCanvas(cv)
    for img in (a, a, b, b, a):
        cena.configurar(7, image=img)
    assert [c[2]["image"] for c in cv.chamadas] == [a, b, a]


# ---------- FilaTrabalhoUI ----------
def test_fila_respeita_o_orcamento_e_sempre_avanca():
    tempo = [0.0]
    feitos = []

    def tarefa(nome, passos):
        for i in range(passos):
            tempo[0] += 0.003  # cada passo "custa" 3 ms
            feitos.append(f"{nome}{i}")
            yield

    fila = FilaTrabalhoUI(relogio=lambda: tempo[0], orcamento_s=0.004)
    fila.agendar(tarefa("a", 3))
    fila.agendar(tarefa("b", 1))
    fila.executar()
    assert feitos == ["a0", "a1"]  # estourou o orçamento no 2º passo: para até o próximo quadro
    fila.agendar(tarefa("u", 1), urgente=True)
    fila.executar()
    assert feitos[2] == "u0"
    while not fila.vazia:
        fila.executar()
    assert feitos == ["a0", "a1", "u0", "a2", "b0"]


# ---------- LacoQuadros ----------
def test_laco_adapta_o_ritmo_e_agenda_pelo_relogio():
    agora = [0.0]
    agendados: list[int] = []
    fps = [60]
    dts: list[float] = []

    def agendar(ms, _f):
        agendados.append(ms)

    laco = LacoQuadros(agendar, dts.append, lambda: fps[0], relogio=lambda: agora[0])
    laco.iniciar()
    assert agendados[-1] in (16, 17)
    agora[0] += 0.016
    laco._tique()
    fps[0] = FPS_REPOUSO
    agora[0] += 0.016
    laco._tique()
    assert agendados[-1] in (32, 33, 34)  # repouso: ~33 ms entre quadros
    agora[0] += 5.0  # janela minimizada: ressincroniza em vez de disparar quadros atrasados
    laco._tique()
    assert agendados[-1] == 1 and dts[-1] == pytest.approx(0.1)  # próximo quadro já; dt limitado
    laco.parar()
    laco._tique()
    assert len(dts) == 4  # parado: não desenha mais


# ---------- Palco ----------
def palco_pronto():
    cv = CanvasFalso()
    p = Palco(cv, (340, 330), 680)
    p.definir_avatar([[object() for _ in range(12)] for _ in range(3)], (236.0, 264.0))
    for estado in Estado:
        p.definir_halos(estado, [object() for _ in range(NIVEIS_HALO)])
    return p, cv


def test_palco_em_repouso_quase_nao_envia_nada_ao_tk():
    """Regressão de desempenho: o repouso já custou ~30% de um núcleo por reenviar tudo a cada quadro."""
    p, cv = palco_pronto()
    p.definir_estado(Estado.PARADO)
    for _ in range(90):  # 3 s: termina a transição de cor
        p.quadro(1 / FPS_REPOUSO, 0.0, 0.0)
    assert p.fps_desejado == FPS_REPOUSO
    cv.chamadas.clear()
    segundos = 10
    for _ in range(segundos * FPS_REPOUSO):
        p.quadro(1 / FPS_REPOUSO, 0.0, 0.0)
    por_segundo = len(cv.chamadas) / segundos
    assert por_segundo < 80  # só a rotação lenta dos arcos, o balanço do busto e a pulsação do halo
    caros = [c for c in cv.chamadas if c[1] in (p.item_avatar, p.item_halo)]
    assert len(caros) / segundos < 6  # imagens grandes: redesenho caro, só poucas vezes por segundo


def test_palco_pede_60_fps_quando_ativo_e_durante_transicoes():
    p, _ = palco_pronto()
    p.definir_estado(Estado.PARADO)
    p.quadro(1 / 60, 0.0, 0.0)
    assert p.fps_desejado == FPS_ATIVO  # a cor ainda está mudando de "iniciando" para "parado"
    for _ in range(120):
        p.quadro(1 / 60, 0.0, 0.0)
    assert p.fps_desejado == FPS_REPOUSO
    for estado in (Estado.OUVINDO, Estado.PENSANDO, Estado.FALANDO):
        p.definir_estado(estado)
        assert p.fps_desejado == FPS_ATIVO


def test_palco_funciona_antes_dos_halos_e_do_avatar_chegarem():
    cv = CanvasFalso()
    p = Palco(cv, (340, 330), 680)
    for _ in range(10):
        p.quadro(1 / 60, 0.0, 0.0)  # nada quebra; o halo fica oculto até existir
    assert not any(c[1] == p.item_halo for c in cv.chamadas)


def test_halos_sao_opacos_e_cobrem_todos_os_estados():
    """Opacos: o Tk copia os pixels em vez de misturar transparência (o que custava ~8 ms por quadro)."""
    halo = imagem_halo("#00e5ff", 1.0, tam=120)
    assert halo.mode == "RGB"
    assert halo.getpixel((0, 0)) == tuple(int(FUNDO[i:i + 2], 16) for i in (1, 3, 5))
    assert imagem_halo("#00e5ff", 1.0, tam=120, fundo=None).mode == "RGBA"
    halos = gerar_halos(primeiro=Estado.PARADO)
    assert next(iter(halos)) is Estado.PARADO and set(halos) == set(Estado)
    assert all(len(v) == NIVEIS_HALO for v in halos.values())
