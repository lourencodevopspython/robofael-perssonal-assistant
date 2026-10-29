"""Modelo de linguagem local (Ollama), com o modo offline como primeira e última camada.

Modelos pequenos rodando no processador são bons para conversar, mas pouco confiáveis para
escolher ferramentas: em testes com o llama3.2:3b, "me conta uma curiosidade" abriu o navegador e
"estou cansado" listou as tarefas. Por isso a resposta é montada em camadas:

1. comandos que o modo offline reconhece ("anota tarefa…", "que horas são", "abre o navegador")
   são atendidos por ele: na hora e sempre do mesmo jeito;
2. pedidos de agenda em linguagem livre ("amanhã às 9 me lembra da reunião") vão ao modelo com
   ferramentas SEGURAS: criar e consultar; concluir, remover e abrir programas ficam só com os
   comandos explícitos da camada 1;
3. o resto é conversa: vai ao modelo sem ferramentas, com o texto em streaming (~1 s até a
   primeira palavra, contra 6–10 s quando há ferramentas);
4. se o Ollama não responde, a fala é atendida pelo modo offline, exatamente como antes, e o
   Ollama só é tentado de novo depois de ESPERA_APOS_FALHA_S.

Usa só a biblioteca padrão (HTTP + JSON linha a linha): nenhuma dependência nova."""

from __future__ import annotations

import contextlib
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Generator, Iterator
from datetime import datetime
from typing import Any

from robofael.adaptadores.ferramentas import FERRAMENTAS, EntradaInvalida, ExecutorFerramentas
from robofael.adaptadores.offline import ModeloOffline
from robofael.dominio.linguagem import descrever_agora, pede_agenda, pede_nova_conversa
from robofael.i18n import Tradutor
from robofael.portas import ModeloDisponivel, ProvedorIndisponivel

log = logging.getLogger(__name__)

# Criar e consultar: um engano do modelo aqui é inofensivo (e visível no painel)
FERRAMENTAS_LOCAIS = frozenset({"adicionar_tarefa", "listar_tarefas", "criar_lembrete", "listar_lembretes",
                                "consultar_historico"})
MAX_RODADAS = 4
ESPERA_APOS_FALHA_S = 30.0
MANTER_CARREGADO = "30m"  # o modelo fica na memória entre as falas (carregar leva segundos)
# As mesmas opções no pré-carregamento e na conversa: mudar num_ctx faz o Ollama recarregar o modelo.
# num_predict limita a resposta (é falada: curta), o que também limita o pior caso no processador.
OPCOES = {"num_ctx": 4096, "num_predict": 200, "temperature": 0.6}
OPCOES_FERRAMENTAS = {**OPCOES, "temperature": 0.0}  # chamadas de ferramenta: JSON estável
OPCOES_DOCUMENTO = {**OPCOES, "num_predict": 1500}  # "gerar doc": texto longo (num_predict não recarrega o modelo)
MAX_MENSAGENS_LOCAL = 16  # no processador, cada mensagem a mais no contexto atrasa a primeira palavra
_MARKDOWN = re.compile(r"[*#`]+")


_GRUPOS_FERRAMENTAS = (
    (re.compile(r"lembr|avis|remind|alert", re.I), ("criar_lembrete", "listar_lembretes")),
    (re.compile(r"tarefa|anot|pendente|task|to.?do", re.I), ("adicionar_tarefa", "listar_tarefas")),
    (re.compile(r"\b(fiz|feito|conclu|realizei|terminei|did|done|finished)\b", re.I), ("consultar_historico",)),
    (re.compile(r"agenda|compromisso|reuni|schedul|appointment|meeting", re.I),
     ("criar_lembrete", "listar_lembretes", "listar_tarefas")),
)


class OllamaIndisponivel(ConnectionError):
    """Servidor fora do ar, recusou a conexão ou não respondeu a tempo."""


