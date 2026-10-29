import numpy as np
import pytest

from conftest import requer_fotos
from robofael.avatar import AVATARES, FORMAS, NIVEIS_BOCA, renderizador
from robofael.avatar.renderizador import PROPORCAO_BUSTO, _caixa_busto, _camisa, _carregar, gerar_quadros
from robofael.configuracao import Configuracao

pytestmark = requer_fotos

PASTA_IMAGENS = Configuracao.do_ambiente().pasta_avatares

ALTURA_TESTE = 160  # pequeno para os testes rodarem rápido


@pytest.mark.parametrize("nome", list(AVATARES))
def test_caixa_do_busto_centrada_na_cabeca(nome):
    cfg = AVATARES[nome]
    x0, y0, x1, y1 = _caixa_busto(cfg)
    assert (x0 + x1) / 2 == pytest.approx(cfg["cabeca"][0])
    assert y0 < cfg["cabeca"][1] < cfg["queixo"] < y1
    assert (x1 - x0) / (y1 - y0) == pytest.approx(PROPORCAO_BUSTO)


@pytest.mark.parametrize("nome", list(AVATARES))
def test_assets_existem(nome):
    cfg = AVATARES[nome]
    for chave in ("arquivo", "arquivo_hd"):
        if chave in cfg:
            assert (PASTA_IMAGENS / cfg[chave]).is_file()


@pytest.mark.lento
def test_camisa_troca_a_roupa_e_preserva_o_rosto():
    img, g = _carregar(AVATARES["cracha"], 400, PASTA_IMAGENS)
    vestida = np.asarray(_camisa(img, g)).astype(int)
    original = np.asarray(img).astype(int)
    cx, ylado, yfrente, hw = g["pescoco"]
    testa = (int(g["topo"] + 0.15 * (g["queixo"] - g["topo"])), int(cx))
    peito = (int(yfrente + 1.6 * hw), int(cx - 1.5 * hw))
    assert np.array_equal(vestida[testa], original[testa])  # rosto intacto
    assert np.abs(vestida[peito][:3] - original[peito][:3]).sum() > 0  # roupa trocada
    assert np.array_equal(vestida[..., 3], original[..., 3])  # silhueta mantida


@pytest.fixture(scope="module")
def quadros_cracha(tmp_path_factory):
    cache = tmp_path_factory.mktemp("cache")
    quadros, centro = gerar_quadros("cracha", ALTURA_TESTE, pasta_cache=cache, pasta_imagens=PASTA_IMAGENS)
    return quadros, centro, cache


@pytest.mark.lento
def test_gera_todos_os_quadros_do_mesmo_tamanho(quadros_cracha):
    quadros, centro, _ = quadros_cracha
    assert len(quadros) == len(FORMAS) and all(len(linha) == NIVEIS_BOCA for linha in quadros)
    tamanhos = {q.size for linha in quadros for q in linha}
    assert len(tamanhos) == 1
    w, h = tamanhos.pop()
    assert 0 < centro[0] < w and 0 < centro[1] < h
    assert centro[0] == pytest.approx(w / 2)  # busto centralizado na horizontal


@pytest.mark.lento
def test_boca_fechada_e_o_mesmo_quadro_em_todos_os_formatos(quadros_cracha):
    quadros, _, _ = quadros_cracha
    assert all(linha[0] is quadros[0][0] for linha in quadros)  # renderizado uma vez só


@pytest.mark.lento
def test_boca_escurece_conforme_abre(quadros_cracha):
    quadros, _, _ = quadros_cracha
    _, g = _carregar(AVATARES["cracha"], ALTURA_TESTE * renderizador.SUPERAMOSTRAGEM, PASTA_IMAGENS)
    k = renderizador.SUPERAMOSTRAGEM
    mx, my, mw = g["mx"] / k + renderizador.MARGEM, g["my"] / k + renderizador.MARGEM, g["mw"] / k
    regiao = (int(mx - mw / 3), int(my - 1), int(mx + mw / 3), int(my + mw / 3))

    def brilho(img):
        return np.asarray(img.crop(regiao).convert("L")).mean()

    neutra = quadros[FORMAS.index("neutra")]
    valores = [brilho(neutra[n]) for n in (0, NIVEIS_BOCA // 2, NIVEIS_BOCA - 1)]
    assert valores[0] > valores[1] > valores[2]


@pytest.mark.lento
def test_segunda_chamada_usa_o_cache(quadros_cracha, monkeypatch):
    _, centro, cache = quadros_cracha
    monkeypatch.setattr(renderizador, "_boca", lambda *a: pytest.fail("deveria ler do cache"))
    quadros, centro2 = gerar_quadros("cracha", ALTURA_TESTE, pasta_cache=cache, pasta_imagens=PASTA_IMAGENS)
    assert centro2 == centro and len(quadros[0]) == NIVEIS_BOCA
