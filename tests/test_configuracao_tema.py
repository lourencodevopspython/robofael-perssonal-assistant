from pathlib import Path

import pytest

from robofael.apresentacao.tema import CORES, ROTULOS, aproximar, hex_para_rgb, misturar, rgb_para_hex
from robofael.configuracao import RAIZ_PROJETO, Configuracao
from robofael.dominio.estados import Estado


def test_padroes_sem_variaveis_de_ambiente():
    c = Configuracao.do_ambiente({})
    assert (c.nome_usuario, c.voz_padrao, c.modelo) == ("Rafael", "pt-BR-AntonioNeural", "claude-opus-5-5")
    assert c.nome_assistente == "Robofael"
    assert c.ativacao_por_voz and c.frase_ativacao == "ok Fael"
    assert c.pasta_modelo_ativacao == RAIZ_PROJETO / "modelos" / "vosk-model-small-pt-0.3"
    assert c.pasta_dados == RAIZ_PROJETO / "dados"
    assert c.arquivo_agenda == RAIZ_PROJETO / "dados" / "agenda.json"
    assert c.pasta_cache_avatar == RAIZ_PROJETO / ".cache" / "avatar"
    assert c.pasta_avatares.is_dir()


def test_variaveis_de_ambiente_sobrescrevem(tmp_path):
    c = Configuracao.do_ambiente({"ROBOFAEL_USUARIO": "Ana", "ROBOFAEL_DADOS": str(tmp_path), "ROBOFAEL_VOZ": "x",
                                  "ROBOFAEL_MODELO": "claude-sonnet-5-5", "ROBOFAEL_CACHE": "",
                                  "ROBOFAEL_ASSISTENTE": "Jarvis"})
    assert c.nome_assistente == "Jarvis"
    assert Configuracao.do_ambiente({"ROBOFAEL_FRASE_ATIVACAO": "ei Jarvis"}).frase_ativacao == "ei Jarvis"
    assert Configuracao.do_ambiente({"ROBOFAEL_ATIVACAO": "0"}).ativacao_por_voz is False
    assert (c.nome_usuario, c.voz_padrao, c.modelo) == ("Ana", "x", "claude-sonnet-5-5")
    assert c.arquivo_perfil_voz == tmp_path / "perfil_voz.json"
    assert c.pasta_cache == RAIZ_PROJETO / ".cache"  # vazio = padrão


def test_variaveis_com_nome_antigo_ainda_valem_com_aviso(tmp_path, caplog):
    c = Configuracao.do_ambiente({"EUROBO_USUARIO": "Ana", "EUROBO_DADOS": str(tmp_path), "EUROBO_ATIVACAO": "0"})
    assert (c.nome_usuario, c.pasta_dados, c.ativacao_por_voz) == ("Ana", tmp_path, False)
    assert "EUROBO_DADOS está obsoleta; use ROBOFAEL_DADOS" in caplog.text


def test_nome_novo_tem_prioridade_sobre_o_antigo(caplog):
    c = Configuracao.do_ambiente({"ROBOFAEL_USUARIO": "Ana", "EUROBO_USUARIO": "Bia"})
    assert c.nome_usuario == "Ana"
    assert "obsoleta" not in caplog.text


def test_configuracao_e_imutavel():
    c = Configuracao.do_ambiente({})
    with pytest.raises(AttributeError):
        c.nome_usuario = "outro"  # type: ignore[misc]
    assert isinstance(c.pasta_assets, Path)


def test_todo_estado_tem_cor_e_rotulo():
    assert set(CORES) == set(ROTULOS) == set(Estado)


def test_conversao_e_mistura_de_cores():
    assert rgb_para_hex(hex_para_rgb("#00e5ff")) == "#00e5ff"
    assert rgb_para_hex((300, -5, 127.6)) == "#ff0080"  # satura nos limites
    assert misturar("#ffffff", "#000000", 0.5) == "#808080"


def test_transicao_de_cor_converge_suavemente():
    atual, alvo = hex_para_rgb("#000000"), hex_para_rgb("#ffffff")
    passos = []
    for _ in range(30):
        atual = aproximar(atual, alvo, 0.2)
        passos.append(atual[0])
    assert passos == sorted(passos) and passos[-1] == pytest.approx(255, abs=1)