class ClienteOllama:
    """API HTTP do Ollama (https://github.com/ollama/ollama/blob/main/docs/api.md)."""

    def __init__(self, url: str = "http://localhost:11434", timeout_s: float = 120.0):
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s

    def _post(self, caminho: str, corpo: dict, timeout_s: float | None = None) -> Any:
        requisicao = urllib.request.Request(f"{self.url}{caminho}", json.dumps(corpo).encode(),
                                            {"Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(requisicao, timeout=timeout_s or self.timeout_s)
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Ollama respondeu {e.code}: {e.read().decode(errors='replace')[:200]}") from e
        except (urllib.error.URLError, OSError) as e:
            raise OllamaIndisponivel(f"{self.url}: {e}") from e

    def modelos(self) -> list[str]:
        try:
            with urllib.request.urlopen(f"{self.url}/api/tags", timeout=3) as r:
                return [m["name"] for m in json.load(r).get("models", [])]
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise OllamaIndisponivel(f"{self.url}: {e}") from e

    def informacoes(self, modelo: str) -> dict:
        with self._post("/api/show", {"model": modelo}, timeout_s=10) as r:
            return dict(json.load(r))

    def capacidades(self, modelo: str) -> list[str]:
        return list(self.informacoes(modelo).get("capabilities") or [])

    def aquecer(self, modelo: str) -> None:
        """Carrega o modelo na memória antes da primeira fala (chamar em segundo plano)."""
        try:
            with self._post("/api/generate", {"model": modelo, "keep_alive": MANTER_CARREGADO,
                                               "options": OPCOES}) as r:
                r.read()
        except Exception as e:  # só uma otimização: a primeira fala carrega o modelo de qualquer jeito
            log.debug("Não consegui pré-carregar o modelo local: %s", e)

    def conversar(self, corpo: dict) -> Generator[dict, None, None]:
        """Resposta em streaming: um objeto JSON por linha, até `done`."""
        with self._post("/api/chat", {**corpo, "stream": True}) as resposta:
            try:
                for linha in resposta:
                    if not linha.strip():
                        continue
                    pedaco = json.loads(linha)
                    if "error" in pedaco:
                        raise RuntimeError(f"Ollama: {pedaco['error']}")
                    yield pedaco
                    if pedaco.get("done"):
                        return
            except (TimeoutError, ConnectionError) as e:
                raise OllamaIndisponivel(f"{self.url}: {e}") from e


def escolher_modelo(cliente: ClienteOllama, preferido: str) -> str | None:
    """O modelo configurado, se instalado; senão o primeiro instalado que aceita ferramentas."""
    instalados = cliente.modelos()
    for nome in (preferido, f"{preferido}:latest"):
        if nome in instalados:
            return nome
    for nome in instalados:
        with contextlib.suppress(Exception):
            if "tools" in cliente.capacidades(nome):
                log.info("Modelo local %s não está instalado; usando %s", preferido, nome)
                return nome
    return None


class CatalogoOllama:
    """Modelos instalados no Ollama que servem a este assistente: conversam e chamam ferramentas."""

    provedor = "ollama"

    def __init__(self, cliente: ClienteOllama):
        self.cliente = cliente

    def modelos(self) -> list[ModeloDisponivel]:
        try:
            instalados = self.cliente.modelos()
        except OllamaIndisponivel as e:
            raise ProvedorIndisponivel("modelos.ollama_fora", url=self.cliente.url) from e
        compativeis = []
        for nome in instalados:
            try:
                info = self.cliente.informacoes(nome)
            except Exception as e:  # um modelo com problema não esconde os outros
                log.debug("Não consegui ler o modelo local %s: %s", nome, e)
                continue
            if {"completion", "tools"} <= set(info.get("capabilities") or []):
                compativeis.append(ModeloDisponivel(nome, (info.get("details") or {}).get("parameter_size", "")))
        return compativeis


def _esquemas_locais() -> list[dict]:
    """Só a primeira frase de cada descrição: no processador, cada token do pedido atrasa a resposta."""
    return [{"type": "function", "function": {"name": f["name"], "description": f["description"].split(". ")[0],
                                              "parameters": f["input_schema"]}}
            for f in FERRAMENTAS if f["name"] in FERRAMENTAS_LOCAIS]


def _chamada_escrita_como_texto(texto: str) -> tuple[str, list[dict]]:
    """Recupera uma chamada de ferramenta que o modelo escreveu como JSON no texto. Se o texto parece
    JSON mas não é uma chamada válida, ele é descartado: nunca é lido em voz alta."""
    bruto = texto.strip()
    if not bruto.startswith("{"):
        return texto, []
    try:
        dados = json.loads(bruto)
    except ValueError:
        log.debug("Modelo local escreveu JSON inválido no lugar da resposta: %r", bruto[:200])
        return "", []
    argumentos = dados.get("parameters", dados.get("arguments")) if isinstance(dados, dict) else None
    if isinstance(dados, dict) and isinstance(dados.get("name"), str) and isinstance(argumentos, dict):
        return "", [{"function": {"name": dados["name"], "arguments": argumentos}}]
    return "", []


def _coagir(entrada: Any) -> Any:
    """Modelos pequenos mandam "false" e "3" como texto: converte o óbvio antes de validar."""
    if isinstance(entrada, str):
        try:
            entrada = json.loads(entrada)
        except ValueError:
            return entrada
    if not isinstance(entrada, dict):
        return entrada
    convertida = {}
    for campo, valor in entrada.items():
        if isinstance(valor, str) and valor.lower() in ("true", "false"):
            valor = valor.lower() == "true"
        elif isinstance(valor, str) and valor.isdigit() and campo == "id":
            valor = int(valor)
        convertida[campo] = valor
    return convertida


class ModeloOllama:
    online = True  # há um modelo de linguagem (local) atendendo: não é o "modo offline"
    provedor = "ollama"

    def __init__(self, cliente: ClienteOllama, modelo: str, executor: ExecutorFerramentas, reserva: ModeloOffline,
                 nome_usuario: str, nome_assistente: str = "Robofael", tradutor: Tradutor | None = None,
                 relogio: Callable[[], datetime] = datetime.now, max_mensagens: int = MAX_MENSAGENS_LOCAL,
                 monotonico: Callable[[], float] = time.monotonic):
        self.cliente = cliente
        self.modelo = modelo
        self.executor = executor
        self.reserva = reserva
        self.nome_usuario, self.nome_assistente = nome_usuario, nome_assistente
        self.tr = tradutor or Tradutor()
        self.relogio = relogio
        self.max_mensagens = max_mensagens
        self._monotonico = monotonico
        self._indisponivel_ate = 0.0
        self.historico: list[dict] = []
        self._ferramentas = _esquemas_locais()
        self.tr.observar(lambda _idioma: self.reiniciar())  # trocou de idioma: conversa nova

    @property
    def sistema(self) -> str:
        return self.tr("local.instrucoes", usuario=self.nome_usuario, assistente=self.nome_assistente)

    def reiniciar(self) -> None:
        self.historico = []

    def escrever(self, pedido: str) -> Iterator[str]:
        """Texto longo para um documento: sem camadas, ferramentas nem histórico; com markdown."""
        corpo = {"model": self.modelo, "keep_alive": MANTER_CARREGADO, "options": OPCOES_DOCUMENTO,
                 "messages": [{"role": "system", "content": self.tr("doc.instrucoes")},
                              {"role": "user", "content": pedido}]}
        with contextlib.closing(self.cliente.conversar(corpo)) as fluxo:
            for pedaco in fluxo:
                if texto := (pedaco.get("message") or {}).get("content"):
                    yield texto

    def responder(self, fala: str) -> Iterator[str]:
        if pede_nova_conversa(fala):
            self.reiniciar()
            yield self.tr("claude.nova_conversa")
            return
        resposta = self.reserva.tentar(fala)
        if resposta is not None:  # camada 1: comando reconhecido
            self._registrar_troca(fala, resposta)
            yield resposta
            return
        if self._monotonico() < self._indisponivel_ate:  # falhou há pouco: nem tenta
            yield self.reserva.interpretar(fala)
            return
        yield from self._conversar(fala)

    # ---------- Conversa com o modelo ----------
    def _conversar(self, fala: str) -> Iterator[str]:
        if len(self.historico) >= self.max_mensagens:
            self.reiniciar()  # conversa nova em vez de um contexto que não cabe (a agenda persiste)
        inicio = len(self.historico)
        agora = self.tr("claude.agora", agora=descrever_agora(self.relogio(), self.tr.idioma))
        self.historico.append({"role": "user", "content": f"{agora}\n{fala}"})
        ferramentas = self._ferramentas_para(fala)
        progresso = {"falou": False, "concluida": False}
        if ferramentas:
            # No processador, um pedido com ferramentas leva dezenas de segundos: avisa em vez de ficar mudo
            # (o aviso não conta como resposta: se o Ollama falhar, o modo offline ainda responde)
            yield self.tr("local.aguarde") + " "
        try:
            yield from self._rodadas(ferramentas, progresso)
        except OllamaIndisponivel as e:
            self._indisponivel_ate = self._monotonico() + ESPERA_APOS_FALHA_S
            log.warning("Modelo local indisponível (%s); respondendo pelo modo offline", e)
            yield self.tr("local.problema") if progresso["falou"] else self.reserva.interpretar(fala)
        except Exception:
            log.exception("Falha no modelo local")
            yield self.tr("local.problema")
        finally:
            if progresso["concluida"]:
                # Compacta: fica a pergunta (sem o carimbo de hora) e a resposta final, sem as chamadas e os
                # resultados em JSON, que no processador custariam segundos a cada fala seguinte
                self.historico[inicio:] = [{"role": "user", "content": fala}, self.historico[-1]]
            else:
                del self.historico[inicio:]  # descarta a rodada (falha ou interrupção): histórico consistente

    def _ferramentas_para(self, fala: str) -> list[dict] | None:
        """Só as ferramentas do assunto da fala (cada esquema custa tokens e é mais uma chance de erro)."""
        if not pede_agenda(fala):
            return None
        nomes = {nome for padrao, grupo in _GRUPOS_FERRAMENTAS for nome in grupo if padrao.search(fala)}
        return [f for f in self._ferramentas if f["function"]["name"] in (nomes or FERRAMENTAS_LOCAIS)]

    def _rodadas(self, ferramentas: list[dict] | None, progresso: dict[str, bool]) -> Iterator[str]:
        for _ in range(MAX_RODADAS):
            corpo = {"model": self.modelo, "keep_alive": MANTER_CARREGADO,
                     "options": OPCOES_FERRAMENTAS if ferramentas else OPCOES,
                     "messages": [{"role": "system", "content": self.sistema}, *self.historico],
                     **({"tools": ferramentas} if ferramentas else {})}
            # Conversa: fala enquanto o modelo escreve. Com ferramentas: espera a resposta inteira, porque
            # modelos pequenos às vezes escrevem a chamada como texto JSON, que não pode ser lido em voz alta.
            texto, chamadas = yield from self._rodada(corpo, transmitir=not ferramentas, progresso=progresso)
            if ferramentas and not chamadas:
                texto, chamadas = _chamada_escrita_como_texto(texto)
            self.historico.append({"role": "assistant", "content": texto,
                                   **({"tool_calls": chamadas} if chamadas else {})})
            if not chamadas:
                if ferramentas:
                    falado = _MARKDOWN.sub("", texto).strip() or self.tr("claude.perdido")
                    progresso["falou"] = True
                    yield falado
                progresso["concluida"] = True
                return
            self.historico.extend(self._executar(c) for c in chamadas)
        yield self.tr("claude.perdido")

    def _rodada(self, corpo: dict, transmitir: bool,
                progresso: dict[str, bool]) -> Generator[str, None, tuple[str, list[dict]]]:
        partes: list[str] = []
        chamadas: list[dict] = []
        with contextlib.closing(self.cliente.conversar(corpo)) as fluxo:  # interromper fecha a conexão
            for pedaco in fluxo:
                mensagem = pedaco.get("message") or {}
                chamadas.extend(mensagem.get("tool_calls") or [])
                texto = mensagem.get("content")
                if not texto:
                    continue
                partes.append(texto)
                if transmitir and (limpo := _MARKDOWN.sub("", texto)):
                    progresso["falou"] = True
                    yield limpo
        return "".join(partes), chamadas

    def _executar(self, chamada: dict) -> dict:
        funcao = chamada.get("function") or {}
        nome = str(funcao.get("name", ""))
        if nome not in FERRAMENTAS_LOCAIS:
            saida: dict = {"erro": f"Ferramenta indisponível: {nome}. Responda sem ela."}
        else:
            try:
                saida = self.executor.executar(nome, _coagir(funcao.get("arguments")))
            except (EntradaInvalida, ValueError) as e:  # o modelo vê o erro e pode corrigir a chamada
                saida = {"erro": str(e)}
        log.debug("Ferramenta local %s -> %s", nome, saida)
        return {"role": "tool", "tool_name": nome, "content": json.dumps(saida, ensure_ascii=False)}

    def _registrar_troca(self, fala: str, resposta: str) -> None:
        """Comandos atendidos pela camada 1 entram no histórico: o modelo sabe do que se falou."""
        self.historico += [{"role": "user", "content": fala}, {"role": "assistant", "content": resposta}]
